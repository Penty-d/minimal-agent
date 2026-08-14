"""执行日志（Trace）：把 Agent 每一步执行过程落成 JSONL。

每次运行写一个 logs/trace-<时间戳>.jsonl，逐行记录：
用户输入 / context 构建 / LLM 调用 / 思考 / 工具调用 / 工具结果 / 最终回答 / 异常。
可用 jq 或任意 JSON 工具回放调试。
"""

from __future__ import annotations

import json
import os
import time


class TraceLogger:
    def __init__(self, logs_dir: str = "logs"):
        os.makedirs(logs_dir, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        self._path = os.path.join(logs_dir, f"trace-{stamp}.jsonl")
        self._f = open(self._path, "a", encoding="utf-8")

    @property
    def path(self) -> str:
        return self._path

    def log(self, session_id: str, event: str, **payload) -> None:
        record = {"ts": time.time(), "session": session_id, "event": event}
        record.update({k: v for k, v in payload.items() if v is not None})
        self._f.write(json.dumps(record, ensure_ascii=False) + "\n")
        self._f.flush()

    def close(self) -> None:
        try:
            self._f.close()
        except Exception:
            pass
