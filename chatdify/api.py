"""Programmatic entry points used by the CLI.

This module is importable but is not a stable public API yet; signatures may change
between minor versions. Functions never write files: they return results and raise
on configuration errors.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from chatdify import dify_compat
from chatdify.models.workflow import Workflow
from chatdify.progress import ProgressTracker
from chatdify.settings import get_settings


@dataclass
class NodeIssue:
    node_id: str
    node_type: str
    errors: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return {"node_id": self.node_id, "node_type": self.node_type, "errors": self.errors}


@dataclass
class ValidationReport:
    """Result of validating an existing DSL without any LLM call (unless dynamic validation is on)."""

    valid: bool
    static_checked: bool
    dynamic_checked: bool
    issues: List[NodeIssue] = field(default_factory=list)
    parse_error: Optional[str] = None
    dynamic_error: Optional[str] = None
    skipped_reason: Optional[str] = None

    def summary(self) -> str:
        if self.parse_error:
            return f"DSL 解析失败: {self.parse_error}"
        lines: List[str] = []
        for issue in self.issues:
            for err in issue.errors:
                lines.append(f"[{issue.node_type}:{issue.node_id}] {err}")
        if self.dynamic_error:
            lines.append(f"[dynamic] {self.dynamic_error}")
        return "\n".join(lines)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "valid": self.valid,
            "static_checked": self.static_checked,
            "dynamic_checked": self.dynamic_checked,
            "issues": [i.to_dict() for i in self.issues],
            "parse_error": self.parse_error,
            "dynamic_error": self.dynamic_error,
            "skipped_reason": self.skipped_reason,
        }


@dataclass
class RunResult:
    """Outcome of generate / fix / modify."""

    success: bool
    dsl: str
    attempts: int
    duration: float
    static_checked: bool
    dynamic_checked: bool
    last_error: str = ""
    token_stats: Dict[str, Any] = field(default_factory=dict)
    agent_stats: Dict[str, Dict[str, float]] = field(default_factory=dict)
    rounds: List[Dict[str, Any]] = field(default_factory=list)
    attempt_details: List[Any] = field(default_factory=list)
    workflow: Optional[Workflow] = field(default=None, repr=False)

    def to_dict(self, include_dsl: bool = True) -> Dict[str, Any]:
        data = {
            "success": self.success,
            "attempts": self.attempts,
            "duration": round(self.duration, 2),
            "static_checked": self.static_checked,
            "dynamic_checked": self.dynamic_checked,
            "last_error": self.last_error,
            "token_stats": self.token_stats,
            "agent_stats": self.agent_stats,
            "rounds": self.rounds,
            "attempt_details": self.attempt_details,
        }
        if include_dsl:
            data["dsl"] = self.dsl
        return data


def _input_files(files: Optional[Sequence[str]]) -> Optional[List[str]]:
    return list(files) if files else None


def _sum_agent_stats(per_round: Dict[int, Dict[str, Dict[str, float]]]) -> Dict[str, Dict[str, float]]:
    """Sum the per-round planner / executor / reviewer stats over all rounds."""
    totals: Dict[str, Dict[str, float]] = {}
    for agents in per_round.values():
        for agent, stats in agents.items():
            acc = totals.setdefault(agent, {})
            for k, v in stats.items():
                acc[k] = acc.get(k, 0) + v
    for acc in totals.values():
        acc["duration"] = round(acc.get("duration", 0.0), 2)
    return totals


def _round_stats(workflow: Workflow) -> List[Dict[str, Any]]:
    """Per-round duration and tokens; ``cumulative_tokens`` also counts LLM calls made before round 1."""
    durations = workflow.total_execution_duration or {}
    token_snapshots = workflow.total_llm_token_stats or {}
    from chatdify.services.token_stats import cache_hit_rate

    rounds = []
    previous = {"total_tokens": 0, "input_tokens": 0, "cached_tokens": 0}
    for i in sorted(k for k in set(durations) | set(token_snapshots) if int(k) >= 0):
        total = (token_snapshots.get(i) or {}).get("total") or {}
        cumulative = {k: int(total.get(k, 0) or 0) for k in previous}
        delta = {k: cumulative[k] - previous[k] for k in previous}
        duration = durations.get(i)
        rounds.append({
            "round": int(i) + 1,
            "duration": round(duration, 2) if duration is not None else None,
            "tokens": delta["total_tokens"],
            "cached_tokens": delta["cached_tokens"],
            "cache_hit_rate": cache_hit_rate(delta),
            "cumulative_tokens": cumulative["total_tokens"],
            "cumulative_input_tokens": cumulative["input_tokens"],
            "cumulative_cached_tokens": cumulative["cached_tokens"],
            "cumulative_calls": int(total.get("total_calls", 0) or 0),
            "agents": {
                agent: {k: round(v, 2) if k == "duration" else int(v) for k, v in stats.items()}
                for agent, stats in ((workflow.agent_stats or {}).get(i) or {}).items()
            },
        })
        previous = cumulative
    return rounds


def _to_result(workflow: Workflow, started: float, dynamic_checked: bool) -> RunResult:
    from chatdify.utils.metric_util import get_workflow_errors_by_type

    last_errors = workflow.last_errors
    if dynamic_checked:
        success = not any(not e.is_valid for e in (last_errors.dynamic_errors or []))
    else:
        success = last_errors.static_is_valid() and not any(
            not e.is_valid for e in (last_errors.dynamic_errors or [])
        )
    try:
        _, attempt_details = get_workflow_errors_by_type(workflow)
    except Exception:
        attempt_details = []
    try:
        dsl = workflow.to_dsl() if workflow.nodes else ""
    except Exception:
        dsl = ""

    return RunResult(
        success=success,
        dsl=dsl,
        attempts=workflow.execution_count,
        duration=time.perf_counter() - started,
        static_checked=dify_compat.is_available(),
        dynamic_checked=dynamic_checked,
        last_error="" if success else last_errors.get_error_summary(include_fix_suggestion=False),
        token_stats=dict(workflow.llm_token_stats or {}),
        agent_stats=_sum_agent_stats(workflow.agent_stats or {}),
        rounds=_round_stats(workflow),
        attempt_details=attempt_details,
        workflow=workflow,
    )


def generate(
    request: str,
    *,
    name: Optional[str] = None,
    mode: Optional[str] = None,
    input_files: Optional[Sequence[str]] = None,
    progress: Optional[ProgressTracker] = None,
) -> RunResult:
    """Generate a Dify workflow DSL from a natural-language request.

    ``name`` becomes the Dify app name; without it the app is called "未命名工作流".
    """
    from chatdify.engines import GenerateEngine

    started = time.perf_counter()
    engine = GenerateEngine(
        dsl_generation_mode=mode or get_settings().generation_mode,
        name=name,
        progress_tracker=progress,
    )
    workflow = engine.run(user_request=request, input_file=_input_files(input_files))
    if name:
        # ZeroShot-style modes parse the LLM's DSL, which carries its own app name.
        workflow.name = name
    return _to_result(workflow, started, engine.dynamic_enabled)


def fix(
    dsl: str,
    *,
    feedback: Optional[str] = None,
    input_files: Optional[Sequence[str]] = None,
    progress: Optional[ProgressTracker] = None,
) -> RunResult:
    """Repair a broken DSL. Static validation findings are added to the feedback."""
    from chatdify.engines import FixEngine

    started = time.perf_counter()
    report = validate(dsl, dynamic=False)
    hints = [feedback] if feedback else []
    if report.issues:
        hints.append("静态校验发现的问题:\n" + report.summary())

    engine = FixEngine(progress_tracker=progress)
    workflow = engine.run(
        dsl_content=dsl,
        feedback="\n\n".join(hints) or None,
        input_file=_input_files(input_files),
    )
    return _to_result(workflow, started, engine.dynamic_enabled)


def modify(
    dsl: str,
    instruction: str,
    *,
    input_files: Optional[Sequence[str]] = None,
    progress: Optional[ProgressTracker] = None,
) -> RunResult:
    """Modify an existing DSL according to a natural-language instruction."""
    from chatdify.engines import ModifyEngine

    started = time.perf_counter()
    engine = ModifyEngine(progress_tracker=progress)
    workflow = engine.run(
        dsl_content=dsl,
        instruction=instruction,
        input_file=_input_files(input_files),
    )
    return _to_result(workflow, started, engine.dynamic_enabled)


def validate(
    dsl: str,
    *,
    dynamic: bool = False,
    request: Optional[str] = None,
    input_files: Optional[Sequence[str]] = None,
) -> ValidationReport:
    """Validate a DSL.

    Static validation uses Dify's node entities and needs no LLM. Dynamic validation
    imports and runs the DSL on a Dify instance and needs ``dify_url`` plus an LLM
    (for test input generation).
    """
    workflow = Workflow()
    try:
        workflow.from_dsl(dsl)
    except Exception as e:
        return ValidationReport(valid=False, static_checked=False, dynamic_checked=False, parse_error=str(e))

    issues: List[NodeIssue] = []
    static_checked = dify_compat.is_available()
    skipped_reason = None if static_checked else dify_compat.unavailable_reason()

    if static_checked:
        from chatdify.core.node_manager import NodeManager
        from chatdify.services.file_service import FileService

        node_errors = NodeManager(None, FileService()).validate_nodes(workflow)
        for node_id, errors in node_errors.errors.items():
            issues.append(NodeIssue(node_id=node_id, node_type=node_errors.get_node_type(node_id), errors=errors))

    dynamic_checked = False
    dynamic_error = None
    if dynamic:
        from chatdify.core.validator_manager import ValidatorManager
        from chatdify.services.file_service import FileService
        from chatdify.services.llm_service import LLMService

        manager = ValidatorManager(LLMService(), FileService())
        if manager.dynamic_enabled:
            result = manager.validate(dsl_content=dsl, input_file=_input_files(input_files), user_request=request)
            dynamic_checked = True
            if not result.is_valid:
                dynamic_error = result.error_message or result.error_type or "unknown error"
        else:
            skipped_reason = "dynamic validation requires --dify-url (or CHATDIFY_DIFY_URL)"

    return ValidationReport(
        valid=not issues and dynamic_error is None,
        static_checked=static_checked,
        dynamic_checked=dynamic_checked,
        issues=issues,
        dynamic_error=dynamic_error,
        skipped_reason=skipped_reason,
    )


@dataclass
class PublishResult:
    app_id: str
    url: str
    created: bool
    warning: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {"app_id": self.app_id, "url": self.url, "created": self.created, "warning": self.warning}


def publish(dsl: str, *, app_id: Optional[str] = None) -> PublishResult:
    """Import a DSL into the configured Dify workspace as an app.

    With ``app_id`` the existing app's draft is overwritten instead of creating a new app.
    Raises ``PublishError`` when Dify is not configured or the import fails.
    """
    from chatdify.utils.exceptions import PublishError

    settings = get_settings()
    if not settings.dify_url:
        raise PublishError("publishing needs a Dify instance: set dify_url (or pass --dify-url)")
    if not (settings.dify_email and settings.dify_password):
        raise PublishError("publishing needs dify_email and dify_password")

    from chatdify.client.dify.app_client import AppClient

    try:
        client = AppClient(settings.dify_url)
        result = client.import_app(mode="yaml-content", yaml_content=dsl, app_id=app_id)
        if result.get("status") == "pending":
            # Dify asks for confirmation when the DSL version differs from its own.
            result = client.confirm_import(result["id"])
    except Exception as e:
        response = getattr(e, "response", None)
        detail = response.text if response is not None else str(e)
        raise PublishError(f"Dify import failed: {detail}") from e

    new_id = result.get("app_id")
    if result.get("status") == "failed" or not new_id:
        raise PublishError(f"Dify import failed: {result.get('error') or result}")
    return PublishResult(
        app_id=new_id,
        url=f"{settings.dify_url.rstrip('/')}/app/{new_id}/workflow",
        created=app_id is None,
        warning=result.get("error") or "",
    )
