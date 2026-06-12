# Workflow / Step Projection 不兼容重构计划

## 背景

当前工程已经是 workflow-first 架构：`delete_knowledge`、`solidify_conversation` 等已知业务流程由 `WorkflowSpec / WorkflowStepSpec` 固定声明，再确定性投影成运行时步骤，并进入 LangGraph checkpoint-safe 的步骤执行循环。

问题不在能力本身，而在命名和边界仍大量沿用 `plan / planner / planning`：

- `DefaultTaskPlanner` 实际不是 planner，而是 workflow step projector。
- `PlanStep / PlanStepState / PlanSubState` 实际是执行步骤、步骤运行态和步骤执行态。
- `requires_planning` 实际表示是否需要 step projection。
- `plan_execution_graph` 实际是 step execution graph。
- API / SSE / 前端仍叫 `plan_steps / plan_created`，容易让人误以为步骤来自 LLM 自主规划。

本计划按“不考虑兼容性”重新设计：不保留旧字段、不加 alias、不做双写、不支持旧 checkpoint 回放。目标是一次性把 workflow projection 和真正 dynamic planning 拆开。

## 核心判断

当前系统不应该继续把固定 workflow 的步骤投影叫 planning。

重构后语义变为：

```text
WorkflowSpec
  -> WorkflowStepProjector
  -> ExecutionStep
  -> StepProjectionValidator
  -> StepExecutionGraph

Future DynamicPlanner
  -> DynamicPlan
  -> PlanDAGValidator
  -> ExecutionStep
  -> StepExecutionGraph
```

关键边界：

- Workflow 是已知业务流程真源。
- Step Projection 是 workflow 的运行时步骤视图。
- Step Execution Graph 是所有步骤的统一执行器。
- Dynamic Planning 是未来开放式低风险任务的独立 step 来源。
- 高风险已知流程永远优先走 `WorkflowSpec`，不交给 dynamic planner。

## 非兼容原则

这次重构不做兼容层：

- 不保留 `DefaultTaskPlanner / TaskPlanner / PlanValidator` alias。
- 不保留 `PlanStep / PlanStepState / PlanSubState` 旧模型名。
- 不保留 `AgentGraphState.plan`。
- 不保留 `RouterDecision.requires_planning`。
- 不保留 `EntryResult.plan_steps`。
- 不保留 `plan_created / plan_validated` SSE 事件。
- 不保留 `plan_execution_graph` 节点名。
- 不保证旧 checkpoint、旧 run snapshot、旧前端和旧 API 客户端可用。

这意味着该重构必须作为一次破坏性版本升级执行，并配套：

- 清空或迁移 LangGraph checkpoint 表。
- 更新前端调用和展示字段。
- 更新 API 文档和测试快照。
- 重新生成 Mermaid 图。
- 重新跑全量测试。

## 目标命名

| 当前名称 | 新名称 | 说明 |
| --- | --- | --- |
| `planner.py` | `step_projector.py` | 只负责 workflow step projection |
| `DefaultTaskPlanner` | `WorkflowStepProjector` | 删除旧类名 |
| `TaskPlanner` | `StepProjector` | 协议名改为真实职责 |
| `PlanStep` | `ExecutionStep` | 中性步骤模型，可承接 workflow projection 和未来 dynamic plan |
| `PlanStepState` | `StepRunState` | checkpoint 中单步骤运行态 |
| `PlanSubState` | `StepExecutionState` | checkpoint 中步骤执行子状态 |
| `plan_validator.py` | `step_projection_validator.py` | 校验投影步骤，不叫 plan validator |
| `PlanValidator` | `StepProjectionValidator` | 删除旧类名 |
| `AgentGraphState.plan` | `AgentGraphState.step_execution` | 删除旧字段 |
| `plan.step_results` | `step_execution.results` | 步骤结果通道 |
| `requires_planning` | `requires_step_projection` | router 控制字段 |
| `plan_steps` | `steps` | API / 前端统一字段 |
| `plan_execution_graph` | `step_execution_graph` | LangGraph 子图名 |
| `build_plan_execution_graph()` | `build_step_execution_graph()` | 删除旧函数名 |
| `plan_task` | `project_workflow_steps` | 节点表达真实动作 |
| `validate_plan` | `validate_projected_steps` | 节点表达真实动作 |
| `execute_plan_step` | `execute_step` | 步骤执行节点 |
| `consume_plan_tool_result` | `consume_step_tool_result` | 工具结果消费节点 |
| `finalize_plan_execution` | `finalize_step_execution` | 步骤执行收束 |
| `plan_created` | `steps_projected` | SSE / AgentEvent |
| `plan_validated` | `steps_validated` | SSE / AgentEvent |

