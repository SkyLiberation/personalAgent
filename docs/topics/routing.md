# Goal 路由与 Workflow 规划

入口框架采用明确的决策边界：

```text
Router: What
  → WorkflowPlanner: How
    → Orchestrator: When / State
      → Executor: Do
        → Policy: May
```

## Router：传输模型与领域模型分离

[router.py](../../src/personal_agent/agent/router.py) 使用两层模型：

- `RouterOutput / GoalDraft`：LLM strict JSON Schema 传输契约
- `RouterDecision / Goal`：系统内部领域模型

模型转换关系如下：

```text
LLM JSON
  └─ RouterOutput
       ├─ GoalDraft[]
       └─ ClarificationDraft | null
              │
              │ validate + normalize
              ▼
       RouterDecision
         └─ Goal[]
              │
              │ WorkflowPlanner.plan()
              ▼
       ExecutionPlan
         └─ WorkflowTask[]
              +
         ExecutionStep[]
```

### LLM 输出模型

#### `GoalDraft`

表示 LLM 识别出的一个最小语义目标。

| 字段 | 类型 | 含义 |
|---|---|---|
| `intent` | `EntryIntent` | 用户要完成的业务目标 |
| `input` | `str` | 该目标实际处理的内容，至少一个字符 |

当前 `EntryIntent` 包含：

```text
capture_text | capture_link | capture_file | ask | summarize_thread
delete_knowledge | solidify_conversation | direct_answer | unknown
```

`GoalDraft` 不包含 ID 和依赖。LLM 只负责识别“做什么”，不负责生成系统标识或执行拓扑。

#### `ClarificationDraft`

仅在当前输入不足以形成可执行目标时使用。

| 字段 | 类型 | 含义 |
|---|---|---|
| `missing_information` | `list[str]` | 缺失信息列表，至少一项 |
| `prompt` | `str` | 面向用户的直接追问 |

#### `RouterOutput`

Router LLM 的顶层 JSON Schema。

| 字段 | 类型 | 含义 |
|---|---|---|
| `outcome` | `"ready" \| "clarify"` | 本次是否已形成目标 |
| `goals` | `list[GoalDraft]` | 按用户表达顺序排列的语义目标 |
| `clarification` | `ClarificationDraft \| null` | 需要澄清时的结构化信息 |

其模型约束为：

- `ready`：至少包含一个 Goal，且 `clarification=null`
- `clarify`：不包含 Goal，且必须提供 `clarification`

### Router 领域模型

#### `Goal`

经过系统标准化、可交给 Planner 的领域目标。

| 字段 | 类型 | 含义 |
|---|---|---|
| `goal_id` | `str` | Router 代码生成的稳定 ID，例如 `goal_1` |
| `intent` | `EntryIntent` | 目标意图 |
| `input` | `str` | 目标输入 |

`Goal` 与 `GoalDraft` 的关键区别是：`goal_id` 由系统生成，而不是交给 LLM。

#### `RouterDecision`

一次 Router 调用的完整领域结果。

| 字段 | 类型 | 含义 |
|---|---|---|
| `goals` | `list[Goal]` | 标准化后的有序目标 |
| `requires_clarification` | `bool` | 是否需要用户补充信息 |
| `missing_information` | `list[str]` | 缺失的信息 |
| `clarification_prompt` | `str` | 发给用户的追问 |
| `error` | `"router_unavailable" \| null` | Router 模型不可用等系统错误 |
| `primary_intent` | property | 最后一个 Goal 的意图；无 Goal 时为 `unknown` |

`RouterDecision` 是 Router 与 Planner/入口编排之间的稳定边界。它不携带工具、风险、确认要求或
workflow 信息。

LLM 对每个 Goal 只输出 `intent / input`，并按用户表达的处理顺序排列。
代码解析后生成稳定的 `goal_1 / goal_2`。

Router 只依赖 `StructuredModelClient` 协议，并向它提交 `StructuredModelRequest[RouterOutput]`。
Router 不引用 OpenAI、LangSmith、trace 开关或脱敏策略。基础设施 adapter 使用
`client.responses.parse(..., text_format=RouterOutput)`，由 OpenAI SDK 完成 strict JSON Schema
生成、响应解析和 Pydantic 校验。

依赖和装配关系如下：

