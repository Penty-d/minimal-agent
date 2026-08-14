"""工具抽象基类。

每个工具对外暴露一份契约（ToolSpec）：名称、描述、参数 JSON Schema。
LLM 完全依据这份契约决定"何时调用、传什么参数"。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


class ToolError(Exception):
    """工具执行出错。由注册表统一捕获并回喂给 LLM。"""


@dataclass
class ToolSpec:
    """工具对外契约，也是 LLM 看到的全部信息。"""

    name: str
    description: str                       # 何时用、干什么，直接影响模型决策
    parameters: dict = field(default_factory=dict)   # 参数 JSON Schema


class Tool(ABC):
    """所有工具的基类。子类实现 execute，并在 spec 声明契约。"""

    spec: ToolSpec

    @abstractmethod
    def execute(self, **kwargs) -> str:
        """执行工具，返回文本结果（会回喂给 LLM）。"""

    @property
    def name(self) -> str:
        return self.spec.name
