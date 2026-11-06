"""Download a Dify release into the local cache (``~/.chatdify/dify/<version>``).

Only the ``api`` directory is needed. ``git`` with sparse checkout is preferred; when git
is unavailable or fails, the release tarball is downloaded and only ``api/`` is extracted.
"""
from __future__ import annotations

import io
import shutil
import subprocess
import tarfile
import tempfile
from pathlib import Path
from typing import Callable, Optional

import requests

DIFY_GIT_URL = "https://github.com/langgenius/dify.git"
DIFY_TARBALL_URL = "https://codeload.github.com/langgenius/dify/tar.gz/refs/tags/{version}"


class DifyFetchError(RuntimeError):
    pass


def _git_fetch(version: str, dest: Path, git_url: str, log: Callable[[str], None]) -> None:
    if shutil.which("git") is None:
        raise DifyFetchError("git not found")
    log(f"git sparse clone {git_url} @ {version}")
    subprocess.run(
        [
            "git", "clone", "--depth", "1", "--branch", version,
            "--filter=blob:none", "--sparse", git_url, str(dest),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    subprocess.run(
        ["git", "-C", str(dest), "sparse-checkout", "set", "api"],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )


def _tarball_fetch(version: str, dest: Path, tarball_url: str, log: Callable[[str], None]) -> None:
    url = tarball_url.format(version=version)
    log(f"download {url}")
    response = requests.get(url, timeout=300)
    response.raise_for_status()

    dest.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(response.content), mode="r:gz") as tar:
        members = []
        for member in tar.getmembers():
            parts = Path(member.name).parts
            # archive layout: dify-<version>/api/...
            if len(parts) >= 2 and parts[1] == "api":
                member.name = str(Path(*parts[1:]))
                members.append(member)
        if not members:
            raise DifyFetchError(f"no api/ directory found in {url}")
        try:
            tar.extractall(dest, members=members, filter="data")
        except TypeError:  # Python < 3.11.4 has no extraction filters
            tar.extractall(dest, members=members)


def fetch_dify(
    version: str,
    cache_dir: Path,
    *,
    git_url: Optional[str] = None,
    tarball_url: Optional[str] = None,
    force: bool = False,
    log: Callable[[str], None] = print,
) -> Path:
    """Fetch Dify ``version`` into ``cache_dir/<version>`` and return that path."""
    target = cache_dir / version
    if target.exists():
        if not force:
            log(f"already present: {target} (use --force to re-download)")
            return target
        shutil.rmtree(target)

    cache_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=cache_dir, prefix=f".{version}-") as tmp:
        staging = Path(tmp) / "dify"
        errors = []
        try:
            _git_fetch(version, staging, git_url or DIFY_GIT_URL, log)
        except (DifyFetchError, subprocess.CalledProcessError, OSError) as e:
            detail = getattr(e, "stderr", None)
            detail = detail.decode(errors="replace").strip() if isinstance(detail, bytes) else str(e)
            errors.append(f"git: {detail}")
            log(f"git fetch failed ({detail.splitlines()[-1] if detail else e}), falling back to tarball")
            shutil.rmtree(staging, ignore_errors=True)
            try:
                _tarball_fetch(version, staging, tarball_url or DIFY_TARBALL_URL, log)
            except (DifyFetchError, requests.RequestException, tarfile.TarError, OSError) as e2:
                errors.append(f"tarball: {e2}")
                raise DifyFetchError("failed to fetch Dify:\n  " + "\n  ".join(errors)) from e2

        if not (staging / "api" / "core" / "workflow").is_dir():
            raise DifyFetchError(f"downloaded tree at {staging} does not look like Dify (missing api/core/workflow)")
        shutil.rmtree(staging / ".git", ignore_errors=True)
        staging.rename(target)

    log(f"Dify {version} ready at {target}")
    return target
