from typing import Dict, List, Optional, Any, Literal
from dataclasses import dataclass
from enum import Enum
from pydantic import BaseModel
from .base import BaseNodeValidator, BaseNodeValidationResult
from chatdify.utils.logging import get_logger

from chatdify.dify_compat.entities import (
    IfElseNodeData,
    SubCondition,
    SupportedComparisonOperator,
    VariableTemplateParser,
)
from chatdify.dify_compat.entities import Condition as BaseCondition



logger = get_logger(__name__)


class ExtendedCondition(BaseCondition):
    """扩展的条件类，添加前端专用字段（后端 Condition 不含这些字段）"""
    varType: Optional[str] = None
    # number 类型比较值的来源：'variable'(值为 {{#node.field#}} 变量引用) 或 'constant'(字面量数字)
    numberVarType: Optional[str] = None


class ExtendedSubCondition(SubCondition):
    """扩展的子条件类，添加varType字段"""
    varType: Optional[str] = None


class ExtendedIfElseNodeData(IfElseNodeData):
    """扩展的IfElseNodeData类"""
    class ExtendedCase(BaseModel):
        """扩展的Case类"""
        case_id: str
        logical_operator: Literal["and", "or"]
        conditions: List[ExtendedCondition]

    cases: Optional[list[ExtendedCase]] = None


@dataclass
class IfElseValidationResult(BaseNodeValidationResult):
    """If-Else节点验证结果"""
    pass


class VariableType(Enum):
    """变量类型枚举"""
    STRING = "string"
    NUMBER = "number"
    BOOLEAN = "boolean"
    FILE = "file"
    NONE = "none"


# Dify 前端 if-else 条件支持的全部 varType 取值（用于结构性校验，避免对未知类型直接崩溃）
KNOWN_VAR_TYPES = {
    "string", "number", "boolean", "object", "file", "secret",
    "array[string]", "array[number]", "array[object]", "array[file]",
    "array[boolean]", "array[any]",
}


