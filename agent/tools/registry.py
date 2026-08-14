"""工具注册机制。

职责：
- register(): 收编工具
- schemas(): 导出 OpenAI 兼容的 tools 数组（LLM 据此自主决策）
- execute(): 按名字 + 参数执行；参数校验与异常捕获统一在这里处理

关键设计：工具执行失败绝不中断 Agent，而是转成 ToolResult 的错误文本
回喂给模型，让它基于错误信息修正参数重试。
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from agent.tools.base import Tool, ToolError


@dataclass
class ToolResult:
    """一次工具执行的结果。error 非空表示执行失败。"""

    name: str
    output: str = ""
    error: str | None = None
    duration_ms: float = 0.0

    def to_api_content(self) -> str:
        """转成回喂给 LLM 的文本。"""
        if self.error:
            return f"工具执行失败：{self.error}"
        return self.output


class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if tool.spec.name in self._tools:
            raise ValueError(f"工具已注册: {tool.spec.name}")
        self._tools[tool.spec.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def names(self) -> list[str]:
        return sorted(self._tools)

    def schemas(self) -> list[dict]:
        """转成 OpenAI 兼容格式的 tools 参数。"""
        return [
            {
                "type": "function",
                "function": {
                    "name": t.spec.name,
                    "description": t.spec.description,
                    "parameters": t.spec.parameters,
                },
            }
            for t in self._tools.values()
        ]

    def execute(self, name: str, arguments: dict) -> ToolResult:
        tool = self._tools.get(name)
        if tool is None:
            return ToolResult(name=name, error=f"未知工具 {name!r}，可用工具：{', '.join(self.names())}")

        start = time.perf_counter()
        try:
            args = self._validate(tool, arguments)
            output = tool.execute(**args)
            return ToolResult(name=name, output=str(output), duration_ms=(time.perf_counter() - start) * 1000)
        except ToolError as e:
            return ToolResult(name=name, error=str(e), duration_ms=(time.perf_counter() - start) * 1000)
        except TypeError as e:
            return ToolResult(name=name, error=f"参数不匹配：{e}", duration_ms=(time.perf_counter() - start) * 1000)
        except Exception as e:   # 兜底：任何异常都转成 tool 错误，不崩 Agent
            return ToolResult(name=name, error=f"内部错误：{type(e).__name__}: {e}", duration_ms=(time.perf_counter() - start) * 1000)

    # ------------------------------------------------------------------
    @staticmethod
    def _validate(tool: Tool, arguments: dict) -> dict:
        """按 JSON Schema 的 required 做基础校验，多余参数过滤掉。"""
        schema = tool.spec.parameters or {}
        required = schema.get("required", [])
        missing = [k for k in required if k not in arguments]
        if missing:
            raise ToolError(f"缺少必要参数 {missing}（schema: {required}）")
        props = set((schema.get("properties") or {}).keys())
        return {k: v for k, v in arguments.items() if not props or k in props or k in required}


def build_session_registry(todo_store, memory_store=None) -> ToolRegistry:
    """为单个会话构建工具注册表。

    - todo 是会话级工具：绑定该会话的 TodoStore，实现"各窗口待办互不影响"。
    - memory 是全局工具：绑定跨会话的 MemoryStore，所有会话共享同一份长期记忆。
    """
    from agent.tools.calculator import CalculatorTool
    from agent.tools.memory import MemoryTool
    from agent.tools.search import SearchTool
    from agent.tools.todo import TodoTool
    from agent.tools.weather import WeatherTool

    registry = ToolRegistry()
    registry.register(CalculatorTool())
    registry.register(SearchTool())
    registry.register(WeatherTool())
    registry.register(TodoTool(todo_store))
    if memory_store is not None:
        registry.register(MemoryTool(memory_store))
    return registry
