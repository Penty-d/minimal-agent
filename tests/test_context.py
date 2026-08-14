"""Context 管理测试：reasoning 回传规则、干净截断、摘要触发时机。"""

from agent.core.context import ContextManager, estimate_tokens
from agent.core.message import Message


def _mk_history(n: int) -> list[Message]:
    hist = []
    for i in range(n):
        hist.append(Message(role="user", content=f"问题{i}" + "好" * 40))
        hist.append(Message(role="assistant", content=f"回答{i}" + "好" * 40))
    return hist


# ----------------------------------------------------------------------
# reasoning_content 回传规则


def test_reasoning_roundtrip_only_for_tool_calls():
    m = Message(role="assistant", content="", thought="先想", tool_calls=[{"id": "c1", "name": "x", "arguments": {}}])
    assert m.to_api().get("reasoning_content") == "先想"

    m2 = Message(role="assistant", content="答案", thought="先想")
    assert "reasoning_content" not in m2.to_api()


# ----------------------------------------------------------------------
# 截断


def test_truncation_never_starts_with_tool():
    """截断后的请求后缀不能以 tool 消息开头（协议要求）。"""
    hist = _mk_history(6)
    cm = ContextManager(system_prompt="sys", max_context_tokens=300)
    messages, info = cm.build_request(hist)
    assert info.dropped > 0
    tail = [m for m in messages if m["role"] != "system"]
    assert tail[0]["role"] != "tool"


def test_truncation_keeps_last_message():
    hist = _mk_history(6)
    cm = ContextManager(system_prompt="sys", max_context_tokens=300)
    messages, info = cm.build_request(hist)
    assert messages[-1]["role"] == "assistant"      # 至少保留最后一条（旧回合的答）
    assert info.kept >= 1


def test_no_truncation_when_budget_sufficient():
    hist = _mk_history(2)
    cm = ContextManager(system_prompt="sys", max_context_tokens=100000)
    _, info = cm.build_request(hist)
    assert info.dropped == 0 and not info.summarized


# ----------------------------------------------------------------------
# 摘要


def test_summary_triggered_only_on_truncation():
    hist = _mk_history(6)
    cm = ContextManager(system_prompt="sys", max_context_tokens=300, summarizer=lambda old, text: "压缩后的摘要")
    messages, info = cm.build_request(hist)
    assert info.summarized
    assert any("压缩后的摘要" in m["content"] for m in messages)


def test_summary_placed_after_system_prompt():
    hist = _mk_history(6)
    cm = ContextManager(system_prompt="sys", max_context_tokens=300, summarizer=lambda old, text: "摘要内容")
    messages, _ = cm.build_request(hist)
    assert messages[0]["role"] == "system"
    assert messages[1]["role"] == "system" and "摘要内容" in messages[1]["content"]


def test_summary_fallback_without_summarizer():
    """无 summarizer 时用提取式兜底（保住最近一条用户意图），不抛异常。"""
    hist = _mk_history(6)
    cm = ContextManager(system_prompt="sys", max_context_tokens=300)
    _, info = cm.build_request(hist)
    assert info.summary and "压缩" in info.summary


def test_incremental_summary_folds_once():
    """同一批消息只折叠一次，不重复耗 token。"""
    hist = _mk_history(8)
    calls = []
    cm = ContextManager(
        system_prompt="sys", max_context_tokens=300,
        summarizer=lambda old, text: (calls.append(len(text)) or "摘要"),
    )
    cm.build_request(hist)
    cm.build_request(hist)                    # 再次 build，不应再折叠相同消息
    assert len(calls) == 1


# ----------------------------------------------------------------------
# token 估算


def test_estimate_tokens_sanity():
    assert estimate_tokens("你好世界") >= 4          # CJK 接近 1 token/字
    assert estimate_tokens("hello world") <= 5       # 英文 4 字符/token
    assert estimate_tokens("") == 0
