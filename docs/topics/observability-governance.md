# 观测与治理层

观测与治理层负责回答三个问题：

- 系统现在是否健康？
- 一次 Agent 运行为什么走到这个结果？
- 哪些动作产生了副作用，是否符合权限、确认和审计要求？

当前项目已经具备应用内事件、日志、checkpoint、工具治理、基础 Web 治理能力，并已完成 LangSmith 的基础配置与 entry 入口 trace context 接入。因此它已经可以开始使用 LangSmith 观察 LangGraph/LangChain 执行链路，但距离生产级 Agent 可观测性仍有明显差距。

## 当前基线

### 1. 应用日志

[logging_utils.py](../../src/personal_agent/core/logging_utils.py) 提供：

- `setup_logging()`：输出 console 和 `log/run.log`。
- `log_event()`：写结构化字段日志。
- `trace_span()`：记录 start/end/error、duration、trace_id、span、user_id、error type 等字段。

这套日志适合本地排错，但不是完整 tracing backend。

### 2. AgentEvent

[orchestration_models.py](../../src/personal_agent/agent/orchestration_models.py) 定义 `AgentEvent`，用于记录编排过程：

- `entry_started`
- `intent_classified`
- `plan_created`
- `plan_validated`
- `step_started`
- `react_iteration`
- `tool_called`
- `tool_result`
- `confirmation_required`
- `step_completed`
- `step_failed`
- `answer_completed`
- `run_completed`

这些事件会进入 `AgentGraphState.events`，并可派生 `execution_trace` 与 SSE 事件。

### 3. LangGraph checkpoint

LangGraph checkpoint 保存可恢复执行现场：

- `messages`
- `plan`
- `react`
- `tool_tracking`
- `tool_results`
- `events`
- `pending_confirmation`
- `answer`

它解决的是恢复和状态回放，不等同于 LLM trace 平台。

### 4. 工具审计

工具层已经从零散 `extras` 收敛到 `ToolGovernance`：

- `risk_level`
- `requires_confirmation`
- `side_effects`
- `permission_scope`
- `idempotency_key_required`
- `rollback_supported`
- `audit_required`

`tool_invocation_event()` 统一 direct 调用与图执行期工具结果的审计 payload。计划执行和 ReAct 的 `tool_result` 事件会带上 `invocation` 字段。

### 5. Web 治理

[web/auth.py](../../src/personal_agent/web/auth.py) 和 [web/api.py](../../src/personal_agent/web/api.py) 提供：

- `GET /api/health` 健康检查。
- API Key 鉴权。
- `Authorization: Bearer <key>`、`X-API-Key`、`api_key` query 参数。
- 进程内 token bucket 限流。
- 基于 `user_id` 的用户隔离。

### 6. LangSmith 基础接入

当前已完成 P0/P1 的基础接入：

- `LangSmithConfig` 从环境变量读取项目、endpoint、API key、workspace、采样率和上传策略开关。
- `configure_langsmith_environment()` 将项目配置桥接到 LangSmith 标准环境变量。
- `execute_entry()` 和 `resume_entry()` 外层会进入 `langsmith_trace_context()`，并通过 LangGraph `config` 设置 `run_name`（`execute_entry` / `resume_entry`）、业务 metadata 和 tags，使整棵节点/LLM/工具子树挂在同一个可检索的顶层 run 下。
- 顶层 trace metadata 会携带 `run_id / thread_id / user_id / session_id / source_platform / source_type` 等业务字段。
- LLM 调用会读取 `response.usage` 并通过 `run_tree.set(usage_metadata=...)` 上报 token，使 LangSmith 能聚合 token 与成本；非流式与流式回答都已覆盖。
- 采样未命中时，`langsmith_trace_context()` 会返回 `tracing_context(enabled=False)` 主动关闭由 `LANGSMITH_*` 环境变量安装的全局 tracer，使 `sample_rate` 真正生效，而不是被全局 tracer 绕过。
- 工具审计事件会通过 `get_current_run_tree()` 填充 `langsmith_run_id`，把业务审计记录与 LangSmith run 关联。
- `PERSONAL_AGENT_LANGSMITH_ENABLED=false` 时会强制设置 `LANGSMITH_TRACING=false`，避免外部环境误开。

