"""State of one `chatdify chat` conversation: workflow versions, context and the Dify app.

Everything is kept under ``<home>/sessions/<id>/``: ``v<N>.yml`` per version and
``session.json`` for the rest, written after every change so a session can be resumed.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from chatdify import api
from chatdify.chat import summary
from chatdify.progress import ProgressTracker
from chatdify.services.token_stats import cache_hit_rate
from chatdify.settings import get_settings

STATE_FILE = "session.json"


@dataclass
class Version:
    number: int
    action: str  # generate / modify / fix / load
    instruction: str
    parent: Optional[int]
    success: Optional[bool]  # None: not validated yet
    last_error: str = ""
    attempts: int = 0
    duration: float = 0.0
    tokens: int = 0
    created_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))


@dataclass
class Outcome:
    """What a generate / modify / fix call produced, for display and for the chat agent."""

    action: str
    success: bool
    version: Optional[Version]
    changes: Dict[str, List[str]]
    last_error: str = ""
    rounds: int = 0
    duration: float = 0.0
    tokens: int = 0
    cache_hit_rate: Optional[float] = None
    agent_stats: Dict[str, Dict[str, float]] = field(default_factory=dict)
    published: Optional[api.PublishResult] = None
    publish_error: str = ""


class ChatSession:
    def __init__(self, directory: Path):
        self.directory = Path(directory)
        self.versions: List[Version] = []
        self.current: Optional[int] = None
        self.messages: List[Dict[str, str]] = []
        self.input_files: List[str] = []
        self.app_id: Optional[str] = None
        self.app_url: Optional[str] = None
        self.published_version: Optional[int] = None
        self.name: Optional[str] = None

    # ------------------------------------------------------------------ lifecycle

    @classmethod
    def create(cls, root: Optional[Path] = None) -> "ChatSession":
        root = Path(root or get_settings().sessions_dir)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        directory = root / stamp
        n = 1
        while directory.exists():
            n += 1
            directory = root / f"{stamp}_{n}"
        directory.mkdir(parents=True)
        session = cls(directory)
        session._save_state()
        return session

    @classmethod
    def load(cls, directory: Path) -> "ChatSession":
        directory = Path(directory)
        state = json.loads((directory / STATE_FILE).read_text(encoding="utf-8"))
        session = cls(directory)
        session.versions = [Version(**v) for v in state.get("versions", [])]
        for key in ("current", "messages", "input_files", "app_id", "app_url", "published_version", "name"):
            if key in state:
                setattr(session, key, state[key])
        return session

    @classmethod
    def latest(cls, root: Optional[Path] = None) -> Optional[Path]:
        root = Path(root or get_settings().sessions_dir)
        candidates = sorted(p.parent for p in root.glob(f"*/{STATE_FILE}")) if root.exists() else []
        return candidates[-1] if candidates else None

    def _save_state(self) -> None:
        state = {
            "versions": [asdict(v) for v in self.versions],
            "current": self.current,
            "messages": self.messages,
            "input_files": self.input_files,
            "app_id": self.app_id,
            "app_url": self.app_url,
            "published_version": self.published_version,
            "name": self.name,
        }
        path = self.directory / STATE_FILE
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(path)

    # ------------------------------------------------------------------ versions

    @property
    def version(self) -> Optional[Version]:
        return self.get(self.current) if self.current else None

    def get(self, number: int) -> Optional[Version]:
        return next((v for v in self.versions if v.number == number), None)

    def dsl_of(self, number: int) -> str:
        return (self.directory / f"v{number}.yml").read_text(encoding="utf-8")

    @property
    def dsl(self) -> str:
        return self.dsl_of(self.current) if self.current else ""

    def _add_version(self, dsl: str, **fields: Any) -> Version:
        version = Version(number=len(self.versions) + 1, parent=self.current, **fields)
        (self.directory / f"v{version.number}.yml").write_text(dsl, encoding="utf-8")
        self.versions.append(version)
        self.current = version.number
        self._save_state()
        return version

    def load_dsl(self, dsl: str, source: str) -> Version:
        return self._add_version(dsl, action="load", instruction=source, success=None)

    def undo(self) -> Optional[Version]:
        version = self.version
        if not version or version.parent is None:
            return None
        self.current = version.parent
        self._save_state()
        return self.version

    def reset(self) -> None:
        """Start over; earlier versions stay on disk."""
        self.current = None
        self.messages = []
        self.app_id = self.app_url = self.published_version = None
        self.name = None
        self._save_state()

    def save(self, path: Path) -> Path:
        if not self.current:
            raise ValueError("no workflow yet")
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.dsl, encoding="utf-8")
        return path

    def lineage(self) -> List[Version]:
        """Versions from the first one to the current one."""
        chain, number = [], self.current
        while number:
            version = self.get(number)
            chain.append(version)
            number = version.parent
        return list(reversed(chain))

    # ------------------------------------------------------------------ context

    def add_message(self, role: str, content: str) -> None:
        self.messages.append({"role": role, "content": content})
        self._save_state()

    def recent_messages(self, turns: Optional[int] = None) -> List[Dict[str, str]]:
        turns = get_settings().chat_history_turns if turns is None else turns
        if turns <= 0:
            return []
        user_positions = [i for i, m in enumerate(self.messages) if m["role"] == "user"]
        if len(user_positions) <= turns:
            return list(self.messages)
        return self.messages[user_positions[-turns]:]

    def recent_instructions(self, turns: Optional[int] = None) -> List[str]:
        """User-facing instructions behind the current version, oldest first."""
        turns = get_settings().chat_history_turns if turns is None else turns
        if turns <= 0:
            return []
        return [v.instruction for v in self.lineage() if v.action in ("generate", "modify", "fix")][-turns:]

    def _with_context(self, instruction: str, user_text: Optional[str]) -> str:
        parts = [instruction.strip()]
        if user_text and user_text.strip() and user_text.strip() != instruction.strip():
            parts.append(f"用户原话：{user_text.strip()}")
        history = self.recent_instructions()
        if history:
            parts.append("此前已完成的修改（从早到晚，供理解指代，不要重复执行）：\n"
                         + "\n".join(f"{i}. {h}" for i, h in enumerate(history, 1)))
        return "\n\n".join(parts)

    # ------------------------------------------------------------------ actions

    def _record(self, action: str, instruction: str, result: api.RunResult) -> Outcome:
        old_dsl = self.dsl
        total = (result.token_stats or {}).get("total") or {}
        tokens = int(total.get("total_tokens", 0) or 0)
        version = None
        if result.dsl:
            version = self._add_version(
                result.dsl, action=action, instruction=instruction, success=result.success,
                last_error=result.last_error, attempts=result.attempts,
                duration=round(result.duration, 1), tokens=tokens,
            )
        outcome = Outcome(
            action=action, success=result.success, version=version,
            changes=summary.diff(old_dsl, result.dsl) if result.dsl and old_dsl else {},
            last_error=result.last_error, rounds=result.attempts, duration=result.duration,
            tokens=tokens, cache_hit_rate=cache_hit_rate(total), agent_stats=result.agent_stats,
        )
        if version and result.success and self.app_id and get_settings().chat_auto_publish:
            try:
                outcome.published = self.publish()
            except Exception as e:
                outcome.publish_error = str(e)
        return outcome

    def generate(self, request: str, *, name: Optional[str] = None,
                 progress: Optional[ProgressTracker] = None) -> Outcome:
        if name:
            self.name = name
        result = api.generate(request, name=name or self.name, input_files=self.input_files or None,
                              progress=progress)
        return self._record("generate", request, result)

    def modify(self, instruction: str, *, user_text: Optional[str] = None,
               progress: Optional[ProgressTracker] = None) -> Outcome:
        if not self.current:
            raise ValueError("no workflow to modify yet; describe the app to generate one first")
        result = api.modify(self.dsl, self._with_context(instruction, user_text),
                            input_files=self.input_files or None, progress=progress)
        return self._record("modify", user_text or instruction, result)

    def fix(self, feedback: Optional[str] = None, *, progress: Optional[ProgressTracker] = None) -> Outcome:
        version = self.version
        if not version:
            raise ValueError("no workflow to fix yet")
        feedback = (feedback or "").strip() or version.last_error
        if not feedback and version.success:
            raise ValueError("the current version passed validation; say what is wrong to fix it")
        result = api.fix(self.dsl, feedback=feedback or None, input_files=self.input_files or None,
                         progress=progress)
        return self._record("fix", feedback or "按校验结果修复", result)

    def validate(self, *, dynamic: bool = False) -> api.ValidationReport:
        version = self.version
        if not version:
            raise ValueError("no workflow to validate yet")
        requests = [v.instruction for v in self.lineage() if v.action == "generate"]
        report = api.validate(self.dsl, dynamic=dynamic, input_files=self.input_files or None,
                              request=requests[-1] if requests else None)
        if report.static_checked or report.dynamic_checked or report.parse_error:
            version.success = report.valid
            version.last_error = "" if report.valid else report.summary()
            self._save_state()
        return report

    def publish(self, *, new: bool = False) -> api.PublishResult:
        if not self.current:
            raise ValueError("no workflow to publish yet")
        result = api.publish(self.dsl, app_id=None if new else self.app_id)
        self.app_id, self.app_url, self.published_version = result.app_id, result.url, self.current
        self._save_state()
        return result

    def attach(self, path: str) -> str:
        file = Path(path).expanduser()
        if not file.is_file():
            raise ValueError(f"file not found: {path}")
        resolved = str(file.resolve())
        if resolved not in self.input_files:
            self.input_files.append(resolved)
            self._save_state()
        return resolved

    # ------------------------------------------------------------------ views

    def state_text(self) -> str:
        """Current state, given to the chat agent each turn."""
        version = self.version
        if not version:
            return "当前还没有工作流。"
        status = {True: "校验通过", False: "校验未通过", None: "尚未校验"}[version.success]
        lines = [f"当前版本 v{version.number}（{version.action}，{status}）", summary.overview(self.dsl)]
        if version.last_error:
            lines.append("最近一次校验的问题（节选）：\n" + version.last_error[:1500])
        if self.app_url:
            synced = "已同步" if self.published_version == self.current else f"Dify 中是 v{self.published_version}"
            lines.append(f"已发布到 Dify：{self.app_url}（{synced}）")
        if self.input_files:
            lines.append("测试文件：" + ", ".join(Path(f).name for f in self.input_files))
        return "\n".join(lines)
