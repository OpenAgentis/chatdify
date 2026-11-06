"""Terminal loop for `chatdify chat`."""
from __future__ import annotations

import shlex
import sys
from pathlib import Path
from typing import Any, Callable, List, Optional, TextIO

from chatdify import api
from chatdify.chat import summary
from chatdify.chat.agent import ChatAgent
from chatdify.chat.session import ChatSession, Outcome
from chatdify.settings import WORKFLOW_MODEL_KINDS, get_settings
from chatdify.utils.exceptions import ChatDifyError

HELP = """Type what you want in plain language, e.g. "build a workflow that translates text",
"remove the polishing step", "why did it fail?". Slash commands run directly:

  /show [yaml|errors|NODE]   current workflow: overview, full DSL, last problems, one node
  /diff [A [B]]              node changes between versions (default: previous -> current)
  /history                   versions of this session
  /undo                      go back to the previous version
  /new                       start over (earlier versions stay in the session directory)
  /load FILE                 continue from a DSL file
  /save [FILE]               write the current version to FILE
  /attach FILE               test input file for dynamic validation
  /generate TEXT | /modify TEXT | /fix [TEXT]   run without asking the assistant
  /validate [dynamic]        static validation, or also run it on Dify
  /publish [new]             import into Dify; later calls overwrite the same app unless 'new'
  /models                    models the generated nodes use (must exist in your Dify)
  /quit                      exit; resume later with `chatdify chat --resume`

Ctrl+C cancels the running step and keeps the current version."""


def format_outcome(outcome: Outcome, session: ChatSession) -> str:
    if not outcome.version:
        text = "✗ no usable DSL was produced; current version unchanged"
        return text + (f"\n  {outcome.last_error.splitlines()[0][:300]}" if outcome.last_error else "")
    mark = "✓" if outcome.success else "✗"
    lines = [f"v{outcome.version.number} {mark}  {outcome.rounds} round(s), {outcome.duration:.0f}s, "
             f"{outcome.tokens} tokens"
             + (f" ({outcome.cache_hit_rate}% of input cached)" if outcome.cache_hit_rate is not None else "")]
    if outcome.changes:
        lines.append("  " + summary.diff_text(outcome.changes))
    lines += ["  " + line for line in summary.overview(session.dsl_of(outcome.version.number)).splitlines()]
    if not outcome.success and outcome.last_error:
        problems = outcome.last_error.strip().splitlines()
        lines.append("  problems: " + " | ".join(p.strip() for p in problems[:3])[:500])
        lines.append("  /fix to repair, /show errors for details")
    if outcome.published:
        lines.append(f"  synced to Dify: {outcome.published.url}")
    if outcome.publish_error:
        lines.append(f"  Dify sync failed: {outcome.publish_error}")
    return "\n".join(lines)


def format_report(report: api.ValidationReport) -> str:
    checked = [name for name, on in (("static", report.static_checked), ("dynamic", report.dynamic_checked)) if on]
    if report.parse_error:
        return f"✗ {report.summary()}"
    if not checked:
        return f"validation skipped: {report.skipped_reason}"
    head = f"{'✓' if report.valid else '✗'} {' + '.join(checked)} validation {'passed' if report.valid else 'failed'}"
    body = report.summary()
    return head + ("\n  " + "\n  ".join(body.splitlines()[:10]) if body else "")


