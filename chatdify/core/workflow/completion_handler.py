from typing import Dict, Any
from chatdify.models.workflow import Workflow, WorkflowErrors
from chatdify.services.llm_service import LLMService
from chatdify.utils.logging import get_logger

logger = get_logger(__name__)


class WorkflowCompletionHandler:
    """工作流完成处理器，负责处理工作流完成时的统一逻辑"""
    
    def __init__(self, llm_service: LLMService):
        self._llm_service = llm_service
    
    def handle_completion(
        self, 
        workflow: Workflow, 
        execution_count: int, 
        total_errors: Dict[int, WorkflowErrors],
        total_dynamic_validation_duration: Dict[int, float],
        total_execution_duration: Dict[int, float],
        total_llm_token_stats: Dict[int, Dict[str, Any]],
        success: bool = True
    ) -> None:
        """处理工作流完成逻辑
        
        Args:
            workflow: 工作流对象
            execution_count: 执行次数
            total_errors: 总错误信息
            total_dynamic_validation_duration: 每次迭代的动态验证时间
            total_execution_duration: 每次迭代的运行时间
            total_llm_token_stats: 每次迭代的llm token统计
            success: 是否成功完成
        """
        # 设置工作流状态
        workflow.execution_count = execution_count
        workflow.total_errors = total_errors.copy()
        workflow.total_dynamic_validation_duration = total_dynamic_validation_duration.copy()
        workflow.total_execution_duration = total_execution_duration.copy()
        workflow.total_llm_token_stats = total_llm_token_stats.copy()
        
        # 标记工作流完成
        workflow.mark_completed()
        
        workflow.llm_token_stats = workflow.total_llm_token_stats[execution_count - 1]
        
        # 输出统计日志
        self._log_completion_stats(workflow, success)
    
    def _log_completion_stats(self, workflow: Workflow, success: bool) -> None:
        """输出完成统计日志"""
        status = "成功" if success else "失败"
        logger.info(f"工作流{status}完成统计:")
        logger.info(f"workflow.total_errors: {workflow.total_errors}")
        logger.info(f"workflow.execution_count: {workflow.execution_count}")
        logger.info(f"workflow.duration: {workflow.get_duration()}秒")
        logger.info(f"workflow.total_dynamic_validation_duration: {workflow.total_dynamic_validation_duration}, sum: {sum(v for v in workflow.total_dynamic_validation_duration.values() if v is not None)}秒")
        logger.info(f"workflow.total_execution_duration: {workflow.total_execution_duration}, sum: {sum(v for v in workflow.total_execution_duration.values() if v is not None)}秒")
        logger.info(f"workflow.total_llm_token_stats: {workflow.total_llm_token_stats}")
        logger.info(f"workflow.llm_token_stats: {workflow.llm_token_stats}")
        logger.info(f"workflow.last_errors.get_dynamic_output: {workflow.last_errors.get_dynamic_output()}")
        # logger.info(f"workflow.last_errors.get_dynamic_running_result_summary: {workflow.last_errors.get_dynamic_running_result_summary()}")
