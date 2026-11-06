"""Runtime settings for chatdify.

Values are resolved in this order (highest first):
explicit overrides passed to ``configure()`` (e.g. CLI flags) > environment variables
(``CHATDIFY_*``) > ``.env`` in the working directory > ``~/.chatdify/config.toml`` > defaults.

Code should read settings at call time via ``get_settings()`` instead of importing
module-level constants, so that CLI overrides take effect.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, Literal, Optional, Tuple, Type

from pydantic import Field, field_validator, model_validator
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    TomlConfigSettingsSource,
)

CHATDIFY_HOME = Path(os.getenv("CHATDIFY_HOME", "~/.chatdify")).expanduser()
CONFIG_FILE = CHATDIFY_HOME / "config.toml"

# Dify release chatdify is tested against; override with dify_version / CHATDIFY_DIFY_VERSION.
DEFAULT_DIFY_VERSION = "1.11.2"

GenerationMode = Literal["AutoGen", "AutoRec", "MixedGen", "ZeroShot", "AutoRecZeroShot"]
GENERATION_MODES: Tuple[str, ...] = ("AutoGen", "AutoRec", "MixedGen", "ZeroShot", "AutoRecZeroShot")
# Modes that retrieve reference DSL templates and therefore need an embedding model.
RETRIEVAL_MODES = frozenset({"AutoRec", "MixedGen", "AutoRecZeroShot"})

# Models written into the generated workflow's nodes. They must exist in the Dify workspace
# the workflow is imported into; override them with the workflow_* settings.
DEFAULT_WORKFLOW_MODELS: Dict[str, Dict[str, Any]] = {
    "llm": {
        "provider": "langgenius/deepseek/deepseek",
        "name": "deepseek-v4-flash",
        "mode": "chat",
        "completion_params": {"max_tokens": 32000, "temperature": 0.2, "thinking": False, "top_p": 0.6},
    },
    "rerank": {"provider": "langgenius/siliconflow/siliconflow", "model": "BAAI/bge-reranker-v2-m3"},
    "embedding": {"provider": "langgenius/siliconflow/siliconflow", "model": "BAAI/bge-m3"},
}
WORKFLOW_MODEL_KINDS = ("llm", "vision_llm", "rerank", "embedding")

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="CHATDIFY_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        toml_file=CONFIG_FILE,
    )

    # LLM (any OpenAI-compatible endpoint)
    llm_model: Optional[str] = None
    llm_base_url: Optional[str] = None
    llm_api_key: Optional[str] = Field(default=None, repr=False)
    # Merged into every chat/completions request body, e.g. {"thinking": {"type": "enabled"}};
    # set as JSON in CHATDIFY_LLM_EXTRA_BODY or as a table in config.toml.
    llm_extra_body: Optional[Dict[str, Any]] = None
    llm_proxy: Optional[str] = None
    llm_max_retries: int = Field(default=3, ge=1)
    llm_retry_delay: float = Field(default=2.0, ge=0)
    llm_debug_http: bool = False

    # Embedding model, only needed by template-retrieval modes
    embedding_model: Optional[str] = None
    embedding_base_url: Optional[str] = None
    embedding_api_key: Optional[str] = Field(default=None, repr=False)
    embedding_proxy: Optional[str] = None

    # Generation behaviour
    generation_mode: GenerationMode = "AutoGen"
    max_retries: int = Field(default=3, ge=1)
    node_max_retries: int = Field(default=3, ge=1)
    expand_request: bool = False
    generate_tasks: bool = False
    node_selector: bool = False

    # Models used by the generated workflow's nodes (see DEFAULT_WORKFLOW_MODELS). Each is a
    # table in config.toml or JSON in CHATDIFY_WORKFLOW_*; keys given replace the default's
    # keys of the same name, so a completion_params table replaces all default parameters.
    workflow_llm: Dict[str, Any] = Field(default_factory=dict)
    workflow_vision_llm: Dict[str, Any] = Field(default_factory=dict)
    workflow_rerank: Dict[str, Any] = Field(default_factory=dict)
    workflow_embedding: Dict[str, Any] = Field(default_factory=dict)

    # Dify source code, used for static validation against Dify's node entities
    dify_src: Optional[Path] = None
    # Version fetched by `chatdify dify fetch` and preferred when several checkouts are found
    dify_version: str = DEFAULT_DIFY_VERSION
    dify_static_validation: bool = True

    # Dify instance, used for dynamic validation (import + run)
    dify_url: Optional[str] = None
    dify_email: Optional[str] = None
    dify_password: Optional[str] = Field(default=None, repr=False)
    dify_dynamic_validation: bool = True
    dify_result_analysis: bool = True

    # `chatdify chat`
    chat_history_turns: int = Field(default=5, ge=0)
    chat_max_tool_calls: int = Field(default=2, ge=1)
    chat_auto_publish: bool = False

    # Local state
    home: Path = CHATDIFY_HOME
    log_dir: Optional[Path] = None
    log_level: str = "INFO"
    log_to_console: bool = True

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: Type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> Tuple[PydanticBaseSettingsSource, ...]:
        return (
            init_settings,
            env_settings,
            dotenv_settings,
            TomlConfigSettingsSource(settings_cls),
        )

    @field_validator("dify_src", "log_dir", "home", mode="before")
    @classmethod
    def _expand_path(cls, value: Any) -> Any:
        if isinstance(value, str):
            return Path(value).expanduser() if value else None
        return value

    @field_validator("dify_url", "llm_proxy", "embedding_proxy", "llm_extra_body", mode="before")
    @classmethod
    def _empty_to_none(cls, value: Any) -> Any:
        return value or None

    @model_validator(mode="after")
    def _default_log_dir(self) -> "Settings":
        if self.log_dir is None:
            self.log_dir = self.home / "logs"
        return self

    @property
    def cache_dir(self) -> Path:
        return self.home / "cache"

    @property
    def sessions_dir(self) -> Path:
        return self.home / "sessions"

    @property
    def dify_cache_dir(self) -> Path:
        return self.home / "dify"

    @property
    def dsl_embedding_cache_dir(self) -> Path:
        # Keyed by embedding model: vectors from different models are not comparable.
        model = (self.embedding_model or "default").replace("/", "_")
        return self.cache_dir / "dsl_embedding" / model

    @property
    def node_reference_embedding_dir(self) -> Path:
        from chatdify.paths import NODE_REFERENCE_VERSION

        return self.cache_dir / f"node_reference_embedding_{NODE_REFERENCE_VERSION}"

    @field_validator("workflow_llm", "workflow_vision_llm", "workflow_rerank", "workflow_embedding", mode="before")
    @classmethod
    def _empty_to_dict(cls, value: Any) -> Any:
        return value or {}

    def workflow_model(self, kind: str) -> Dict[str, Any]:
        """Effective model config for ``kind`` in WORKFLOW_MODEL_KINDS."""
        if kind == "vision_llm":
            return {**self.workflow_model("llm"), **self.workflow_vision_llm}
        return {**DEFAULT_WORKFLOW_MODELS[kind], **getattr(self, f"workflow_{kind}")}

    def default_workflow_models(self) -> list[str]:
        """Kinds still using the built-in defaults, which a user's Dify may not have."""
        kinds = [k for k in ("llm", "rerank", "embedding") if not getattr(self, f"workflow_{k}")]
        if "llm" in kinds and not self.workflow_vision_llm:
            kinds.insert(1, "vision_llm")
        return kinds

    @property
    def dynamic_validation_enabled(self) -> bool:
        return bool(self.dify_url) and self.dify_dynamic_validation

    @property
    def result_analysis_enabled(self) -> bool:
        return self.dynamic_validation_enabled and self.dify_result_analysis

    def missing_llm_fields(self) -> list[str]:
        return [
            name
            for name in ("llm_model", "llm_base_url", "llm_api_key")
            if not getattr(self, name)
        ]


_settings: Optional[Settings] = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def configure(**overrides: Any) -> Settings:
    """Rebuild the global settings; ``None`` values are ignored so unset CLI flags fall through."""
    global _settings
    _settings = Settings(**{k: v for k, v in overrides.items() if v is not None})
    from chatdify.utils.logging import LoggerFactory

    LoggerFactory.reset()
    return _settings