class ChatRepl:
    def __init__(
        self,
        session: ChatSession,
        agent: ChatAgent,
        *,
        progress_factory: Callable[[], Any] = lambda: None,
        read: Callable[[str], str] = input,
        out: Optional[TextIO] = None,
    ):
        self.session = session
        self.agent = agent
        self.progress_factory = progress_factory
        self.read = read
        self.out = out or sys.stdout

    def say(self, text: str = "") -> None:
        print(text, file=self.out, flush=True)

    def confirm(self, prompt: str) -> bool:
        try:
            return self.read(f"{prompt} [y/N] ").strip().lower() in ("y", "yes")
        except (EOFError, KeyboardInterrupt):
            return False

    def on_event(self, kind: str, name: str, **payload: Any) -> None:
        if kind == "tool_start":
            args = payload.get("args") or {}
            detail = next((str(v) for v in args.values() if v not in (None, "")), "")
            self.say(f"→ {name}" + (f": {' '.join(detail.split())[:200]}" if detail else ""))
        elif kind == "tool_end":
            result = payload.get("result")
            if isinstance(result, Outcome):
                self.say(format_outcome(result, self.session))
            elif isinstance(result, api.ValidationReport):
                self.say(format_report(result))
            elif isinstance(result, api.PublishResult):
                self.say(f"  {'imported' if result.created else 'updated'}: {result.url}")
            elif "error" in (payload.get("content") or {}):
                self.say(f"  {payload['content']['error']}")

    def prompt(self) -> str:
        return f"chatdify[v{self.session.current}]> " if self.session.current else "chatdify> "

    def run(self) -> int:
        self.say(f"chatdify chat — describe the app you want, or /help. Session: {self.session.directory}")
        if self.session.current:
            self.say(self.session.state_text())
        while True:
            try:
                line = self.read(self.prompt())
            except EOFError:
                self.say()
                break
            except KeyboardInterrupt:
                self.say("\n(use /quit to exit)")
                continue
            line = line.strip()
            if not line:
                continue
            try:
                if not self.handle(line):
                    break
            except KeyboardInterrupt:
                self.say(f"\ncancelled; still at v{self.session.current}" if self.session.current else "\ncancelled")
            except (ValueError, OSError, ChatDifyError) as e:
                self.say(f"error: {e}")
            except Exception as e:
                self.say(f"error: {type(e).__name__}: {e} (details in {get_settings().log_dir / 'system.log'})")
        self.say(f"session saved in {self.session.directory}; resume with `chatdify chat --resume`")
        return 0

    def handle(self, line: str) -> bool:
        """Process one input line; returns False to quit."""
        if not line.startswith("/"):
            reply = self.agent.handle(line)
            if reply:
                self.say(reply)
            return True
        command, _, rest = line[1:].partition(" ")
        rest = rest.strip()
        handler = getattr(self, f"cmd_{command.lower()}", None)
        if command.lower() in ("quit", "exit", "q"):
            return False
        if not handler:
            self.say(f"unknown command /{command}; /help lists them")
            return True
        handler(rest)
        return True

    # ------------------------------------------------------------------ commands

    def cmd_help(self, rest: str) -> None:
        self.say(HELP)

    def cmd_show(self, rest: str) -> None:
        if not self.session.current:
            raise ValueError("no workflow yet")
        if rest == "yaml":
            self.say(self.session.dsl.rstrip())
        elif rest == "errors":
            version = self.session.version
            self.say(version.last_error or ("no problems recorded" if version.success else "not validated yet"))
        elif rest:
            self.say(summary.node_detail(self.session.dsl, rest) or f"no node with id or title {rest!r}")
        else:
            self.say(self.session.state_text())

    def cmd_diff(self, rest: str) -> None:
        numbers = [int(x.lstrip("v")) for x in rest.split()] if rest else []
        current = self.session.version
        if not current:
            raise ValueError("no workflow yet")
        new = numbers[1] if len(numbers) > 1 else (numbers[0] if numbers else current.number)
        old = numbers[0] if len(numbers) > 1 else (self.session.get(new).parent if self.session.get(new) else None)
        if not old or not self.session.get(old) or not self.session.get(new):
            raise ValueError("give two existing versions, e.g. /diff 1 3")
        changes = summary.diff(self.session.dsl_of(old), self.session.dsl_of(new))
        self.say(f"v{old} -> v{new}: {summary.diff_text(changes)}")

    def cmd_history(self, rest: str) -> None:
        if not self.session.versions:
            self.say("no versions yet")
        for v in self.session.versions:
            mark = {True: "✓", False: "✗", None: "·"}[v.success]
            here = " <- current" if v.number == self.session.current else ""
            dify = " (in Dify)" if v.number == self.session.published_version else ""
            self.say(f"v{v.number} {mark} {v.action:<8} {' '.join(v.instruction.split())[:80]}{dify}{here}")

    def cmd_undo(self, rest: str) -> None:
        version = self.session.undo()
        if not version:
            raise ValueError("nothing to undo")
        note = ""
        if self.session.app_id and self.session.published_version != version.number:
            note = f" (Dify still has v{self.session.published_version}; /publish to sync)"
        self.say(f"back to v{version.number}{note}")

    def cmd_new(self, rest: str) -> None:
        self.session.reset()
        self.say("started over; describe the new app")

    def cmd_load(self, rest: str) -> None:
        path = Path(rest).expanduser()
        if not path.is_file():
            raise ValueError(f"file not found: {rest}")
        version = self.session.load_dsl(path.read_text(encoding="utf-8"), str(path))
        self.say(f"loaded v{version.number} from {path}\n{summary.overview(self.session.dsl)}")

    def cmd_save(self, rest: str) -> None:
        if not self.session.current:
            raise ValueError("no workflow yet")
        name = summary.describe(self.session.dsl).get("name") or "workflow"
        path = self.session.save(Path(rest).expanduser() if rest else Path(f"{name}_v{self.session.current}.yml"))
        self.say(f"saved v{self.session.current} to {path}")

    def cmd_attach(self, rest: str) -> None:
        for item in shlex.split(rest) or [""]:
            self.say(f"attached {self.session.attach(item)}")

    def cmd_generate(self, rest: str) -> None:
        if not rest:
            raise ValueError("usage: /generate <request>")
        self.say(format_outcome(self.session.generate(rest, progress=self.progress_factory()), self.session))

    def cmd_modify(self, rest: str) -> None:
        if not rest:
            raise ValueError("usage: /modify <instruction>")
        self.say(format_outcome(self.session.modify(rest, progress=self.progress_factory()), self.session))

    def cmd_fix(self, rest: str) -> None:
        self.say(format_outcome(self.session.fix(rest or None, progress=self.progress_factory()), self.session))

    def cmd_validate(self, rest: str) -> None:
        self.say(format_report(self.session.validate(dynamic=rest in ("dynamic", "--dynamic", "-d"))))

    def cmd_publish(self, rest: str) -> None:
        result = self.session.publish(new=rest == "new")
        self.say(f"{'imported' if result.created else 'updated'} v{self.session.current}: {result.url}"
                 + (f"\n  warning: {result.warning}" if result.warning else ""))

    def cmd_models(self, rest: str) -> None:
        settings = get_settings()
        defaults = settings.default_workflow_models()
        for kind in WORKFLOW_MODEL_KINDS:
            model = settings.workflow_model(kind)
            tag = "  [default]" if kind in defaults else ""
            self.say(f"{kind:<10} {model.get('name') or model.get('model')} ({model.get('provider')}){tag}")
        if defaults:
            self.say("set workflow_* in config.toml to models available in your Dify")


