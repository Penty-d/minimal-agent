"""配置模块：从环境变量 / .env 文件加载运行配置。

配置项统一通过环境变量注入，便于部署时在不同服务商之间切换，
也避免把 API Key 写进代码仓库。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

load_dotenv()

# OpenAI 兼容协议，默认对接 DeepSeek。
# 模型名以官方文档为准：deepseek-v4-flash / deepseek-v4-pro。
DEFAULT_BASE_URL = "https://api.deepseek.com/v1"
DEFAULT_MODEL = "deepseek-v4-flash"


@dataclass
class Settings:
    # LLM 接入
    api_key: str = ""
    base_url: str = DEFAULT_BASE_URL
    model: str = DEFAULT_MODEL
    temperature: float = 0.3
    request_timeout: float = 120.0
    max_retries: int = 3

    # 上下文 / 循环控制
    max_context_tokens: int = 6000      # 单次请求的上下文 token 预算
    max_loop_turns: int = 8             # 单条用户输入的最大工具循环轮次
    system_prompt: str = field(default_factory=lambda: SYSTEM_PROMPT)

    # 路径
    data_dir: str = "data"              # 会话持久化目录
    logs_dir: str = "logs"              # trace 日志目录


SYSTEM_PROMPT = """你是一个运行在终端里的最小 Agent（minimal-agent），可以通过工具完成任务。

行为准则：
1. 需要实时事实信息（天气、搜索等）时，必须调用对应工具，不要编造数据。
2. 需要数学计算时，调用 calculator 工具。
3. 用户要求记录待办时，调用 todo 工具（每个会话有独立的待办列表）。
4. 先调用工具获取结果，再基于结果组织回答；回答用中文，简洁直接。
5. 如果用户追问依赖之前工具结果的问题，结合历史中的工具结果回答。
"""


def load_settings() -> Settings:
    """从环境变量构建配置。"""
    return Settings(
        api_key=os.environ.get("LLM_API_KEY", ""),
        base_url=os.environ.get("LLM_BASE_URL", DEFAULT_BASE_URL).rstrip("/"),
        model=os.environ.get("LLM_MODEL", DEFAULT_MODEL),
        temperature=float(os.environ.get("TEMPERATURE", "0.3")),
        request_timeout=float(os.environ.get("REQUEST_TIMEOUT", "120")),
        max_retries=int(os.environ.get("MAX_RETRIES", "3")),
        max_context_tokens=int(os.environ.get("MAX_CONTEXT_TOKENS", "6000")),
        max_loop_turns=int(os.environ.get("MAX_LOOP_TURNS", "8")),
        data_dir=os.environ.get("DATA_DIR", "data"),
        logs_dir=os.environ.get("LOGS_DIR", "logs"),
    )
