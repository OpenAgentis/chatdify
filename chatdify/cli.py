"""chatdify command line interface.

DSL goes to stdout (or ``-o``); progress and logs go to stderr.
Exit codes: 0 success, 1 generation/validation failed, 2 configuration or runtime error.
"""
from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from chatdify import __version__

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_ERROR = 2

DSL_SUFFIXES = (".yml", ".yaml")


class CLIError(Exception):
    """Configuration or usage error, reported without a traceback."""


def _err(message: str = "") -> None:
    print(message, file=sys.stderr, flush=True)


# --------------------------------------------------------------------------- settings


def _apply_settings(args: argparse.Namespace) -> None:
    from chatdify.settings import Settings, configure

    verbose = getattr(args, "verbose", 0) or 0
    if verbose > 0:
        log_to_console: Optional[bool] = True
    elif "log_to_console" in Settings().model_fields_set:
        log_to_console = None
    else:
        # The CLI shows progress lines by default; raw logs only on request.
        log_to_console = False
    overrides: Dict[str, Any] = {
        "llm_model": getattr(args, "model", None),
        "llm_base_url": getattr(args, "base_url", None),
        "generation_mode": getattr(args, "mode", None),
        "max_retries": getattr(args, "max_retries", None),
        "dify_src": getattr(args, "dify_src", None),
        "dify_url": getattr(args, "dify_url", None),
        "log_to_console": log_to_console,
    }
    if verbose > 1:
        overrides["log_level"] = "DEBUG"
    if getattr(args, "no_static", False):
        overrides["dify_static_validation"] = False
    try:
        configure(**overrides)
    except Exception as e:
        raise CLIError(f"invalid configuration: {e}") from e


def _require_llm() -> None:
    from chatdify.settings import CONFIG_FILE, get_settings

    missing = get_settings().missing_llm_fields()
    if missing:
        names = ", ".join(f"CHATDIFY_{m.upper()}" for m in missing)
        raise CLIError(
            f"LLM is not configured (missing {names}).\n"
            f"Run `chatdify init` to write {CONFIG_FILE}, or set the environment variables."
        )


def _progress(args: argparse.Namespace):
    if getattr(args, "quiet", False):
        return None
    from chatdify.progress import ConsoleProgressTracker

    return ConsoleProgressTracker(show_details=(getattr(args, "verbose", 0) or 0) > 0)


def _read_text(value: str, what: str) -> str:
    if value == "-":
        return sys.stdin.read()
    path = Path(value)
    if not path.is_file():
        raise CLIError(f"{what} not found: {value}")
    return path.read_text(encoding="utf-8")


