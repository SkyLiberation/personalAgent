# Workflow 平台化优化设计

本文设计一个不考虑向后兼容的目标形态：把当前 `WorkflowSpec + LangGraph StepExecutionGraph` 提升为接近优秀 workflow 平台的能力集合。参考对象包括：

- LangGraph：durable execution、streaming、human-in-the-loop、persistence。
- Temporal：durable execution、event history、workflow/activity、长事务恢复。
- Prefect：flow/task、event、automation、deployment。
- Airflow：DAG、asset-aware/event-driven scheduling、数据资产编排。

本文不是短期改造清单，而是目标架构蓝图。允许重命名模型、重建状态表、替换当前 run context 机制，并继续把已 step 化的 workflow 扩展为完整平台能力。

## 目标

目标不是再写一个通用 Temporal，而是在个人知识库 Agent 场景内实现这些平台级能力：

```text
Versioned Workflow Definition
  -> Durable Workflow Execution
  -> Durable Step / Activity History
  -> Worker Queue / Backpressure
  -> Event / Asset Trigger
  -> HITL / Policy Gate
  -> Tool Boundary / Idempotency
  -> Observability / Replay / Fork
  -> Evaluation Gate
  -> Deployment / Version Migration
```

一句话：**把当前“请求内 LangGraph 编排”升级为“持久化、事件驱动、可重放、可演进的 workflow 平台”。**

## 当前差距

当前工程已有很好的基础：

- `WorkflowSpec / WorkflowRegistry` 是固定业务流程真源。
- `WorkflowStepProjector` 确定性投影 `ExecutionStep`。
- `capture_* / ask / summarize_thread / delete_knowledge / solidify_conversation / direct_answer` 已进入 `StepExecutionGraph`。
- LangGraph 已用于 checkpoint、interrupt/resume、ReAct 子图和事件流。
- ToolGateway 统一治理工具调用。

但与优秀 workflow 平台相比，主要差距是：

| 维度 | 当前状态 | 目标状态 |
| --- | --- | --- |
| Durable execution | LangGraph checkpoint 保存主状态，但部分大对象仍在内存 | 所有关键 step input/output/event 都持久化，可从任意 step 恢复 |
| Activity history | 有 `AgentEvent`，但不是完整 event-sourced history | 每个 workflow/step/activity 都有不可变事件历史 |
| Worker queue | 请求内同步执行为主，graph sync 半后台化 | 所有耗时/副作用 step 进入 queue，由 worker 执行 |
| Backpressure | 靠同步路径和局部 budget | 队列级并发、优先级、速率限制、dead letter |
| Versioning | `WorkflowSpec.version="v1"`，但缺版本迁移 | workflow definition 版本化，新旧 run 可并存 |
| Workflow 覆盖 | capture/summarize/direct answer 已 step 化，`unknown` 仍是 fallback branch | 所有业务 workflow 都 step 化，只是 UI 展示粒度可配置 |
| HITL | 删除确认已接入 LangGraph interrupt | HITL 是通用 gate，可用于任意 step/tool/quality review |
| Replay/Fork | 可导出 checkpoint，但重放能力有限 | 支持从任意历史点 fork、dry-run、replay with patched spec |
| Evaluation gate | evals 存在，但不是发布门禁 | workflow/prompt/model/tool 改动必须过 eval gate |
| Event trigger | 以用户 entry 驱动为主 | 用户 entry、note created、graph sync pending、review due 都是事件 |

## 目标架构

```text
API / Feishu / CLI / Scheduler / Webhook
  -> WorkflowTrigger
  -> WorkflowRuntime.start_or_signal()
  -> WorkflowExecutionStore
  -> DurableGraphEngine
  -> Step Scheduler
  -> Worker Queue
  -> Activity Worker
  -> ToolGateway / ModelGateway / HumanGate
  -> EventLog + SnapshotStore + ArtifactStore
  -> Observability / Replay / Eval
```

核心变化：

