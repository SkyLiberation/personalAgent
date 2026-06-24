# 工具层

优秀 Agent 的工具层不是把 API 暴露给模型，而是把模型的意图转换为可理解、可组合、可控、可观测的系统动作。

当前项目的工具层已经从“工具声明”推进到“轻量 Tool Runtime”：业务工具使用 LangChain `@tool` 生成标准 `BaseTool`，用显式 Pydantic `args_schema` 表达参数语义，用统一 artifact 承载业务结果，并通过 `ToolGovernance` 驱动 `ToolGateway` 执行 timeout、retry、rate limit、HITL、幂等和审计。幂等账本与工具审计已由 `PostgresToolGovernanceStore` 持久化到 Postgres，不再只是进程内记录。它不是裸露 API 集合，而是模型意图和真实系统副作用之间的执行边界。

一个重要边界是：**能作为 tool 的能力必须先是 service 能力**。Service 承担业务语义、状态变更、数据归属和领域不变量；Tool 只是在 service 外包一层 Agent 可调用的 schema、governance、artifact 和审计边界。不能为了让 Agent 调用而绕过 service 直接包 repository、store 或算法函数。

另一个重要边界是：**“走 ToolGateway 治理”不等于“允许 Agent 动态选择”**。当前工具通过 `ToolGovernance.exposure` 明确暴露范围：

| Exposure | 含义 | 是否可被 Agent 动态选择 | 典型例子 |
| --- | --- | --- | --- |
| `public_agent` | 公共 Agent 工具，可出现在默认动态工具面 | 是 | `graph_search`, `web_search`, `find_similar_notes`, `list_research_runs` |
| `scoped_agent` | 只在特定 workflow 的 scoped allowed tools 内动态选择 | 局部是 | `update_note`, `pause_research_subscription`, `retry_worker_task` |
| `workflow_activity` | 只由确定性 workflow step 调用，仍经过 ToolGateway 治理 | 否 | `delete_note`, `capture_text`, `research_collect_sources` |
| `admin` | 管理 / 运维工具，需要管理入口或更高权限 | 受限 | 预留 |

因此 `delete_note` 仍然是 tool，不是因为 Agent 需要动态选择它，而是因为删除长期知识必须经过统一治理边界：HITL、幂等、审计、策略拦截和恢复路径。但它的 exposure 是 `workflow_activity`，不会出现在 ReAct 默认/局部动态工具空间中。

## 设计目标

工具层需要同时满足两类要求：

- 对模型友好：工具名称、描述、参数 schema 要让模型知道何时调用、如何调用、不要在什么场景调用。
- 对系统可靠：工具执行必须有结构化输入输出、风险标记、确认机制、结果归属校验和可审计记录。

因此工具层的职责不是“替 Agent 思考”，而是限制和承接 Agent 的行动：

```text
Agent 决策层
    ↓
计划 / ReAct 选择工具与参数
    ↓
ToolGateway / ToolExecutor
    ↓
业务工具
    ↓
Application / Domain Service
    ↓
结构化 artifact / evidence / HITL 状态
```

## 当前实现与能力

当前工具层可以按“声明 -> 校验 -> Gateway 执行 -> Artifact 返回 -> 编排隔离 / HITL -> 审计”的链路理解。它不是把 API 裸露给模型，而是用一组明确的模型与契约把模型意图转换成可控系统动作。

### 工具声明与注册

