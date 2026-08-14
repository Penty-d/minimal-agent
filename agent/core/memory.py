"""跨会话长期记忆（MemoryStore）。

对标 Claude Code 的自动记忆，保持最简：
- 一条记忆 = 一句事实（由模型蒸馏，不存对话原文）
- 会话开始把记忆句子全量注入 context（主召回途径）
- 需要时按整句/短语精确过滤（不做分词/切片——中文切词难做对）

落盘 data/memory.json，所有会话共享，重启后仍在。
"""

from __future__ import annotations

import json
import os
import time
import uuid

_TYPES = ["偏好", "事实", "事件", "其他"]


class MemoryStore:
    def __init__(self, path: str = "data/memory.json"):
        self._path = path
        self._entries: list[dict] = []
        self._load()

    # ------------------------------------------------------------------
    def save(self, content: str, type_: str = "事实") -> dict:
        """保存一句记忆。与已有记忆高度相似（一方包含另一方）时合并刷新。"""
        content = content.strip()
        type_ = type_ if type_ in _TYPES else "事实"

        for e in self._entries:                    # 简单去重：包含关系视为重复 → 合并
            if content in e["content"] or e["content"] in content:
                e["content"] = content
                e["type"] = type_
                e["updated_at"] = time.time()
                self._persist()
                return e

        entry = {
            "id": "m" + uuid.uuid4().hex[:8],
            "type": type_,
            "content": content,
            "created_at": time.time(),
            "updated_at": time.time(),
        }
        self._entries.append(entry)
        self._persist()
        return entry

    def list(self) -> list[dict]:
        return list(self._entries)

    def recall(self, query: str, top_k: int = 5) -> list[dict]:
        """按整句/短语精确过滤（不做分词）。无命中返回空列表。

        主召回途径是会话开始的全量注入；这里是按需过滤，用于记忆较多时
        或模型想确认某条细节。
        """
        q = (query or "").strip().lower()
        if not q:
            return []
        hits = [e for e in self._entries if q in e["content"].lower()]
        return hits[:top_k]

    def render_block(self, max_entries: int = 15) -> str:
        """渲染记忆句子（新→旧），供会话开始时注入 context。"""
        if not self._entries:
            return ""
        lines = []
        for e in reversed(self._entries[-max_entries:]):
            lines.append(f"- [{e['id']}] ({e['type']}) {e['content']}")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    def to_dict(self) -> dict:
        return {"entries": self._entries}

    @classmethod
    def from_dict(cls, data: dict) -> "MemoryStore":
        store = cls(path=":memory:")
        store._entries = data.get("entries", [])
        return store

    def _load(self) -> None:
        if not os.path.exists(self._path):
            return
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                self._entries = json.load(f).get("entries", [])
        except Exception:
            self._entries = []

    def _persist(self) -> None:
        directory = os.path.dirname(self._path) or "."
        os.makedirs(directory, exist_ok=True)
        tmp = self._path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False)
        os.replace(tmp, self._path)