```text
DefaultIntentRouter
  → StructuredModelClient                 # application port
      ↑
ObservedStructuredModelClient             # optional decorator
  → TracePayloadPolicy
  → OpenAIResponsesModelClient             # provider adapter
      → client.responses.parse
```

`AgentRuntime` 是 composition root：模型未配置时注入 `None`；LangSmith 关闭时直接注入 OpenAI
adapter；LangSmith 开启时再叠加观测 decorator 和 payload policy。业务 Router 不参与这些决策。
默认脱敏模式保留模型、消息数量、字符数、延迟和 token usage 等摘要，不上传 Router prompt 或
`RouterOutput` 正文；完整字段边界见
[LLM Trace 脱敏策略](observability-governance.md#7-llm-trace-脱敏策略)。

Router 不输出工具、检索策略、风险、确认要求或 workflow topology。这些字段属于执行策略，
如果由 Router 维护，会与 WorkflowSpec 和 Tool Governance 形成多个事实源。

## Router 使用的 LLM 配置

Router 的模型调用配置由
[`RouterConfig`](../../src/personal_agent/core/config_models.py) 定义，与通用问答模型配置分离。

| 配置项 | 环境变量 | 默认值/说明 |
|---|---|---|
| `api_key` | `ROUTER_API_KEY` | 未设置时回退到 `OPENAI_API_KEY` |
| `base_url` | `ROUTER_BASE_URL` | 未设置时回退到 `OPENAI_BASE_URL` |
| `model` | `ROUTER_MODEL` | 默认 `gpt-5.4-mini` |
| `timeout_seconds` | `PERSONAL_AGENT_ROUTER_TIMEOUT_SECONDS` | 默认 30 秒 |
| `max_retries` | `PERSONAL_AGENT_ROUTER_MAX_RETRIES` | 默认 2 次 |
| `extra_body` | `ROUTER_EXTRA_BODY` | 供应商扩展参数 JSON |

Router 默认使用 `responses.parse`，因此所选模型和接口需要支持 Responses API 的 Pydantic
结构化输出。项目不提供 `json_object` 降级路径：需要结构化契约的调用统一使用 strict
`json_schema`。配置独立的目的是让 Router 不受通用问答模型供应商能力限制。

## WorkflowPlanner：唯一规划入口

[workflow_planner.py](../../src/personal_agent/agent/workflow_planner.py) 负责：

- 为每个 Goal 选择 active `WorkflowSpec`
- 从 WorkflowSpec 编译 `ExecutionStep`
- 根据 Goal 顺序生成 task 依赖，并连接跨 workflow 的 step 依赖
- 生成 `WorkflowTask` 和 `ExecutionPlan`

工具、风险等级、确认策略、ReAct 模式均从 WorkflowSpec 投影，不读取 Router 元数据。
当前执行策略是顺序串行；未来若引入并行、条件分支或资源约束，也应由 Planner 根据语义目标和
规划策略生成 DAG，而不是扩张 Router 的输出职责。

## ExecutionPlan：任务级计划

[execution_models.py](../../src/personal_agent/agent/execution_models.py) 定义：

### `WorkflowTask`

Goal 与选中 Workflow 的绑定，包含 `task_id / intent / input / depends_on / workflow_id /
workflow_version / step_ids`。其中 `depends_on` 由 Planner 生成，不来自 Router。

### `ExecutionPlan`

任务级计划，包含系统生成的 `plan_id` 和 `WorkflowTask[]`。它描述任务拓扑，不重复保存完整 Step。

### `ExecutionStep`

由 `WorkflowSpec` 编译出的执行节点。它包含：

- 节点标识、动作类型和描述
- 工具、工具输入和允许工具范围
- Step 依赖
- 风险、确认和失败策略
- workflow 与 task 归属
- 当前执行状态和重试次数

`ExecutionPlan` 不重复存储完整 steps。任务拓扑保存在 plan 中，可变的步骤运行状态由
`StepExecutionState` 管理，避免两个步骤事实源发生漂移。

## Orchestrator：只负责过程状态

Orchestrator 不重新选择 workflow，也不从 Router 推断工具和风险。它只负责：

- 按 step DAG 调度
- checkpoint 和恢复
- HITL
- 重试和 replanning
- ReAct 子图
- 事件与结果聚合

执行节点通过 step-local 的 `task_intent` 和 `task_input` 获取当前任务语义，因此复合请求不会再依赖
全局单一 intent 或整句原始输入。
