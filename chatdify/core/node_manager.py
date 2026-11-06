"""
节点管理器模块
"""
from typing import List, Dict, Any, Optional, Tuple
import yaml
import time

from chatdify import dify_compat
from chatdify.settings import get_settings
from chatdify.models.edge import Edge
from chatdify.models.node import Node, NodeErrors
from chatdify.models.workflow import Workflow
from chatdify.services.llm_service import LLMService
from chatdify.services.file_service import FileService
from chatdify.utils.logging import get_logger
from chatdify.utils.exceptions import NodeManagerError
from chatdify.utils.decorators import timing_decorator
from chatdify.prompts.workflow_prompts import (
    GENERATE_NODE_PROMPT_SYSTEM,
    GENERATE_NODE_PROMPT_USER
)
from chatdify.core.node_validator.base import BaseNodeValidationResult

logger = get_logger(__name__)


class NodeManager:
    """节点管理器，负责生成和管理节点"""
    
    def __init__(self, llm_service: LLMService, file_service: FileService):
        self._llm_service = llm_service
        self._file_service = file_service
        self._node_references_cache: Dict[str, str] = {}
        self._node_type_configs: Dict[str, Dict] = {}
        self._select_node_types: List[str] = []
        logger.info("节点管理器初始化完成")
    
    @timing_decorator
    def generate_nodes(
            self, 
            workflow: Workflow, 
            user_request: str,
            feedback_history: str = "",
            reference_workflow_nodes: Optional[List[Node]] = None,
            previous_workflow_nodes: Optional[List[Node]] = None,
            previous_workflow_conversation_variables: str = ""
        ) -> Tuple[List[Node], NodeErrors]:
        """为工作流生成节点"""
        try:
            nodes, node_errors = self._generate_nodes(
                workflow=workflow,
                user_request=user_request,
                feedback_history=feedback_history,
                reference_workflow_nodes=reference_workflow_nodes,
                previous_workflow_nodes=previous_workflow_nodes,
                previous_workflow_conversation_variables=previous_workflow_conversation_variables
            )
            
            if previous_workflow_nodes:
                logger.info(f"历史节点数量: {len(previous_workflow_nodes)}")
            logger.info(f"生成了{len(nodes)}个节点")
            return nodes, node_errors
            
        except Exception as e:
            logger.error(f"生成节点失败: {str(e)}")
            raise NodeManagerError(f"生成节点失败: {str(e)}")
            
    @timing_decorator
    def validate_nodes(self, workflow: Workflow) -> NodeErrors:
        """验证工作流中的节点"""
        graph_data = workflow.graph_data
        
        self._validate_graph_data(graph_data)

        # 已声明的会话变量类型映射，供 assigner 等校验"操作-类型-取值"兼容性
        self._conversation_variable_types = {
            v.get("name"): v.get("value_type") for v in workflow.conversation_variables
        }
    
        node_map = {}
        node_errors = NodeErrors()
    
        # 遍历workflow nodes，构建node_map
        for node in workflow.nodes:
            node_id = node.id
            node_map[node_id] = node
            
        for node_id in graph_data["traverse_node_ids"]:
            node_type = graph_data["node_types"][node_id]
            
            # 获取节点对象
            if node_id not in node_map:
                error_msg = f"节点[node_id: {node_id}, node_type: {node_type}] 在节点映射中不存在"
                logger.error(error_msg)
                node_errors.add_error(node_id, node_type, error_msg)
                continue
                
            node = node_map[node_id]
            
            # 获取所有前置节点
            all_previous_nodes = self._get_all_previous_nodes(
                node_id,
                graph_data["reverse_adj_list"],
                node_map
            )

            related_edges=graph_data["node_related_edges"][node_id]

            validation_result = None
    
            # 对于iteration和loop节点，需要特殊处理验证逻辑
            if node_type in ['iteration', 'loop']:
                # 获取内部节点信息
                internal_node_ids = self._get_internal_nodes_from_graph_data(
                    node_id=node_id, node_type=node_type, graph_data=graph_data
                )
                
                # 构建内部节点的variable_pool
                internal_nodes = {}
                for internal_node_id in internal_node_ids:
                    if internal_node_id in node_map:
                        internal_nodes[internal_node_id] = node_map[internal_node_id]
                
                # 根据节点类型进行特殊验证
                if node_type == 'loop':
                    internal_nodes[node.id] = node

                    validation_result = self._validate_node(
                        node=node, 
                        all_previous_nodes={
                            "loop_variable": all_previous_nodes,
                            "break_condition": internal_nodes
                        }
                    )
                elif node_type == 'iteration':
                    validation_result = self._validate_node(
                        node=node, 
                        all_previous_nodes={
                            "iterator": all_previous_nodes,
                            "output": internal_nodes
                        }
                    )
            
            elif node_type in ['if-else', 'question-classifier']:
                source_handles = []
                for e in related_edges:
                    if e.source_type == node_type:
                        source_handles.append(e.sourceHandle)

                validation_result = self._validate_node(
                    node=node,
                    all_previous_nodes=all_previous_nodes,
                    source_handles=source_handles
                )
                        
            else:
                # 普通节点验证
                validation_result = self._validate_node(node, all_previous_nodes)
    
            # 处理验证结果
            if validation_result is None:
                # 验证被跳过（未启用 Dify 静态校验）
                continue
    
            if not validation_result.is_valid:
                error_msg = (
                    f"节点[node_id: {node_id}, node_type: {node_type}] 验证失败, "
                    f"错误原因: {' '.join(validation_result.errors)}"
                )
                logger.error(error_msg)
                node_errors.add_error(node_id, node_type, error_msg)
            else:
                # 验证成功
                node_errors.set_node_valid(node_id, node_type, True)
                logger.debug(f"节点[node_id: {node_id}, node_type: {node_type}] 验证成功")
            
        return node_errors
            
    def _get_node_reference(self, node_type: str) -> str:
        """获取节点参考信息（使用缓存）"""
        if node_type == 'tool':
            tool_refs = []
            logger.info(f"select_node_types: {self._select_node_types}")
            for selected_type in self._select_node_types:
                if selected_type.startswith('tool_'):
                    if selected_type not in self._node_references_cache:
                        self._node_references_cache[selected_type] = self._file_service.read_node_reference(selected_type, ref_type="node")
                    tool_refs.append(self._node_references_cache[selected_type])
            
            logger.info(f"加载了 {len(tool_refs)} 个工具 ref")
            return "\n".join(tool_refs)

        if node_type not in self._node_references_cache:
            self._node_references_cache[node_type] = self._file_service.read_node_reference(node_type, ref_type="node")
        
        refs = self._node_references_cache[node_type]

        return refs
    
    def _validate_graph_data(self, graph_data: Dict) -> None:
        """验证图数据的完整性"""
        required_keys = ["traverse_node_ids", "node_types", "node_related_edges", "reverse_adj_list", "node_descriptions"] 
         
        missing_keys = [key for key in required_keys if not graph_data.get(key)]
        
        if missing_keys:
            error_msg = f"图数据缺少必要的键: {', '.join(missing_keys)}"
            logger.error(error_msg)
            raise NodeManagerError(error_msg)
    
    def _get_all_previous_nodes(
        self,
        node_id: str,
        reverse_adj_list: Dict[str, List[str]],
        node_map: Dict[str, Node]
    ) -> Dict[str, Node]:
        """获取节点的所有前置节点列表（包括直接和间接前置节点）
        
        Args:
            node_id: 节点ID
            reverse_adj_list: 反向邻接表
            node_map: 节点映射表
            
        Returns:
            所有前置节点列表
        """
        visited = set()  # 用于记录已访问的节点
        all_previous_nodes = {}  # 存储所有前置节点
        
        def dfs(current_id: str):
            """深度优先搜索获取所有前置节点"""
            if current_id in visited:
                return
            visited.add(current_id)
            
            # 获取直接前置节点
            for prev_id in reverse_adj_list.get(current_id, []):
                if prev_node := node_map.get(prev_id):
                    if prev_id not in all_previous_nodes:
                        all_previous_nodes[prev_id] = prev_node
                    # 递归获取前置节点的前置节点
                    dfs(prev_id)
        
        # 从目标节点开始搜索
        dfs(node_id)

        logger.info(f"为节点{node_id} 获取了 {len(all_previous_nodes)} 个前置节点, all_previous_nodes: {list(all_previous_nodes.keys())}")

        return all_previous_nodes

    def _get_previous_nodes(
            self,
            node_id: str,
            reverse_adj_list: Dict[str, List[str]],
            node_map: Dict[str, Node]
        ) -> List[Node]:
        """获取前置节点列表"""
        previous_nodes = []
        for prev_node_id in reverse_adj_list.get(node_id, []):
            if prev_node := node_map.get(prev_node_id):
                previous_nodes.append(prev_node)
            else:
                logger.error(f"找不到前置节点: {prev_node_id}")
                # raise NodeManagerError(f"找不到前置节点: {prev_node_id}")
                pass
               
        return previous_nodes

    def _generate_nodes(
            self,
            workflow: Workflow, 
            user_request: str,
            feedback_history: str = "",
            reference_workflow_nodes: Optional[List[Node]] = None,
            previous_workflow_nodes: Optional[List[Node]] = None,
            previous_workflow_conversation_variables: str = ""
        ) -> Tuple[List[Node], NodeErrors]:
        """生成节点"""
        nodes = []
        node_map = {}

        # 上一轮工作流的会话变量声明(含初值)，作为节点生成时会话变量初值的权威基准
        self._previous_workflow_conversation_variables = previous_workflow_conversation_variables

        # 已声明的会话变量类型映射（生成阶段通常为空，待 sync 后才有；完整校验时可用）
        self._conversation_variable_types = {
            v.get("name"): v.get("value_type") for v in workflow.conversation_variables
        }

        self._select_node_types = workflow.select_node_types

        graph_data = workflow.graph_data

        self._validate_graph_data(graph_data)

        node_errors = NodeErrors()

        # 第一阶段：生成所有节点，对iteration和loop节点进行基础验证
        iteration_loop_nodes = []  # 记录需要第二阶段验证的节点
            
        for node_id in graph_data["traverse_node_ids"]:
            node_type = graph_data["node_types"][node_id]
            
            # 节点功能需求描述描述，用于生成节点数据
            node_description = graph_data["node_descriptions"][node_id]

            # 获取节点参考信息（使用缓存）
            node_reference = self._get_node_reference(node_type)

            if not node_reference:
                logger.error(f"节点类型 {node_type} 的参考信息不存在")
                node_reference = ""
                # raise NodeManagerError(f"节点类型 {node_type} 的参考信息不存在")
            
            # 获取前置节点
            previous_nodes = self._get_previous_nodes(
                node_id, 
                graph_data["reverse_adj_list"], 
                node_map
            )

            all_previous_nodes = self._get_all_previous_nodes(
                node_id,
                graph_data["reverse_adj_list"],
                node_map
            )

            related_edges=graph_data["node_related_edges"][node_id]

            current_feedback_history = feedback_history
            node = None

            for i in range(get_settings().node_max_retries):
                try:
                    # 生成节点数据
                    node_data = self._generate_node_data(
                        user_request=user_request,
                        node_description=node_description,
                        node_type=node_type,
                        node_id=node_id,
                        related_edges=related_edges,
                        previous_nodes=previous_nodes,
                        existing_nodes=nodes,
                        node_reference=node_reference,
                        feedback_history=current_feedback_history,
                        reference_workflow_nodes=reference_workflow_nodes,
                        previous_workflow_nodes=previous_workflow_nodes
                    )
                    
                    # 创建并添加节点
                    node = Node.create(node_data)
                    logger.info(f"创建了节点: {node.to_dict()}")

                    # 对iteration和loop节点进行基础验证（跳过依赖内部节点的验证）
                    if node_type in ['iteration', 'loop']:
                        validation_result = self._validate_node(
                            node=node,
                            all_previous_nodes=all_previous_nodes,
                            is_first_stage=True
                        )
                    
                    elif node_type in ['if-else', 'question-classifier']:
                        source_handles = []
                        for e in related_edges:
                            if e.source_type == node_type:
                                source_handles.append(e.sourceHandle)

                        validation_result = self._validate_node(
                            node=node,
                            all_previous_nodes=all_previous_nodes,
                            source_handles=source_handles
                        )
                        
                    else:
                        # 其他节点进行完整验证
                        validation_result = self._validate_node(
                            node=node,
                            all_previous_nodes=all_previous_nodes
                        )
                    
                    if not validation_result:
                        node_errors.set_node_valid(node_id, node_type, True)
                        break
                        
                    if validation_result.is_valid:
                        node_errors.set_node_valid(node_id, node_type, True)
                        logger.info(f"第{i+1}次 节点 {node_id} 生成成功, 验证成功!")
                        break
                        
                    # 处理验证失败的情况
                    error_msg = "\n".join(validation_result.errors)
                    error_msg = f"第{i+1}次 节点[node_id: {node_id}, node_type: {node_type}] 验证失败, 错误原因: {str(error_msg)}"
                    current_feedback_history += f"\n {error_msg}\n"
                    previous_workflow_nodes = [node]
                    node_errors.add_error(node_id, node_type, error_msg)
                    logger.error(error_msg)
                    
                    # 验证失败时中止后续验证
                    if validation_result.should_abort:
                        node = None
                        break
                        
                except Exception as e:
                    error_msg = f"第{i+1}次 节点[node_id: {node_id}, node_type: {node_type}] 生成失败, 错误原因: {str(e)}"
                    current_feedback_history += f"\n {error_msg}\n"
                    node_errors.add_error(node_id, node_type, error_msg)
                    logger.error(error_msg)
                    time.sleep(1)
            
            if not node:
                error_msg = (
                    f"节点[node_id: {node_id}, node_type: {node_type}] "
                    f"最终生成失败"
                    "错误原因: " + "\n-".join(node_errors.errors[node_id])
                )
                raise NodeManagerError(error_msg)
            
            nodes.append(node)
            node_map[node_id] = node

            # 记录需要第二阶段验证的节点
            if node_type in ['iteration', 'loop']:
                iteration_loop_nodes.append({
                    'node': node,
                    'node_id': node_id,
                    'node_type': node_type,
                    'node_description': node_description,
                    'node_reference': node_reference,
                    'related_edges': graph_data["node_related_edges"][node_id],
                    'all_previous_nodes': all_previous_nodes,
                    'user_request': user_request,
                    'reference_workflow_nodes': reference_workflow_nodes
                })

        # 第二阶段：对iteration和loop节点进行完整验证和重生成
        if iteration_loop_nodes:
            self._validate_and_regenerate_iteration_loop_nodes(
                iteration_loop_nodes=iteration_loop_nodes, 
                nodes=nodes, 
                node_map=node_map, 
                graph_data=graph_data, 
                node_errors=node_errors
            )

        return nodes, node_errors
    
    def _validate_node(
            self,
            node: Node,
            all_previous_nodes: Dict[str, Any],
            **kwargs
        ) -> Optional[BaseNodeValidationResult]:
        """验证节点"""
        
        if not dify_compat.is_available():
            return None

        from chatdify.core.node_validator.node_validator import NodeValidator
        # 添加节点验证
        node_id = node.id
        node_type = node.data.get("type")
        validator = NodeValidator(node_type)

        # 把已声明的会话/环境变量类型传给校验器（assigner 等需据此校验"操作-类型-取值"兼容性）；
        # 生成阶段会话变量可能尚未声明，则为空、退化为类型无关校验
        kwargs.setdefault(
            "conversation_variable_types",
            getattr(self, "_conversation_variable_types", None)
        )

        validation_result = validator.validate_node(
            node_data_config=node.data, 
            variable_pool=all_previous_nodes, 
            **kwargs
        )  
        
        return validation_result
    
    def _validate_and_regenerate_iteration_loop_nodes(
            self,
            iteration_loop_nodes: List[Dict[str, Any]],
            nodes: List[Node],
            node_map: Dict[str, Node],
            graph_data: Dict[str, Any],
            node_errors: NodeErrors
        ) -> None:
        """对iteration和loop节点进行完整验证，失败时重新生成"""
        if not dify_compat.is_available():
            return

        node_max_retries = get_settings().node_max_retries

        for node_info in iteration_loop_nodes:
            node = node_info['node']
            node_id = node_info['node_id']
            node_type = node_info['node_type']
            all_previous_nodes = node_info['all_previous_nodes']
            
            # 使用GraphProcessor提供的内部节点信息
            internal_node_ids = self._get_internal_nodes_from_graph_data(
                node_id=node_id, node_type=node_type, graph_data=graph_data
            )
            
            # 构建内部节点的variable_pool
            internal_nodes = {}
            for internal_node_id in internal_node_ids:
                if internal_node_id in node_map:
                    internal_nodes[internal_node_id] = node_map[internal_node_id]

            current_feedback_history = ""
            regenerated_node = node  # 初始为第一阶段生成的节点
            validation_successful = False
            
            # 尝试验证和重生成
            for i in range(node_max_retries):
                # 进行完整验证
                validation_result = None

                if node_type == 'loop':
                    internal_nodes[regenerated_node.id] = regenerated_node

                    validation_result = self._validate_node(
                        node=regenerated_node, 
                        all_previous_nodes={
                            "loop_variable": all_previous_nodes,
                            "break_condition": internal_nodes
                        }
                    )
                    
                elif node_type == 'iteration':
                    validation_result = self._validate_node(
                        node=regenerated_node, 
                        all_previous_nodes={
                            "iterator": all_previous_nodes,
                            "output": internal_nodes
                        }
                    )
                
                if not validation_result or validation_result.is_valid:
                    # 验证成功，更新节点映射
                    node_map[node_id] = regenerated_node
                    # 更新nodes列表中的节点
                    for idx, n in enumerate(nodes):
                        if n.id == node_id:
                            nodes[idx] = regenerated_node
                            break
                    logger.info(f"第二阶段验证成功: 节点 {node_id}")
                    validation_successful = True
                    break
                    
                # 验证失败，准备重新生成
                error_msg = "\n".join(validation_result.errors)
                error_msg = f"第二阶段第{i+1}次 节点[node_id: {node_id}, node_type: {node_type}] 完整验证失败: {error_msg}"
                current_feedback_history += f"\n {error_msg}\n"
                logger.error(error_msg)
                node_errors.add_error(node_id, node_type, error_msg)

                if validation_result.should_abort:
                    break
                
                # 如果这是最后一次尝试，不再重新生成
                if i == node_max_retries - 1:
                    break
                    
                # 重新生成节点
                try:
                    # 获取当前的前置节点（不包括自己）
                    previous_nodes = self._get_previous_nodes(
                        node_id,
                        graph_data["reverse_adj_list"],
                        node_map
                    )
                    
                    # 获取除了当前节点外的其他节点
                    existing_nodes = [n for n in nodes if n.id != node_id]
                    
                    node_data = self._generate_node_data(
                        user_request=node_info['user_request'],
                        node_description=node_info['node_description'],
                        node_type=node_type,
                        node_id=node_id,
                        related_edges=node_info['related_edges'],
                        previous_nodes=previous_nodes,
                        existing_nodes=existing_nodes,
                        node_reference=node_info['node_reference'],
                        feedback_history=current_feedback_history,
                        reference_workflow_nodes=node_info['reference_workflow_nodes'],
                        previous_workflow_nodes=[regenerated_node]
                    )
                    
                    regenerated_node = Node.create(node_data)
                    logger.info(f"第二阶段第{i+1}次重新生成节点: {node_id}")
                    
                except Exception as e:
                    error_msg = f"第二阶段第{i+1}次 节点[node_id: {node_id}, node_type: {node_type}] 重新生成失败: {str(e)}"
                    current_feedback_history += f"\n {error_msg}\n"
                    node_errors.add_error(node_id, node_type, error_msg)
                    logger.error(error_msg)
                    time.sleep(1)
                    break  # 生成失败，退出循环
            
            # 如果所有尝试都失败了
            if not validation_successful:
                final_error = (
                    f"节点[node_id: {node_id}, node_type: {node_type}] "
                    f"第二阶段经过{node_max_retries}次尝试，验证和重生成都失败"
                )
                logger.error(final_error)

    def _get_internal_nodes_from_graph_data(
            self,
            node_id: str,
            node_type: str,
            graph_data: Dict[str, Any]
        ) -> List[str]:
        """从graph_data中获取iteration/loop节点的内部节点列表"""
        if node_type == 'iteration':
            return graph_data.get('iteration_internal_nodes', {}).get(node_id, [])
        elif node_type == 'loop':
            return graph_data.get('loop_internal_nodes', {}).get(node_id, [])
        else:
            return []
    
    @timing_decorator
    def _generate_node_data(
            self, 
            user_request: str,
            node_description: str, 
            node_type: str, 
            node_id: str, 
            related_edges: List[Edge], 
            previous_nodes: List[Node], 
            existing_nodes: List[Node], 
            node_reference: str, 
            feedback_history: str = "",
            reference_workflow_nodes: Optional[List[Node]] = None,
            previous_workflow_nodes: Optional[List[Node]] = None) -> Dict[str, Any]:
        """
        生成节点数据
        
        Args:
            user_request: 用户请求
            node_description: 节点功能需求描述
            node_type: 节点类型
            node_id: 节点ID
            related_edges: 相关边
            previous_nodes: 前一个节点
            existing_nodes: 已存在的节点列表
            node_reference: 节点参考信息
            feedback_history: 反馈历史
            reference_workflow_nodes: 参考dsl的节点列表
            previous_workflow_nodes: 之前dsl的节点列表
            
        Returns:
            节点数据
        """
        system_prompt = GENERATE_NODE_PROMPT_SYSTEM
        user_prompt = GENERATE_NODE_PROMPT_USER

        # 参考dsl的节点信息
        reference_workflow_nodes_str = ""
        if reference_workflow_nodes:
            reference_workflow_nodes_str = self._format_nodes(reference_workflow_nodes) 
            # logger.info(f"参考dsl的节点信息: {reference_workflow_nodes_str}")

        # 格式化历史节点信息
        previous_workflow_nodes_str = ""
        if previous_workflow_nodes:
            previous_workflow_nodes_str = self._format_nodes(previous_workflow_nodes)
            # logger.info(f"之前dsl的节点信息: {previous_workflow_nodes_str}")

        # 格式化
        related_edges_str = self._format_edges(related_edges)
        existing_nodes_str = self._format_nodes(existing_nodes)
        previous_nodes_str = self._format_nodes(previous_nodes)
        
        try:
            node_data = self._llm_service.generate_json(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                variables={
                    "user_request": user_request,
                    "node_description": node_description,
                    "node_id": node_id,
                    "node_type": node_type,
                    "related_edges": related_edges_str,
                    "previous_nodes": previous_nodes_str,
                    "node_reference": node_reference,
                    "existing_nodes": existing_nodes_str,
                    "feedback_history": feedback_history,
                    "reference_workflow_nodes": reference_workflow_nodes_str,
                    "previous_workflow_nodes": previous_workflow_nodes_str,
                    "previous_workflow_conversation_variables": getattr(self, "_previous_workflow_conversation_variables", "") or ""
                },
                call_type='node'
            )

            logger.info(f"yaml 加载正确 node_data: {node_data}")

            if not isinstance(node_data, dict):
                raise NodeManagerError(f"生成的节点格式不正确: {node_data}")
            
            node_data["data"]["type"] = node_type

            return node_data

        except Exception as e:
            logger.error(f"生成节点数据失败: {str(e)}")
            raise NodeManagerError(f"生成节点数据失败: {str(e)}")
    
    def _format_edges(self, edges: List[Edge]) -> str:
        """格式化边列表为字符串"""
        return yaml.dump([edge.to_full_dict() for edge in edges], allow_unicode=True, default_flow_style=False)
    
    def _format_nodes(self, nodes: List[Node]) -> str:
        """格式化节点列表为字符串"""
        return yaml.dump([node.to_dict() for node in nodes], allow_unicode=True, default_flow_style=False)

