"""Conversational front end: an LLM with tools that drive a ChatSession.

This sits outside the paper's Planner–Executor–Reviewer loop; it only decides which
of generate / modify / fix / validate / publish to call, and those run the loop.
"""
from __future__ import annotations

import json
from typing import Any, Callable, Dict, List, Optional, Tuple

from chatdify.chat import summary
from chatdify.chat.session import ChatSession, Outcome
from chatdify.progress import ProgressTracker
from chatdify.settings import get_settings
from chatdify.utils.exceptions import ChatDifyError

# Each of these runs the full refinement loop: minutes and ~10^5 tokens per call.
EXPENSIVE_TOOLS = frozenset({"generate_workflow", "modify_workflow", "fix_workflow"})
MAX_STEPS = 8
MAX_YAML_CHARS = 20000


def _tool(name: str, description: str, properties: Dict[str, Any], required: List[str]) -> Dict[str, Any]:
    return {"type": "function", "function": {
        "name": name, "description": description,
        "parameters": {"type": "object", "properties": properties, "required": required},
    }}


TOOLS = [
    _tool("show_workflow", "查看当前工作流。summary: 节点结构和输入变量；yaml: 完整 DSL；errors: 最近一次校验的问题；"
          "node: 某个节点的完整配置（node 参数填节点 id 或标题）。不消耗生成额度，回答问题前先用它。",
          {"detail": {"type": "string", "enum": ["summary", "yaml", "errors", "node"]},
           "node": {"type": "string", "description": "detail=node 时的节点 id 或标题"}},
          ["detail"]),
    _tool("generate_workflow", "根据需求从零生成一个新的 Dify 工作流（约 5～10 分钟）。只在还没有工作流，或用户明确要求重新做一个时使用。",
          {"request": {"type": "string", "description": "完整的应用需求，保留用户提到的所有输入、输出和步骤"},
           "name": {"type": "string", "description": "可选的应用名称"}},
          ["request"]),
    _tool("modify_workflow", "按指令修改当前工作流（约 5～10 分钟）。指令要具体，只包含用户要求的改动。",
          {"instruction": {"type": "string", "description": "要做的修改"}},
          ["instruction"]),
    _tool("fix_workflow", "修复当前工作流的错误（约 5～10 分钟）。不填 feedback 时使用最近一次校验的问题。",
          {"feedback": {"type": "string", "description": "用户描述的问题或在 Dify 中看到的报错"}},
          []),
    _tool("validate_workflow", "校验当前工作流，不修改它。dynamic=true 时导入 Dify 实际运行（几分钟），否则只做静态校验（几秒）。",
          {"dynamic": {"type": "boolean"}},
          []),
    _tool("publish_workflow", "把当前版本导入用户的 Dify；已发布过时覆盖同一个应用。仅在用户要求时调用。",
          {}, []),
]

SYSTEM_PROMPT = """你是 ChatDify 的对话助手，帮用户在对话中创建、修改、修复和发布 Dify 工作流。

规则：
1. 还没有工作流时，用户描述应用需求就调用 generate_workflow；已有工作流时，修改意见调用 modify_workflow，除非用户明确要重新做一个。
2. 用户要求修复，或说出在 Dify 中看到的报错时，调用 fix_workflow。
3. 用户只是提问时不要调用 generate / modify / fix；需要细节时先调用 show_workflow，再根据结果回答。
4. generate / modify / fix 每次要几分钟、消耗大量 token。只做用户要求的改动，不要自作主张追加修改；需求含糊时先向用户确认。
5. 用户没有要求时不要调用 publish_workflow。
6. 工具返回后，用简短的话向用户汇报：成功与否、改了哪些节点；失败时说明主要原因和建议的下一步。是否已同步到 Dify 以工具结果中的 published 字段为准。
7. 用用户使用的语言回复。用户可以随时用斜杠命令（/help）直接操作。

当前状态：
{state}"""

EventHandler = Callable[..., None]


def _text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(part.get("text", "") if isinstance(part, dict) else str(part) for part in content)
    return str(content or "")


def outcome_dict(outcome: Outcome, session: ChatSession) -> Dict[str, Any]:
    data: Dict[str, Any] = {
        "action": outcome.action,
        "success": outcome.success,
        "version": outcome.version.number if outcome.version else None,
        "rounds": outcome.rounds,
        "duration_s": round(outcome.duration),
        "tokens": outcome.tokens,
    }
    if outcome.version:
        data["changes"] = outcome.changes
        data["workflow"] = summary.overview(session.dsl)
    else:
        data["note"] = "没有得到可用的 DSL，当前版本未改变"
    if outcome.last_error:
        data["last_error"] = outcome.last_error[:1500]
    if outcome.published:
        data["published"] = f"已自动同步到 Dify 中的同一个应用：{outcome.published.url}"
    elif session.app_id:
        data["published"] = f"未同步；Dify 中仍是 v{session.published_version}，用户要求时再调用 publish_workflow"
    if outcome.publish_error:
        data["publish_error"] = outcome.publish_error
    return data


