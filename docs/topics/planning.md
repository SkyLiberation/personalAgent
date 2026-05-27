# 规划层说明

本文汇总当前项目规划层的职责划分、计划生成与执行路径、现有能力、已知限制和后续改进方向。对应代码主要位于 [src/personal_agent/agent/planner.py](../../src/personal_agent/agent/planner.py)、[src/personal_agent/agent/plan_validator.py](../../src/personal_agent/agent/plan_validator.py)、[src/personal_agent/agent/plan_executor.py](../../src/personal_agent/agent/plan_executor.py) 和 [src/personal_agent/agent/replanner.py](../../src/personal_agent/agent/replanner.py)。

## 设计目标

当前规划层的目标是把复杂或高风险任务从“一次性回答”升级为可观测、可校验、可执行和可恢复的步骤流：

- 用 `PlanStep` 表示结构化任务步骤
- 用 `DefaultTaskPlanner` 根据 intent 生成计划
- 用 `PlanValidator` 在执行前做结构、依赖、风险和工具校验
- 用 `PlanExecutor` 按依赖顺序执行计划并回传进度
- 用 `Replanner` 在失败重试耗尽后尝试替换剩余步骤

## 组件分层

### 1. `PlanStep`

代码位置：[planner.py](../../src/personal_agent/agent/planner.py)

作用：

- 表示计划中的一个可执行步骤
- 记录步骤类型、工具名、工具输入、依赖关系和风险等级
- 记录执行状态和重试次数

核心字段包括：

- `step_id`
- `action_type`
- `description`
- `tool_name`
- `tool_input`
- `depends_on`
- `expected_output`
- `success_criteria`
- `risk_level`
- `requires_confirmation`
- `on_failure`
- `status`
- `retry_count`

当前支持的主要 `action_type`：

```text
retrieve
resolve
tool_call
compose
verify
```

### 2. `DefaultTaskPlanner`

代码位置：[planner.py](../../src/personal_agent/agent/planner.py)

作用：

- 接收 router 产出的 intent
- 优先调用 LLM 生成结构化计划
- LLM 不可用或输出不可解析时，回退到启发式计划
- 将 `ToolExecutor.list_tools()` 注入规划 prompt，让 planner 感知当前可用的 LangChain 工具

当前内置启发式计划覆盖：

- `capture_text / capture_link / capture_file`
- `ask`
- `summarize_thread`
- `delete_knowledge`
- `solidify_conversation`
- `direct_answer`
- `unknown`

### 3. `PlanValidator`

代码位置：[plan_validator.py](../../src/personal_agent/agent/plan_validator.py)

作用：

- 执行前校验计划结构
- 校验依赖图是否完整、是否存在循环依赖
- 校验 `tool_call` 中的 `tool_name` 是否已注册
- 校验 `risk_level / on_failure / status`
- 将计划与 `RouterDecision` 交叉校验

它是规划层的安全门。比如 router 标记 `requires_confirmation=True`，但计划里没有任何确认步骤时，会产生阻断性 issue。

### 4. `PlanExecutor`

代码位置：[plan_executor.py](../../src/personal_agent/agent/plan_executor.py)

作用：

- 对计划步骤做拓扑排序
- 按依赖顺序执行步骤
- 将步骤状态从 `planned` 推进到 `running / completed / failed / skipped`
- 通过 progress callback 发出 SSE 事件
- 将执行过程写入 `WorkingMemory.recent_steps`
- 在失败时按 `on_failure` 决定 retry、skip、abort 或 replan

当前 step 分发逻辑：

- `retrieve`：查询图谱或知识侧信息
- `resolve`：将模糊目标解析为具体 note
- `tool_call`：生成写入 `tool_messages` 的 tool-call message，由 `PlanExecutionGraph.plan_tool_node` 执行，并按 `pending_tool_call_id` 精确消费 artifact
- `compose`：生成回答、删除摘要或固化草稿
- `verify`：校验回答或执行结果

`PlanStep` 已支持可选执行策略字段：

```text
execution_mode = "deterministic" | "react"
allowed_tools = [...]
max_iterations = 3
```

`execution_mode="react"` 的步骤会进入独立 `ReactGraph` 的小范围 Thought / Action / Observation 节点循环；其他步骤留在 `PlanExecutionGraph` 的确定性 handler。计划图负责依赖、失败处理和审计，ReAct 只作为单步内部策略。

当前实现约束：

- `allowed_tools` 为空时默认只允许只读检索工具（`graph_search / web_search`）
- 高风险、写长期知识和确认类工具不会被 ReAct 调用
- `max_iterations` 有上限，validator 会对过大值给出 warning
- 每轮 action / observation 会发出 `react_iteration` 事件
- `failed` 或 `exhausted` 会进入步骤失败/重试处理，而不是被当作成功结果继续组合
- `ask` 和 `delete_knowledge` 的 retrieve 步已经启用 ReAct

