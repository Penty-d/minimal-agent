"""todo 工具：会话级的待办清单。

TodoStore 属于某个 Session；每个会话通过 build_session_registry 拿到
绑定自己 store 的 TodoTool 实例，从而实现各窗口待办互不影响。
"""

from __future__ import annotations

from dataclasses import dataclass

from agent.tools.base import Tool, ToolError, ToolSpec


@dataclass
class TodoItem:
    id: str
    text: str
    done: bool = False


class TodoStore:
    """单个会话的待办列表。"""

    def __init__(self):
        self._items: list[TodoItem] = []
        self._counter = 0

    def add(self, text: str) -> TodoItem:
        text = text.strip()
        if not text:
            raise ToolError("待办内容不能为空")
        self._counter += 1
        item = TodoItem(id=f"t{self._counter}", text=text)
        self._items.append(item)
        return item

    def list_items(self) -> list[TodoItem]:
        return list(self._items)

    def complete(self, item_id: str) -> TodoItem | None:
        for it in self._items:
            if it.id == item_id:
                it.done = True
                return it
        return None

    def remove(self, item_id: str) -> TodoItem | None:
        for i, it in enumerate(self._items):
            if it.id == item_id:
                return self._items.pop(i)
        return None

    def render(self) -> str:
        if not self._items:
            return "（待办为空）"
        return "\n".join(
            f"{it.id} {'[x]' if it.done else '[ ]'} {it.text}" for it in self._items
        )

    def to_dict(self) -> dict:
        return {
            "counter": self._counter,
            "items": [{"id": it.id, "text": it.text, "done": it.done} for it in self._items],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "TodoStore":
        store = cls()
        store._counter = data.get("counter", 0)
        store._items = [
            TodoItem(id=d["id"], text=d["text"], done=d.get("done", False))
            for d in data.get("items", [])
        ]
        return store


class TodoTool(Tool):
    spec = ToolSpec(
        name="todo",
        description=(
            "管理当前会话的待办清单。用户要记录/查看/勾选/删除待办、备忘、"
            "周报要点、任务清单时使用。操作：add 添加，list 查看，"
            "complete 完成，remove 删除。每个会话的待办互相独立。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string",
                    "enum": ["add", "list", "complete", "remove"],
                    "description": "要执行的操作",
                },
                "item": {"type": "string", "description": "add 操作时的待办内容"},
                "id": {"type": "string", "description": "complete/remove 操作时的待办 id（形如 t1）"},
            },
            "required": ["operation"],
        },
    )

    def __init__(self, store: TodoStore):
        self._store = store

    def execute(self, operation: str = "", item: str = "", id: str = "") -> str:
        op = (operation or "").strip()
        if op == "add":
            it = self._store.add(item)
            return f"已添加待办：{it.id} {it.text}\n当前待办：\n{self._store.render()}"
        if op == "list":
            return f"当前待办：\n{self._store.render()}"
        if op == "complete":
            it = self._store.complete(id)
            return f"已完成：{it.id} {it.text}" if it else f"找不到 id={id}"
        if op == "remove":
            it = self._store.remove(id)
            return f"已删除：{it.id} {it.text}" if it else f"找不到 id={id}"
        raise ToolError(f"未知操作：{op}（可用：add/list/complete/remove）")