保留 `DynamicPlanner / DynamicPlan / PlanDAGValidator` 这些名字给未来真正 planning 能力使用。也就是说，`plan` 这个词只允许出现在 dynamic planning 模块，不再出现在固定 workflow projection 主路径。

## 目标目录

```text
src/personal_agent/agent/
  workflow.py
  workflow_validator.py
  step_projector.py
  step_projection_validator.py
  step_execution_graph.py
  step_execution_models.py
  dynamic_planning.py              # 未来预留，不默认启用
  dynamic_plan_validator.py        # 未来预留，不默认启用
  orchestration_graph.py
  orchestration_nodes/
    _entry.py
    _steps.py
    _react.py
```

如果不想立即拆文件，也必须先完成类名、字段名和 graph node 名称替换；文件拆分可以在同一个版本内完成，但不能留下旧导出。

## 目标运行链路

```text
EntryInput
  -> normalize_entry
  -> route_intent
  -> branch workflow
       ask / capture / summarize / direct_answer
  -> step projection workflow
       project_workflow_steps
       validate_projected_steps
       prepare_step_execution
       select_next_step
       execute_step
          -> react_graph?
          -> step_tool_node?
          -> confirm_step?
       consume_step_tool_result
       handle_step_success / handle_step_failure
       finalize_step_execution
  -> finalize_entry_result
```

普通 `ask / capture / summarize / direct_answer` 仍然是 workflow，但不进入 step projection。`delete_knowledge / solidify_conversation` 因为需要 HITL、checkpoint 恢复、前端展示和结构化步骤结果，才进入 step projection。

## 破坏性改造阶段

### P0：建立破坏性改造基线

目标：明确这不是兼容迁移。

改动：

1. 在本计划、README、runtime 文档中声明旧 `plan_*` checkpoint/API 不兼容。
2. 新增升级说明：改造版本需要清空 checkpoint 表或执行一次性数据迁移。
3. 冻结功能改动，避免和命名重构混在一起。
4. 列出所有旧命名扫描项，作为后续验收基线。

验收：

- 文档明确“不支持旧 checkpoint replay”。
- issue / PR 描述明确这是 breaking change。
- `rg "DefaultTaskPlanner|PlanStep|requires_planning|plan_steps|plan_execution_graph"` 作为待清单，而不是兼容承诺。

### P1：模型与路由字段一次性改名

目标：先改核心数据模型，让旧语义无法继续传播。

改动：

1. `planner.py` 改为 `step_projector.py`。
2. `DefaultTaskPlanner` 改为 `WorkflowStepProjector`。
3. `TaskPlanner` 改为 `StepProjector`。
4. `PlanStep` 改为 `ExecutionStep`。
5. `PlanStepState` 改为 `StepRunState`。
6. `PlanSubState` 改为 `StepExecutionState`。
7. `AgentGraphState.plan` 改为 `AgentGraphState.step_execution`。
8. `step_results` 挪到 `state.step_execution.results`。
9. `RouterDecision.requires_planning` 改为 `requires_step_projection`。
10. router JSON schema、prompt、默认决策全部替换为新字段。

不做：

- 不保留旧字段。
- 不写 `@property plan`。
- 不做 `model_validator` 兼容旧 checkpoint。

验收：

- 代码中不再存在核心旧类名。
- 新建 checkpoint 只写 `step_execution`。
- router 输出不再包含 `requires_planning`。

### P2：Validator / Graph / Node 一次性改名

目标：执行图语义从 plan 彻底切到 step execution。

改动：

1. `plan_validator.py` 改为 `step_projection_validator.py`。
2. `PlanValidator` 改为 `StepProjectionValidator`。
3. `build_plan_execution_graph()` 改为 `build_step_execution_graph()`。
4. 子图名 `plan_execution_graph` 改为 `step_execution_graph`。
5. graph node 改名：
   - `plan_task` -> `project_workflow_steps`
   - `validate_plan` -> `validate_projected_steps`
   - `prepare_plan_execution` -> `prepare_step_execution`
   - `execute_plan_step` -> `execute_step`
   - `plan_tool_node` -> `step_tool_node`
   - `consume_plan_tool_result` -> `consume_step_tool_result`
   - `finalize_plan_execution` -> `finalize_step_execution`
