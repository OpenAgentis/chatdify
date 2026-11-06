"""Modify an existing workflow DSL according to user feedback."""
from typing import List, Optional, Union

from chatdify.agents.loop import RefinementLoop
from chatdify.agents.planner import Plan
from chatdify.core.workflow.context import WorkflowContext
from chatdify.models.workflow import Workflow
from chatdify.progress import ProgressTracker
from chatdify.services.file_service import FileService
from chatdify.services.llm_service import LLMService
from chatdify.utils.decorators import timing_decorator
from chatdify.utils.exceptions import ModifyError
from chatdify.utils.logging import get_logger

logger = get_logger(__name__)


class ModifyEngine(RefinementLoop):
    exception_error_type = "未知错误"
    exception_message_prefix = "修改工作流出现异常"

    def __init__(
        self,
        llm_service: Optional[LLMService] = None,
        file_service: Optional[FileService] = None,
        progress_tracker: Optional[ProgressTracker] = None,
    ):
        super().__init__(llm_service, file_service, progress_tracker)
        logger.info("DSL修改引擎初始化完成")

    @timing_decorator
    def run(
        self,
        dsl_content: str,
        instruction: str,
        previous_workflow: Optional[Workflow] = None,
        input_file: Optional[Union[str, List[str]]] = None,
    ) -> Workflow:
        """Turn ``instruction`` into a change request once, then loop until the reviewer accepts."""
        user_workflow = Workflow()
        try:
            user_workflow.from_dsl(dsl_content)
            logger.info(
                f"用户DSL解析成功, 工作流模式：{user_workflow.mode}, "
                f"边大小：{len(user_workflow.edges)}, 节点大小：{len(user_workflow.nodes)}"
            )
        except Exception as e:
            logger.error(f"解析用户DSL内容失败: {str(e)}")
            raise ModifyError(f"用户DSL解析错误: {str(e)}")

        processed_request = self.planner.modify_request(dsl_content, instruction)

        self._reset_totals()
        self._input_file = input_file
        self._review_request = None
        self._previous = previous_workflow
        self._system_feedback = ""

        self._context = WorkflowContext()
        self._context.workflow = user_workflow.copy()
        self._context.setup(user_request=processed_request, user_workflow=user_workflow)

        return self._run()

    def _begin_round(self, i: int) -> None:
        self._context.setup(feedback=self._system_feedback, previous_workflow=self._previous)

    def _planning_message(self, i: int) -> str:
        return f"第{i+1}轮修改规划"

    def _plan(self, i: int) -> Plan:
        return self.planner.plan(
            workflow=self._context.workflow,
            user_request=self._context.user_request,
            tasks=[],
            dsl_mode="AutoGen",
            feedback_history=self._context.format_feedback_history(),
            previous_workflow=self._context.previous_workflow,
        )

    def _previous_workflow(self) -> Optional[Workflow]:
        return self._context.previous_workflow

    def _set_feedback(self, feedback: str) -> None:
        self._system_feedback = feedback

    def _on_rejected(self) -> None:
        self._previous = self._context.workflow.copy()
