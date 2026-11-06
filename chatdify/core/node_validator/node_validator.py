"""节点配置验证器"""
from typing import Dict, Any, Type

from chatdify.utils.logging import get_logger
from .base import BaseNodeValidator, BaseNodeValidationResult
from .llm import LLMNodeValidator
from .code import CodeNodeValidator
from .if_else import IfElseNodeValidator
from .answer import AnswerNodeValidator
from .document_extractor import DocumentExtractorNodeValidator
from .end import EndNodeValidator
from .question_classifier import QuestionClassifierNodeValidator
from .iteration import IterationNodeValidator
from .tool import ToolNodeValidator
from .template_transform import TemplateTransformNodeValidator
from .parameter_extractor import ParameterExtractorNodeValidator
from .variable_aggregator import VariableAggregatorNodeValidator
from .http_request import HttpRequestNodeValidator
from .knowledge_retrieval import KnowledgeRetrievalNodeValidator 
from .variable_assigner import VariableAssignerNodeValidator
from .loop import LoopNodeValidator
from .start import StartNodeValidator

logger = get_logger(__name__)


class NodeValidator:
    """节点配置验证器"""
    
    # 节点类型到验证器的映射
    VALIDATOR_MAPPING: Dict[str, Type[BaseNodeValidator]] = {
        "llm": LLMNodeValidator,
        "code": CodeNodeValidator,
        "if-else": IfElseNodeValidator,
        "document-extractor": DocumentExtractorNodeValidator,
        "question-classifier": QuestionClassifierNodeValidator,
        "iteration": IterationNodeValidator,
        "tool": ToolNodeValidator,
        "template-transform": TemplateTransformNodeValidator,
        "parameter-extractor": ParameterExtractorNodeValidator,
        "variable-aggregator": VariableAggregatorNodeValidator,
        "http-request": HttpRequestNodeValidator,
        "knowledge-retrieval": KnowledgeRetrievalNodeValidator,
        "assigner": VariableAssignerNodeValidator,
        "loop": LoopNodeValidator,
        "answer": AnswerNodeValidator,
        "end": EndNodeValidator,
        "start": StartNodeValidator
    }

    def __init__(self, node_type: str):
        """初始化节点配置验证器
        
        Args:
            node_type: 节点类型
        """
        self._node_type = node_type
        self._validator = self.VALIDATOR_MAPPING.get(node_type)
       
    def validate_node(
        self, 
        node_data_config: Dict[str, Any], 
        variable_pool: Dict[str, Any],
        **kwargs
    ) -> BaseNodeValidationResult:
        """验证节点配置
        
        Args:
            node_data_config: 节点配置数据
            variable_pool: 变量池
            
        Returns:
            BaseNodeValidationResult: 验证结果。如果节点类型不支持验证，返回默认的成功结果。
        """
        try:
            if not self._validator:
                logger.warning(f"节点类型 {self._node_type} 不支持验证，跳过验证")
                return BaseNodeValidationResult(
                    is_valid=True,
                    errors=[],
                    variable_selectors=set()
                )
                
            logger.info(f"开始验证 {self._node_type} 类型节点")

            result = self._validator.validate_node(
                node_data_config=node_data_config, 
                variable_pool=variable_pool,
                **kwargs
            )
            
            self._log_validation_summary(result)
                
            return result
            
        except Exception as e:
            error_msg = f"节点验证过程出错: {str(e)}"
            logger.error(error_msg)
            raise ValueError(error_msg)
    
    @classmethod
    def _log_validation_summary(
        cls,
        result: BaseNodeValidationResult
    ) -> None:
        """记录验证摘要信息"""
        logger.info(
            f"节点验证完成 - 是否有效: {result.is_valid}, "
            f"错误数: {len(result.errors)}, "
            f"选择器数: {len(result.variable_selectors)}, "
            f"选择器详情: {result.variable_selectors}"
        )
        
        if result.errors:
            logger.error(f"节点验证错误: {result.errors}")

  