"""Runtime 主循环测试：MockLLM 驱动整条链路（离线、确定性）。"""

import json
from types import SimpleNamespace

import pytest

from agent.core.runtime import AgentRuntime, SessionBusyError
from agent.core.session import SessionManager
from agent.core.trace import TraceLogger
from agent.llm.client import LLMError, RawLLMResponse
from agent.llm.mock import MockLLM


def _make_runtime(tmp_path, llm, max_turns=8):
    sessions = SessionManager(store_dir=str(tmp_path / "sessions"), system_prompt="sys")
    trace = TraceLogger(str(tmp_path / "logs"))
    runtime = AgentRuntime(llm=llm, sessions=sessions, trace=trace,
                           settings=SimpleNamespace(max_loop_turns=max_turns))
    return runtime, sessions, trace


def _tool_call(name, args, i):
    return {"id": f"call_{i}", "type": "function",
            "function": {"name": name, "arguments": json.dumps(args, ensure_ascii=False)}}


def test_full_loop_with_tool(tmp_path):
    """规则 mock：查天气 → 调工具 → 结果回喂 → 基于结果回答。"""
    runtime, sessions, _ = _make_runtime(tmp_path, MockLLM())
    sid = sessions.create("w1").id
    answer = runtime.run(sid, "北京天气怎么样")
    assert "北京" in answer

    roles = [m.role for m in sessions.get(sid).history]
    assert roles == ["user", "assistant", "tool", "assistant"]
    assert sessions.get(sid).state == "idle"


def test_follow_up_accumulates_history(tmp_path):
    runtime, sessions, _ = _make_runtime(tmp_path, MockLLM())
    sid = sessions.create("w").id
    runtime.run(sid, "北京天气怎么样")
    runtime.run(sid, "那上海呢")
    hist = sessions.get(sid).history
    assert sum(1 for m in hist if m.role == "user") == 2
    assert hist[-1].role == "assistant"


def test_max_turns_guard(tmp_path):
    """连续返回工具调用 → 达到轮次上限自动停止。"""
    script = [RawLLMResponse(tool_calls=[_tool_call("weather", {"city": "北京"}, i)]) for i in range(10)]
    runtime, sessions, _ = _make_runtime(tmp_path, MockLLM(script=script), max_turns=3)
    sid = sessions.create("w").id
    answer = runtime.run(sid, "test")
    assert "最大工具循环轮次 3" in answer
    assert sessions.get(sid).state == "idle"


def test_llm_error_propagates_and_resets_state(tmp_path):
    class Boom:
        def chat(self, messages, tools=None, **kw):
            raise LLMError("boom")

    runtime, sessions, _ = _make_runtime(tmp_path, Boom())
    sid = sessions.create("w").id
    with pytest.raises(LLMError):
        runtime.run(sid, "hi")
    assert sessions.get(sid).state == "idle"


def test_busy_state_rejects_concurrent_input(tmp_path):
    runtime, sessions, _ = _make_runtime(tmp_path, MockLLM())
    sid = sessions.create("w").id
    sessions.get(sid).state = "busy"
    with pytest.raises(SessionBusyError):
        runtime.run(sid, "hi")


def test_trace_records_events(tmp_path):
    runtime, sessions, trace = _make_runtime(tmp_path, MockLLM())
    sid = sessions.create("w").id
    runtime.run(sid, "北京天气怎么样")
    events = [json.loads(line)["event"] for line in open(trace.path, encoding="utf-8")]
    for want in ["user_input", "context_build", "llm_call", "tool_call", "tool_result", "assistant_answer"]:
        assert want in events


def test_scripted_tool_then_answer(tmp_path):
    """脚本模式：先调工具，下一轮给最终答案。"""
    script = [
        RawLLMResponse(tool_calls=[_tool_call("calculator", {"expression": "1+2"}, 0)]),
        RawLLMResponse(content="1+2=3"),
    ]
    runtime, sessions, _ = _make_runtime(tmp_path, MockLLM(script=script))
    sid = sessions.create("w").id
    answer = runtime.run(sid, "算一下")
    assert answer == "1+2=3"
    roles = [m.role for m in sessions.get(sid).history]
    assert roles == ["user", "assistant", "tool", "assistant"]