1. workflow 不再只是 entry 请求里的一个分支，而是系统级一等对象。
2. step 不再只是前端展示状态，而是 durable activity 的调度单元。
3. checkpoint 不再只保存当前状态，还要配合不可变 event log。
4. 大对象不再放内存 store，而是进入 artifact store。
5. 所有副作用必须通过 activity boundary 执行。

## 核心模型

### WorkflowDefinition

替代当前 `WorkflowSpec` 的目标模型。

```python
class WorkflowDefinition:
    workflow_id: str
    version: str
    intent: str
    trigger_schema: dict
    state_schema: dict
    steps: list[StepDefinition]
    edges: list[WorkflowEdge]
    policies: WorkflowPolicies
    outputs: list[OutputDefinition]
```

关键要求：

- `workflow_id + version` 不可变。
- 已经有运行实例引用的 definition 不允许原地修改。
- 新版本通过新 definition 注册。
- 每个 step 有稳定 step key，支持历史回放和版本迁移映射。

### StepDefinition

替代当前 `WorkflowStepSpec`。

```python
class StepDefinition:
    step_id: str
    kind: "activity" | "decision" | "human_gate" | "subworkflow" | "react_loop"
    activity_type: str
    input_mapping: dict
    output_mapping: dict
    retry_policy: RetryPolicy
    timeout_policy: TimeoutPolicy
    idempotency_policy: IdempotencyPolicy
    risk_policy: RiskPolicy
    cache_policy: CachePolicy
    resource_policy: ResourcePolicy
```

关键变化：

- `action_type` 升级成 `kind + activity_type`。
- input/output 显式映射，不靠节点内部临时注入。
- retry/timeout/idempotency/resource 不再散落在 ToolGateway 或节点代码里。
- ReAct 是一种 `react_loop` step，不是隐藏在普通 step 里的特殊分支。

### WorkflowExecution

运行实例。

```python
class WorkflowExecution:
    execution_id: str
    workflow_id: str
    workflow_version: str
    run_id: str
    thread_id: str
    status: "queued" | "running" | "waiting" | "completed" | "failed" | "cancelled"
    current_step_ids: list[str]
    input_artifact_id: str
    output_artifact_id: str | None
    created_at: datetime
    updated_at: datetime
```

### StepExecution

每个 step 的 durable runtime state。

```python
class StepExecution:
    execution_id: str
    step_id: str
    step_source: "workflow_definition" | "dynamic_plan"
    plan_id: str | None
    attempt: int
    status: "queued" | "running" | "waiting" | "completed" | "failed" | "skipped"
    input_artifact_id: str
    output_artifact_id: str | None
    error_artifact_id: str | None
    worker_id: str | None
    started_at: datetime | None
    completed_at: datetime | None
```

### WorkflowEvent

不可变事件流。

```python
class WorkflowEvent:
    event_id: str
    execution_id: str
    step_id: str | None
    type: str
    payload_artifact_id: str | None
    timestamp: datetime
    sequence: int
```

事件例子：

- `workflow.started`
- `plan.generated`
- `plan.admitted`
- `plan.rejected`
- `step.scheduled`
- `step.started`
- `activity.completed`
- `tool.called`
- `human_gate.requested`
- `human_gate.resumed`
- `step.failed`
- `workflow.completed`
- `workflow.forked`
- `workflow.replayed`

### ArtifactStore

专门保存大对象：

- ask 的 `ContextPack`
- evidence pool
- retrieval candidates
- prompt input/output
- tool raw result
- uploaded file extraction result
- graph sync result
- verifier report

当前 `AskRunContextStore` 应被替换为 durable artifact store。

```text
ArtifactStore
  artifact_id
  kind
  content_json / blob_ref
  content_hash
  redaction_policy
  created_at
```

## Dynamic Plan 接入

目标平台必须预留 dynamic plan 的接入能力。固定 workflow 和动态 plan 的区别只在**步骤来源**，不在执行治理。

