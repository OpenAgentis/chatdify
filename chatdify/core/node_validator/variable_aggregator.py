from typing import Dict, Any, Set, Tuple
from dataclasses import dataclass, field
from .base import BaseNodeValidator, BaseNodeValidationResult
from chatdify.dify_compat.entities import (
    VariableAggregatorNodeData,
    AdvancedSettings,
)
from chatdify.utils.logging import get_logger

logger = get_logger(__name__)


@dataclass
class VariableAggregatorValidationResult(BaseNodeValidationResult):
    """变量聚合节点验证结果"""
    aggregated_selectors: Set[Tuple[str, ...]] = field(default_factory=set)  # 存储聚合变量选择器
    group_selectors: Dict[str, Set[Tuple[str, ...]]] = field(default_factory=dict)  # 存储分组变量选择器


class VariableAggregatorNodeValidator(BaseNodeValidator[VariableAggregatorNodeData]):
    """变量聚合节点验证器"""
    
    @classmethod
    def validate_node(
        cls,
        node_data_config: Dict[str, Any],
        variable_pool: Dict[str, Any],
        **kwargs
    ) -> VariableAggregatorValidationResult:
        """验证变量聚合节点配置"""
        try:
            # 获取节点数据
            node_data = cls._get_node_data(node_data_config)
            
            result = VariableAggregatorValidationResult(
                is_valid=True,
                errors=[],
                variable_selectors=set(),
                aggregated_selectors=set(),
                group_selectors={}
            )
            
            # 验证基础配置
            cls._validate_basic_config(node_data, result)
            
            # 验证输出类型
            cls._validate_output_type(node_data, result)
            
            # 验证变量选择器
            cls._validate_variables(node_data, variable_pool, result)
            
            # 验证高级设置
            cls._validate_advanced_settings(node_data, variable_pool, result)
        
            return result
            
        except Exception as e:
            logger.error(f"变量聚合节点验证过程发生错误: {str(e)}", exc_info=True)
            return VariableAggregatorValidationResult(
                is_valid=False,
                errors=[f"变量聚合节点验证过程发生错误: {str(e)}"],
                variable_selectors=set(),
                aggregated_selectors=set(),
                group_selectors={}
            )
    
    @classmethod
    def _validate_basic_config(
        cls,
        node_data: VariableAggregatorNodeData,
        result: VariableAggregatorValidationResult
    ) -> None:
        """验证基础配置"""
        # 验证节点数据完整性
        if not hasattr(node_data, 'output_type'):
            result.is_valid = False
            result.errors.append("缺少输出类型(output_type)配置")
            
        if not hasattr(node_data, 'variables'):
            result.is_valid = False
            result.errors.append("缺少变量选择器(variables)配置")
    
    @classmethod
    def _validate_output_type(
        cls,
        node_data: VariableAggregatorNodeData,
        result: VariableAggregatorValidationResult
    ) -> None:
        """验证输出类型"""
        valid_output_types = [
            "string", "number", "object", 
            "array[string]", "array[number]", "array[object]",
            "array[any]", "array[boolean]", "array[file]"
        ]
        
        if not node_data.output_type:
            result.is_valid = False
            result.errors.append("输出类型(output_type)不能为空")
            return
            
        if node_data.output_type not in valid_output_types:
            result.is_valid = False
            result.errors.append(f"无效的输出类型: '{node_data.output_type}'，支持的类型: {valid_output_types}")
    
    @classmethod
    def _validate_variables(
        cls,
        node_data: VariableAggregatorNodeData,
        variable_pool: Dict[str, Any],
        result: VariableAggregatorValidationResult
    ) -> None:
        """验证变量选择器"""
        if not node_data.variables:
            result.is_valid = False
            result.errors.append("变量选择器列表(variables)不能为空")
            return
            
        if not isinstance(node_data.variables, list):
            result.is_valid = False
            result.errors.append("变量选择器列表(variables)必须是列表格式")
            return
            
        if len(node_data.variables) < 1:
            result.is_valid = False
            result.errors.append("至少需要一个变量选择器")
            return
        
        # 验证每个变量选择器
        for i, selector in enumerate(node_data.variables):
            if not isinstance(selector, list):
                result.is_valid = False
                result.errors.append(f"第 {i+1} 个变量选择器必须是列表格式")
                continue
                
            if len(selector) < 1:
                result.is_valid = False
                result.errors.append(f"第 {i+1} 个变量选择器路径不能为空")
                continue
            
            selector_tuple = tuple(selector)
            result.aggregated_selectors.add(selector_tuple)
            result.variable_selectors.add(selector_tuple)
            
            # 验证变量是否存在
            error = cls._validate_variable_exists(selector, variable_pool)
            if error:
                result.is_valid = False
                result.errors.append(f"第 {i+1} 个变量验证失败: {error}")
    
    @classmethod
    def _validate_advanced_settings(
        cls,
        node_data: VariableAggregatorNodeData,
        variable_pool: Dict[str, Any],
        result: VariableAggregatorValidationResult
    ) -> None:
        """验证高级设置"""
        if not node_data.advanced_settings:
            return
            
        advanced_settings = node_data.advanced_settings
        
        # 验证分组设置
        if advanced_settings.group_enabled:
            if not advanced_settings.groups:
                result.is_valid = False
                result.errors.append("启用分组时必须配置分组列表")
                return
                
            if not isinstance(advanced_settings.groups, list):
                result.is_valid = False
                result.errors.append("分组配置必须是列表格式")
                return
                
            if len(advanced_settings.groups) < 1:
                result.is_valid = False
                result.errors.append("至少需要一个分组配置")
                return
            
            # 验证每个分组
            group_names = set()
            for i, group in enumerate(advanced_settings.groups):
                cls._validate_group(group, i, variable_pool, result, group_names)
    
    @classmethod
    def _validate_group(
        cls,
        group: AdvancedSettings.Group,
        group_index: int,
        variable_pool: Dict[str, Any],
        result: VariableAggregatorValidationResult,
        group_names: set
    ) -> None:
        """验证单个分组配置"""
        # 验证分组名称
        if not group.group_name:
            result.is_valid = False
            result.errors.append(f"第 {group_index+1} 个分组的名称不能为空")
        elif group.group_name in group_names:
            result.is_valid = False
            result.errors.append(f"第 {group_index+1} 个分组的名称 '{group.group_name}' 重复")
        else:
            group_names.add(group.group_name)
        
        # 验证分组输出类型
        valid_output_types = [
            "string", "number", "object", 
            "array[string]", "array[number]", "array[object]",
            "array[any]", "array[boolean]", "array[file]"
        ]
        
        if not group.output_type:
            result.is_valid = False
            result.errors.append(f"第 {group_index+1} 个分组的输出类型不能为空")
        elif group.output_type not in valid_output_types:
            result.is_valid = False
            result.errors.append(f"第 {group_index+1} 个分组的输出类型 '{group.output_type}' 无效，支持的类型: {valid_output_types}")
        
        # 验证分组变量
        if not group.variables:
            result.is_valid = False
            result.errors.append(f"第 {group_index+1} 个分组的变量列表不能为空")
            return
            
        if not isinstance(group.variables, list):
            result.is_valid = False
            result.errors.append(f"第 {group_index+1} 个分组的变量必须是列表格式")
            return
            
        if len(group.variables) < 1:
            result.is_valid = False
            result.errors.append(f"第 {group_index+1} 个分组至少需要一个变量")
            return
        
        # 初始化分组选择器集合
        if group.group_name not in result.group_selectors:
            result.group_selectors[group.group_name] = set()
        
        # 验证分组中的每个变量选择器
        for j, selector in enumerate(group.variables):
            if not isinstance(selector, list):
                result.is_valid = False
                result.errors.append(f"第 {group_index+1} 个分组的第 {j+1} 个变量选择器必须是列表格式")
                continue
                
            if len(selector) < 1:
                result.is_valid = False
                result.errors.append(f"第 {group_index+1} 个分组的第 {j+1} 个变量选择器路径不能为空")
                continue
            
            selector_tuple = tuple(selector)
            result.group_selectors[group.group_name].add(selector_tuple)
            result.variable_selectors.add(selector_tuple)
            
            # 验证变量是否存在
            error = cls._validate_variable_exists(selector, variable_pool)
            if error:
                result.is_valid = False
                result.errors.append(f"第 {group_index+1} 个分组的第 {j+1} 个变量验证失败: {error}")