class IfElseNodeValidator(BaseNodeValidator[ExtendedIfElseNodeData]):
    """If-Else节点验证器"""
    
    # 不同类型变量支持的操作符映射
    OPERATOR_TYPE_MAPPING = {
        VariableType.STRING: {
            "contains", "not contains", "start with", "end with",
            "is", "is not", "empty", "not empty", "in", "not in"
        },
        VariableType.NUMBER: {
            "=", "≠", ">", "<", "≥", "≤", "null", "not null"
        },
        VariableType.FILE: {
            "exists", "not exists", "all of"
        },
        VariableType.BOOLEAN: {
            "is", "is not", "empty", "not empty"
        }
    }
    
    @classmethod
    def validate_node(
        cls,
        node_data_config: Dict[str, Any],
        variable_pool: Dict[str, Any],
        **kwargs
    ) -> IfElseValidationResult:
        """验证If-Else节点配置"""

        node_data = ExtendedIfElseNodeData.model_validate(node_data_config)
        result = super().validate_node(node_data, variable_pool)
        
        source_handles = set(kwargs.get("source_handles", []))
        logger.info(f"source_handles: {source_handles}")

        # 验证cases
        if not node_data.cases:
            result.is_valid = False
            result.errors.append("cases不能为空")
            return result
            
        # 验证每个case
        for case in node_data.cases:
            # 验证case_id
            if not case.case_id:
                result.is_valid = False
                result.errors.append("case_id不能为空")
                continue
            
            if case.case_id not in source_handles:
                result.is_valid = False
                result.errors.append(
                    f"case_id {case.case_id} 不正确, 必须和边信息中对应的sourceHandle值保持一致\n"
                    f"当前边信息中对应的sourceHandle值列表为: {source_handles}"
                    )
    
            if not case.conditions:
                result.is_valid = False
                result.errors.append(f"case {case.case_id} 的conditions不能为空")
                continue
                
            # 验证每个condition
            for condition in case.conditions:
                # 验证variable_selector
                if not condition.variable_selector:
                    result.is_valid = False
                    result.errors.append("variable_selector不能为空")
                    continue
                    
                result.variable_selectors.add(tuple(condition.variable_selector))
                error = cls._validate_variable_exists(
                        condition.variable_selector,
                        variable_pool
                    )
                if error:
                    result.is_valid = False
                    result.errors.append(error)
                
                # if not condition.value:
                #     result.is_valid = False
                #     result.errors.append("value不能为空")
                #     continue

                # value 可能为 None（empty/not empty/null/not null 等无需比较值的操作符）
                value_is_variable_ref = False
                if isinstance(condition.value, str) and condition.value:
                    variable_template_parser = VariableTemplateParser(template=condition.value)
                    selectors = variable_template_parser.extract_variable_selectors()
                    value_is_variable_ref = len(selectors) > 0

                    for selector in selectors:
                        result.variable_selectors.add(tuple(selector.value_selector))

                        error = cls._validate_variable_exists(
                            selector.value_selector,
                            variable_pool
                        )
                        if error:
                            result.is_valid = False
                            result.errors.append(error)
    
                # 验证操作符
                if not condition.comparison_operator:
                    result.is_valid = False
                    result.errors.append("comparison_operator不能为空")
                    continue

                # 获取变量类型
                if not condition.varType:
                    result.is_valid = False
                    result.errors.append("varType不能为空")
                    continue

                var_type_raw = condition.varType

                # 校验 numberVarType：仅 number 类型需要，且必须与 value 是否为变量引用保持一致
                cls._validate_number_var_type(
                    var_type_raw, condition.numberVarType, value_is_variable_ref, result
                )

                # 结构性校验：未知 varType 直接拦截，避免 VariableType(...) 抛异常崩溃
                if var_type_raw not in KNOWN_VAR_TYPES:
                    result.is_valid = False
                    result.errors.append(
                        f"varType的值错误: '{var_type_raw}' 不是合法的变量类型, "
                        f"合法取值为: {sorted(KNOWN_VAR_TYPES)}"
                    )
                    continue

                # 仅对基础标量类型(string/number/boolean/file)做操作符-类型匹配校验；
                # array[*]/object/secret 等类型的操作符集合不在此强约束，避免误报。
                try:
                    var_type = VariableType(var_type_raw)
                except ValueError:
                    continue

                # 验证操作符是否支持当前变量类型
                if not cls._is_operator_supported(condition.comparison_operator, var_type):
                    result.is_valid = False
                    result.errors.append(
                        f"comparison_operator的值错误: "
                        f"varType: {var_type.value} 不支持操作符 {condition.comparison_operator}, "
                        f"支持的操作符有: {cls.OPERATOR_TYPE_MAPPING.get(var_type, set())}, "
                        f"请修正comparison_operator的值"
                    ) 
                    continue
                    
                # # 验证子条件
                # if isinstance(variable, ArrayFileSegment) and condition.sub_variable_condition:
                #     cls._validate_sub_conditions(
                #         condition.sub_variable_condition.conditions,
                #         result
                #     )
                
        return result
    
    @classmethod
    def _validate_number_var_type(
        cls,
        var_type_raw: Optional[str],
        number_var_type: Optional[str],
        value_is_variable_ref: bool,
        result: IfElseValidationResult,
    ) -> None:
        """
        校验 number 类型条件的 numberVarType 字段。

        Dify 前端在 varType=number 时用 numberVarType 区分比较值来源：
          - 'variable'：value 是变量引用，如 '{{#10000001.total_rounds#}}'
          - 'constant'：value 是字面量数字，如 '3'
        缺失或与 value 实际形态不一致会导致前端无法正确渲染/绑定变量。
        """
        if var_type_raw != "number":
            return

        if number_var_type not in ("variable", "constant"):
            result.is_valid = False
            result.errors.append(
                "numberVarType不能为空：当varType为number时，必须设置numberVarType，"
                "取值为'variable'(比较值是变量引用)或'constant'(比较值是字面量数字)。"
            )
            return

        # 比较值是 {{#...#}} 变量引用，numberVarType 必须为 variable
        if value_is_variable_ref and number_var_type != "variable":
            result.is_valid = False
            result.errors.append(
                "numberVarType的值错误：value是变量引用(形如'{{#节点ID.字段#}}')时，"
                "numberVarType必须为'variable'，否则前端会把它当作常量字符串导致比较失效。"
            )
            return

        # numberVarType 声明为 variable，但 value 不是变量引用
        if (not value_is_variable_ref) and number_var_type == "variable":
            result.is_valid = False
            result.errors.append(
                "numberVarType的值错误：numberVarType为'variable'时，value必须是变量引用"
                "(形如'{{#节点ID.字段#}}')；若比较的是字面量数字请改为'constant'。"
            )

    @classmethod
    def _is_operator_supported(
        cls, 
        operator: SupportedComparisonOperator, 
        var_type: VariableType
        ) -> bool:

        return operator in cls.OPERATOR_TYPE_MAPPING.get(var_type, set())
       
    @classmethod
    def _validate_sub_conditions(
        cls,
        conditions: List[SubCondition],
        result: IfElseValidationResult
    ) -> None:
        """验证子条件"""
        for condition in conditions:
            if not condition.key:
                result.is_valid = False
                result.errors.append("子条件的key不能为空")
                continue
                
            if not condition.comparison_operator:
                result.is_valid = False
                result.errors.append("子条件的comparison_operator不能为空")
                continue