```text
固定 workflow:
  WorkflowDefinition(versioned)
    -> StepDefinition[]
    -> StepExecution(step_source="workflow_definition")

动态 plan:
  Planner output
    -> DynamicPlan
    -> PlanAdmission
    -> admitted StepDefinition-like projection
    -> StepExecution(step_source="dynamic_plan")
```

也就是说，后续 plan 生成的 step 不应另起一套执行器，而应接入同一套：

- durable artifact store
- immutable event log
- worker queue
- activity boundary
- policy gate
- HITL
- replay / fork
- observability
- eval gate

### DynamicPlan

```python
class DynamicPlan:
    plan_id: str
    execution_id: str
    planner_name: str
    planner_version: str
    goal: str
    constraints: dict
    proposed_steps: list[PlanStep]
    created_from_artifact_id: str
```

`DynamicPlan` 是 planner 的原始产物，需要作为 artifact 持久化。它不能直接执行。

### PlanStep

```python
class PlanStep:
    step_id: str
    kind: "activity" | "decision" | "human_gate" | "subworkflow" | "react_loop"
    activity_type: str
    description: str
    depends_on: list[str]
    input_mapping: dict
    expected_output_schema: dict
    risk_level: "low" | "medium" | "high"
    allowed_tools: list[str]
    budget: dict
```

`PlanStep` 字段应尽量对齐 `StepDefinition`，但要保留 `planner_name / planner_version / goal / constraints` 等 provenance 信息，方便审计和回放。

### PlanAdmission

动态 plan 必须经过 admission，类似 Kubernetes admission controller 或当前 `StepProjectionValidator` 的增强版。

```text
DynamicPlan
  -> schema validation
  -> dependency validation
  -> cycle detection
  -> tool allowlist validation
  -> risk policy validation
  -> budget validation
  -> data access validation
  -> side-effect validation
  -> HITL injection
  -> admitted step projection
```

Admission 的输出只有两种：

```text
plan.admitted
  -> schedule admitted steps

plan.rejected
  -> return clarification / safe fallback
```

关键规则：

- 高风险业务流程仍优先使用固定 `WorkflowDefinition`，例如 `delete_knowledge`、长期写入、批量删除。
- dynamic plan 默认只能使用低风险、只读或可补偿 activity。
- dynamic plan 要调用写操作时，必须自动插入 `human_gate`。
- dynamic plan 不能绕过 ToolGateway / ModelGateway / StorageGateway。
- dynamic plan 的每个 step 都必须有 budget 和 timeout。
- dynamic plan 的输入、输出和 planner 原始响应都必须进入 artifact store。

### 适用场景

dynamic plan 适合低风险、开放式、工具范围明确的任务：

```text
整理最近三篇笔记并生成复习建议
比较多个主题下的观点差异
找出可能过期的知识并生成候选列表
围绕某个主题生成学习路径
从知识库中提取未完成行动项
```

不适合默认替代固定 workflow：

```text
delete_knowledge
solidify_conversation 的长期写入主干
capture 的持久化入库主干
权限、删除、批量写入、外部发送等高风险动作
```

### 与 WorkflowDefinition 的关系

dynamic plan 可以作为三种形态存在：

| 形态 | 说明 |
| --- | --- |
| `ad_hoc_plan` | 一次性 plan，仅绑定当前 execution |
| `plan_as_subworkflow` | 固定 workflow 中某个 step 调用 planner，admission 后作为 subworkflow 执行 |
| `promoted_workflow` | 多次验证稳定后，把 dynamic plan 固化成新的 `WorkflowDefinition` |

最后一种很关键：dynamic plan 不只是运行时能力，也可以成为发现新固定 workflow 的来源。稳定、高频、低失败率的 dynamic plan 应被提升为 versioned workflow definition。

## 执行引擎

目标执行引擎分两层：

