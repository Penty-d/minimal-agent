# minimal-agent

从零实现的最小可用 Agent Runtime。

OpenAI 兼容协议。

## 特性

- **自实现主循环**：遵守ReAct流程，接收输入 → 模型决策 → 调用工具 → 工具结果 → 直到最终答案
- **工具注册机制**：工具按 名称，描述，参数的JSON Schema注册
- **session隔离 + 持久化**：session落盘， `/use` 切回，`--resume` 恢复最近会话
- **Context 管理**：token 预算、干净截断、增量摘要压缩
- **执行 trace**：每步执行落 JSONL，可回放调试

## 快速开始

```bash
pip install -r requirements.txt
cp .env.example .env      # 填入 LLM_API_KEY（DeepSeek）
python -m agent.main                # 真实 API（启动新建会话）
python -m agent.main --mock         # 离线 Mock（无需 Key）
python -m agent.main --resume       # 启动时恢复最近会话
```

REPL 内置命令（以 `/` 开头）：`/new <名称>` 新建会话、`/use <id|名称>` 切换会话、`/sessions` 列出会话、`/reset` 清空当前会话、`/help`、`/exit`。

## 测试

```bash
python -m pytest tests/ -q
# 39 passed
```

## 系统设计

### 整体架构

```
用户输入
   │
   ▼
┌──────────────────────────────────────────────────┐
│ ContextManager：system + 摘要 + 近期历史 + 新输入   │
└──────────────────────────────────────────────────┘
   │
   ▼
┌──────────────┐  原始输出   ┌──────────────┐
│  LLM 客户端  │──────────▶ │   解析器      │
└──────────────┘            └──────────────┘
                                 │
              ┌──────────────────┴──────────────────┐
              ▼                                     ▼
        有工具调用（tool_calls）               无工具调用（最终答案）
              │                                     │
              ▼                                     ▼
   ┌──────────────────┐                        返回给用户
   │ ToolRegistry      │  ──执行──▶  工具结果
   │ execute(name,args)│ ◀──────────  （calculator/search/
   └──────────────────┘               weather/todo）
              │
              ▼  结果以 tool 消息回喂，继续循环
        ┌─────────────┐
        │ AgentRuntime │  每步写入 Trace；会话历史入库
        └─────────────┘
```

### 模块职责

| 模块 | 职责 |
|------|------|
| `agent/llm/client.py` | OpenAI 兼容客户端：请求/响应|
| `agent/llm/mock.py` | 离线 Mock：与真实客户端同接口，脚本/规则两种模式 |
| `agent/llm/summary.py` | 对话摘要器：Context 压缩用 |
| `agent/tools/` | 工具契约 + 注册表 + 内置工具（calculator / search / weather / todo） |
| `agent/core/context.py` | 上下文拼装，截断|
| `agent/core/session.py` | 会话隔离、JSON 持久化 |
| `agent/core/runtime.py` | 主循环：busy 状态、异常分层、消息配对 |
| `agent/core/trace.py` | 执行日志 |

### Agent 决策循环

遵循ReAct规则，llm返回纯对话信息时视为结束这一轮对话

防御机制：`MAX_LOOP_TURNS`（默认 8）限制单条输入的最大工具轮次，防止死循环；工具执行异常转成文本回喂，由模型修正重试。

### 跨会话长期记忆

**由llm判断是否需要写入memory，并将关键信息以短句的形式写入，以免占据过多context**。

| 环节 | 召回/写入时机 | 放置方式 |
|------|--------------|----------|
| 写入 | 对话中：模型判断"值得长期记住"时调 `memory.save` | 落盘 `data/memory.json`，所有会话共享 |
| 会话开始召回 | 每次组装请求（`build_request`）时注入记忆句子 | system prompt之后、会话摘要之前 |

### 上下文组成

| 内容 | 召回时机 | 放置方式 |
|------|----------|----------|
| system prompt | 每次请求 | 最前 |
| memory | 每次用户输入 | system prompt之后，简单拼装 |
| 滚动摘要 | 每次用户输入 | memory之后 |
| 最近若干轮完整对话 | 每次用户输入 | 摘要之后，按时间顺序 |

## 配置

| 环境变量 | 默认值 | 说明 |
|----------|--------|------|
| `LLM_API_KEY` | （必填） | API Key，仅从环境变量读取，不进仓库 |
| `LLM_BASE_URL` | `https://api.deepseek.com/v1` | OpenAI 兼容端点 |
| `LLM_MODEL` | `deepseek-v4-flash` | 模型名 |
| `MAX_CONTEXT_TOKENS` | `128000` | 单次请求上下文 token 预算 |
| `MAX_LOOP_TURNS` | `8` | 单条输入最大工具轮次 |
| `TEMPERATURE` | `1.0` | 采样温度

## 目录结构

```
minimal-agent/
├── agent/
│   ├── config.py        # 配置
│   ├── main.py          # CLI REPL
│   ├── llm/             # 客户端 / 解析 / Mock / 摘要
│   ├── tools/           # 工具契约 + 注册表 + 内置工具
│   └── core/            # 消息 / Context / Session / Runtime / Trace
├── tests/               # pytest 测试套件
└── requirements.txt
```

## 相关说明

- **"从零实现"的边界**：不使用 Agent 框架；使用标准工具库（httpx、python-dotenv、pytest）。
- **切换服务商**：兼容 OpenAI response协议。
- **安全**：calculator 使用 AST 白名单求值，拒绝 `eval` 类注入；`.env` 被 `.gitignore` 排除。
- **AI 辅助开发记录**：见 [`docs/AI-PROMPT-LOG.md`](docs/AI-PROMPT-LOG.md)。
