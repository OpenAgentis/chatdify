"""
Token统计模块
"""
from typing import Dict, Any, Optional
import tiktoken
from chatdify.utils.logging import get_logger

logger = get_logger(__name__)


def get_tokenizer(model_name: str):
    """获取对应模型的tokenizer
    
    Args:
        model_name: 模型名称
        
    Returns:
        对应的tokenizer
    """
    try:
        if "gpt-4" in model_name.lower():
            return tiktoken.encoding_for_model("gpt-4")
        elif "gpt-3.5" in model_name.lower():
            return tiktoken.encoding_for_model("gpt-3.5-turbo")
        else:
            # 默认使用cl100k_base编码（GPT-4/ChatGPT使用的编码）
            return tiktoken.get_encoding("cl100k_base")
    except Exception as e:
        logger.warning(f"无法获取tokenizer，使用默认编码: {e}")
        return tiktoken.get_encoding("cl100k_base")


def count_tokens(text: str, tokenizer=None) -> int:
    """计算文本的token数量
    
    Args:
        text: 要计算的文本
        tokenizer: 可选的tokenizer，如果不提供则使用默认编码
        
    Returns:
        token数量
    """
    try:
        if tokenizer is None:
            tokenizer = tiktoken.get_encoding("cl100k_base")
        return len(tokenizer.encode(text))
    except Exception as e:
        logger.warning(f"Token计数失败，使用估算值: {e}")
        # 简单估算：中文平均每个字符约1个token，英文约4个字符1个token
        chinese_chars = sum(1 for char in text if '\u4e00' <= char <= '\u9fff')
        other_chars = len(text) - chinese_chars
        return chinese_chars + other_chars // 4


def cache_hit_rate(stats: Dict[str, Any]) -> Optional[float]:
    """Share of input tokens served from the provider's prompt cache, in percent."""
    input_tokens = int(stats.get("input_tokens", 0) or 0)
    if not input_tokens:
        return None
    return round(int(stats.get("cached_tokens", 0) or 0) / input_tokens * 100, 1)


def _empty() -> Dict[str, int]:
    # cached_tokens is the part of input_tokens read from the prompt cache, not an extra amount.
    return {"input_tokens": 0, "cached_tokens": 0, "output_tokens": 0, "total_calls": 0}


def _view(stats: Dict[str, int]) -> Dict[str, int]:
    return {**stats, "total_tokens": stats["input_tokens"] + stats["output_tokens"]}


class TokenStats:
    """Token统计类 - 支持动态call_type统计"""

    def __init__(self):
        self.total_stats = _empty()
        # 按call_type动态统计
        self.type_stats: Dict[str, Dict[str, int]] = {}

    def add_usage(self, input_tokens: int, output_tokens: int, call_type: Optional[str] = None,
                  cached_tokens: int = 0):
        """添加token使用统计

        Args:
            input_tokens: 输入token数量（含命中缓存的部分）
            output_tokens: 输出token数量
            call_type: 调用类型，如果为None则只更新总体统计
            cached_tokens: 输入中命中提供方缓存的token数量
        """
        targets = [self.total_stats]
        if call_type:
            if call_type not in self.type_stats:
                self.type_stats[call_type] = _empty()
                logger.info(f"创建新的call_type统计: {call_type}")
            targets.append(self.type_stats[call_type])
        for stats in targets:
            stats["input_tokens"] += input_tokens
            stats["cached_tokens"] += cached_tokens
            stats["output_tokens"] += output_tokens
            stats["total_calls"] += 1

    def get_stats(self) -> Dict[str, Any]:
        """获取完整统计信息"""
        result = {"total": _view(self.total_stats)}
        for call_type, stats in self.type_stats.items():
            result[call_type] = _view(stats)
        return result

    def get_type_stats(self, call_type: str) -> Dict[str, int]:
        """获取指定call_type的统计信息，不存在则返回空统计"""
        return _view(self.type_stats.get(call_type) or _empty())

    def get_all_call_types(self) -> list[str]:
        """获取所有已记录的call_type列表"""
        return list(self.type_stats.keys())

    def reset(self):
        """重置所有统计"""
        self.total_stats = _empty()
        self.type_stats.clear()
        logger.info("Token统计已重置")

    def get_summary(self) -> str:
        """获取统计摘要字符串"""
        def line(stats: Dict[str, int]) -> str:
            rate = cache_hit_rate(stats)
            cached = f"（缓存命中 {stats['cached_tokens']}，{rate}%）" if rate is not None else ""
            return f"{stats['total_calls']}次调用, {stats['input_tokens']}输入{cached}, {stats['output_tokens']}输出"

        summary = f"总计: {line(self.total_stats)}\n"
        active = {k: v for k, v in self.type_stats.items() if v["total_calls"] > 0}
        if active:
            summary += "分类统计:\n" + "".join(f"  {k}: {line(v)}\n" for k, v in active.items())
        return summary.strip()