def enable_line_editing(history_file: Path) -> None:
    """Arrow keys and history for input(), when readline is available."""
    try:
        import atexit
        import readline
    except ImportError:
        return
    history_file.parent.mkdir(parents=True, exist_ok=True)
    try:
        readline.read_history_file(history_file)
    except (FileNotFoundError, OSError):
        pass
    readline.set_history_length(1000)
    atexit.register(readline.write_history_file, history_file)


def start(
    dsl: Optional[str] = None,
    dsl_source: str = "",
    resume: Optional[str] = None,
    input_files: Optional[List[str]] = None,
    progress_factory: Callable[[], Any] = lambda: None,
) -> int:
    settings = get_settings()
    if resume:
        directory = ChatSession.latest() if resume == "latest" else Path(resume).expanduser()
        if not directory or not (directory / "session.json").is_file():
            raise ValueError(f"no session to resume in {directory or settings.sessions_dir}")
        session = ChatSession.load(directory)
    else:
        session = ChatSession.create()
    if dsl:
        session.load_dsl(dsl, dsl_source)
    for path in input_files or []:
        session.attach(path)

    repl: ChatRepl
    agent = ChatAgent(session, on_event=lambda kind, **kw: repl.on_event(kind, **kw),
                      confirm=lambda prompt: repl.confirm(prompt), progress_factory=progress_factory)
    repl = ChatRepl(session, agent, progress_factory=progress_factory)
    if sys.stdin.isatty():
        enable_line_editing(settings.home / "chat_history")
    return repl.run()