class ChatAgent:
    def __init__(
        self,
        session: ChatSession,
        llm: Any = None,
        *,
        on_event: Optional[EventHandler] = None,
        confirm: Optional[Callable[[str], bool]] = None,
        progress_factory: Optional[Callable[[], Optional[ProgressTracker]]] = None,
    ):
        self.session = session
        self._llm = llm
        self._on_event = on_event or (lambda kind, **kw: None)
        self._confirm = confirm or (lambda prompt: False)
        self._progress_factory = progress_factory or (lambda: None)
        self.tokens = 0

    @property
    def llm(self) -> Any:
        if self._llm is None:
            from chatdify.services.llm_service import LLMService

            self._llm = LLMService().llm
        return self._llm

    def _messages(self, text: str) -> List[Any]:
        from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

        history = []
        for m in self.session.recent_messages():
            history.append(HumanMessage(m["content"]) if m["role"] == "user" else AIMessage(m["content"]))
        return [SystemMessage(SYSTEM_PROMPT.format(state=self.session.state_text())), *history, HumanMessage(text)]

    def handle(self, text: str) -> str:
        """Answer one user message, calling tools as needed; returns the reply text."""
        from langchain_core.messages import ToolMessage

        messages = self._messages(text)
        self.session.add_message("user", text)
        bound = self.llm.bind_tools(TOOLS)
        limit = get_settings().chat_max_tool_calls
        expensive_calls = 0
        reply = ""
        try:
            for _ in range(MAX_STEPS):
                response = bound.invoke(messages)
                usage = getattr(response, "usage_metadata", None) or {}
                self.tokens += int(usage.get("total_tokens", 0) or 0)
                messages.append(response)
                if not response.tool_calls:
                    reply = _text(response.content).strip()
                    break
                for call in response.tool_calls:
                    name, args = call["name"], call.get("args") or {}
                    if name in EXPENSIVE_TOOLS and expensive_calls >= limit:
                        content: Dict[str, Any] = {"error": (
                            f"本轮已调用 {expensive_calls} 次生成/修改/修复，达到上限（chat_max_tool_calls={limit}）。"
                            "请先向用户汇报结果，并询问是否继续。")}
                    else:
                        expensive_calls += name in EXPENSIVE_TOOLS
                        self._on_event("tool_start", name=name, args=args)
                        content, raw = self._run_tool(name, args, text)
                        self._on_event("tool_end", name=name, result=raw, content=content)
                    messages.append(ToolMessage(json.dumps(content, ensure_ascii=False, default=str),
                                                tool_call_id=call["id"]))
            else:
                reply = "（本轮工具调用步数已达上限，已停止。）"
        except KeyboardInterrupt:
            self.session.add_message("assistant", "（用户取消了这一轮，当前版本未改变）")
            raise
        self.session.add_message("assistant", reply)
        return reply

    def _run_tool(self, name: str, args: Dict[str, Any], user_text: str) -> Tuple[Dict[str, Any], Any]:
        session = self.session
        try:
            if name == "show_workflow":
                return self._show(args.get("detail") or "summary", args.get("node") or ""), None
            if name == "generate_workflow":
                outcome = session.generate(args.get("request") or user_text, name=args.get("name") or None,
                                           progress=self._progress_factory())
                return outcome_dict(outcome, session), outcome
            if name == "modify_workflow":
                outcome = session.modify(args.get("instruction") or user_text, user_text=user_text,
                                         progress=self._progress_factory())
                return outcome_dict(outcome, session), outcome
            if name == "fix_workflow":
                outcome = session.fix(args.get("feedback") or None, progress=self._progress_factory())
                return outcome_dict(outcome, session), outcome
            if name == "validate_workflow":
                report = session.validate(dynamic=bool(args.get("dynamic")))
                return {**report.to_dict(), "summary": report.summary()[:1500]}, report
            if name == "publish_workflow":
                if not session.app_id and not self._confirm(f"Import v{session.current} into Dify ({get_settings().dify_url})?"):
                    return {"error": "用户拒绝了发布"}, None
                result = session.publish()
                return result.to_dict(), result
            return {"error": f"unknown tool {name}"}, None
        except (ValueError, ChatDifyError) as e:
            return {"error": str(e)}, None
        except Exception as e:  # report to the model instead of ending the conversation
            return {"error": f"{type(e).__name__}: {e}"}, None

    def _show(self, detail: str, node: str) -> Dict[str, Any]:
        session = self.session
        if not session.current:
            return {"error": "还没有工作流"}
        if detail == "yaml":
            dsl = session.dsl
            return {"yaml": dsl[:MAX_YAML_CHARS], "truncated": len(dsl) > MAX_YAML_CHARS}
        if detail == "errors":
            version = session.version
            return {"success": version.success, "last_error": version.last_error or "（无）"}
        if detail == "node":
            found = summary.node_detail(session.dsl, node)
            return {"node": found} if found else {"error": f"没有找到节点 {node!r}", "workflow": summary.overview(session.dsl)}
        return {"state": session.state_text(), **summary.describe(session.dsl)}