核心规划链路也已开始接入 LLM trace wrapper：

- router：记录 `prompt_name=router`、模型、latency、JSON parse 状态。
- planner：记录 `prompt_name=planner`、模型、latency、`PlanStep[]` parse 状态。
- replanner：记录 `prompt_name=replanner`、失败 step metadata 和 parse 状态。
- ReAct：记录 `prompt_name=react`、模型调用和 `ReactAction` parse 状态。
- direct answer：记录 `prompt_name=direct_answer` 与 route metadata。
- runtime answer generation：非流式回答记录 `prompt_name=answer_generation`；流式回答记录 stream latency 和输出长度。
- query planner：记录 `prompt_name=query_planner`、结构化 schema 和 `QueryUnderstanding` parse 状态。
- LLM reranker：记录 `prompt_name=evidence_rerank`、候选数量和 `EvidenceRerank` parse 状态。
- Graphiti 内部 LLM：记录 `prompt_name=graphiti_extraction`、response model、latency 和 JSON parse 状态。
- embedding：记录 `embedding.call / embedding.local / embedding.fallback`，可看到外部 embedding 延迟、维度、输入长度和降级原因。
- 本地检索：记录 `retrieval.local`，包含 query 长度、lexical/vector 候选数、合并候选数、结果数、过滤器状态、embedding 是否参与和总耗时。
- verifier：记录 `verifier.result / verifier.run`，包含 evidence score、citation/claim 状态、issue/warning 数量、输入输出长度和耗时，不上传原始回答正文。
- 基础 metrics：记录 `agent.run`、`tool.invocation`、`verifier.run`，可由结构化日志聚合运行耗时、工具成功率和校验结果分布。
- `PERSONAL_AGENT_TRACE_UPLOAD_INPUTS=false` 时，统一 wrapper 默认不走会上传完整 prompt/output 的 traceable runner，仅保留本地结构化日志和非敏感 metadata；显式开启后才上传完整输入输出。

## 当前弱点

### 1. LLM 调用级 trace 仍不完整

目前无法稳定地从一个界面看到：

- router prompt
- planner prompt
- replanner prompt
- verifier prompt
- ReAct prompt
- raw model output
- parse result
- tokens
- latency
- model name
- retry 次数

这会导致“为什么这样规划/为什么这样回答”很难快速定位。

### 2. 缺少跨节点 run tree

当前 `AgentEvent` 是线性事件流，缺少父子 span 结构。一次运行中的路由、规划、检索、工具调用、LLM 生成、校验之间还不能自然形成 trace tree。

### 3. 工具审计还未独立落库

`tool_result.payload.invocation` 已经形成结构化 payload，但还没有写入独立审计表。LangSmith 适合调试和观测，业务审计仍应独立持久化。

### 4. metrics 与 alert 缺失

当前没有统一指标：

- run 成功率
- intent 分布
- plan validation failure rate
- tool failure rate
- LLM latency / token cost
- graph search timeout rate
- HITL 等待/拒绝/确认比例

也没有告警规则。

### 5. 限流和权限模型偏轻

限流是进程内的，不适合多实例。API Key 模型适合个人或轻量多用户场景，还没有组织、角色、租户、key 生命周期管理。

### 6. Policy Engine 已落地（统一策略层）

历史上治理元数据和轻量策略分散在多处：

- 工具层的 `risk_level / side_effects / permission_scope / requires_confirmation`。
- Web 层的 API Key、进程内限流和 `user_id` 隔离。
- 记忆层的 `user_id / session_id / source` 等访问边界。
- `delete_note` 的 HITL、幂等 key 和工具审计 payload。

