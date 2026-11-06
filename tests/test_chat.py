import io
import json

import pytest
from langchain_core.messages import AIMessage

from chatdify import api, cli
from chatdify.chat import summary
from chatdify.chat.agent import ChatAgent
from chatdify.chat.repl import ChatRepl
from chatdify.chat.session import ChatSession
from chatdify.settings import configure
from chatdify.utils.exceptions import PublishError
from conftest import EXAMPLES

DSL = (EXAMPLES / "dsl" / "audio_script.yml").read_text(encoding="utf-8")


def _without_node(dsl: str, title: str) -> str:
    import yaml

    data = yaml.safe_load(dsl)
    graph = data["workflow"]["graph"]
    removed = {n["id"] for n in graph["nodes"] if n["data"].get("title") == title}
    graph["nodes"] = [n for n in graph["nodes"] if n["id"] not in removed]
    graph["edges"] = [e for e in graph["edges"] if e["source"] not in removed and e["target"] not in removed]
    return yaml.safe_dump(data, allow_unicode=True)


def _result(dsl=DSL, success=True, error=""):
    return api.RunResult(success=success, dsl=dsl, attempts=1, duration=1.0, static_checked=True,
                         dynamic_checked=False, last_error=error,
                         token_stats={"total": {"total_tokens": 100}})


@pytest.fixture
def fake_api(monkeypatch):
    calls = []

    def generate(request, **kw):
        calls.append(("generate", request, kw))
        return _result()

    def modify(dsl, instruction, **kw):
        calls.append(("modify", instruction, kw))
        return _result(_without_node(dsl, "TTS音频转换"))

    def fix(dsl, feedback=None, **kw):
        calls.append(("fix", feedback, kw))
        return _result(dsl)

    def publish(dsl, app_id=None):
        calls.append(("publish", app_id, {}))
        new_id = app_id or "app-1"
        return api.PublishResult(app_id=new_id, url=f"http://dify/app/{new_id}/workflow", created=app_id is None)

    for name, fn in (("generate", generate), ("modify", modify), ("fix", fix), ("publish", publish)):
        monkeypatch.setattr(api, name, fn)
    return calls


