"""Run a suite of generation / bugfix cases and write per-case DSL plus an aggregate summary.

Case file format (YAML), grouped by category::

    content_creation_cases:
      ppt_generation:
        prompt: |
          ...
        input_file: deck.pptx            # optional, str or list, relative to --data-dir

Bugfix cases additionally have ``dsl`` (relative to --dsl-dir) and ``feedback``.
"""
from __future__ import annotations

import json
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional

import yaml

from chatdify.services.token_stats import cache_hit_rate
from chatdify.settings import get_settings

TASKS = ("generation", "bugfix")


@dataclass
class EvalCase:
    category: str
    name: str
    prompt: str = ""
    input_files: List[str] = field(default_factory=list)
    dsl_path: Optional[Path] = None
    feedback: Optional[str] = None

    @property
    def key(self) -> str:
        return f"{self.category}/{self.name}"


def _as_list(value: Any) -> List[str]:
    if not value:
        return []
    return [value] if isinstance(value, str) else list(value)


def load_cases(
    path: Path,
    task: str,
    data_dir: Optional[Path] = None,
    dsl_dir: Optional[Path] = None,
    select: Optional[Iterable[str]] = None,
) -> List[EvalCase]:
    if task not in TASKS:
        raise ValueError(f"unknown task '{task}', choose from {TASKS}")
    data_dir = data_dir or path.parent / "data"
    dsl_dir = dsl_dir or path.parent / "bugfix_dsl"
    wanted = set(select or [])

    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    cases: List[EvalCase] = []
    for category, items in raw.items():
        for name, spec in (items or {}).items():
            case = EvalCase(
                category=category,
                name=name,
                prompt=(spec.get("prompt") or "").strip(),
                input_files=[str(data_dir / p) for p in _as_list(spec.get("input_file"))],
                feedback=spec.get("feedback"),
            )
            if task == "bugfix":
                if not spec.get("dsl"):
                    raise ValueError(f"bugfix case {case.key} has no 'dsl' field")
                case.dsl_path = dsl_dir / spec["dsl"]
            if wanted and case.key not in wanted and category not in wanted:
                continue
            cases.append(case)
    return cases


def _run_case(case: EvalCase, task: str, with_feedback: bool, progress) -> Dict[str, Any]:
    from chatdify import api
    from chatdify.utils.metric_util import get_node_summary

    started = time.perf_counter()
    try:
        if task == "generation":
            result = api.generate(case.prompt, name=case.name, input_files=case.input_files, progress=progress)
        else:
            dsl = case.dsl_path.read_text(encoding="utf-8")
            result = api.fix(
                dsl,
                feedback=case.feedback if with_feedback else None,
                input_files=case.input_files,
                progress=progress,
            )
    except Exception as e:  # one broken case must not abort the whole run
        return {
            "status": "error",
            "error": f"{type(e).__name__}: {e}",
            "duration": round(time.perf_counter() - started, 2),
        }

    workflow = result.workflow
    return {
        "status": "succeeded" if result.success else "failed",
        "attempts": result.attempts,
        "duration": round(result.duration, 2),
        "last_error": result.last_error,
        "node_summary": get_node_summary(workflow.nodes) if workflow else {},
        "token_stats": result.token_stats,
        "agent_stats": result.agent_stats,
        "rounds": result.rounds,
        "attempt_details": result.attempt_details,
        "dsl": result.dsl,
    }


def _by_round(results: Dict[str, Dict[str, Any]], max_rounds: int) -> List[Dict[str, Any]]:
    """Metrics as if every case had been allowed at most N rounds, for N = 1..max_rounds.

    Cases that finished earlier still count in later rows with their final numbers, and the
    denominator is always all cases, so rows are comparable across N.
    """
    total = len(results)
    if not total:
        return []
    observed = max((len(r.get("rounds") or []) for r in results.values()), default=0)
    rows = []
    for n in range(1, max(max_rounds, observed) + 1):
        succeeded = sum(1 for r in results.values() if r["status"] == "succeeded" and r.get("attempts", 0) <= n)
        duration = 0.0
        tokens = {"total_tokens": 0, "input_tokens": 0, "cached_tokens": 0}
        for r in results.values():
            rounds = [x for x in (r.get("rounds") or []) if x["round"] <= n]
            duration += sum(x.get("duration") or 0 for x in rounds)
            if rounds:
                tokens["total_tokens"] += rounds[-1].get("cumulative_tokens", 0)
                tokens["input_tokens"] += rounds[-1].get("cumulative_input_tokens", 0)
                tokens["cached_tokens"] += rounds[-1].get("cumulative_cached_tokens", 0)
        rows.append({
            "round": n,
            "success_rate": round(succeeded / total * 100, 2),
            "avg_duration": round(duration / total, 2),
            "avg_tokens": round(tokens["total_tokens"] / total),
            "cache_hit_rate": cache_hit_rate(tokens),
        })
    return rows