```text
Workflow Engine
  负责 definition、edges、state、事件、HITL、调度

Activity Worker
  负责具体 activity：capture_url、chunk、retrieve、compose、verify、delete_note、graph_sync
```

### Workflow Engine 职责

- 创建 `WorkflowExecution`。
- 读取 `WorkflowDefinition`。
- 根据 edges 计算可运行 step。
- 写入 `step.scheduled` 事件。
- 把 activity step 投递到 worker queue。
- 对 human gate step 发出 pending approval。
- 对 completed/failed step 做状态推进。
- 汇总最终 output。

### Activity Worker 职责

- 从 queue 拉取 `StepExecution`。
- 加载 input artifact。
- 执行 activity。
- 写 output artifact。
- 写 activity event。
- 按 retry/timeout/idempotency policy 汇报状态。

这会把当前 `_node_execute_step()` 中的大量同步分发逻辑拆开，让请求线程不再背负长耗时执行。

## 队列与 Worker

目标队列至少分四类：

| Queue | 任务 | 特征 |
| --- | --- | --- |
| `interactive` | ask-compose、direct-answer、低延迟用户请求 | 高优先级、短 timeout |
| `retrieval` | ask-retrieve、多源检索、rerank | 中高优先级、可并发 |
| `ingestion` | capture chunk、写库、review card | 中优先级、可重试 |
| `graph` | Graphiti sync、graph quality check | 低优先级、强 backpressure |

队列能力：

- per-user concurrency limit
- per-tool rate limit
- priority
- delayed retry
- exponential backoff
- dead letter
- lease timeout
- worker heartbeat

## 所有 Workflow Step 化

当前业务 branch 已基本取消，capture/summarize/direct_answer 已进入 step projection。下一步是不考虑兼容性地继续细化为 durable steps：把正文提取、去重、写 parent note、partition、chunk materialize、review、graph sync 都拆成可单独恢复和重试的活动；展示层可以按需折叠。

### capture_text

```text
cap-1 normalize-source
  -> cap-2 dedupe-source
  -> cap-3 create-parent-note
  -> cap-4 partition-document
  -> cap-5 materialize-chunks
  -> cap-6 link-related-notes
  -> cap-7 schedule-review
  -> cap-8 enqueue-graph-sync
  -> cap-9 compose-capture-result
```

### capture_link

```text
link-1 extract-url
  -> link-2 fetch-url
  -> cap-2 dedupe-source
  -> cap-3 create-parent-note
  -> cap-4 partition-document
  -> cap-5 materialize-chunks
  -> cap-6 link-related-notes
  -> cap-7 schedule-review
  -> cap-8 enqueue-graph-sync
  -> cap-9 compose-capture-result
```

### capture_file

```text
file-1 resolve-upload
  -> file-2 extract-file-content
  -> file-3 partition-native-document
  -> cap-2 dedupe-source
  -> cap-3 create-parent-note
  -> cap-5 materialize-chunks
  -> cap-6 link-related-notes
  -> cap-7 schedule-review
  -> cap-8 enqueue-graph-sync
  -> cap-9 compose-capture-result
```

### ask

```text
ask-1 build-query-context
  -> ask-2 plan-retrieval
  -> ask-3 retrieve-local
  -> ask-4 retrieve-graph
  -> ask-5 retrieve-web?
  -> ask-6 merge-evidence
  -> ask-7 enrich-candidates
  -> ask-8 rerank-context
  -> ask-9 compose-answer
  -> ask-10 verify-answer
  -> ask-11 retry-or-web-fallback?
  -> ask-12 finalize-answer
```

当前 `ask-retrieve` 可以拆细，因为目标平台有 queue 和 artifact store 后，不再需要把一长段重活塞进一个 step。

### delete_knowledge

```text
del-1 retrieve-candidates
  -> del-2 resolve-target
  -> del-3 human-confirm-delete
  -> del-4 delete-note
  -> del-5 enqueue-graph-delete-sync
  -> del-6 compose-delete-result
```

### solidify_conversation

