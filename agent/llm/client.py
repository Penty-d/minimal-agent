"""OpenAI 兼容的 LLM 客户端。

只负责一件事：把 messages（含工具 schema）发给 /chat/completions，
拿回模型原始输出（content / reasoning_content / tool_calls）。
网络、重试、响应解析都收敛在这一层，上层不关心细节。

兼容 DeepSeek / 智谱 GLM / 通义 Qwen / 豆包 / OpenAI 等一切
OpenAI 兼容端点，切换服务商只需改 base_url 与 model。
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field

import httpx

from agent.config import Settings


class LLMError(Exception):
    """LLM 调用失败：网络、鉴权、限流、响应格式异常等。"""


@dataclass
class RawLLMResponse:
    """模型原始输出，由解析层进一步加工成结构化指令。

    - content: 正文（可能是最终答案，也可能是工具调用前的说明）
    - reasoning: 思考过程（DeepSeek-reasoner 的 reasoning_content）
    - tool_calls: OpenAI 结构化 tool_calls 列表（原始 dict）
    - finish_reason: stop / tool_calls / length 等
    """

    content: str | None = None
    reasoning: str | None = None
    tool_calls: list[dict] | None = None
    finish_reason: str | None = None
    raw: dict = field(default_factory=dict)


class LLMClient:
    """非流式的 OpenAI 兼容客户端，带指数退避重试。"""

    def __init__(self, settings: Settings):
        if not settings.api_key:
            raise LLMError("未配置 LLM_API_KEY：请复制 .env.example 为 .env 并填写，或使用 MockLLM。")
        self._settings = settings
        self._url = f"{settings.base_url}/chat/completions"
        self._headers = {
            "Authorization": f"Bearer {settings.api_key}",
            "Content-Type": "application/json",
        }
        self._http = httpx.Client(timeout=settings.request_timeout)

    # ------------------------------------------------------------------
    def chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        temperature: float | None = None,
        max_tokens: int = 4096,
    ) -> RawLLMResponse:
        """发送一次对话请求。"""
        payload: dict = {
            "model": self._settings.model,
            "messages": messages,
            "temperature": self._settings.temperature if temperature is None else temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }
        if tools:
            payload["tools"] = tools

        last_error: LLMError | None = None
        for attempt in range(self._settings.max_retries):
            try:
                resp = self._http.post(self._url, headers=self._headers, json=payload)
                if resp.status_code == 200:
                    return self._parse_message(resp.json())

                # 限流与服务器错误属于瞬时故障，指数退避重试
                if resp.status_code == 429 or resp.status_code >= 500:
                    last_error = LLMError(f"HTTP {resp.status_code}: {resp.text[:200]}")
                    time.sleep(2 ** attempt)
                    continue

                # 鉴权 / 参数等错误，重试无意义，直接抛出
                raise LLMError(f"HTTP {resp.status_code}: {resp.text[:200]}")

            except (httpx.TimeoutException, httpx.TransportError) as e:
                last_error = LLMError(f"网络错误: {e}")
                time.sleep(2 ** attempt)

        raise last_error or LLMError("LLM 请求失败")

    # ------------------------------------------------------------------
    @staticmethod
    def _parse_message(data: dict) -> RawLLMResponse:
        """从响应 JSON 中抽取 content / reasoning_content / tool_calls。"""
        try:
            message = data["choices"][0]["message"]
            choice = data["choices"][0]
        except (KeyError, IndexError) as e:
            raise LLMError(f"响应格式异常: {json.dumps(data, ensure_ascii=False)[:300]}") from e

        return RawLLMResponse(
            content=message.get("content"),
            reasoning=message.get("reasoning_content"),
            tool_calls=message.get("tool_calls"),
            finish_reason=choice.get("finish_reason"),
            raw=data,
        )
