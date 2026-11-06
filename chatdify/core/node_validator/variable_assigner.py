from typing import Any, Dict, Set, Tuple
from dataclasses import dataclass, field

from chatdify.dify_compat.entities import (
    InputType,
    Operation,
    SegmentType,
    VariableAssignerNodeData,
    VariableOperationItem,
)
from chatdify.dify_compat.entities import variable_assigner_helpers as helpers

from .base import BaseNodeValidator, BaseNodeValidationResult

from chatdify.utils.logging import get_logger

logger = get_logger(__name__)


@dataclass
class VariableAssignerNodeValidationResult(BaseNodeValidationResult):
    """变量赋值节点验证结果"""
    operation_items: Set[Tuple[str, ...]] = field(default_factory=set)  # 存储操作项信息


class VariableAssignerNodeValidator(BaseNodeValidator[VariableAssignerNodeData]):
    """Variable Assigner 节点验证器"""
    
    @classmethod
    def validate_node(
        cls,
        node_data_config: Dict[str, Any],
        variable_pool: Dict[str, Any],
        **kwargs
    ) -> VariableAssignerNodeValidationResult:
        """
        验证 Variable Assigner 节点配置
        
        Args:
            node_data_config: 节点配置数据
            variable_pool: 变量池
            
        Returns:
            VariableAssignerNodeValidationResult: 验证结果
        """
        try:
            # 获取节点数据
            node_data = cls._get_node_data(node_data_config)
            
            result = VariableAssignerNodeValidationResult(
                is_valid=True,
                errors=[],
                variable_selectors=set(),
                operation_items=set()
            )
            
            # 验证基础配置
            cls._validate_basic_config(node_data, result)
            
            if not result.is_valid:
                return result
            
            # 已声明的会话/环境变量类型映射 {name: value_type}（完整 DSL 校验时可用；
            # 生成阶段会话变量尚未声明，则为 None，退化为按操作的类型无关校验）
            conversation_variable_types = kwargs.get("conversation_variable_types")

            # 验证每个操作项
            cls._validate_operation_items(node_data, variable_pool, result, conversation_variable_types)
            
            return result
            
        except Exception as e:
            logger.error(f"变量赋值节点验证过程发生错误: {str(e)}", exc_info=True)
            return VariableAssignerNodeValidationResult(
                is_valid=False,
                errors=[f"变量赋值节点验证过程发生错误: {str(e)}"],
                variable_selectors=set(),
                operation_items=set()
            )
    
    @classmethod
    def _validate_basic_config(
        cls,
        node_data: VariableAssignerNodeData,
        result: VariableAssignerNodeValidationResult
    ) -> None:
        """验证基础配置"""
        # 验证节点数据完整性
        if not hasattr(node_data, 'items'):
            result.is_valid = False
            result.errors.append("缺少变量操作项配置")
            return
            
        if not node_data.items:
            result.is_valid = False
            result.errors.append("变量操作项列表不能为空")
            return
            
        # 验证版本
        if hasattr(node_data, 'version') and node_data.version != "2":
            result.errors.append(f"警告：当前版本为 {node_data.version}，建议使用版本 2")
    
    @classmethod
    def _validate_operation_items(
        cls,
        node_data: VariableAssignerNodeData,
        variable_pool: Dict[str, Any],
        result: VariableAssignerNodeValidationResult,
        conversation_variable_types: Dict[str, Any] | None = None
    ) -> None:
        """验证操作项列表"""
        for i, item in enumerate(node_data.items):
            item_prefix = f"操作项 {i + 1}"
            
            # 验证单个操作项
            cls._validate_single_operation_item(
                item, variable_pool, result, item_prefix, conversation_variable_types
            )
            
            # 记录操作项信息
            if item.variable_selector:
                result.operation_items.add(tuple(item.variable_selector))
    
    @classmethod
    def _validate_single_operation_item(
        cls,
        item: VariableOperationItem,
        variable_pool: Dict[str, Any],
        result: VariableAssignerNodeValidationResult,
        item_prefix: str,
        conversation_variable_types: Dict[str, Any] | None = None
    ) -> None:
        """验证单个操作项"""
        # 验证变量选择器
        cls._validate_variable_selector(item, variable_pool, result, item_prefix)
        
        # 验证操作类型
        cls._validate_operation_type(item, result, item_prefix)
        
        # 验证输入类型
        cls._validate_input_type_config(item, result, item_prefix)
        
        # 验证操作-变量类型-输入方式的兼容性（faithful to dify v2）
        cls._validate_operation_variable_compatibility(
            item, variable_pool, result, item_prefix, conversation_variable_types
        )
        
        # 验证输入值
        cls._validate_input_value(
            item, variable_pool, result, item_prefix, conversation_variable_types
        )
    
    @classmethod
    def _validate_variable_selector(
        cls,
        item: VariableOperationItem,
        variable_pool: Dict[str, Any],
        result: VariableAssignerNodeValidationResult,
        item_prefix: str
    ) -> None:
        """验证变量选择器"""
        if not item.variable_selector:
            result.is_valid = False
            result.errors.append(f"{item_prefix}: 变量选择器不能为空")
            return
        
        # 验证选择器格式
        if not cls._validate_selector_format(item.variable_selector):
            result.is_valid = False
            result.errors.append(f"{item_prefix}: 变量选择器格式无效")
            return
        
        # 验证变量是否存在
        error = cls._validate_variable_exists(item.variable_selector, variable_pool)
        if error:
            result.is_valid = False
            result.errors.append(f"{item_prefix}: {error}")
            return
        
        result.variable_selectors.add(tuple(item.variable_selector))
    
    @classmethod
    def _validate_operation_type(
        cls,
        item: VariableOperationItem,
        result: VariableAssignerNodeValidationResult,
        item_prefix: str
    ) -> None:
        """验证操作类型"""
        try:
            # 检查操作是否在枚举中
            if item.operation not in Operation:
                result.is_valid = False
                result.errors.append(
                    f"{item_prefix}: 不支持的操作类型 '{item.operation}'，"
                    f"支持的操作: {', '.join([op.value for op in Operation])}"
                )
        except (ValueError, TypeError):
            result.is_valid = False
            result.errors.append(f"{item_prefix}: 操作类型格式无效 '{item.operation}'")
    
    @classmethod
    def _validate_input_type_config(
        cls,
        item: VariableOperationItem,
        result: VariableAssignerNodeValidationResult,
        item_prefix: str
    ) -> None:
        """验证输入类型配置"""
        try:
            # 检查输入类型是否在枚举中
            if item.input_type not in InputType:
                result.is_valid = False
                result.errors.append(
                    f"{item_prefix}: 不支持的输入类型 '{item.input_type}'，"
                    f"支持的类型: {', '.join([t.value for t in InputType])}"
                )
        except (ValueError, TypeError):
            result.is_valid = False
            result.errors.append(f"{item_prefix}: 输入类型格式无效 '{item.input_type}'")
    
    # 算术类操作（仅 number 支持）
    _ARITHMETIC_OPS = (Operation.ADD, Operation.SUBTRACT, Operation.MULTIPLY, Operation.DIVIDE)
    # 不需要提供值的操作
    _NO_VALUE_OPS = (Operation.CLEAR, Operation.REMOVE_FIRST, Operation.REMOVE_LAST)
    # 仅数组变量才支持的操作（出现这些操作即可断定目标是数组类型，与是否已声明类型无关）
    _ARRAY_ONLY_OPS = (
        Operation.APPEND, Operation.EXTEND, Operation.REMOVE_FIRST, Operation.REMOVE_LAST
    )

    @classmethod
    def _as_segment_type(cls, type_str: Any) -> "SegmentType | None":
        """chatdify 的会话变量类型字符串(如 'array[string]') -> dify SegmentType；无法识别返回 None。"""
        if not type_str:
            return None
        if isinstance(type_str, SegmentType):
            return type_str
        try:
            return SegmentType(str(type_str))
        except ValueError:
            return None

    @classmethod
    def _as_operation(cls, operation: Any) -> "Operation | None":
        """把操作规范化为 Operation 枚举；非法返回 None（由 _validate_operation_type 报告）。"""
        if isinstance(operation, Operation):
            return operation
        try:
            return Operation(operation)
        except (ValueError, TypeError):
            return None

    @classmethod
    def _resolve_target_type(
        cls,
        selector: list,
        conversation_variable_types: Dict[str, Any] | None
    ) -> "SegmentType | None":
        """解析 assigner 目标变量的 SegmentType。

        assigner 只能写入会话/环境变量（conversation.* / env.*）；其类型取自已声明的
        conversation_variable_types。生成阶段尚未声明时返回 None（不臆测类型，避免误报）。
        """
        if not selector or len(selector) < 2 or selector[0] not in ("conversation", "env"):
            return None
        if not conversation_variable_types:
            return None
        return cls._as_segment_type(conversation_variable_types.get(selector[1]))

    @classmethod
    def _validate_operation_variable_compatibility(
        cls,
        item: VariableOperationItem,
        variable_pool: Dict[str, Any],
        result: VariableAssignerNodeValidationResult,
        item_prefix: str,
        conversation_variable_types: Dict[str, Any] | None = None
    ) -> None:
        """按 dify v2 规则校验 操作-变量类型-输入方式 的兼容性（顺序与 dify node.py 一致）。"""
        op = cls._as_operation(item.operation)
        if op is None:
            return  # 操作类型本身非法，已由 _validate_operation_type 报告

        target_type = cls._resolve_target_type(item.variable_selector, conversation_variable_types)

        # (a) 该变量类型是否支持此操作（仅在目标类型已知时校验）
        if target_type is not None and not helpers.is_operation_supported(
            variable_type=target_type, operation=op
        ):
            result.is_valid = False
            result.errors.append(
                f"{item_prefix}: 变量类型 '{target_type.value}' 不支持操作 '{op.value}'。"
                f"（number 支持 over-write/set/+=/-=/*=//=；string/boolean/object 仅支持 over-write/set；"
                f"array[*] 支持 over-write/append/extend/remove-first/remove-last/clear）"
            )
            return

        # (b) 变量(variable)输入是否被该操作支持（与类型无关：set/+=/-=/*=//= 不接受变量输入）
        if item.input_type == InputType.VARIABLE and not helpers.is_variable_input_supported(operation=op):
            result.is_valid = False
            result.errors.append(
                f"{item_prefix}: 操作 '{op.value}' 不支持变量(variable)输入，只能用常量(constant)输入。"
            )
            return

        # (c) 常量(constant)输入是否被该 类型+操作 支持（仅在目标类型已知时校验）
        if (
            item.input_type == InputType.CONSTANT
            and target_type is not None
            and not helpers.is_constant_input_supported(variable_type=target_type, operation=op)
        ):
            result.is_valid = False
            result.errors.append(
                f"{item_prefix}: 变量类型 '{target_type.value}' 的操作 '{op.value}' 不支持常量(constant)输入。"
            )
            return

        # (d) 类型无关兜底（覆盖生成阶段会话变量尚未声明、target_type 未知的情况）：
        #     dify 中数组类型变量的任何操作都不支持常量输入(is_constant_input_supported: array -> False)，
        #     必须用变量(variable)引用输入。下面两种情形即使不知道声明类型也能断定目标是数组：
        if item.input_type == InputType.CONSTANT and target_type is None:
            # d1. append/extend/remove-* 是数组专属操作 -> 目标必为数组 -> 常量输入非法
            if op in cls._ARRAY_ONLY_OPS:
                result.is_valid = False
                result.errors.append(
                    f"{item_prefix}: 数组变量的 '{op.value}' 操作必须使用变量(variable)引用输入"
                    f"（如引用 code/llm 节点的输出），不接受常量(constant)输入。"
                )
                return
            # d2. over-write 的常量值是数组字面量 -> 目标必为数组 -> 常量输入非法
            if op == Operation.OVER_WRITE and isinstance(item.value, list):
                result.is_valid = False
                result.errors.append(
                    f"{item_prefix}: 用常量数组 over-write 会话变量不被支持；"
                    f"数组变量须用变量(variable)引用输入（如引用 code 节点拼好的数组输出）。"
                )
                return

    @classmethod
    def _validate_input_value(
        cls,
        item: VariableOperationItem,
        variable_pool: Dict[str, Any],
        result: VariableAssignerNodeValidationResult,
        item_prefix: str,
        conversation_variable_types: Dict[str, Any] | None = None
    ) -> None:
        """验证输入值（目标类型已知时 faithful to dify is_input_value_valid，未知时退化为按操作校验取值形状）。"""
        op = cls._as_operation(item.operation)
        if op is None:
            return

        # 这些操作不需要值
        if op in cls._NO_VALUE_OPS:
            return

        if item.value is None:
            result.is_valid = False
            result.errors.append(f"{item_prefix}: 操作 '{op.value}' 需要提供值")
            return

        # 变量输入：仅校验引用存在性（具体值类型由运行期解析）
        if item.input_type == InputType.VARIABLE:
            if isinstance(item.value, (list, tuple)):
                value_error = cls._validate_variable_exists(list(item.value), variable_pool)
                if value_error:
                    result.is_valid = False
                    result.errors.append(f"{item_prefix}: 引用变量错误 - {value_error}")
            return

        # 常量输入
        target_type = cls._resolve_target_type(item.variable_selector, conversation_variable_types)
        if target_type is not None:
            if not helpers.is_input_value_valid(
                variable_type=target_type, operation=op, value=item.value
            ):
                result.is_valid = False
                result.errors.append(
                    f"{item_prefix}: 输入值 {item.value!r} 与变量类型 '{target_type.value}' / 操作 '{op.value}' 不匹配。"
                )
            return

        # 目标类型未知（会话变量在生成阶段尚未声明）：按操作隐含的取值形状做类型无关校验
        cls._validate_constant_value_shape_by_operation(op, item.value, result, item_prefix)

    @classmethod
    def _validate_constant_value_shape_by_operation(
        cls,
        op: "Operation",
        value: Any,
        result: VariableAssignerNodeValidationResult,
        item_prefix: str
    ) -> None:
        """仅依据操作即可确定的取值形状校验（不依赖目标变量声明类型）。

        - +=/-=/*=//=：值必须是数字；/= 的值不能为 0。
        - append：值必须是单个元素（字符串/数字/布尔/对象），不能是数组。
        - extend：值必须是数组。
        - over-write/set：取值形状取决于变量类型，类型未知时不做形状校验。
        """
        if op in cls._ARITHMETIC_OPS:
            if not isinstance(value, (int, float)):
                result.is_valid = False
                result.errors.append(
                    f"{item_prefix}: 算术操作 '{op.value}' 的值必须是数字(number)，当前为 {value!r}"
                )
            elif op == Operation.DIVIDE and value == 0:
                result.is_valid = False
                result.errors.append(f"{item_prefix}: 除法操作 '/=' 的值不能为 0")
        elif op == Operation.APPEND:
            if not isinstance(value, (str, int, float, bool, dict)):
                result.is_valid = False
                result.errors.append(
                    f"{item_prefix}: append 的值应为单个元素(字符串/数字/布尔/对象)，不能是数组，当前为 {value!r}"
                )
        elif op == Operation.EXTEND:
            if not isinstance(value, list):
                result.is_valid = False
                result.errors.append(
                    f"{item_prefix}: extend 的值必须是数组，当前为 {value!r}"
                )