```text
sol-1 select-dialogue-range
  -> sol-2 draft-knowledge-note
  -> sol-3 optional-human-review
  -> sol-4 capture-text-subworkflow
  -> sol-5 compose-solidify-result
```

## Event / Asset Trigger

目标平台应支持显式 trigger：

```text
UserEntryCreated
NoteCreated
ChunkCreated
GraphSyncPending
ReviewDue
WorkflowFailed
HumanApprovalExpired
EvaluationRegressionDetected
```

例子：

```text
NoteCreated
  -> enqueue graph_sync workflow

ReviewDue
  -> enqueue review_digest workflow

WorkflowFailed(intent=ask, reason=retrieval_empty)
  -> enqueue reflection workflow

EvaluationRegressionDetected(workflow=ask)
  -> block deployment
```

这会把当前“用户请求驱动”扩展为“事件驱动 + 用户请求驱动”。

## HITL 统一化

当前 HITL 主要服务 `delete_note`。目标形态中，HITL 是通用 step：

```text
HumanGateDefinition
  gate_id
  title
  payload_schema
  decisions
  timeout_policy
  default_decision
  allowed_reviewers
```

适用场景：

- 高风险删除。
- solidify 写入前人工审阅草稿。
- 低置信 ask 答案请求用户确认问题范围。
- graph 抽取质量过低时请求人工修正。

HITL 的 resume 不应依赖节点内部约定，而应写入：

```text
human_gate.requested
human_gate.resumed
human_gate.expired
```

## Policy 与 Tool Boundary

目标系统中，所有外部副作用都必须是 activity：

- 写长期记忆。
- 删除 note。
- 抓 URL。
- 调 web search。
- 调 Graphiti ingest。
- 调 LLM。
- 发飞书消息。

每个 activity 都有统一 envelope：

```text
ActivityInput
  execution_id
  step_id
  attempt
  idempotency_key
  principal
  policy_context
  payload_artifact_id
```

ToolGateway / ModelGateway / StorageGateway 负责：

- policy evaluation
- idempotency
- timeout
- retry eligibility
- redaction
- audit
- output artifact write

## Versioning 与 Migration

目标规则：

1. `WorkflowDefinition` 不可变。
2. 新版本创建新 definition。
3. 新 run 默认使用 latest stable version。
4. 已运行实例继续绑定创建时的 version。
5. 允许显式 fork 到新版本，但必须记录 `workflow.forked` 事件。

需要新增：

```text
WorkflowDefinitionStore
WorkflowMigrationSpec
WorkflowDeployment
```

`WorkflowDeployment` 控制：

- active version
- canary percentage
- allowed users
- rollback version
- eval gate status

## Replay / Fork / Debug

目标能力：

```text
replay execution_id
fork execution_id --from-step ask-7 --workflow-version v3
dry-run workflow_id --input artifact_id
compare execution_a execution_b
```

Replay 模式：

| 模式 | 行为 |
| --- | --- |
| `history` | 完全复用历史 activity outputs，只重建状态 |
| `deterministic` | 复用外部副作用结果，重新跑纯计算节点 |
| `live` | 重新调用模型/工具，但禁止写副作用 |
| `fork-live` | 从某 step 后重新运行，写入新 execution |

这比当前 checkpoint export 更适合排查“为什么这次 ask 回答差”或“为什么删除候选选错”。

## Observability

目标观测面：

- workflow timeline
- step input/output artifact
- prompt/model/tool version
- retrieval candidates snapshot
- rerank before/after
- ContextPack selected/dropped
- verifier report
- policy decision
- cost / token / latency
- retry/backoff history
- worker logs

建议新增统一 trace id：

```text
trace_id = execution_id
span_id = step_execution_id / activity_attempt_id
```

所有日志、AgentEvent、tool audit、policy decision、LLM trace 都挂同一个 trace tree。

## Evaluation Gate

任何 workflow definition、prompt、model、tool schema、retriever/reranker 策略变更都应走 eval gate：