def _write_output(text: str, output: Optional[str]) -> None:
    if output:
        path = Path(output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        _err(f"DSL written to {path}")
    else:
        sys.stdout.write(text if text.endswith("\n") else text + "\n")


def _validation_status_line() -> str:
    from chatdify import dify_compat
    from chatdify.settings import get_settings

    settings = get_settings()
    static = "on" if dify_compat.is_available() else "off"
    dynamic = f"on ({settings.dify_url})" if settings.dynamic_validation_enabled else "off"
    return f"static validation: {static}, dynamic validation: {dynamic}"


def _describe_workflow_model(settings, kind: str) -> str:
    model = settings.workflow_model(kind)
    return f"{model.get('name') or model.get('model')} ({model.get('provider')})"


def _workflow_models_notice() -> Optional[str]:
    """Reminder shown while generated nodes still point at the built-in default models."""
    from chatdify.settings import get_settings

    settings = get_settings()
    defaults = settings.default_workflow_models()
    if not defaults:
        return None
    used = ", ".join(f"{k}: {_describe_workflow_model(settings, k)}" for k in defaults)
    return (f"note: workflow nodes use built-in default models ({used}); set "
            + ", ".join(f"workflow_{k}" for k in defaults)
            + " in config.toml to models available in your Dify (see README, 'Workflow models')")


def _run_header(line: str) -> None:
    _err(line)
    notice = _workflow_models_notice()
    if notice:
        _err(notice)


# --------------------------------------------------------------------------- commands


def _token_text(stats: Dict[str, Any]) -> str:
    from chatdify.services.token_stats import cache_hit_rate

    rate = cache_hit_rate(stats)
    text = f"{int(stats.get('total_tokens', 0) or 0)} tokens"
    return text + (f" ({rate}% of input cached)" if rate is not None else "")


def _finish_run(args: argparse.Namespace, result) -> int:
    if args.json:
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2, default=str))
        if args.output and result.dsl:
            Path(args.output).write_text(result.dsl, encoding="utf-8")
    elif result.dsl:
        _write_output(result.dsl, args.output)

    status = "succeeded" if result.success else "failed"
    tokens = (result.token_stats or {}).get("total", {})
    _err(
        f"{status} after {result.attempts} attempt(s) in {result.duration:.1f}s"
        + (f", {_token_text(tokens)}" if tokens else "")
    )
    for agent in ("planner", "executor", "reviewer"):
        stats = (result.agent_stats or {}).get(agent)
        if stats:
            _err(f"  {agent:<9} {stats.get('duration', 0):.1f}s, {_token_text(stats)}")
    if not result.success and result.last_error and not args.json:
        _err("last error:\n" + result.last_error)
    return EXIT_OK if result.success else EXIT_FAILED


def cmd_generate(args: argparse.Namespace) -> int:
    _require_llm()
    if args.request_file:
        request = _read_text(args.request_file, "request file")
    elif args.request:
        request = args.request
    else:
        raise CLIError("provide a request, e.g. chatdify generate \"translate text into English\"")

    from chatdify import api
    from chatdify.settings import RETRIEVAL_MODES, get_settings

    settings = get_settings()
    if settings.generation_mode in RETRIEVAL_MODES and not settings.embedding_api_key:
        raise CLIError(f"mode {settings.generation_mode} retrieves templates and needs an embedding model "
                       "(CHATDIFY_EMBEDDING_MODEL / _BASE_URL / _API_KEY); use --mode AutoGen otherwise")
    if not args.quiet:
        _run_header(f"mode: {settings.generation_mode}, model: {settings.llm_model}, {_validation_status_line()}")
        if not settings.log_to_console:
            _err(f"logs: {settings.log_dir / 'system.log'} (use -v to print them here)")
    name = args.name or (Path(args.output).stem if args.output else None)
    result = api.generate(request.strip(), name=name, input_files=args.input_file, progress=_progress(args))
    return _finish_run(args, result)


def cmd_fix(args: argparse.Namespace) -> int:
    _require_llm()
    from chatdify import api

    dsl = _read_text(args.dsl, "DSL file")
    feedback = _read_text(args.feedback_file, "feedback file") if args.feedback_file else args.feedback
    if not args.quiet:
        _run_header(_validation_status_line())
    result = api.fix(dsl, feedback=feedback, input_files=args.input_file, progress=_progress(args))
    return _finish_run(args, result)


def cmd_modify(args: argparse.Namespace) -> int:
    _require_llm()
    from chatdify import api

    dsl = _read_text(args.dsl, "DSL file")
    if not args.quiet:
        _run_header(_validation_status_line())
    result = api.modify(dsl, args.instruction, input_files=args.input_file, progress=_progress(args))
    return _finish_run(args, result)


def cmd_chat(args: argparse.Namespace) -> int:
    _require_llm()
    from chatdify.chat import repl
    from chatdify.settings import get_settings

    settings = get_settings()
    dsl = _read_text(args.dsl, "DSL file") if args.dsl else None
    _run_header(f"model: {settings.llm_model}, mode: {settings.generation_mode}, {_validation_status_line()}")
    try:
        return repl.start(
            dsl=dsl,
            dsl_source=args.dsl or "",
            resume=args.resume,
            input_files=args.input_file,
            progress_factory=lambda: _progress(args),
        )
    except ValueError as e:
        raise CLIError(str(e)) from e


