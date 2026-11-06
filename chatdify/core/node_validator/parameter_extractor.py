from typing import Any, Dict

from chatdify.dify_compat.entities import ParameterExtractorNodeData

from .base import BaseNodeValidator, BaseNodeValidationResult


class ParameterExtractorNodeValidationResult(BaseNodeValidationResult):
    """参数提取器验证结果"""
    pass


class ParameterExtractorNodeValidator(BaseNodeValidator[ParameterExtractorNodeData]):
    """参数提取器验证器"""
    
    @classmethod
    def validate_node(
        cls,
        node_data_config: Dict[str, Any],
        variable_pool: Dict[str, Any],
        **kwargs
    ) -> ParameterExtractorNodeValidationResult:
        """
        验证参数提取器节点配置
        
        Args:
            node_data_config: 节点配置数据
            variable_pool: 变量池
            
        Returns:
            ParameterExtractorValidationResult: 验证结果
        """
        node_data = cls._get_node_data(node_data_config)
        result = ParameterExtractorNodeValidationResult(
            is_valid=True,
            errors=[],
            variable_selectors=set()
        )

        # 验证query字段
        if not node_data.query:
            result.is_valid = False
            result.errors.append("查询内容(query)不能为空")
            return result
        
         # 添加查询变量选择器到集合
        result.variable_selectors.add(tuple(node_data.query))
        
        # 验证查询变量是否存在
        error = cls._validate_variable_exists(
            node_data.query,
            variable_pool
        )
        if error:
            result.is_valid = False
            result.errors.append(error)

        # 验证parameters字段
        if not node_data.parameters:
            result.is_valid = False
            result.errors.append("参数列表(parameters)不能为空")
            return result

        # 验证每个参数
        for param in node_data.parameters:
            if not param.name:
                result.is_valid = False
                result.errors.append(f"参数名称(name)不能为空")
            
        return result