"""Planner agent: decomposes the request and plans the workflow graph.

Steps, in order: intent decomposition into sub-tasks (``generate_tasks``), retrieval of a
similar workflow template (retrieval modes only), node selection, and DAG synthesis
(edges plus a Mermaid sketch). For fix / modify the request is built from the existing DSL
and decomposition is skipped.
"""
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from chatdify.core.dsl_recommend import DslRecommender
from chatdify.core.edge_manager import EdgeManager
from chatdify.core.node_manager import NodeManager, NodeErrors
from chatdify.core.workflow.request_processor import RequestProcessor
from chatdify.models.edge import Edge, EdgeErrors
from chatdify.models.workflow import Workflow
from chatdify.paths import DSL_TEMPLATE_VERSION
from chatdify.services.file_service import FileService
from chatdify.services.llm_service import LLMService
from chatdify.settings import RETRIEVAL_MODES, get_settings
from chatdify.utils.logging import get_logger

logger = get_logger(__name__)

# Modes where the planner builds the graph and the executor fills every node.
GRAPH_MODES = frozenset({"AutoGen", "MixedGen"})


@dataclass
class Plan:
    """The planner's blueprint handed to the executor."""

    user_request: str
    tasks: List[str]
    dsl_mode: str
    reference_dsl: str = ""
    reference_workflow: Optional[Workflow] = None
    edge_errors: EdgeErrors = field(default_factory=EdgeErrors)
    graph: str = ""


class Planner:
    def __init__(self, llm_service: LLMService, file_service: FileService, node_manager: NodeManager):
        self._llm_service = llm_service
        self._file_service = file_service
        self._node_manager = node_manager
        self._request_processor = RequestProcessor(llm_service)
        self._edge_manager = EdgeManager(llm_service, file_service)
        self._dsl_recommender = DslRecommender(llm_service, file_service)

    # ------------------------------------------------------------------ request shaping

    def decompose(
        self,
        user_request: str,
        feedback_history: str,
        expand_request: bool,
        generate_tasks: bool,
    ) -> Tuple[str, List[str]]:
        """Optionally expand the request and break it into sub-tasks."""
        return self._request_processor.process_request(
            user_request, feedback_history, expand_request, generate_tasks
        )

    def bugfix_request(self, dsl: str) -> str:
        return self._request_processor.process_bugfix_request(dsl)

    def modify_request(self, dsl: str, feedback: str) -> str:
        return self._request_processor.process_modify_request(original_dsl=dsl, feedback=feedback)

    # ------------------------------------------------------------------ graph planning

    def plan(
        self,
        workflow: Workflow,
        user_request: str,
        tasks: List[str],
        dsl_mode: str,
        feedback_history: str,
        previous_workflow: Optional[Workflow] = None,
    ) -> Plan:
        """Retrieve references and, in graph modes, select nodes and write the edges into ``workflow``."""
        ref_tasks = [user_request] + list(tasks or [])
        reference_dsl = self.get_reference_dsl("\n".join(ref_tasks), dsl_mode)
        plan = Plan(user_request=user_request, tasks=tasks, dsl_mode=dsl_mode, reference_dsl=reference_dsl)
        if dsl_mode not in GRAPH_MODES:
            return plan

        if dsl_mode == "MixedGen":
            try:
                plan.reference_workflow, _ = self.generate_workflow_from_dsl(reference_dsl)
            except Exception as e:
                logger.error(f"Failed to parse reference DSL: {e}")

        node_list, select_node_types = self._check_node_list(
            user_request=user_request,
            feedback_history=feedback_history,
            reference_dsl=reference_dsl,
        )
        workflow.set_select_node_types(select_node_types)

        logger.info(f"开始生成工作流，工作流模式初始值: {workflow.mode}")

        edges, plan.edge_errors, plan.graph = self._generate_edges(
            user_request=user_request,
            tasks=tasks,
            node_list=node_list,
            select_node_types=select_node_types,
            feedback_history=feedback_history,
            reference_workflow=plan.reference_workflow,
            previous_workflow=previous_workflow,
            workflow_mode=workflow.mode,
        )
        workflow.set_edges(edges)
        return plan

    def get_reference_dsl(self, tasks_str: str, dsl_mode: str) -> str:
        if dsl_mode in RETRIEVAL_MODES:
            reference_dsl = self._dsl_recommender.generate_dsl(tasks_str, dsl_version=DSL_TEMPLATE_VERSION)
            logger.info(f"生成了DSL推荐内容: {reference_dsl}")
            return reference_dsl
        return ""

    def generate_workflow_from_dsl(self, dsl: str) -> Tuple[Workflow, NodeErrors]:
        workflow = Workflow()
        workflow.from_dsl(dsl)
        node_errors = self._node_manager.validate_nodes(workflow)
        return workflow, node_errors

    def _check_node_list(
        self,
        user_request: str,
        feedback_history: str,
        reference_dsl: str,
    ) -> Tuple[List[str], List[str]]:
        select_node_types = None

        if get_settings().node_selector:
            from chatdify.core.workflow.node_selector import NodeRetrievalConfig, NodeSelector

            retriever = NodeSelector(config=NodeRetrievalConfig(top_k=20), file_service=self._file_service)
            query = "\n".join([user_request, feedback_history, reference_dsl])
            select_node_types = retriever.get_selected_node(query)

        node_list, select_node_types = self._file_service.read_node_list(select_node_types)

        if not node_list or not select_node_types:
            raise ValueError("没有可用的节点类型")

        return node_list, select_node_types

    def _generate_edges(
        self,
        user_request: str,
        tasks: List[str],
        node_list: List[str],
        select_node_types: List[str],
        feedback_history: str,
        reference_workflow: Optional[Workflow],
        previous_workflow: Optional[Workflow],
        workflow_mode: str,
    ) -> Tuple[List[Edge], EdgeErrors, str]:
        logger.info("开始生成边")
        return self._edge_manager.generate_edges(
            user_request=user_request,
            tasks=tasks,
            node_list=node_list,
            select_node_types=select_node_types,
            feedback_history=feedback_history,
            reference_workflow=reference_workflow if reference_workflow else None,
            previous_workflow=previous_workflow if previous_workflow else None,
            workflow_mode=workflow_mode,
        )
