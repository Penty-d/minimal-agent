"""跨会话长期记忆（MemoryStore）。

对标 Claude Code 的自动记忆，保持最简：
- 一条记忆 = 一句事实（由模型蒸馏，不存对话原文）
- 召回 = 会话开始把记忆句子全量注入 context（不做按需检索）

落盘 data/memory.json，所有会话共享，重启后仍在。
"""

from __future__ import annotations

import json
import os
import time
import uuid

_TYPES = ["偏好", "事实", "事件", "其他"]
MAX_MEMORY_LEN = 100        # 单条记忆硬性长度上限（一句话）


class MemoryStore:
    def __init__(self, path: str = "data/memory.json", max_len: int = MAX_MEMORY_LEN):
        self._path = path
        self._max_len = max_len
        self._entries: list[dict] = []
        self._load()

    # ------------------------------------------------------------------
    def save(self, content: str, type_: str = "事实") -> dict:
        """保存一句记忆。超长直接拒绝；与已有记忆高度相似（一方包含另一方）时合并刷新。"""
        content = content.strip()
        if len(content) > self._max_len:
            raise ValueError(
                f"记忆内容过长（{len(content)} 字，上限 {self._max_len} 字），"
                f"请压缩成一句话再保存"
            )
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