```text
ChangeSet
  -> static validation
  -> workflow spec validation
  -> golden tests
  -> offline eval suite
  -> canary deployment
  -> production promotion
```

ask gate：

- retrieval recall
- citation correctness
- answer faithfulness
- verifier pass rate
- latency / cost

delete gate：

- candidate recall
- target resolve accuracy
- false delete rate
- HITL payload correctness

capture gate：

- chunk coverage
- chunk boundary quality
- metadata preservation
- graph sync success

solidify gate：

- selected dialogue range accuracy
- draft quality
- no instruction-as-note failure
- capture output correctness

## 存储设计

目标新增表或等价存储：

```text
workflow_definitions
workflow_deployments
workflow_executions
step_executions
workflow_events
workflow_artifacts
worker_queues
activity_attempts
human_tasks
workflow_eval_runs
workflow_replay_runs
```

与现有业务表边界：

- 长期知识仍在 `knowledge_notes / chunks / review / graph mapping`。
- workflow state 只保存执行现场、事件和 artifact。
- artifact 可引用业务对象 ID，但不成为事实源。

## 与 LangGraph 的关系

目标不是丢掉 LangGraph，而是重新定位：

| 层 | 目标职责 |
| --- | --- |
| Workflow Platform | definition、execution、queue、event log、artifact、deployment |
| LangGraph | 单个 workflow execution 内的状态机编排和 HITL resume |
| ToolGateway | 外部副作用边界 |
| Worker | activity 执行容器 |

也可以进一步把 LangGraph 只用于 agentic 子流程，例如 ReAct、clarification、human-in-loop dialogue；而 durable workflow engine 负责更外层的长期运行和任务调度。

## 迁移路径

不考虑兼容性时，仍建议分阶段落地，避免一次性重写失败。

### Phase 1：Durable Artifacts（已完成 ask context 切面）

替换 `AskRunContextStore`：

```text
AskRunContextStore
  -> workflow_artifacts
```

已完成：

- ask 的 evidence pool、ContextPack、selected candidates、answer、verifier report 会序列化到 `workflow_artifacts(kind="ask_run_context")`。
- 所有 step 都会持久化 `step_input / step_output / step_error` artifact。
- `StepRunState` 保存 `input_artifact_id / output_artifact_id / error_artifact_id`，checkpoint 只需要保存引用和轻量结果。

继续优化后，artifact 已支持 `expires_at / redacted_at`、批量过期清理和递归字段脱敏，脱敏后会重新计算 content hash。

仍未完成的通用平台部分：worker activity 还没有全部统一到 artifact contract，artifact encryption/KMS 和按 workflow/kind 自动选择 retention policy 尚未接入。

### Phase 2：Workflow Event Log（已完成 AgentEvent 持久化切面）

引入不可变 `workflow_events`，让 `AgentEvent` 成为派生视图。

```text
AgentEvent = public projection
WorkflowEvent = internal source of truth
```

已完成：`EntryOrchestrator` 在 graph streaming 过程中即时追加 `workflow_events`，并在 execute / interrupt / resume / replay 返回路径做幂等 flush。表以 `event_id` 为主键，重复写入会 `ON CONFLICT DO NOTHING`。

仍未完成的通用平台部分：当前 event log 仍是从 `AgentEvent` 派生的持久化日志，还不是所有 activity / worker / artifact 操作的唯一 source of truth；后续需要把 `AgentEvent` 反过来变成 `WorkflowEvent` 的 API/SSE projection。

### Phase 3：Worker Queue（已完成 durable queue + graph sync 接入切面）

先把 graph sync、web fetch、file extraction、ask retrieval 移出请求线程。

优先队列：

```text
graph
ingestion
retrieval
```

已完成的最小切面：

