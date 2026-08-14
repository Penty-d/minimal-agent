"""LLM 输出解析器：把模型原始输出加工成结构化指令。

判断模型到底想干什么：
1. 输出工具调用 → 哪个工具、什么参数（可能一次调多个）
2. 输出最终答案 → 直接回复用户
3. 思考过程 → 单独抽取，供日志展示与后续消息回传

支持两条路径：
- 结构化路径：OpenAI 兼容 function calling 返回的 tool_calls 数组
- 文本路径：模型无 function calling 时，按约定输出
      <thinking>...</thinking>
      <tool_call>{"name":"calculator","arguments":{...}}</tool_call>
  由本模块从纯文本抽取（同时兼容模型把调用写在正文里的情况）

注意：arguments 是 JSON 字符串，且模型不一定生成合法 JSON，
解析必须容错，失败时保留原文，不能抛异常中断循环。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from agent.llm.client import RawLLMResponse

# ----------------------------------------------------------------------
# 结构化输出


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict


@dataclass
class LLMStep:
    thought: str | None = None              # 思考过程
    tool_calls: list[ToolCall] | None = None   # 需要执行的工具调用
    final_answer: str | None = None         # 最终答案（无工具调用时才有）
    raw_content: str = ""                   # 原始正文，便于调试/trace

    @property
    def has_tool_calls(self) -> bool:
        return bool(self.tool_calls)


# ----------------------------------------------------------------------
# 文本解析规则

_THINKING_RE = re.compile(r"<thinking>\s*(.*?)\s*</thinking>", re.DOTALL)
_TOOL_CALL_RE = re.compile(
    r"<(?:tool_call|invoke|toolcall)[^>]*>\s*(.*?)\s*</(?:tool_call|invoke|toolcall)>",
    re.DOTALL,
)
_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)
_XML_NAME_RE = re.compile(r"<name>\s*(.*?)\s*</name>", re.DOTALL)
_XML_ARGS_RE = re.compile(r"<arguments>\s*(.*?)\s*</arguments>", re.DOTALL)
_ARG_FIELD_RE = re.compile(r'"arguments"\s*:\s*(\{.*?\})', re.DOTALL)


def _strip_fence(s: str) -> str:
    m = _JSON_FENCE_RE.search(s)
    return m.group(1) if m else s


def _safe_loads(s: str) -> dict | None:
    """把字符串解析成 dict；失败返回 None 而不是抛异常。"""
    if not s or not s.strip():
        return None
    try:
        value = json.loads(_strip_fence(s.strip()))
        return value if isinstance(value, dict) else None
    except json.JSONDecodeError:
        return None


def _salvage_arguments(s: str) -> dict:
    """arguments 非法 JSON 时的兜底：尝试抠出 arguments 字段。"""
    m = _ARG_FIELD_RE.search(s)
    if m:
        value = _safe_loads(m.group(1))
        if isinstance(value, dict):
            return value
    return {"_raw": s}


def _parse_arguments(arg) -> dict:
    """arguments 可能是 dict（部分模型）或 JSON 字符串（OpenAI 兼容格式）。"""
    if isinstance(arg, dict):
        return arg
    if isinstance(arg, str):
        value = _safe_loads(arg)
        if value is not None:
            return value
        return _salvage_arguments(arg)
    return {}


def _parse_text_tool_call(inner: str, idx: int) -> ToolCall | None:
    """从一段 tool_call 内部文本解析出 name + arguments。"""
    inner = inner.strip()

    # 方式1：整体是 JSON：{"name": "...", "arguments": {...}}
    data = _safe_loads(inner)
    if data and "name" in data:
        return ToolCall(
            id=f"text_call_{idx}",
            name=str(data["name"]),
            arguments=_parse_arguments(data.get("arguments", {})),
        )

    # 方式2：XML 风格：<name>x</name> <arguments>{...}</arguments>
    name_m = _XML_NAME_RE.search(inner)
    args_m = _XML_ARGS_RE.search(inner)
    if name_m:
        return ToolCall(
            id=f"text_call_{idx}",
            name=name_m.group(1).strip(),
            arguments=_parse_arguments(args_m.group(1) if args_m else ""),
        )

    # 方式3：整段按 JSON 处理，至少拿到名字
    if data:
        return ToolCall(
            id=f"text_call_{idx}",
            name=str(data.get("name") or data.get("tool") or "unknown"),
            arguments=_parse_arguments(data),
        )
    return None


def _clean(text: str | None) -> str:
    """清理正文：去掉 thinking 标签、压缩空白。"""
    if not text:
        return ""
    text = _THINKING_RE.sub("", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# ----------------------------------------------------------------------
# 主入口


def parse_response(raw: RawLLMResponse) -> LLMStep:
    """把 RawLLMResponse 解析成 LLMStep。"""
    content = raw.content or ""
    thought = raw.reasoning or extract_thinking(content)

    # ---- 路径一：结构化 tool_calls ----
    if raw.tool_calls:
        tool_calls: list[ToolCall] = []
        for i, tc in enumerate(raw.tool_calls):
            fn = tc.get("function", {})
            tool_calls.append(
                ToolCall(
                    id=tc.get("id") or f"api_call_{i}",
                    name=fn.get("name", "unknown"),
                    arguments=_parse_arguments(fn.get("arguments", {})),
                )
            )
        return LLMStep(
            thought=thought,
            tool_calls=tool_calls,
            final_answer=_clean(content) or None,   # 调工具时模型可能附带说明
            raw_content=content,
        )

    # ---- 路径二：文本 tool_call ----
    text_calls = _TOOL_CALL_RE.findall(content)
    if text_calls:
        tool_calls = [tc for i, inner in enumerate(text_calls) if (tc := _parse_text_tool_call(inner, i))]
        tail = _TOOL_CALL_RE.sub("", content)       # 调用之后的正文视为候选答案
        return LLMStep(
            thought=thought,
            tool_calls=tool_calls or None,
            final_answer=_clean(tail) or None,
            raw_content=content,
        )

    # ---- 纯文本：直接是最终答案 ----
    return LLMStep(thought=thought, final_answer=_clean(content) or None, raw_content=content)


def extract_thinking(content: str) -> str | None:
    """从正文提取 <thinking> 块（文本路径下模型自带的思考）。"""
    m = _THINKING_RE.search(content or "")
    return m.group(1).strip() if m else None
