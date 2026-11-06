"""
边模型定义
"""
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional, Tuple
from copy import deepcopy

from chatdify.utils.exceptions import EdgeError


class EdgeErrors:
    def __init__(self):
        self.errors: Dict[str, List[str]] = {}
    
    def add_error(self, edge_id: str, error_msg: str):
        if edge_id not in self.errors:
            self.errors[edge_id] = []
        self.errors[edge_id].append(error_msg)
    
    def has_errors(self) -> bool:
        return len(self.errors) > 0
    
    def format_errors(self) -> str:
        """格式化错误信息"""
        error_str = ""
        for edge_id, errors in self.errors.items():
            error_str += f"边 {edge_id} 存在以下错误:\n"
            for error in errors:
                error_str += f"- {error}\n"
            error_str += "\n"
        return error_str

        
@dataclass
class Edge:
    """边模型，表示工作流中节点之间的连接"""
    id: str
    source: str
    target: str
    sourceHandle: str = "source"
    targetHandle: str = "target"
    data: Dict[str, Any] = field(default_factory=dict)
    zIndex: int = 0
    sourceDescription: str = ""
    targetDescription: str = ""

    @property
    def source_type(self) -> Optional[str]:
        """获取源节点类型"""
        return self.data.get("sourceType")

    @source_type.setter
    def source_type(self, value: str) -> None:
        """设置源节点类型"""
        self.data["sourceType"] = value 
    
    @property
    def target_type(self) -> Optional[str]:
        """获取目标节点类型"""
        return self.data.get("targetType")
    
    @target_type.setter
    def target_type(self, value: str) -> None:
        """设置目标节点类型"""
        self.data["targetType"] = value
    
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

    @property
    def loop_id(self) -> Optional[str]:
        """获取迭代ID"""
        return self.data.get("loop_id")
        
    @loop_id.setter
    def loop_id(self, value: str) -> None:
        """设置循环ID"""
        self.data["loop_id"] = value
    
    def normalize_zIndex(self) -> None:
        """标准化zIndex值"""
        if self.is_in_iteration or self.is_in_loop:
            self.zIndex = 1002
    
    def normalize_targetType(self, workflow_mode: str='workflow') -> None:
        """标准化目标节点类型"""

        if workflow_mode == 'advanced-chat':
            return

        if self.data["targetType"] == "answer":
            self.data["targetType"] = "end"
  
    def is_valid_edge(self) -> Tuple[bool, List[str]]:
        """检查是否是有效边
        
        Returns:
            Tuple[bool, str]: (是否有效, 错误原因)
        """
        error_reasons = []
        is_valid = True
        
        # 检查基本属性
        if not self.source or not self.target:
            error_reasons.append("边的源节点（source）或目标节点（target）为空，要求不能为空")
            is_valid = False
        
        if self.source == self.target:
            error_reasons.append("边的源节点（source）和目标节点（target）相同，要求不能相同。请重新规划工作流源节点ID和目标节点ID。")
            is_valid = False

        # # 检查目标节点类型限制
        # invalid_target_types = ["start", "iteration-start", "loop-start"]
        # if self.target_type in invalid_target_types:
        #     error_reasons.append(f"目标节点类型不能是 {self.target_type}")
        #     is_invalid = True
            
        # 检查迭代相关规则
        if self.is_in_iteration:
            if not self.iteration_id:
                error_reasons.append("迭代边缺少 iteration_id")
                is_valid = False
            if self.target == self.iteration_id:
                error_reasons.append(f"迭代边的目标节点（target：{self.target}）不能等于迭代节点ID（iteration_id：{self.iteration_id}）")
                is_valid = False
                
        # 检查循环相关规则
        if self.is_in_loop:
            if not self.loop_id:
                error_reasons.append("循环边缺少 loop_id")
                is_valid = False
            if self.target == self.loop_id:
                error_reasons.append(f"循环边的目标节点（target：{self.target}）不能等于循环节点ID（loop_id：{self.loop_id}）")
                is_valid = False
        
        # 返回汇总的错误信息
        return is_valid, error_reasons
    
    @classmethod
    def create(cls, edge_data: Dict[str, Any], workflow_mode: str='workflow') -> Tuple['Edge', bool,  List[str]]:
        """创建边实例
        
        Args:
            edge_data: 边的数据字典
            workflow_mode: 工作流模式，默认是workflow
        Returns:
            Tuple[Edge, bool, Dict[str, str]]: 
                - Edge: 边实例
                - bool: 是否有效
                - Dict[str, str]: {边ID: 错误原因}
        """
        try:
            edge = cls(
                id=str(edge_data.get("id", "")),
                source=str(edge_data.get("source", "")),
                target=str(edge_data.get("target", "")),
                sourceHandle=str(edge_data.get("sourceHandle", "source")),
                targetHandle=str(edge_data.get("targetHandle", "target")),
                data=dict(edge_data.get("data", {})),
                zIndex=int(edge_data.get("zIndex", 0)),
                sourceDescription=str(edge_data.get("sourceDescription", "")),
                targetDescription=str(edge_data.get("targetDescription", ""))
            )

            edge.normalize_zIndex()
            
            # 临时处理。支持chatflow时候需要移除。
            # edge.normalize_targetType(workflow_mode=workflow_mode)
            
            is_valid, error_reason = edge.is_valid_edge()
        
            return edge, is_valid, error_reason
            
        except Exception as e:
            raise EdgeError(f"创建边实例失败: {str(e)}")
           
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典

        Returns:
            Dict[str, Any]: 边的数据字典
        """
        return {
            "id": self.id,
            "source": self.source,
            "target": self.target,
            "sourceHandle": self.sourceHandle,
            "targetHandle": self.targetHandle,
            "data": self.data.copy(),
            "zIndex": self.zIndex   
        }
    
    def to_full_dict(self) -> Dict[str, Any]:
        """转换为全字典

        Returns:
            Dict[str, Any]: 边的数据字典
        """
        return {
            "id": self.id,
            "source": self.source,
            "target": self.target,
            "sourceHandle": self.sourceHandle,
            "targetHandle": self.targetHandle,
            "data": self.data.copy(),
            "zIndex": self.zIndex,
            "sourceDescription": self.sourceDescription,
            "targetDescription": self.targetDescription   
        }
        
    def __str__(self) -> str:
        return str(self.to_dict())
    
    def __hash__(self) -> int:
        return hash(self.id)
    
    def __eq__(self, other: object) -> bool:
        """判断两条边是否相等"""
        if not isinstance(other, Edge):
            return False
        
        return self.id == other.id
    
    def copy(self) -> 'Edge':
        """创建边的深拷贝
            
        Returns:
            Edge: 复制的边实例
        """

        # 创建新的边实例，进行深拷贝
        copied_edge = Edge(
            id=self.id,
            source=self.source,
            target=self.target,
            sourceHandle=self.sourceHandle,
            targetHandle=self.targetHandle,
            data=deepcopy(self.data),
            zIndex=self.zIndex,
            sourceDescription=self.sourceDescription,
            targetDescription=self.targetDescription
        )
        
        return copied_edge