当前 entry 编排分为 `EntryGraph -> PlanExecutionGraph -> ReactGraph` 三层。两个执行子图分别持有自己的 `ToolNode`，并通过 `tool_messages`、`pending_tool_call_id` 和 `pending_react_iteration` 保持可校验、可恢复边界。

### 5. `Replanner`

代码位置：[replanner.py](../../src/personal_agent/agent/replanner.py)

作用：

- 在步骤失败且 retry 耗尽后尝试重新规划
- 优先调用 LLM 生成替代步骤
- LLM 不可用或失败时，使用启发式补救计划
- 保留已完成步骤，只替换未完成或失败的后续步骤

默认步骤重试预算以 checkpoint-safe 状态保存：

```text
step.max_retries = 3
step.failure_reason
step.recoverable
```

## 当前执行路径

### entry 入口

1. `AgentRuntime.execute_entry()` 接收入口请求
2. `DefaultIntentRouter` 产出 `RouterDecision`
3. 若 `requires_planning=True`，`DefaultTaskPlanner` 生成 `PlanStep` 列表
4. `PlanValidator` 校验真实执行计划
5. 校验结果写入 `WorkingMemory.plan_steps`
6. 若 `requires_planning=False`，不生成正式计划，后续由 runtime 记录轻量 `execution_trace`

注意：

- 当前只有需要计划驱动的 entry 才会生成可执行 `plan_steps`
- 普通 `ask / capture / direct_answer` 使用 `execution_trace` 表达执行路径
- `PlanValidator` 已注入 `ToolExecutor`，工具校验不再依赖硬编码白名单

### 计划驱动执行

只有 `RouterDecision.requires_planning=True` 且存在有效步骤时，才进入 `PlanExecutor`。

当前主要覆盖：

- `delete_knowledge`
- `solidify_conversation`

其他意图走 entry orchestration graph 内置普通分支，并通过 `execution_trace` 可观测：

- `capture`
- `ask`
- `summarize`
- `direct_answer`
- `unknown`

### 计划与执行路径可观测

真实计划会进入：

- `WorkingMemory.plan_steps`
- `EntryResult.plan_steps`
- SSE `plan_created / plan_step_started / plan_step_completed / plan_step_failed / plan_execution_complete`
- 前端可折叠计划面板

非计划驱动路径会进入：

- `WorkingMemory.execution_trace`
- `EntryResult.execution_trace`
- SSE `execution_trace`
- 前端“Agent 执行路径”面板

这避免把不会被 `PlanExecutor` 执行的步骤展示成正式计划。

## 典型计划

### `delete_knowledge`

当前固化计划模板：

```text
retrieve -> resolve -> tool_call(delete_note) -> compose
```

含义：

- `retrieve`：检索候选笔记
- `resolve`：将模糊删除请求解析成具体 note_id
- `tool_call`：调用 `delete_note`；工具层创建确认请求并在恢复执行时校验确认载荷
- `compose`：生成删除结果摘要

`resolve` 当前会按顺序尝试：

- 图谱 episode UUID 映射本地 note
- 本地相似检索
- 关键词匹配
- 最近 citations

resolve 返回的候选笔记现已包含 `parent_note_id` / `parent_title`，前端可展示 chunk 所属的父文档。

高风险删除步骤当前由 LangGraph entry 总编排承载 HITL：`execute_plan_step` 收到 `delete_note` 返回的 pending confirmation 后，会进入 `confirm_step`，通过 `interrupt()` 暂停 run；前端确认或拒绝后调用 `/api/entry/runs/{run_id}/resume`，后端用 checkpoint 中的 `thread_id` 恢复同一个 graph run。`delete_note` 工具仍保留 `action_id / token`，作为确认载荷和工具层审计边界。

### `solidify_conversation`

当前启发式计划：

```text
compose -> tool_call(capture_text)
```

含义：

- `compose`：将近期候选会话以轮次标识提供给 LLM，由模型根据当前保存请求语义选择依据并生成入库草稿；无合格正文时不写入。同时从草稿中抽取候选结论（`candidate_conclusions`）并存入 `PostgresCrossSessionStore`
- `tool_call`：复用 `capture_text` 写入长期知识库；正文由执行器从上游 compose 结果注入
- `tool_call` 成功后自动回写：草稿标记为 `solidified`，关联候选结论同步切换已固化状态

