# 规划层说明

本文说明当前项目如何把复杂或高风险请求拆成可校验、可执行、可恢复的计划步骤。重点不是罗列“已有能力”，而是解释每一种计划步骤的语义、输入输出和它在真实流程中的作用。对应代码主要位于 [planner.py](../../src/personal_agent/agent/planner.py)、[plan_validator.py](../../src/personal_agent/agent/plan_validator.py)、[orchestration_nodes/_steps.py](../../src/personal_agent/agent/orchestration_nodes/_steps.py) 和 [orchestration_models.py](../../src/personal_agent/agent/orchestration_models.py)。

## 设计目标

规划层只服务需要明确步骤边界的任务。普通 `ask / capture / direct_answer / summarize` 直接走 Graph 分支并输出 `execution_trace`；真正进入计划执行的主要是：

- `delete_knowledge`：删除长期知识，属于高风险操作，必须解析目标并经过确认。
- `solidify_conversation`：把已有对话结论整理成正式知识，需要先生成草稿，再写入知识库。

规划层的核心职责：

- 用 `PlanStep` 表达任务步骤。
- 用 `PlanStepState` 保存 checkpoint-safe 执行状态。
- 用 `PlanValidator` 阻止不安全或不可执行的计划。
- 用 LangGraph `PlanExecutionGraph` 按步骤推进，并把状态写入 checkpoint。
- 对高风险工具通过 `interrupt/resume` 接入人工确认。

## 计划步骤模型

`DefaultTaskPlanner` 产出 `PlanStep`。进入 Graph 后会转换为 `PlanStepState`，保存在 `AgentGraphState.plan.steps` 中。

核心字段：

| 字段 | 含义 |
| --- | --- |
| `step_id` | 步骤唯一标识，例如 `del-2` |
| `action_type` | 步骤类型：`retrieve / resolve / tool_call / compose / verify` |
| `description` | 面向用户和日志的步骤说明 |
| `tool_name` | `tool_call` 或 ReAct 可调用的工具名 |
| `tool_input` | 工具输入；部分字段允许由上游步骤动态注入 |
| `depends_on` | 前置步骤 id |
| `risk_level` | 风险等级：`low / medium / high` |
| `requires_confirmation` | 是否需要用户确认 |
| `on_failure` | 失败策略：`skip / retry / abort` |
| `execution_mode` | `deterministic` 或 `react` |
| `allowed_tools` | ReAct 模式允许调用的工具列表 |
| `max_iterations` | ReAct 最大迭代轮数 |

执行时，Graph 会更新：

- `status`：`planned / running / completed / failed / skipped`
- `retry_count`
- `failure_reason`
- `validation_warnings`
- `AgentGraphState.plan.results[step_id]`

## 当前步骤类型

### `retrieve`：检索候选信息

`retrieve` 用于把用户请求转成候选上下文。当前主要调用图谱检索：

```text
deps.graph_store.ask(question, user_id)
```

返回结果会写入 `state.plan.results[step_id]`，常见字段：

- `answer`
- `entity_names`
- `relation_facts`
- `related_episode_uuids`

在 `delete_knowledge` 中，`retrieve` 的重要输出是 `related_episode_uuids`。这些 episode uuid 后续会被 `resolve` 映射回本地 `knowledge_notes`。

### `resolve`：把模糊目标解析为具体对象

`resolve` 不执行删除，也不修改数据库。它只回答一个问题：

> 用户说“删除这条 / 删除关于 DNS 的知识 / 删除刚才那条”，到底对应哪一个 `note_id`？

当前 `delete_knowledge` 的 `resolve` 逻辑在 [_steps.py](../../src/personal_agent/agent/orchestration_nodes/_steps.py) 中，顺序如下。

第一步：使用图谱 episode 映射。

1. 遍历上游步骤结果。
2. 查找 `related_episode_uuids`。
3. 调用 `PostgresMemoryStore.find_notes_by_graph_episode_uuids(user_id, uuids)`。
4. 将匹配到的 note 转成候选项。

候选项结构类似：

```json
{
  "note_id": "...",
  "title": "...",
  "summary": "...",
  "source": "graph_episode"
}
```

