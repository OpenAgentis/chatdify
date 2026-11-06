"""节点模型定义"""
from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional
import re
from copy import deepcopy

from chatdify.utils.logging import get_logger
from chatdify.utils.exceptions import NodeError
from chatdify.models.node_config import NodeConfig

logger = get_logger(__name__)


class NodeErrors:
    def __init__(self):
        self.errors: Dict[str, List[str]] = {}
        self.node_states: Dict[str, bool] = {}
        self.node_types: Dict[str, str] = {}  # 新增：存储节点类型

    def add_error(self, node_id: str, node_type: str, error_msg: str):
        if node_id not in self.errors:
            self.errors[node_id] = []
        self.errors[node_id].append(error_msg)
        self.node_states[node_id] = False
        
        # 存储节点类型
        if node_type:
            self.node_types[node_id] = node_type
    
    def set_node_valid(self, node_id: str, node_type: str, is_valid: bool):
        """设置节点状态
        Args:
            node_id: 节点ID
            is_valid: 节点是否有效
            node_type: 节点类型（可选）
        """
        self.node_states[node_id] = is_valid
        
        # 存储节点类型
        if node_type:
            self.node_types[node_id] = node_type
    
    def set_node_type(self, node_id: str, node_type: str):
        """设置节点类型
        Args:
            node_id: 节点ID
            node_type: 节点类型
        """
        self.node_types[node_id] = node_type
    
    def get_node_type(self, node_id: str) -> str:
        """获取节点类型
        Args:
            node_id: 节点ID
        Returns:
            节点类型，如果不存在则返回空字符串
        """
        return self.node_types.get(node_id, "")
    
    def is_node_valid(self, node_id: str) -> bool:
        """获取节点状态"""
        return self.node_states.get(node_id, True)
    
    def is_all_nodes_valid(self) -> bool:
        """获取所有节点状态"""
        return all(self.node_states.values())
    
    def has_errors(self) -> bool:
        return len(self.errors) > 0
    
    def get_errors_by_type(self, node_type: str) -> Dict[str, List[str]]:
        """根据节点类型获取错误信息
        Args:
            node_type: 节点类型
        Returns:
            该类型节点的错误信息字典
        """
        type_errors = {}
        for node_id, errors in self.errors.items():
            if self.get_node_type(node_id) == node_type:
                type_errors[node_id] = errors
        return type_errors
    
    def get_error_node_types(self) -> List[str]:
        """获取有错误的节点类型列表
        Returns:
            有错误的节点类型列表（去重）
        """
        error_node_types = set()
        
        for node_id in self.errors.keys():
            node_type = self.get_node_type(node_id)
            if node_type:  # 只添加非空的节点类型
                error_node_types.add(node_type)
        
        return list(error_node_types)
    
    def format_errors(self) -> str:
        """格式化错误信息"""
        error_str = ""
        for node_id, errors in self.errors.items():
            node_type = self.get_node_type(node_id)
            error_str += f"节点[node_id: {node_id}, node_type: {node_type}] 存在以下错误:\n"
            for error in errors:
                error_str += f"- {error}\n"
            error_str += "\n"
        return error_str
    
    def format_errors_by_type(self, node_type: str) -> str:
        """根据节点类型格式化错误信息
        Args:
            node_type: 节点类型
        Returns:
            该类型节点的格式化错误信息字符串
        """
        error_str = ""
        type_errors = self.get_errors_by_type(node_type)
        
        if not type_errors:
            return error_str
        
        error_str += f"节点类型 '{node_type}' 的错误信息:\n"
        error_str += "=" * 50 + "\n"
        
        for node_id, errors in type_errors.items():
            error_str += f"节点[node_id: {node_id}] 存在以下错误:\n"
            for error in errors:
                error_str += f"  - {error}\n"
            error_str += "\n"
        
        return error_str