当前 `compose` 还会产出 `draft_ready` 事件，并把草稿和候选结论保存到 `PostgresCrossSessionStore`。后续 `tool_call(capture_text)` 成功后，计划执行节点会完成 `draft → stored → solidified` 状态回写。

## 当前能力

- 已具备结构化 `PlanStep`
- 已具备 LLM 优先、启发式兜底的规划器
- 已具备动态工具列表注入
- 已具备执行前计划校验
- 已具备工具名动态校验，避免硬编码白名单漂移
- 已具备依赖图校验和循环依赖检测
- 已具备风险等级和确认要求校验
- 已具备工具治理交叉校验（工具固有 vs 步骤声明的 risk_level、requires_confirmation、writes_longterm、accesses_external）
- 已具备计划阶段 `tool_input` 深度参数校验（基于 LangChain 工具的 Pydantic schema）
- 已具备计划执行器和步骤状态机
- 已具备 SSE 进度事件和前端计划面板
- 已具备 `plan_steps` 与 `execution_trace` 语义拆分
- 已具备失败重试、依赖跳过、abort 和重规划
- 已具备删除目标解析链路
- 已具备固化草稿生成和注入 `capture_text` 的基础链路
- 已具备固化草稿状态回写闭环（draft → stored → solidified）
- 已具备候选结论抽取与固化同步标记

## 已知限制

### 1. LLM 规划输出仍依赖文本约束

虽然 planner 要求 LLM 输出 JSON，并且 validator 会做二次校验，但当前字段语义仍主要由 prompt 约束。复杂任务下可能出现：

- 步骤过泛
- 依赖不合理
- 工具输入不完整
- 风险等级低估

### 2. `PlanValidator` 深度参数校验仍可增强

`PlanValidator` 已基于 LangChain 工具 schema 对 `tool_call` 步骤的 `tool_input` 做前置校验，缺失必填字段或类型不匹配会生成阻断性 issue；实际调用由 `ToolNode` 再次校验参数。

当前校验覆盖 required 字段检查和基础类型匹配（string/boolean/integer/number），复杂嵌套结构校验仍需补充。

### 3. 审批和恢复已使用持久化 checkpoint

删除类操作已通过 LangGraph `interrupt/resume` 接入 checkpoint，当前 `confirm_step` 可以暂停 run，并在用户确认或拒绝后从同一个 `thread_id` 恢复。底层 `PostgresPendingActionStore` 仍承担 token、过期时间和审计载荷；checkpoint 由 `PostgresSaver` 写入与业务数据相同的 Postgres 数据库，支持跨进程恢复。

### 4. 重规划仍偏补救式

`Replanner` 能在失败后生成替代步骤，但当前更偏“失败后 salvage”，还不是完整的全局动态规划。比如：

- 未统一重新校验 revised steps
- 对已执行副作用的建模有限
- 对工具级权限和风险继承已有基础支持（LangChain 工具 `extras` governance 字段），但 revised steps 重新校验仍未统一

### 5. ReAct 单步策略已接入，仍需扩展

`PlanExecutor` 已能按 `execution_mode` 在确定性 handler 和 `ReActStepRunner` 之间分发。ReAct runner 当前定位为单步内部的受控检索/观察循环，而不是替代整个计划执行器。

已落地能力：

- `PlanStep.execution_mode / allowed_tools / max_iterations`
- `PlanValidator` 对 ReAct 的风险、确认、工具白名单和迭代上限校验
- `PlanExecutor._dispatch_step()` 的 ReAct 分支
- `ReActStepRunner` 的 Thought / Action / Observation 循环和 `react_iteration` 事件
- `tests/test_react_runner.py` 与 `tests/test_plan_executor.py::TestReActStepDispatch`

剩余改进主要是扩大适用步骤、沉淀更稳定的 ReAct prompt/事件 schema，并评估是否需要用 LangGraph `StateGraph` 重写 runner 内部状态机。

### 6. ~~graph state 中的计划步骤仍使用 dict~~（已通过 PlanStepState 强类型化解决）

`AgentGraphState.plan_steps` 已收敛为 `list[PlanStepState]`（Pydantic BaseModel），`_plan_step_to_dict()` / `_plan_step_from_dict()` 已移除。规划器产出 `PlanStep` 后通过 `PlanStepState.from_plan_step()` 写入 graph state，执行/校验/ReAct 节点通过 `sd.to_plan_step()` 获取业务对象，API 边界统一 `model_dump(mode="json")` 序列化。

## 演进方向

- 为规划层新增独立文档化的 plan schema，并让 LLM 输出更稳定
- 明确哪些 intent 必须由 `PlanExecutor` 驱动，逐步减少双轨执行
- 为 revised steps 增加重新校验流程
- ~~将 graph state 中的 `plan_steps: list[dict]` 收敛为强类型 `PlanStepState`~~（已完成）
- 基于 Postgres checkpoint 扩展多段审批和长任务恢复

