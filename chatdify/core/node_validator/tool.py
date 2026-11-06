from typing import Any, Dict

from chatdify.dify_compat.entities import ToolNodeData, VariableTemplateParser

from .base import BaseNodeValidator, BaseNodeValidationResult


class ToolNodeValidationResult(BaseNodeValidationResult):
    """Tool节点验证结果"""
    pass


class ToolNodeValidator(BaseNodeValidator[ToolNodeData]):
    """Tool 节点验证器"""
    
    @classmethod
    def validate_node(
        cls,
        node_data_config: Dict[str, Any],
        variable_pool: Dict[str, Any],
        **kwargs
    ) -> ToolNodeValidationResult:
        """
        验证Tool节点配置
        
        Args:
            node_data_config: 节点配置数据
            variable_pool: 变量池
            
        Returns:
            ToolNodeValidationResult: 验证结果
        """
        # 获取节点数据
        node_data = cls._get_node_data(node_data_config)
        
        result = ToolNodeValidationResult(
            is_valid=True,
            errors=[],
            variable_selectors=set()
        )

        # 验证必要字段
        if not node_data.tool_name:
            result.is_valid = False
            result.errors.append("工具名称(tool_name)不能为空")
            return result

        if not node_data.provider_id:
            result.is_valid = False
            result.errors.append("提供者ID(provider_id)不能为空")
            return result

        try:
            # 验证工具参数
            for param_name, tool_input in node_data.tool_parameters.items():
                # 验证参数类型
                if tool_input.type not in ["mixed", "variable", "constant"]:
                    result.is_valid = False
                    result.errors.append(f"参数 {param_name} 的类型无效")
                    continue

                # 验证变量引用
                if tool_input.type == "variable":
                    if not isinstance(tool_input.value, list):
                        result.is_valid = False
                        result.errors.append(f"参数 {param_name} 的变量值必须是列表")
                        continue
                        
                    result.variable_selectors.add(tuple(tool_input.value))
                    error = cls._validate_variable_exists(tuple(tool_input.value), variable_pool)
                    if error:
                        result.is_valid = False
                        result.errors.append(error)
                        
                # 验证混合类型
                elif tool_input.type == "mixed":
                    if not isinstance(tool_input.value, str):
                        result.is_valid = False
                        result.errors.append(f"参数 {param_name} 的混合值必须是字符串")
                        continue
                        
                    try:
                        variable_template_parser = VariableTemplateParser(template=tool_input.value)
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
                        result.errors.append(f"参数 {param_name} 的变量模板解析失败: {str(e)}")

                # 验证常量类型
                elif tool_input.type == "constant":
                    if not isinstance(tool_input.value, (str, int, float, bool)):
                        result.is_valid = False
                        result.errors.append(f"参数 {param_name} 的常量值类型无效")
                        
        except Exception as e:
            result.is_valid = False
            result.errors.append(f"工具参数验证过程发生错误: {str(e)}")
            
        return result