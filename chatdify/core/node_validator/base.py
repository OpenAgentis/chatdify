from dataclasses import dataclass, field
from typing import Set, Tuple, List, Optional, Sequence, TypeVar, Generic, Any, Dict

from chatdify.models.node import Node
from chatdify.utils.logging import get_logger


logger = get_logger(__name__)


T = TypeVar('T')


@dataclass
class BaseNodeValidationResult:
    """节点验证基础结果类"""
    is_valid: bool = True
    errors: List[str] = field(default_factory=list)
    variable_selectors: Set[Tuple[str, ...]] = field(default_factory=set)  # 存储提取的variable_selector
    should_abort: bool = False  # 验证失败时是否中止后续验证


class BaseNodeValidator(Generic[T]):
    """节点验证器基类"""
    
    @classmethod
    def validate_node(cls, node_data_config: dict, variable_pool: dict, **kwargs) -> BaseNodeValidationResult:
        """
        验证节点配置的基础方法
        
        Args:
            node_data: 节点数据
            variable_pool: 变量池
            
        Returns:
            BaseNodeValidationResult: 验证结果
        """
        result = BaseNodeValidationResult(
            is_valid=True,
            errors=[],
            variable_selectors=set(),
            should_abort = False
        )
        return result
    
    @classmethod
    def _validate_variable_exists(
        cls,
        selector: Sequence[str],
        variable_pool: dict
    ) -> Optional[str]:
        """验证变量是否存在于变量池中"""

        if not variable_pool:
            return None
            
        current = variable_pool
    
        error = cls._validate_selector_length(selector)
        if error:
            return error
        
        #验证选择器是否在变量池中
        # 如果是sys等类型，特殊处理；
        if selector[0] in ["sys", "env", "conversation"]:
            return None
            
        error = cls._validate_selector_in_variable_pool(
            selector,
            variable_pool
        )
        if error:
            return error
    
        node = current[selector[0]]
        error = cls._validate_node_type_referenceable(selector, node)
        if error:
            return error

        error = cls._validate_reference_variable_name(selector, node)
        if error:
            return error

        return None
    
    @classmethod
    def _validate_selector_in_variable_pool(
        cls,
        selector: Sequence[str],
        variable_pool: dict
    ) -> Optional[str]:
        """验证选择器是否存在于变量池中
        
        Args:
            selector: 选择器序列
            variable_selector: 变量选择器对象
            variable_pool: 变量池
            
        Returns:
            Optional[str]: 如果验证失败返回错误信息，否则返回None
        """
        if selector[0] not in variable_pool:
            return (
                f"变量引用错误: '{'.'.join(selector)}' - "
                f"节点 '{selector[0]}' 不是当前节点的前置节点。"
                f"请仔细检查任务工作流上下文，从可用前置节点列表中选择, 可用前置节点列表: {', '.join(list(variable_pool.keys()))}"
            )
        return None

    @classmethod
    def _validate_node_type_referenceable(cls, selector: Sequence[str], node: Node) -> Optional[str]:
        """验证节点类型是否可以被引用
        
        Args:
            node_type: 节点类型
            node_id: 节点ID
            
        Returns:
            Optional[str]: 如果验证失败返回错误信息，否则返回None
        """

        node_id = node.id
        node_type = node.data.get("type")

        non_referenceable_types = {
            "if-else",    # 条件节点
            "loop-start", # 循环开始节点
            "iteration-start",  # 迭代开始节点
            "assigner", # 赋值节点
        }

        if node_type == "iteration-start":
            iteration_id = node.parentId
            correct_selector = [iteration_id, selector[1]]
            return (
                f"变量引用错误: '{'.'.join(selector)}' - "
                f"(节点ID: {node_id}, 节点类型: '{node_type}') 不能被作为变量引用。"
                f"正确的变量引用建议使用: '{'.'.join(correct_selector)}'。"
            )
        
        if node_type in non_referenceable_types:
            return (
                f"变量引用错误: '{'.'.join(selector)}' - "
                f"(节点ID: {node_id}, 节点类型: '{node_type}') 不能被作为变量引用。"
                f"请仔细检查任务工作流上下文， 选择正确的变量引用。"
            )
            
        return None

    @classmethod
    def _validate_reference_variable_name(cls, selector: Sequence[str], node: Node) -> Optional[str]:
        """验证引用节点变量的变量名称是否符合规范
        
        Args:
            node: 节点
            selector: 选择器
        Returns:
            str: 如果验证失败返回错误信息，否则返回None
        """
        output_rules = {
            # "http-request": "body",
            "llm": "text",
            "document-extractor": "text",
            "agent": "text",
            "variable-aggregator": "output",
            "template-transform": "output",
            "question-classifier": "class_name",
            "knowledge-retrieval": "result",
        }

        node_id = node.id
        node_type = node.data.get("type")
        output_name = ".".join(selector[1:])
        
        if node_type == "start":
            # 从 variables 字段提取可用的输出变量
            node_variables = node.data.get("variables", [])
            available_outputs = set()
            
            # 提取所有变量的 variable 字段作为可用输出
            for var in node_variables:
                if isinstance(var, dict) and "variable" in var:
                    available_outputs.add(var["variable"])
            
            # 如果有可用输出但引用的变量不在其中，返回错误
            output_name = output_name.split(".")[0]
            if available_outputs and output_name not in available_outputs:
                return (
                    f"输出变量错误: '{'.'.join(selector)}' - "
                    f"节点 '{node_id}' (类型: {node_type}) 的可用输出为: {sorted(available_outputs)}，"
                    f"而不是: '{output_name}'"
                )
            
        if node_type == "iteration" and output_name not in ["item", "index", "output"]:
           return ( 
                f"变量引用错误: '{'.'.join(selector)}' - "
                f"(节点ID: {node_id}, 节点类型: '{node_type}') 的输出变量名必须为 item （迭代内部引用）或者 output（迭代外部引用）, 而不是 '{output_name}' 。"
                f"iteration类型节点，不支持iteration类型节点.item.xx的引用方式。"
                f"如果确定需要引用iteration节点的item内部子变量，"
                f"请考虑添加相应处理节点（比如code节点）对item变量进行处理。将处理后的节点输出给到当前节点。"
            )

        if node_type == "list-operator":
            allowed_outputs = {"result", "first_record", "last_record"}
            output_field = output_name.split(".")[0]
            if output_field not in allowed_outputs:
                if output_field == "item":
                    return (
                        f"变量引用错误: '{'.'.join(selector)}' - "
                        f"(节点ID: {node_id}, 节点类型: '{node_type}') 无 item 输出；"
                        f"list-operator 可用输出为 result（过滤后的数组）、first_record、last_record。"
                        f"item 仅用于 iteration 节点在迭代内部的引用。"
                    )
                return (
                    f"输出变量错误: '{'.'.join(selector)}' - "
                    f"节点 '{node_id}' (类型: {node_type}) 的可用输出为: {sorted(allowed_outputs)}，"
                    f"而不是: '{output_field}'"
                )
            if "." in output_name:
                return (
                    f"变量引用错误: '{'.'.join(selector)}' - "
                    f"(节点ID: {node_id}, 节点类型: '{node_type}') 不支持 '{output_name}' 的点号展开；"
                    f"请直接引用 result、first_record 或 last_record。"
                )
        
        if node_type == "code":
            node_outputs = node.data.get("outputs", {})
            available_outputs = set(node_outputs.keys())
            
            if available_outputs and output_name not in available_outputs:
                return (
                    f"输出变量错误: '{'.'.join(selector)}' - "
                    f"节点 '{node_id}' (类型: {node_type}) 的可用输出为: {sorted(available_outputs)}，"
                    f"而不是: '{output_name}'"
                )
        
        if node_type == "parameter-extractor":
            node_outputs = node.data.get("parameters", [])
            available_outputs = set([param["name"] for param in node_outputs])
            
            if available_outputs and output_name not in available_outputs:
                return (
                    f"输出变量错误: '{'.'.join(selector)}' - "
                    f"节点 '{node_id}' (类型: {node_type}) 的可用输出为: {sorted(available_outputs)}，"
                    f"而不是: '{output_name}'"
                )
        
        if node_type == "tool":
            tool_name = node.data.get("tool_name", "")
            if tool_name.startswith("md_to_"):
                if output_name not in ["files"]:
                    return (
                        f"输出变量错误: '{'.'.join(selector)}' - "
                        f"节点 '{node_id}' (类型: {node_type}, 工具名称: {tool_name}) 的可用输出为: ['files']，"
                        f"而不是: '{output_name}'"
                    )
        if node_type == "loop":
            # 从loop节点获取loop_variables
            loop_variables = node.data.get("loop_variables", [])

            available_outputs = set([var["label"] for var in loop_variables if isinstance(var, dict) and "label" in var])
            if available_outputs and output_name not in available_outputs:
                return (
                    f"输出变量错误: '{'.'.join(selector)}' - "
                    f"节点 '{node_id}' (类型: {node_type}) 的可用输出为: {sorted(available_outputs)}，"
                    f"而不是: '{output_name}'"
                )

        # 如果节点类型在规则中且输出名称不符合规则
        if node_type in output_rules and output_name != output_rules[node_type]:
            return ( 
                f"变量引用错误: '{'.'.join(selector)}' - "
                f"(节点ID: {node_id}, 节点类型: '{node_type}') 的输出变量名必须为 '{output_rules[node_type]}, 而不是 '{output_name}' 。"
            )
        return None
    
    @classmethod
    def _validate_variable_selectors_not_empty(
        cls,
        result: BaseNodeValidationResult
    ) -> Optional[str]:
        """验证变量选择器不为空"""
        if not result.variable_selectors:
            return ("变量选择器不能为空, 至少包含一个输入。请检查节点配置")

        return None
        
    @classmethod
    def _validate_selector_length(cls, selector: Sequence[str]) -> Optional[str]:
        """验证选择器长度"""
        if len(selector) < 2:
            return (
                f"变量引用错误: '{'.'.join(selector)}' - "
                f"变量引用路径长度必须大于等于2。"
            )
        
        return None
    
    @staticmethod
    def _validate_selector_format(selector: Sequence[str]) -> bool:
        """验证选择器格式"""
        if not selector:
            return False
        return all(isinstance(part, str) and part.strip() for part in selector)
        
    @staticmethod
    def _validate_selector_naming(variable_name: str) -> bool:
        """验证选择器命名"""
        if not variable_name:
            return False
        return variable_name.isidentifier()
        
    @classmethod
    def _get_node_data(cls, config: Dict[str, Any]) -> Optional[Any]:
        """获取节点数据
        
        Args:
            config: 节点配置数据，必须包含 type 字段
            
        Returns:
            Any: 验证后的节点数据模型实例
            
        Raises:
            ValueError: 当配置数据无效时抛出
            KeyError: 当缺少必要字段时抛出
        """
        try:
            if not isinstance(config, dict):
                raise ValueError("配置数据必须是字典类型")
                
            node_type = config.get('type')
            if not node_type:
                raise KeyError("配置数据缺少 'type' 字段")
                
            from chatdify.dify_compat.entities import get_node_class, get_node_data_cls

            if not get_node_class(node_type):
                raise ValueError(f"未找到节点类型 '{node_type}' 对应的类")

            node_data_cls = get_node_data_cls(node_type)
            if not node_data_cls:
                raise ValueError(f"节点类型 '{node_type}' 没有节点数据类定义")
                
            return node_data_cls.model_validate(config)
            
        except Exception as e:
            raise ValueError(f"节点数据验证失败: {str(e)}")