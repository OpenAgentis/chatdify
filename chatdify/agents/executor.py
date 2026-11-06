"""Executor agent: fills every node and compiles the DSL.

In graph modes (AutoGen, MixedGen) each node is generated against the node knowledge base
and checked on the spot (static validation plus up to ``node_max_retries`` regenerations);
the reviewer later checks the assembled workflow as a whole. Other modes take the DSL from
the retrieved template (AutoRec) or from a single LLM call (ZeroShot, AutoRecZeroShot).
"""
import uuid
from copy import deepcopy
from typing import Any, Dict, List, Optional, Tuple

from chatdify.agents.planner import GRAPH_MODES, Plan
from chatdify.core.node_manager import NodeErrors, NodeManager
from chatdify.core.zero_shot_dsl import ZeroShotDslGenerator
from chatdify.models.edge import EdgeErrors
from chatdify.models.node import Node
from chatdify.models.workflow import ValidationResult, Workflow
from chatdify.prompts.workflow_prompts import (
    GENERATE_CONVERSATION_VARIABLES_PROMPT_SYSTEM,
    GENERATE_CONVERSATION_VARIABLES_PROMPT_USER,
)
from chatdify.services.file_service import FileService
from chatdify.services.llm_service import LLMService
from chatdify.utils.logging import get_logger

logger = get_logger(__name__)