这些能力现已收敛成统一 `PolicyEngine`（`personal_agent/policy/`）。它接收归一化的 `PolicyInput`（`action / user_id / session_id / source_platform / tool_name / resource / risk_level / side_effects / permission_scope / confirmed / react_allowed_tools / resource_owner`），输出 `PolicyDecision`（`allow / deny / require_confirmation / require_escalation` + `audit_required / rule / reason`）。

落地范围：

- **工具层**：`ToolGateway._validate_policy` 委托给 `PolicyEngine`，统一 ReAct 自主守卫、高风险确认门、override 拒绝。幂等 key 与外部域名白名单仍由 gateway 作为执行机制保留。每个非放行决策通过 `record_policy_decision` 写入审计与指标。
- **记忆层**：`MemoryFacade` 的 capture/update/delete 通过引擎做 owner 校验与删除确认门，对应 [memory.md](memory.md) 的 `Memory Policy Engine`。
- **规划/ReAct**：`_is_react_tool_blocked` 复用同一引擎，确保预过滤与 gateway 执行期判定一致。
- **可配置覆盖**：`PolicyConfig`（`Settings.policy`）支持按用户/来源/工具/权限域配置 allow/deny 列表，以及关闭高风险确认门，默认空集合时完全沿用代码内默认规则。

`workspace` 维度在 `PolicyInput` 中已预留字段，但当前未引入业务 workspace 概念，默认 `None`。

## LangSmith 接入目标

LangSmith 接入的第一目标不是替代现有 `AgentEvent`，而是补齐 LLM/Agent trace 视角。

目标能力：

- 自动追踪 LangChain / LangGraph 执行链路。
- 把一次 `execute_entry()` 作为顶层 run。
- 将 router、planner、plan execution、ReAct、ToolNode、LLM 调用放入同一个 trace tree。
- 在 trace metadata 中携带业务上下文。
- 将线上失败 trace 转化为 eval 样本。
- 保留本地 `AgentEvent` 作为产品反馈和业务状态源。

## 接入原则

1. LangSmith 用于调试、分析和评测，不作为唯一审计源。
2. `AgentEvent` 继续服务前端、SSE、checkpoint 和业务状态。
3. 工具副作用仍以本地审计表为准，LangSmith 只保存可观测副本。
4. 默认不上传敏感原文；需要脱敏策略后再开启完整 prompt trace。
5. trace metadata 只放稳定、低敏、可索引字段。

## 推荐环境变量

根据 LangSmith 官方文档，LangChain / LangGraph 应用可以通过环境变量启用 tracing：

```env
LANGSMITH_TRACING=true
LANGSMITH_API_KEY=...
LANGSMITH_PROJECT=personal-agent-dev
LANGSMITH_ENDPOINT=https://api.smith.langchain.com
```

可选：

```env
LANGSMITH_WORKSPACE_ID=...
```

项目建议再增加自己的开关，避免生产环境误开：

```env
PERSONAL_AGENT_LANGSMITH_ENABLED=false
PERSONAL_AGENT_LANGSMITH_PROJECT=personal-agent-dev
PERSONAL_AGENT_TRACE_UPLOAD_INPUTS=false
PERSONAL_AGENT_TRACE_SAMPLE_RATE=1.0
```

## Metadata 规范

每个 LangSmith 顶层 run 建议携带：

```json
{
  "app": "personal-agent",
  "env": "dev",
  "run_id": "agent run id",
  "thread_id": "user:session",
  "user_id": "user id",
  "session_id": "session id",
  "intent": "ask | capture_text | delete_knowledge | ...",
  "source_platform": "web | cli | feishu",
  "requires_planning": true,
  "requires_confirmation": false,
  "risk_level": "low"
}
```

工具子 run 建议携带：

