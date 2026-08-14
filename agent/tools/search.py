"""search 工具：搜索（演示环境为 mock 数据）。

返回一组预设搜索结果。接入真实搜索 API（Bing / SerpAPI / 自建服务）时，
只需替换 execute 的实现，契约与 LLM 侧完全不变。
"""

from __future__ import annotations

import json

from agent.tools.base import Tool, ToolError, ToolSpec

_MOCK_RESULTS = {
    "天气": [
        {"title": "中国天气网 - 全国天气预报", "url": "https://www.weather.com.cn/", "snippet": "提供全国城市天气实况与预报，支持按城市查询。"},
        {"title": "墨迹天气 - 15天天气预报", "url": "https://www.moji.com/", "snippet": "实时空气质量、逐小时预报、生活指数。"},
    ],
    "agent": [
        {"title": "Anthropic - Building effective agents", "url": "https://www.anthropic.com/research/building-effective-agents", "snippet": "关于 Agent 架构、工具使用与循环设计的工程实践。"},
        {"title": "Letta (MemGPT) - 带内存的 Agent 框架", "url": "https://github.com/letta-ai/letta", "snippet": "通过虚拟上下文管理将无限记忆交给 LLM 的经典框架。"},
    ],
    "claude code": [
        {"title": "Claude Code 官方文档", "url": "https://docs.anthropic.com/en/docs/claude-code", "snippet": "终端内的 Agentic 编程助手，支持原生工具调用与多轮执行。"},
    ],
}

_FALLBACK = [
    {"title": "Mock 搜索结果", "url": "https://example.com/mock", "snippet": "（演示用结果）未命中关键词，返回兜底结果。"},
]


class SearchTool(Tool):
    spec = ToolSpec(
        name="search",
        description=(
            "模拟搜索引擎。需要查询当前事实、网页资料时使用。"
            "输入一个查询词，返回若干条搜索结果（标题/链接/摘要）。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "要搜索的关键词或问题"},
            },
            "required": ["query"],
        },
    )

    def execute(self, query: str = "") -> str:
        if not query.strip():
            raise ToolError("query 不能为空")
        results = next(
            (rows for key, rows in _MOCK_RESULTS.items() if key.lower() in query.lower()),
            _FALLBACK,
        )
        return json.dumps(results, ensure_ascii=False)
