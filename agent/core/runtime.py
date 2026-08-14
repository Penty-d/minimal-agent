"""Agent Runtime 主循环。

流程（每次用户输入）：
    组装 context（system + 摘要 + 历史 + 新输入）
    → LLM 决策（返回工具调用或最终答案）
    → 有工具调用：逐个执行、结果回喂 → 继续循环
    → 无工具调用：这就是最终答案 → 返回

设计要点：
- 请求消息列表一次性组装，循环中追加，保证 tool 消息始终紧跟
  产生它的 assistant 消息（协议要求）。
- session.state 置 busy 防止同一会话并发；结束（无论成败）恢复 idle 并落盘。
- 工具错误由注册表转成文本回喂模型，不中断整个循环。
- LLM 网络错误抛 LLMError 给上层，trace 记录现场。
"""

from __future__ import annotations

from agent.core.message import Message
from agent.core.session import Session, SessionManager
from agent.core.trace import TraceLogger
from agent.llm.client import LLMError
from agent.llm.parser import ToolCall, parse_response


class SessionBusyError(Exception):
    """同一会话正在执行中，拒绝并发输入。"""


class AgentRuntime:
    def __init__(self, llm, sessions: SessionManager, trace: TraceLogger | None = None, settings=None):
        self.llm = llm
        self.sessions = sessions
        self.trace = trace
        self._max_turns = getattr(settings, "max_loop_turns", 8)

    # ------------------------------------------------------------------
    def run(self, sid: str, user_input: str, max_turns: int | None = None) -> str:
        """处理一条用户输入，返回 Agent 回答。"""
        session = self.sessions.get(sid)
        if session is None:
            raise KeyError(f"session 不存在: {sid}")
        if session.state == "busy":
            raise SessionBusyError(f"会话 {session.name} 正在处理中，请稍候")

        session.state = "busy"
        limit = max_turns or self._max_turns
        try:
            return self._run_loop(session, user_input, limit)
        except LLMError as e:
            self._trace(session, "error", type="LLMError", message=str(e))
            raise
        except Exception as e:
            self._trace(session, "error", type=type(e).__name__, message=str(e))
            raise
        finally:
            session.state = "idle"
            session.touch()
            self.sessions.persist_all()

    # ------------------------------------------------------------------
    def _run_loop(self, session: Session, user_input: str, max_turns: int) -> str:
        self._trace(session, "user_input", text=user_input)

        # 用户输入先写入历史，保证持久化完整、后续追问能接上
        session.history.append(Message(role="user", content=user_input))
        messages, info = session.context.build_request(session.history)
        self._trace(
            session, "context_build",
            kept=info.kept, dropped=info.dropped, summarized=info.summarized,
        )

        for turn in range(1, max_turns + 1):
            self._trace(session, "llm_call", turn=turn)
            raw = self.llm.chat(messages, tools=session.registry.schemas())
            step = parse_response(raw)
            self._trace(
                session, "step", turn=turn, has_tool=step.has_tool_calls,
                thought=(step.thought or "")[:500] or None,
            )

            if step.has_tool_calls:
                assistant_msg = Message(
                    role="assistant",
                    content=raw.content or "",
                    tool_calls=[self._tc_dict(tc) for tc in step.tool_calls],
                    thought=step.thought,      # 经 to_api() 回传给支持该字段的模型
                )
                session.history.append(assistant_msg)
                messages.append(assistant_msg.to_api())

                for tc in step.tool_calls:
                    self._trace(session, "tool_call", id=tc.id, name=tc.name, arguments=tc.arguments)
                    result = session.registry.execute(tc.name, tc.arguments)
                    self._trace(
                        session, "tool_result", name=tc.name,
                        error=result.error, ms=round(result.duration_ms, 2),
                    )
                    tool_msg = Message(
                        role="tool",
                        content=result.to_api_content(),
                        tool_call_id=tc.id,
                        name=tc.name,
                    )
                    session.history.append(tool_msg)
                    messages.append(tool_msg.to_api())
                continue                    # 有工具调用 → 让模型基于结果再决策

            answer = step.final_answer or "（模型没有给出回答）"
            session.history.append(Message(role="assistant", content=answer, thought=step.thought))
            self._trace(session, "assistant_answer", text=answer)
            return answer

        # 达到最大轮次：防御性停止
        note = f"（已达到最大工具循环轮次 {max_turns}，自动停止。你可以继续追问。）"
        session.history.append(Message(role="assistant", content=note))
        self._trace(session, "max_turns", limit=max_turns)
        return note

    # ------------------------------------------------------------------
    @staticmethod
    def _tc_dict(tc: ToolCall) -> dict:
        return {"id": tc.id, "name": tc.name, "arguments": tc.arguments}

    def _trace(self, session: Session, event: str, **payload) -> None:
        if self.trace:
            self.trace.log(session.id, event, **payload)