每个业务工具由 `build_*_tool()` 工厂创建，并统一使用 LangChain `@tool` 生成标准 `BaseTool`。工具声明时同时绑定 [显式 ArgsSchema](#显式-argsschema)、[ToolGovernance](#toolgovernance-治理契约) 和 `content_and_artifact` 返回协议。

工具工厂不应该承载业务流程本身。正确形态是：

```text
Tool ArgsSchema / description / governance
    ↓
Tool function: 参数归一、调用 service、包装 artifact
    ↓
Application Service: 业务规则、持久化、领域状态和协作对象
```

如果一个能力还没有 service 边界，应该先沉淀为 service 方法，再判断是否需要包成 tool。

`ToolExecutor` 负责注册和查询 `BaseTool`，并持有统一 [ToolGateway](#toolgateway-执行边界)。Agent 编排期不再自行编译工具子图；调试 API 和非编排同步入口也通过 `invoke_direct()` 进入同一个 Gateway。

| 工具 | 类型 | 用途 | 治理属性 |
| --- | --- | --- | --- |
| `capture_text` | 写 | 写入文字知识笔记 | `risk_level=low`, `side_effects=write_longterm`, `permission_scope=memory:write`, `timeout=60s`, `rate_limit=30/min` |
| `capture_url` | 外部读 | 提取链接正文 | `risk_level=low`, `side_effects=external_network`, `permission_scope=network:read`, `timeout=30s`, `max_retries=1`, `rate_limit=20/min` |
| `capture_upload` | 写 | 提取上传文件正文 | `risk_level=low`, `side_effects=write_longterm`, `permission_scope=memory:write`, `timeout=45s`, `rate_limit=20/min` |
| `graph_search` | 本地读 | 查询图谱知识 | `risk_level=low`, `side_effects=read_local`, `permission_scope=memory:read`, `timeout=15s`, `rate_limit=60/min` |
| `web_search` | 外部读 | 查询公网资料 | `risk_level=low`, `side_effects=external_network`, `permission_scope=network:read`, `timeout=20s`, `max_retries=1`, `rate_limit=30/min`, `allowed_domains` |
| `delete_note` | 删除 | 删除知识笔记 | `risk_level=high`, `requires_confirmation`, `side_effects=delete_longterm`, `permission_scope=memory:delete`, `idempotency_key_required`, `timeout=20s`, `rate_limit=10/min` |
| `restore_note` | 恢复 | 从删除快照恢复知识笔记 | `risk_level=high`, `requires_confirmation`, `side_effects=write_longterm`, `permission_scope=memory:write`, `idempotency_key_required`, `timeout=20s`, `rate_limit=10/min` |

新增工具面不再只围绕“采集 / 检索 / 删除”，而是覆盖跨 workflow 的业务动作和状态观察：

| 工具组 | 工具 | 用途 | 主要治理边界 |
| --- | --- | --- | --- |
| Research pipeline | `research_prepare_run`, `research_plan_queries`, `research_collect_sources`, `research_cluster_events`, `research_rank_events`, `research_compose_digest` | 将 Research 主链路拆成可 checkpoint、可审计、可恢复的 workflow 阶段 | `research_collect_sources` 声明 `external_network`; `research_rank_events` 声明 `read_longterm`; 阶段状态写入 Postgres Research store |
| Research 管理 | `list_research_subscriptions`, `update_research_subscription`, `pause_research_subscription`, `resume_research_subscription`, `run_research_subscription_now`, `list_research_runs`, `get_research_digest`, `submit_research_feedback`, `save_research_event` | 管理订阅、查看 run/digest、记录反馈、将事件入库 | 写入类为 `medium + write_longterm`; 查询类为 `read_longterm`; 入库走 `research:save` |
| 知识生命周期 | `list_recent_notes`, `get_note`, `find_similar_notes`, `update_note`, `supersede_note`, `mark_note_deprecated`, `mark_notes_conflicted` | 查询、修正、替换、标记过期或冲突，维护知识生命周期 | 查询类低风险；更新/版本关系类为 `medium + write_longterm` |
| 运行诊断 | `inspect_worker_queue`, `retry_worker_task` | 查看 durable worker 队列、重试 dead task | 查看为只读；重试为 `medium` |
| Workflow 诊断 | `inspect_workflow_run` | 查看 run snapshot、步骤状态和历史 | 只读诊断工具 |

这些工具的设计标准是“Agent 是否需要用它做业务决策”，而不是“某个函数是否能被封装”。URL 归一化、相似度计算、source priority 这类算法细节仍留在领域函数中，不进入公共工具面。

更完整的判断标准是：

1. 该能力先是清晰的 service 方法，而不是直接访问 store / repository / 内部算法。
2. 该能力是公共业务动作或状态观察，而不是只服务单个函数的实现细节。
3. Agent 需要在 workflow / ReAct / direct 调试入口中动态选择它。
4. 它需要权限控制、审计、审批、风险治理、限流、超时、幂等或跨用户归属校验。
5. 它的输入输出能稳定表达为 schema 和 artifact。

只有同时满足这些条件中的关键项，才值得在 service 外再包一层 tool。

### Scoped ReAct 与管理类 workflow

新增的 `manage_research`、`maintain_knowledge`、`inspect_operations`、`inspect_workflow` 不是把所有工具摊给全局 Agent，而是在 workflow 内配置 scoped allowed tools：

```text
manage_research
    allowed_tools = Research 订阅 / run / digest / feedback / save 工具

maintain_knowledge
    allowed_tools = 笔记查询 / 更新 / supersede / deprecated / conflicted 工具

inspect_operations
    allowed_tools = inspect_worker_queue / retry_worker_task

inspect_workflow
    allowed_tools = inspect_workflow_run
```

因此 Agent 的决策空间是分层的：全局路由选择业务 workflow，workflow 内部 ReAct 在局部工具箱里选择具体动作，真实执行仍统一经过 ToolGateway。

实现上，ReAct 的可用工具集合会先取 workflow step 的 `allowed_tools`，再与注册工具中 exposure 属于 `public_agent / scoped_agent / admin` 的集合求交集。`workflow_activity` 即使被误写进 `allowed_tools`，也不会进入 ReAct 可选集合。

### Research workflow pipeline

`research_once` 已不再是一个大号黑盒工具。当前主链路是：

```text
research_prepare_run
    ↓
research_plan_queries
    ↓
research_collect_sources
    ↓
research_cluster_events
    ↓
research_rank_events
    ↓
research_compose_digest
    ↓
research-compose
```

scheduled run 使用内部 `execute_research_run` workflow 复用已存在的 `ResearchRun.run_id`，所以外部 cron / durable worker 入队后也进入同一套阶段化 workflow。阶段之间只传 `run_id` / `max_items`，sources、events、digest 等大对象落在 Postgres Research store，避免 checkpoint 膨胀。

### 步骤投影校验

Agent 决策层会使用 workflow step projection 或进入 ReAct，选择工具和参数。但投影出的工具步骤不会直接执行。`StepProjectionValidator`（语义上是 StepProjectionValidator）会读取 [ArgsSchema](#显式-argsschema) 校验参数，读取 [ToolGovernance](#toolgovernance-治理契约) 校验风险等级、确认要求和 ReAct 调用边界。

这一步的价值是把 prompt 或 workflow projection 中的软规则变成硬边界。比如某个步骤把 `delete_note` 标成 `risk_level=low`，校验层会用工具声明期的真实治理契约发现风险不一致。

### Gateway 执行

通过校验后，工具调用进入 [ToolGateway](#toolgateway-执行边界)。Gateway 会结合 [ToolGatewayContext](#toolgatewaycontext-执行上下文) 判断调用来自 projected step、react 还是 direct，并读取 [ToolGovernance](#toolgovernance-治理契约) 中的策略字段，统一处理 ReAct allowlist、高风险拦截、幂等 key 抢占、timeout、retry、rate limit、异常收敛和审计落库。

这一步是项目区别于“裸工具列表”的关键：工具运行时安全策略不是靠 prompt 约束，也不是散落在每个业务函数里，而是在模型和真实系统之间形成统一执行边界。

### Artifact 返回

业务工具真正执行后，会返回统一 [Tool Artifact](#tool-artifact-返回契约)。成功、失败、证据和待确认状态都走 `ok / data / error / evidence`。编排层不需要理解每个工具的私有返回格式，只要消费这个稳定结构。

注意：artifact 是 tool 层协议，不是 service 层协议。Service 应返回领域对象、DTO 或 use case result；tool 负责把它转成 Agent 编排能消费的 artifact。

### 编排隔离与 HITL

工具结果不会直接进入用户可见的 `messages`，而是进入内部 `tool_messages`。系统通过 [ToolTrackingSubState](#tooltrackingsubstate-编排归属) 保存当前上下文、step id、tool call id、工具名、工具输入和 ReAct iteration，工具结果回来后必须完成归属校验。

高风险动作通过 [PendingConfirmation / IdempotencyKey](#pendingconfirmation--idempotencykey-hitl-契约) 走两阶段执行：第一次只生成确认 payload，用户确认后才带 `confirmed=True` 和 `idempotency_key` 执行真实副作用。

### 审计与可观测性

每次工具调用都会形成 [ToolInvocationEvent](#toolinvocationevent-审计模型)。审计事件会合并工具名、输入、输出、执行模式、step id、thread/user、风险等级、副作用、权限域、耗时、error_kind、attempts、timed_out、rate_limited 等字段。direct 调用和图执行期工具结果消费都会产出同一形状的审计 payload，并由 `PostgresToolGovernanceStore.record()` 写入 `tool_audit_events`。

## 核心模型与契约

### 显式 ArgsSchema

显式 Pydantic `ArgsSchema` 是工具参数语义契约。它比函数签名自动推导更适合 Agent 工具层，因为它能表达字段级 description、必填、默认值、长度和范围约束。

当前用途：

- Workflow step projection 和 ReAct prompt 可以展示工具参数说明。
- `StepProjectionValidator` 用 `args_schema.model_validate()` 做执行前校验。
- 未来接入模型原生 tool calling 时，可以直接作为更稳定的 tool schema。

典型例子是 `WebSearchArgs`：`query` 必填且非空，`limit` 被限制在 1-10，`scrape` 明确说明只有摘要不足时才使用。

### ToolGovernance 治理契约

`ToolGovernance` 是工具声明期固定下来的治理契约，通过 `extras.governance` 挂在 `BaseTool` 上。它不是给工具打标签，而是被 `StepProjectionValidator`、`ToolGateway` 和审计层共同消费。

| 能力 | 字段 | 当前用途 |
| --- | --- | --- |
| 暴露范围 | `exposure` | 区分 `public_agent / scoped_agent / workflow_activity / admin`；ReAct 动态工具选择会过滤掉 workflow-only 工具，确定性 workflow 仍可调用 activity 工具 |
| 风险分级 | `risk_level` | 区分 `low / medium / high` 工具；`StepProjectionValidator` 用它发现计划风险不一致，`ToolGateway` 用它阻止高风险工具进入 ReAct 自主执行 |
| 人工确认 | `requires_confirmation` | 标记工具是否必须走 HITL；`delete_note` 首次调用只返回确认 payload，确认后才允许真实执行 |
| 副作用建模 | `side_effects` | 标记 `read_local`、`external_network`、`write_longterm`、`delete_longterm`、`send_external`、`irreversible` 等副作用；ReAct 会阻断删除、外发、不可逆、高风险和需确认动作，scoped allowed tools 内的中风险写入可执行并被审计 |
| 权限域 | `permission_scope` | 标记工具所需权限，例如 `memory:read`、`memory:write`、`memory:delete`、`network:read`；当前进入审计和未来权限后端输入 |
| 幂等约束 | `idempotency_key_required` | 高风险确认执行时要求 `idempotency_key`；缺失会被 `ToolGateway` 拒绝；确认执行前通过 Postgres `INSERT ... ON CONFLICT DO NOTHING` 抢占 key，避免跨进程重复副作用 |
| 回滚声明 | `rollback_supported` | 标记工具是否支持回滚；当前进入审计，未来可连接删除前快照、软删除窗口或补偿动作 |
| 审计开关 | `audit_required` | 控制是否记录结构化 `tool.audit`；默认开启，避免工具调用只留下普通日志 |
| 超时策略 | `timeout_seconds` | `ToolGateway` 按工具配置执行超时控制，避免网络、图谱或存储异常拖住整条编排链路 |
| 重试策略 | `max_retries`、`retry_backoff_seconds` | `ToolGateway` 只对瞬时异常执行重试，并把尝试次数写入审计；业务失败 artifact 不再默认重试，避免重复副作用 |
| 限流策略 | `rate_limit_per_minute` | `ToolGateway` 按工具和用户维度限流，防止 ReAct 循环、外部网络搜索或调试 API 造成调用风暴 |
| 外部来源限制 | `allowed_domains` | 外部网络工具可声明允许访问的域名后缀；Gateway 校验入参 URL，`web_search(scrape=True)` 的结果正文抓取也复用同一判断，避免二次抓取绕过白名单 |

这些字段的消费路径是：

```text
工具声明 extras.governance
    ↓
StepProjectionValidator：计划级风险、参数和执行模式校验
    ↓
ToolGateway：运行时策略执行，包含 ReAct guard、确认幂等、timeout、retry、rate limit
    ↓
ToolInvocationEvent：结构化审计，记录风险、副作用、权限、耗时、错误分类、尝试次数、超时和限流结果
```

一个典型例子是 `delete_note`：它声明 `risk_level=high` 和 `requires_confirmation=True`，因此不能进入 ReAct 自主调用；声明 `side_effects=("delete_longterm",)`，步骤投影校验和 Gateway 都会把它视为真实长期副作用；声明 `idempotency_key_required=True`，确认执行时如果没有幂等 key，Gateway 会直接拒绝；声明 `permission_scope="memory:delete"`，审计事件会保留删除权限域；声明 `timeout_seconds=20.0` 和 `rate_limit_per_minute=10`，删除动作不会无限挂起，也不会被同一用户高频触发。确认执行后，底层不是物理删除，而是写入删除快照并软删除 note/chunk。

`restore_note` 是对应的恢复工具。它同样是高风险、要求确认和幂等 key，但副作用声明为 `write_longterm`，权限域为 `memory:write`。API 恢复入口不会直接改库，而是通过 `restore_note` 进入 ToolGateway，从 `knowledge_delete_snapshots` 恢复 note、chunk 和 review card。

### ToolGatewayContext 执行上下文

`ToolGatewayContext` 描述一次工具调用发生在什么执行场景中，是 Gateway 做策略校验和审计归因的输入。

核心字段：

- `execution_mode`：`deterministic`、`react` 或 `direct`。
- `tool_call_id`：当前工具调用的唯一标识，用于匹配 `tool_messages`。
- `step_id`：计划步骤 ID，用于审计和归属校验。
- `thread_id` / `user_id`：线程和用户归属，用于审计、限流和未来权限判断。
- `react_allowed_tools`：ReAct 当前步骤允许调用的工具集合。

因此，同一个工具在 direct、deterministic plan 和 ReAct 中会经过同一个 Gateway，但上下文不同，策略也不同。比如 `graph_search` 可以在 ReAct 中调用，`delete_note` 即使被模型选中，也会因为上下文是 react 且工具高风险 / 需要确认而被拒绝；`update_research_subscription` 这类中风险写入只有在对应管理 workflow 的 scoped allowed tools 内才可执行。

### Gateway 运行时策略

运行时策略由 `ToolGovernance` 字段声明，并在 `ToolGateway` 内部直接执行。当前已经落地：

- `timeout_seconds`：防止工具调用无限挂起。
- `max_retries` 与 `retry_backoff_seconds`：只处理瞬时异常，避免业务失败被误重放。
- `rate_limit_per_minute`：按工具和用户维度限流。
- `allowed_domains`：限制外部网络工具可访问的域名；既约束直接 URL 入参，也约束 `web_search(scrape=True)` 对搜索结果 URL 的二次抓取。
- 高风险确认执行时的 `idempotency_key` 校验与 Postgres 持久账本抢占。

策略命中结果会进入审计事件，例如 `error_kind`、`attempts`、`timed_out`、`rate_limited`，并随完整 `ToolInvocationEvent` 写入 `tool_audit_events`。

### ToolError / ToolErrorKind 错误分类

`ToolError` 是工具层的可解释异常，`ToolErrorKind` 用来区分错误是否可重试。当前 Gateway 会优先读取工具主动抛出的错误分类；如果是普通异常，则按异常类型做兜底分类。

当前分类价值：

- `transient`：网络抖动、临时不可用等可重试错误，Gateway 会按 `max_retries` 和 `retry_backoff_seconds` 重试。
- `validation`：参数、域名白名单、确认输入不完整等错误，不重试。
- `permission`：越权、高风险 ReAct、自主删除等策略拒绝，不重试。
- `timeout`：工具执行超过 `timeout_seconds`，进入审计并返回可解释失败。
- `rate_limited`：命中工具和用户维度限流，不重试。
- `business`：业务不可恢复失败，例如目标对象不存在，不重试。

这样做的重点不是让错误类型更多，而是让 Gateway 能把“应该重试的技术故障”和“不应该重复执行的业务/权限失败”分开。

### ToolGateway 执行边界

`ToolGateway` 是模型意图和真实系统副作用之间的统一执行边界。它集中处理工具查找、策略校验、参数注入、`tool.invoke()`、异常收敛、artifact 归一和审计记录。

专门设计这一层的原因是：service 只应该负责业务动作，权限、确认、限流、超时、重试、幂等和审计属于系统级能力，应该集中在模型和真实系统之间的边界层扩展。Tool 是 service 的 Agent-facing adapter，不是 service 的替代品。

### Tool Artifact 返回契约

`ToolArtifact` 是已落地的 Pydantic 模型，定义工具执行结果的统一结构。工具统一使用 `response_format="content_and_artifact"`：

- `content` 供 LangGraph/LangChain 消息流表达工具观察结果。
- `artifact` 保存业务结构化输出：`ok`、`data`、`error`、`evidence`。

```json
{
  "ok": true,
  "data": {},
  "error": null,
  "evidence": []
}
```

失败时 `ok=false`、`data=null`、`error` 存放可解释错误。编排层通过统一 artifact 维护计划进度、证据、失败恢复和 HITL 状态。Gateway 内部以 `ToolArtifact` 为类型源头，在进入 LangGraph state、日志或 HTTP 响应时序列化为 JSON-ready dict。

### ToolTrackingSubState 编排归属

`ToolTrackingSubState` 保存一次待处理工具调用的归属信息：

- `active_context`：当前是 plan 还是 react。
- `pending_step_id`：当前计划步骤。
- `pending_call_id`：当前工具调用 ID。
- `pending_tool_name` / `pending_tool_input`：审计时需要合并的工具名和输入。
- `pending_react_iteration`：当前 ReAct 轮次。

它和 `tool_messages` 配合，保证 checkpoint 恢复后不会把旧工具结果消费到新的步骤里。

### PendingConfirmation / IdempotencyKey HITL 契约

`PendingConfirmation` 表示工具已产生待确认动作，但真实副作用尚未执行。`delete_note` 的两阶段流程是：

1. 第一次调用仅返回待确认 payload。
2. `StepExecutionGraph` 将 payload 写入 checkpoint 的 `pending_confirmation`，并在确认节点暂停。
3. 用户确认后，同一工具在 `confirmed=True` 和 `idempotency_key` 输入下由 `step_tool_node` 执行删除。
4. `delete_note` 写入 `knowledge_delete_snapshots`，随后对 note/chunk 写入 `deleted_at` 等软删除字段；默认检索和复习查询会排除这些记录。
5. 需要恢复时，`restore_note(confirmed=True, idempotency_key=...)` 通过同一个 Gateway 从快照恢复 note、chunk 和 review card。

`idempotency_key` 由 thread/run/step 组合生成，用于避免用户重复确认、恢复重放或网络重试造成重复副作用。确认执行前，Gateway 调用 `IdempotencyStore.reserve()` 抢占 key；Postgres 实现会向 `tool_idempotency_ledger` 插入 `reserved` 行，成功抢占才继续执行副作用，失败会释放 reservation，成功才标记为 `committed`。

### ToolInvocationEvent 审计模型

`ToolInvocationEvent` 是已落地的 Pydantic 模型，也是 direct 调用和图执行期工具调用共用的结构化审计 projection。它不是普通日志字符串，而是稳定字段集合：

- 调用归因：`thread_id`、`run_id`、`user_id`、`step_id`、`execution_mode`、`tool_call_id`。
- 工具输入输出：`tool_name`、`input`、`output`、`artifact_ok`、`error`、`evidence`。
- 治理属性：`risk_level`、`requires_confirmation`、`confirmed`、`side_effects`、`permission_scope`、`idempotency_key_required`、`side_effect_id`。
- 策略结果：`latency_ms`、`attempts`、`timed_out`、`rate_limited`、`timeout_seconds`、`max_retries`。
- 错误分类：`error_kind`，用于区分 transient、validation、permission、timeout、rate_limited 和 business。
- Trace 关联：`langsmith_run_id`。

写入 `tool_audit_events` 时，`run_id`、`confirmed`、`risk_level`、`side_effect_id`、`error`、`latency_ms`、`attempts` 等被提升为一等列以便索引和过滤；完整 payload 仍以 JSONB 保留，查询时按调用方权限脱敏。

Gateway 和图执行节点以 `ToolInvocationEvent` 为类型源头，在写入日志、事件 payload 和 `tool_audit_events` 时使用 `model_dump(mode="json")` 序列化。业务审计查询以 Postgres 审计表为准，LangSmith run id 作为调试 trace 关联字段。

## Model / Layer 依赖类图

这张图描述“工具层如何消费模型与治理契约”，不是 Python 继承关系。为表达分层，沿用 [capture-ask-model-flow.md](../workflow/capture-ask-model-flow.md) 的约定：

- 蓝色节点是处理层。
- 白色节点是已落地的模型 / 契约。
- 绿色节点是已落地、被多层共同消费的审计 projection。
- 黄色虚线节点是尚未落地的未来回滚模型。

关键边界需要特别明确：

- `ToolGovernance` 是工具声明期就固定下来的治理契约（`extras.governance`），被策略校验层和审计层共同消费，而不是执行期临时计算。
- 显式 Pydantic `ArgsSchema` 是工具参数语义契约，被 Planner / ReAct prompt 展示、`StepProjectionValidator` 执行前校验和未来模型原生 tool calling 共同消费。
- timeout、retry、rate limit 等运行时策略不是独立模型，而是 `ToolGovernance` 字段在 `ToolGateway` 内部的执行逻辑；策略命中结果会进入审计 projection。
- `ToolError / ToolErrorKind` 是已落地的错误分类契约，Gateway 用它判断是否重试，并把分类结果写入审计 projection。
- `ToolGatewayContext` 承载一次调用的执行模式与归属信息（plan / react / direct），是策略校验和审计归因的输入。
- `ToolArtifact`（`ok/data/error/evidence`）是已落地的工具返回模型，HITL 暂停、审计 payload 和编排进度都基于它。
- `ToolInvocationEvent` 是已落地的审计模型，Gateway 直接调用与图执行期消费节点共用它生成审计 projection，包含 error_kind、attempts、timed_out、rate_limited 等策略结果，并由 Postgres 审计表持久化。

图源见：[Tools Model / Layer 依赖类图](../mermaid/tools-model-layer-dependencies.md)。

## 与优秀 Agent 工具层的对照

| 维度 | 优秀 Agent 工具层 | 当前项目状态 |
| --- | --- | --- |
| 工具抽象 | 暴露 service-backed 的任务语义工具，而不是裸 API、数据库操作或算法函数 | 已按业务动作封装为 `capture_*`、`graph_search`、`web_search`、`delete_note`、Research pipeline / 管理、知识生命周期和诊断工具 |
| 输入契约 | 使用结构化 schema，参数少而明确，可在执行前校验 | 已使用 Pydantic schema，并由 `StepProjectionValidator` 校验计划参数 |
| 输出契约 | 返回稳定机器可读结构，失败可解释，证据可追踪 | 已统一为 `ok / data / error / evidence` artifact |
| 读写分层 | 读工具低风险开放，写工具标记副作用并受控执行 | 已用 `ToolGovernance.side_effects`、`risk_level`、`permission_scope` 表达读写和权限边界 |
| 高风险治理 | 删除、外发、付款、生产变更等需要确认、审计、幂等和回滚 | `delete_note` 已实现确认暂停；其他高风险类别目前尚未出现 |
| 执行隔离 | 内部工具消息不污染用户会话，可恢复后精确归属 | 已通过 `tool_messages` 与 pending id 做隔离和归属校验 |
| 自主探索限制 | ReAct 只能调用允许列表内工具，并限制迭代；写入需受 scoped workflow 和治理约束 | 已禁止高风险/需确认/删除/外发/不可逆工具进入 ReAct；管理类 workflow 允许 scoped 中风险写入并审计 |
| 观测审计 | 每次调用记录工具名、输入、输出、耗时、错误、用户/线程/副作用 id | 已提供 `tool_invocation_event()` 统一事件形状，direct 调用和图执行期工具结果都会产出审计 payload |
| 工具描述质量 | 描述包含使用时机、禁用场景、副作用和返回解释 | 当前工具描述已补充主要副作用和禁用场景，后续可继续按业务演进细化 |
| Tool Gateway | 在模型与真实系统之间集中处理权限、速率、确认、重试、幂等、审计 | 已引入轻量 `ToolGateway`，集中执行 timeout、retry、rate limit、高风险确认幂等和审计；权限后端和审计落库仍可继续扩展 |

## 主要差距

当前实现已经能支持个人知识 Agent 的核心工具调用，也已经具备轻量 Tool Runtime 的雏形。Research、知识生命周期、后台任务和 workflow 诊断已进入工具面。距离成熟生产级工具层，主要差距不在“能不能调工具”，而在治理能力是否能跨进程、跨用户、跨工具类型持续生效：

1. 权限判断还没有后端化

   `permission_scope` 已经进入 `ToolGovernance` 和审计事件，并由 `PolicyEngine` 统一处理入口、记忆和工具调用的 allow / deny / require confirmation。下一步需要继续细化到更强的用户、线程、客户端来源、工具名、参数和副作用组合策略。

2. 审计查询与脱敏能力已产品化，互链仍可继续收敛

   当前 `tool_invocation_event()` 已定义统一事件形状并写入 `tool_audit_events`，审计查询 API、字段级脱敏、高风险确认上下文、指标告警和策略决策落库均已落地（见 P1）。后续可继续收敛业务对象 ID、回滚记录与 LangSmith trace 之间的细粒度互链。

3. 幂等账本已持久化，但事务边界仍可继续收敛

   `delete_note` 确认执行路径已经要求 `idempotency_key`，Gateway 也会用 Postgres `tool_idempotency_ledger` 在副作用前抢占 key。当前语义已经覆盖重启、横向扩容和 checkpoint 重放下的重复执行防护；后续可继续把更多写入类工具纳入同一幂等契约，并在业务副作用与 ledger 之间收敛更强的事务边界。

4. 回滚与补偿策略还没有形成通用模型

   `rollback_supported` 已经是治理契约字段，但当前更多用于声明和审计。后续可以为删除、写入、外发等副作用工具分别建立默认策略，例如删除前快照、软删除窗口、补偿动作和人工恢复入口。

5. 工具质量还缺少评测闭环

   当前工具 schema、description 和 Gateway 策略已经能支撑主流程，但还没有系统化评估工具选择准确率、参数生成准确率、高风险误调用率、ReAct 越权拦截率和外部网络失败率。生产化工具层需要用 eval 证明治理策略确实有效。

## 按优先级排序的演进建议

当前工程已经完成了工具层的“可控执行边界”：schema、governance、Gateway、HITL、错误分类、运行时策略和审计 projection。下一阶段的优先级应该从“工具能安全跑起来”转向“工具治理能生产化运行”。

### P0：接入真实权限后端

当前 `permission_scope` 已经进入 `ToolGovernance` 契约和审计事件，但主要还是声明与记录。最高收益的下一步是把 Gateway 的 policy validate 接入真实权限后端：

- 用户级权限。
- workspace / tenant 权限。
- 工具级 allow / deny。
- 外部网络访问权限。
- 写入、删除、外发等副作用权限。
- 不同客户端来源的权限差异，例如 Web、飞书、调试 API。

目标是让 Gateway 输入用户、线程、工具、参数、副作用类型，输出 allow / deny / require confirmation / require escalation。这样 `risk_level`、`permission_scope` 和 `side_effects` 就不只是治理元数据，而是能真正驱动授权决策。

### P1：把审计事件升级为审计系统 **已落地**

当前 `ToolInvocationEvent` 已经把工具调用从日志字符串升级成结构化审计模型，并已由 `PostgresToolGovernanceStore` 写入 `tool_audit_events`。在已落库基础上现已补齐：

- 工具调用历史查询：`GET /api/audit/events`（按 user/tool/thread/run/risk/mode/side_effect/时间范围过滤）。
- 输入 / 输出脱敏：`storage/audit_redaction.py` 默认掩码用户内容，仅管理员 key 可 `reveal=true`。
- 失败率、删除失败率、高风险调用数、重复 idempotency、策略拒绝数等指标与阈值告警：`GET /api/audit/metrics`。
- 高风险操作的确认上下文：`tool_audit_events` 提升 `confirmed`、`run_id`、`side_effect_id` 等一等列，配合幂等账本 confirmer/committed_at 回答“谁何时确认了什么”。
- 按 idempotency key 追踪调用生命周期：`GET /api/audit/events/by-idempotency/{key}`（账本 + 审计事件）。
- 策略决策落库：gateway 与 facade 两条路径经 `set_policy_decision_sink` 写入 `tool_policy_decisions`，可经 `GET /api/audit/policy-decisions` 查询。
- LangSmith trace 与业务审计记录之间通过 `langsmith_run_id` 互链。

这一步把“可观测”从开发调试能力提升为生产治理能力。

### P2：扩展幂等覆盖面和回滚记录

当前高风险确认路径已经要求 `idempotency_key`，Gateway 也有 Postgres 持久幂等账本。下一步应把这套能力扩展到更多写入类工具，并补齐回滚记录：

- 更多写入类工具接入幂等 key，尤其是 Research 投递、worker retry、知识版本关系更新等可重复触发动作。
- 工具副作用对象 ID 记录。
- 删除前快照或软删除记录。
- 回滚 / 补偿动作状态。
- 重放、恢复、重复确认时的可解释提示。

这一步能把“高风险动作需要确认”进一步提升为“高风险动作可恢复、可追踪、可防重”。

### P3：补充熔断和外部来源治理

当前 `allowed_domains` 已经限制 Gateway 直接 URL 入参，也限制 `web_search(scrape=True)` 对搜索结果 URL 的二次抓取。下一步可以继续强化外部网络工具：

- 按域名、provider、用户维度做 circuit breaker。
- 区分搜索、抓取、下载等不同外部访问类型。
- 记录被白名单拒绝的 URL 和原因。
- 对外部结果建立来源可信度和证据引用规则。
- 对限流、超时、被拒绝访问给出不同恢复建议。

### P4：持续升级 ArgsSchema 和工具描述

当前业务工具已经使用显式 Pydantic args schema，并把 description 从简单功能说明升级为更接近模型操作手册的写法。后续可以持续补齐：

- 什么时候使用。
- 什么时候不要使用。
- 必填参数如何选择。
- 枚举、范围、长度、默认值。
- 返回 artifact 中哪些字段可作为后续步骤依据。
- 失败后是否可重试。
- 是否访问外部网络。
- 是否写入长期记忆。
- 是否需要用户确认。

`@tool` 的 description 会进入 Planner 和 ReAct prompt，后续如果接入模型原生 tool calling，也会直接影响模型选工具质量。因此 description 质量本身就是工具层能力的一部分。

### P5：选择性接入模型原生 Tool Calling

当前工程主要采用“Planner 输出 JSON 计划 -> 系统解析 -> Gateway 执行工具”的路线。这条路线可控性强，但还没有充分利用 `BaseTool` 可以直接绑定到模型工具调用的能力，例如：

```python
llm.bind_tools(tools)
```

接入模型原生 tool calling 后，可以获得：

- 参数结构由模型 API 的 tool call 协议约束。
- tool call 和普通文本回答边界更清晰。
- 多工具调用、并行工具调用和调用追踪更标准化。
- 减少自定义 JSON parser 的脆弱性。

但这不应该替代 `ToolGateway`。更合理的演进方式是：简单只读检索任务可以尝试走原生 tool calling，高风险写入 / 删除 / 外发动作仍然必须经过 Gateway、HITL、幂等和审计。

### P6：评估是否复用标准 ToolNode / Middleware

当前项目自建 `ToolGateway.invoke_graph`，是因为标准工具节点无法直接满足风险治理、HITL、幂等、审计和归属校验。但随着 Gateway 能力稳定，可以评估是否把它拆成更接近生态标准的形态：

- 标准 `ToolNode` 负责基础工具执行。
- Gateway 前置 middleware 负责 policy validate。
- Gateway 后置 middleware 负责 artifact 标准化和 audit。
- 项目仍保留 `tool_messages` 隔离、pending id 归属校验和 checkpoint 恢复逻辑。

这样可以降低自定义图节点的维护成本，同时保留项目自己的治理边界。

### P7：建立工具调用评测闭环

当前已有工具 schema、artifact、治理属性和高风险路径的单元测试。下一步可以补充 Agent 工具层特有的评测：

- 工具选择准确率 eval，特别是 scoped workflow 内的 Research 管理、知识维护和运维诊断工具选择。
- 参数生成准确率 eval。
- 高风险工具误调用率。
- ReAct 越权调用拦截率，以及 scoped 中风险写入的误调用率。
- artifact schema 稳定性测试。
- 工具 description A/B test。
- 外部网络工具失败率和超时率统计。

这一步能证明工具层不是只靠代码约束，而是有持续评估和迭代机制。

## 面试讲解口径

面试时不要把工具层讲成“我封装了几个工具”，而要讲成：

> 我把工具层设计成 Agent 行动的安全执行边界，而不是 API 列表。模型可以提出意图，但真正触碰存储、网络和删除动作前，必须经过显式 schema、治理元数据、执行网关、HITL 和审计；同时 timeout、retry、rate limit 这些运行时策略也由工具契约驱动，而不是散落在业务函数里。

可以按四层来讲：

1. Service-backed 工具声明层

   每个业务工具统一使用 LangChain `@tool` 生成标准 `BaseTool`，但不是裸函数暴露。能成为 tool 的能力应先经过 service；工具声明层只负责显式 Pydantic `args_schema`、操作手册式 description、`content_and_artifact` 结构化返回，以及 `ToolGovernance` 治理元数据。这里声明的不只是风险等级和副作用，还包括 timeout、retry、rate limit、allowed domains、是否需要确认、是否要求幂等 key。

   这层的价值是复用 `BaseTool` 的 name、description、args schema、标准 invoke 和 artifact 协议，同时把项目自己的治理契约绑定到工具对象上。

2. 执行前校验层

   `StepProjectionValidator` 会直接读取注册表中的工具 schema 和 governance，阻止未知工具、参数不合法、高风险 ReAct、自主删除等问题。也就是说，LLM 生成的计划不会直接执行，而是先经过系统级契约校验。

3. 统一执行网关层

   无论是 LangGraph 编排里的工具调用，还是调试 API 的 direct invoke，都会走同一个 `ToolGateway`。Gateway 集中处理 ReAct allowlist、高风险策略、幂等校验、timeout、retry、rate limit、artifact 归一和审计事件记录。

   这一步是项目区别于“裸工具列表”的关键：工具的运行时安全策略不是靠 prompt 约束，也不是写在每个业务函数里，而是在模型和真实系统之间形成统一执行边界。

4. 编排隔离与恢复层

   工具结果不会直接污染用户对话历史，而是进入 `tool_messages`。系统通过 `pending_tool_call_id`、`pending_step_id`、`pending_react_iteration` 做结果归属校验，避免恢复 checkpoint 后消费到旧 artifact。`delete_note` 这类高风险动作采用两阶段执行：第一次只生成确认 payload，用户确认后才带 `confirmed=True` 和 `idempotency_key` 真实执行。

这个项目工具层最值得强调的亮点有：

- 工具不是函数，而是受治理的系统能力。
- 复用 LangChain `BaseTool` 工具协议，但执行边界收敛到项目自己的 `ToolGateway`。
- 显式 Pydantic `args_schema` 提供字段级描述和范围约束，提升模型参数生成质量，也让步骤投影校验能阻断无效调用。
- `ToolGovernance` 不只做审计标签，还驱动 timeout、retry、rate limit、外部域名白名单、高风险确认和幂等校验。
- ReAct 自主探索和确定性计划分权；高风险、需确认、删除、外发和不可逆动作不能被自主探索路径直接执行，中风险写入必须处在 scoped workflow allowed tools 内。
- `delete_note` 采用两阶段执行：第一次只返回确认 payload，用户确认后才带 `confirmed=True` 和 `idempotency_key` 执行软删除并写入删除快照。
- 审计不是日志字符串，而是结构化 projection，包含工具名、输入、输出、风险等级、副作用、权限域、耗时、尝试次数、是否超时、是否限流、线程和用户归属。

面试中需要注意边界表述：

- 可以说“已有轻量 Tool Gateway，并已落地 timeout、retry、rate limit、幂等校验和审计”，不要说“完整生产级权限系统已落地”。
- 可以说“已有结构化审计事件、Postgres 独立审计表，以及查询 API、字段级脱敏、指标告警和策略决策落库”，审计查询能力已产品化；可继续收敛与业务对象 ID、回滚记录的细粒度互链。
- 可以说“确认机制、软删除快照和 `restore_note` 恢复已在删除场景落地”，不要说“所有高风险工具都有完整回滚能力”。
- 可以说“幂等 key 校验和 Postgres 持久账本已覆盖确认执行路径”，不要说“所有写操作都已完整幂等”。
- 可以说“显式 args schema 已覆盖当前业务工具”，不要说“已经接入模型原生 tool calling”。

最适合收尾的一句话：

> 我这个工具层真正想解决的不是“让模型能调工具”，而是“让模型调工具之后，系统仍然可控、可恢复、可审计”。我复用了 `BaseTool` 的标准协议，但把真正生产化需要的策略收敛在自己的 Gateway 里，这也是我认为 Agent 工程里最容易被低估、但最接近生产化的一层。
