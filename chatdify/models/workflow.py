"""
工作流模型定义
"""
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Tuple
import yaml
import uuid
import re
from datetime import datetime
from copy import deepcopy

from chatdify.utils.logging import get_logger
from chatdify.models.edge import Edge
from chatdify.models.node import Node
from chatdify.utils.exceptions import WorkflowError
from chatdify.models.graph_processor import GraphProcessor


logger = get_logger(__name__)


@dataclass
class ValidationResult:
    """验证结果类"""
    is_valid: bool
    error_type: Optional[str] = None  # 'node' | 'edge' | "未知类型" | 'import' | 'runtime' | 'testcase' | 'result_analysis'
    error_message: Optional[str] = None
    data: Optional[Dict[str, Any]] = None
    running_data: Optional[List[Dict[str, Any]]] = None

    def __repr__(self) -> str:
        # running_data 通常包含所有节点的运行事件，体积过大，日志中只展示长度摘要。
        if self.running_data is None:
            running_repr = "None"
        else:
            running_repr = f"<{len(self.running_data)} events>"

        return (
            "ValidationResult("
            f"is_valid={self.is_valid!r}, "
            f"error_type={self.error_type!r}, "
            f"error_message={self.error_message!r}, "
            f"data={self.data!r}, "
            f"running_data={running_repr})"
        )


@dataclass
class WorkflowErrors:
    """工作流错误集合"""
    static_errors: Optional[List[ValidationResult]] = None
    dynamic_errors: Optional[List[ValidationResult]] = None
    
    def copy(self) -> 'WorkflowErrors':
        """创建当前错误对象的深拷贝
        
        Returns:
            WorkflowErrors: 新的错误对象副本
        """
        
        return WorkflowErrors(
            static_errors=deepcopy(self.static_errors) if self.static_errors else None,
            dynamic_errors=deepcopy(self.dynamic_errors) if self.dynamic_errors else None
        )

    def get_static_error_summary(self) -> str:
        """获取静态错误摘要
        
        Returns:
            str: 格式化的静态错误摘要
        """
        if not self.static_errors:
            return ""
            
        static_messages = []
        for error in self.static_errors:
            if error.error_message:
                static_messages.append(f"- {error.error_type or '未知类型'}: {error.error_message}")
        
        if static_messages:
            return "静态检测错误：\n" + "\n".join(static_messages)
        return ""
    
    def get_dynamic_error_summary(self) -> str:
        """获取动态错误摘要
        
        Returns:
            str: 格式化的动态错误摘要
        """
        if not self.dynamic_errors:
            return ""
            
        dynamic_messages = []
        for error in self.dynamic_errors:
            if not error.is_valid and error.error_message:
                dynamic_messages.append(f"- {error.error_type or '运行时'}: {error.error_message}")
        
        if dynamic_messages:
            return "动态验证错误：\n" + "\n".join(dynamic_messages)
        return ""

    def get_error_summary(self, include_fix_suggestion: bool = True) -> str:
        """获取错误摘要
        
        Args:
            include_fix_suggestion: 是否包含修复建议
            
        Returns:
            str: 格式化的错误摘要
        """
        error_parts = []
        
        # 获取静态错误摘要
        static_summary = self.get_static_error_summary()
        if static_summary:
            error_parts.append(static_summary)
        
        # 获取动态错误摘要
        dynamic_summary = self.get_dynamic_error_summary()
        if dynamic_summary:
            error_parts.append(dynamic_summary)
        
        if error_parts:
            summary = "\n\n".join(error_parts)
            if include_fix_suggestion:
                summary += "\n\n请根据以上信息修正DSL。"
            return summary
        else:
            return ""
    
    def static_is_valid(self) -> bool:
        """静态校验是否通过（节点经重试后仍有失败即视为不通过）"""
        return all(error.is_valid for error in (self.static_errors or []))

    def has_errors(self) -> bool:
        """检查是否有错误"""
        static_has_errors = bool(self.static_errors and any(
            error.error_message for error in self.static_errors
        ))
        
        dynamic_has_errors = bool(self.dynamic_errors and any(
            not error.is_valid and error.error_message for error in self.dynamic_errors
        ))
        
        return static_has_errors or dynamic_has_errors
    
    def get_dynamic_output(self) -> str:
        """获取动态运行结果摘要
        
        Returns:
            str: 最终动态运行输出
        """
        if not self.dynamic_errors:
            return ""
        
        final_outputs = []
        for error in self.dynamic_errors:
            if not error.data:
                continue
            
            if 'data' not in error.data:
                continue

            data = error.data['data']
            outputs = data.get('outputs')

            if not outputs:
                continue

            final_outputs.append(f"outputs={outputs}")
    
        if final_outputs:
            return "最终运行结果：\n" + "\n".join(final_outputs)

        return ""
    
    def get_dynamic_running_result_summary(self) -> str:
        """获取动态运行结果摘要
        
        Returns:
            str: 格式化的动态运行结果摘要
        """
        if not self.dynamic_errors:
            return ""
        
        running_result_messages = []
        for error in self.dynamic_errors:
            if not error.running_data:
                continue
            for event in error.running_data:
                if 'data' not in event:
                    continue

                data = event['data']
                outputs = data.get('outputs')

                if event['event'] == 'node_finished':
                    node_id = data.get('node_id')
                    node_type = data.get('node_type')
                    running_result_messages.append(f"- 运行结果: [event={event['event']}, node_id={node_id}, node_type={node_type}] outputs={outputs}")
                
                if event['event'] == 'workflow_finished':
                    running_result_messages.append(f"- 运行结果: [event={event['event']}] outputs={outputs}")
        
        if running_result_messages:
            return "所有运行结果：\n" + "\n".join(running_result_messages)

        return ""