def _summarize(results: Dict[str, Dict[str, Any]], task: str, started_at: str) -> Dict[str, Any]:
    total = len(results)
    statuses = Counter(r["status"] for r in results.values())
    succeeded = statuses.get("succeeded", 0)
    by_attempt = Counter(r["attempts"] for r in results.values() if r["status"] == "succeeded")
    categories = Counter(key.split("/")[0] for key in results)
    node_types: Counter = Counter()
    tokens: Dict[str, int] = Counter()
    agent_totals: Dict[str, Counter] = {}
    for r in results.values():
        for agent, stats in (r.get("agent_stats") or {}).items():
            agent_totals.setdefault(agent, Counter()).update(stats)
        node_types.update((r.get("node_summary") or {}).get("type_distribution", {}))
        total_stats = (r.get("token_stats") or {}).get("total") or {}
        for k in ("input_tokens", "cached_tokens", "output_tokens", "total_tokens", "total_calls"):
            tokens[k] += int(total_stats.get(k, 0) or 0)
    durations = [r.get("duration", 0) for r in results.values()]

    return {
        "task": task,
        "started_at": started_at,
        "total_cases": total,
        "succeeded": succeeded,
        "failed": statuses.get("failed", 0),
        "errored": statuses.get("error", 0),
        "success_rate": round(succeeded / total * 100, 2) if total else 0.0,
        "success_by_attempt": {f"attempt_{k}": v for k, v in sorted(by_attempt.items())},
        "by_round": _by_round(results, get_settings().max_retries),
        "total_duration": round(sum(durations), 2),
        "avg_duration": round(sum(durations) / total, 2) if total else 0.0,
        "category_counts": dict(categories),
        "node_type_distribution": dict(node_types.most_common()),
        "token_totals": dict(tokens),
        "cache_hit_rate": cache_hit_rate(tokens),
        "agent_totals": {
            agent: {
                **{k: round(v, 2) if k == "duration" else int(v) for k, v in stats.items()},
                "cache_hit_rate": cache_hit_rate(stats),
            }
            for agent, stats in agent_totals.items()
        },
    }


def run_eval(
    cases: List[EvalCase],
    task: str,
    out_dir: Path,
    *,
    with_feedback: bool = True,
    progress_factory: Optional[Callable[[EvalCase], Any]] = None,
    on_case_done: Optional[Callable[[EvalCase, Dict[str, Any], int, int], None]] = None,
) -> Dict[str, Any]:
    """Run ``cases`` and write results under ``out_dir/<timestamp>/``. Returns the summary dict."""
    started_at = datetime.now()
    run_dir = out_dir / f"{task}_{started_at.strftime('%Y%m%d_%H%M%S')}"
    dsl_dir = run_dir / "dsl"
    dsl_dir.mkdir(parents=True, exist_ok=True)

    results: Dict[str, Dict[str, Any]] = {}
    with open(run_dir / "results.jsonl", "w", encoding="utf-8") as jsonl:
        for index, case in enumerate(cases, start=1):
            progress = progress_factory(case) if progress_factory else None
            record = _run_case(case, task, with_feedback, progress)
            dsl = record.pop("dsl", "")
            if dsl:
                path = dsl_dir / f"{case.category}.{case.name}.yml"
                path.write_text(dsl, encoding="utf-8")
                record["dsl_file"] = str(path.relative_to(run_dir))
            results[case.key] = record
            jsonl.write(json.dumps({"case": case.key, **record}, ensure_ascii=False, default=str) + "\n")
            jsonl.flush()
            if on_case_done:
                on_case_done(case, record, index, len(cases))

            summary = _summarize(results, task, started_at.isoformat())
            with open(run_dir / "summary.yml", "w", encoding="utf-8") as f:
                yaml.safe_dump(summary, f, allow_unicode=True, sort_keys=False)

    summary = _summarize(results, task, started_at.isoformat())
    summary["output_dir"] = str(run_dir)
    return summary