## 下一步实现方案：重规划步骤复校验

目标：让 `Replanner` 产出的 revised steps 与初始 planner 产出的步骤走同一套 `PlanValidator` 安全门禁，避免失败补救步骤绕过工具存在性、参数 schema、风险等级、确认要求和权限治理。

### 1. 统一 revised plan 数据结构

让 `Replanner` 返回结构化结果：

```text
ReplanResult
  revised_steps
  reason
  preserved_step_ids
  replaced_step_ids
  risk_notes
```

`revised_steps` 必须继续使用 `PlanStep`，不要引入第二套 step schema。

### 2. 在 PlanExecutor 中接入复校验

在失败触发 replan 后，执行顺序改为：

```text
failed step
  -> Replanner.replan()
  -> PlanValidator.validate(revised_steps)
  -> 通过：替换后续未执行步骤
  -> warning：记录到 progress event / execution_trace
  -> blocking issue：放弃 revised steps，进入原有失败策略
```

保留已完成步骤，不允许 replan 修改已经产生副作用的步骤。

### 3. 风险和确认继承规则

新增明确规则：

- revised step 的 `risk_level` 不能低于被替换步骤和目标工具的固有风险
- 写长期知识或删除类工具必须保留 `requires_confirmation`
- `allowed_tools` 不能扩展到原计划未授权的高风险工具
- 外部访问工具必须保留 `accesses_external` warning

这些规则优先放在 `PlanValidator`，避免 executor 内散落安全逻辑。

### 4. 事件与可观测性

## 下一步实现方案：PlanStepState 强类型化

目标：把 graph checkpoint 状态中的 `plan_steps: list[dict]` 收敛成明确、可序列化、可校验的 `PlanStepState`，让计划步骤在 planner、validator、orchestration nodes、API 和前端之间共享同一套 schema。

### 1. 新增 checkpoint-safe 模型

在 `orchestration_models.py` 或独立 `plan_state.py` 中新增：

```text
PlanStepState
  step_id
  action_type
  description
  tool_name
  tool_input
  depends_on
  expected_output
  success_criteria
  risk_level
  requires_confirmation
  on_failure
  status
  retry_count
  execution_mode
  allowed_tools
  max_iterations
  validation_warnings
```

模型应使用 Pydantic `BaseModel`，保证 `model_dump(mode="json")` 可直接进入 checkpoint / API。

### 2. 明确与 `PlanStep` 的关系

短期保留 planner 输出 `PlanStep`：

```text
DefaultTaskPlanner -> list[PlanStep]
PlanStepState.from_plan_step()
AgentGraphState.plan_steps: list[PlanStepState]
```

业务执行需要 `PlanStep` 时，使用显式方法：

```text
PlanStepState.to_plan_step()
```

这样转换仍存在，但集中在模型方法中，不再散落 `_plan_step_to_dict()` / `_plan_step_from_dict()` helper。

### 3. 修改 graph state 和节点

- `AgentGraphState.plan_steps` 改为 `list[PlanStepState]`。
- `_node_plan_task()` 写入 `PlanStepState`。
- `_node_validate_plan()` 从 `PlanStepState` 转回 `PlanStep` 校验，再写回 `PlanStepState`。
- `select_next_step / execute_plan_step / handle_step_*` 直接访问强类型字段。
- API 返回时统一 `model_dump(mode="json")`。

### 4. 直接切换状态结构

不保留旧 `list[dict]` checkpoint 兼容。改造完成后，`AgentGraphState.plan_steps` 只接受 `list[PlanStepState]`，相关节点、API 映射和测试数据同步切换。

测试覆盖：

- 新 `PlanStepState` 可以 checkpoint roundtrip。
- planner 新增字段时 API、SSE、前端计划面板不丢字段。
- orchestration graph 中不再出现 `_plan_step_to_dict()` / `_plan_step_from_dict()`。

补充 replan 相关事件：

```text
plan_replan_attempt
plan_replanned
plan_replan_rejected
```

事件 payload 至少包含：

```text
failed_step_id
replaced_step_ids
new_step_ids
validation_issues
validation_warnings
reason
```

### 5. 测试落点

- revised steps 工具不存在时被阻断
- revised steps 缺少必填 `tool_input` 时被阻断
- revised steps 降低风险等级时被修正或阻断
- revised steps 尝试绕过确认删除时被阻断
- revised steps 通过校验后只替换未完成步骤
- `plan_replan_rejected` 事件 payload 包含校验问题
