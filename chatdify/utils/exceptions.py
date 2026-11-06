"""
异常定义模块
"""

class ChatDifyError(Exception):
    """基础异常类"""
    pass

class LLMServiceError(ChatDifyError):
    """LLM服务异常"""
    pass

class FileServiceError(ChatDifyError):
    """文件服务异常"""
    pass

class GenerateError(ChatDifyError):
    """generate 失败"""
    pass

class FixError(ChatDifyError):
    """fix 失败"""
    pass

class ModifyError(ChatDifyError):
    """modify 失败"""
    pass

class PublishError(ChatDifyError):
    """导入 Dify 失败"""
    pass

class NodeManagerError(ChatDifyError):
    """节点管理器异常"""
    pass

class EdgeManagerError(ChatDifyError):
    """节点管理器异常"""
    pass

class DSLGeneratorError(ChatDifyError):
    """DSL生成器异常"""
    pass

class WorkflowError(ChatDifyError):
    """工作流异常"""
    pass

class NodeError(ChatDifyError):
    """工作流异常"""
    pass

class EdgeError(ChatDifyError):
    """工作流异常"""
    pass

class DslRecommendError(ChatDifyError):
    """DSL生成器异常"""
    pass

class LoginError(ChatDifyError):
    """登录异常"""
    pass

class RateLimitError(ChatDifyError):
    """登录次数异常"""
    pass

class TokenError(ChatDifyError):
    """令牌异常"""
    pass


class NodeSelectorError(Exception):
    """节点选择器专用异常"""
    pass


class EmbeddingInitializationError(NodeSelectorError):
    """嵌入模型初始化异常"""
    pass


class VectorStoreError(NodeSelectorError):
    """向量存储异常"""
    pass