@dataclass
class Workflow:
    """工作流模型，包含节点和边的集合"""
    edges: List[Edge] = field(default_factory=list)
    nodes: List[Node] = field(default_factory=list)
    dsl: str = ""
    graphdata: Dict[str, Any] = field(default_factory=dict)
    name: str = "未命名工作流"
    version: str = "0.5.0"
    mode: str = "workflow"
    # mode: str = "workflow，advanced-chat"

    # 会话/环境变量与特性（advanced-chat 多轮对话依赖 conversation_variables 持久化跨轮状态）
    conversation_variables: List[Dict[str, Any]] = field(default_factory=list)
    environment_variables: List[Dict[str, Any]] = field(default_factory=list)
    features: Dict[str, Any] = field(default_factory=dict)
    
    execution_count: int = 0
    
    last_errors: WorkflowErrors = field(default_factory=WorkflowErrors)
    total_errors: Dict[int, WorkflowErrors] = field(default_factory=dict)

    # 新增时间字段
    created_at: Optional[datetime] = field(default_factory=lambda: datetime.now())
    completed_at: Optional[datetime] = None
    
    # 新增llm token统计字段
    llm_token_stats: Dict[str, int] = field(default_factory=dict)

    # 新增选中的节点类型列表字段
    select_node_types: List[str] = field(default_factory=list)
    
    # 新增动态验证时间字段
    last_validation_started_at: Optional[datetime] = None
    last_validation_completed_at: Optional[datetime] = None
    last_validation_duration: Optional[float] = None
    # 新增动态验证时长字段
    total_dynamic_validation_duration: Dict[int, float] = field(default_factory=dict)
    
    # 新增每次迭代运行时间字段
    total_execution_duration: Dict[int, float] = field(default_factory=dict)
    
    # 新增每次迭代llm token统计字段
    total_llm_token_stats: Dict[int, Dict[str, Any]] = field(default_factory=dict)

    # 每轮各 agent（planner / executor / reviewer）的耗时与 token 用量
    agent_stats: Dict[int, Dict[str, Dict[str, float]]] = field(default_factory=dict)
    
    # 新增迭代时间记录字段
    iteration_started_at: Dict[int, datetime] = field(default_factory=dict)
    iteration_completed_at: Dict[int, datetime] = field(default_factory=dict)

    def reset(self) -> None:
        """重置工作流到初始状态"""
        self.edges = []
        self.nodes = []
        self.dsl = ""
        self.graphdata = {}
        self.conversation_variables = []
        self.environment_variables = []
        self.features = {}
        self.execution_count = 0
        self.last_errors = WorkflowErrors()
        self.total_errors = {}
        self.completed_at = None
        self.last_validation_started_at = None
        self.last_validation_completed_at = None
        self.last_validation_duration = None
        self.total_dynamic_validation_duration = {}
        self.total_execution_duration = {}
        self.total_llm_token_stats = {}
        self.iteration_started_at = {}
        self.iteration_completed_at = {}
        logger.info("工作流已重置到初始状态")

    def mark_completed(self) -> None:
        """标记工作流为已完成"""
        self.completed_at = datetime.now()
        logger.info(f"工作流已完成，完成时间: {self.completed_at}")
    
    def get_duration(self) -> Optional[float]:
        """获取工作流执行时长（秒）"""
        if self.created_at and self.completed_at:
            return (self.completed_at - self.created_at).total_seconds()
        return None
    
    def mark_validation_started(self) -> None:
        """标记验证开始"""
        self.last_validation_started_at = datetime.now()
        logger.info(f"验证开始，开始时间: {self.last_validation_started_at}")

    def mark_validation_completed(self) -> None:    
        """标记验证完成"""
        self.last_validation_completed_at = datetime.now()
        logger.info(f"验证完成，完成时间: {self.last_validation_completed_at}")
    
    def get_last_validation_duration(self) -> Optional[float]:
        """获取最后一次验证时长（秒）
        
        Returns:
            验证时长（秒），如果不存在则返回 None
        """
        if self.last_validation_duration is not None:
            return self.last_validation_duration
        # 如果 duration 未设置，尝试从时间计算
        if self.last_validation_started_at and self.last_validation_completed_at:
            self.last_validation_duration = (self.last_validation_completed_at - self.last_validation_started_at).total_seconds()
            return self.last_validation_duration

        return None
    
    def mark_iteration_started(self, iteration_index: int) -> None:
        """标记迭代开始
        
        Args:
            iteration_index: 迭代索引
        """
        self.iteration_started_at[iteration_index] = datetime.now()
        logger.info(f"第{iteration_index+1}次迭代开始，开始时间: {self.iteration_started_at[iteration_index]}")
    
    def mark_iteration_completed(self, iteration_index: int) -> None:
        """标记迭代完成
        
        Args:
            iteration_index: 迭代索引
        """
        self.iteration_completed_at[iteration_index] = datetime.now()
        logger.info(f"第{iteration_index+1}次迭代完成，完成时间: {self.iteration_completed_at[iteration_index]}")
    
    def get_iteration_duration(self, iteration_index: int) -> Optional[float]:
        """获取指定迭代的时长（秒）
        
        Args:
            iteration_index: 迭代索引
            
        Returns:
            迭代时长（秒），如果不存在则返回 None
        """
        # 如果已经计算过，直接返回
        if iteration_index in self.total_execution_duration:
            return self.total_execution_duration[iteration_index]
        
        # 如果时间未设置，尝试从开始和结束时间计算
        if iteration_index in self.iteration_started_at and iteration_index in self.iteration_completed_at:
            duration = (self.iteration_completed_at[iteration_index] - self.iteration_started_at[iteration_index]).total_seconds()
            self.total_execution_duration[iteration_index] = duration
            return duration
        
        return None

    def get_node_by_id(self, node_id: str) -> Optional[Node]:
        """通过ID获取节点"""
        for node in self.nodes:
            if node.id == node_id:
                return node
        return None
    
    def set_select_node_types(self, select_node_types: List[str]) -> None:
        """设置选中的节点类型列表"""
        self.select_node_types = select_node_types
        logger.info(f"设置了选中的节点类型列表: {select_node_types}")
    
    def set_edges(self, edges: List[Edge]) -> None:
        """设置工作流的边集合并构建图
        
        Args:
            edges: 边的列表
        """
        self.edges = edges
        self._build_graph()
        logger.info(f"设置了{len(self.edges)}条边并构建图结构")
    
    def set_nodes(self, nodes: List[Node]) -> None:
        """设置工作流的节点集合
        Args:
            nodes: 节点的列表
        """
        self.nodes = nodes
        self.set_mode()
        logger.info(f"设置了{len(self.nodes)}个节点")
    
    def set_static_errors(self, errors: Optional[List[ValidationResult]]) -> None:
        """设置静态错误"""
        self.last_errors.static_errors = errors
        logger.info(f"设置了静态错误: {errors}")
    
    def set_dynamic_errors(self, errors: Optional[List[ValidationResult]]) -> None:
        """设置静态错误"""
        self.last_errors.dynamic_errors = errors
        logger.info(f"设置了动态错误")
    
    def set_mode(self):
        """根据节点类型自动判断工作流模式"""
        # 默认返回workflow模式
        self.mode = "workflow"

        # 检查是否包含answer节点
        for node in self.nodes:
            if node.data.get("type") == "answer":
                self.mode = "advanced-chat"
                break
    
    def _build_graph(self):
        """构建图"""
        processor = GraphProcessor(self.edges)
        self.graph_data = processor.build_graph()
        # 更新处理后的边
        self.edges = processor.edges
    
    def from_dsl(self, dsl: str) -> None:
        """从DSL字符串中加载工作流"""
        try:
            workflow_dict = yaml.safe_load(dsl)
            if not isinstance(workflow_dict, dict):
                raise WorkflowError("无效的DSL格式")
            
            # 解析app
            app_data = workflow_dict.get("app", {})
            self.name = app_data.get("name", "未命名工作流")
            self.mode = app_data.get("mode", "workflow")

            # 解析会话/环境变量与特性（用于 advanced-chat 多轮对话的跨轮状态）
            wf_data = workflow_dict.get("workflow", {})
            self.conversation_variables = wf_data.get("conversation_variables", []) or []
            self.environment_variables = wf_data.get("environment_variables", []) or []
            self.features = wf_data.get("features", {}) or {}

            # 解析边
            edges_data = workflow_dict.get("workflow", {}).get("graph", {}).get("edges", [])
            # 空边抛出异常
            if not edges_data:
                raise WorkflowError("DSL中没有定义任何边")

            edges = [
                Edge.create(edge_data, workflow_mode=self.mode)[0]
                for edge_data in edges_data
            ]

            self.set_edges(edges)
            
            # 解析节点
            nodes_data = workflow_dict.get("workflow", {}).get("graph", {}).get("nodes", [])
            
            # 空节点抛出异常
            if not nodes_data:
                raise WorkflowError("DSL中没有定义任何节点")
            
            nodes = [
                Node.create(node_data)
                for node_data in nodes_data
            ]
            
            self.set_nodes(nodes)

            # add
            self.to_dsl()

            logger.info(f"从DSL加载了{len(self.edges)}条边和{len(self.nodes)}个节点")
            
        except yaml.YAMLError as e:
            logger.error(f"解析DSL失败: {str(e)}")
            raise WorkflowError(f"解析DSL失败: {str(e)}")
        except Exception as e:
            logger.error(f"加载DSL失败: {str(e)}")
            raise WorkflowError(f"加载DSL失败: {str(e)}")
    
    def to_dsl(self) -> str:
        """将工作流转换为DSL字符串"""
        if not self.dsl:
            # 1. 生成YAML
            dsl = self._generate_dsl_yaml()

            # 2. tool_type 转换
            dsl = self._convert_tool_type(dsl)
            
            # 3. 迭代节点的引用转换
            dsl = self._convert_iteration_reference(dsl)

            # 4. 验证YAML格式
            yaml_content = yaml.safe_load(dsl)

            self.dsl = dsl
        
        return self.dsl

    def _fix_iteration_loop_start_node_id(self) -> None:
        """修正iteration节点和loop节点的start_node_id错误
        
        当iteration/loop节点的start_node_id指向其内部子节点时，
        自动修正为对应的iteration-start/loop-start节点
        """
        # 节点类型映射: {容器节点类型: start节点类型}
        container_to_start = {
            "iteration": "iteration-start",
            "loop": "loop-start"
        }
        
        # 构建start节点到容器节点的映射关系: {容器节点ID: start节点ID}
        start_type_to_container = {start_type: container_type for container_type, start_type in container_to_start.items()}
        start_node_maps = {container_type: {} for container_type in container_to_start}
        for node in self.nodes:
            node_type = node.data.get("type")
            container_type = start_type_to_container.get(node_type)
            if container_type:
                parent_id = node.parentId
                if parent_id:
                    start_node_maps[container_type][parent_id] = node.id
        
        # 修正所有容器节点的start_node_id
        for node in self.nodes:
            node_type = node.data.get("type")
            if node_type not in container_to_start:
                continue
                
            start_type = container_to_start[node_type]
            old_start_node_id = node.data.get("start_node_id")
            correct_start_id = start_node_maps[node_type].get(node.id)
            
            if not correct_start_id:
                logger.error(f"未找到{node_type}节点 {node.id} 对应的{start_type}节点")
                continue
            
            if correct_start_id != old_start_node_id:
                node.data["start_node_id"] = correct_start_id
                logger.info(f"修正{node_type}节点 {node.id} 的start_node_id: {old_start_node_id} -> {correct_start_id}")
               
    def _generate_dsl_yaml(self) -> str:
        """生成工作流YAML"""
        try:
            # 空边或者空节点抛出异常
            if not self.edges or not self.nodes:
                raise WorkflowError("DSL中没有定义任何边或者节点")
            
            self._fix_iteration_loop_start_node_id()

            # advanced-chat 多轮场景：若未显式声明会话变量，则从 assigner 写入的 conversation.* 自动补全声明
            if self.mode == "advanced-chat" and not self.conversation_variables:
                self.conversation_variables = self._derive_conversation_variables_from_nodes()

            workflow_body: Dict[str, Any] = {}

            # advanced-chat 多轮对话依赖 conversation_variables 持久化跨轮状态，必须随 DSL 输出，否则会被丢弃
            if self.conversation_variables:
                workflow_body["conversation_variables"] = self.conversation_variables
            if self.environment_variables:
                workflow_body["environment_variables"] = self.environment_variables
            if self.features:
                workflow_body["features"] = self.features

            workflow_body["graph"] = {
                "edges": [edge.to_dict() for edge in self.edges],
                "nodes": [node.to_dict() for node in self.nodes],
                "type": "custom"
            }

            workflow_dict = {
                "app": {
                    "mode": self.mode,
                    "name": self.name
                },

                "version": self.version,

                "workflow": workflow_body
            }
            
            return yaml.dump(workflow_dict, allow_unicode=True, sort_keys=False)
            
        except Exception as e:
            logger.error(f"生成DSL YAML失败: {str(e)}")
            raise WorkflowError(f"生成DSL YAML失败: {str(e)}")
    
    # value_type -> 该类型的默认值（声明会话变量时需要一个合理初始值）
    _CONVERSATION_DEFAULT_VALUE = {
        "string": "",
        "number": 0,
        "boolean": False,
        "array[string]": [],
        "array[number]": [],
        "array[boolean]": [],
        "array[object]": [],
        "object": {},
    }

    # 类型“具体度”排序：越靠后越具体，避免被弱类型（string）覆盖
    _TYPE_SPECIFICITY = {
        "string": 0,
        "boolean": 1,
        "number": 1,
        "object": 2,
        "array[string]": 2,
        "array[number]": 2,
        "array[boolean]": 2,
        "array[object]": 2,
    }

    # 节点输出 -> value_type 的确定性映射（仅登记可确信的，未知一律返回 None 走默认 string）
    _NODE_OUTPUT_TYPES = {
        ("llm", "text"): "string",
        ("agent", "text"): "string",
        ("document-extractor", "text"): "string",
        ("template-transform", "output"): "string",
        ("question-classifier", "class_name"): "string",
        ("knowledge-retrieval", "result"): "array[object]",
    }

    def _infer_constant_type(self, value: Any) -> str:
        """根据常量字面值推断 value_type。"""
        if isinstance(value, bool):
            return "boolean"
        if isinstance(value, (int, float)):
            return "number"
        if isinstance(value, dict):
            return "object"
        if isinstance(value, list):
            if value and all(isinstance(x, bool) for x in value):
                return "array[boolean]"
            if value and all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in value):
                return "array[number]"
            if value and all(isinstance(x, str) for x in value):
                return "array[string]"
            return "array[object]" if value else "array[string]"
        return "string"

    def _infer_node_output_type(self, selector: list, node_type_map: Dict[str, str]) -> Optional[str]:
        """根据来源节点输出推断 value_type；无法确信时返回 None。"""
        if len(selector) < 2:
            return None
        node_type = node_type_map.get(selector[0])
        if not node_type:
            return None
        output_name = selector[1]
        direct = self._NODE_OUTPUT_TYPES.get((node_type, output_name))
        if direct:
            return direct
        # code 节点输出在 node.data.outputs[name].type 中显式声明，可直接采信
        if node_type == "code":
            node = next((n for n in self.nodes if n.id == selector[0]), None)
            if node:
                outputs = node.data.get("outputs", {}) or {}
                declared = outputs.get(output_name, {})
                if isinstance(declared, dict) and declared.get("type"):
                    return declared["type"]
        return None

    def _scan_conversation_references(self) -> Dict[str, str]:
        """扫描所有节点，收集被引用的会话变量名及其推断类型。

        覆盖两类引用：
        1) 变量选择器形如 [conversation, name]（assigner 写入/取值、其他节点的 variable_selector 等）。
        2) 模板字符串中的 {{#conversation.name#}}（llm/answer/template 等节点的文本引用）。
        类型推断：append/extend 视为数组、+= 等视为数字；over-write/set 时解析“源值”的真实
        类型（常量字面值 / 来源节点输出 / 其它会话变量），避免把数组源写入被默认推断为 string 的
        目标会话变量，导致 Dify 运行期报 “Invalid input value”。
        返回 {变量名: value_type}。
        """
        array_ops = {"append", "extend"}
        number_ops = {"+=", "-=", "*=", "/="}
        ref_pattern = re.compile(r"conversation\.([A-Za-z_][A-Za-z0-9_]*)")

        names: Dict[str, str] = {}
        # 形如 (目标会话变量名, 源会话变量名)：over-write/set 一个会话变量到另一个，源类型待解析后回填
        pending_conversation_refs: List[Tuple[str, str]] = []
        node_type_map = {n.id: n.data.get("type") for n in self.nodes}

        def note(name: str, value_type: str) -> None:
            # 更“具体”的类型优先，避免被弱类型（string）覆盖
            if name in names and (
                self._TYPE_SPECIFICITY.get(value_type, 0)
                <= self._TYPE_SPECIFICITY.get(names[name], 0)
                and names[name] != value_type
            ):
                return
            names[name] = value_type

        def walk(obj: Any) -> None:
            if isinstance(obj, dict):
                for v in obj.values():
                    walk(v)
            elif isinstance(obj, list):
                # 形如 [conversation, name, ...] 的变量选择器
                if len(obj) >= 2 and obj[0] == "conversation" and isinstance(obj[1], str):
                    note(obj[1], "string")
                for v in obj:
                    walk(v)
            elif isinstance(obj, str):
                for m in ref_pattern.findall(obj):
                    note(m, "string")

        def resolve_write_source_type(item: Dict[str, Any], target_name: str) -> Optional[str]:
            """解析 over-write/set 操作写入的“源值”类型；返回 None 表示无法确信。"""
            input_type = (item.get("input_type") or "").lower()
            value = item.get("value")
            if input_type == "constant":
                return self._infer_constant_type(value)
            if input_type == "variable" and isinstance(value, (list, tuple)) and len(value) >= 2:
                src = list(value)
                if src[0] == "conversation" and isinstance(src[1], str):
                    pending_conversation_refs.append((target_name, src[1]))
                    return None
                if src[0] == "sys":
                    return "string"
                return self._infer_node_output_type(src, node_type_map)
            return None

        for node in self.nodes:
            walk(node.data)
            # assigner 写入目标可推断更精确的类型
            if node.data.get("type") == "assigner":
                for item in node.data.get("items", []) or []:
                    selector = item.get("variable_selector") or []
                    if len(selector) < 2 or selector[0] != "conversation":
                        continue
                    target_name = selector[1]
                    op = (item.get("operation") or item.get("write_mode") or "").lower()
                    if op in array_ops:
                        note(target_name, "array[string]")
                    elif op in number_ops:
                        note(target_name, "number")
                    elif op == "clear":
                        continue
                    else:
                        src_type = resolve_write_source_type(item, target_name)
                        if src_type:
                            note(target_name, src_type)
                        else:
                            note(target_name, "string")

        # 回填会话变量之间的赋值依赖：源类型确定后，让目标对齐源类型（迭代至稳定）
        for _ in range(len(pending_conversation_refs) + 1):
            changed = False
            for target_name, src_name in pending_conversation_refs:
                src_type = names.get(src_name)
                if src_type and self._TYPE_SPECIFICITY.get(src_type, 0) > self._TYPE_SPECIFICITY.get(
                    names.get(target_name, "string"), 0
                ):
                    note(target_name, src_type)
                    changed = True
            if not changed:
                break

        return names

    def _derive_conversation_variables_from_nodes(self) -> List[Dict[str, Any]]:
        """根据节点中对 conversation.* 的引用，推导会话变量声明列表。

        advanced-chat 多轮对话依赖会话变量持久化跨轮状态；若 DSL 未显式声明，
        Dify 导入/运行时引用 conversation.xxx 会失败。
        """
        names = self._scan_conversation_references()
        derived: List[Dict[str, Any]] = []
        for name, value_type in names.items():
            derived.append({
                "id": str(uuid.uuid4()),
                "name": name,
                "description": "",
                "selector": ["conversation", name],
                "value_type": value_type,
                "value": deepcopy(self._CONVERSATION_DEFAULT_VALUE.get(value_type, "")),
            })
        if derived:
            logger.info(f"从节点引用推导出 {len(derived)} 个会话变量声明: {list(names.keys())}")
        return derived

    def referenced_conversation_variable_names(self) -> List[str]:
        """返回节点中实际引用到的全部 conversation.* 变量名（确定性扫描，用于覆盖校验）。"""
        return list(self._scan_conversation_references().keys())

    def extract_conversation_variable_usage(self) -> str:
        """汇总各 conversation.* 变量在节点中的使用事实（写入操作 / 分支条件 / 读取引用）。

        仅做确定性的事实抽取，不做类型与初值的推断——把类型与初始值的判断交给 LLM，
        以避免程序启发式推断（尤其是 over-write 源类型、轮次计数初值）出错。
        """
        ref_pattern = re.compile(r"conversation\.([A-Za-z_][A-Za-z0-9_]*)")
        usage: Dict[str, Dict[str, List[str]]] = {}

        def ensure(name: str) -> Dict[str, List[str]]:
            if name not in usage:
                usage[name] = {"writes": [], "conditions": [], "reads": []}
            return usage[name]

        def title_of(node) -> str:
            return node.data.get("title") or node.id

        for node in self.nodes:
            ntype = node.data.get("type")

            if ntype == "assigner":
                for item in node.data.get("items", []) or []:
                    selector = item.get("variable_selector") or []
                    if len(selector) >= 2 and selector[0] == "conversation":
                        op = item.get("operation") or item.get("write_mode") or ""
                        input_type = item.get("input_type") or ""
                        val = item.get("value")
                        ensure(selector[1])["writes"].append(
                            f"节点[{title_of(node)}] operation={op} input_type={input_type} value={val!r}"
                        )

            if ntype == "if-else":
                for case in node.data.get("cases") or []:
                    case_id = case.get("id") or case.get("case_id") or ""
                    for cond in case.get("conditions") or []:
                        selector = cond.get("variable_selector") or []
                        if len(selector) >= 2 and selector[0] == "conversation":
                            op = cond.get("comparison_operator") or ""
                            val = cond.get("value")
                            ensure(selector[1])["conditions"].append(
                                f"节点[{title_of(node)}] 分支[{case_id}] {op} {val!r}"
                            )

            found: set = set()

            def walk(obj: Any) -> None:
                if isinstance(obj, dict):
                    for v in obj.values():
                        walk(v)
                elif isinstance(obj, list):
                    for v in obj:
                        walk(v)
                elif isinstance(obj, str):
                    for m in ref_pattern.findall(obj):
                        found.add(m)

            walk(node.data)
            for name in found:
                ensure(name)["reads"].append(f"节点[{title_of(node)}]({ntype})")

        if not usage:
            return ""

        lines: List[str] = []
        for name, u in usage.items():
            lines.append(f"会话变量 conversation.{name}:")
            if u["writes"]:
                lines.append("  写入(assigner):")
                lines.extend(f"    - {w}" for w in u["writes"])
            if u["conditions"]:
                lines.append("  分支条件(if-else):")
                lines.extend(f"    - {c}" for c in u["conditions"])
            if u["reads"]:
                lines.append("  读取引用: " + ", ".join(sorted(set(u["reads"]))))
        return "\n".join(lines)

    def sync_conversation_variables(self) -> None:
        """显式生成/补全会话变量声明（程序兜底实现，LLM 生成失败时回退使用）。

        chatdify 的图生成（AutoGen/MixedGen）只产出边与节点，不产出会话变量；
        本方法在节点生成完成后，根据节点对 conversation.* 的实际引用，补全
        workflow.conversation_variables。已有的显式声明（如来自参考 DSL）保留，
        仅追加缺失的变量，避免覆盖。
        """
        if self.mode != "advanced-chat":
            return

        derived = self._derive_conversation_variables_from_nodes()
        if not derived:
            return

        existing_names = {v.get("name") for v in self.conversation_variables}
        added = [d for d in derived if d["name"] not in existing_names]
        if added:
            self.conversation_variables.extend(added)
            logger.info(
                f"会话变量生成步骤：补全 {len(added)} 个会话变量 "
                f"{[d['name'] for d in added]}（已有 {len(existing_names)} 个）"
            )

    def _convert_tool_type(self, text:str) -> str:
        # Pattern to replace values starting with tool_ with tool
        pattern = r'(type|sourceType|targetType):\s*tool_\w+'
        replacement = r'\1: tool'
        
        # Execute regex replacement
        result = re.sub(pattern, replacement, text)
        
        return result
    
    def _convert_iteration_reference(self, text:str) -> str:
        # 使用正则表达式匹配数字+start.item的模式，并替换为数字+.item
        pattern = r'(\d+)start\.item'
        replacement = r'\1.item'
        
        # 执行替换
        result = re.sub(pattern, replacement, text)
        
        return result

    def copy(self) -> 'Workflow':
        """创建当前工作流对象的深拷贝
        
        Returns:
            Workflow: 新的工作流对象副本
        """
        # 创建新的工作流实例
        new_workflow = Workflow(
            edges=[edge.copy() for edge in self.edges],
            nodes=[node.copy() for node in self.nodes],
            dsl=self.dsl,
            graphdata=deepcopy(self.graphdata),
            name=self.name,
            version=self.version,
            mode=self.mode,
            conversation_variables=deepcopy(self.conversation_variables),
            environment_variables=deepcopy(self.environment_variables),
            features=deepcopy(self.features),
            execution_count=self.execution_count,
            last_errors=self.last_errors.copy(),
            total_errors=deepcopy(self.total_errors),
            created_at=self.created_at,
            completed_at=self.completed_at,
            total_dynamic_validation_duration=deepcopy(self.total_dynamic_validation_duration),
            total_execution_duration=deepcopy(self.total_execution_duration),
            total_llm_token_stats=deepcopy(self.total_llm_token_stats)
        )
        
        logger.info(f"创建工作流副本: {self.name}")
        return new_workflow