6. `_after_validate_plan` 改为 `_after_validate_projected_steps`。
7. 日志、事件 payload、snapshot 字段同步改名。

不做：

- 不保留旧 node name。
- 不让 Mermaid 图继续出现 `plan_execution_graph`。

验收：

- `draw_entry_graph.py` 生成图中只出现 `step_execution_graph`。
- graph snapshot、history 摘要只出现 step execution 术语。
- 所有 graph 单元测试通过。

### P3：API / SSE / 前端破坏性切换

目标：对外接口不再暴露 `plan_*`。

改动：

1. `EntryResult.plan_steps` 改为 `EntryResult.steps`。
2. run snapshot 中 `plan` 改为 `step_execution`。
3. history 摘要中 `plan` 相关字段改为 step 字段。
4. SSE 事件改名：
   - `plan_created` -> `steps_projected`
   - `plan_validated` -> `steps_validated`
   - `plan_step_started` -> `step_started`
   - `plan_step_completed` -> `step_completed`
   - `plan_step_failed` -> `step_failed`
5. API 文档删除 `plan_steps`。
6. 前端计划面板改名为“执行步骤”或 “Workflow Steps”。
7. 前端类型、组件、状态管理和测试全部切到 `steps`。

不做：

- 不返回 `plan_steps`。
- 不兼容旧 SSE 事件名。
- 不保留 deprecated 字段。

验收：

- API response 中没有 `plan_steps`。
- 前端不再订阅 `plan_created`。
- 端到端删除确认和 solidify 草稿仍可展示。

### P4：删除旧 checkpoint 与脚本假设

目标：接受 checkpoint schema 破坏，确保新现场干净。

改动：

1. 增加一次性运维步骤：
   - 开发 / 测试环境：清空 LangGraph checkpoint 表。
   - 生产环境：停机窗口内导出必要审计，再清空或归档 checkpoint。
2. `export_thread_checkpoints.py` 输出新字段名。
3. `replay_from_checkpoint()` 文档说明：只能 replay 新版本 checkpoint。
4. run history 摘要使用 `step_execution`。
5. replay updates 白名单改为新字段路径。

不做：

- 不从旧 `plan` checkpoint 自动迁移。
- 不支持旧 checkpoint replay。

验收：

- 新 checkpoint export 可读。
- replay_from_checkpoint 能从新 `step_execution` 状态 fork。
- 旧 checkpoint replay 失败时错误信息明确提示版本不兼容。

### P5：测试与评测改名

目标：测试表达真实边界。

改动：

1. `test_planner.py` 改为 `test_step_projector.py`。
2. `test_plan_validator.py` 改为 `test_step_projection_validator.py`。
3. `test_plan_replan.py` 只保留真正 dynamic planning 相关内容；当前 workflow projection eval 改名。
4. regression 测试从 “plan execution graph” 改为 “step execution graph”。
5. 删除所有断言 `requires_planning / plan_steps / plan_created` 的测试。
6. 新增断言：
   - delete/solidify 触发 `requires_step_projection=True`
   - branch workflow 不生成 `steps`
   - `steps_projected` 事件存在
   - `step_execution.results` 能动态注入 tool args

验收：

- 全量测试通过。
- `rg "requires_planning|plan_steps|plan_created|plan_execution_graph|DefaultTaskPlanner|PlanStep|PlanValidator" tests src` 无命中，除非在 dynamic planning 未来模块中合理出现。

### P6：文档与 Mermaid 一次性收口

目标：文档不再解释“历史命名”，因为旧命名已经消失。

改动：

1. `docs/topics/planning.md` 改名为 `docs/topics/workflow-step-projection.md`。
2. 新增 `docs/topics/dynamic-planning.md`，说明未来真正 planning 的触发条件、禁用场景和 guardrail。
3. runtime、workflow、tools、interview 文档删除“历史字段名 / 兼容名”表述。
4. Mermaid 图重新生成到 `docs/mermaid/entry-orchestration.md`。
5. README 链接更新。

验收：

- 文档中不再说 `plan_execution_graph` 是历史命名。
- 文档中不再说 `DefaultTaskPlanner` 是兼容名。
- 固定 workflow 文档只使用 step projection 术语。

