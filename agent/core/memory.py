"""跨会话长期记忆（MemoryStore）。

对标 Claude Code 的自动记忆：**写入由模型蒸馏事实、会话开始注入索引、
细节按需召回**。不依赖向量库与融合评分，是基础但完整的方案。

一条记忆 = { id, type, content, created_at, updated_at }。
落盘 data/memory.json，所有会话共享，重启后仍在。

升级方向（未实现，见 README）：embedding 语义检索 + 重要度/新鲜度融合评分。
"""

from __future__ import annotations

import json
import os
import re
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
        """保存一条记忆。与已有记忆高度相似时合并刷新，避免重复堆积。"""
        content = content.strip()
        type_ = type_ if type_ in _TYPES else "事实"

        for e in self._entries:                    # 简单去重：相似 → 合并刷新
            if self._overlap(content, e["content"]) >= 0.5:
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
        """按词粒度召回相关记忆。英文按单词、中文按 2 字粒度切分，
        命中词越多越靠前；无命中返回空列表。
        """
        terms = self._terms(query or "")
        if not terms:
            return []
        scored = []
        for e in self._entries:
            text = e["content"].lower()
            score = sum(len(t) for t in terms if t in text)
            if score > 0:
                scored.append((score, e))
        scored.sort(key=lambda x: (-x[0], -x[1].get("updated_at", 0)))
        return [e for _, e in scored[:top_k]]

    def render_block(self, max_entries: int = 15) -> str:
        """渲染记忆索引（新→旧），供会话开始时注入 context。"""
        if not self._entries:
            return ""
        lines = []
        for e in reversed(self._entries[-max_entries:]):
            text = " ".join(e["content"].split())
            if len(text) > 60:
                text = text[:60] + "…"
            lines.append(f"- [{e['id']}] ({e['type']}) {text}")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    @staticmethod
    def _terms(text: str) -> list[str]:
        """英文单词 + 中文 2 字粒度。"""
        text = (text or "").lower()
        words = re.findall(r"[a-z0-9]+", text)
        grams = []
        for run in re.findall(r"[一-鿿]+", text):
            if len(run) <= 2:
                grams.append(run)
            else:
                grams.extend(run[i:i + 2] for i in range(len(run) - 1))
        return words + grams

    @staticmethod
    def _overlap(a: str, b: str) -> float:
        ta, tb = set(MemoryStore._terms(a)), set(MemoryStore._terms(b))
        if not ta or not tb:
            return 0.0
        return len(ta & tb) / len(ta | tb)

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
