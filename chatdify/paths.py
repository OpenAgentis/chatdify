"""Package-internal resource paths (knowledge base shipped with chatdify)."""
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
# Repository root when running from a git clone / editable install.
PROJECT_ROOT = PACKAGE_DIR.parent

KG_DIR = PACKAGE_DIR / "kg"

NODE_REFERENCE_VERSION = "v4"
NODE_REFERENCE_DIR = KG_DIR / f"node_reference_{NODE_REFERENCE_VERSION}"
NODE_TYPES_CONFIG_PATH = NODE_REFERENCE_DIR / "node_types.yml"

DSL_TEMPLATE_VERSION = "v3"
DSL_TEMPLATE_DIR = KG_DIR / f"dsl_template_{DSL_TEMPLATE_VERSION}"
DSL_TEMPLATE_TYPES_CONFIG_PATH = DSL_TEMPLATE_DIR / "template_types.yml"

NODE_ERROR_FILENAME = "node_error.yml"
NODE_USAGE_FILENAME = "node_usage.yml"
NODE_SAMPLE_FILENAME = "node_sample.yml"
EDGE_ERROR_FILENAME = "edge_error.yml"
EDGE_USAGE_FILENAME = "edge_usage.yml"
EDGE_SAMPLE_FILENAME = "edge_sample.yml"
COMMON_NODE_USAGE_FILENAME = "common_node_usage.yml"
COMMON_EDGE_USAGE_FILENAME = "common_edge_usage.yml"

NODE_RAG_TOP_K = 5
EDGE_RAG_TOP_K = 5
