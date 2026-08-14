"""search 工具：基于必应 RSS 的真实搜索（免 Key）。

使用 Bing 的 `format=rss` 轻量接口返回真实网页结果（标题/链接/摘要）。
网络不可用或解析失败时，回退到内置演示数据，保证工具永不崩、演示可用。

后端可注入（backend 参数），测试时用假后端即可保持离线确定性。
"""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET

import httpx

from agent.tools.base import Tool, ToolError, ToolSpec

# cn.bing.com 对国内网络更友好；www 作兜底
_BING_ENDPOINTS = ["https://cn.bing.com/search", "https://www.bing.com/search"]
_BING_TIMEOUT = 5.0
_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; minimal-agent/0.1)"}

# 本地演示数据（回退用）
_LOCAL_RESULTS = {
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
    {"title": "（离线演示结果）", "url": "", "snippet": "当前无法访问搜索引擎，返回内置演示数据。"},
]


def _strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text or "").strip()


def _parse_rss(xml_text: str) -> list[dict]:
    """解析必应 RSS，抽取 title / link / description。"""
    root = ET.fromstring(xml_text)
    results = []
    for item in root.findall(".//item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        desc = _strip_html(item.findtext("description"))
        if title and link:
            results.append({"title": title, "url": link, "snippet": desc})
    return results


def bing_search(query: str, limit: int = 5) -> list[dict]:
    """必应 RSS 搜索；任一端点成功即返回，全部失败返回空列表（由调用方回退）。"""
    params = {"q": query, "format": "rss"}
    with httpx.Client(timeout=_BING_TIMEOUT, follow_redirects=True) as client:
        for base in _BING_ENDPOINTS:
            try:
                resp = client.get(base, params=params, headers=_HEADERS)
                resp.raise_for_status()
                results = _parse_rss(resp.text)
                if results:
                    return results[:limit]
            except Exception:
                continue
    return []


def _local_results(query: str) -> list[dict]:
    """本地演示数据：按关键词命中返回，未命中给兜底。"""
    for key, rows in _LOCAL_RESULTS.items():
        if key.lower() in query.lower():
            return rows
    return _FALLBACK


class SearchTool(Tool):
    spec = ToolSpec(
        name="search",
        description=(
            "使用必应搜索返回真实的网页搜索结果（标题/链接/摘要）。"
            "需要查询当前事实、网页资料、最新信息时使用。"
            "网络不可用时自动回退内置演示数据。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "要搜索的关键词或问题"},
            },
            "required": ["query"],
        },
    )

    def __init__(self, backend=None):
        self._backend = backend or bing_search

    def execute(self, query: str = "") -> str:
        if not query.strip():
            raise ToolError("query 不能为空")
        try:
            results = self._backend(query.strip())
            if results:
                return json.dumps(results, ensure_ascii=False)
        except Exception:
            pass
        return json.dumps(_local_results(query), ensure_ascii=False)
