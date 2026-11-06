"""Progress reporting for long-running generation / repair / modification runs."""
import sys
import time
from enum import Enum
from typing import Optional, Protocol, TextIO, runtime_checkable


class WorkflowStep(str, Enum):
    """One step per agent of the Planner–Executor–Reviewer loop."""

    PLANNING = "planning"
    EXECUTION = "execution"
    REVIEW = "review"


STEP_LABELS = {
    WorkflowStep.PLANNING: "planner",
    WorkflowStep.EXECUTION: "executor",
    WorkflowStep.REVIEW: "reviewer",
}


@runtime_checkable
class ProgressTracker(Protocol):
    def start_step_sync(self, step: WorkflowStep, message: str = "") -> None: ...

    def complete_step_sync(self, message: str = "") -> None: ...

    def fail_step_sync(self, message: str = "") -> None: ...

    def add_step_detail_sync(self, detail: str) -> None: ...


class ConsoleProgressTracker:
    """Writes one line per step event to a stream (stderr by default)."""

    def __init__(self, stream: Optional[TextIO] = None, show_details: bool = False, max_message_len: int = 300):
        self._stream = stream or sys.stderr
        self._show_details = show_details
        self._max_message_len = max_message_len
        self._step: Optional[WorkflowStep] = None
        self._started_at: float = 0.0

    def _write(self, text: str) -> None:
        print(text, file=self._stream, flush=True)

    def _shorten(self, message: str) -> str:
        message = " ".join(message.split())
        if len(message) > self._max_message_len:
            return message[: self._max_message_len] + "..."
        return message

    def _label(self) -> str:
        return STEP_LABELS.get(self._step, "step") if self._step else "step"

    def start_step_sync(self, step: WorkflowStep, message: str = "") -> None:
        self._step = step
        self._started_at = time.perf_counter()
        self._write(f"[{self._label()}] ... {self._shorten(message)}")

    def complete_step_sync(self, message: str = "") -> None:
        elapsed = time.perf_counter() - self._started_at
        self._write(f"[{self._label()}] ok  {self._shorten(message)} ({elapsed:.1f}s)")

    def fail_step_sync(self, message: str = "") -> None:
        elapsed = time.perf_counter() - self._started_at
        self._write(f"[{self._label()}] err {self._shorten(message)} ({elapsed:.1f}s)")

    def add_step_detail_sync(self, detail: str) -> None:
        if self._show_details:
            self._write(detail.rstrip())
