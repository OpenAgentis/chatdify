"""Token accounting, including prompt-cache hits."""
from types import SimpleNamespace

import pytest

from chatdify.services.llm_service import LLMService
from chatdify.services.token_stats import TokenStats, cache_hit_rate


def _response(token_usage=None, usage_metadata=None):
    return SimpleNamespace(response_metadata={"token_usage": token_usage} if token_usage else {},
                           usage_metadata=usage_metadata)


@pytest.mark.parametrize(
    "response,expected",
    [
        # OpenAI / GLM (the format GLM-5.3 returns)
        (_response({"prompt_tokens": 3625, "completion_tokens": 158,
                    "prompt_tokens_details": {"cached_tokens": 3584, "cache_write_tokens": None}}), (3625, 158, 3584)),
        # DeepSeek
        (_response({"prompt_tokens": 1000, "completion_tokens": 10, "prompt_cache_hit_tokens": 640,
                    "prompt_cache_miss_tokens": 360}), (1000, 10, 640)),
        # only LangChain's normalised usage_metadata
        (_response(usage_metadata={"input_tokens": 80, "output_tokens": 5,
                                   "input_token_details": {"cache_read": 64}}), (80, 5, 64)),
        # provider without cache reporting
        (_response({"prompt_tokens": 12, "completion_tokens": 3}), (12, 3, 0)),
        (_response(), (0, 0, 0)),
    ],
)
def test_extract_usage(response, expected):
    service = LLMService.__new__(LLMService)
    assert service._extract_usage_from_response(response) == expected


def test_token_stats_tracks_cached_tokens():
    stats = TokenStats()
    stats.add_usage(1000, 100, "node", cached_tokens=800)
    stats.add_usage(500, 50, cached_tokens=0)
    result = stats.get_stats()
    assert result["total"] == {"input_tokens": 1500, "cached_tokens": 800, "output_tokens": 150,
                               "total_calls": 2, "total_tokens": 1650}
    assert result["node"]["cached_tokens"] == 800
    assert cache_hit_rate(result["total"]) == 53.3
    assert "缓存命中 800" in stats.get_summary()


def test_cache_hit_rate_without_input():
    assert cache_hit_rate({}) is None
    assert cache_hit_rate({"input_tokens": 0, "cached_tokens": 0}) is None
