import time
from functools import wraps
from typing import Callable
from chatdify.utils.logging import get_logger

# logger = get_logger(__name__)


def timing_decorator(func: Callable) -> Callable:
    """计时装饰器"""
    @wraps(func)
    def wrapper(*args, **kwargs):
        logger = get_logger(__name__)
        
        start_time = time.time()
        # 获取上下文信息
        context_info = ""
        if "node_id" in kwargs and "node_type" in kwargs:
            context_info = f"[节点ID: {kwargs['node_id']}, 类型: {kwargs['node_type']}]"
        result = func(*args, **kwargs)
        end_time = time.time()
        elapsed_time = end_time - start_time
        logger.info(f"[timing] 函数 {func.__name__} {context_info} 执行时间: {elapsed_time:.2f} 秒")
        return result
    return wrapper