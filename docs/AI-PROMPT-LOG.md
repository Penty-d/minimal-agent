# AI Prompt 与问题解决记录

本项目使用 Claude Code 辅助开发。本文记录各阶段的关键 Prompt 思路、产出与踩坑过程。

原则：**AI 用于辅助思考与加速开发，不替代设计决策**。每个模块先讲清设计意图、明确接口契约，再实现并测试验证；AI 产出的代码逐段审阅，不理解的地方会追问"为什么这么设计"。

## 一、开发流程

| 阶段 | Prompt 要点 | 产出 | 关键决策 |
|------|-------------|------|----------|
| 1. 系统设计 | 讲清 Agent 决策循环、工具与 Schema、输出解析、Session/Context 的存在意义 | 系统设计文档 | 职责分层：客户端只管网络，解析只管结构化，循环由 runtime 决策 |
| 2. 骨架与配置 | 环境变量配置、OpenAI 兼容协议 | config / .env / requirements | 配置走环境变量，Key 不进仓库 |
| 3. LLM 客户端 | 协议核实 + 重试策略 | `llm/client.py` + `mock.py` | 瞬时错误退避重试，鉴权错误直接抛；Mock 与真实客户端同接口 |
| 4. 输出解析 | 提取思考/工具调用/最终答案 | `llm/parser.py` | 结构化 + 文本双路径；arguments 容错解析 |
| 5. 工具层 | 工具契约与注册机制、安全求值 | `tools/` | 校验与异常捕获统一在注册表；calculator 用 AST 白名单拒绝 eval 注入 |
| 6. Context | token 预算、截断、摘要压缩 | `core/context.py` | 干净截断保持 tool 配对；仅在截断时增量摘要 |
| 7. Session | 多窗口隔离、持久化 | `core/session.py` | 每会话独立历史/摘要/待办/注册表；原子写入 |
| 8. Runtime | 主循环、busy、异常、trace | `core/runtime.py` + `main.py` | 请求列表一次组装循环追加；先写用户消息进历史 |
| 9. 测试 | 非确定系统的测试策略 | `tests/` | MockLLM 固定模型行为，测试确定性、离线 |

## 二、遇到的问题与解决

### 1. DeepSeek 协议与印象不符 → 联网核实官方文档

实现前按旧印象以为模型名是 `deepseek-chat`、思考过程不传回。联网核对 `api-docs.deepseek.com` 后发现：

- 当前模型为 `deepseek-v4-flash` / `deepseek-v4-pro`
- 思考模式默认开启，响应带 `reasoning_content`
- **带 `tool_calls` 的 assistant 消息在后续请求中需回传 `reasoning_content`**（部分版本否则报 400）
- `arguments` 是 JSON 字符串，且"模型不一定生成合法 JSON"

解决：配置改为新模型名；`Message.to_api()` 只对带 `tool_calls` 的 assistant 消息回传 `reasoning_content`；解析器对 arguments 做容错。

### 2. 截断破坏 tool 配对 → API 400

Context 截断时按 token 预算从旧到新切，结果可能以一条 `tool` 消息开头——而协议要求 `tool` 消息紧跟产生它的 `assistant` 消息。解决：截断后修边界，丢掉孤立的 tool 消息；并在 runtime 中用"请求列表一次组装、循环追加"保证配对永远成立。

### 3. 用户输入未写入历史 → 持久化缺 user 轮

初版只在请求里追加用户消息，没写进 `session.history`，导致持久化不完整、追问断档。解决：`_run_loop` 先 `history.append(user_msg)` 再组装请求。

### 4. Mock 规则式无限重调同一工具

规则式 Mock 每次看"最后一条 user 消息"；工具结果回喂后没有新的 user 消息，于是无限重调同一工具直到撞轮次上限。解决：Mock 识别"最后一条 user 之后存在 tool 结果"，视为模型已拿到信息、直接作答——模拟真实模型行为。

### 5. calculator 的 eval 注入风险

`eval` 可执行任意代码（`__import__('os')` 等）。解决：用 `ast.parse` + 白名单遍历，只放行数字/四则/幂/括号/白名单函数与常量，从语法层拒绝危险节点；除零等错误转成文本回喂模型。

### 6. "从零实现"的边界理解

最初连 `.env` 加载器都手写，过于极端。确认约束本质是"不依赖 Agent 框架"，标准工具库（httpx、python-dotenv、pytest）可用。改为 `python-dotenv`。

### 7. 工具描述与实现不一致

calculator 描述示例写了 `5^2`，但实现只支持 `**`（`^` 在 Python 中是异或）。导致"契约引导模型调用出错"。解决：让描述与实现完全一致。

### 8. 非确定系统的测试

Agent 行为依赖 LLM，直接测不稳定。解决：MockLLM 提供脚本模式（预设响应序列），精确复现"调工具→回答/连续调/超轮次/异常"等场景，测试 runtime 逻辑本身；模型质量另用评测，不进单测。

### 9. search 工具"名不副实"

初版 search 是罐头 mock（按关键词查写死的字典），"没法真正搜索"。确认题目允许 mock 但并非强制后，改为**真实搜索 + 回退**：
- 用必应 `format=rss` 免 Key 轻量接口，返回真实网页结果（标题/链接/摘要），国内网络可用
- 网络不可用或解析失败时回退内置演示数据，工具永不崩
- 后端可注入，测试用假后端保持离线确定性，也便于日后替换为带 Key 的正式搜索 API

## 三、给后续使用者的建议

- 协议细节以官方文档为准，不要凭印象
- 每加一个工具先定好 Schema，description 与实现保持一致
- 测试聚焦"runtime 决策逻辑"，用 Mock 隔离模型不确定性
