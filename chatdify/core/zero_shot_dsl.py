"""
ZeroShot DSL 生成：由 LLM 直接输出完整 YAML，与模板检索（dsl_recommend）独立。
"""
from typing import List, Optional

from chatdify.prompts.zero_shot_prompts import (
    ZERO_SHOT_SYSTEM_PROMPT,
    ZERO_SHOT_FULL_DSL_PROMPT,
)
from chatdify.services.file_service import FileService
from chatdify.services.llm_service import LLMService


class ZeroShotDslGenerator:
    """不经过分步边/节点生成，一次性产出完整 DSL；可选传入检索得到的 reference_dsl 供模型参考。"""

    def __init__(self, llm_service: LLMService, file_service: FileService):
        self._llm_service = llm_service
        self._file_service = file_service

    def generate_full_dsl(
        self,
        user_request: str,
        feedback_history: str = "",
        tasks: Optional[List[str]] = None,
        reference_dsl: str = "",
    ) -> str:

        yaml_str = self._llm_service.generate_code(
            system_prompt=ZERO_SHOT_SYSTEM_PROMPT,
            user_prompt=ZERO_SHOT_FULL_DSL_PROMPT,
            variables={
                "user_request": user_request,
                "feedback_history": feedback_history or "(无)",
                "reference_dsl": reference_dsl.strip() if reference_dsl else "(无)",
            },
            format_type="yaml",
        )
        return yaml_str.strip()
