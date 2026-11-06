"""Generate a new workflow from a natural-language request."""
from typing import List, Optional, Union

from chatdify.agents.loop import RefinementLoop
from chatdify.agents.planner import Plan
from chatdify.core.workflow.context import WorkflowContext
from chatdify.models.workflow import Workflow
from chatdify.progress import ProgressTracker
from chatdify.services.file_service import FileService
from chatdify.services.llm_service import LLMService
from chatdify.settings import GENERATION_MODES, get_settings
from chatdify.utils.decorators import timing_decorator
from chatdify.utils.exceptions import GenerateError
from chatdify.utils.logging import get_logger

logger = get_logger(__name__)


class GenerateEngine(RefinementLoop):
    VALID_DSL_MODES = frozenset(GENERATION_MODES)

    def __init__(
        self,
        dsl_generation_mode: str = "AutoGen",
        llm_service: Optional[LLMService] = None,
        file_service: Optional[FileService] = None,
        name: Optional[str] = None,
        mode: Optional[str] = None,
        progress_tracker: Optional[ProgressTracker] = None,
    ):
        if dsl_generation_mode not in self.VALID_DSL_MODES:
            raise GenerateError(f"无效的DSL生成模式: {dsl_generation_mode}")
        super().__init__(llm_service, file_service, progress_tracker)
        settings = get_settings()
        self._expand_request = settings.expand_request
        self._generate_tasks = settings.generate_tasks
        self._dsl_mode = dsl_generation_mode
        self._context = WorkflowContext(name=name, mode=mode)
        logger.info(f"工作流引擎初始化完成，模式: {dsl_generation_mode}")

    @timing_decorator
    def run(
        self,
        user_request: str,
        feedback: Optional[str] = None,
        previous_workflow: Optional[Workflow] = None,
        input_file: Optional[Union[str, List[str]]] = None,
    ) -> Workflow:
        self._reset_totals()
        self._user_request = user_request
        self._feedback = feedback
        self._previous = previous_workflow
        self._input_file = input_file
        self._review_request = user_request
        return self._run()

    def _begin_round(self, i: int) -> None:
        self._context.setup(user_request=self._user_request, feedback=self._feedback, previous_workflow=self._previous)

    def _planning_message(self, i: int) -> str:
        return f"第{i+1}轮规划: {self._user_request[:100]}..."

    def _plan(self, i: int) -> Plan:
        processed_request, tasks = self.planner.decompose(
            self._user_request,
            self._context.format_feedback_history(),
            self._expand_request,
            self._generate_tasks,
        )
        self._context.user_request = processed_request
        self._context.tasks = tasks

        # Retrieval-only modes cannot act on feedback, so later rounds switch to MixedGen.
        if len(self._context.format_feedback_history()) > 0 and self._dsl_mode in ("AutoRec", "AutoRecZeroShot"):
            self._dsl_mode = "MixedGen"

        if tasks:
            self._detail("\n" + tasks[0])

        return self.planner.plan(
            workflow=self._context.workflow,
            user_request=processed_request,
            tasks=tasks,
            dsl_mode=self._dsl_mode,
            feedback_history=self._context.format_feedback_history(),
            previous_workflow=self._previous,
        )

    def _previous_workflow(self) -> Optional[Workflow]:
        return self._previous

    def _after_execution(self) -> None:
        self._previous = self._context.workflow.copy()

    def _set_feedback(self, feedback: str) -> None:
        self._feedback = feedback
