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
- 将 `ToolRegistry.list_tools()` 注入规划 prompt，让 planner 感知当前可用工具

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
- `tool_call`：调用 `ToolRegistry.execute()`
- `compose`：生成回答、删除摘要或固化草稿
- `verify`：校验回答或执行结果

`PlanStep` 已支持可选执行策略字段：

```text
execution_mode = "deterministic" | "react"
allowed_tools = [...]
max_iterations = 3
```

`execution_mode="react"` 的步骤会交给 `ReActStepRunner` 进入小范围 Thought / Action / Observation 循环；其他步骤继续走确定性 handler。`PlanExecutor` 仍负责全局依赖、状态推进、失败处理和审计，ReAct 只作为单步内部策略。

当前实现约束：

- `allowed_tools` 为空时默认只允许只读检索工具（`graph_search / web_search`）
- 高风险、写长期知识和确认类工具不会被 ReAct 调用
- `max_iterations` 有上限，validator 会对过大值给出 warning
- 每轮 action / observation 会发出 `react_iteration` 事件
- `ask` 和 `delete_knowledge` 的 retrieve 步已经启用 ReAct

当前 `ReActStepRunner` 是工程内自定义受控 runner，直接复用 `ToolRegistry.execute()`，没有把整个 `PlanExecutor` 替换成不透明 agent。这样可以获得动态观察能力，同时保留规划层已有的可校验和可回放边界。

### 5. `Replanner`

代码位置：[replanner.py](../../src/personal_agent/agent/replanner.py)

作用：

- 在步骤失败且 retry 耗尽后尝试重新规划
- 优先调用 LLM 生成替代步骤
- LLM 不可用或失败时，使用启发式补救计划
- 保留已完成步骤，只替换未完成或失败的后续步骤

当前默认最大重试次数：

```text
MAX_RETRIES = 3
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
- `PlanValidator` 已注入 `ToolRegistry`，工具校验不再依赖硬编码白名单

### 计划驱动执行

只有 `RouterDecision.requires_planning=True` 且存在有效步骤时，才进入 `PlanExecutor`。

当前主要覆盖：

- `delete_knowledge`
- `solidify_conversation`

其他意图仍走稳定的 LangGraph 固定分支，并通过 `execution_trace` 可观测：

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

当前启发式计划：

```text
retrieve -> resolve -> verify -> tool_call(delete_note) -> compose
```

含义：

- `retrieve`：检索候选笔记
- `resolve`：将模糊删除请求解析成具体 note_id
- `verify`：检查误删风险，并要求确认
- `tool_call`：调用 `delete_note`
- `compose`：生成删除结果摘要

`resolve` 当前会按顺序尝试：

- 图谱 episode UUID 映射本地 note
- 本地相似检索
- 关键词匹配
- 最近 citations

resolve 返回的候选笔记现已包含 `parent_note_id` / `parent_title`，前端可展示 chunk 所属的父文档。

### `solidify_conversation`

当前启发式计划：

```text
retrieve -> compose -> verify -> tool_call(capture_text)
```

含义：

- `retrieve`：加载最近对话，抽取候选事实和结论
- `compose`：生成适合入库的知识文本草稿，同时从草稿中抽取候选结论（`candidate_conclusions`）并存入 `CrossSessionStore`
- `verify`：检查草稿准确性和完整性
- `tool_call`：复用 `capture_text` 写入长期知识库
- `tool_call` 成功后自动回写：草稿标记为 `solidified`，关联候选结论同步切换已固化状态

当前 `compose` 还会产出 `draft_ready` 事件，并把草稿和候选结论保存到 `CrossSessionStore`。`tool_call` 成功后 `PlanExecutor` 自动完成 `draft → stored → solidified` 状态回写。

## 当前能力

- 已具备结构化 `PlanStep`
- 已具备 LLM 优先、启发式兜底的规划器
- 已具备动态工具列表注入
- 已具备执行前计划校验
- 已具备工具名动态校验，避免硬编码白名单漂移
- 已具备依赖图校验和循环依赖检测
- 已具备风险等级和确认要求校验
- 已具备工具治理交叉校验（工具固有 vs 步骤声明的 risk_level、requires_confirmation、writes_longterm、accesses_external）
- 已具备计划阶段 `tool_input` 深度参数校验（基于 `ToolSpec.input_schema`）
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

`PlanValidator` 已基于 `ToolSpec.input_schema` 对 `tool_call` 步骤的 `tool_input` 做前置校验，缺失必填字段或类型不匹配会生成阻断性 issue。`ToolRegistry.execute()` 也默认启用 schema 校验，工具执行前即暴露参数错误。

当前校验覆盖 required 字段检查和基础类型匹配（string/boolean/integer/number），复杂嵌套结构校验仍需补充。

### 3. 审批和恢复还不是 checkpoint 级别

删除类操作使用 `PendingActionStore` 做应用层两阶段确认，但当前没有引入 LangGraph checkpoint。多段审批或长时间中断恢复能力仍有限。

### 4. 重规划仍偏补救式

`Replanner` 能在失败后生成替代步骤，但当前更偏“失败后 salvage”，还不是完整的全局动态规划。比如：

- 未统一重新校验 revised steps
- 对已执行副作用的建模有限
- 对工具级权限和风险继承已有基础支持（`ToolSpec` governance 字段），但 revised steps 重新校验仍未统一

### 5. ReAct 单步策略已接入，仍需扩展

`PlanExecutor` 已能按 `execution_mode` 在确定性 handler 和 `ReActStepRunner` 之间分发。ReAct runner 当前定位为单步内部的受控检索/观察循环，而不是替代整个计划执行器。

已落地能力：

- `PlanStep.execution_mode / allowed_tools / max_iterations`
- `PlanValidator` 对 ReAct 的风险、确认、工具白名单和迭代上限校验
- `PlanExecutor._dispatch_step()` 的 ReAct 分支
- `ReActStepRunner` 的 Thought / Action / Observation 循环和 `react_iteration` 事件
- `tests/test_react_runner.py` 与 `tests/test_plan_executor.py::TestReActStepDispatch`

剩余改进主要是扩大适用步骤、沉淀更稳定的 ReAct prompt/事件 schema，并评估是否需要用 LangGraph `StateGraph` 重写 runner 内部状态机。

## 演进方向

- 为规划层新增独立文档化的 plan schema，并让 LLM 输出更稳定
- 明确哪些 intent 必须由 `PlanExecutor` 驱动，逐步减少双轨执行
- 为 revised steps 增加重新校验流程
- 为多段审批和长任务恢复评估 LangGraph checkpoint

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