```json
{
  "tool_name": "graph_search",
  "tool_call_id": "...",
  "step_id": "...",
  "execution_mode": "deterministic | react | direct",
  "risk_level": "low",
  "side_effects": ["read_local"],
  "permission_scope": "memory:read"
}
```

LLM 子 run 建议携带：

```json
{
  "prompt_name": "router | planner | replanner | verifier | react",
  "prompt_version": "v1",
  "model": "...",
  "parse_schema": "...",
  "parse_ok": true
}
```

## 分阶段规划

### P0：配置与自动 tracing（已完成）

目标：最小成本看到 LangGraph / LangChain trace。

工作项：

- 在 `.env.example` 和 [docs/env.md](../env.md) 增加 LangSmith 环境变量说明。
- 在 `Settings` 中增加 `LangSmithConfig`。
- 启动时根据 `PERSONAL_AGENT_LANGSMITH_ENABLED` 设置/校验 `LANGSMITH_*` 环境变量。
- 先依赖 LangChain/LangGraph 原生 tracing，不改业务逻辑。

验收：

- 执行一次 `ask`，LangSmith 项目中能看到 trace。
- trace 中能看到 LangGraph 节点和工具调用。
- 未配置 API key 时不影响本地运行。

### P1：顶层 run 与 metadata 对齐（基础完成）

目标：能按业务维度检索 trace。

工作项：

- 在 `execute_entry()` 或 entry graph 外层包一层 trace context。
- 将 `run_id / thread_id / user_id / session_id / intent / source_platform` 写入 metadata。
- 后续将 `AgentEvent.event_id` 与 LangSmith run id 关联到日志字段。
- 后续为 `tool_invocation_event()` 增加 `langsmith_run_id` 预留字段。

验收：

- 可以在 LangSmith 按 `thread_id`、`intent`、`run_id` 过滤 trace。
- 本地 `AgentEvent` 和 LangSmith trace 能互相定位。

### P2：LLM 调用统一包装（主链路基础完成）

目标：看清每次模型调用的 prompt、输出、解析和失败。

工作项：

- 建立统一 LLM wrapper。（已完成）
- router、planner、replanner、ReAct 通过 wrapper 调用。（已完成）
- direct_answer、runtime answer generation、query planner 和 LLM reranker 通过 wrapper 或 trace context 记录。（已完成）
- 记录 `prompt_name`、`prompt_version`、`model`、`latency_ms`、`parse_ok`、`parse_error`。（主链路已完成）
- 使用 `PERSONAL_AGENT_TRACE_UPLOAD_INPUTS` 控制是否上传完整 prompt/output。（已完成）
- Graphiti 内部策略记录 `graphiti_extraction` 调用和 parse 状态。（已完成）
- embedding 与数据库向量入口记录外部调用、本地 embedding 和失败降级。（已完成）
- 本地 Postgres 检索记录 `retrieval.local` 聚合指标。（已完成）
- verifier 规则校验事件已接入；后续继续接入数据库向量相似度 SQL 分段 latency、结构化检索 cache 命中率。
- 对 raw input/output 增加脱敏开关。

验收：

- 任意一次失败规划都能定位到 planner raw output。
- 任意一次 ReAct parse failure 都能看到原始模型输出和解析错误。

### P3：工具审计落库

目标：把业务副作用与观测 trace 分离。

工作项：

- 新建 `tool_invocations` 或 `agent_audit_events` 表。
- 将 `tool_result.payload.invocation` 写入表。
- 对高风险工具记录 confirmation payload、确认人、确认时间、执行结果。
- 为 `delete_note` 补充幂等 key 与删除前快照策略。

验收：

- 不打开 LangSmith 也能查询某用户所有高风险操作。
- 可以回答“谁在什么时候删除了哪条笔记，是否确认，结果如何”。

### P4：Policy Engine 与权限后端（已完成）

目标：把散落在入口、工具、记忆和规划流程中的轻量权限判断收敛为统一策略服务。

工作项：

