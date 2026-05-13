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
3. `DefaultTaskPlanner` 生成 `PlanStep` 列表
4. `PlanValidator` 校验计划
5. 校验结果写入 `WorkingMemory.plan_steps`
6. 计划通过 API / SSE 返回给前端展示

注意：

- 当前所有 entry 都会生成可观测计划
- 但不是所有 entry 都由 `PlanExecutor` 驱动执行
- `PlanValidator` 已注入 `ToolRegistry`，工具校验不再依赖硬编码白名单

### 计划驱动执行

只有 `RouterDecision.requires_planning=True` 且存在有效步骤时，才进入 `PlanExecutor`。

当前主要覆盖：

- `delete_knowledge`
- `solidify_conversation`

其他意图仍走稳定的 LangGraph 固定分支：

- `capture`
- `ask`
- `summarize`
- `direct_answer`
- `unknown`

### 计划可观测

计划会进入：

- `WorkingMemory.plan_steps`
- `EntryResult.plan_steps`
- SSE `plan_created / plan_step_started / plan_step_completed / plan_step_failed / plan_execution_complete`
- 前端可折叠计划面板

这意味着计划既参与 prompt 上下文，也会作为用户可见的执行结构返回给 Web 前端。

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

### `solidify_conversation`

当前启发式计划：

```text
retrieve -> compose -> verify -> tool_call(capture_text)
```

含义：

- `retrieve`：加载最近对话，抽取候选事实和结论
- `compose`：生成适合入库的知识文本草稿
- `verify`：检查草稿准确性和完整性
- `tool_call`：复用 `capture_text` 写入长期知识库

当前 `compose` 还会产出 `draft_ready` 事件，并把草稿保存到 `CrossSessionStore`。

## 当前能力

- 已具备结构化 `PlanStep`
- 已具备 LLM 优先、启发式兜底的规划器
- 已具备动态工具列表注入
- 已具备执行前计划校验
- 已具备工具名动态校验，避免硬编码白名单漂移
- 已具备依赖图校验和循环依赖检测
- 已具备风险等级和确认要求校验
- 已具备计划执行器和步骤状态机
- 已具备 SSE 进度事件和前端计划面板
- 已具备失败重试、依赖跳过、abort 和重规划
- 已具备删除目标解析链路
- 已具备固化草稿生成和注入 `capture_text` 的基础链路

## 已知限制

### 1. 计划不是所有任务的真实执行引擎

当前 `capture / ask / summarize / direct_answer / unknown` 仍主要走 LangGraph 固定分支。它们会生成计划并展示，但真正执行不完全由 `PlanExecutor` 驱动。

这让系统更稳，但也意味着计划和真实执行链路之间仍存在双轨。

### 2. `ask` 的外部搜索规划还缺失

当前 `ask` 计划默认是：

```text
retrieve -> compose -> verify
```

检索主要面向个人知识图谱和本地记忆。若图谱和本地记忆无法匹配，且 LLM 判断不应直接回答，规划层还没有 `web_search` 步骤可选。

后续需要结合工具层新增 `web_search`，并让 planner 能生成类似：

```text
graph_search/local_retrieve -> web_search -> compose -> verify
```

### 3. LLM 规划输出仍依赖文本约束

虽然 planner 要求 LLM 输出 JSON，并且 validator 会做二次校验，但当前字段语义仍主要由 prompt 约束。复杂任务下可能出现：

- 步骤过泛
- 依赖不合理
- 工具输入不完整
- 风险等级低估

### 4. `PlanValidator` 还没有深度参数校验

当前 validator 能校验工具是否存在，但没有基于 `ToolSpec.input_schema` 对 `tool_input` 做完整 schema 校验。

因此一些参数错误会延迟到工具执行阶段才暴露。

### 5. 审批和恢复还不是 checkpoint 级别

删除类操作使用 `PendingActionStore` 做应用层两阶段确认，但当前没有引入 LangGraph checkpoint。多段审批或长时间中断恢复能力仍有限。

### 6. 重规划仍偏补救式

`Replanner` 能在失败后生成替代步骤，但当前更偏“失败后 salvage”，还不是完整的全局动态规划。比如：

- 未统一重新校验 revised steps
- 对已执行副作用的建模有限
- 对工具级权限和风险继承还不完整

## 演进方向

- 为规划层新增独立文档化的 plan schema，并让 LLM 输出更稳定
- 将 `ToolSpec.input_schema` 接入 `PlanValidator`
- 引入 `web_search` 作为 ask 低置信度兜底步骤
- 明确哪些 intent 必须由 `PlanExecutor` 驱动，逐步减少双轨执行
- 为 revised steps 增加重新校验流程
- 为多段审批和长任务恢复评估 LangGraph checkpoint
- 补充 `entry -> router -> planner -> validator -> executor -> replanner -> fallback` 的回归评测样本

