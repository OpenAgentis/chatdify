"""Repair an existing workflow DSL that fails validation."""
from typing import List, Optional, Union

from chatdify.agents.loop import RefinementLoop
from chatdify.agents.planner import Plan
from chatdify.core.workflow.context import WorkflowContext
from chatdify.models.workflow import Workflow
from chatdify.progress import ProgressTracker, WorkflowStep
from chatdify.services.file_service import FileService
from chatdify.services.llm_service import LLMService
from chatdify.utils.decorators import timing_decorator
from chatdify.utils.exceptions import FixError
from chatdify.utils.logging import get_logger

logger = get_logger(__name__)


class FixEngine(RefinementLoop):
    exception_error_type = "未知错误"
    exception_message_prefix = "修复工作流出现异常"

    def __init__(
        self,
        llm_service: Optional[LLMService] = None,
        file_service: Optional[FileService] = None,
        progress_tracker: Optional[ProgressTracker] = None,
    ):
        super().__init__(llm_service, file_service, progress_tracker)
        logger.info("Bugfix引擎初始化完成")

    @timing_decorator
    def run(
        self,
        dsl_content: str,
        feedback: Optional[str] = None,
        input_file: Optional[Union[str, List[str]]] = None,
    ) -> Workflow:
        """Review the DSL once, then loop with the reviewer's findings as feedback until it passes."""
        user_workflow = Workflow()
        try:
            user_workflow.from_dsl(dsl_content)
            logger.info(f"用户DSL解析成功, 边大小：{len(user_workflow.edges)}, 节点大小：{len(user_workflow.nodes)}")
        except Exception as e:
            logger.error(f"解析用户DSL内容失败: {str(e)}")
            raise FixError(f"用户DSL解析错误: {str(e)}")

        self._reset_totals()
        self._user_workflow = user_workflow
        self._input_file = input_file
        self._review_request = None

        self._context = WorkflowContext()
        self._context.setup(user_workflow=user_workflow, feedback=feedback)
        self._context.workflow = user_workflow.copy()

        self._start(WorkflowStep.REVIEW, "评审待修复的DSL")
        result = self.reviewer.review(self._context.workflow, input_file)
        validation_duration = self._context.workflow.get_last_validation_duration()
        self._total_dynamic_validation_duration[-1] = validation_duration
        if validation_duration is not None:
            logger.info(f"开始修复前动态验证耗时: {validation_duration:.2f} 秒")
        else:
            logger.warning("开始修复前动态验证耗时: 无法获取（可能未正确记录）")

        self._system_feedback = result.error_message if result.error_message else ""
        self._complete(f"评审完成, 结果：{self._system_feedback}")

        return self._run()

    def _planning_message(self, i: int) -> str:
        return f"第{i+1}轮修复规划"

    def _plan(self, i: int) -> Plan:
        user_request = self.planner.bugfix_request(self._context.workflow.to_dsl())
        self._context.setup(user_request=user_request, feedback=self._system_feedback)
        return self.planner.plan(
            workflow=self._context.workflow,
            user_request=self._context.user_request,
            tasks=[],
            dsl_mode="AutoGen",
            feedback_history=self._context.format_feedback_history(),
        )

    def _set_feedback(self, feedback: str) -> None:
        self._system_feedback = feedback

    def _on_exception(self) -> None:
        self._context.workflow = self._user_workflow.copy()