## Dynamic Planning 保留位置

不兼容重构不等于移除真正 plan 能力。相反，它把真正 planning 的名字腾出来。

未来 dynamic planning 应作为独立模块：

```python
class DynamicPlanner:
    def plan(self, goal: str, context: PlanningContext) -> DynamicPlan:
        ...

class DynamicPlan:
    plan_id: str
    steps: list[ExecutionStep]
    rationale: str
    risk_level: str
    requires_approval: bool

class PlanDAGValidator:
    def validate(self, plan: DynamicPlan, tools: ToolRegistry) -> ValidationResult:
        ...
```

触发条件：

- router 无法映射到固定 workflow。
- 用户目标低风险。
- 工具 allowlist 不含写入、删除、外发、生产变更等高风险动作。
- 配置显式启用 dynamic planning。
- 有专项 eval 覆盖。

禁止场景：

- `delete_knowledge`
- `restore_note`
- `solidify_conversation` 的长期写入主干
- 外发消息、付款、生产变更、跨用户数据操作
- 权限不明确的工具组合

Dynamic planner 输出仍必须转换为 `ExecutionStep`，进入同一个 `StepExecutionGraph`，并经过 ToolGateway、HITL、幂等、审计和 checkpoint。

## 执行顺序建议

推荐按下面顺序落地，避免同时破坏太多未知面：

1. P0：确认 breaking change 边界，冻结功能开发。
2. P1：改模型和 router 字段。
3. P2：改 graph / node / validator 命名。
4. P3：改 API / SSE / 前端。
5. P4：清理 checkpoint 和 replay 语义。
6. P5：改测试与 eval。
7. P6：重刷文档和 Mermaid。

虽然这是不兼容重构，但仍应分 PR 执行。区别是每个 PR 都面向新世界收敛，不引入 alias 和双字段。

## 风险

### 风险 1：旧 checkpoint 全部失效

接受该风险。处理方式是停机窗口归档旧 checkpoint，并明确新版本只支持新 checkpoint。

### 风险 2：前端和 API 同步破坏

接受该风险。后端、前端和 API 文档必须同版本发布。

### 风险 3：大范围重命名引入行为回归

缓解方式不是兼容层，而是：

- 先锁定行为测试。
- 每阶段跑全量测试。
- 用 delete/solidify 端到端场景验收。
- 重放新版本 checkpoint 验证 HITL resume。

### 风险 4：把 dynamic planning 空间也删掉

通过命名边界避免：固定 workflow 主路径不用 plan；`DynamicPlanner / DynamicPlan / PlanDAGValidator` 专门留给未来真正规划能力。

## 最终验收

代码验收：

```text
rg "DefaultTaskPlanner|TaskPlanner|PlanStep|PlanStepState|PlanSubState|PlanValidator" src tests
rg "requires_planning|plan_steps|plan_created|plan_validated|plan_execution_graph" src tests frontend
```

期望：固定 workflow 主路径无命中。若未来 dynamic planning 模块出现 `DynamicPlan / PlanDAGValidator`，必须只位于 dynamic planning 边界内。

行为验收：

- `ask / capture / summarize / direct_answer` 不返回 `steps`。
- `delete_knowledge` 返回 `steps`，包含 retrieve / resolve / tool_call / compose。
- `solidify_conversation` 返回 `steps`，包含 compose / tool_call。
- 删除确认仍能 interrupt / resume。
- `step_execution.results` 能把 resolve 的 `note_id` 注入 delete 工具。
- `step_execution.results` 能把 solidify 草稿注入 capture 工具。
- ReAct 仍只能在单个低风险 step 内运行。
- 高风险工具仍必须经过 ToolGateway、HITL 和幂等账本。

文档验收：

- README、runtime、workflow、tools、interview 全部使用 Workflow / Step Projection 术语。
- `planning` 只出现在 `dynamic-planning.md` 或未来 dynamic planning 设计中。
- Mermaid 图只显示 `step_execution_graph`。

## 推荐一句话

> 这次不兼容重构的目标不是删掉规划能力，而是把“固定 workflow 的步骤投影”和“未来真正 dynamic planning”彻底拆开：当前生产主路径只叫 Workflow / Step Projection，`plan` 这个词只留给未来由模型动态生成 DAG 的低风险开放式任务。
