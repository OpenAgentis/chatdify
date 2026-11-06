"""Reviewer agent: checks the assembled workflow and decides whether to accept it.

Static findings (node and edge errors) are collected by the executor while it builds the
workflow. The reviewer adds dynamic runtime probing on a Dify instance, with generated test
inputs and an LLM judge of the outputs, when ``dify_url`` is configured. Without a Dify
instance the static findings decide.
"""
from typing import List, Optional, Union

from chatdify.core.validator_manager import ValidatorManager
from chatdify.models.workflow import ValidationResult, Workflow
from chatdify.services.file_service import FileService
from chatdify.services.llm_service import LLMService


class Reviewer:
    def __init__(self, llm_service: LLMService, file_service: FileService):
        self._validator_manager = ValidatorManager(llm_service, file_service)

    @property
    def dynamic_enabled(self) -> bool:
        return self._validator_manager.dynamic_enabled

    def review(
        self,
        workflow: Workflow,
        input_file: Optional[Union[str, List[str]]] = None,
        user_request: Optional[str] = None,
    ) -> ValidationResult:
        """Run dynamic validation (a no-op success without Dify) and time it on ``workflow``."""
        workflow.mark_validation_started()
        result = self._validator_manager.validate(
            dsl_content=workflow.to_dsl(),
            input_file=input_file,
            user_request=user_request,
        )
        workflow.mark_validation_completed()
        return result

    def accepts(self, workflow: Workflow, result: ValidationResult) -> bool:
        """Record ``result`` on ``workflow`` and judge it together with the executor's static findings."""
        workflow.set_dynamic_errors([result])
        return self._validator_manager.accepts(workflow.last_errors, result)