- ✅ 定义统一 `PolicyDecision`：`allow / deny / require_confirmation / require_escalation`（含 `audit_required / rule / reason`）。
- ✅ 定义统一输入 `PolicyInput`：用户、session、入口来源、action、resource、工具名、风险等级、副作用、权限域、确认标志、ReAct 允许集、资源 owner（`workspace` 字段预留，暂不引入业务概念）。
- ✅ 将 `ToolGateway` 的高风险确认、ReAct guard、`permission_scope` 判断接入 `PolicyEngine`。
- ✅ 将 `MemoryFacade` 的 capture / update / delete 接入 Memory Policy（owner 校验 + 删除确认门）。
- ✅ 将入口来源（`source_platform`）纳入策略上下文，经 `ToolGatewayContext` 从 `AgentGraphState.entry_input` 透传。
- ✅ 将策略结果写入审计事件（`record_policy_decision`），便于追踪“为什么允许 / 拒绝 / 要求确认”。

实现：`personal_agent/policy/`（`models.py` + `engine.py`），可配置覆盖见 `Settings.policy`（`PolicyConfig`）。

验收：

- ✅ 可以针对用户、入口来源和工具/权限域配置 allow / deny（`PolicyRules`）。
- ✅ `delete_note` 这类高风险动作的确认要求来自策略决策（`tool.high_risk_confirmation`），不再只写死在工具实现里。
- ✅ 长期记忆的读写删除都通过同一个策略接口解释授权结果。

### P5：metrics 与告警

目标：从单次调试走向运行质量监控。

工作项：

- 输出 run-level metrics。
- 输出 tool-level metrics。
- 输出 LLM latency / token / error metrics。
- 增加失败率、超时率、高风险操作异常告警。

验收：

- 可以看到最近 24h 成功率、平均延迟、工具失败 TopN。
- 高风险工具失败、policy deny 激增或 debug reset 调用能触发告警。

### P6：eval 与线上 trace 闭环

目标：把真实失败样本沉淀为回归评测。

工作项：

- 标记失败/低质量 trace。
- 从 LangSmith trace 导出 eval dataset。
- 将线上失败的 router/planner/ReAct 样本加入 eval。
- 对 prompt/model 改动做回归比较。

验收：

- 线上失败样本可以一键转为回归 case。
- prompt 或模型升级前能跑对比评测。

## 隐私与安全边界

LangSmith 会接收 prompt、输出、工具输入输出等观测数据。接入前必须明确：

- 是否允许上传用户原文。
- 是否允许上传长期记忆内容。
- 是否允许上传外部搜索结果正文。
- 是否需要对 API key、URL token、用户 ID、文件路径脱敏。
- 生产环境是否采样，而不是全量上传。

建议默认策略：

- dev：允许完整 trace，便于调试。
- staging：允许完整 trace，但使用测试数据。
- prod：默认只上传 metadata 和摘要；敏感字段脱敏；按采样率上传。

## 与现有事件系统的关系

| 能力 | AgentEvent | LangSmith |
| --- | --- | --- |
| 前端进度展示 | 主来源 | 不直接使用 |
| SSE 输出 | 主来源 | 不直接使用 |
| checkpoint 恢复 | 主来源 | 不参与 |
| LLM prompt/debug | 弱 | 主来源 |
| trace tree | 弱 | 主来源 |
| 工具副作用审计 | 结构化 payload，待落库 | 可辅助排查 |
| eval 样本沉淀 | 可提供业务标签 | 主来源 |

两者应该互补，而不是互相替代。

## 参考

- LangSmith LangGraph observability: https://docs.langchain.com/oss/python/langgraph/observability
- LangSmith observability quickstart: https://docs.langchain.com/langsmith/observability-quickstart
- LangSmith custom instrumentation: https://docs.langchain.com/langsmith/annotate-code
- LangSmith environment variables: https://docs.langchain.com/langsmith/env-var
