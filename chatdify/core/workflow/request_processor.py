"""请求处理器"""
from typing import List, Tuple

from chatdify.services.llm_service import LLMService
from chatdify.utils.logging import get_logger
from chatdify.utils.exceptions import GenerateError, ModifyError
from chatdify.prompts.workflow_prompts import (
    SYSTEM_PROMPT,
    EXPAND_REQUEST_PROMPT,
    TASKS_PLANNING_PROMPT_SYSTEM,
    TASKS_PLANNING_PROMPT_USER
)

logger = get_logger(__name__)

class RequestProcessor:
    def __init__(self, llm_service: LLMService):
        self._llm_service = llm_service
    
    def process_request(
        self, 
        user_request: str, 
        feedback_history: str,
        expand_request: bool = True,
        generate_tasks: bool = True
    ) -> Tuple[str, List[str]]:
        processed_request = self._expand_user_request(user_request) if expand_request else user_request
        tasks = self._generate_tasks(processed_request, feedback_history) if generate_tasks else []
        
        logger.info(f"处理后的请求: {processed_request}")

        return processed_request, tasks
    
    def process_bugfix_request(self, user_request: str) -> str:
        """
        处理DSL错误修复请求，为添加修复工作流的提示前缀
        
        Args:
            user_request: 用户的原始DSL内容，待bugfix
            
        Returns:
            str: 添加了修复提示前缀的完整请求
        """
        bugfix_prefix = (
            "请根据提供DIFY DSL工作流内容和错误信息，分析并修复当前工作流中存在的问题。"
            "需要识别错误的根本原因，并提供具体的修复方案来优化工作流的执行效果。\n\n"
            "提供DIFY DSL工作流内容如下：\n"
        )
        
        return bugfix_prefix + user_request

    def process_modify_request(
        self,
        original_dsl: str,
        feedback: str
    ) -> str:
        """处理DSL修改请求
        
        Args:
            original_dsl: 原始DSL内容
            feedback: 用户反馈
            
        Returns:
            处理后的修改请求
        """
        try:
            # 构建包含原始DSL和修改建议的完整请求
            modify_prefix = "请根据以下反馈修改现有的Dify工作流DSL：\n\n"
            
            # 添加原始DSL内容
            dsl_section = f"原始DSL内容：\n```yaml\n{original_dsl}\n```\n\n"
            
            # 添加用户修改建议
            feedback_section = f"用户修改建议：\n{feedback}\n\n"
            
            
            # 组合完整的处理请求
            processed_request = (
                modify_prefix + 
                dsl_section + 
                feedback_section
            )
            
            return processed_request
            
        except Exception as e:
            logger.error(f"处理修改请求失败: {str(e)}")
            raise ModifyError(f"处理修改请求失败: {str(e)}")
            
    def _expand_user_request(self, user_request: str) -> str:
        try:
            return self._llm_service.generate(
                system_prompt=SYSTEM_PROMPT,
                user_prompt=EXPAND_REQUEST_PROMPT,
                variables={"user_request": user_request}
            )
        except Exception as e:
            logger.error(f"扩展用户请求失败: {str(e)}")
            raise GenerateError(f"扩展用户请求失败: {str(e)}")

    def _generate_tasks(self, expanded_request: str, feedback_history: str) -> List[str]:
        try:
            tasks_text = self._llm_service.generate(
                system_prompt=TASKS_PLANNING_PROMPT_SYSTEM,
                user_prompt=TASKS_PLANNING_PROMPT_USER,
                variables={
                    "user_request": expanded_request,
                    "feedback_history": feedback_history
                }
            )
            return self._parse_tasks(tasks_text)
        except Exception as e:
            logger.error(f"生成任务列表失败: {str(e)}")
            return []

    def _parse_tasks(self, tasks_text: str) -> List[str]:
        
        tasks_mermaid_code = tasks_text

        # import mermaid as md
        # mermaid_obj = md.Mermaid(tasks_mermaid_code)
        # logger.info("Mermaid 代码语法校验通过")
        
        logger.info(f"任务规划 Mermaid 代码:\n{tasks_mermaid_code}")

        tasks = [tasks_mermaid_code]

        return tasks
    

        
