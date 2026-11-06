"""
边管理器模块
"""
from typing import List, Dict, Optional, Tuple
import yaml
import time

from chatdify.models.edge import Edge, EdgeErrors
from chatdify.models.workflow import Workflow
from chatdify.services.llm_service import LLMService
from chatdify.services.file_service import FileService
from chatdify.utils.logging import get_logger
from chatdify.utils.exceptions import EdgeManagerError
from chatdify.utils.decorators import timing_decorator
from chatdify.prompts.workflow_prompts import (
    GENERATE_EDGES_PROMPT_SYSTEM,
    GENERATE_EDGES_PROMPT_USER,
    GENERATE_EDGES_MERMAID_PROMPT_SYSTEM,
    GENERATE_EDGES_MERMAID_PROMPT_USER,
    GENERATE_NODE_DESCRIPTION_PROMPT_SYSTEM,
    GENERATE_NODE_DESCRIPTION_PROMPT_USER,
)

logger = get_logger(__name__)


class EdgeManager:
    """边管理器，负责生成和管理边"""
    
    def __init__(self, llm_service: LLMService, file_service: FileService):
        """
        初始化边管理器
        
        Args:
            llm_service: LLM服务
            file_service: 文件服务
        """
        self._llm_service = llm_service
        self._file_service = file_service
        logger.info("边管理器初始化完成")
        
    @timing_decorator
    def generate_edges(
        self, 
        user_request: str, 
        tasks: List[str], 
        node_list: List[str], 
        select_node_types: List[str],
        feedback_history: str = "",
        reference_workflow: Optional[Workflow] = None,
        previous_workflow: Optional[Workflow] = None,
        workflow_mode: str = 'workflow'
    ) -> Tuple[List[Edge], EdgeErrors, str]:
        """
        生成边
        
        Args:
            user_request: 用户请求
            tasks: 任务列表
            node_list: 节点列表使用详情，包含节点类型和节点描述
            select_node_types: 选中的节点类型
            feedback_history: 反馈历史
            reference_workflow: 参考workflow
            previous_workflow: 之前的workflow
            workflow_mode: 工作流模式
            
        Returns:
            边列表, 边错误, mermaid 代码
        """
        
        system_prompt = GENERATE_EDGES_PROMPT_SYSTEM
        user_prompt = GENERATE_EDGES_PROMPT_USER

        try:
            edge_errors = EdgeErrors()

            # 将任务列表和节点列表格式化为字符串
            tasks_str = "\n".join(tasks)

            node_list_str = "\n".join(node_list)

            select_node_types_str = f"选中的节点类型列表（注意：节点类型只能从这里面选择）: {select_node_types}"

            logger.info(f"选中的节点类型列表: {select_node_types}")
            
            # 格式化reference_workflow信息；
            reference_workflow_str = ""
            if reference_workflow:
                logger.info(f"参考workflow 边数量: {len(reference_workflow.edges)}")
                reference_workflow_str = reference_workflow.to_dsl()

            # 格式化历史边信息
            previous_workflow_str = ""
            if previous_workflow:
                previous_workflow_str = self.format_edges(previous_workflow.edges)
                logger.info(f"历史边数量: {len(previous_workflow.edges)}")
                logger.info(f"历史dsl:\n {previous_workflow_str}")
            
            edges_json = self._llm_service.generate_json(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                variables={
                    "user_request": user_request,
                    "tasks": tasks_str,
                    "node_list": node_list_str,
                    "select_node_types": select_node_types_str,
                    "feedback_history": feedback_history,
                    "reference_workflow": reference_workflow_str,
                    "previous_workflow": previous_workflow_str
                },
                call_type='edge'
            )
            
            # 解析边JSON
            logger.info(f"生成的边JSON: {edges_json}")

            if isinstance(edges_json, list):
                edges = []
                is_exsit_invalid_edge = False
            
                for edge_data in edges_json:
                    edge, is_valid, error_reason = Edge.create(edge_data=edge_data, workflow_mode=workflow_mode)

                    if not is_valid:
                        logger.warning(f"跳过错误边: {edge_data}")
                        is_exsit_invalid_edge = True
                        error_msg = "\n".join(error_reason)
                        edge_errors.add_error(edge.id, error_msg)
                        continue

                    edges.append(edge)
                
                if is_exsit_invalid_edge:
                    logger.warning(f"存在错误的边: {edge_errors.format_errors()}")
                    raise EdgeManagerError(f"存在错误的边。错误信息：{edge_errors.format_errors()}。请修正边信息, 注意不要重复同样的错误。")
                
                # 更新边的节点描述
                self.update_edge_descriptions(edges=edges, user_request=user_request)
                
                edges_mermaid_code = self.format_edges_to_mermaid(edges=edges)

                return edges, edge_errors, edges_mermaid_code
            else:
                raise EdgeManagerError(f"生成的边格式不正确: {edges_json}")
        except Exception as e:
            logger.error(f"生成边失败: {str(e)}")
            raise EdgeManagerError(f"生成边失败: {str(e)}")
    
    def format_edges(self, edges: List[Edge]) -> str:
        """格式化边列表为字符串"""
        return yaml.dump([edge.to_dict() for edge in edges], allow_unicode=True, default_flow_style=False)
    
    def format_edges_to_mermaid(self, edges: List[Edge]) -> str:
        """格式化边, 输出mermaid 流程代码"""
        try:
            # 将边信息格式化为 YAML
            edges_yaml = yaml.dump([edge.to_full_dict() for edge in edges], allow_unicode=True, default_flow_style=False)
            logger.info(f"开始生成 Mermaid 图，边数量: {len(edges)}")
            
            # 使用专门的 Mermaid 生成提示词
            mermaid_code = self._llm_service.generate(
                system_prompt=GENERATE_EDGES_MERMAID_PROMPT_SYSTEM,
                user_prompt=GENERATE_EDGES_MERMAID_PROMPT_USER,
                variables={
                    "edges_yaml": edges_yaml
                },
                call_type='edge'
            )
            
            # import mermaid as md
            # # 尝试创建 Mermaid 对象来校验语法
            # mermaid_obj = md.Mermaid(mermaid_code)
            # logger.info("Mermaid 代码语法校验通过")

            logger.info(f"生成的边Mermaid 代码:\n{mermaid_code}")
            
            return mermaid_code
            
        except Exception as e:
            logger.error(f"生成 Mermaid 图失败: {str(e)}")
            return ""
    
    def generate_node_descriptions(self, user_request: str, edges: List[Edge], max_retries: int = 3, retry_delay: float = 1.0) -> List[Dict[str, str]]:
        """
        根据工作流边信息、节点信息和用户需求生成节点功能描述
        
        Args:
            user_request: 用户需求描述
            edges: 边信息列表
            max_retries: 最大重试次数
            retry_delay: 每次重试延迟秒数
            
        Returns:
            List[Dict[str, str]]: 节点功能描述列表，包含node_id、node_type、node_description字段
        """
        try:
            # 从边信息中提取所有节点信息
            expected_nodes = self._extract_nodes_from_edges(edges)
            expected_node_ids = {node["node_id"] for node in expected_nodes}
            
            # 格式化边信息为YAML
            edges_yaml = yaml.dump([edge.to_dict() for edge in edges], allow_unicode=True, default_flow_style=False)
            nodes_info = yaml.dump(expected_nodes, allow_unicode=True, default_flow_style=False)
            
            logger.info(f"开始生成节点功能描述，节点数量: {len(expected_nodes)}")
            
            # 重试机制参数
            last_exception = None
            missing_nodes_feedback = None  # 用于存储缺失节点的反馈信息
            
            for attempt in range(max_retries):
                try:
                    if attempt > 0:
                        logger.info(f"第 {attempt + 1} 次重试生成节点功能描述")
                        time.sleep(retry_delay * attempt)  # 递增延迟
                    
                    # 准备变量字典
                    variables = {
                        "user_request": user_request,
                        "edges_info": edges_yaml,
                        "nodes_info": nodes_info
                    }
                    
                    # 如果有缺失节点的反馈信息，添加到变量中
                    if missing_nodes_feedback:
                        variables["missing_nodes_feedback"] = missing_nodes_feedback
                        logger.info(f"向大模型反馈缺失节点信息: {missing_nodes_feedback}")
                    else:
                        variables["missing_nodes_feedback"] = ""
                    
                    # 调用LLM生成节点功能描述
                    node_descriptions = self._llm_service.generate_json(
                        system_prompt=GENERATE_NODE_DESCRIPTION_PROMPT_SYSTEM,
                        user_prompt=GENERATE_NODE_DESCRIPTION_PROMPT_USER,
                        variables=variables,
                        call_type='node_description'
                    )
                    
                    if not isinstance(node_descriptions, list):
                        if attempt < max_retries - 1:
                            logger.warning(f"第 {attempt + 1} 次尝试返回格式不正确: {node_descriptions}，将重试")
                            continue
                        else:
                            raise EdgeManagerError(f"生成的节点功能描述格式不正确: {node_descriptions}")
                    
                    # 检查输出结果的完整性
                    output_node_ids = {desc.get("node_id") for desc in node_descriptions if desc.get("node_id")}
                    missing_node_ids = expected_node_ids - output_node_ids
                    
                    if not missing_node_ids:
                        # 所有节点都在输出中，成功返回
                        if attempt > 0:
                            logger.info(f"第 {attempt + 1} 次尝试成功生成节点功能描述")
                        logger.info(f"成功生成节点功能描述: {node_descriptions}")
                        return node_descriptions
                    else:
                        # 有缺失的节点，记录并准备重试
                        if attempt < max_retries - 1:
                            # 准备缺失节点的详细反馈信息
                            missing_nodes_feedback = self._prepare_missing_nodes_feedback(
                                missing_node_ids=missing_node_ids, 
                                output_node_ids=output_node_ids
                            )
                            logger.error(f"第 {attempt + 1} 次尝试缺失节点: {missing_node_ids}，将重试")
                            continue
                        else:
                            # 达到最大重试次数，尝试补充缺失的节点
                            logger.error(f"达到最大重试次数，尝试补充缺失的节点: {missing_node_ids}")
                            
                            # 为缺失的节点创建默认描述
                            for missing_node_id in missing_node_ids:
                                missing_node_info = next(
                                    (node for node in expected_nodes if node["node_id"] == missing_node_id), 
                                    None
                                )
                                if missing_node_info:
                                    default_description = {
                                        "node_id": missing_node_id,
                                        "node_type": missing_node_info["node_type"],
                                        "node_description": f"执行{missing_node_info['node_type']}类型的处理任务"
                                    }
                                    node_descriptions.append(default_description)
                            
                            logger.info(f"补充缺失节点后的最终结果: {node_descriptions}")
                            return node_descriptions
                        
                except Exception as retry_error:
                    last_exception = retry_error
                    if attempt < max_retries - 1:
                        logger.warning(f"第 {attempt + 1} 次尝试异常: {str(retry_error)}，将重试")
                        continue
                    else:
                        break
            
            # 如果所有重试都失败，抛出异常
            logger.error(f"生成节点功能描述失败（已重试 {max_retries} 次）: {str(last_exception)}")
            raise EdgeManagerError(f"生成节点功能描述失败: {str(last_exception)}")
            
        except Exception as e:
            logger.error(f"生成节点功能描述失败: {str(e)}")
            raise EdgeManagerError(f"生成节点功能描述失败: {str(e)}")
    
    def _prepare_missing_nodes_feedback(self, missing_node_ids: set, output_node_ids: set) -> str:
        """
        准备缺失节点的反馈信息
        
        Args:
            missing_nodes: 缺失的节点ID集合
            output_node_ids: 输出的节点ID集合

        Returns:
            格式化的缺失节点反馈信息
        """
        feedback_parts = []
        
        # 添加总体统计信息
        feedback_parts.append(f"节点完整性检查结果:")
        feedback_parts.append(f"- 已生成描述节点: {output_node_ids}")
        feedback_parts.append(f"- 缺失节点: {missing_node_ids}")
        
        feedback_parts.append(f"\n请重新生成节点功能描述，确保包含所有缺失的节点，并为每个节点提供合适的功能描述。")
        
        return "\n".join(feedback_parts)
    
    def _extract_nodes_from_edges(self, edges: List[Edge]) -> List[Dict[str, str]]:
        """
        从边信息中提取节点信息
        
        Args:
            edges: 边信息列表
            
        Returns:
            List[Dict[str, str]]: 节点信息列表，包含node_id和node_type
        """
        nodes_dict = {}
        
        for edge in edges:
            # 添加源节点
            if edge.source not in nodes_dict:
                nodes_dict[edge.source] = {
                    "node_id": edge.source,
                    "node_type": edge.source_type
                }
            
            # 添加目标节点
            if edge.target not in nodes_dict:
                nodes_dict[edge.target] = {
                    "node_id": edge.target,
                    "node_type": edge.target_type
                }
        
        return list(nodes_dict.values())
    
    def update_edge_descriptions(self, edges: List[Edge], user_request: str) -> None:
        """
        为边列表更新节点描述信息（直接修改边对象）
        
        Args:
            edges: 要更新的边对象列表
            user_request: 用户需求描述
        """
        try:
            # 生成节点功能描述
            node_descriptions = self.generate_node_descriptions(user_request, edges)
            
            # 创建节点ID到描述的映射
            node_desc_map = {
                desc["node_id"]: desc["node_description"] 
                for desc in node_descriptions 
                if "node_id" in desc and "node_description" in desc
            }
            
            # 直接更新每条边的节点描述
            for edge in edges:
                if edge.source in node_desc_map:
                    edge.sourceDescription = node_desc_map[edge.source]
                
                if edge.target in node_desc_map:
                    edge.targetDescription = node_desc_map[edge.target]
            
            logger.info(f"成功更新 {len(edges)} 条边的节点描述")
            
        except Exception as e:
            logger.error(f"更新边节点描述失败: {str(e)}")
            # raise EdgeManagerError(f"更新边节点描述失败: {str(e)}")
    

    
    