@dataclass
class Node:
    """节点模型，表示工作流中的处理单元"""
    id: str
    data: Dict[str, Any] = field(default_factory=dict)
    parentId: Optional[str] = None
    type: str = "custom"
    zIndex: int = 0
    height: int = 90
    width: int = 244
    position: Dict[str, float] = field(default_factory=dict)
    positionAbsolute: Dict[str, float] = field(default_factory=dict)
   
    def __str__(self) -> str:
        return str(self.to_dict())

    def to_dict(self)-> Dict[str, Any]:
        return {
            "id": self.id,
            "data": self.data.copy(),
            "parentId": self.parentId,
            "type": self.type,
            "zIndex": self.zIndex,
            "height": self.height,
            "width": self.width,
            "position": self.position.copy(),
            "positionAbsolute": self.positionAbsolute.copy()
        }

    def copy(self) -> 'Node':
        """创建节点的深拷贝 
        Returns:
            Node: 复制的节点实例
        """

        # 创建新的节点实例，进行深拷贝
        copied_node = Node(
            id=self.id,
            data=deepcopy(self.data),
            parentId=self.parentId,
            type=self.type,
            zIndex=self.zIndex,
            height=self.height,
            width=self.width,
            position=deepcopy(self.position),
            positionAbsolute=deepcopy(self.positionAbsolute)
        )
        
        return copied_node
    
    @property
    def is_in_iteration(self) -> bool:
        """判断是否在迭代中"""
        return self.data.get("isInIteration", False)
    
    @property
    def is_in_loop(self) -> bool:
        """判断是否在迭代中"""
        return self.data.get("isInLoop", False)
    
    @property
    def iteration_id(self) -> Optional[str]:
        """获取迭代ID"""
        return self.data.get("iteration_id")

    @iteration_id.setter
    def iteration_id(self, value: str) -> None:
        """设置迭代ID"""
        self.data["iteration_id"] = value
        self.parentId = value

    @property
    def loop_id(self) -> Optional[str]:
        """获取迭代ID"""
        return self.data.get("loop_id")
        
    @loop_id.setter
    def loop_id(self, value: str) -> None:
        """设置循环ID"""
        self.data["loop_id"] = value
        self.parentId = value

    def normalize_in_loop(self) -> None:
        """标准化循环内部节点"""
        if not self.is_in_loop:
            return
        
        if self.data.get("type") == "loop-start":
            return
        
        # 验证loop_id
        if not self.loop_id or not self.loop_id.strip():
            raise NodeError(
                f"循环内部节点[{self.id}]必须设置有效的循环ID (loop_id)，"
                f"当前值: {self.loop_id}"
            )
        
        # 标准化parentId
        self.parentId = self.loop_id.strip()
        
        logger.info(f"节点[{self.id}]已标准化为循环内部节点，parentId设置为: {self.parentId}")

    def normalize_in_iteration(self) -> None:
        """标准化迭代内部节点"""
        if not self.is_in_iteration:
            return
        
        if self.data.get("type") == "iteration-start":
            return
    
        # 验证iteration_id
        if not self.iteration_id or not self.iteration_id.strip():
            raise NodeError(
                f"迭代内部节点[{self.id}]必须设置有效的迭代ID (iteration_id)，"
                f"当前值: {self.iteration_id}"
            )
        
        # 标准化parentId
        self.parentId = self.iteration_id.strip()
        
        logger.info(f"节点[{self.id}]已标准化为迭代内部节点，parentId设置为: {self.parentId}")

    def normalize_node_type(self) -> None:
        """标准化节点类型"""
        raw_node_type = self.data.get("type", "")
        if raw_node_type.strip().startswith("tool"):
            self.data["type"] = "tool"
        if not self.type.strip().startswith("custom"):
            self.type = "custom"
    
    def remove_memory_for_llm(self) -> None:
        """当node_type为llm时移除memory字段"""
        if self.data.get("type") == "llm" and "memory" in self.data:
            del self.data["memory"]
    
    def normalize_variable_references(self) -> None:
        """规范化节点中的变量引用格式"""
        self.data = self._normalize_references(self.data)
    
    def normalize_start_node(self) -> None:
        """标准化起始节点"""
        if self.data.get("type") == "start":
            # 处理变量配置，移除select类型变量中多余的multiple字段
            variables = self.data.get("variables", [])
            for variable in variables:
                if isinstance(variable, dict) and variable.get("type") == "select":
                    # 移除多余的multiple字段
                    if "multiple" in variable:
                        del variable["multiple"]
                        logger.info(f"已移除节点[{self.id}]中select类型变量[{variable.get('variable', 'unknown')}]的多余multiple字段")
    
    def _normalize_references(self, data: Any) -> Any:
        """递归规范化变量引用"""
        if isinstance(data, str):
            # 将 {#xxx#} 格式转换为 {{#xxx#}}
            normalized = re.sub(r'(?<!\{)\{#([^{}]+?)#\}', r'{{#\1#}}', data)
            
            # 修复可能存在的错误格式 {{#{xxx}#}}
            normalized = re.sub(r'\{\{#\{([^{}]+?)\}#\}\}', r'{{#\1#}}', normalized)

            # 修复可能存在的错误格式 {{#{xxx}#}}
            normalized = re.sub(r'\{#\{([^{}]+?)\}#\}', r'{{#\1#}}', normalized)
            
            return normalized
        elif isinstance(data, dict):
            return {k: self._normalize_references(v) for k, v in data.items()}
        elif isinstance(data, list):
            return [self._normalize_references(item) for item in data]
        return data
    
    def process_node_config(self) -> None:
        """处理节点配置
        
        获取默认配置并根据节点类型进行处理
        """
        try:
            # 创建配置管理器实例并获取完整配置
            config_manager = NodeConfig(
                node_type=self.data["type"],
                generator_config=self.data
            )
            self.data = config_manager.get_node_config()

            # 处理llm类型的memory字段
            self.remove_memory_for_llm()
            
        except Exception as e:
            logger.error(f"处理节点配置失败: {str(e)}")
            raise NodeError(f"处理节点配置失败: {str(e)}")
        
    @classmethod
    def create(cls, node_data: Dict) -> 'Node':
        """创建节点实例"""
        node_id = node_data.get("id", "")
        try:
            node_data["data"]["type"] = node_data["data"].get("type", "").strip()
            # 创建基础节点
            node = cls(
                id=node_data.get("id", ""),
                data=node_data.get("data", {}),
                parentId=node_data.get("parentId"),
                zIndex=node_data.get("zIndex", 0),
                type=node_data.get("type", "custom"),
                height=node_data.get("height", 90),
                width=node_data.get("width", 244),
                position=node_data.get("position", {}),
                positionAbsolute=node_data.get("positionAbsolute", {})
            )
            
            node.normalize_node_type()
            node.normalize_variable_references()
            node.normalize_in_loop()
            node.normalize_in_iteration()
            node.normalize_start_node()
            
            # 处理节点配置
            node.process_node_config()
            # 返回节点
            return node
            
        except Exception as e:
            error_msg = f"创建节点失败, 节点ID {node_id}: {str(e)}"
            logger.error(error_msg)
            raise NodeError(error_msg)
    
   
   