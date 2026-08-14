"""消息模型。

Session 历史中存的是本模块的 Message（带 thought、ts 等内部字段）；
真正发给 LLM 前通过 to_api() 转成 OpenAI 兼容格式。

关于 reasoning_content 的取舍（DeepSeek V4）：
- 带 tool_calls 的 assistant 消息，重放进后续请求时必须带上 reasoning_content，
  否则部分模型版本会报 400（"assistant message with tool_calls must also have
  reasoning_content"）。
- 纯回答（无 tool_calls）的 assistant 消息不回传 reasoning_content：
  避免陈旧思考污染后续对话，也省 token。
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field

# tool_calls 内部格式：[{"id": "...", "name": "...", "arguments": {...}}]


@dataclass
class Message:
    role: str                                  # system / user / assistant / tool
    content: str = ""
    tool_calls: list | None = None             # assistant 专用
    tool_call_id: str | None = None            # tool 专用
    name: str | None = None                    # tool 专用
    thought: str | None = None                 # assistant 思考（reasoning_content）
    ts: float = field(default_factory=time.time)

    # ------------------------------------------------------------------
    def to_api(self) -> dict:
        """转成 OpenAI 兼容的 message。"""
        if self.role == "assistant":
            d: dict = {"role": "assistant", "content": self.content or None}
            if self.tool_calls:
                d["tool_calls"] = [
                    {
                        "id": tc["id"],
                        "type": "function",
                        "function": {
                            "name": tc["name"],
                            "arguments": json.dumps(tc.get("arguments", {}), ensure_ascii=False),
                        },
                    }
                    for tc in self.tool_calls
                ]
                if self.thought:               # 仅 tool_calls 消息回传思考（见模块注释）
                    d["reasoning_content"] = self.thought
            return d
        if self.role == "tool":
            return {"role": "tool", "tool_call_id": self.tool_call_id, "content": self.content}
        return {"role": self.role, "content": self.content}

    # ------------------------------------------------------------------
    def to_dict(self) -> dict:
        return {
            "role": self.role,
            "content": self.content,
            "tool_calls": self.tool_calls,
            "tool_call_id": self.tool_call_id,
            "name": self.name,
            "thought": self.thought,
            "ts": self.ts,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Message":
        return cls(
            role=d.get("role", "user"),
            content=d.get("content", ""),
            tool_calls=d.get("tool_calls"),
            tool_call_id=d.get("tool_call_id"),
            name=d.get("name"),
            thought=d.get("thought"),
            ts=d.get("ts", time.time()),
        )

    def __repr__(self) -> str:
        body = self.content[:40] if self.content else (f"tool_calls={len(self.tool_calls)}" if self.tool_calls else "")
        return f"<{self.role}: {body}>"


def to_api_messages(messages: list[Message]) -> list[dict]:
    """整段历史转 API 格式。"""
    return [m.to_api() for m in messages]
