"""Locate a Dify source checkout and make its ``api`` package importable.

Dify is not vendored: chatdify imports node entities straight from a Dify source tree,
so upgrading Dify only means pointing at a newer checkout. Lookup order:

1. ``dify_src`` setting (``--dify-src`` / ``CHATDIFY_DIFY_SRC`` / config file)
2. ``<repo>/dify`` git submodule (git clone / editable install)
3. ``~/.chatdify/dify/<version>`` populated by ``chatdify dify fetch``

Without an explicit ``dify_src``, a checkout whose version equals the ``dify_version``
setting wins over the others.
"""
from __future__ import annotations

import sys
import tomllib
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

from chatdify.paths import PROJECT_ROOT

# Imported once to check that Dify and its Python dependencies are usable.
_PROBE_MODULE = "core.workflow.nodes.node_mapping"

# Releases whose node entities live where ``entities.py`` imports them. Dify 1.13.1 moved
# them to ``api/dify_graph`` and 1.14.0 to the separate ``graphon`` package.
SUPPORTED_DIFY_VERSIONS = "1.11.x – 1.13.0"


class DifyUnavailableError(RuntimeError):
    """Dify source code or its Python dependencies are not available."""


@dataclass
class DifyInfo:
    root: Path
    version: Optional[str]
    source: str
    expected_version: Optional[str] = None

    @property
    def api_dir(self) -> Path:
        return self.root / "api"

    @property
    def version_matches(self) -> bool:
        return self.expected_version is None or self.version == self.expected_version


@dataclass
class LocateResult:
    info: Optional[DifyInfo]
    tried: List[Tuple[str, Path]] = field(default_factory=list)


def _normalize_root(path: Path) -> Optional[Path]:
    """Accept either the Dify repo root or its ``api`` directory."""
    path = path.expanduser().resolve()
    if (path / "api" / "core" / "workflow").is_dir():
        return path
    if path.name == "api" and (path / "core" / "workflow").is_dir():
        return path.parent
    return None


def layout_supported(root: Path) -> bool:
    return (root / "api" / Path(*_PROBE_MODULE.split("."))).with_suffix(".py").is_file()


def read_dify_version(root: Path) -> Optional[str]:
    try:
        with open(root / "api" / "pyproject.toml", "rb") as f:
            return tomllib.load(f).get("project", {}).get("version")
    except (OSError, tomllib.TOMLDecodeError):
        return None


def _candidates(dify_src: Optional[Path], cache_dir: Path, version: str) -> List[Tuple[str, Path]]:
    if dify_src:
        # An explicit path must not silently fall back to another checkout.
        return [("dify_src setting", dify_src)]
    candidates = [("repository submodule", PROJECT_ROOT / "dify"), (f"cache ({version})", cache_dir / version)]
    if cache_dir.is_dir():
        for path in sorted(cache_dir.iterdir(), reverse=True):
            if path.name != version:
                candidates.append((f"cache ({path.name})", path))
    return candidates


def _expected_version(version: Optional[str]) -> str:
    if version:
        return version
    from chatdify.settings import get_settings

    return get_settings().dify_version


def locate_dify(
    dify_src: Optional[Path] = None,
    cache_dir: Optional[Path] = None,
    version: Optional[str] = None,
) -> LocateResult:
    from chatdify.settings import get_settings

    if cache_dir is None:
        cache_dir = get_settings().dify_cache_dir
    expected = _expected_version(version)
    result = LocateResult(info=None)
    found: List[DifyInfo] = []
    for source, path in _candidates(dify_src, cache_dir, expected):
        result.tried.append((source, path))
        root = _normalize_root(path)
        if root:
            info = DifyInfo(root=root, version=read_dify_version(root), source=source, expected_version=expected)
            if info.version_matches:
                result.info = info
                return result
            found.append(info)
    result.info = found[0] if found else None
    return result


_active: Optional[DifyInfo] = None


def activate(
    dify_src: Optional[Path] = None,
    cache_dir: Optional[Path] = None,
    version: Optional[str] = None,
) -> DifyInfo:
    """Put ``<dify>/api`` on ``sys.path`` and verify Dify node entities import cleanly."""
    global _active
    if _active is not None:
        return _active

    located = locate_dify(dify_src, cache_dir, version)
    if located.info is None:
        tried = "\n".join(f"  - {source}: {path}" for source, path in located.tried)
        raise DifyUnavailableError(
            "Dify source code not found. Tried:\n"
            f"{tried}\n"
            "Run `chatdify dify fetch`, or pass --dify-src /path/to/dify."
        )

    info = located.info
    api_dir = str(info.api_dir)
    if api_dir not in sys.path:
        sys.path.insert(0, api_dir)

    try:
        __import__(_PROBE_MODULE)
    except ModuleNotFoundError as e:
        sys.path.remove(api_dir)
        if (info.api_dir / (e.name or "").split(".")[0]).exists():
            raise DifyUnavailableError(
                f"Dify {info.version or '(unknown version)'} at {info.root} has no module '{e.name}': "
                f"its code layout is not supported (static validation works with Dify "
                f"{SUPPORTED_DIFY_VERSIONS}). Use a supported release, e.g. "
                "`chatdify dify fetch --version 1.13.0`; see 'Upgrading Dify' in the README."
            ) from e
        raise DifyUnavailableError(
            f"Dify found at {info.root}, but its Python dependency '{e.name}' is missing. "
            'Install the extra from the chatdify source directory: pip install -e ".[dify]"'
        ) from e
    except Exception as e:
        sys.path.remove(api_dir)
        raise DifyUnavailableError(
            f"Failed to import Dify from {info.root} (version {info.version or 'unknown'}): "
            f"{type(e).__name__}: {e}"
        ) from e

    if not info.version_matches:
        warnings.warn(
            f"Using Dify {info.version or 'unknown version'} at {info.root}, but dify_version is "
            f"{info.expected_version}; run `chatdify dify fetch` to get it, or set dify_version.",
            stacklevel=2,
        )
    _active = info
    return info


def active_dify() -> Optional[DifyInfo]:
    return _active
