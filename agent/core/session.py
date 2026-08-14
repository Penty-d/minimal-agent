"""Session 管理：多窗口隔离 + JSON 持久化。

一个 Session 拥有独立的：消息历史、Context（含滚动摘要）、待办清单、
工具注册表。窗口 1 记的待办窗口 2 看不到，各自的摘要也互不影响。

持久化：每个 Session 落一个 JSON 文件，启动时自动恢复——
"随时接着上一个窗口聊"跨进程成立。写入用临时文件 + 原子替换。
"""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from dataclasses import dataclass, field

from agent.core.context import ContextManager
from agent.core.message import Message
from agent.tools.registry import build_session_registry
from agent.tools.todo import TodoStore


def _new_sid(name: str | None) -> str:
    base = "".join(c if c.isalnum() else "_" for c in (name or "session"))[:24]
    return f"{base}_{int(time.time())}_{uuid.uuid4().hex[:6]}"


@dataclass
class Session:
    id: str
    name: str
    context: ContextManager
    history: list[Message] = field(default_factory=list)
    state: str = "idle"                     # idle / busy
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    memory_store: object = None             # 跨会话长期记忆（全局共享）

    def __post_init__(self):
        self.todos = TodoStore()
        self.registry = build_session_registry(self.todos, self.memory_store)

    def touch(self):
        self.updated_at = time.time()

    # ------------------------------------------------------------------
    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "state": self.state,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "context": self.context.to_dict(),
            "history": [m.to_dict() for m in self.history],
            "todos": self.todos.to_dict(),
        }

    @classmethod
    def from_dict(cls, d: dict, system_prompt: str, max_context_tokens: int, summarizer=None, memory_block=None, memory_store=None) -> "Session":
        session = cls(
            id=d["id"],
            name=d.get("name", d["id"]),
            context=ContextManager.from_dict(
                d.get("context", {}), system_prompt, max_context_tokens, summarizer, memory_block
            ),
            memory_store=memory_store,
        )
        session.history = [Message.from_dict(m) for m in d.get("history", [])]
        session.state = d.get("state", "idle")
        session.created_at = d.get("created_at", time.time())
        session.updated_at = d.get("updated_at", time.time())
        session.todos = TodoStore.from_dict(d.get("todos", {}))
        session.registry = build_session_registry(session.todos, memory_store)
        return session


class SessionManager:
    def __init__(
        self,
        store_dir: str = "data/sessions",
        system_prompt: str = "",
        max_context_tokens: int = 6000,
        summarizer=None,
        memory_store=None,
    ):
        self._sessions: dict[str, Session] = {}
        self._lock = threading.RLock()
        self.store_dir = store_dir
        self.system_prompt = system_prompt
        self.max_context_tokens = max_context_tokens
        self.summarizer = summarizer
        self.memory_store = memory_store      # 跨会话长期记忆（全局共享）
        self._load_all()

    def _memory_block(self):
        """跨会话记忆索引：会话组装请求时注入 context（实时读取全局 store）。"""
        if self.memory_store is None:
            return None
        block = self.memory_store.render_block()
        return block or None

    # ------------------------------------------------------------------
    def create(self, name: str | None = None) -> Session:
        with self._lock:
            session = Session(
                id=_new_sid(name),
                name=name or "会话",
                context=ContextManager(
                    self.system_prompt, self.max_context_tokens, self.summarizer,
                    memory_block=self._memory_block,
                ),
                memory_store=self.memory_store,
            )
            self._sessions[session.id] = session
            self._persist(session)
            return session

    def get(self, sid: str) -> Session | None:
        with self._lock:
            return self._sessions.get(sid)

    def list(self) -> list[Session]:
        with self._lock:
            return list(self._sessions.values())

    def delete(self, sid: str) -> bool:
        with self._lock:
            existed = self._sessions.pop(sid, None) is not None
        if existed:
            path = self._path(sid)
            if os.path.exists(path):
                os.remove(path)
        return existed

    def persist_all(self) -> None:
        with self._lock:
            for s in self._sessions.values():
                self._persist(s)

    # ------------------------------------------------------------------
    def _persist(self, session: Session) -> None:
        os.makedirs(self.store_dir, exist_ok=True)
        path = self._path(session.id)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(session.to_dict(), f, ensure_ascii=False)
        os.replace(tmp, path)               # 原子替换，避免写一半崩溃

    def _path(self, sid: str) -> str:
        return os.path.join(self.store_dir, f"{sid}.json")

    # ------------------------------------------------------------------
    def _load_all(self) -> None:
        if not os.path.isdir(self.store_dir):
            return
        for fn in os.listdir(self.store_dir):
            if not fn.endswith(".json"):
                continue
            path = os.path.join(self.store_dir, fn)
            try:
                with open(path, "r", encoding="utf-8") as f:
                    d = json.load(f)
                self._sessions[d["id"]] = Session.from_dict(
                    d, self.system_prompt, self.max_context_tokens,
                    self.summarizer, self._memory_block, self.memory_store,
                )
            except Exception as e:
                print(f"[session] 加载失败 {fn}: {e}")
