from typing import Dict, Any, Set, Tuple
from dataclasses import dataclass, field
from .base import BaseNodeValidator, BaseNodeValidationResult
from chatdify.dify_compat.entities import LoopNodeData
from chatdify.utils.logging import get_logger

logger = get_logger(__name__)


@dataclass
class LoopValidationResult(BaseNodeValidationResult):
    """循环节点验证结果"""
    loop_variable_selectors: Set[Tuple[str, ...]] = field(default_factory=set)
    break_condition_selectors: Set[Tuple[str, ...]] = field(default_factory=set)


class LoopNodeValidator(BaseNodeValidator[LoopNodeData]):
    """循环节点验证器"""
    
    @classmethod
    def validate_node(
        cls,
        node_data_config: Dict[str, Any],
        variable_pool: Dict[str, Any],
        **kwargs
    ) -> LoopValidationResult:
        """验证循环节点配置"""
        try:
            is_first_stage = kwargs.get("is_first_stage", False)
            if is_first_stage:
                return cls.validate_node_at_first_stage(node_data_config, variable_pool)

            node_data = cls._get_node_data(node_data_config)

            result = LoopValidationResult(is_valid=True, errors=[], variable_selectors=set())

            loop_variable_pool = variable_pool["loop_variable"] 
            break_condition_pool = variable_pool["break_condition"]

            # 验证基础配置
            cls._validate_basic_config(node_data, result)
            
            # 验证循环变量
            cls._validate_loop_variables(node_data, loop_variable_pool, result)
            
            # 验证循环条件
            cls._validate_break_conditions(node_data, break_condition_pool, result)
            
            # 验证开始节点ID
            cls._validate_start_node_id(node_data, result)
            
            return result
            
        except Exception as e:
            logger.error(f"循环节点验证过程发生错误: {str(e)}", exc_info=True)
            return LoopValidationResult(
                is_valid=False,
                errors=[f"循环节点验证过程发生错误: {str(e)}"],
                variable_selectors=set()
            )
    
    @classmethod
    def validate_node_at_first_stage(
        cls,
        node_data_config: Dict[str, Any],
        variable_pool: Dict[str, Any]
    ) -> LoopValidationResult:
        """第一阶段验证循环节点配置"""
        try:
            node_data = cls._get_node_data(node_data_config)
            result = LoopValidationResult(is_valid=True, errors=[], variable_selectors=set())
            
            # 验证基础配置
            cls._validate_basic_config(node_data, result)
            
            # 验证开始节点ID
            cls._validate_start_node_id(node_data, result)

            # 验证循环变量
            cls._validate_loop_variables(node_data, variable_pool, result)
            
            return result
            
        except Exception as e:
            logger.error(f"循环节点验证过程发生错误: {str(e)}", exc_info=True)
            return LoopValidationResult(
                is_valid=False,
                errors=[f"循环节点验证过程发生错误: {str(e)}"],
                variable_selectors=set()
            )
    
    @classmethod
    def _validate_basic_config(cls, node_data: LoopNodeData, result: LoopValidationResult) -> None:
        """验证基础配置"""
        if not hasattr(node_data, 'loop_count'):
            result.is_valid = False
            result.errors.append("缺少循环次数(loop_count)配置")
            
    @classmethod
    def _validate_loop_variables(
        cls,
        node_data: LoopNodeData,
        variable_pool: Dict[str, Any],
        result: LoopValidationResult
    ) -> None:
        """验证循环变量
        
        Args:
            node_data: 循环节点数据
            variable_pool: 变量池
            result: 验证结果对象
        """
        if not node_data.loop_variables:
            return
            
        # 检查循环变量列表是否有效
        if not isinstance(node_data.loop_variables, list):
            result.is_valid = False
            result.errors.append("循环变量配置(loop_variables)必须是列表格式")
            return
            
        seen_labels = set()
        
        for var in node_data.loop_variables:
            # 验证变量对象完整性
            if not hasattr(var, 'label') or not var.label:
                result.is_valid = False
                result.errors.append("循环变量(loop_variables)缺少标签或标签为空")
                continue

            # 验证标签格式
            if not cls._validate_selector_naming(var.label):
                result.is_valid = False
                result.errors.append(f"循环变量标签 '{var.label}' 格式无效，必须是有效的Python标识符")
                continue
            
            # 检查标签是否重复
            if var.label in seen_labels:
                result.is_valid = False
                result.errors.append(f"重复的循环变量标签: {var.label}")
                continue
            seen_labels.add(var.label)
            
            # 验证值类型
            if not hasattr(var, 'value_type') or var.value_type not in ["variable", "constant"]:
                result.is_valid = False
                result.errors.append(f"无效的循环变量值类型: {getattr(var, 'value_type', '未设置')}，请设置为'constant'或'variable'")
                continue
                
            # 验证变量值
            if var.value_type == "variable":
                if not hasattr(var, 'value') or not var.value:
                    result.is_valid = False
                    result.errors.append(f"变量类型循环变量{var.label}的值不能为空")
                    continue
               
                # 检查variable_selector格式
                if not isinstance(var.value, list):
                    result.is_valid = False
                    result.errors.append(f"当循环变量值类型是变量（variable）时，循环变量的value必须是列表格式: {var.value}")
                    continue
                    
                # 验证变量是否存在
                error = cls._validate_variable_exists(
                    var.value,
                    variable_pool
                )

                if error:
                    result.is_valid = False
                    result.errors.append(f"循环变量验证失败: {error}")
            
            # 记录变量选择器用于后续验证
            if var.value_type == "variable":
                # 记录有效的循环变量选择器
                result.loop_variable_selectors.add(tuple(var.value))
                result.variable_selectors.add(tuple(var.value))
    
    @classmethod
    def _validate_break_conditions(
        cls, 
        node_data: LoopNodeData, 
        variable_pool: Dict[str, Any],
        result: LoopValidationResult,
    ) -> None:
        """验证循环终止条件"""
        if not node_data.break_conditions:
            return
            
        if node_data.logical_operator not in ["and", "or"]:
            result.is_valid = False
            result.errors.append(f"无效的逻辑运算符: {node_data.logical_operator}")
            return
            
        # 验证每个终止条件的variable_selector
        for condition in node_data.break_conditions:
            if not hasattr(condition, 'variable_selector') or not condition.variable_selector:
                result.is_valid = False
                result.errors.append("终止条件缺少variable_selector配置")
                continue
                
            # 检查variable_selector格式
            if not isinstance(condition.variable_selector, list):
                result.is_valid = False
                result.errors.append(f"终止条件的variable_selector必须是列表格式: {condition.variable_selector}")
                continue
                
            # 检查变量是否存在
            error = cls._validate_variable_exists(
                condition.variable_selector,
                variable_pool
            )
            if error:
                result.is_valid = False
                result.errors.append(f"终止条件变量验证失败: {error}")
            
            result.break_condition_selectors.add(tuple(condition.variable_selector))
            result.variable_selectors.add(tuple(condition.variable_selector))
    
    @classmethod
    def _validate_start_node_id(cls, node_data: LoopNodeData, result: LoopValidationResult) -> None:
        """验证开始节点ID"""
        if not hasattr(node_data, 'start_node_id'):
            result.is_valid = False
            result.errors.append("缺少开始节点ID配置")
            return
            
        if not node_data.start_node_id:
            result.is_valid = False
            result.errors.append("开始节点ID不能为空")