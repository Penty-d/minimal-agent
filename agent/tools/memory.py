"""memory 工具：跨会话长期记忆的读写接口。

模型通过它保存蒸馏后的事实/偏好（save）、检索相关记忆（recall）、
查看全部（list）。所有会话共享同一个 MemoryStore，属于跨对话记忆。
"""

from __future__ import annotations

from agent.core.memory import MemoryStore
from agent.tools.base import Tool, ToolError, ToolSpec


class MemoryTool(Tool):
    spec = ToolSpec(
        name="memory",
        description=(
            "管理跨会话的长期记忆（所有会话共享，重启后仍在）。"
            "当用户给出值得长期记住的事实、偏好、约定时调用 save；"
            "需要回忆历史信息时调用 recall；查看全部用 list。"
            "新会话开始时会自动带上已有记忆的索引。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string",
                    "enum": ["save", "recall", "list"],
                    "description": "要执行的操作",
                },
                "content": {"type": "string", "description": "save 操作时，蒸馏成一句话的记忆内容"},
                "type": {
                    "type": "string",
                    "enum": ["偏好", "事实", "事件", "其他"],
                    "description": "save 操作的记忆类型（可选，默认 事实）",
                },
                "query": {"type": "string", "description": "recall 操作时检索的关键词"},
                "top_k": {"type": "integer", "description": "recall 返回条数（可选，默认 5）"},
            },
            "required": ["operation"],
        },
    )

    def __init__(self, store: MemoryStore):
        self._store = store

    def execute(self, operation: str = "", content: str = "", type: str = "", query: str = "", top_k: int = 5) -> str:
        op = (operation or "").strip()
        if op == "save":
            if not content.strip():
                raise ToolError("content 不能为空")
            e = self._store.save(content, type)
            return f"已保存记忆 [{e['id']}] ({e['type']})：{e['content']}"
        if op == "recall":
            hits = self._store.recall(query, int(top_k or 5))
            if not hits:
                return "（没有匹配的长期记忆）"
            return "\n".join(
                f"[{e['id']}] ({e['type']}) {e['content']}" for e in hits
            )
        if op == "list":
            block = self._store.render_block(max_entries=50)
            return block or "（长期记忆为空）"
        raise ToolError(f"未知操作：{op}（可用：save/recall/list）")
