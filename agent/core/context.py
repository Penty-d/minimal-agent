"""Context 管理：在 token 预算内把 Session 历史组织成一次 LLM 请求。

组成（从前往后）：
    system 提示
    历史摘要（长期锚点，压缩后放在最前）
    近期对话（episodic，按时间顺序）
    新用户输入

三个关键机制：
1. token 预算：超过预算的旧历史被截断
2. 干净截断：保留的后缀不能以 tool 消息开头（协议要求 tool 消息
   紧跟产生它的 assistant 消息），否则 API 报错
3. 基础压缩：被截断的历史折叠进滚动摘要；只有确实发生截断时才调用
   LLM 摘要，避免每轮无谓烧 token
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from agent.core.message import Message

_MARGIN = 120   # 预留余量，避免刚好卡在预算线上


def estimate_tokens(text: str) -> int:
    """粗略 token 估算：CJK 字符≈1 token，其他字符≈4 字符/token。

    不引入分词库，够"基础压缩"使用；需要精确计数时可换成 tiktoken。
    """
    if not text:
        return 0
    cjk = sum(1 for ch in text if "一" <= ch <= "鿿" or "぀" <= ch <= "ヿ" or "가" <= ch <= "힯")
    other = len(text) - cjk
    return int(cjk + other / 4) + 1


@dataclass
class BuildInfo:
    """一次 build 的说明，供 trace / 调试。"""

    kept: int = 0
    dropped: int = 0
    summarized: bool = False
    summary: str = ""


class ContextManager:
    def __init__(self, system_prompt: str, max_context_tokens: int = 6000, summarizer=None, memory_block=None):
        self.system_prompt = system_prompt
        self.max_context_tokens = max_context_tokens
        self.summarizer = summarizer        # callable(old_summary, dropped_text) -> new_summary
        self.memory_block = memory_block    # callable() -> 跨会话记忆索引文本 | None
        self.summary = ""                   # 滚动摘要（会话内长期记忆）
        self._folded = 0                    # 已折叠进摘要的前缀消息数

    # ------------------------------------------------------------------
    def build_request(self, history: list[Message]) -> tuple[list[dict], BuildInfo]:
        """组装一次请求的完整 message 列表。

        用户输入由调用方先写入 history（保证持久化完整），这里只负责
        截断 + 加摘要 + 组装。
        """
        info = BuildInfo()

        memory_text = self.memory_block() if self.memory_block else None

        reserve = (
            estimate_tokens(self.system_prompt)
            + estimate_tokens(self.summary)
            + estimate_tokens(memory_text or "")
            + _MARGIN
        )
        budget = max(100, self.max_context_tokens - reserve)

        kept, dropped = self._truncate(history, budget)
        info.kept, info.dropped = len(kept), len(dropped)

        if dropped:                          # 确有截断 → 增量摘要
            new_summary = self._summarize(dropped)
            if new_summary and new_summary != self.summary:
                self.summary = new_summary
                info.summarized = True
                info.summary = self.summary

        messages: list[dict] = [{"role": "system", "content": self.system_prompt}]
        if memory_text:
            # 跨会话记忆索引：system 之后、会话摘要之前（全局锚点）
            messages.append({"role": "system", "content": f"[跨会话记忆]\n{memory_text}"})
        if self.summary:
            messages.append({"role": "system", "content": f"[历史对话摘要]\n{self.summary}"})
        messages.extend(m.to_api() for m in kept)
        return messages, info

    # ------------------------------------------------------------------
    def _truncate(self, history: list[Message], budget: int) -> tuple[list[Message], list[Message]]:
        """尽量保留最新消息，返回 (保留, 丢弃)。"""
        if not history:
            return [], []

        total = 0
        cut = len(history)
        for i in range(len(history) - 1, -1, -1):   # 从新到旧累计
            t = self._message_tokens(history[i])
            if total + t > budget:
                cut = i + 1
                break
            total += t
            cut = i

        # 硬底线：至少保留最后一条消息（通常是最新回合）
        if cut >= len(history):
            cut = len(history) - 1

        # 干净边界：后缀不能以 tool 消息开头
        while cut < len(history) and history[cut].role == "tool":
            cut += 1

        return history[cut:], history[:cut]

    # ------------------------------------------------------------------
    def _summarize(self, dropped: list[Message]) -> str:
        """增量摘要：只折叠尚未折叠过的部分。"""
        start = min(self._folded, len(dropped))
        fresh = dropped[start:]
        if not fresh:
            return self.summary
        self._folded += len(fresh)

        # 提取式兜底：没有 summarizer 或 LLM 失败时，保留最近一条用户意图
        fallback = [f"[早期对话摘要] 共压缩 {len(fresh)} 条消息。"]
        for m in reversed(fresh):
            if m.role == "user" and m.content.strip():
                fallback.append(f"用户曾问：{m.content.strip()}")
                break

        if not self.summarizer:
            return self.summary or "\n".join(fallback)

        dropped_text = "\n".join(
            f"[{m.role}] " + (m.content or json.dumps(m.tool_calls or {}, ensure_ascii=False))
            for m in fresh
        )
        try:
            result = self.summarizer(self.summary, dropped_text)
            if result and result.strip():
                return result.strip()
        except Exception:
            pass
        return self.summary or "\n".join(fallback)

    # ------------------------------------------------------------------
    @staticmethod
    def _message_tokens(m: Message) -> int:
        n = estimate_tokens(m.content or "")
        if m.tool_calls:
            n += estimate_tokens(json.dumps(m.tool_calls, ensure_ascii=False))
        return n

    # ------------------------------------------------------------------
    def to_dict(self) -> dict:
        return {"summary": self.summary, "folded": self._folded}

    @classmethod
    def from_dict(cls, d: dict, system_prompt: str, max_context_tokens: int, summarizer=None, memory_block=None) -> "ContextManager":
        cm = cls(system_prompt=system_prompt, max_context_tokens=max_context_tokens, summarizer=summarizer, memory_block=memory_block)
        cm.summary = d.get("summary", "")
        cm._folded = d.get("folded", 0)
        return cm
