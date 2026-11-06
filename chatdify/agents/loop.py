"""Closed-loop refinement shared by generate, fix and modify.

Each round runs Planner → Executor → Reviewer. When the reviewer rejects the workflow, its
error summary becomes feedback for the next round, up to ``max_retries`` rounds. Subclasses
only decide how a round's request is built and how feedback is carried over.
"""
import time
from typing import Any, Dict, List, Optional, Union

from chatdify.agents.executor import Executor
from chatdify.agents.planner import Plan, Planner
from chatdify.agents.reviewer import Reviewer
from chatdify.core.node_manager import NodeManager
from chatdify.core.workflow.completion_handler import WorkflowCompletionHandler
from chatdify.core.workflow.context import WorkflowContext
from chatdify.models.workflow import ValidationResult, Workflow, WorkflowErrors
from chatdify.progress import ProgressTracker, WorkflowStep
from chatdify.services.file_service import FileService
from chatdify.services.llm_service import LLMService
from chatdify.settings import get_settings
from chatdify.utils.logging import get_logger

logger = get_logger(__name__)

AGENTS = ("planner", "executor", "reviewer")
_TOKEN_KEYS = ("input_tokens", "cached_tokens", "output_tokens", "total_tokens", "total_calls")


class RefinementLoop:
    # Error type recorded when a round raises instead of returning a workflow.
    exception_error_type = "未知类型"
    exception_message_prefix = "生成工作流出现异常"

    def __init__(
        self,
        llm_service: Optional[LLMService] = None,
        file_service: Optional[FileService] = None,
        progress_tracker: Optional[ProgressTracker] = None,
    ):
        self._llm_service = llm_service or LLMService()
        self._file_service = file_service or FileService()
        self._progress_tracker = progress_tracker
        self._max_retries = get_settings().max_retries

        node_manager = NodeManager(self._llm_service, self._file_service)
        self.planner = Planner(self._llm_service, self._file_service, node_manager)
        self.executor = Executor(self._llm_service, self._file_service, node_manager)
        self.reviewer = Reviewer(self._llm_service, self._file_service)

        self._completion_handler = WorkflowCompletionHandler(self._llm_service)
        self._context = WorkflowContext()
        self._input_file: Optional[Union[str, List[str]]] = None
        self._review_request: Optional[str] = None
        self._reset_totals()

    @property
    def dynamic_enabled(self) -> bool:
        return self.reviewer.dynamic_enabled

    # ------------------------------------------------------------------ hooks

    def _begin_round(self, i: int) -> None:
        """Prepare the context before the round's timer starts."""

    def _planning_message(self, i: int) -> str:
        return f"第{i+1}轮规划"

    def _plan(self, i: int) -> Plan:
        raise NotImplementedError

    def _previous_workflow(self) -> Optional[Workflow]:
        """Workflow from the previous round that the executor may build on."""
        return None

    def _after_execution(self) -> None:
        """Called after the executor, before review."""

    def _set_feedback(self, feedback: str) -> None:
        raise NotImplementedError

    def _on_rejected(self) -> None:
        """Called after the reviewer rejected the round and feedback was set."""

    def _on_exception(self) -> None:
        """Called after a round raised and feedback was set."""

    # ------------------------------------------------------------------ progress

    def _start(self, step: WorkflowStep, message: str) -> None:
        if self._progress_tracker:
            self._progress_tracker.start_step_sync(step, message)

    def _complete(self, message: str) -> None:
        if self._progress_tracker:
            self._progress_tracker.complete_step_sync(message)

    def _fail(self, message: str) -> None:
        if self._progress_tracker:
            self._progress_tracker.fail_step_sync(message)

    def _detail(self, detail: str) -> None:
        if self._progress_tracker:
            self._progress_tracker.add_step_detail_sync(detail)

    # ------------------------------------------------------------------ bookkeeping

    def _reset_totals(self) -> None:
        self._total_errors: Dict[int, WorkflowErrors] = {}
        self._total_dynamic_validation_duration: Dict[int, Optional[float]] = {}
        self._total_execution_duration: Dict[int, Optional[float]] = {}
        self._total_llm_token_stats: Dict[int, Dict[str, Any]] = {}
        self._agent_stats: Dict[int, Dict[str, Dict[str, float]]] = {}
        self._round_started: Dict[int, float] = {}
        self._phase_started: Optional[tuple] = None

    def _token_totals(self) -> Dict[str, int]:
        total = self._llm_service.get_token_stats().get("total") or {}
        return {k: int(total.get(k, 0) or 0) for k in _TOKEN_KEYS}

    def _begin_phase(self) -> None:
        self._phase_started = (time.perf_counter(), self._token_totals())

    def _end_phase(self, i: int, agent: str) -> None:
        if self._phase_started is None:
            return
        started, tokens_before = self._phase_started
        tokens_after = self._token_totals()
        stats = self._agent_stats.setdefault(i, {}).setdefault(agent, {"duration": 0.0, **{k: 0 for k in _TOKEN_KEYS}})
        stats["duration"] += time.perf_counter() - started
        for k in _TOKEN_KEYS:
            stats[k] += tokens_after[k] - tokens_before[k]
        self._phase_started = None

    def _record_round_end(self, i: int) -> None:
        # Timed here rather than via workflow.get_iteration_duration: fix rebuilds the
        # workflow mid-round (context.setup resets it), which drops the recorded start time.
        self._context.workflow.mark_iteration_completed(i)
        started = self._round_started.get(i)
        execution_duration = time.perf_counter() - started if started is not None else None
        self._total_execution_duration[i] = execution_duration
        if execution_duration is not None:
            logger.info(f"第{i+1}次迭代运行时间: {execution_duration:.2f} 秒")
        else:
            logger.warning(f"第{i+1}次迭代运行时间: 无法获取（可能未正确记录开始时间）")

        iteration_token_stats = self._llm_service.get_token_stats()
        self._total_llm_token_stats[i] = iteration_token_stats
        logger.info(f"第{i+1}次迭代token统计: {iteration_token_stats}")

    def _finish(self, execution_count: int, success: bool) -> Workflow:
        workflow = self._context.workflow
        workflow.agent_stats = {i: dict(v) for i, v in self._agent_stats.items()}
        self._completion_handler.handle_completion(
            workflow=workflow,
            execution_count=execution_count,
            total_errors=self._total_errors,
            total_dynamic_validation_duration=self._total_dynamic_validation_duration,
            total_execution_duration=self._total_execution_duration,
            total_llm_token_stats=self._total_llm_token_stats,
            success=success,
        )
        return workflow

    # ------------------------------------------------------------------ the loop

    def _run(self) -> Workflow:
        for i in range(self._max_retries):
            agent = None
            try:
                self._begin_round(i)
                self._round_started[i] = time.perf_counter()
                self._context.workflow.mark_iteration_started(i)

                agent = "planner"
                self._start(WorkflowStep.PLANNING, self._planning_message(i))
                self._begin_phase()
                plan = self._plan(i)
                if plan.graph:
                    self._detail("工作流Mermaid图如下所示:\n" + plan.graph)
                self._end_phase(i, agent)
                self._complete(f"第{i+1}轮规划完成")

                agent = "executor"
                self._start(WorkflowStep.EXECUTION, f"第{i+1}轮生成节点，模式: {plan.dsl_mode}")
                self._begin_phase()
                self.executor.execute(
                    workflow=self._context.workflow,
                    plan=plan,
                    feedback_history=self._context.format_feedback_history(),
                    previous_workflow=self._previous_workflow(),
                    progress_tracker=self._progress_tracker,
                )
                self._end_phase(i, agent)
                self._after_execution()
                self._complete(f"第{i+1}轮工作流生成完成")

                agent = "reviewer"
                self._start(WorkflowStep.REVIEW, f"第{i+1}轮评审工作流")
                self._begin_phase()
                result = self.reviewer.review(self._context.workflow, self._input_file, self._review_request)
                validation_duration = self._context.workflow.get_last_validation_duration()
                self._total_dynamic_validation_duration[i] = validation_duration
                if validation_duration is not None:
                    logger.info(f"第{i+1}次动态验证耗时: {validation_duration:.2f} 秒")
                self._end_phase(i, agent)

                self._record_round_end(i)

                accepted = self.reviewer.accepts(self._context.workflow, result)
                self._total_errors[i] = self._context.workflow.last_errors.copy()

                if accepted:
                    logger.info(f"第{i+1}次评审通过")
                    self._complete(f"第{i+1}轮评审通过，共尝试{i+1}轮")
                    return self._finish(execution_count=i + 1, success=True)

                feedback = self._total_errors[i].get_error_summary(include_fix_suggestion=True)
                logger.info(f"第{i+1}次评审未通过, 原因: {feedback}")
                self._set_feedback(feedback)
                self._on_rejected()

                if i < self._max_retries - 1:
                    error_msg = self._total_errors[i].get_error_summary(include_fix_suggestion=False)
                    self._fail(f"第{i+1}轮评审未通过: {error_msg}")
                else:
                    self._fail(f"第{i+1}轮评审完成")

            except Exception as e:
                if agent:
                    self._end_phase(i, agent)
                error_msg = f"{self.exception_message_prefix}: {str(e)}"
                exception_error = ValidationResult(
                    is_valid=False,
                    error_type=self.exception_error_type,
                    error_message=error_msg,
                )
                workflow = self._context.workflow
                workflow.set_static_errors([exception_error])
                self._total_errors[i] = workflow.last_errors.copy()

                if workflow.last_validation_started_at is not None:
                    if workflow.last_validation_completed_at is None:
                        workflow.mark_validation_completed()
                    self._total_dynamic_validation_duration[i] = workflow.get_last_validation_duration()

                self._record_round_end(i)

                self._set_feedback(self._total_errors[i].get_error_summary(include_fix_suggestion=True))
                self._on_exception()

                logger.error(f"第{i+1}轮出现异常: {error_msg}")
                self._fail(f"第{i+1}轮出现异常: {error_msg}")

                time.sleep(1)

        logger.error("已达到最大轮数，工作流仍未通过评审")
        return self._finish(execution_count=self._max_retries, success=False)
