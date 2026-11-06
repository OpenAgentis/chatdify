from typing import Any, Dict

from chatdify.dify_compat.entities import AnswerNodeData, VariableTemplateParser


from .base import BaseNodeValidator, BaseNodeValidationResult


class AnswerNodeValidationResult(BaseNodeValidationResult):
    """Answer节点验证结果"""
    pass


class AnswerNodeValidator(BaseNodeValidator[AnswerNodeData]):
    """Answer 节点验证器"""
    
    @classmethod
    def validate_node(
        cls,
        node_data_config: Dict[str, Any],
        variable_pool: Dict[str, Any],
        **kwargs
    ) -> AnswerNodeValidationResult:
        """
        验证Answer节点配置
        
        Args:
            node_data_config: 节点配置数据
            variable_pool: 变量池
            
        Returns:
            AnswerNodeValidationResult: 验证结果
        """
        # 获取节点数据
        node_data = cls._get_node_data(node_data_config)
        
        result = AnswerNodeValidationResult(
            is_valid=True,
            errors=[],
            variable_selectors=set()
        )

        # 验证answer字段
        if not node_data.answer:
            result.is_valid = False
            result.errors.append("回答内容不能为空")
            return result

        try:
            # 提取并验证变量选择器
            variable_template_parser = VariableTemplateParser(template=node_data.answer)
            selectors = variable_template_parser.extract_variable_selectors()
            
            for selector in selectors:
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
    
    