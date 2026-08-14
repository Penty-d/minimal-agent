# minimal-agent

从零实现的最小可用 Agent Runtime。主流程（决策循环、输出解析、上下文管理、会话隔离、工具调度）全部自实现，不依赖任何 Agent 框架（langgraph / openhands / openclaw 等）。LLM 调用走 OpenAI 兼容协议。

## 特性

- **自实现主循环**：接收输入 → 模型决策 → 调用工具 → 结果回喂 → 直到最终答案
- **工具注册机制**：每个工具暴露名称 / 描述 / 参数 JSON Schema，模型自主决策调用
- **真实搜索**：`search` 工具基于必应 RSS 返回真实网页结果，网络不可用时回退内置演示数据
- **输出解析**：同时支持结构化 `tool_calls` 与文本标签（`<tool_call>`）两条路径，容错处理非法 JSON
- **多会话隔离 + 持久化**：窗口 1 的待办与历史不会出现在窗口 2，重启后自动恢复
- **Context 管理**：token 预算、干净截断（保持工具调用配对完整）、增量摘要压缩
- **执行 trace**：每步执行落 JSONL，可回放调试
- **双模式**：真实 API / 离线 Mock（无需 Key 即可运行与测试）

## 快速开始

```bash
pip install -r requirements.txt
cp .env.example .env      # 填入 LLM_API_KEY（DeepSeek）
python -m agent.main                # 真实 API
python -m agent.main --mock         # 离线 Mock（无需 Key）
```

REPL 内置命令（以 `/` 开头）：`/new <名称>` 新建会话、`/use <id|名称>` 切换会话、`/sessions` 列出会话、`/reset` 清空当前会话、`/help`、`/exit`。

## 测试

```bash
python -m pytest tests/ -q
# 39 passed
```

全部离线、确定性，基于 MockLLM 驱动，不依赖网络与 API Key。

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
| `agent/llm/client.py` | OpenAI 兼容客户端：请求/响应、指数退避重试、`reasoning_content` 抽取 |
| `agent/llm/parser.py` | 输出解析：结构化 `tool_calls` + 文本 `<tool_call>` 双路径，容错 |
| `agent/llm/mock.py` | 离线 Mock：与真实客户端同接口，脚本/规则两种模式 |
| `agent/llm/summary.py` | 对话摘要器：Context 压缩用 |
| `agent/tools/` | 工具契约 + 注册表 + 内置工具（calculator / search / weather / todo） |
| `agent/core/context.py` | token 预算、干净截断、增量摘要 |
| `agent/core/session.py` | 会话隔离、JSON 持久化 |
| `agent/core/runtime.py` | 主循环：busy 状态、异常分层、消息配对 |
| `agent/core/trace.py` | 执行日志（JSONL） |

### Agent 决策循环

每轮循环里，模型基于当前 context 返回两类输出之一：

1. **工具调用**（`tool_calls` 非空）→ 逐个执行工具，结果以 `tool` 角色消息回喂，进入下一轮
2. **最终答案**（无 `tool_calls`）→ 返回给用户，循环结束

防御机制：`MAX_LOOP_TURNS`（默认 8）限制单条输入的最大工具轮次，防止死循环；工具执行异常转成文本回喂，由模型修正重试。

## Memory：召回时机与放置方式

本项目把记忆分为四类，各自的召回时机与放置位置如下：

| 记忆类型 | 内容 | 召回时机 | 放置方式 |
|----------|------|----------|----------|
| 指令记忆 | system 提示（行为准则、必须用工具不编造） | 每次请求 | **最前**（context 第 1 条） |
| 长期记忆 | 滚动摘要（被截断历史的压缩） | 每次组装请求时取回（`build_request`） | **system 之后**，近期历史之前（全局锚点） |
| 近期记忆 | 最近若干轮完整对话（含工具调用/结果配对） | 每次组装请求时截断保留最新 | **摘要之后**，按时间顺序 |
| 任务记忆 | 待办清单（会话级 TodoStore） | **按需召回**：模型需要时通过 `todo` 工具读取 | 工具注入（模型调用工具获取） |

关键设计决策：

- **摘要放最前、近期放最后**：LLM 对 context 开头与结尾的信息权重更高。摘要放开头提供全局锚点，近期对话放结尾保证对最新状态（如"那明天呢"的天气结果）有完整感知。
- **召回时机 = 每次 LLM 调用前**：`ContextManager.build_request()` 在每轮循环组装请求，先取回摘要，再截断保留近期历史。压缩只发生在 token 超预算时，避免每轮无谓损耗。
- **工具结果必须随近期记忆保留**：追问"那明天呢"依赖上一轮的天气结果，工具调用与结果成对保留。
- **思考过程（reasoning_content）不回放进普通消息**：只对带 `tool_calls` 的 assistant 消息回传（DeepSeek V4 协议要求），避免陈旧思考污染后续对话。
- **待办按会话隔离**：`TodoStore` 绑定单个会话，模型通过 `todo` 工具按需读取，属于"拉取式"记忆而非全量注入。

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
- **切换服务商**：改 `LLM_BASE_URL` 与 `LLM_MODEL` 两个配置项即可对接 GLM / Qwen / 豆包 / OpenAI 等兼容端点。
- **安全**：calculator 使用 AST 白名单求值，拒绝 `eval` 类注入；`.env` 被 `.gitignore` 排除。
- **搜索实现**：`search` 工具用必应 `format=rss` 免 Key 轻量接口返回真实结果；网络不可用时回退内置演示数据。后端可注入，便于替换为带 Key 的正式搜索 API。
- **AI 辅助开发记录**：见 [`docs/AI-PROMPT-LOG.md`](docs/AI-PROMPT-LOG.md)。
