"""MockLLM：不联网的 LLM 替身，接口与 LLMClient 保持一致。

用途：
1. 离线开发/演示：按关键字返回"该调哪个工具"，让整套 Agent 循环
   在没有 API Key 的情况下也能跑通。
2. 测试：支持脚本模式，预设一串 RawLLMResponse 依次返回，精确控制
   模型行为（先调工具再回答 / 连续调工具 / 超轮次等），保证测试
   确定性、无网络依赖。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from agent.llm.client import RawLLMResponse


@dataclass
class MockRule:
    """一条规则：匹配最后一条用户消息，返回对应响应。"""

    pattern: re.Pattern
    respond: callable  # (text) -> RawLLMResponse


def _tool_call(name: str, arguments: dict, idx: int) -> dict:
    return {
        "id": f"call_mock_{idx}",
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(arguments, ensure_ascii=False)},
    }


CITIES = ["北京", "上海", "广州", "深圳", "杭州", "成都", "武汉", "南京", "西安", "重庆"]


def _extract_city(text: str) -> str:
    for c in CITIES:
        if c in text:
            return c
    return "北京"


# 默认规则：按常见指令关键字触发工具调用，其余直接回答。
def _default_rules() -> list[MockRule]:
    def weather(text: str) -> RawLLMResponse:
        return RawLLMResponse(tool_calls=[_tool_call("weather", {"city": _extract_city(text)}, 0)])

    def calculator(_: str) -> RawLLMResponse:
        return RawLLMResponse(tool_calls=[_tool_call("calculator", {"expression": "1+2"}, 1)])

    def search(_: str) -> RawLLMResponse:
        return RawLLMResponse(tool_calls=[_tool_call("search", {"query": "default"}, 2)])

    def todo(text: str) -> RawLLMResponse:
        item = text.split("：")[-1].split(":")[-1].strip() or text
        return RawLLMResponse(tool_calls=[_tool_call("todo", {"operation": "add", "item": item}, 3)])

    def memory_save(text: str) -> RawLLMResponse:
        content = re.sub(r"^(记住|请记住|记好)\s*[:：]?\s*", "", text).strip() or text
        type_ = "偏好" if re.search(r"(偏好|习惯)", text) else "事实"
        return RawLLMResponse(
            tool_calls=[_tool_call("memory", {"operation": "save", "content": content, "type": type_}, 5)]
        )

    return [
        # 提到天气，或提到某个已知城市（追问"那上海呢"时，模型会结合上下文理解为查上海天气）
        MockRule(re.compile(r"天气|" + "|".join(CITIES)), weather),
        MockRule(re.compile(r"记住|偏好|习惯|长期记忆"), memory_save),
        MockRule(re.compile(r"计算|多少|等于|求和|\d+\s*[-+*/]\s*\d+"), calculator),
        MockRule(re.compile(r"搜索|查一查|查一下", re.I), search),
        MockRule(re.compile(r"记(下|录)?|待办|todo|周报|备忘"), todo),
    ]


class MockLLM:
    def __init__(self, script: list[RawLLMResponse] | None = None):
        """script 提供时按脚本依次返回；否则走默认规则。"""
        self._script = list(script) if script else []
        self._rules = _default_rules()
        self.calls: list[dict] = []          # 记录每次入参，供测试断言

    # ------------------------------------------------------------------
    def chat(self, messages, tools=None, temperature=None, max_tokens=4096) -> RawLLMResponse:
        self.calls.append({"messages": messages, "tools": tools})
        if self._script:
            return self._script.pop(0)
        return self._match(messages)

    # ------------------------------------------------------------------
    def _match(self, messages: list[dict]) -> RawLLMResponse:
        # 内部任务（如对话摘要压缩）不套工具决策规则
        for m in messages:
            if "[internal" in (m.get("content") or ""):
                return RawLLMResponse(content="（摘要）用户此前的对话已归纳为摘要。")

        # 找到最后一条 user 消息的位置
        last_user_idx = max(
            (i for i, m in enumerate(messages) if m.get("role") == "user"),
            default=None,
        )

        # 工具结果出现在最后一条 user 之后 → 模型已拿到信息，直接作答
        if last_user_idx is not None:
            results = [m["content"] for m in messages[last_user_idx + 1:] if m.get("role") == "tool"]
            if results:
                return RawLLMResponse(content=f"（mock 已基于工具结果回答）\n{results[-1]}")

        last_user = messages[last_user_idx]["content"] if last_user_idx is not None else ""

        # 主召回途径：会话开始注入的记忆块 → 用户问记忆相关时直接引用
        if re.search(r"记得|回忆", last_user):
            block = next(
                (m["content"] for m in messages
                 if m.get("role") == "system" and "[跨会话记忆]" in (m.get("content") or "")),
                None,
            )
            if block:
                return RawLLMResponse(content=f"（mock 引用会话开始时注入的记忆）\n{block}")
            return RawLLMResponse(content="（mock）暂时没有相关长期记忆。")

        for rule in self._rules:
            if rule.pattern.search(last_user):
                return rule.respond(last_user)
        return RawLLMResponse(content=f"(mock) 收到：{last_user}")
