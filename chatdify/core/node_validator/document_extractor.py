from collections.abc import Sequence
from typing import Optional, Any, Dict
from dataclasses import dataclass

from chatdify.dify_compat.entities import (
    DocumentExtractorNodeData,
)

from chatdify.models.node import Node
from .base import BaseNodeValidator, BaseNodeValidationResult


@dataclass
class DocumentExtractorNodeValidationResult(BaseNodeValidationResult):
    """DocumentExtractor节点验证结果"""
    pass


class DocumentExtractorNodeValidator(BaseNodeValidator[DocumentExtractorNodeData]):
    """DocumentExtractor节点验证器"""
    
    # 定义不被接受的上游节点类型
    UNSUPPORTED_UPSTREAM_NODE_TYPES = {
        "question-classifier",
        "llm", 
        "code",
        "parameter-extractor",
        "tool"
    }
    
    @classmethod
    def validate_node(
        cls,
        node_data_config: Dict[str, Any],
        variable_pool: Dict[str, Any],
        **kwargs
    ) -> DocumentExtractorNodeValidationResult:
        """
        验证DocumentExtractor节点配置
        
        Args:
            node_data_config: 节点配置数据
            variable_pool: 变量池
            
        Returns:
            DocumentExtractorNodeValidationResult: 验证结果
        """
        # 获取节点数据
        node_data = cls._get_node_data(node_data_config)
        
        result = DocumentExtractorNodeValidationResult(
            is_valid=True,
            errors=[],
            variable_selectors=set()
        )

        # 验证变量选择器
        if not hasattr(node_data, 'variable_selector') or not node_data.variable_selector:
            result.is_valid = False
            result.errors.append("变量选择器variable_selector不能为空")
            return result
            
        # 添加到变量选择器集合
        result.variable_selectors.add(tuple(node_data.variable_selector))
        
        error = cls._validate_variable_exists(
            node_data.variable_selector,
            variable_pool
        )

        if error:
            result.is_valid = False
            result.errors.append(error)
            return result
        
        # 需要从variable_pool中获取对应的节点信息
        node_id = node_data.variable_selector[0]
        if node_id in variable_pool:
            node = variable_pool[node_id]
            
            # 验证上游节点类型
            upstream_type_error = cls._validate_upstream_node_type(node)
            if upstream_type_error:
                result.is_valid = False
                result.errors.append(upstream_type_error)
                result.should_abort = True
                return result
           
            reference_error = cls._validate_reference_start_variable(
                node_data.variable_selector,
                node
            )
            
            if reference_error:
                result.is_valid = False
                result.errors.append(reference_error)
                result.should_abort = True  # 设置中止标志
                return result
              
        return result
    
    @classmethod
    def _validate_upstream_node_type(cls, node: Node) -> Optional[str]:
        """
        验证上游节点类型是否被DocumentExtractor节点支持
        
        Args:
            node: 上游节点
            
        Returns:
            str: 如果验证失败返回错误信息，否则返回None
        """
        node_type = node.data.get("type")
        
        # 检查是否为不支持的节点类型
        if node_type in cls.UNSUPPORTED_UPSTREAM_NODE_TYPES:
            return (
                f"上游节点类型错误: DocumentExtractor节点不能接受'{node_type}'类型的上游节点。"
                f"DocumentExtractor节点通常应该连接到start节点，"
                f"不支持的上游节点类型包括: {', '.join(sorted(cls.UNSUPPORTED_UPSTREAM_NODE_TYPES))}。"
                f"请检查工作流设计，如果上游节点没问题。则说明当前场景不应该使用DocumentExtractor类型节点，请尝试选择其他类型节点。"
            )
        
        return None
        
    @classmethod
    def _validate_reference_start_variable(cls, selector: Sequence[str], node: Node) -> Optional[str]:
        """
        验证引用start节点变量是否符合规范
        Args:
            node: 节点
            selector: 选择器
        Returns:
            str: 如果验证失败返回错误信息，否则返回None
        """
        
        node_id = node.id
        node_type = node.data.get("type")
        output_name = ".".join(selector[1:])
        
        # DocumentExtractor特有的校验：如果引用的是start节点
        if node_type == "start":
            # 获取start节点的变量配置
            node_variables = node.data.get("variables", [])
            
            # 查找对应的变量配置
            target_variable = None
            for var in node_variables:
                if isinstance(var, dict) and var.get("variable") == output_name:
                    target_variable = var
                    break
            
            if target_variable:
                # 检查变量类型是否为file或file-list
                var_type = target_variable.get("type")
                if var_type not in ["file", "file-list"]:
                    return (
                        f"变量类型错误: '{'.'.join(selector)}' - "
                        f"DocumentExtractor节点只能引用文件类型的变量，"
                        f"变量 '{output_name}' 的类型为 '{var_type}'，"
                        f"必须是 'file' 或 'file-list' 类型。"
                        f"请仔细检查start节点, "
                        f"如果start节点信息没有错，则说明当前场景不应该使用DocumentExtractor类型节点，请尝试选择其他类型节点"
                    )
                
                # 检查allowed_file_types是否包含document
                allowed_file_types = target_variable.get("allowed_file_types", [])

                if "custom" in allowed_file_types:
                    return None
                
                if "document" not in allowed_file_types:
                    return (
                        f"文件类型错误: '{'.'.join(selector)}' - "
                        f"DocumentExtractor节点要求引用的start节点变量 '{output_name}' "
                        f"的allowed_file_types必须包含'document'类型，"
                        f"当前start节点的allowed_file_types为: {allowed_file_types}。"
                        f"请仔细检查start节点, "
                        f"如果start节点信息没有错，则说明当前场景不应该使用DocumentExtractor类型节点，请尝试选择其他类型节点"
                    )
                
                # 检查是否包含不支持的文件类型（如image、video等）
                unsupported_types = [t for t in allowed_file_types if t not in ["document"]]
                if unsupported_types:
                    return (
                        f"文件类型错误: '{'.'.join(selector)}' - "
                        f"DocumentExtractor节点不支持引用包含以下文件类型的start节点变量: {unsupported_types}。"
                        f"请确保变量 '{output_name}' 的allowed_file_types仅包含'document'类型。"
                        f"请仔细检查start节点, "
                        f"如果start节点信息没有错，则说明当前场景不应该使用DocumentExtractor类型节点，请尝试选择其他类型节点"
                    )
        
        return None