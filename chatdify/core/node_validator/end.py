from typing import Dict, Any, Set, Tuple, Optional
from dataclasses import dataclass, field

from chatdify.dify_compat.entities import (
    EndNodeData,
    EndStreamParam,
    VariableSelector,
)

from .base import BaseNodeValidator, BaseNodeValidationResult

@dataclass
class EndNodeValidationResult(BaseNodeValidationResult):
    """End节点验证结果"""
    stream_variable_selectors: Set[Tuple[str, ...]] = field(default_factory=set)   # 存储流式输出的变量选择器


class EndNodeValidator(BaseNodeValidator[EndNodeData]):
    """End节点验证器"""
    
    @classmethod
    def validate_node(
        cls,
        node_data_config: Dict[str, Any],
        variable_pool: dict,
        **kwargs
    ) -> EndNodeValidationResult:
        """
        验证End节点配置
        
        Args:
            node_data_config: 节点配置数据
            variable_pool: 变量池
            node_id_config_mapping: 节点ID配置映射
            
        Returns:
            EndNodeValidationResult: 验证结果
        """
        # 获取节点数据
        node_data = cls._get_node_data(node_data_config)
        
        result = EndNodeValidationResult(
            is_valid=True,
            errors=[],
            variable_selectors=set(),
            stream_variable_selectors=set()
        )

        # 验证输出变量选择器
        if not node_data.outputs:
            result.is_valid = False
            result.errors.append("输出变量选择器列表不能为空")
            return result

        # 验证每个输出变量选择器
        for variable_selector in node_data.outputs:
            if not variable_selector.variable:
                result.is_valid = False
                result.errors.append("变量名不能为空")
                continue
                
            if not variable_selector.value_selector:
                result.is_valid = False
                result.errors.append(f"变量 '{variable_selector.variable}' 的选择器路径不能为空")
                continue

            # 添加到变量选择器集合
            result.variable_selectors.add(tuple(variable_selector.value_selector))
            
            # 验证变量是否存在
            error = cls._validate_variable_exists(
                variable_selector.value_selector,
                variable_pool
            )
            if error:
                result.is_valid = False
                result.errors.append(error)

        return result

    @staticmethod
    def validate_stream_param(stream_param: EndStreamParam) -> Optional[str]:
        """
        验证流式参数
        
        Args:
            stream_param: 流式参数
            
        Returns:
            str: 如果验证失败返回错误信息，否则返回None
        """
        if not stream_param.end_dependencies:
            return "end_dependencies 不能为空"
            
        if not stream_param.end_stream_variable_selector_mapping:
            return "end_stream_variable_selector_mapping 不能为空"
            
        # 验证依赖关系
        for end_node_id, dependencies in stream_param.end_dependencies.items():
            if not isinstance(dependencies, list):
                return f"节点 {end_node_id} 的依赖必须是列表类型"
                
        # 验证变量选择器映射
        for end_node_id, selectors in stream_param.end_stream_variable_selector_mapping.items():
            if not isinstance(selectors, list):
                return f"节点 {end_node_id} 的变量选择器映射必须是列表类型"
                
            for selector in selectors:
                if not isinstance(selector, list):
                    return f"节点 {end_node_id} 的变量选择器必须是列表类型"
                    
        return None

    @staticmethod
    def _is_stream_variable(
        variable_selector: VariableSelector,
        node_id_config_mapping: Dict[str, Any]
    ) -> bool:
        """检查是否为流式输出变量"""
        if len(variable_selector.value_selector) < 2:
            return False
            
        node_id = variable_selector.value_selector[0]
        if node_id not in node_id_config_mapping:
            return False
            
        node_type = node_id_config_mapping[node_id].get("data", {}).get("type")
        return (
            node_type == "llm" and
            variable_selector.value_selector[1] == "text"
        )


