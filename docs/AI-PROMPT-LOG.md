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

### 1. 回溯 session 历史时 UI 未回显

vibecoding 之后，在使用 /use 命令时，我发现对话历史并未回显，用户对先前对话内容一无所知，即使 session 中已经有详细的对话记录。

解决：添加历史记录回显，并修正 AI 设置的 12 轮对话记录 limit。

### 2. 模型回答在历史回显中被截断

回显时发现 Agent 的回答被截断（只显示前 120 字），切回旧会话看不到完整的模型输出，没法接着聊。

解决：回显不再截断用户提问与模型回答，完整多行显示；只有工具调用给摘要。

### 3. session 记录污染

解决完历史记录回显问题后，重启对话发现 agent 的不同 session 的上下文全部混杂，于是追查文件，发现只有一份 session，是 vibecoding 时设计失误。每次新启动 agent 时还默认保持上次 session 内容。

解决：改为每次打开 agent 都新起一个 session；旧会话保留在磁盘，用 /use 显式切回，--resume 可恢复最近会话。

### 4. search 工具没法真正搜索

search 初版是罐头 mock，按关键词查写死的字典，未命中就返回兜底文本，名不副实。

解决：改用必应 RSS（format=rss）免 Key 返回真实网页结果，国内网络可用；网络不可用时回退内置演示数据，工具永不崩；后端可注入，便于日后替换为带 Key 的正式搜索 API。

### 5. DeepSeek 协议与印象不符

实现前以为模型名是 deepseek-chat、思考过程不回传。联网核对官方文档发现：当前模型是 deepseek-v4-flash / pro，思考模式默认开启，带 tool_calls 的 assistant 消息在后续请求中需要回传 reasoning_content（否则部分版本报 400），且 arguments 是 JSON 字符串、模型不一定生成合法 JSON。

解决：配置改用新模型名；Message 序列化时只对带 tool_calls 的 assistant 消息回传 reasoning_content；解析器对 arguments 做容错。

### 6. calculator 工具描述与实现不一致

描述示例写了 `5^2`，但实现只支持 `**`（`^` 在 Python 中是异或），模型照描述调用会失败。

解决：让工具描述与实现完全一致（改为 `5**2`）。

### 7. Mock 规则式无限重调同一工具

规则式 MockLLM 只看最后一条 user 消息；工具结果回喂后没有新的 user 消息，于是无限重调同一工具直到撞轮次上限。

解决：Mock 识别"最后一条 user 之后存在 tool 结果"即视为模型已拿到信息、直接作答，模拟真实模型行为。

### 8. 用户输入未写入 session 历史

初版只在请求里追加用户消息，没写进 session.history，导致持久化缺 user 轮、追问断档。

解决：runtime 先 history.append(user_msg) 再组装请求。

### 9. Context 截断破坏工具配对

按 token 预算截断时，切割点可能落在 tool 消息上，导致发给 API 的请求以 tool 消息开头，违反"tool 消息必须紧跟产生它的 assistant 消息"的协议。

解决：截断后修边界丢掉孤立的 tool 消息；请求列表一次组装、循环追加，保证配对永远成立。


## 三、给后续使用者的建议

- 协议细节以官方文档为准，不要凭印象
- 每加一个工具先定好 Schema，description 与实现保持一致
- 测试聚焦"runtime 决策逻辑"，用 Mock 隔离模型不确定性
