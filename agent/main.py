"""命令行入口：交互式多窗口 Agent。

运行：
    python -m agent.main              # 使用真实 API（需配置 .env）
    python -m agent.main --mock       # 使用离线 MockLLM（无需 Key，演示/测试）

内置命令（以 / 开头）：
    /new <名称>     新建会话并切换
    /use <id|名称>  切换到已有会话
    /sessions       列出所有会话
    /reset          清空当前会话历史
    /help           帮助
    /exit           退出
"""

from __future__ import annotations

import argparse
import sys

from agent.config import load_settings
from agent.core.runtime import AgentRuntime, SessionBusyError
from agent.core.session import SessionManager
from agent.core.trace import TraceLogger
from agent.llm.client import LLMClient, LLMError
from agent.llm.mock import MockLLM
from agent.llm.summary import make_summarizer

# ----------------------------------------------------------------------
# 终端着色（非 tty 环境下自动禁用）


def _enable_ansi():
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            sys.stdin.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


_COLOR = sys.stdout.isatty()


def paint(code: str, text: str) -> str:
    return f"\x1b[{code}m{text}\x1b[0m" if _COLOR else text


GREEN, RED, CYAN, BOLD, DIM = "32", "31", "36", "1", "2"

# ----------------------------------------------------------------------
# 内置命令


def _handle_command(line: str, runtime: AgentRuntime, sessions: SessionManager, current) -> tuple[bool, object]:
    """处理 / 命令。返回 (是否退出, 当前会话)。"""
    parts = line.split(maxsplit=1)
    cmd = parts[0].lower()
    arg = parts[1] if len(parts) > 1 else ""

    if cmd == "/help":
        print(paint(DIM, __doc__.split("运行：")[1]))
        return False, current

    if cmd == "/exit":
        return True, current

    if cmd == "/new":
        session = sessions.create(arg or "会话")
        print(paint(CYAN, f"已新建并切换到会话：{session.name}（{session.id}）"))
        return False, session

    if cmd == "/use":
        if not arg:
            print(paint(RED, "用法：/use <id|名称>"))
            return False, current
        session = _find_session(sessions, arg)
        if session is None:
            print(paint(RED, f"找不到会话：{arg}（/sessions 查看）"))
        else:
            print(paint(CYAN, f"已切换到会话：{session.name}（{session.id}）"))
            return False, session
        return False, current

    if cmd == "/sessions":
        rows = sessions.list()
        if not rows:
            print(paint(DIM, "（暂无会话）"))
            return False, current
        for s in rows:
            mark = " *" if s.id == current.id else ""
            stamp = s.updated_at  # epoch 秒
            print(f"  {s.id}  {s.name}{mark}  消息{len(s.history)}条  {paint(DIM, s.state)}")
        return False, current

    if cmd == "/reset":
        current.history.clear()
        current.context.summary = ""
        current.context._folded = 0          # noqa: SLF001  重置摘要折叠游标
        sessions.persist_all()
        print(paint(CYAN, f"已清空会话 {current.name} 的历史与摘要"))
        return False, current

    print(paint(RED, f"未知命令：{cmd}（/help 查看）"))
    return False, current


def _find_session(sessions: SessionManager, key: str):
    rows = sessions.list()
    for s in rows:                          # 精确 id
        if s.id == key:
            return s
    for s in rows:                          # id 前缀
        if s.id.startswith(key):
            return s
    for s in rows:                          # 名称
        if s.name == key:
            return s
    return None


# ----------------------------------------------------------------------
# REPL


def _repl(runtime: AgentRuntime, sessions: SessionManager, current, mock: bool) -> None:
    mode = "mock" if mock else runtime.llm._settings.model if hasattr(runtime.llm, "_settings") else "?"
    print(paint(CYAN, f"minimal-agent  |  模式: {mode}  |  输入 /help 查看命令，Ctrl+C 退出"))

    while True:
        try:
            line = input(f"{paint(BOLD, current.name)}> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not line:
            continue

        if line.startswith("/"):
            should_exit, current = _handle_command(line, runtime, sessions, current)
            if should_exit:
                break
            continue

        try:
            answer = runtime.run(current.id, line)
        except SessionBusyError as e:
            print(paint(RED, f"[busy] {e}"))
        except LLMError as e:
            print(paint(RED, f"[LLM 错误] {e}"))
        except KeyError as e:
            print(paint(RED, f"[错误] {e}"))
        else:
            print(paint(GREEN, answer))


def _initial_session(sessions: SessionManager):
    rows = sessions.list()
    if not rows:
        return sessions.create("default")
    return max(rows, key=lambda s: s.updated_at)   # 恢复到最近使用的会话


# ----------------------------------------------------------------------
# 入口


def main() -> None:
    parser = argparse.ArgumentParser(description="minimal-agent 命令行")
    parser.add_argument("--mock", action="store_true", help="使用离线 MockLLM（无需 API Key）")
    args = parser.parse_args()

    _enable_ansi()
    settings = load_settings()

    if args.mock:
        llm = MockLLM()
    else:
        try:
            llm = LLMClient(settings)
        except LLMError as e:
            print(paint(RED, f"[错误] {e}"))
            print(paint(DIM, "提示：配置 .env 后重试，或加 --mock 以离线模式运行。"))
            return

    sessions = SessionManager(
        store_dir=f"{settings.data_dir}/sessions",
        system_prompt=settings.system_prompt,
        max_context_tokens=settings.max_context_tokens,
        summarizer=make_summarizer(llm),
    )
    trace = TraceLogger(settings.logs_dir)
    runtime = AgentRuntime(llm=llm, sessions=sessions, trace=trace, settings=settings)

    print(paint(DIM, f"trace 日志：{trace.path}"))
    current = _initial_session(sessions)
    try:
        _repl(runtime, sessions, current, args.mock)
    finally:
        trace.close()


if __name__ == "__main__":
    main()