class ScriptedLLM:
    """Stands in for a tool-calling chat model; returns the scripted messages in order."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.seen = []

    def bind_tools(self, tools):
        self.tools = tools
        return self

    def invoke(self, messages):
        self.seen.append(list(messages))
        return self.responses.pop(0)


def call(name, **args):
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": f"call-{name}"}])


@pytest.fixture
def session(tmp_path):
    return ChatSession.create(tmp_path / "sessions")


# ---------------------------------------------------------------------- summary


def test_overview_and_diff():
    text = summary.overview(DSL)
    assert "开始(start) → 生成音频大纲(llm) → 生成音频脚本(llm) → TTS音频转换(tool) → 结束(end)" in text
    assert "topic:paragraph" in text
    changes = summary.diff(DSL, _without_node(DSL, "TTS音频转换"))
    assert changes["removed"] == ["TTS音频转换(tool)"] and not changes["added"]
    assert summary.node_detail(DSL, "生成音频大纲")


def test_diff_lists_changed_fields_and_ignores_display_only():
    import yaml

    data = yaml.safe_load(DSL)
    nodes = data["workflow"]["graph"]["nodes"]
    nodes[0]["data"]["desc"] = "new description"
    nodes[1]["data"]["model"] = {"name": "other"}
    changes = summary.diff(DSL, yaml.safe_dump(data, allow_unicode=True))
    assert changes["changed"] == ["生成音频大纲(llm) [model]"]


# ---------------------------------------------------------------------- session


def test_versions_undo_and_resume(session, fake_api):
    v1 = session.generate("做一个播客脚本工作流").version
    v2 = session.modify("删掉 TTS").version
    assert (v1.number, v2.number, v2.parent) == (1, 2, 1)
    assert session.undo().number == 1
    v3 = session.modify("再删一次").version
    assert v3.parent == 1 and [v.number for v in session.lineage()] == [1, 3]

    resumed = ChatSession.load(session.directory)
    assert resumed.current == 3 and resumed.dsl == session.dsl
    assert ChatSession.latest(session.directory.parent) == session.directory


def test_modify_passes_user_words_and_recent_instructions(session, fake_api):
    session.generate("做一个播客脚本工作流")
    session.modify("删除工作流中的TTS节点并重连", user_text="TTS 不要了")
    instruction = fake_api[-1][1]
    assert instruction.startswith("删除工作流中的TTS节点并重连")
    assert "用户原话：TTS 不要了" in instruction
    assert "1. 做一个播客脚本工作流" in instruction
    assert session.version.instruction == "TTS 不要了"


def test_history_turns_limits_context(session, fake_api):
    configure(chat_history_turns=1)
    session.generate("第一句")
    session.modify("第二句")
    session.modify("第三句")
    assert "第一句" not in fake_api[-1][1] and "1. 第二句" in fake_api[-1][1]


def test_fix_defaults_to_last_error(session, fake_api, monkeypatch):
    monkeypatch.setattr(api, "generate", lambda request, **kw: _result(success=False, error="code 节点缺少 main"))
    session.generate("x")
    session.fix()
    assert fake_api[-1][1] == "code 节点缺少 main"
    with pytest.raises(ValueError, match="passed validation"):
        session.fix()


def test_publish_overwrites_same_app_and_auto_publish(session, fake_api):
    session.generate("x")
    assert session.publish().created
    session.publish()
    assert [c[1] for c in fake_api if c[0] == "publish"] == [None, "app-1"]

    configure(chat_auto_publish=True)
    outcome = session.modify("改一下")
    assert outcome.published.app_id == "app-1" and session.published_version == session.current
    from chatdify.chat.agent import outcome_dict

    assert outcome_dict(outcome, session)["published"].startswith("已自动同步")
    configure(chat_auto_publish=False)
    outcome = session.modify("再改一下")
    assert "未同步" in outcome_dict(outcome, session)["published"]


def test_failed_run_without_dsl_keeps_version(session, fake_api, monkeypatch):
    session.generate("x")
    monkeypatch.setattr(api, "modify", lambda dsl, instruction, **kw: _result(dsl="", success=False, error="boom"))
    outcome = session.modify("改坏")
    assert outcome.version is None and session.current == 1


# ---------------------------------------------------------------------- agent


def test_agent_routes_change_to_modify(session, fake_api):
    session.generate("做一个播客脚本工作流")
    llm = ScriptedLLM(call("modify_workflow", instruction="删除 TTS 节点"), AIMessage(content="已删除 TTS 节点。"))
    events = []
    agent = ChatAgent(session, llm, on_event=lambda kind, **kw: events.append((kind, kw["name"])))
    assert agent.handle("TTS 不要了") == "已删除 TTS 节点。"
    assert fake_api[-1][0] == "modify" and "用户原话：TTS 不要了" in fake_api[-1][1]
    assert events == [("tool_start", "modify_workflow"), ("tool_end", "modify_workflow")]
    tool_reply = json.loads(llm.seen[1][-1].content)
    assert tool_reply["version"] == 2 and tool_reply["changes"]["removed"] == ["TTS音频转换(tool)"]
    assert session.messages[-2:] == [{"role": "user", "content": "TTS 不要了"},
                                     {"role": "assistant", "content": "已删除 TTS 节点。"}]


def test_agent_question_uses_show_only(session, fake_api):
    session.generate("x")
    llm = ScriptedLLM(call("show_workflow", detail="summary"), AIMessage(content="有 6 个输入变量。"))
    ChatAgent(session, llm).handle("start 节点有哪些变量？")
    assert [c[0] for c in fake_api] == ["generate"]
    assert "topic" in llm.seen[1][-1].content
    assert "当前版本 v1" in llm.seen[0][0].content


def test_agent_caps_expensive_calls_per_turn(session, fake_api):
    session.generate("x")
    configure(chat_max_tool_calls=2)
    llm = ScriptedLLM(call("modify_workflow", instruction="a"), call("fix_workflow", feedback="b"),
                      call("modify_workflow", instruction="c"), AIMessage(content="先停一下"))
    ChatAgent(session, llm).handle("改三次")
    assert [c[0] for c in fake_api] == ["generate", "modify", "fix"]
    assert "chat_max_tool_calls=2" in llm.seen[3][-1].content


def test_agent_publish_needs_confirmation_first_time(session, fake_api):
    session.generate("x")
    llm = ScriptedLLM(call("publish_workflow"), AIMessage(content="好的，没有发布。"))
    ChatAgent(session, llm, confirm=lambda prompt: False).handle("发布到 Dify")
    assert not any(c[0] == "publish" for c in fake_api)

    llm = ScriptedLLM(call("publish_workflow"), AIMessage(content="已发布。"))
    ChatAgent(session, llm, confirm=lambda prompt: True).handle("发布到 Dify")
    assert session.app_id == "app-1"


def test_agent_tool_error_goes_back_to_model(session, fake_api):
    llm = ScriptedLLM(call("modify_workflow", instruction="x"), AIMessage(content="还没有工作流，请先描述需求。"))
    ChatAgent(session, llm).handle("改一下")
    assert "no workflow to modify" in llm.seen[1][-1].content


def test_ctrl_c_keeps_current_version(session, fake_api, monkeypatch):
    session.generate("x")

    def interrupted(*a, **kw):
        raise KeyboardInterrupt

    monkeypatch.setattr(api, "modify", interrupted)
    llm = ScriptedLLM(call("modify_workflow", instruction="x"))
    with pytest.raises(KeyboardInterrupt):
        ChatAgent(session, llm).handle("改一下")
    assert session.current == 1 and "取消" in session.messages[-1]["content"]


# ---------------------------------------------------------------------- repl


def _repl(session, lines, llm=None):
    feed = iter(lines)

    def read(prompt):
        try:
            return next(feed)
        except StopIteration:
            raise EOFError

    out = io.StringIO()
    agent = ChatAgent(session, llm or ScriptedLLM(), on_event=lambda kind, **kw: repl.on_event(kind, **kw))
    repl = ChatRepl(session, agent, read=read, out=out)
    return repl, out


def test_repl_slash_commands(session, fake_api, tmp_path):
    dsl_file = tmp_path / "in.yml"
    dsl_file.write_text(DSL, encoding="utf-8")
    target = tmp_path / "out.yml"
    repl, out = _repl(session, [f"/load {dsl_file}", "/modify 删掉 TTS", "/diff", "/undo", "/undo",
                                "/history", f"/save {target}", "/publish", "/bogus", "/quit", "never read"])
    assert repl.run() == 0
    text = out.getvalue()
    assert "loaded v1" in text and "v2 ✓" in text and "removed: TTS音频转换(tool)" in text
    assert "back to v1" in text and "error: nothing to undo" in text
    assert "imported v1: http://dify/app/app-1/workflow" in text
    assert "unknown command /bogus" in text and "chatdify chat --resume" in text
    assert target.read_text(encoding="utf-8") == DSL


def test_repl_free_text_goes_to_agent(session, fake_api):
    llm = ScriptedLLM(call("generate_workflow", request="播客脚本"), AIMessage(content="生成好了。"))
    repl, out = _repl(session, ["做一个播客脚本工作流"], llm)
    repl.run()
    text = out.getvalue()
    assert "→ generate_workflow: 播客脚本" in text and "v1 ✓" in text and "生成好了。" in text


# ---------------------------------------------------------------------- api.publish / cli


def test_publish_requires_dify():
    with pytest.raises(PublishError, match="dify_url"):
        api.publish(DSL)


def test_publish_confirms_pending_import(monkeypatch):
    from chatdify.client.dify import app_client

    seen = {}

    class FakeClient:
        def __init__(self, url):
            pass

        def import_app(self, **kw):
            seen.update(kw)
            return {"id": "imp-1", "status": "pending"}

        def confirm_import(self, import_id):
            seen["confirmed"] = import_id
            return {"status": "completed", "app_id": "app-9"}

    monkeypatch.setattr(app_client, "AppClient", FakeClient)
    configure(dify_url="http://dify/", dify_email="a@example.com", dify_password="p")
    result = api.publish(DSL, app_id="app-9")
    assert seen["app_id"] == "app-9" and seen["confirmed"] == "imp-1"
    assert result.url == "http://dify/app/app-9/workflow" and not result.created


def test_chat_without_llm_is_config_error(capsys):
    assert cli.main(["chat"]) == cli.EXIT_ERROR
    assert "chatdify init" in capsys.readouterr().err
