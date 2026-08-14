"""跨会话长期记忆测试：存取、去重、召回、持久化、工具、context 注入。"""

from agent.core.memory import MemoryStore
from agent.core.session import SessionManager
from agent.tools.memory import MemoryTool


def _tmp_store(tmp_path):
    return MemoryStore(str(tmp_path / "memory.json"))


# ----------------------------------------------------------------------
# MemoryStore


def test_save_and_list(tmp_path):
    store = _tmp_store(tmp_path)
    store.save("用户喜欢简洁回答", "偏好")
    store.save("用户从事金融行业", "事实")
    assert len(store.list()) == 2


def test_save_dedup_merges_duplicates(tmp_path):
    """高度相似的记忆合并刷新，不堆重复。"""
    store = _tmp_store(tmp_path)
    store.save("用户喜欢简洁回答")
    store.save("用户喜欢简洁回答")        # 完全相同 → 合并
    assert len(store.list()) == 1
    store.save("用户从事金融行业")        # 不同事实 → 新增
    assert len(store.list()) == 2


def test_recall_matches_relevant(tmp_path):
    store = _tmp_store(tmp_path)
    store.save("用户喜欢简洁回答", "偏好")
    store.save("用户从事金融行业", "事实")
    hits = store.recall("金融")
    assert len(hits) == 1 and "金融" in hits[0]["content"]
    assert "简洁" in store.recall("简洁")[0]["content"]


def test_recall_no_match_returns_empty(tmp_path):
    store = _tmp_store(tmp_path)
    store.save("用户喜欢简洁回答")
    assert store.recall("完全不相关的话题xyz") == []


def test_persistence_roundtrip(tmp_path):
    path = str(tmp_path / "memory.json")
    store = MemoryStore(path)
    store.save("用户是前端工程师")
    store2 = MemoryStore(path)             # 重新加载
    assert len(store2.list()) == 1
    assert "前端" in store2.recall("前端")[0]["content"]


# ----------------------------------------------------------------------
# MemoryTool


def test_tool_save_recall_list(tmp_path):
    tool = MemoryTool(_tmp_store(tmp_path))
    out = tool.execute("save", content="用户偏好用中文回答", type="偏好")
    assert "已保存" in out and "(偏好)" in out
    hits = tool.execute("recall", query="中文")
    assert "中文" in hits
    assert "（长期记忆为空）" not in tool.execute("list")


def test_tool_unknown_operation(tmp_path):
    from agent.tools.base import ToolError
    tool = MemoryTool(_tmp_store(tmp_path))
    try:
        tool.execute("nope")
        assert False, "应抛 ToolError"
    except ToolError:
        pass


# ----------------------------------------------------------------------
# 会话接线：memory_store 注入 context + 工具


def test_memory_block_injected_into_request(tmp_path):
    store = MemoryStore(str(tmp_path / "memory.json"))
    store.save("用户做过 Agent 项目", "事实")
    sm = SessionManager(
        store_dir=str(tmp_path / "sessions"), system_prompt="sys", memory_store=store,
    )
    s = sm.create("w")
    messages, _ = s.context.build_request([])
    system_contents = [m["content"] for m in messages if m["role"] == "system"]
    assert any("跨会话记忆" in c and "Agent" in c for c in system_contents)


def test_session_registry_includes_memory_tool(tmp_path):
    store = MemoryStore(str(tmp_path / "memory.json"))
    sm = SessionManager(
        store_dir=str(tmp_path / "sessions"), system_prompt="sys", memory_store=store,
    )
    s = sm.create("w")
    assert "memory" in s.registry.names()
    assert "todo" in s.registry.names()
