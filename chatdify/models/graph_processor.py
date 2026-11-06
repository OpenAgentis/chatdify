"""
图处理器模块
图构建和遍历相关功能
"""
from typing import List, Dict, Any, Tuple
from collections import deque

from chatdify.utils.logging import get_logger
from chatdify.models.edge import Edge
from chatdify.utils.exceptions import WorkflowError


logger = get_logger(__name__)


class GraphProcessor:
    """图处理器类，负责图的构建、环检测和遍历"""
    
    def __init__(self, edges: List[Edge]):
        """
        初始化图处理器
        
        Args:
            edges: 边的列表
        """
        self.edges = edges
        self.graph_data = {}
        # 新增：维护iteration和loop的内部节点关系
        self.iteration_internal_nodes = {}  # {iteration_id: [internal_node_ids]}
        self.loop_internal_nodes = {}       # {loop_id: [internal_node_ids]}
        self.node_to_iteration = {}         # {node_id: iteration_id}
        self.node_to_loop = {}              # {node_id: loop_id}

    def build_graph(self) -> Dict[str, Any]:
        """构建图
        
        Returns:
            Dict[str, Any]: 图数据结构
        """
        logger.info(f"开始构建图, 边数量: {len(self.edges)}")

        # 构建iteration和loop内部节点关系
        self._build_internal_node_relationships()

        # 修正边
        self.edges = self._correct_edges(self.edges)

        # 环移除最多迭代次数：避免 _remove_cycle_edges 未删到边或边集异常时 while 死循环
        _initial_edge_count = len(self.edges)
        _max_cycle_removal_rounds = max(_initial_edge_count, 1) * 2
        _cycle_removal_rounds = 0
        _last_cycles: List[List[str]] = []

        while True:  # 循环直到没有环为止
            adj_list = {}
            in_degrees = {}
            node_related_edges = {}
            reverse_adj_list = {}
            node_types = {}
            node_descriptions = {}
           
            if not self.edges:
                logger.error("没有边, 无法构建图")
                raise WorkflowError("没有边, 无法构建图")
               
            # 初始化
            for edge in self.edges:
                adj_list[edge.source] = adj_list.get(edge.source, [])
                adj_list[edge.target] = adj_list.get(edge.target, [])
                in_degrees[edge.source] = in_degrees.get(edge.source, 0)
                in_degrees[edge.target] = in_degrees.get(edge.target, 0)
                node_related_edges[edge.source] = node_related_edges.get(edge.source, [])
                node_related_edges[edge.target] = node_related_edges.get(edge.target, []) 
                reverse_adj_list[edge.source] = reverse_adj_list.get(edge.source, [])
                reverse_adj_list[edge.target] = reverse_adj_list.get(edge.target, [])
                
                if edge.source not in node_types:
                    node_types[edge.source] = edge.source_type
                if edge.target not in node_types:
                    node_types[edge.target] = edge.target_type
                
                if edge.source not in node_descriptions or not node_descriptions[edge.source]:
                    node_descriptions[edge.source] = edge.sourceDescription
                if edge.target not in node_descriptions or not node_descriptions[edge.target]:
                    node_descriptions[edge.target] = edge.targetDescription
                
            # 构建图数据
            for edge in self.edges:
                node_related_edges[edge.source].append(edge)
                node_related_edges[edge.target].append(edge)
                reverse_adj_list[edge.target].append(edge.source)
                adj_list[edge.source].append(edge.target)
                in_degrees[edge.target] += 1

                # 处理特殊节点的连接关系(iteration和loop)
                if edge.is_in_loop or edge.is_in_iteration:
                    control_flow_id = edge.loop_id if edge.is_in_loop else edge.iteration_id
                    if control_flow_id:
                        # 记录控制流节点的内部边
                        node_related_edges[control_flow_id].append(edge)
                        
                        # 更新控制流节点的邻接关系
                        if edge.source_type and edge.source_type.endswith('start'):
                            adj_list[control_flow_id].append(edge.source)
                            reverse_adj_list[edge.source].append(control_flow_id)
                            in_degrees[edge.source] += 1
                 
            # 检测环
            has_cycle, cycles = self._detect_cycles(adj_list)

            if has_cycle:
                _last_cycles = cycles
                _cycle_removal_rounds += 1
                if _cycle_removal_rounds > _max_cycle_removal_rounds:
                    msg = (
                        f"移除环边超过最大迭代次数 ({_max_cycle_removal_rounds})，仍无法得到无环图；"
                        f"初始边数={_initial_edge_count}，当前边数={len(self.edges)}，"
                        f"最后一次环信息={_last_cycles}"
                    )
                    logger.error(msg)
                    raise WorkflowError(msg)
                # 移除环边并重新构建图
                logger.warning(f"检测到环结构，环信息：{cycles}")
                self.edges = self._remove_cycle_edges(cycles)
                logger.warning(f"检测到环结构，移除环边后剩余边数量: {len(self.edges)}")
                continue
            
            # 遍历图
            traverse_node_ids = self._traverse_by_topology(adj_list, in_degrees)
            
            self.graph_data = {
                "adj_list": adj_list,
                "reverse_adj_list": reverse_adj_list,
                "node_related_edges": node_related_edges,
                "node_types": node_types,
                "traverse_node_ids": traverse_node_ids,
                "node_descriptions": node_descriptions,
                # 新增：iteration和loop内部节点关系
                "iteration_internal_nodes": self.iteration_internal_nodes,
                "loop_internal_nodes": self.loop_internal_nodes,
                "node_to_iteration": self.node_to_iteration,
                "node_to_loop": self.node_to_loop
            }
            logger.info(f"构建无环图成功, 边数量: {len(self.edges)}")
            break
            
        return self.graph_data
    
    def _build_internal_node_relationships(self) -> None:
        """构建iteration和loop的内部节点关系"""
        # 清空之前的关系
        self.iteration_internal_nodes.clear()
        self.loop_internal_nodes.clear()
        self.node_to_iteration.clear()
        self.node_to_loop.clear()
        
        # 遍历所有边，建立内部节点关系
        for edge in self.edges:
            # 处理iteration内部节点
            if edge.is_in_iteration and edge.iteration_id:
                iteration_id = edge.iteration_id
                
                # 初始化iteration内部节点列表
                if iteration_id not in self.iteration_internal_nodes:
                    self.iteration_internal_nodes[iteration_id] = []
                
                # 添加源节点和目标节点到内部节点列表
                if edge.source not in self.iteration_internal_nodes[iteration_id]:
                    self.iteration_internal_nodes[iteration_id].append(edge.source)
                    self.node_to_iteration[edge.source] = iteration_id
                    
                if edge.target not in self.iteration_internal_nodes[iteration_id]:
                    self.iteration_internal_nodes[iteration_id].append(edge.target)
                    self.node_to_iteration[edge.target] = iteration_id
            
            # 处理loop内部节点
            if edge.is_in_loop and edge.loop_id:
                loop_id = edge.loop_id
                
                # 初始化loop内部节点列表
                if loop_id not in self.loop_internal_nodes:
                    self.loop_internal_nodes[loop_id] = []
                
                # 添加源节点和目标节点到内部节点列表
                if edge.source not in self.loop_internal_nodes[loop_id]:
                    self.loop_internal_nodes[loop_id].append(edge.source)
                    self.node_to_loop[edge.source] = loop_id
                    
                if edge.target not in self.loop_internal_nodes[loop_id]:
                    self.loop_internal_nodes[loop_id].append(edge.target)
                    self.node_to_loop[edge.target] = loop_id
        
        logger.info(f"构建内部节点关系完成:")
        logger.info(f"iteration_internal_nodes: {self.iteration_internal_nodes}")
        logger.info(f"loop_internal_nodes: {self.loop_internal_nodes}")
    
    def get_internal_nodes_for_iteration_loop(
            self, 
            node_id: str, 
            node_type: str
        ) -> List[str]:
        """获取iteration/loop节点的内部节点列表
        
        Args:
            node_id: iteration或loop节点的ID
            node_type: 节点类型('iteration'或'loop')
            
        Returns:
            List[str]: 内部节点ID列表
        """
        if node_type == 'iteration':
            return self.iteration_internal_nodes.get(node_id, [])
        elif node_type == 'loop':
            return self.loop_internal_nodes.get(node_id, [])
        else:
            return []
    
    def is_node_inside_iteration_loop(
            self, 
            target_node_id: str, 
            iteration_loop_id: str, 
            iteration_loop_type: str
        ) -> bool:
        """判断节点是否在iteration/loop内部
        
        Args:
            target_node_id: 目标节点ID
            iteration_loop_id: iteration或loop节点ID
            iteration_loop_type: 节点类型('iteration'或'loop')
            
        Returns:
            bool: 是否在内部
        """
        if iteration_loop_type == 'iteration':
            return target_node_id in self.iteration_internal_nodes.get(iteration_loop_id, [])
        elif iteration_loop_type == 'loop':
            return target_node_id in self.loop_internal_nodes.get(iteration_loop_id, [])
        else:
            return False

    def _remove_cycle_edges(self, cycles: List[List[str]]) -> List[Edge]:
        """移除环中的边
        
        Args:
            cycles: 检测到的环列表
            
        Returns:
            List[Edge]: 移除环后的边列表
        """
        edges_to_remove = set()
        
        # 对于每个环，移除最后一条边（从环的最后一个节点到第一个节点的边）
        for cycle in cycles:
            cycle_last = cycle[-2]
            cycle_first = cycle[-1]
            
            # 找到要移除的边
            for edge in self.edges:
                if edge.source == cycle_last and edge.target == cycle_first:
                    edges_to_remove.add(edge)
                    logger.warning(f"移除环边: source={edge.source}, target={edge.target}")
                    break
        
        # 返回不在待移除集合中的边
        return [edge for edge in self.edges if edge not in edges_to_remove]
    
    def _detect_cycles(self, adj_list: Dict[str, List[str]]) -> Tuple[bool, List[List[str]]]:
        """检测图中是否存在环
        
        Args:
            adj_list: 邻接表
            
        Returns:
            Tuple[bool, List[List[str]]]: (是否存在环, 环路径列表)
        """
        visited = set()
        in_current_path = set()
        cycles = []
        
        def detect_cycle(node_id: str, path: List[str]) -> bool:
            in_current_path.add(node_id)
            path.append(node_id)
            
            for next_id in adj_list.get(node_id, []):
                if next_id in in_current_path:
                    cycle_start = path.index(next_id)
                    cycles.append(path[cycle_start:] + [next_id])
                    return True
                if next_id not in visited and detect_cycle(next_id, path):
                    return True
                    
            in_current_path.remove(node_id)
            path.pop()
            return False
            
        # 检测是否存在环
        has_cycle = False
        for node_id in adj_list:
            if node_id not in visited:
                if detect_cycle(node_id, []):
                    has_cycle = True
                    break
                    
        return has_cycle, cycles

    def _correct_edges(self, edges: List[Edge]) -> List[Edge]:
        """修正边的目标节点类型
        
        Args:
            edges: 原始边列表
            
        Returns:
            List[Edge]: 修正后的边列表
        """
    
        corrected_edges = []

        for edge in edges:
            if edge.target_type == "loop-start":
                edge.target_type = "loop"
                if edge.target in self.node_to_loop:
                    edge.target = self.node_to_loop[edge.target]
                edge.id = f"{edge.source}-source-{edge.target}-target"
                logger.info(f"修正边目标: loop-start -> loop, edge_id: {edge.id}")

            elif edge.target_type == "iteration-start" :
                edge.target_type = "iteration"
                if edge.target in self.node_to_iteration:
                    edge.target = self.node_to_iteration[edge.target]
                edge.id = f"{edge.source}-source-{edge.target}-target"
                logger.info(f"修正边目标: iteration-start -> iteration, edge_id: {edge.id}")
               
            corrected_edges.append(edge)
        
        return corrected_edges

    def _traverse_by_dfs(
            self,
            adj_list: Dict[str, List[str]],
            in_degrees: Dict[str, int]
        ) -> List[str]:
        """使用DFS生成节点遍历列表
        
        Args:
            adj_list: 邻接表
            in_degrees: 节点入度表
            
        Returns:
            List[str]: 遍历顺序的节点ID列表
        """
        traverse_node_ids = []
        visited = set()
        
        def dfs(node_id: str):
            visited.add(node_id)
            traverse_node_ids.append(node_id)
            
            neighbors = sorted(adj_list[node_id]) if node_id in adj_list else []
            for next_id in neighbors:
                if next_id not in visited:
                    dfs(next_id)
        
        # 找出所有入度为0的节点作为起点
        start_nodes = [node_id for node_id, degree in in_degrees.items() if degree == 0]
        if not start_nodes:
            raise WorkflowError("没有入度为0的节点，可能存在环结构")

        # 从每个起点开始DFS
        for start_node in sorted(start_nodes):
            if start_node not in visited:
                dfs(start_node)
        
        # 检查是否存在未遍历的节点
        unvisited = set(adj_list.keys()) - visited
        if unvisited:
            raise WorkflowError(f"存在未遍历的节点: {unvisited}")
            
        logger.info(f"DFS遍历完成，遍历序列: {traverse_node_ids}")
        return traverse_node_ids
    
    def _traverse_by_bfs(
            self,
            adj_list: Dict[str, List[str]],
            in_degrees: Dict[str, int]
        ) -> List[str]:
        """使用BFS生成节点遍历列表
        
        Args:
            adj_list: 邻接表
            in_degrees: 节点入度表
                
        Returns:
            List[str]: 遍历顺序的节点ID列表
        """
        traverse_node_ids = []
        visited = set()
        queue = deque()
        
        # 找出所有入度为0的节点作为起点
        start_nodes = [node_id for node_id, degree in in_degrees.items() if degree == 0]
        if not start_nodes:
            raise WorkflowError("没有入度为0的节点，可能存在环结构")
        
        # 将所有起点加入队列
        for start_node in sorted(start_nodes):
            queue.append(start_node)
            visited.add(start_node)
        
        # BFS遍历
        while queue:
            current_node = queue.popleft()
            traverse_node_ids.append(current_node)
            
            # 获取并排序邻接节点
            neighbors = sorted(adj_list[current_node]) if current_node in adj_list else []
            for next_node in neighbors:
                if next_node not in visited:
                    visited.add(next_node)
                    queue.append(next_node)
        
        # 检查是否存在未遍历的节点
        unvisited = set(adj_list.keys()) - visited
        if unvisited:
            raise WorkflowError(f"存在未遍历的节点: {unvisited}")
        
        logger.info(f"BFS遍历完成，遍历序列: {traverse_node_ids}")
        return traverse_node_ids
    
    def _traverse_by_topology(
        self,
        adj_list: Dict[str, List[str]],
        in_degrees: Dict[str, int]
    ) -> List[str]:
        """使用拓扑排序生成节点遍历列表
        
        Args:
            adj_list: 邻接表
            in_degrees: 节点入度表
                
        Returns:
            List[str]: 遍历顺序的节点ID列表
        """
        traverse_node_ids = []
        queue = deque()
        in_degree_copy = in_degrees.copy()  # 复制入度表以免修改原始数据
        
        # 将所有入度为0的节点加入队列
        for node_id, degree in in_degrees.items():
            if degree == 0:
                queue.append(node_id)
        
        if not queue:
            raise WorkflowError("没有入度为0的节点，可能存在环结构")
        
        # 拓扑排序
        while queue:
            # 按节点ID排序，确保遍历顺序确定性
            sorted_nodes = sorted(queue)
            current_node = sorted_nodes[0]
            queue.remove(current_node)
            
            traverse_node_ids.append(current_node)
            
            # 更新邻接节点的入度
            for next_node in adj_list.get(current_node, []):
                in_degree_copy[next_node] -= 1
                # 当节点入度减为0时，将其加入队列
                if in_degree_copy[next_node] == 0:
                    queue.append(next_node)
        
        # 检查是否存在未遍历的节点（可能存在环）
        if len(traverse_node_ids) != len(adj_list):
            unvisited = set(adj_list.keys()) - set(traverse_node_ids)
            raise WorkflowError(f"存在未遍历的节点，可能存在环结构: {unvisited}")
        
        logger.info(f"拓扑排序遍历完成，遍历序列: {traverse_node_ids}")
        return traverse_node_ids
    
    def get_graph_data(self) -> Dict[str, Any]:
        """获取图数据
        
        Returns:
            Dict[str, Any]: 图数据结构
        """
        return self.graph_data
    
    def get_traverse_order(self, method: str = "topology") -> List[str]:
        """获取节点遍历顺序
        
        Args:
            method: 遍历方法，可选值: "topology", "dfs", "bfs"
            
        Returns:
            List[str]: 节点遍历顺序
        """
        if not self.graph_data:
            self.build_graph()
            
        adj_list = self.graph_data["adj_list"]
        in_degrees = {}
        
        # 重新计算入度
        for node in adj_list:
            in_degrees[node] = 0
        for node, neighbors in adj_list.items():
            for neighbor in neighbors:
                in_degrees[neighbor] = in_degrees.get(neighbor, 0) + 1
        
        if method == "dfs":
            return self._traverse_by_dfs(adj_list, in_degrees)
        elif method == "bfs":
            return self._traverse_by_bfs(adj_list, in_degrees)
        else:  # topology
            return self._traverse_by_topology(adj_list, in_degrees)