第二步：如果图谱映射没有候选，则让 LLM 在本地 note 候选中选择。

1. 读取当前用户的 parent notes：`list_notes(user_id, include_chunks=False)`。
2. 取最近最多 100 条。
3. 只把 `note_id / title / summary` 提供给模型。
4. 要求模型只在目标明显对应时返回一个候选 `note_id`；不确定或多候选时返回 `null`。

这一步的关键约束是：LLM 只能从已有候选 ID 中选择，不能生成新 ID，也不能执行删除。

如果仍然没有候选，`resolve` 会失败并写入用户可见回答：

```text
未找到可删除的知识笔记，请提供更具体的标题或内容描述。
```

如果找到候选，`resolve` 返回：

```json
{
  "note_id": "...",
  "title": "...",
  "summary": "...",
  "source": "...",
  "candidates": [...]
}
```

随后 Graph 会把 `note_id` 动态注入依赖该 `resolve` 步骤的 `tool_call(delete_note)`：

```text
resolve result.note_id
  -> delete_note.tool_input.note_id
  -> delete_note.tool_input.user_id
```

因此，删除哪些数据不是 planner 在计划阶段拍脑袋决定的，而是运行时通过 `resolve` 从真实知识库候选中解析出来。

### `tool_call`：调用工具

`tool_call` 不在普通 Python handler 中直接执行，而是交给 LangGraph `ToolNode`。Graph 会创建 tool-call message，并通过 `tool_messages` 和 `pending_tool_call_id` 精确消费结果。

当前关键工具：

- `delete_note`
- `capture_text`

`delete_note` 的行为：

1. 未确认时，不删除数据，只返回 `pending_confirmation=true`。
2. Graph 检测到 pending confirmation 后进入 `interrupt()`。
3. 用户确认后，resume 时携带确认决策，Graph 将 `confirmed=true` 注入工具输入。
4. 工具在二次调用时真正删除。

真正删除时会清理：

- 目标 `knowledge_notes` 记录
- 如果目标是 parent note，则级联删除子 chunk notes
- 关联 `review_cards`
- 上传文件引用
- Graphiti episode 映射，若图谱可用

`capture_text` 的行为：

- 将文本写入长期知识库。
- 生成 `KnowledgeNote`。
- 复用 capture 链路做 chunk、review card、图谱同步等后续处理。

### `compose`：生成用户可见文本或草稿

`compose` 用于把前置步骤结果整理为自然语言输出。不同 intent 下语义不同。

在 `delete_knowledge` 中：

- 依赖 `delete_note` 的结果。
- 生成删除结果摘要，例如“已创建确认请求”“已删除某笔记”“未找到目标”。

在 `solidify_conversation` 中：

- 从 checkpoint `state.messages` 中读取候选会话。
- 让模型判断哪些会话事实属于本次固化范围。
- 生成一条可独立入库的知识草稿。
- 如果没有足以固化的知识正文，则失败，不写入知识库。

solidify 的草稿保存在 checkpoint 的 `plan.results` 中，并发出 `draft_ready` 事件，便于前端展示。

### `verify`：校验回答或结果

`verify` 用于对回答事实依据做校验。当前计划驱动主流程中，删除计划不允许添加独立 `verify` 步骤，因为删除确认由 `delete_note` 工具和 HITL 流程承担；solidify 也不允许 `verify`，因为当前只有 `compose -> capture_text` 两步具有明确执行语义。

## 典型计划

### 删除知识：`delete_knowledge`

当前模板：

```text
del-1 retrieve
  -> del-2 resolve
  -> del-3 tool_call(delete_note)
  -> del-4 compose
```

步骤含义：

| 步骤 | 作用 | 是否修改数据 |
| --- | --- | --- |
| `retrieve` | 找删除候选，通常通过图谱检索拿到 episode uuid | 否 |
| `resolve` | 从候选中确定一个真实 `note_id` | 否 |
| `tool_call(delete_note)` | 创建确认动作；确认后删除 note/chunk/review/图谱映射 | 是，且必须确认 |
| `compose` | 生成删除结果说明 | 否 |

关键安全规则：