def _collect_dsl_files(paths: List[str]) -> List[Path]:
    files: List[Path] = []
    for raw in paths:
        path = Path(raw)
        if path.is_dir():
            files.extend(sorted(p for p in path.rglob("*") if p.suffix in DSL_SUFFIXES and p.is_file()))
        elif path.is_file():
            files.append(path)
        else:
            raise CLIError(f"no such file or directory: {raw}")
    if not files:
        raise CLIError("no .yml/.yaml files found")
    return files


def cmd_validate(args: argparse.Namespace) -> int:
    from chatdify import api, dify_compat

    if args.dynamic:
        _require_llm()
    files = _collect_dsl_files(args.paths)
    static_on = dify_compat.is_available()
    if not static_on and not args.dynamic:
        raise CLIError(
            "static validation is unavailable:\n"
            f"{dify_compat.unavailable_reason()}\n"
            "See `chatdify dify status`."
        )

    reports = []
    failed = 0
    for path in files:
        report = api.validate(path.read_text(encoding="utf-8"), dynamic=args.dynamic, request=args.request,
                              input_files=args.input_file)
        reports.append((path, report))
        if not report.valid:
            failed += 1
        if not args.json:
            mark = "ok  " if report.valid else "FAIL"
            print(f"{mark} {path}")
            if not report.valid:
                for line in report.summary().splitlines():
                    print(f"     {line}")
            if report.skipped_reason and args.dynamic:
                print(f"     note: {report.skipped_reason}")

    if args.json:
        print(json.dumps([{"file": str(p), **r.to_dict()} for p, r in reports], ensure_ascii=False, indent=2))
    else:
        _err(f"{len(files) - failed}/{len(files)} valid")
    return EXIT_OK if failed == 0 else EXIT_FAILED


def cmd_eval(args: argparse.Namespace) -> int:
    _require_llm()
    from chatdify.evaluation import load_cases, run_eval
    from chatdify.progress import ConsoleProgressTracker

    cases_path = Path(args.cases)
    if not cases_path.is_file():
        raise CLIError(f"case file not found: {cases_path}")
    cases = load_cases(
        cases_path,
        args.task,
        data_dir=Path(args.data_dir) if args.data_dir else None,
        dsl_dir=Path(args.dsl_dir) if args.dsl_dir else None,
        select=args.case,
    )
    if args.limit:
        cases = cases[: args.limit]
    if not cases:
        raise CLIError("no cases selected")

    _run_header(f"running {len(cases)} {args.task} case(s); {_validation_status_line()}")

    def progress_factory(case):
        if args.quiet:
            return None
        return ConsoleProgressTracker(show_details=False, max_message_len=160)

    def on_case_done(case, record, index, total):
        _err(f"[{index}/{total}] {record['status']:<9} {case.key} ({record.get('duration', 0):.0f}s)")

    summary = run_eval(
        cases,
        args.task,
        Path(args.output_dir),
        with_feedback=not args.no_feedback,
        progress_factory=progress_factory,
        on_case_done=on_case_done,
    )
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        from tabulate import tabulate

        rows = [
            ["cases", summary["total_cases"]],
            ["succeeded", summary["succeeded"]],
            ["failed", summary["failed"]],
            ["errored", summary["errored"]],
            ["success rate", f"{summary['success_rate']}%"],
            ["avg duration (s)", summary["avg_duration"]],
            ["total tokens", summary["token_totals"].get("total_tokens", 0)],
            ["input / cached tokens", f"{summary['token_totals'].get('input_tokens', 0)} / "
                                      f"{summary['token_totals'].get('cached_tokens', 0)}"],
            ["cache hit rate", "–" if summary.get("cache_hit_rate") is None else f"{summary['cache_hit_rate']}%"],
        ]
        rows += [[k.replace("_", " "), v] for k, v in summary["success_by_attempt"].items()]
        print(tabulate(rows, tablefmt="simple"))
        if summary.get("by_round"):
            print("\nallowing at most N rounds:")
            print(tabulate(
                [[r["round"], f"{r['success_rate']}%", r["avg_duration"], r["avg_tokens"],
                  "–" if r.get("cache_hit_rate") is None else f"{r['cache_hit_rate']}%"] for r in summary["by_round"]],
                headers=["N", "success rate", "avg duration (s)", "avg tokens", "cache hit rate"],
                tablefmt="simple",
            ))
        _err(f"results: {summary['output_dir']}")
    return EXIT_OK


