"""Model settings that override what the LLM wrote into model-backed nodes."""
from typing import Any, Dict

from chatdify.settings import get_settings


class ConfigLoader:
    """Builds per-node overrides from the workflow_* settings (highest priority in NodeConfig)."""

    def load_node_config(self, node_type: str, generator_config: Dict[str, Any]) -> Dict[str, Any]:
        settings = get_settings()
        if node_type == "llm":
            vision = generator_config.get("vision", {}).get("enabled", False)
            return {"model": settings.workflow_model("vision_llm" if vision else "llm")}
        if node_type in ("parameter-extractor", "question-classifier"):
            return {"model": settings.workflow_model("llm")}
        if node_type == "knowledge-retrieval":
            rerank = settings.workflow_model("rerank")
            embedding = settings.workflow_model("embedding")
            return {
                "multiple_retrieval_config": {
                    "reranking_model": {"model": rerank["model"], "provider": rerank["provider"]},
                    "weights": {
                        "vector_setting": {
                            "embedding_model_name": embedding["model"],
                            "embedding_provider_name": embedding["provider"],
                        }
                    },
                }
            }
        return {}