- `delete_note.note_id` 不能由 planner 提前写死，必须由 `resolve` 动态注入。
- `delete_note` 必须依赖 `resolve`。
- `delete_note` 必须声明 `risk_level="high"` 和 `requires_confirmation=True`。
- 删除计划不允许用 `verify` 代替确认。

### 固化对话：`solidify_conversation`

当前模板：

```text
sol-1 compose
  -> sol-2 tool_call(capture_text)
```

步骤含义：

| 步骤 | 作用 | 是否修改数据 |
| --- | --- | --- |
| `compose` | 从 checkpoint 对话中选择本次用户要求固化的知识，生成草稿 | 否 |
| `tool_call(capture_text)` | 把草稿写入 `knowledge_notes` | 是 |

关键安全规则：

- 固化计划不允许出现 `retrieve / resolve / verify`，因为当前这些步骤没有独立可兑现语义。
- `capture_text.text` 不能由 planner 提前填写，也不能是占位符。
- 正文必须来自上游 `compose` 的真实草稿，并由 Graph 动态注入。
- 用户已明确要求固化，因此 `capture_text` 是 `risk_level="low"` 且 `requires_confirmation=False`。

## 校验规则

`PlanValidator` 是计划执行前的安全门。它会检查：

- `action_type` 是否有效。
- `depends_on` 是否引用存在的步骤。
- 依赖图是否有环。
- `tool_call.tool_name` 是否已注册。
- 工具参数是否满足 LangChain tool schema。
- `risk_level / on_failure / status` 是否合法。
- ReAct 步骤是否越权调用高风险工具。
- intent 特定规则是否满足。

其中 intent 特定规则最重要：

- `delete_knowledge` 必须包含 `tool_call(delete_note)`。
- `delete_knowledge` 的 `delete_note` 必须依赖 `resolve`。
- `solidify_conversation` 必须包含 `tool_call(capture_text)`。
- `solidify_conversation` 的 `capture_text` 必须依赖 `compose`。

如果校验有 blocking issue，Graph 会尝试 fallback plan；如果仍不可用，则转成用户可见的澄清或错误提示，不会执行危险工具。

## ReAct 步骤

`PlanStep.execution_mode="react"` 表示该步骤内部可以运行受控 Thought / Action / Observation 循环。当前主要用于检索类步骤。

约束：

- 默认只允许只读工具，例如 `graph_search / web_search`。
- 不允许高风险、写长期知识或需要确认的工具。
- `max_iterations` 有上限。
- 每轮 action / observation 都会进入事件流。
- ReAct 失败或耗尽会回到计划步骤状态机，按 `on_failure` 处理。

ReAct 是单步内部策略，不替代整体计划执行器。

## 可观测性与恢复

计划执行状态保存在 `AgentGraphState.plan`，并进入 Postgres checkpoint。

用户和前端可以看到：

- `EntryResult.plan_steps`
- SSE `plan_created`
- SSE `plan_step_started`
- SSE `plan_step_completed`
- SSE `plan_step_failed`
- SSE `draft_ready`
- run snapshot 中的 plan / pending confirmation

当高风险工具需要确认时，Graph 会暂停在 checkpoint 中。用户通过 resume 接口确认或拒绝后，后端用同一个 `thread_id` 恢复，不需要重新规划。

## 已知边界

- planner LLM 仍依赖 prompt 约束，复杂任务下可能生成过泛或不可执行的步骤，因此必须经过 `PlanValidator`。
- `resolve` 当前只选择单个删除目标；多目标批量删除需要额外设计候选确认 UI 和计划 schema。
- 本地候选选择只给 LLM `note_id / title / summary`，不会给全文，能降低误删风险，但也可能导致召回不足。
- replan 当前更偏失败补救；revised steps 的完整复校验仍是后续重点。
- solidify 的范围判断依赖 checkpoint 对话和 LLM，仍需要更系统的长会话干扰评测。

## 演进方向

- 为 `resolve` 增加结构化候选确认 UI，支持多候选人工选择。
- 为 revised steps 接入与初始计划完全一致的复校验。
- 为计划步骤定义更稳定的 JSON schema，并加入独立 contract tests。
- 为删除、固化、长会话干扰建立专项 eval。