def cmd_dify_status(args: argparse.Namespace) -> int:
    from chatdify import dify_compat
    from chatdify.settings import WORKFLOW_MODEL_KINDS, get_settings

    settings = get_settings()
    located = dify_compat.locate_dify(settings.dify_src, settings.dify_cache_dir, settings.dify_version)
    info: Dict[str, Any] = {
        "dify_version": settings.dify_version,
        "searched": [{"source": s, "path": str(p)} for s, p in located.tried],
        "found": None,
        "static_validation": False,
        "reason": None,
        "dynamic_validation": settings.dynamic_validation_enabled,
        "dify_url": settings.dify_url,
    }
    if located.info:
        info["found"] = {
            "path": str(located.info.root),
            "version": located.info.version,
            "source": located.info.source,
            "version_matches": located.info.version_matches,
        }
    info["static_validation"] = dify_compat.is_available()
    info["reason"] = None if info["static_validation"] else dify_compat.unavailable_reason()
    defaults = settings.default_workflow_models()
    info["workflow_models"] = {
        kind: {**settings.workflow_model(kind), "source": "default" if kind in defaults else "config"}
        for kind in WORKFLOW_MODEL_KINDS
    }

    if args.json:
        print(json.dumps(info, ensure_ascii=False, indent=2))
        return EXIT_OK

    print(f"dify_version: {settings.dify_version}")
    if located.info:
        tag = "" if located.info.version_matches else f"  (differs from dify_version {settings.dify_version})"
        print(f"Dify source: {located.info.root} [{located.info.version or 'unknown'}] via {located.info.source}{tag}")
    else:
        print("Dify source: not found; searched:")
        for s, p in located.tried:
            print(f"  - {s}: {p}")
    print(f"static validation: {'available' if info['static_validation'] else 'unavailable'}")
    if info["reason"] and located.info:
        print(f"  reason: {info['reason']}")
    print(f"dynamic validation: {'on (' + settings.dify_url + ')' if settings.dynamic_validation_enabled else 'off'}")
    print("workflow models (must exist in your Dify):")
    for kind in WORKFLOW_MODEL_KINDS:
        print(f"  {kind:<10} {_describe_workflow_model(settings, kind)}"
              + ("  [default]" if kind in defaults else ""))
    notice = _workflow_models_notice()
    if notice:
        _err(notice)
    return EXIT_OK


def cmd_dify_fetch(args: argparse.Namespace) -> int:
    from chatdify.dify_compat.fetch import DifyFetchError, fetch_dify
    from chatdify.settings import get_settings

    settings = get_settings()
    try:
        path = fetch_dify(
            args.version or settings.dify_version,
            settings.dify_cache_dir,
            git_url=args.git_url,
            tarball_url=args.tarball_url,
            force=args.force,
            log=_err,
        )
    except DifyFetchError as e:
        raise CLIError(str(e)) from e
    print(path)
    from chatdify.dify_compat.locator import SUPPORTED_DIFY_VERSIONS, layout_supported

    if not layout_supported(path):
        _err(
            f"warning: static validation does not support this Dify release's code layout yet "
            f"(supported: Dify {SUPPORTED_DIFY_VERSIONS}); see 'Upgrading Dify' in the README"
        )
        return EXIT_OK
    _err('static validation also needs the extra; in the chatdify source directory run: pip install -e ".[dify]"')
    return EXIT_OK


