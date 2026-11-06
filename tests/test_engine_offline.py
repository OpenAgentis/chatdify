"""Planner → Executor → Reviewer loop of the engines, with the LLM-backed agent steps stubbed out."""
import pytest

from chatdify import api
from chatdify.agents.executor import Executor
from chatdify.agents.planner import Plan, Planner
from chatdify.models.workflow import ValidationResult
from chatdify.progress import WorkflowStep
from chatdify.settings import configure
from conftest import EXAMPLES

DSL = (EXAMPLES / "dsl" / "audio_script.yml").read_text(encoding="utf-8")


class RecordingTracker:
    def __init__(self):
        self.events = []

    def start_step_sync(self, step, message=""):
        self.events.append(("start", step))

    def complete_step_sync(self, message=""):
        self.events.append(("ok", None))

    def fail_step_sync(self, message=""):
        self.events.append(("fail", None))

    def add_step_detail_sync(self, detail):
        pass


@pytest.fixture
def fake_llm():
    configure(llm_model="fake", llm_base_url="http://127.0.0.1:9", llm_api_key="sk-test",
              dify_static_validation=False, max_retries=3)


def _stub_agents(monkeypatch, static_valid_per_attempt):
    """Stub planner and executor; return the feedback history the executor saw on each round."""
    calls = []

    def fake_decompose(self, user_request, feedback_history, expand_request, generate_tasks):
        return user_request, []

    def fake_plan(self, workflow, user_request, tasks, dsl_mode, feedback_history, previous_workflow=None):
        return Plan(user_request=user_request, tasks=tasks, dsl_mode=dsl_mode)

    def fake_execute(self, workflow, plan, feedback_history, previous_workflow=None, progress_tracker=None):
        attempt = len(calls)
        calls.append(feedback_history)
        workflow.from_dsl(DSL)
        if not static_valid_per_attempt[attempt]:
            workflow.set_static_errors([
                ValidationResult(is_valid=False, error_type="node", error_message=f"bad node on attempt {attempt}")
            ])

    monkeypatch.setattr(Planner, "decompose", fake_decompose)
    monkeypatch.setattr(Planner, "bugfix_request", lambda self, dsl: "fix this workflow")
    monkeypatch.setattr(Planner, "plan", fake_plan)
    monkeypatch.setattr(Executor, "execute", fake_execute)
    return calls


def test_success_on_first_attempt(fake_llm, monkeypatch):
    calls = _stub_agents(monkeypatch, [True])
    tracker = RecordingTracker()
    result = api.generate("make an audio script", progress=tracker)

    assert result.success
    assert result.attempts == 1
    assert len(calls) == 1
    assert "app:" in result.dsl
    assert not result.dynamic_checked
    assert set(result.agent_stats) == {"planner", "executor", "reviewer"}


def test_each_round_runs_planner_executor_reviewer(fake_llm, monkeypatch):
    _stub_agents(monkeypatch, [False, True])
    tracker = RecordingTracker()
    api.generate("make an audio script", progress=tracker)

    starts = [step for kind, step in tracker.events if kind == "start"]
    round_ = [WorkflowStep.PLANNING, WorkflowStep.EXECUTION, WorkflowStep.REVIEW]
    assert starts == round_ * 2


def test_static_errors_trigger_retry_with_feedback(fake_llm, monkeypatch):
    calls = _stub_agents(monkeypatch, [False, True])
    result = api.generate("make an audio script")

    assert result.success
    assert result.attempts == 2
    assert "bad node on attempt 0" in calls[1]
    assert [r["round"] for r in result.rounds] == [1, 2]
    assert all(r["duration"] is not None for r in result.rounds)
    assert set(result.rounds[0]["agents"]) == {"planner", "executor", "reviewer"}


def test_gives_up_after_max_retries(fake_llm, monkeypatch):
    calls = _stub_agents(monkeypatch, [False, False, False])
    result = api.generate("make an audio script")

    assert not result.success
    assert len(calls) == 3
    assert "bad node on attempt 2" in result.last_error


def test_fix_returns_repaired_workflow(fake_llm, monkeypatch):
    # fix rebuilds the workflow mid-round; round timing must survive that.
    calls = _stub_agents(monkeypatch, [False, True])
    result = api.fix(DSL, feedback="it crashes")

    assert result.success
    assert result.attempts == 2
    assert len(calls) == 2


def test_missing_llm_config_fails_fast():
    from chatdify.utils.exceptions import LLMServiceError

    with pytest.raises(LLMServiceError, match="chatdify init"):
        api.generate("anything")
