"""minimal-agent：一个最小可用的 Agent Runtime。

设计目标：
- 主流程（循环、解析、上下文、会话、工具调度）全部自实现，不依赖任何 Agent 框架。
- LLM 调用走 OpenAI 兼容协议（默认 DeepSeek），客户端直接用 HTTP 实现。
"""

__version__ = "0.1.0"
