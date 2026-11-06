from collections.abc import Sequence
from typing import Set, Tuple, Any, Dict
from dataclasses import dataclass, field
from .base import BaseNodeValidator, BaseNodeValidationResult
from chatdify.models.node import Node

from chatdify.dify_compat.entities import LLMNodeData, VariableSelector, VariableTemplateParser


# vision 只接受文件类型变量；这些 start 变量类型视为文件
_FILE_VAR_TYPES = frozenset({"file", "file-list"})
# 这些节点的输出明确是文本/对象，绝不可能是文件，可直接判定非文件
_TEXT_OUTPUT_NODE_TYPES = frozenset({
    "llm", "agent", "question-classifier", "template-transform",
    "document-extractor", "knowledge-retrieval",
})


@dataclass
class LLMNodeValidationResult(BaseNodeValidationResult):
    """LLM节点验证结果"""
    jinja2_variable_selectors: Set[Tuple[str, ...]] = field(default_factory=set)  # 存储jinja2变量选择器


class LLMNodeValidator(BaseNodeValidator[LLMNodeData]):
    """LLM节点验证器"""
    
    @classmethod
    def validate_node(
        cls,
        node_data_config: Dict[str, Any],
        variable_pool: Dict[str, Any],
        **kwargs
    ) -> LLMNodeValidationResult:
        """
        验证LLM节点配置
        
        Args:
            node_data: 节点数据
            variable_pool: 变量池
            
        Returns:
            LLMNodeValidationResult: 验证结果
        """
        # 获取节点数据
        node_data = cls._get_node_data(node_data_config)
        
        result = LLMNodeValidationResult(
            is_valid=True,
            errors=[],
            variable_selectors=set(),
            jinja2_variable_selectors=set()
        )

        # 验证prompt_template中的变量选择器
        cls._validate_prompt_template(
            node_data=node_data,
            variable_pool=variable_pool,
            result=result
        )

        # 验证jinja2变量
        if node_data.prompt_config and node_data.prompt_config.jinja2_variables:
            cls._validate_jinja2_variables(
                variables=node_data.prompt_config.jinja2_variables,
                variable_pool=variable_pool,
                result=result
            )

        # 验证vision配置
        if node_data.vision and node_data.vision.enabled:
            cls._validate_vision_config(
                node_data=node_data,
                variable_pool=variable_pool,
                result=result
            )

        # 验证context配置
        if node_data.context.enabled:
            cls._validate_context_config(
                node_data=node_data,
                variable_pool=variable_pool,
                result=result
            )
        
        # 验证变量选择器不为空
        error = cls._validate_variable_selectors_not_empty(result)
        if error:
            result.is_valid = False
            result.errors.append(error)

        return result

    @staticmethod
    def _validate_prompt_template(
        node_data: LLMNodeData,
        variable_pool: dict,
        result: LLMNodeValidationResult
    ) -> None:
        """验证prompt模板"""
        if isinstance(node_data.prompt_template, list):
            # Chat模式
            for message in node_data.prompt_template:
                if not message.text and not message.jinja2_text:
                    result.is_valid = False
                    result.errors.append("提示词模板不能为空")
                    continue

                template = message.jinja2_text if message.edition_type == "jinja2" else message.text
                variable_template_parser = VariableTemplateParser(template=template)
                selectors = variable_template_parser.extract_variable_selectors()
                
                for selector in selectors:
                    result.variable_selectors.add(tuple(selector.value_selector))
                    error = LLMNodeValidator._validate_variable_exists(
                        selector.value_selector,
                        variable_pool
                    )
                    if error:
                        result.is_valid = False
                        result.errors.append(error)
        else:
            # Completion模式
            template = (node_data.prompt_template.jinja2_text 
                       if node_data.prompt_template.edition_type == "jinja2" 
                       else node_data.prompt_template.text)
            
            if not template:
                result.is_valid = False
                result.errors.append("提示词模板不能为空")
                return
                
            variable_template_parser = VariableTemplateParser(template=template)
            selectors = variable_template_parser.extract_variable_selectors()
            
            for selector in selectors:
                result.variable_selectors.add(tuple(selector.value_selector))
                error = LLMNodeValidator._validate_variable_exists(
                    selector.value_selector,
                    variable_pool
                )
                if error:
                    result.is_valid = False
                    result.errors.append(error)

    @staticmethod
    def _validate_jinja2_variables(
        variables: Sequence[VariableSelector],
        variable_pool: dict,
        result: LLMNodeValidationResult
    ) -> None:
        """验证jinja2变量"""
        for variable in variables:
            if not variable.variable:
                result.is_valid = False
                result.errors.append("变量名不能为空")
                continue
                
            if not variable.value_selector:
                result.is_valid = False
                result.errors.append(f"变量 '{variable.variable}' 的选择器路径不能为空")
                continue

            result.jinja2_variable_selectors.add(tuple(variable.value_selector))
            error = LLMNodeValidator._validate_variable_exists(
                variable.value_selector,
                variable_pool
            )
            if error:
                result.is_valid = False
                result.errors.append(error)

    @staticmethod
    def _validate_vision_config(
        node_data: LLMNodeData,
        variable_pool: dict,
        result: LLMNodeValidationResult
    ) -> None:
        """验证vision配置"""
        if not node_data.vision.configs or not node_data.vision.configs.variable_selector:
            result.is_valid = False
            result.errors.append("Vision变量选择器不能为空")
            return
            
        selector = VariableSelector(
            variable="vision_files",
            value_selector=list(node_data.vision.configs.variable_selector)
        )
        result.variable_selectors.add(tuple(selector.value_selector))
        
        error = LLMNodeValidator._validate_variable_exists(
            selector.value_selector,
            variable_pool
        )
        if error:
            result.is_valid = False
            result.errors.append(error)
            return

        # 校验 vision 目标必须是文件类型变量（file / file-list / array[file]）
        file_status = LLMNodeValidator._resolve_selector_is_file(
            selector.value_selector, variable_pool
        )
        if file_status == "not_file":
            result.is_valid = False
            result.errors.append(
                f"Vision变量选择器 '{'.'.join(selector.value_selector)}' 指向的不是文件类型变量。"
                f"LLM vision 只能引用 file / file-list / array[file] 类型（通常是 start 节点的图片变量）；"
                f"不能引用 object/array[object]/字符串等类型，也不能引用 code 节点输出或值为 object 的迭代 item"
                f"（运行期会报错 Invalid variable type: ObjectVariable / Type is not JSON serializable: File）。"
                f"请将 vision 直接指向 start 节点的图片文件变量；多模型场景应让 iteration 遍历模型名数组，"
                f"vision 仍引用 start 节点的图片，不要用 code 打包文件。"
            )

    @staticmethod
    def _resolve_selector_is_file(
        selector: Sequence[str], variable_pool: dict
    ) -> str:
        """
        判断 selector 指向的变量是否为文件类型。

        返回 'file'（file/file-list/array[file]）、'not_file'（明确非文件）、
        'unknown'（无法判定，放行避免误报）。
        """
        if not selector or len(selector) < 2:
            return "unknown"
        head = selector[0]
        if head in ("sys", "env", "conversation"):
            return "unknown"
        node = variable_pool.get(head) if isinstance(variable_pool, dict) else None
        if not isinstance(node, Node):
            return "unknown"

        node_type = node.data.get("type")
        field_name = selector[1].split(".")[0]

        if node_type == "start":
            for var in node.data.get("variables", []):
                if isinstance(var, dict) and var.get("variable") == field_name:
                    return "file" if var.get("type") in _FILE_VAR_TYPES else "not_file"
            return "unknown"

        if node_type == "code":
            # code 节点不支持 file 输出，任何已声明输出字段都不是文件
            outputs = node.data.get("outputs", {}) or {}
            return "not_file" if field_name in outputs else "unknown"

        if node_type == "list-operator":
            if field_name in ("result", "first_record", "last_record"):
                var_type = node.data.get("var_type") or ""
                if var_type == "array[file]":
                    return "file"
                if var_type.startswith("array["):
                    return "not_file"
            return "unknown"

        if node_type == "iteration":
            if field_name == "item":
                return LLMNodeValidator._resolve_array_element_is_file(
                    node.data.get("iterator_selector"), variable_pool
                )
            if field_name == "output":
                output_type = node.data.get("output_type") or ""
                if output_type == "array[file]":
                    return "file"
                if output_type.startswith("array["):
                    return "not_file"
            return "unknown"

        if node_type in _TEXT_OUTPUT_NODE_TYPES:
            return "not_file"

        return "unknown"

    @staticmethod
    def _resolve_array_element_is_file(
        selector: Sequence[str], variable_pool: dict
    ) -> str:
        """判断 selector 指向的数组变量，其元素是否为文件类型（用于解析 iteration.item）。"""
        if not selector or len(selector) < 2:
            return "unknown"
        head = selector[0]
        if head in ("sys", "env", "conversation"):
            return "unknown"
        node = variable_pool.get(head) if isinstance(variable_pool, dict) else None
        if not isinstance(node, Node):
            return "unknown"

        node_type = node.data.get("type")
        field_name = selector[1].split(".")[0]

        if node_type == "start":
            for var in node.data.get("variables", []):
                if isinstance(var, dict) and var.get("variable") == field_name:
                    # file-list 的元素才是 file；单个 file 不作为可迭代数组来源
                    return "file" if var.get("type") == "file-list" else "not_file"
            return "unknown"

        if node_type == "code":
            # code 输出的 array[*] 元素均非文件
            outputs = node.data.get("outputs", {}) or {}
            return "not_file" if field_name in outputs else "unknown"

        if node_type == "list-operator":
            var_type = node.data.get("var_type") or ""
            if var_type == "array[file]":
                return "file"
            if var_type.startswith("array["):
                return "not_file"
            return "unknown"

        if node_type in _TEXT_OUTPUT_NODE_TYPES:
            return "not_file"

        return "unknown"

    @staticmethod
    def _validate_context_config(
        node_data: LLMNodeData,
        variable_pool: dict,
        result: LLMNodeValidationResult
    ) -> None:
        """验证context配置"""
        if not node_data.context.variable_selector:
            result.is_valid = False
            result.errors.append("Context变量选择器不能为空")
            return
            
        selector = VariableSelector(
            variable="context",
            value_selector=list(node_data.context.variable_selector)
        )
        result.variable_selectors.add(tuple(selector.value_selector))
        
        error = LLMNodeValidator._validate_variable_exists(
            selector.value_selector,
            variable_pool
        )
        if error:
            result.is_valid = False
            result.errors.append(error)