- 新增 `worker_queue_tasks` durable queue。
- 新增 `PostgresWorkerQueueStore`，支持 idempotent enqueue、lease、complete、fail/dead 和 task listing。
- capture 生成 chunk 后，会为 pending chunk 入队 `graph_sync_note`。
- `AgentRuntime.drain_worker_queue(queue="graph")` 可同步租约并执行 graph sync worker task。
- `AgentService` 暴露 `enqueue_graph_sync()` 和 `drain_worker_queue()` 转发入口。
- 新增 `WorkflowWorker` 和 `personal-agent worker` 常驻 CLI。
- queue 支持 lease heartbeat、per-user running limit、queue stats、dead task retry。

仍未完成的通用平台部分：

- web fetch、file extraction、ask retrieval 尚未迁入 queue。
- 队列级 rate limit、priority aging、dead-letter UI 还未完善。

### Phase 4：All Workflow Step 化

已完成：

- `capture_text` 投影为 `cap-structure -> tool_call(capture_text)`。
- `capture_link` 投影为 `cap-link-fetch -> cap-link-store`，抓取正文后动态注入 `capture_text`。
- `capture_file` 投影为 `cap-file-read -> cap-file-store`，解析上传文件后动态注入 `capture_text`。
- `summarize_thread` 投影为 `sum-compose`，复用原 thread summary 业务逻辑。
- `direct_answer` 投影为 `direct-compose`，复用原直接回复业务逻辑。
- `StepProjectionValidator` 已允许这些 workflow 的入口参数 / 上游工具结果动态注入，同时保留工具 schema 校验。
- `tool_result` 事件保留 artifact 输出，并把 capture 常用字段提升到 payload 顶层兼容现有 UI。

仍未完成的通用平台部分：

- UI 折叠展示策略还未实现。
- `unknown` 和 projection 校验失败仍走 fallback branch。

### Phase 5：Workflow Version Deployment

已完成最小切面：

```text
workflow_id=ask
version=v1/v2/v3
deployment=stable/canary/disabled
```

- 新增 `workflow_definitions`，持久化 `WorkflowSpec` definition payload。
- 新增 `workflow_deployments`，按 `workflow_id + environment` pin `stable_version / canary_version / status`。
- `AgentRuntime` 启动时会把当前 `WORKFLOW_REGISTRY` 同步到 definition store。
- `WorkflowStepProjector` 会优先通过 deployment store 选择 active spec，再投影 `ExecutionStep`。
- `AgentRuntime / AgentService` 暴露 definition/deployment 查询和设置入口。

仍未完成的通用平台部分：

- canary 已按 `workflow_id + routing_key` 稳定哈希做百分比分流。
- execution checkpoint 会 pin `workflow_id / workflow_version`，历史 run 不会因 deployment 变化而漂移。
- 新增 `workflow_state_migrations`，持久化 `from_version -> to_version` 的 step mapping。
- `migrate_step_execution()` 可复用旧版本已完成步骤的 artifact/result，新步骤保持 `planned`。
- `preview_workflow_state_migration()` 可在不执行副作用时预览迁移结果。

仍未完成的是部署时自动批量迁移长运行实例；当前迁移采用显式注册、显式预览。

### Phase 6：Replay / Fork

已完成最小切面：

- 新增 `workflow_replay_runs`，记录 replay/fork 的 source run、source checkpoint、mode、status、新 run。
- `replay_from_checkpoint()` 继续复用 LangGraph checkpoint time travel，并记录 `workflow_replayed` 事件。
- 新增 `fork_from_checkpoint()`，从历史 checkpoint 生成新 `run_id` 后继续执行，并记录 `workflow_forked` 事件。
- 新增 `PostgresWorkflowReplayStore`，提供 artifact 查询、replay run 查询和 debug bundle 组装。
- `build_workflow_debug_bundle(run_id)` 会聚合 event log、artifact 摘要、checkpoint history、replay/fork 记录。
- 新增 workflow dry-run，可校验 active 或 patched definition 并投影 steps，不执行副作用。
- 新增 event-sourced execution projection，`rebuild_workflow_projection(run_id)` 可从 `workflow_events` 重建 intent、workflow version、step 状态、artifact 引用、HITL、answer 和错误。
- debug bundle 已包含上述 projection。
- 新增 `fork_from_step(run_id, step_id)`，可定位 LangGraph 子图 `checkpoint_ns`，重置目标 step 及其传递依赖，并以新 `run_id` 恢复。

