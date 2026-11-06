"""工作流上下文管理器"""
from typing import List, Optional
from chatdify.models.workflow import Workflow
from chatdify.utils.logging import get_logger

logger = get_logger(__name__)

class WorkflowContext:
    def __init__(self, name: Optional[str] = None, mode: Optional[str] = None):
        self._tasks: List[str] = []
        self._feedback_history: List[str] = []
        self._previous_workflow: Optional[Workflow] = None
        self._name = name if name else "未命名工作流"
        self._mode = mode if mode else "workflow"

        self._workflow: Workflow = Workflow(name=self._name, mode=self._mode)
        self._user_request: Optional[str] = ""
        self._user_workflow: Optional[Workflow] = None
        
    @property
    def tasks(self) -> List[str]:
        return self._tasks
        
    @tasks.setter
    def tasks(self, value: List[str]):
        self._tasks = value
        
    @property
    def tasks_str(self) -> str:
        return "\n".join([f"- {task}" for task in self._tasks])
    
    @property
    def workflow(self) -> Workflow:
        return self._workflow
    
    @workflow.setter
    def workflow(self, value: Workflow):
        self._workflow = value
    
    @property
    def user_request(self) -> str:
        return self._user_request
    
    @user_request.setter
    def user_request(self, value: str):
        self._user_request = value
        
    @property
    def previous_workflow(self) -> Optional[Workflow]:
        return self._previous_workflow
    
    @previous_workflow.setter
    def previous_workflow(self, value: Optional[Workflow]):
        self._previous_workflow = value
    
    def setup(self, user_request: Optional[str] = None, feedback: Optional[str] = None, previous_workflow: Optional[Workflow] = None, user_workflow: Optional[Workflow] = None):
        if feedback:
            self._feedback_history.append(feedback)
            logger.info(f"记录反馈信息: {feedback}")
        
        if user_request:
            self._user_request = user_request
        
        if user_workflow:
            self._user_workflow = user_workflow
     
        if previous_workflow:
            self._previous_workflow = previous_workflow
            
        self._workflow.reset()
    
    def format_feedback_history(self) -> str:
        if not self._feedback_history:
            return ""
        return "\n".join([f"Feedback {i+1}: {feedback}" for i, feedback in enumerate(self._feedback_history)])
    
    