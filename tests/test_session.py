"""Session 管理测试：多窗口隔离 + 持久化恢复。"""

import os

from agent.core.message import Message
from agent.core.session import SessionManager


def test_two_sessions_are_isolated(tmp_path):
    sm = SessionManager(store_dir=str(tmp_path / "sessions"), system_prompt="sys")
    w1 = sm.create("窗口1")
    w2 = sm.create("窗口2")

    w1.registry.execute("todo", {"operation": "add", "item": "查北京天气"})
    w1.history.append(Message(role="user", content="帮我查天气"))

    assert "查北京天气" in w1.registry.execute("todo", {"operation": "list"}).output
    assert "（待办为空）" in w2.registry.execute("todo", {"operation": "list"}).output
    assert len(w2.history) == 0


def test_persistence_roundtrip(tmp_path):
    store_dir = str(tmp_path / "sessions")
    sm = SessionManager(store_dir=store_dir, system_prompt="sys")
    w = sm.create("w")
    w.registry.execute("todo", {"operation": "add", "item": "写周报"})
    w.history.append(Message(role="user", content="帮我写周报"))
    sm.persist_all()

    sm2 = SessionManager(store_dir=store_dir, system_prompt="sys")
    assert len(sm2.list()) == 1
    restored = sm2.get(w.id)
    assert restored is not None
    assert restored.history[0].content == "帮我写周报"
    assert "写周报" in restored.registry.execute("todo", {"operation": "list"}).output


def test_delete_removes_file(tmp_path):
    store_dir = str(tmp_path / "sessions")
    sm = SessionManager(store_dir=store_dir, system_prompt="sys")
    w = sm.create("w")
    sid = w.id
    assert sm.delete(sid) is True
    assert sm.get(sid) is None
    assert not os.path.exists(os.path.join(store_dir, f"{sid}.json"))


def test_load_all_skips_corrupted_files(tmp_path, capsys):
    store_dir = str(tmp_path / "sessions")
    os.makedirs(store_dir, exist_ok=True)
    with open(os.path.join(store_dir, "broken.json"), "w", encoding="utf-8") as f:
        f.write("{not valid json")
    sm = SessionManager(store_dir=store_dir, system_prompt="sys")
    assert len(sm.list()) == 0
    assert "加载失败" in capsys.readouterr().out
