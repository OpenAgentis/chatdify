from typing import Any, Dict, Set
import re
from jinja2 import Environment, TemplateSyntaxError, meta

from chatdify.dify_compat.entities import TemplateTransformNodeData

from .base import BaseNodeValidator, BaseNodeValidationResult

from chatdify.utils.logging import get_logger

logger = get_logger(__name__)


class TemplateTransformNodeValidationResult(BaseNodeValidationResult):
    """模板转换节点验证结果"""
    pass


class TemplateTransformNodeValidator(BaseNodeValidator[TemplateTransformNodeData]):
    """Template Transform 节点验证器"""
    
    @classmethod
    def validate_node(
        cls,
        node_data_config: Dict[str, Any],
        variable_pool: Dict[str, Any],
        **kwargs
    ) -> TemplateTransformNodeValidationResult:
        """
        验证 Template Transform 节点配置
        
        Args:
            node_data_config: 节点配置数据
            variable_pool: 变量池
            
        Returns:
            TemplateTransformNodeValidationResult: 验证结果
        """
        try:
            # 获取节点数据
            node_data = cls._get_node_data(node_data_config)
            
            result = TemplateTransformNodeValidationResult(
                is_valid=True,
                errors=[],
                variable_selectors=set()
            )

            # 基础验证
            cls._validate_basic_requirements(node_data, result)
            
            if not result.is_valid:
                return result

            # 验证变量配置
            cls._validate_variables(node_data, variable_pool, result)
            
            # 验证模板语法和变量引用
            cls._validate_template_syntax_and_variables(node_data, result)
            
            return result
            
        except Exception as e:
            logger.error(f"Template Transform 节点验证异常: {str(e)}")
            return TemplateTransformNodeValidationResult(
                is_valid=False,
                errors=[f"节点验证过程发生异常: {str(e)}"],
                variable_selectors=set()
            )
    
    @classmethod
    def _validate_basic_requirements(
        cls, 
        node_data: TemplateTransformNodeData, 
        result: TemplateTransformNodeValidationResult
    ) -> None:
        """验证基础要求"""
        if not node_data.template or not node_data.template.strip():
            result.is_valid = False
            result.errors.append("模板内容不能为空")
            
        # if not node_data.variables:
        #     result.is_valid = False
        #     result.errors.append("至少需要定义一个变量")
    
    @classmethod
    def _validate_variables(
        cls, 
        node_data: TemplateTransformNodeData, 
        variable_pool: Dict[str, Any],
        result: TemplateTransformNodeValidationResult
    ) -> None:
        """验证变量配置"""
        variable_names = set()
        
        for variable_selector in node_data.variables:
            # 验证变量名
            if not variable_selector.variable or not variable_selector.variable.strip():
                result.is_valid = False
                result.errors.append("变量名不能为空")
                continue
                
            # 检查变量名重复
            if variable_selector.variable in variable_names:
                result.is_valid = False
                result.errors.append(f"变量名重复: {variable_selector.variable}")
            else:
                variable_names.add(variable_selector.variable)
            
            # 验证变量名格式（Jinja2 变量名规则）
            if not cls._is_valid_variable_name(variable_selector.variable):
                result.is_valid = False
                result.errors.append(f"变量名格式无效: {variable_selector.variable}，变量名必须以字母或下划线开头，只能包含字母、数字和下划线")
                
            # 验证变量选择器
            error = cls._validate_variable_exists(
                variable_selector.value_selector,
                variable_pool
            )
            if error:
                result.is_valid = False
                result.errors.append(error)

            # 检查变量选择器重复
            selector_tuple = tuple(variable_selector.value_selector)
            if selector_tuple in result.variable_selectors:
                result.is_valid = False
                result.errors.append(
                    f"变量选择器重复: {variable_selector.variable} 和其他变量引用相同的数据源"
                )
            else:
                result.variable_selectors.add(selector_tuple)
    
    @classmethod
    def _validate_template_syntax_and_variables(
        cls, 
        node_data: TemplateTransformNodeData,
        result: TemplateTransformNodeValidationResult
    ) -> None:
        """验证模板语法和变量引用"""
        try:
            # 验证 Jinja2 语法
            env = Environment()
            template = env.from_string(node_data.template)
            
            # 提取模板中使用的变量
            template_variables = cls._extract_template_variables(node_data.template)
            defined_variables = {vs.variable for vs in node_data.variables}
            
            # 检查模板中引用的变量是否都已定义
            undefined_vars = template_variables - defined_variables
            if undefined_vars:
                result.is_valid = False
                result.errors.append(
                    f"模板中引用了未定义的变量: {sorted(undefined_vars)}"
                )
            
            # # 检查定义的变量是否都被使用
            # unused_vars = defined_variables - template_variables
            # if unused_vars:
            #     result.is_valid = False
            #     result.errors.append(
            #         f"定义了但未在模板中使用的变量: {sorted(unused_vars)}"
            #     )
                
        except TemplateSyntaxError as e:
            result.is_valid = False
            result.errors.append(f"模板Jinja2语法错误: {str(e)}. 仅支持Jinja2语法")
        except Exception as e:
            result.is_valid = False
            result.errors.append(f"模板验证失败: {str(e)}")
    
    @staticmethod
    def _extract_template_variables(template_str: str) -> Set[str]:
        """
        从模板字符串中提取未声明的变量名
        
        Args:
            template_str: 模板字符串
            
        Returns:
            变量名集合
        """
        try:
            env = Environment()
            ast = env.parse(template_str)
            # 使用 jinja2.meta.find_undeclared_variables 来准确提取需要从外部上下文传入的变量
            # 这个方法能正确处理循环变量等在模板内部声明的变量
            return meta.find_undeclared_variables(ast)
        except Exception:
            # 如果AST解析失败，回退到正则表达式
            # 注意：正则表达式无法处理复杂的 Jinja2 语法，例如循环变量，可能会产生不准确的结果
            pattern = r'\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)(?:\.[a-zA-Z_][a-zA-Z0-9_]*)*\s*\}\}'
            matches = re.findall(pattern, template_str)
            # 正则表达式会错误地将 item.name 中的 item 提取出来，这是一个简化回退方法的局限性
            return {match.split('.')[0] for match in matches}

    @staticmethod
    def _is_valid_variable_name(name: str) -> bool:
        """
        检查变量名是否符合 Jinja2 规范
        
        Args:
            name: 变量名
            
        Returns:
            是否有效
        """
        if not name:
            return False
        
        # Jinja2 变量名规则：以字母或下划线开头，只能包含字母、数字和下划线
        pattern = r'^[a-zA-Z_][a-zA-Z0-9_]*$'
        return bool(re.match(pattern, name))
