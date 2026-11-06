from typing import Optional, Sequence, Set, Any, Dict
from dataclasses import dataclass
from .base import BaseNodeValidator, BaseNodeValidationResult
from chatdify.utils.py_syntax_validator import MainFunctionValidator
from chatdify.models.node import Node

from chatdify.dify_compat.entities import CodeNodeData, CodeNodeError, VariableSelector


_FILE_SOURCE_TYPES = frozenset({"file", "file-list"})


@dataclass
class CodeNodeValidationResult(BaseNodeValidationResult):
    """Code节点验证结果"""
    pass

   
class CodeNodeValidator(BaseNodeValidator[CodeNodeData]):
    """Code节点验证器"""
    
    @classmethod
    def validate_node(
        cls,
        node_data_config: Dict[str, Any],
        variable_pool: Dict[str, Any],
        **kwargs
    ) -> CodeNodeValidationResult:
        """
        验证Code节点配置
        
        Args:
            node_data_config: 节点数据配置
            variable_pool: 变量池
            
        Returns:
            CodeNodeValidationResult: 验证结果
        """
        # 获取节点数据
        node_data = cls._get_node_data(node_data_config)

        result = super().validate_node(node_data, variable_pool)
        
        # 验证变量选择器列表
        try:
            cls._validate_variables(node_data.variables)
        except CodeNodeError as e:
            result.is_valid = False
            result.errors.append(str(e))
            return result
            
        # 验证变量选择器唯一性和存在性
        cls._validate_variable_selectors(node_data.variables, variable_pool, result)

        # 禁止引用 file / file-list 类型变量作为输入
        cls._validate_no_file_input(node_data.variables, variable_pool, result)
        cls._validate_no_file_output(node_data.outputs, result)
        
        # 验证代码语法和主函数
        code_syntax_validate_result = cls._validate_code_syntax(node_data.code, result)
        
        # 验证输出配置与代码返回值的一致性
        if code_syntax_validate_result:
            cls._validate_output_consistency(code_syntax_validate_result, node_data.outputs, result)
            cls._validate_output_types(code_syntax_validate_result, node_data.outputs, result)
        
        return result
    
    @classmethod
    def _validate_variable_selectors(
        cls, 
        variables: Sequence[VariableSelector], 
        variable_pool: Dict[str, Any], 
        result: CodeNodeValidationResult
    ) -> None:
        """验证变量选择器唯一性和存在性"""
        for variable_selector in variables:
            # 检查变量选择器重复
            selector_tuple = tuple(variable_selector.value_selector)
            if selector_tuple in result.variable_selectors:
                result.is_valid = False
                error_msg = f"变量选择器重复：{variable_selector.variable} 和其他变量引用相同路径 {variable_selector.value_selector}"
                result.errors.append(error_msg)
            else:
                result.variable_selectors.add(selector_tuple)
            
            # 验证变量是否存在
            error = cls._validate_variable_exists(variable_selector.value_selector, variable_pool)
            if error:
                result.is_valid = False
                result.errors.append(error)
    
    @classmethod
    def _validate_code_syntax(cls, code: str, result: CodeNodeValidationResult) -> Optional[Dict[str, Any]]:
        """验证代码语法和主函数"""
        
        # 验证主函数
        try:
            code_validator = MainFunctionValidator()
            code_syntax_validate_result = code_validator.validate_code(code)
            if not code_syntax_validate_result["valid"]:
                result.is_valid = False
                result.errors.extend(code_syntax_validate_result["errors"])

                return code_syntax_validate_result
               
        except Exception as e:
            result.is_valid = False
            error_msg = f"主函数验证失败：{str(e)}"
            result.errors.append(error_msg)
            return None
          
    
    @classmethod
    def _validate_output_consistency(
        cls, 
        code_syntax_result: Dict[str, Any], 
        output_config: Dict[str, Any], 
        result: CodeNodeValidationResult
    ) -> None:
        """
        验证代码返回值与输出配置的一致性
        
        参数:
            code_syntax_result: 代码语法验证结果，包含返回分析
            output_config: 节点输出配置
            result: 验证结果对象
        """
        try:
            # 检查是否有返回分析数据
            if not code_syntax_result.get('return_analysis'):
                return
                
            analysis = code_syntax_result['return_analysis']
            
            # 检查返回一致性
            if not analysis.get('consistency', {}).get('consistent', False):
                return
                
            # 获取正常返回的变量集合
            normal_returns = analysis.get('normal_returns', [])
            if not normal_returns:
                return
                
            return_vars = set(normal_returns[0])
            config_vars = set(output_config.keys())

            if 'error' in config_vars:
                result.is_valid = False
                result.errors.append(
                    f"code节点输出配置（outputs）不能包含'error'命名字段。请用其他名字替代，比如'err'。"
                )
            
            # 比较返回变量和配置变量
            missing_in_config = return_vars - config_vars
            missing_in_code = config_vars - return_vars
            
            # 记录不一致情况
            if missing_in_config:
                result.is_valid = False
                result.errors.append(
                    f"输出配置(outputs)中缺少了在代码中返回的变量: {sorted(missing_in_config)}。请在输出配置(outputs)中增加这些变量。"
                )
                
            if missing_in_code:
                result.is_valid = False
                result.errors.append(
                    f"输出配置(outputs)中定义了代码未返回的变量: {sorted(missing_in_code)}。请在输出配置(outputs)中移除这些变量。"
                )
                
        except Exception as e:
            result.is_valid = False
            result.errors.append(
                f"代码返回值与输出配置(outputs)的一致性验证异常: {str(e)}"
            )

    # outputs 声明类型 -> 代码推断类型是否兼容（仅覆盖 dify 运行期会强制校验的类型，
    # 避免静态层比 dify 更严而误报）。
    # 注意：boolean 不在此表——dify code_node._transform_result 对 BOOLEAN 输出不做类型强制，
    #       故对 boolean 声明不做静态拦截（否则会产生 dify 运行期并不会报的假阳性）。
    _OUTPUT_TYPE_COMPAT: Dict[str, frozenset] = {
        "string": frozenset({"str"}),
        "number": frozenset({"int", "float", "bool"}),  # dify 会把 bool 转 int
        "object": frozenset({"dict"}),
        "array[string]": frozenset({"list"}),
        "array[number]": frozenset({"list"}),
        "array[boolean]": frozenset({"list"}),
        "array[object]": frozenset({"list"}),
    }

    @classmethod
    def _output_type_compatible(cls, declared: str, inferred: str) -> bool:
        allowed = cls._OUTPUT_TYPE_COMPAT.get(declared)
        if allowed is None:
            return True
        return inferred in allowed

    @classmethod
    def _format_output_type_mismatch_hint(cls, declared: str, inferred: str) -> str:
        if declared == "string" and inferred == "bool":
            return "布尔标志位应声明 boolean 并 return True/False，或改 return 为字符串"
        if declared == "string" and inferred in ("int", "float"):
            return "数值结果应声明 number，或在 return 前 str() 转换"
        if declared == "number" and inferred == "str":
            return "应 return 数字，或改 outputs 为 string"
        if declared == "object" and inferred != "dict":
            return "应 return 字典对象"
        if declared.startswith("array[") and inferred != "list":
            return "应 return 列表"
        return "请让 outputs 声明类型与 main() return 的 Python 类型一致"

    @classmethod
    def _validate_output_types(
        cls,
        code_syntax_result: Dict[str, Any],
        output_config: Dict[str, Any],
        result: CodeNodeValidationResult,
    ) -> None:
        """静态校验 outputs 声明类型与 main() return 推断类型是否兼容。"""
        try:
            analysis = code_syntax_result.get("return_analysis") or {}
            entry_types: Dict[str, Set[str]] = analysis.get("return_entry_types") or {}
            if not entry_types:
                return

            for output_name, output_def in output_config.items():
                declared = (
                    output_def.get("type")
                    if isinstance(output_def, dict)
                    else getattr(output_def, "type", None)
                )
                if not declared:
                    continue
                declared = str(declared)
                inferred_set = entry_types.get(output_name)
                if not inferred_set:
                    continue

                # 只要存在与声明类型不兼容的推断类型即报错；多种推断类型若都兼容
                # （如 number 同时出现 int/float）则不报，避免误报。
                incompatible = sorted(
                    t for t in inferred_set if not cls._output_type_compatible(declared, t)
                )
                if incompatible:
                    result.is_valid = False
                    bad = incompatible[0]
                    result.errors.append(
                        f"输出 '{output_name}' 声明为 {declared}，但代码推断返回 {'/'.join(incompatible)}；"
                        f"{cls._format_output_type_mismatch_hint(declared, bad)}"
                    )
        except Exception as e:
            result.is_valid = False
            result.errors.append(f"outputs 类型静态校验异常: {str(e)}")

    @classmethod
    def _resolve_selector_source_type(
        cls, selector: Sequence[str], variable_pool: Dict[str, Any]
    ) -> Optional[str]:
        """解析变量选择器上游字段的类型（仅识别 file / file-list 来源）。"""
        if len(selector) < 2 or selector[0] not in variable_pool:
            return None
        node = variable_pool[selector[0]]
        if not isinstance(node, Node):
            return None

        node_type = node.data.get("type")
        field_name = selector[1].split(".")[0]

        if node_type == "start":
            for var in node.data.get("variables", []):
                if isinstance(var, dict) and var.get("variable") == field_name:
                    var_type = var.get("type")
                    if var_type in _FILE_SOURCE_TYPES:
                        return var_type
            return None

        if node_type == "http-request" and field_name == "files":
            return "file-list"

        if node_type == "tool" and field_name == "files":
            return "file-list"

        return None

    @classmethod
    def _validate_no_file_input(
        cls,
        variables: Sequence[VariableSelector],
        variable_pool: Dict[str, Any],
        result: CodeNodeValidationResult,
    ) -> None:
        """禁止 Code 节点 variables 引用 file / file-list 类型上游变量。"""
        try:
            for variable in variables:
                source_type = cls._resolve_selector_source_type(
                    variable.value_selector, variable_pool
                )
                if source_type not in _FILE_SOURCE_TYPES:
                    continue
                selector = ".".join(variable.value_selector)
                result.is_valid = False
                result.errors.append(
                    f"输入变量 '{variable.variable}' 引用了文件类型上游 '{selector}'（{source_type}），"
                    f"Code 节点不支持 file / file-list 类型输入。"
                    f"请从 variables 和 main() 参数中移除该变量；"
                )
        except Exception as e:
            result.is_valid = False
            result.errors.append(f"File 输入静态校验异常: {str(e)}")

    @classmethod
    def _validate_no_file_output(
        cls,
        output_config: Dict[str, Any],
        result: CodeNodeValidationResult,
    ) -> None:
        """禁止 Code 节点 outputs 声明 file 类型。"""
        try:
            for output_name, output_def in output_config.items():
                declared = (
                    output_def.get("type")
                    if isinstance(output_def, dict)
                    else getattr(output_def, "type", None)
                )
                if declared and str(declared) in _FILE_SOURCE_TYPES:
                    result.is_valid = False
                    result.errors.append(
                        f"输出 '{output_name}' 声明 type 为 {declared}，Code 节点不支持 file / file-list 类型输出"
                    )
        except Exception as e:
            result.is_valid = False
            result.errors.append(f"File 输出静态校验异常: {str(e)}")
    
    @staticmethod
    def _validate_variables(variables: Sequence[VariableSelector]) -> None:
        """验证变量选择器列表"""
        if not variables:
            return 
            # raise CodeNodeError("变量选择器列表不能为空")
            
        # 验证变量名唯一性
        variable_names = set()
        for variable in variables:
            if not variable.variable:
                raise CodeNodeError("变量名不能为空")
                
            if variable.variable in variable_names:
                raise CodeNodeError(f"变量名 '{variable.variable}' 重复")
                
            variable_names.add(variable.variable)
            
        # 验证选择器路径
        for variable in variables:
            if not variable.value_selector:
                raise CodeNodeError(f"变量 '{variable.variable}' 的选择器路径不能为空")
                
            # 验证选择器路径中的每个部分
            for selector in variable.value_selector:
                if not isinstance(selector, str):
                    raise CodeNodeError(
                        f"变量 '{variable.variable}' 的选择器路径包含无效类型: {type(selector)}"
                    )
                if not selector.strip():
                    raise CodeNodeError(
                        f"变量 '{variable.variable}' 的选择器路径包含空字符串"
                    )