def _toml_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, dict):
        items = ", ".join(f"{json.dumps(str(k))} = {_toml_value(v)}" for k, v in value.items())
        return "{ " + items + " }" if items else "{}"
    if isinstance(value, list):
        return "[" + ", ".join(_toml_value(v) for v in value) + "]"
    return json.dumps(str(value), ensure_ascii=False)


def _write_config(path: Path, values: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# chatdify configuration, written by `chatdify init`", ""]
    lines += [f"{k} = {_toml_value(v)}" for k, v in values.items() if v not in (None, "")]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.chmod(path, 0o600)


def _ask(prompt: str, default: Optional[str] = None, secret: bool = False) -> Optional[str]:
    suffix = f" [{default}]" if default and not secret else ""
    reader = getpass.getpass if secret else input
    answer = reader(f"{prompt}{suffix}: ").strip()
    return answer or default


def cmd_init(args: argparse.Namespace) -> int:
    import tomllib

    from chatdify.settings import CONFIG_FILE, DEFAULT_WORKFLOW_MODELS

    existing: Dict[str, Any] = {}
    if CONFIG_FILE.exists():
        existing = tomllib.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        if not args.force and not sys.stdin.isatty():
            raise CLIError(f"{CONFIG_FILE} exists; use --force to overwrite")

    values = dict(existing)
    workflow_llm = dict(existing.get("workflow_llm") or {})
    if (args.api_key or args.base_url or args.model
            or args.workflow_llm_provider or args.workflow_llm_name):
        # non-interactive
        for key, val in (("llm_base_url", args.base_url), ("llm_model", args.model),
                         ("llm_api_key", args.api_key), ("dify_url", args.dify_url),
                         ("dify_src", args.dify_src)):
            if val:
                values[key] = str(val)
        for key, val in (("provider", args.workflow_llm_provider), ("name", args.workflow_llm_name)):
            if val:
                workflow_llm[key] = val
    else:
        if not sys.stdin.isatty():
            raise CLIError("no terminal; pass --base-url/--model/--api-key")
        print(f"Writing {CONFIG_FILE}. Press Enter to keep the value in brackets.\n")
        values["llm_base_url"] = _ask("OpenAI-compatible base URL", existing.get("llm_base_url"))
        values["llm_model"] = _ask("Model name", existing.get("llm_model"))
        api_key = _ask("API key (input hidden, Enter to keep)", secret=True)
        if api_key:
            values["llm_api_key"] = api_key
        dify_url = _ask("Dify URL for dynamic validation (optional, e.g. http://localhost)",
                        existing.get("dify_url"))
        if dify_url:
            values["dify_url"] = dify_url
            values["dify_email"] = _ask("Dify console email", existing.get("dify_email"))
            password = _ask("Dify console password (input hidden, Enter to keep)", secret=True)
            if password:
                values["dify_password"] = password
        dify_src = _ask("Path to a Dify source checkout (optional)", existing.get("dify_src"))
        if dify_src:
            values["dify_src"] = dify_src
        print("\nGenerated workflows call models configured in your Dify (Settings > Model Provider).")
        default_llm = DEFAULT_WORKFLOW_MODELS["llm"]
        workflow_llm["provider"] = _ask("Dify model provider for LLM nodes",
                                        workflow_llm.get("provider", default_llm["provider"]))
        workflow_llm["name"] = _ask("Dify model name for LLM nodes",
                                    workflow_llm.get("name", default_llm["name"]))

    if workflow_llm:
        values["workflow_llm"] = workflow_llm
    else:
        values.pop("workflow_llm", None)
    _write_config(CONFIG_FILE, values)
    _err(f"saved {CONFIG_FILE} (mode 600)")
    _err("vision LLM, rerank and embedding models for generated workflows are set with "
         "workflow_vision_llm / workflow_rerank / workflow_embedding; check them with `chatdify dify status`")
    return EXIT_OK


def cmd_config(args: argparse.Namespace) -> int:
    from chatdify.settings import CONFIG_FILE, WORKFLOW_MODEL_KINDS, get_settings

    settings = get_settings()
    data = settings.model_dump(mode="json")
    for key in ("llm_api_key", "embedding_api_key", "dify_password"):
        if data.get(key):
            data[key] = data[key][:4] + "***"
    defaults = settings.default_workflow_models()
    for kind in WORKFLOW_MODEL_KINDS:
        data[f"workflow_{kind}"] = settings.workflow_model(kind)
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        print(f"# config file: {CONFIG_FILE} ({'found' if CONFIG_FILE.exists() else 'missing'})")
        for k, v in data.items():
            tag = "  # default" if k.startswith("workflow_") and k[len("workflow_"):] in defaults else ""
            print(f"{k} = {v}{tag}")
    return EXIT_OK


# --------------------------------------------------------------------------- parser


def build_parser() -> argparse.ArgumentParser:
    from chatdify.settings import GENERATION_MODES

    common = argparse.ArgumentParser(add_help=False)
    g = common.add_argument_group("common options")
    g.add_argument("-v", "--verbose", action="count", default=0, help="show step details and logs (-vv: debug)")
    g.add_argument("-q", "--quiet", action="store_true", help="hide progress output")
    g.add_argument("--json", action="store_true", help="machine-readable JSON on stdout")
    g.add_argument("--dify-src", metavar="PATH", help="Dify source checkout used for static validation")
    g.add_argument("--dify-url", metavar="URL", help="Dify instance used for dynamic validation")
    g.add_argument("--no-static", action="store_true", help="skip static validation against Dify")

    llm = argparse.ArgumentParser(add_help=False)
    lg = llm.add_argument_group("model options")
    lg.add_argument("--model", help="model name")
    lg.add_argument("--base-url", help="OpenAI-compatible base URL")
    lg.add_argument("--max-retries", type=int, help="generate/validate rounds (default 3)")

    io = argparse.ArgumentParser(add_help=False)
    io.add_argument("-o", "--output", metavar="FILE", help="write DSL to FILE instead of stdout")
    io.add_argument("--input-file", action="append", metavar="FILE",
                    help="test input file for dynamic validation (repeatable)")

    parser = argparse.ArgumentParser(
        prog="chatdify",
        description="Generate, repair and modify Dify workflow DSL with LLMs.",
    )
    parser.add_argument("--version", action="version", version=f"chatdify {__version__}")
    sub = parser.add_subparsers(dest="command", metavar="<command>")

    p = sub.add_parser("init", help="write ~/.chatdify/config.toml")
    p.add_argument("--base-url")
    p.add_argument("--model")
    p.add_argument("--api-key")
    p.add_argument("--dify-url")
    p.add_argument("--dify-src")
    p.add_argument("--workflow-llm-provider", metavar="PROVIDER",
                   help="Dify model provider for LLM nodes in generated workflows, e.g. langgenius/openai/openai")
    p.add_argument("--workflow-llm-name", metavar="MODEL", help="Dify model name for those nodes, e.g. gpt-4o")
    p.add_argument("--force", action="store_true", help="overwrite without asking")
    p.set_defaults(func=cmd_init, skip_settings=True)

    p = sub.add_parser("generate", parents=[common, llm, io], help="generate a workflow from a request")
    p.add_argument("request", nargs="?", help="natural-language description of the workflow")
    p.add_argument("-f", "--request-file", metavar="FILE", help="read the request from FILE ('-' for stdin)")
    p.add_argument("--mode", choices=list(GENERATION_MODES), help="generation strategy (default AutoGen)")
    p.add_argument("--name", help="Dify app name (default: the -o file name)")
    p.set_defaults(func=cmd_generate)

    p = sub.add_parser("fix", parents=[common, llm, io], help="repair a broken DSL")
    p.add_argument("dsl", help="DSL file ('-' for stdin)")
    p.add_argument("--feedback", help="error message or hint, e.g. from a failed Dify run")
    p.add_argument("--feedback-file", metavar="FILE")
    p.set_defaults(func=cmd_fix)

    p = sub.add_parser("modify", parents=[common, llm, io], help="change a DSL according to an instruction")
    p.add_argument("dsl", help="DSL file ('-' for stdin)")
    p.add_argument("instruction", help="what to change")
    p.set_defaults(func=cmd_modify)

    p = sub.add_parser("chat", parents=[common, llm], help="build and change a workflow in a conversation")
    p.add_argument("dsl", nargs="?", help="start from this DSL file")
    p.add_argument("--resume", nargs="?", const="latest", metavar="SESSION_DIR",
                   help="continue the last session (or the given session directory)")
    p.add_argument("--mode", choices=list(GENERATION_MODES), help="generation strategy (default AutoGen)")
    p.add_argument("--input-file", action="append", metavar="FILE",
                   help="test input file for dynamic validation (repeatable)")
    p.set_defaults(func=cmd_chat)

    p = sub.add_parser("validate", parents=[common, llm], help="validate DSL files or directories")
    p.add_argument("paths", nargs="+", metavar="PATH")
    p.add_argument("--dynamic", action="store_true", help="also import and run on the Dify instance")
    p.add_argument("--request", help="original request, used to judge run results with --dynamic")
    p.add_argument("--input-file", action="append", metavar="FILE")
    p.set_defaults(func=cmd_validate)

    p = sub.add_parser("eval", parents=[common, llm], help="run a benchmark suite")
    p.add_argument("task", choices=["generation", "bugfix"])
    p.add_argument("cases", help="case file (YAML)")
    p.add_argument("--data-dir", help="input files directory (default: <cases dir>/data)")
    p.add_argument("--dsl-dir", help="bugfix DSL directory (default: <cases dir>/bugfix_dsl)")
    p.add_argument("--case", action="append", metavar="CATEGORY[/NAME]", help="only run matching cases")
    p.add_argument("--limit", type=int, help="run at most N cases")
    p.add_argument("--no-feedback", action="store_true", help="bugfix: hide the recorded error feedback")
    p.add_argument("--mode", choices=list(GENERATION_MODES))
    p.add_argument("-o", "--output-dir", default="eval_results", help="results directory (default ./eval_results)")
    p.set_defaults(func=cmd_eval)

    dify_parser = sub.add_parser("dify", help="manage the Dify source used for static validation")
    dsub = dify_parser.add_subparsers(dest="dify_command", metavar="<action>")
    dp = dsub.add_parser("status", parents=[common], help="show which Dify source is used")
    dp.set_defaults(func=cmd_dify_status, skip_settings=False)
    dp = dsub.add_parser("fetch", parents=[common], help="download Dify into ~/.chatdify/dify/<version>")
    dp.add_argument("--version", help="Dify tag (default: the dify_version setting)")
    dp.add_argument("--git-url", help="git mirror URL")
    dp.add_argument("--tarball-url", help="tarball URL template with {version}")
    dp.add_argument("--force", action="store_true", help="re-download if present")
    dp.set_defaults(func=cmd_dify_fetch, skip_settings=False)
    dify_parser.set_defaults(func=lambda a: (dify_parser.print_help(), EXIT_ERROR)[1], skip_settings=True)

    p = sub.add_parser("config", parents=[common], help="show the effective configuration (secrets masked)")
    p.set_defaults(func=cmd_config)

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return EXIT_ERROR

    try:
        if not getattr(args, "skip_settings", False):
            _apply_settings(args)
        return args.func(args)
    except CLIError as e:
        _err(f"error: {e}")
        return EXIT_ERROR
    except KeyboardInterrupt:
        _err("interrupted")
        return 130
    except Exception as e:
        if (getattr(args, "verbose", 0) or 0) > 1:
            raise
        from chatdify.settings import get_settings

        _err(f"error: {type(e).__name__}: {e}")
        _err(f"(run with -vv for a traceback; logs: {get_settings().log_dir / 'system.log'})")
        return EXIT_ERROR


if __name__ == "__main__":
    sys.exit(main())
