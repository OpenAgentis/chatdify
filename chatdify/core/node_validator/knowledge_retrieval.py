from typing import Dict, Any, Set, Tuple
from dataclasses import dataclass, field
from .base import BaseNodeValidator, BaseNodeValidationResult
from chatdify.dify_compat.entities import (
    KnowledgeRetrievalNodeData,
    MultipleRetrievalConfig,
)
from chatdify.utils.logging import get_logger

logger = get_logger(__name__)


@dataclass
class KnowledgeRetrievalValidationResult(BaseNodeValidationResult):
    """知识检索节点验证结果"""
    query_selectors: Set[Tuple[str, ...]] = field(default_factory=set)  # 存储查询选择器
    dataset_selectors: Set[Tuple[str, ...]] = field(default_factory=set)  # 存储数据集选择器


class KnowledgeRetrievalNodeValidator(BaseNodeValidator[KnowledgeRetrievalNodeData]):
    """知识检索节点验证器"""
    
    @classmethod
    def validate_node(
        cls,
        node_data_config: Dict[str, Any],
        variable_pool: Dict[str, Any],
        **kwargs
    ) -> KnowledgeRetrievalValidationResult:
        """验证知识检索节点配置"""
        try:
            # 获取节点数据
            node_data = cls._get_node_data(node_data_config)
            
            result = KnowledgeRetrievalValidationResult(
                is_valid=True,
                errors=[],
                variable_selectors=set(),
                query_selectors=set(),
                dataset_selectors=set()
            )
            
            # 验证基础配置
            cls._validate_basic_config(node_data, result)
            
            # 验证查询变量选择器
            cls._validate_query_selector(node_data, variable_pool, result)
            
            # 验证数据集ID
            cls._validate_dataset_ids(node_data, result)
            
            # 验证检索模式配置
            cls._validate_retrieval_mode(node_data, result)
            
            # 验证元数据过滤配置
            cls._validate_metadata_filtering(node_data, result)
        
            return result
            
        except Exception as e:
            logger.error(f"知识检索节点验证过程发生错误: {str(e)}", exc_info=True)
            return KnowledgeRetrievalValidationResult(
                is_valid=False,
                errors=[f"知识检索节点验证过程发生错误: {str(e)}"],
                variable_selectors=set(),
                query_selectors=set(),
                dataset_selectors=set()
            )
    
    @classmethod
    def _validate_basic_config(
        cls,
        node_data: KnowledgeRetrievalNodeData,
        result: KnowledgeRetrievalValidationResult
    ) -> None:
        """验证基础配置"""
        # 验证节点数据完整性
        if not hasattr(node_data, 'query_variable_selector'):
            result.is_valid = False
            result.errors.append("缺少查询变量选择器配置(query_variable_selector)")
            
        if not hasattr(node_data, 'dataset_ids'):
            result.is_valid = False
            result.errors.append("缺少数据集ID配置(dataset_ids)")
            
        if not hasattr(node_data, 'retrieval_mode'):
            result.is_valid = False
            result.errors.append("缺少检索模式配置(retrieval_mode)")
    
    @classmethod
    def _validate_query_selector(
        cls,
        node_data: KnowledgeRetrievalNodeData,
        variable_pool: Dict[str, Any],
        result: KnowledgeRetrievalValidationResult
    ) -> None:
        """验证查询变量选择器"""
        if not node_data.query_variable_selector:
            result.is_valid = False
            result.errors.append("查询变量选择器(query_variable_selector)不能为空")
            return
            
        # 验证选择器格式
        if not isinstance(node_data.query_variable_selector, list):
            result.is_valid = False
            result.errors.append("查询变量选择器(query_variable_selector)必须是列表格式")
            return
            
        # 验证选择器路径有效性
        if len(node_data.query_variable_selector) < 1:
            result.is_valid = False
            result.errors.append("查询变量选择器(query_variable_selector)路径不能为空")
            return
        
        result.query_selectors.add(tuple(node_data.query_variable_selector))
        result.variable_selectors.add(tuple(node_data.query_variable_selector))
        
        # 验证查询变量是否存在
        error = cls._validate_variable_exists(
            node_data.query_variable_selector,
            variable_pool
        )
        if error:
            result.is_valid = False
            result.errors.append(f"查询变量验证失败: {error}")
            return
    
    @classmethod
    def _validate_dataset_ids(
        cls,
        node_data: KnowledgeRetrievalNodeData,
        result: KnowledgeRetrievalValidationResult
    ) -> None:
        """验证数据集ID"""
        if not node_data.dataset_ids:
            result.is_valid = False
            result.errors.append("数据集ID(dataset_ids)不能为空")
            return
            
        if not isinstance(node_data.dataset_ids, list):
            result.is_valid = False
            result.errors.append("数据集ID(dataset_ids)必须是列表格式")
            return
            
        if len(node_data.dataset_ids) < 1:
            result.is_valid = False
            result.errors.append("至少需要一个数据集ID(dataset_ids)")
            return
    
    @classmethod
    def _validate_retrieval_mode(
        cls,
        node_data: KnowledgeRetrievalNodeData,
        result: KnowledgeRetrievalValidationResult
    ) -> None:
        """验证检索模式配置"""

        valid_modes = ["multiple"]
        
        if node_data.retrieval_mode not in valid_modes:
            result.is_valid = False
            result.errors.append(f"无效的检索模式(retrieval_mode): '{node_data.retrieval_mode}'，支持的模式: {valid_modes}")
            return
        
        
        if node_data.retrieval_mode == "multiple":
            if not node_data.multiple_retrieval_config:
                result.is_valid = False
                result.errors.append("多检索模式需要配置 multiple_retrieval_config")
            else:
                cls._validate_multiple_retrieval_config(node_data.multiple_retrieval_config, result)

    @classmethod
    def _validate_multiple_retrieval_config(
        cls,
        config: MultipleRetrievalConfig,
        result: KnowledgeRetrievalValidationResult
    ) -> None:
        """验证多检索配置"""
        # 验证 top_k
        if config.top_k <= 0:
            result.is_valid = False
            result.errors.append("多检索配置的 top_k 必须大于 0")
        
        # 验证 score_threshold
        if config.score_threshold is not None:
            if not (0.0 <= config.score_threshold <= 1.0):
                result.is_valid = False
                result.errors.append("多检索配置的 score_threshold 必须在 0.0 到 1.0 之间")
        
        # 验证重排序配置
        if config.reranking_enable and config.reranking_mode == "reranking_model":
            if not config.reranking_model:
                result.is_valid = False
                result.errors.append("启用重排序模型时必须配置 reranking_model")
        
        # 验证权重配置
        if config.reranking_mode == "weighted_score":
            if not config.weights:
                result.is_valid = False
                result.errors.append("加权评分模式需要配置 weights")

    @classmethod
    def _validate_metadata_filtering(
        cls,
        node_data: KnowledgeRetrievalNodeData,
        result: KnowledgeRetrievalValidationResult
    ) -> None:
        """验证元数据过滤配置"""
        if node_data.metadata_filtering_mode == "automatic":
            if not node_data.metadata_model_config:
                result.is_valid = False
                result.errors.append("自动元数据过滤模式需要配置metadata_model_config")
        elif node_data.metadata_filtering_mode == "manual":
            if not node_data.metadata_filtering_conditions:
                result.is_valid = False
                result.errors.append("手动元数据过滤模式需要配置metadata_filtering_conditions")
    
   