class Executor:
    def __init__(self, llm_service: LLMService, file_service: FileService, node_manager: NodeManager):
        self._llm_service = llm_service
        self._file_service = file_service
        self._node_manager = node_manager
        self._zero_shot_dsl = ZeroShotDslGenerator(llm_service, file_service)

    def execute(
        self,
        workflow: Workflow,
        plan: Plan,
        feedback_history: str,
        previous_workflow: Optional[Workflow] = None,
        progress_tracker: Optional[object] = None,
    ) -> None:
        """Turn ``plan`` into nodes on ``workflow`` and record node / edge errors as static errors."""
        dsl_mode = plan.dsl_mode

        if dsl_mode == "AutoRec":
            workflow.from_dsl(plan.reference_dsl)

        if dsl_mode == "ZeroShot":
            full_dsl = self._zero_shot_dsl.generate_full_dsl(
                user_request=plan.user_request,
                feedback_history=feedback_history,
                tasks=plan.tasks,
            )
            if progress_tracker and full_dsl:
                preview = full_dsl[:4000] + ("..." if len(full_dsl) > 4000 else "")
                progress_tracker.add_step_detail_sync("ZeroShot 生成完整 DSL:\n" + preview)
            workflow.from_dsl(full_dsl)

        if dsl_mode == "AutoRecZeroShot":
            full_dsl = self._zero_shot_dsl.generate_full_dsl(
                user_request=plan.user_request,
                feedback_history=feedback_history,
                tasks=plan.tasks,
                reference_dsl=plan.reference_dsl,
            )
            if progress_tracker and full_dsl:
                reference_dsl = plan.reference_dsl
                preview = full_dsl[:4000] + ("..." if len(full_dsl) > 4000 else "")
                ref_preview = (reference_dsl[:2000] + "...") if len(reference_dsl) > 2000 else reference_dsl
                progress_tracker.add_step_detail_sync("AutoRecZeroShot：检索参考 DSL（节选）:\n" + ref_preview)
                progress_tracker.add_step_detail_sync("AutoRecZeroShot：ZeroShot 生成完整 DSL:\n" + preview)
            workflow.from_dsl(full_dsl)

        if dsl_mode in GRAPH_MODES:
            nodes, node_errors = self._generate_nodes(
                workflow=workflow,
                user_request=plan.user_request,
                feedback_history=feedback_history,
                reference_workflow=plan.reference_workflow,
                previous_workflow=previous_workflow,
            )
            workflow.set_nodes(nodes)

            # 会话变量生成步骤：图生成只产出边与节点，这里用 LLM 依据节点对 conversation.* 的
            # 实际使用情况生成会话变量声明及其初值（程序推导仅作回退）
            self._sync_conversation_variables(workflow, plan.user_request)
            if workflow.conversation_variables and progress_tracker:
                conv_names = [v.get("name") for v in workflow.conversation_variables]
                progress_tracker.add_step_detail_sync(
                    "生成会话变量(conversation_variables): " + ", ".join(conv_names)
                )

            self._generate_dsl(workflow)

            self._set_workflow_static_errors(workflow=workflow, edge_errors=plan.edge_errors, node_errors=node_errors)

    def _generate_nodes(
        self,
        workflow: Workflow,
        user_request: str,
        feedback_history: str,
        reference_workflow: Optional[Workflow],
        previous_workflow: Optional[Workflow]
    ) -> Tuple[List[Node], NodeErrors]:
        logger.info("开始生成节点")
        # 继承上一轮会话变量声明，仅供本轮节点生成参考（assigner 类型校验、提示词初值基准）；
        # 最终声明由节点生成完成后的 _sync_conversation_variables 全量重新生成。
        previous_workflow_conversation_variables = ""
        if previous_workflow and previous_workflow.conversation_variables:
            workflow.conversation_variables = deepcopy(previous_workflow.conversation_variables)
            previous_workflow_conversation_variables = "\n".join(
                f"- conversation.{v.get('name')}: 类型={v.get('value_type', 'string')}, 初值={v.get('value')!r}"
                for v in previous_workflow.conversation_variables
                if v.get("name")
            )

        return self._node_manager.generate_nodes(
            workflow=workflow,
            user_request=user_request,
            feedback_history=feedback_history,
            reference_workflow_nodes=reference_workflow.nodes if reference_workflow else None,
            previous_workflow_nodes=previous_workflow.nodes if previous_workflow else None,
            previous_workflow_conversation_variables=previous_workflow_conversation_variables
        )

    def _sync_conversation_variables(self, workflow: Workflow, user_request: str) -> None:
        """生成 advanced-chat 多轮对话的会话变量声明。

        节点生成完成后，依据本轮节点的实际 usage 用 LLM **全量**生成会话变量（类型 + 初值）；
        上一轮继承到 workflow 上的声明仅作节点生成参考，此处不保留、不合并。
        LLM 失败或返回为空时清空后回退程序推导；LLM 漏掉的引用变量用程序推导补齐。
        """
        if workflow.mode != "advanced-chat":
            return
        # 先清空已有会话变量
        workflow.conversation_variables = []
        
        referenced = workflow.referenced_conversation_variable_names()
        if not referenced:
            workflow.conversation_variables = []
            return

        declarations: Optional[List[Dict[str, Any]]] = None
        try:
            usage = workflow.extract_conversation_variable_usage()
            nodes_info = self._node_manager._format_nodes(workflow.nodes)
            declarations = self._generate_conversation_variables_with_llm(
                usage, nodes_info, user_request
            )
        except Exception as e:
            logger.error(f"LLM 生成会话变量失败，回退到程序推导: {e}")

        if declarations:
            workflow.conversation_variables = declarations
            existing_names = {d["name"] for d in declarations}
            missing = [n for n in referenced if n not in existing_names]
            if missing:
                logger.warning(f"LLM 未覆盖会话变量 {missing}，用程序推导补齐")
                for d in workflow._derive_conversation_variables_from_nodes():
                    if d["name"] in missing:
                        workflow.conversation_variables.append(d)
        else:
            workflow.conversation_variables = []
            workflow.sync_conversation_variables()

        logger.info(
            f"会话变量生成完成: {[v.get('name') for v in workflow.conversation_variables]}"
        )

    def _generate_conversation_variables_with_llm(
        self, usage: str, nodes_info: str, user_request: str
    ) -> List[Dict[str, Any]]:
        """调用 LLM 生成会话变量声明，并对类型/初值做规范化校验。"""
        if not usage.strip():
            return []

        raw = self._llm_service.generate_json(
            system_prompt=GENERATE_CONVERSATION_VARIABLES_PROMPT_SYSTEM,
            user_prompt=GENERATE_CONVERSATION_VARIABLES_PROMPT_USER,
            variables={
                "conversation_variable_usage": usage,
                "nodes_info": nodes_info,
                "user_request": user_request,
            },
            call_type='conversation_variables'
        )

        if not isinstance(raw, list):
            logger.error(f"LLM 会话变量返回非数组，忽略: {raw!r}")
            return []

        allowed = set(Workflow._CONVERSATION_DEFAULT_VALUE.keys())
        declarations: List[Dict[str, Any]] = []
        seen = set()
        for item in raw:
            if not isinstance(item, dict):
                continue
            name = item.get("name")
            if not name or name in seen:
                continue
            value_type = item.get("value_type")
            if value_type not in allowed:
                logger.warning(f"会话变量 {name} 的 value_type={value_type!r} 非法，按 string 处理")
                value_type = "string"
            value = item.get("value", Workflow._CONVERSATION_DEFAULT_VALUE.get(value_type))
            value = self._coerce_conversation_value(value, value_type)
            seen.add(name)
            declarations.append({
                "id": str(uuid.uuid4()),
                "name": name,
                "description": item.get("description", "") or "",
                "selector": ["conversation", name],
                "value_type": value_type,
                "value": value,
            })
        return declarations

    @staticmethod
    def _coerce_conversation_value(value: Any, value_type: str) -> Any:
        """把 LLM 给出的初始值规范化到与 value_type 匹配，明显不符时回退类型默认值。"""
        default = Workflow._CONVERSATION_DEFAULT_VALUE.get(value_type, "")
        try:
            if value_type == "number":
                if isinstance(value, bool):
                    return 0
                if isinstance(value, (int, float)):
                    return value
                if isinstance(value, str):
                    s = value.strip()
                    if s.lstrip("-").isdigit():
                        return int(s)
                    if s.lstrip("-").replace(".", "", 1).isdigit():
                        return float(s)
                return 0
            if value_type == "boolean":
                if isinstance(value, bool):
                    return value
                if isinstance(value, str):
                    return value.strip().lower() in ("true", "1", "yes")
                return False
            if value_type == "string":
                if isinstance(value, str):
                    return value
                return "" if value is None else str(value)
            if value_type.startswith("array"):
                return value if isinstance(value, list) else deepcopy(default)
            if value_type == "object":
                return value if isinstance(value, dict) else deepcopy(default)
        except Exception:
            return deepcopy(default)
        return deepcopy(default)

    def _generate_dsl(
        self,
        workflow: Workflow
    ) -> str:
        logger.info("开始生成DSL")

        dsl = workflow.to_dsl()

        return dsl
    
    def _set_workflow_static_errors(self, workflow: Workflow, edge_errors: EdgeErrors, node_errors: NodeErrors) -> None:
        """设置工作流的静态错误
        
        Args:
            workflow: 工作流对象
            edge_errors: 边错误集合
            node_errors: 节点错误集合
        """
        static_validation_results = []

        # 处理节点错误
        if node_errors.has_errors():
            node_errors_str = node_errors.format_errors()
            if not node_errors.is_all_nodes_valid():
                is_valid_nodes = False
            else:
                is_valid_nodes = True

            nodes_validation_result = ValidationResult(
                is_valid=is_valid_nodes,
                error_type="node",
                error_message=node_errors_str,
                data={"node": node_errors}
            )

            static_validation_results.append(nodes_validation_result)

        # 处理边错误
        if edge_errors.has_errors():
            edge_errors_str = edge_errors.format_errors()
            edges_validation_result = ValidationResult(
                is_valid=True,
                error_type="edge",
                error_message=edge_errors_str,
                data={"edge": edge_errors}
            )

            static_validation_results.append(edges_validation_result)
        
        # 设置工作流的静态错误
        if static_validation_results:
            workflow.set_static_errors(static_validation_results)
        else:
            workflow.set_static_errors(None)
        
    