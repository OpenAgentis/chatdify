"""Dify integration: locate the Dify source tree and expose its node entities.

Static validation needs a Dify checkout plus the ``chatdify[dify]`` extra. Without them,
chatdify still generates workflows but skips node-level validation.
"""
from typing import Optional

from chatdify.dify_compat.locator import (
    DifyInfo,
    DifyUnavailableError,
    active_dify,
    locate_dify,
)

__all__ = [
    "DifyInfo",
    "DifyUnavailableError",
    "active_dify",
    "ensure_dify",
    "is_available",
    "locate_dify",
    "unavailable_reason",
]

_unavailable_reason: Optional[str] = None
# (dify_src, cache_dir) that already failed, so lookups are not repeated per node
_failed_key: Optional[tuple] = None


def ensure_dify() -> DifyInfo:
    """Activate Dify using current settings, raising ``DifyUnavailableError`` on failure."""
    from chatdify.dify_compat.locator import activate
    from chatdify.settings import get_settings

    settings = get_settings()
    return activate(settings.dify_src, settings.dify_cache_dir, settings.dify_version)


def is_available() -> bool:
    """Whether static validation against Dify can run; logs the reason once if not."""
    global _unavailable_reason, _failed_key
    from chatdify.settings import get_settings

    settings = get_settings()
    if not settings.dify_static_validation:
        _unavailable_reason = "disabled by dify_static_validation=false"
        return False
    if active_dify() is not None:
        return True
    key = (settings.dify_src, settings.dify_cache_dir, settings.dify_version)
    if key == _failed_key:
        return False
    try:
        ensure_dify()
        return True
    except DifyUnavailableError as e:
        _unavailable_reason = str(e)
        _failed_key = key
        from chatdify.utils.logging import get_logger

        get_logger(__name__).warning(f"Dify 静态校验未启用: {e}")
        return False


def unavailable_reason() -> Optional[str]:
    return _unavailable_reason
