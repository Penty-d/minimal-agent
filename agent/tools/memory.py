"""memory 工具：跨会话长期记忆的读写接口。

模型通过它保存蒸馏后的事实/偏好（save）、检索相关记忆（recall）、
查看全部（list）。所有会话共享同一个 MemoryStore，属于跨对话记忆。
"""

from __future__ import annotations

from agent.core.memory import MAX_MEMORY_LEN, MemoryStore
from agent.tools.base import Tool, ToolError, ToolSpec


class MemoryTool(Tool):
    spec = ToolSpec(
        name="memory",
        description=(
            "管理跨会话的长期记忆（所有会话共享，重启后仍在）。"
            "当用户给出值得长期记住的事实、偏好、约定时调用 save；"
            "查看全部用 list。新会话开始时会自动带上已有记忆，"
            "不需要在对话中手动召回。"
            f"注意：单条记忆必须压缩成不超过 {MAX_MEMORY_LEN} 字的一句话，超长会被拒绝。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string",
                    "enum": ["save", "list"],
                    "description": "要执行的操作",
                },
                "content": {"type": "string", "description": "save 操作时，蒸馏成一句话的记忆内容"},
                "type": {
                    "type": "string",
                    "enum": ["偏好", "事实", "事件", "其他"],
                    "description": "save 操作的记忆类型（可选，默认 事实）",
                },
            },
            "required": ["operation"],
        },
    )

    def __init__(self, store: MemoryStore):
        self._store = store

    def execute(self, operation: str = "", content: str = "", type: str = "") -> str:
        op = (operation or "").strip()
        if op == "save":
            if not content.strip():
                raise ToolError("content 不能为空")
            try:
                e = self._store.save(content, type)
            except ValueError as err:      # 超长等数据层拒绝 → 转成工具错误回喂模型
                raise ToolError(str(err))
            return f"已保存记忆 [{e['id']}] ({e['type']})：{e['content']}"
        if op == "list":
            block = self._store.render_block(max_entries=50)
            return block or "（长期记忆为空）"
        raise ToolError(f"未知操作：{op}（可用：save/list）")
