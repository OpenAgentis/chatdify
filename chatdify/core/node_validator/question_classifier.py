from typing import Dict, Any

from chatdify.dify_compat.entities import QuestionClassifierNodeData, VariableTemplateParser

from .base import BaseNodeValidator, BaseNodeValidationResult
from chatdify.utils.logging import get_logger

logger = get_logger(__name__)


class QuestionClassifierNodeValidationResult(BaseNodeValidationResult):
    """参数提取器验证结果"""
    pass


class QuestionClassifierNodeValidator(BaseNodeValidator[QuestionClassifierNodeData]):
    """问题分类器节点验证器"""
    
    @classmethod
    def validate_node(
        cls,
        node_data_config: Dict[str, Any],
        variable_pool: Dict[str, Any],
        **kwargs
    ) -> QuestionClassifierNodeValidationResult:
        """
        验证问题分类器节点配置
        
        Args:
            node_data_config: 节点配置数据
            variable_pool: 变量池
            
        Returns:
            QuestionClassifierNodeValidationResult: 验证结果
        """
        # 获取节点数据
        node_data = cls._get_node_data(node_data_config)
        
        result = QuestionClassifierNodeValidationResult(
            is_valid=True,
            errors=[],
            variable_selectors=set()
        )

        source_handles = set(kwargs.get("source_handles", []))
        logger.info(f"source_handles: {source_handles}")

        # 验证查询变量选择器
        if not node_data.query_variable_selector:
            result.is_valid = False
            result.errors.append("查询变量选择器(query_variable_selector)不能为空")
            return result
            
        # 添加查询变量选择器到集合
        result.variable_selectors.add(tuple(node_data.query_variable_selector))
        
        # 验证查询变量是否存在
        error = cls._validate_variable_exists(
            node_data.query_variable_selector,
            variable_pool
        )
        if error:
            result.is_valid = False
            result.errors.append(error)
        
        try:
            # 验证classes
            if not node_data.classes:
                result.is_valid = False
                result.errors.append("classes不能为空")
            
            # 验证每个class的id和name
            for class_item in node_data.classes:
                if not class_item.id:
                    result.is_valid = False
                    result.errors.append("class的id不能为空")
                if not class_item.name:
                    result.is_valid = False
                    result.errors.append("class的name不能为空")
                
                # 验证class的id是否有效
                if class_item.id not in source_handles:
                    result.is_valid = False
                    result.errors.append(
                        f"class的id {class_item.id} 不正确, 必须和边信息中对应的sourceHandle值保持一致\n"
                        f"当前边信息中对应的sourceHandle值列表为: {source_handles}"
                        )
                
            # 验证指令中的变量选择器
            if node_data.instruction:
                variable_template_parser = VariableTemplateParser(template=node_data.instruction)
                instruction_selectors = variable_template_parser.extract_variable_selectors()
                
                # 验证每个指令变量选择器
                for selector in instruction_selectors:
                    result.variable_selectors.add(tuple(selector.value_selector))
                    error = cls._validate_variable_exists(
                        selector.value_selector,
                        variable_pool
                    )
                    if error:
                        result.is_valid = False
                        result.errors.append(error)
                
        except Exception as e:
            result.is_valid = False
            result.errors.append(f"变量选择器验证过程发生错误: {str(e)}")
            
        return result
   
    
   
    