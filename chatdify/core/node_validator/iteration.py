from typing import Dict, Any, Set, Tuple
from dataclasses import dataclass, field
from .base import BaseNodeValidator, BaseNodeValidationResult
from chatdify.models.node import Node

from chatdify.dify_compat.entities import (
    ErrorHandleMode,
    IterationNodeData,
)
from chatdify.utils.logging import get_logger

logger = get_logger(__name__)


@dataclass
class IterationValidationResult(BaseNodeValidationResult):
    """迭代节点验证结果"""
    iterator_selectors: Set[Tuple[str, ...]] = field(default_factory=set)  # 存储迭代器选择器
    output_selectors: Set[Tuple[str, ...]] = field(default_factory=set)  # 存储输出选择器


class IterationNodeValidator(BaseNodeValidator[IterationNodeData]):
    """迭代节点验证器"""
    
    # 并行数量限制常量
    MIN_PARALLEL_NUMS = 1
    MAX_PARALLEL_NUMS = 100
    DEFAULT_PARALLEL_NUMS = 10
    
    @classmethod
    def validate_node(
        cls,
        node_data_config: Dict[str, Any],
        variable_pool: Dict[str, Any],
        **kwargs
    ) -> IterationValidationResult:
        """验证迭代节点配置"""
        try:
            is_first_stage = kwargs.get("is_first_stage", False)
            if is_first_stage:
                return cls.validate_node_at_first_stage(node_data_config, variable_pool)

            # 获取节点数据
            node_data = cls._get_node_data(node_data_config)
            
            result = IterationValidationResult(is_valid=True,
            errors=[],
            variable_selectors=set(),
            iterator_selectors=set(),
            output_selectors=set()
            )
            
            iterator_variable_pool = variable_pool["iterator"] 
            output_variable_pool = variable_pool["output"]

            # 验证基础配置
            cls._validate_basic_config(node_data, result)
            
            # 验证迭代器选择器
            cls._validate_iterator_selector(node_data, iterator_variable_pool, result)
            
            # 验证输出选择器
            cls._validate_output_selector(node_data, output_variable_pool, result)
            
            # 验证并行配置
            cls._validate_parallel_config(node_data, result)
            
            # 验证错误处理模式
            cls._validate_error_handle_mode(node_data, result)
            
            # 验证开始节点ID
            cls._validate_start_node_id(node_data, result)
            
            # 记录验证统计信息
            cls._log_validation_summary(result)
                
            return result
            
        except Exception as e:
            logger.error(f"迭代节点验证过程发生错误: {str(e)}", exc_info=True)
            return IterationValidationResult(
                is_valid=False,
                errors=[f"迭代节点验证过程发生错误: {str(e)}"],
                variable_selectors=set(),
                iterator_selectors=set(),
                output_selectors=set()
            )
    
    @classmethod
    def validate_node_at_first_stage(
        cls,
        node_data_config: Dict[str, Any],
        variable_pool: Dict[str, Any]
    ) -> IterationValidationResult:
        """第一阶段验证迭代节点配置"""
        try:
            # 获取节点数据
            node_data = cls._get_node_data(node_data_config)
            
            result = IterationValidationResult(is_valid=True,
            errors=[],
            variable_selectors=set(),
            iterator_selectors=set(),
            output_selectors=set()
            )
            
            # 验证基础配置
            cls._validate_basic_config(node_data, result)
            
            # 验证迭代器选择器
            cls._validate_iterator_selector(node_data, variable_pool, result)
            
            # 验证并行配置
            cls._validate_parallel_config(node_data, result)
            
            # 验证错误处理模式
            cls._validate_error_handle_mode(node_data, result)
            
            # 验证开始节点ID
            cls._validate_start_node_id(node_data, result)
            
            return result
            
        except Exception as e:
            logger.error(f"迭代节点验证过程发生错误: {str(e)}", exc_info=True)
            return IterationValidationResult(
                is_valid=False,
                errors=[f"迭代节点验证过程发生错误: {str(e)}"],
                variable_selectors=set(),
                iterator_selectors=set(),
                output_selectors=set()
            )
    
    @classmethod
    def _validate_basic_config(
        cls,
        node_data: IterationNodeData,
        result: IterationValidationResult
    ) -> None:
        """验证基础配置"""
        # 验证节点数据完整性
        if not hasattr(node_data, 'iterator_selector'):
            result.is_valid = False
            result.errors.append("缺少迭代器选择器配置(iterator_selector)")
            
        if not hasattr(node_data, 'output_selector'):
            result.is_valid = False
            result.errors.append("缺少输出选择器配置(output_selector)")
    
    @classmethod
    def _validate_iterator_selector(
        cls,
        node_data: IterationNodeData,
        variable_pool: Dict[str, Any],
        result: IterationValidationResult
    ) -> None:
        """验证迭代器选择器"""
        if not node_data.iterator_selector:
            result.is_valid = False
            result.errors.append("迭代器选择器(iterator_selector)不能为空")
            return
            
        # 验证选择器格式
        if not isinstance(node_data.iterator_selector, list):
            result.is_valid = False
            result.errors.append("迭代器选择器(iterator_selector)必须是列表格式")
            return
            
        # 验证选择器路径有效性
        if len(node_data.iterator_selector) < 1:
            result.is_valid = False
            result.errors.append("迭代器选择器(iterator_selector)路径不能为空")
            return
            
        result.iterator_selectors.add(tuple(node_data.iterator_selector))
        result.variable_selectors.add(tuple(node_data.iterator_selector))

        # 验证迭代器变量是否存在    
        error = cls._validate_variable_exists(
            node_data.iterator_selector,
            variable_pool
        )
        if error:
            result.is_valid = False
            result.errors.append(f"迭代器变量(iterator_selector)验证失败: {error}")
            return
        
        # 需要从variable_pool中获取对应的节点信息
        node_id = node_data.iterator_selector[0]
        if node_id in variable_pool:
            ref_node = variable_pool[node_id]
            cls._validate_iterator_variable_type(ref_node=ref_node, result=result)
            
    @classmethod
    def _validate_iterator_variable_type(
        cls,
        ref_node: Node,
        result: IterationValidationResult
    ) -> None:
        """验证迭代器变量类型"""
        node_type = ref_node.data.get("type")

        if node_type not in ["sys", "start", "code", "parameter-extractor"]:
            result.is_valid = False
            result.errors.append(f"迭代器变量(iterator_selector)类型错误，迭代器变量(iterator_selector)类型必须是数组。"
            f"仅支持sys、start、parameter-extractor、code节点类型引用，"
            f"当前节点类型为{node_type}, 该节点的输出类型不是数组")
            result.should_abort = True  # 设置中止标志
            return

    @classmethod
    def _validate_output_selector(
        cls,
        node_data: IterationNodeData,
        variable_pool: Dict[str, Any],
        result: IterationValidationResult
    ) -> None:
        """验证输出选择器"""
        if not node_data.output_selector:
            result.is_valid = False
            result.errors.append("输出选择器(output_selector)不能为空")
            return
            
        # 验证选择器格式
        if not isinstance(node_data.output_selector, list):
            result.is_valid = False
            result.errors.append("输出选择器(output_selector)必须是列表格式")
            return
            
        # 验证选择器路径有效性
        if len(node_data.output_selector) < 1:
            result.is_valid = False
            result.errors.append("输出选择器路径(output_selector)不能为空")
            return
       
        result.output_selectors.add(tuple(node_data.output_selector))
        result.variable_selectors.add(tuple(node_data.output_selector))
        
        # 验证输出变量是否存在（在迭代上下文中可能不存在）
        error = cls._validate_variable_exists(
            node_data.output_selector,
            variable_pool
        )
        if error:
            result.is_valid = False
            result.errors.append(error)
            return
    
    @classmethod
    def _validate_parallel_config(
        cls,
        node_data: IterationNodeData,
        result: IterationValidationResult
    ) -> None:
        """验证并行配置"""
        if not hasattr(node_data, 'is_parallel'):
            return
            
        if node_data.is_parallel:
            # 验证并行数量
            if not hasattr(node_data, 'parallel_nums'):
                result.is_valid = False
                result.errors.append("启用并行模式时必须指定parallel_nums")
                return
                
            if not isinstance(node_data.parallel_nums, int):
                result.is_valid = False
                result.errors.append("parallel_nums必须是整数")
                return
                
            if node_data.parallel_nums < cls.MIN_PARALLEL_NUMS:
                result.is_valid = False
                result.errors.append(f"parallel_nums必须大于等于 {cls.MIN_PARALLEL_NUMS}")
        
            elif node_data.parallel_nums > cls.MAX_PARALLEL_NUMS:
                result.is_valid = False
                result.errors.append(f"parallel_nums不能超过 {cls.MAX_PARALLEL_NUMS}")
        
    
    @classmethod
    def _validate_error_handle_mode(
        cls,
        node_data: IterationNodeData,
        result: IterationValidationResult
    ) -> None:
        """验证错误处理模式"""
        if not hasattr(node_data, 'error_handle_mode'):
            return
            
        try:
            # 验证错误处理模式是否有效
            if isinstance(node_data.error_handle_mode, str):
                ErrorHandleMode(node_data.error_handle_mode)
            elif isinstance(node_data.error_handle_mode, ErrorHandleMode):
                pass  # 已经是正确的枚举类型
            else:
                result.is_valid = False
                result.errors.append(
                    f"无效的错误处理模式: {node_data.error_handle_mode}, "
                    f"支持的模式: {[mode.value for mode in ErrorHandleMode]}"
                )
               
        except ValueError:
            result.is_valid = False
            result.errors.append(
                f"无效的错误处理模式: {node_data.error_handle_mode}, "
                f"支持的模式: {[mode.value for mode in ErrorHandleMode]}"
            )
    
    @classmethod
    def _validate_start_node_id(
        cls,
        node_data: IterationNodeData,
        result: IterationValidationResult
    ) -> None:
        """验证开始节点ID"""
        if not hasattr(node_data, 'start_node_id'):
            result.is_valid = False
            result.errors.append("缺少start_node_id配置")
            return
            
        if not node_data.start_node_id:
            result.is_valid = False
            result.errors.append("start_node_id不能为空")
            return
            
        # 验证节点ID格式（基本格式检查）
        if len(str(node_data.start_node_id).strip()) == 0:
            result.is_valid = False
            result.errors.append("start_node_id不能为空字符串")
    
    @classmethod
    def _log_validation_summary(
        cls,
        result: IterationValidationResult
    ) -> None:
        """记录验证摘要信息"""
        logger.info(
            f"迭代节点验证完成 - 有效: {result.is_valid}, "
            f"错误数: {len(result.errors)}, "
            f"迭代器选择器: {result.iterator_selectors}, "
            f"输出选择器: {result.output_selectors}"
        )
        
        if result.errors:
            logger.error(f"迭代节点验证错误: {result.errors}")
       
    
    