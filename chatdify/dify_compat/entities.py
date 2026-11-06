"""Single import point for Dify symbols used by chatdify.

When upgrading Dify, adapt moved or renamed symbols here only; validators import from this
module and never from Dify directly. Importing it activates the Dify checkout (see
``locator.activate``) and raises ``DifyUnavailableError`` if Dify cannot be used.
"""
from chatdify.dify_compat import ensure_dify

ensure_dify()

# ruff: noqa: E402
from core.app.app_config.entities import VariableEntity, VariableEntityType
from core.file.enums import FileTransferMethod, FileType
from core.variables import (
    ArrayFileSegment,
    ArrayVariable,
    FileSegment,
    NoneVariable,
    SegmentType,
)
from core.workflow.nodes.answer.entities import AnswerNodeData
from core.workflow.nodes.base.entities import VariableSelector
from core.workflow.nodes.base.variable_template_parser import VariableTemplateParser
from core.workflow.nodes.code.entities import CodeNodeData
from core.workflow.nodes.code.exc import CodeNodeError
from core.workflow.nodes.document_extractor.entities import DocumentExtractorNodeData
from core.workflow.nodes.document_extractor.exc import DocumentExtractorError
from core.workflow.nodes.end.entities import EndNodeData, EndStreamParam
from core.workflow.nodes.http_request.entities import HttpRequestNodeBody, HttpRequestNodeData
from core.workflow.nodes.if_else.entities import IfElseNodeData
from core.workflow.nodes.iteration.entities import ErrorHandleMode, IterationNodeData
from core.workflow.nodes.knowledge_retrieval.entities import (
    KnowledgeRetrievalNodeData,
    MultipleRetrievalConfig,
)
from core.workflow.nodes.llm.entities import LLMNodeData
from core.workflow.nodes.loop.entities import LoopNodeData
from core.workflow.nodes.node_mapping import LATEST_VERSION, NODE_TYPE_CLASSES_MAPPING
from core.workflow.nodes.parameter_extractor.entities import ParameterExtractorNodeData
from core.workflow.nodes.question_classifier.entities import QuestionClassifierNodeData
from core.workflow.nodes.start.entities import StartNodeData
from core.workflow.nodes.template_transform.entities import TemplateTransformNodeData
from core.workflow.nodes.tool.entities import ToolNodeData
from core.workflow.nodes.variable_aggregator.entities import (
    AdvancedSettings,
    VariableAggregatorNodeData,
)
from core.workflow.nodes.variable_assigner.v2 import helpers as variable_assigner_helpers
from core.workflow.nodes.variable_assigner.v2.entities import (
    VariableAssignerNodeData,
    VariableOperationItem,
)
from core.workflow.nodes.variable_assigner.v2.enums import InputType, Operation
from core.workflow.utils.condition.entities import (
    Condition,
    SubCondition,
    SupportedComparisonOperator,
)


def get_node_class(node_type: str):
    return NODE_TYPE_CLASSES_MAPPING.get(node_type, {}).get(LATEST_VERSION)


def get_node_data_cls(node_type: str):
    """Pydantic data class of a node type; Dify 1.11+ sets ``_node_data_type`` via generics."""
    node_class = get_node_class(node_type)
    if node_class is None:
        return None
    return getattr(node_class, "_node_data_type", None)