仍未完成的通用平台部分：

- replay 还不是完全 event-sourced deterministic replay，仍依赖 LangGraph checkpoint。
- step-level fork 已有 runtime/service API，但还没有管理 UI 和 execution compare 视图。
- event projection 尚未物化为独立 `workflow_executions / step_executions` 查询表。
- replay 尚未区分 history/deterministic/live/fork-live 四种严格副作用策略。

### Phase 7：Eval Gate

已完成最小切面：

- 新增 `workflow_eval_runs`，记录 `workflow_id / version / suite / passed / score / metrics / report`。
- `PostgresWorkflowDefinitionStore.record_eval_run()` 可把离线 eval、pytest eval、CI 结果写入门禁表。
- `set_deployment()` 默认启用 eval gate：stable/canary 目标版本必须有最新通过的 eval run，否则拒绝 deployment。
- `status="disabled"` 不需要 eval gate，方便紧急下线。
- 开发/紧急场景可显式传 `require_eval_gate=False` 强制发布。
- `AgentRuntime / AgentService` 暴露 `record_workflow_eval_run()` 与 `get_workflow_eval_gate_status()`。

仍未完成的通用平台部分：

- CLI 已提供 `workflow-eval-record / workflow-deploy / workflow-dry-run`，CI 可直接写入 eval 并执行受门禁约束的部署。
- 尚未把 prompt/model/tool schema/retriever 变更自动归因到对应 workflow version。
- 已支持 per-workflow 多 suite、最低 score 和 metric threshold policy。

## 最终目标形态

完成后，系统应该能支持这些操作：

```text
启动一个 ask workflow
  -> 返回 execution_id
  -> 前端实时看每个 step
  -> retrieval 在 worker 中跑
  -> ContextPack 持久化
  -> compose/verify 可恢复
  -> 失败可从任意 step fork
  -> 新版 ask workflow 可灰度
  -> prompt 改动必须过 eval gate

采集一个 URL
  -> fetch/partition/write/review/graph sync 全部 step 化
  -> graph sync 后台排队
  -> 失败进入 dead letter
  -> 可重试单个 chunk 的 graph ingest

删除一条知识
  -> candidate snapshot 持久化
  -> human approval 持久化
  -> delete activity 幂等
  -> 可审计谁确认、删了什么、为什么删
```

## 设计原则

1. Workflow definition 是真源，LLM 不拥有全局流程设计权。
2. 每个外部副作用都是 activity。
3. 每个 activity input/output 都有 artifact。
4. Event log 不可变，snapshot 只是加速读取。
5. 大对象不进 checkpoint，进 artifact store。
6. HITL 是通用 gate，不是删除流程特例。
7. Eval gate 是 workflow deployment 的前置条件。
8. Worker queue 承担长耗时和外部系统波动。
9. ReAct 是受控 step，不是全局 autonomous loop。
10. 允许 fork/replay/debug 成为一等能力，而不是临时脚本。

## 面试表述

可以这样讲未来优化方向：

> 当前项目已经有 workflow-first 的雏形：固定 `WorkflowSpec` 投影成 `ExecutionStep`，再由 LangGraph 执行。下一步如果对齐优秀 workflow 平台，我会把它升级成 durable workflow platform：引入 versioned workflow definition、不可变 event log、durable artifact store、worker queue、activity boundary、通用 HITL gate、replay/fork 和 eval gate。这样 ask、capture、delete、solidify 都会成为可持久化、可恢复、可观测、可灰度发布的 workflow，而不是一次请求里的同步编排。
