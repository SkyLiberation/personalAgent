# delete_knowledge Workflow

`delete_knowledge` 是当前项目的高风险 step projection workflow。它的目标不是让模型直接删除知识，而是把“用户想删什么”拆成可审计的步骤：先召回候选，再解析目标，最后经 HITL 确认后调用删除工具。

对应代码：

- [workflow.py](../../src/personal_agent/agent/workflow.py)：`DeleteKnowledge WorkflowSpec`
- [step_projector.py](../../src/personal_agent/agent/step_projector.py)：把 workflow 确定性投影成 `ExecutionStep`
- [step_projection_validator.py](../../src/personal_agent/agent/step_projection_validator.py)：执行前校验步骤、工具、风险和确认要求
- [orchestration_nodes/_steps.py](../../src/personal_agent/agent/orchestration_nodes/_steps.py)：步骤执行、确认暂停、工具结果消费
- [delete_note.py](../../src/personal_agent/tools/delete_note.py)：真实删除工具入口

## 固定拓扑

```text
delete_knowledge
  del-1 retrieve
    -> del-2 resolve
    -> del-3 tool_call(delete_note, high risk, HITL required)
    -> del-4 compose
```

这个拓扑来自 `WorkflowSpec`，不是 LLM 动态生成。LLM 只允许出现在执行期的语义决策节点，例如 `delete_target_resolve` 的候选选择。

## Step 契约

| Step | 类型 | 作用 | 关键契约 |
| --- | --- | --- | --- |
| `del-1` | `retrieve` | 用图谱和本地语义匹配检索候选笔记 | `execution_mode=react`，只允许 `graph_search`，无候选时走 clarification |
| `del-2` | `resolve` | 从候选中确定真实 `note_id` | 先用 graph episode 映射回本地 note；无映射时用 LLM 在本地候选中选择；不确定则不删除 |
| `del-3` | `tool_call` | 请求确认并执行 `delete_note` | `risk_level=high`，`requires_confirmation=True`，`side_effects=delete_longterm`，用户拒绝则 abort |
| `del-4` | `compose` | 生成删除结果摘要 | 消费工具 artifact，输出已删除、待确认、取消或失败说明 |

## 执行细节

1. Router 把用户输入归类为 `delete_knowledge`，并设置高风险、需要 step projection。
2. `WorkflowStepProjector` 从 `WORKFLOW_REGISTRY` 取出 `delete_knowledge` spec，确定性生成 4 个 `ExecutionStep`。
3. `StepProjectionValidator` 校验必须包含 `tool_call(delete_note)`，且高风险删除必须要求确认。
4. `del-1` 进入 retrieve，调用 graph/local 检索得到候选线索。
5. `del-2` resolve 尝试通过 `related_episode_uuids` 反查本地 note；如果不可用，再让 LLM 在最近本地 note 列表里选择唯一候选。
6. `del-3` 的工具输入由 `del-2` 动态注入 `note_id/title/summary/user_id`。
7. `delete_note` 首次调用返回 `pending_confirmation=True`，图层把它转换成 `confirmation_required` 事件并进入 `interrupt()`。
8. 用户确认后 resume，`confirm_step` 带 `confirmed=True` 和确定性 `idempotency_key` 重新调度 `delete_note`。
9. 工具真实删除本地 note/chunk，并清理可映射的 graph episode。
10. `del-4` 汇总结果，`finalize_step_execution` 生成最终回答和 `execution_trace`。

## HITL 与安全边界

- 删除长期知识必须经过 `ToolGateway` 和 `PolicyEngine`，不是由 planner 或 LLM 直接改库。
- `del-3` 是唯一有长期删除副作用的步骤，且被 spec、validator、tool metadata 三层标记为高风险。
- 用户拒绝确认时，当前步骤标记为 `skipped`，依赖步骤被跳过，workflow 进入取消结果。
- 确认 resume 会设置 `idempotency_key`，降低重复提交造成二次删除的风险。

## 失败分支

| 场景 | 处理 |
| --- | --- |
| 没有候选 | `del-1 / del-2` 走 clarification，提示用户提供更具体标题或内容 |
| 多候选或不确定 | `del-2` 不生成删除目标，要求用户进一步选择 |
| 用户拒绝确认 | `del-3` abort，返回操作已取消 |
| 工具删除失败 | 记录 `tool_result` / `step_failed`，进入 failure handler |
| graph 残留 | 删除工具尽力清理 graph episode；后续 graph reconcile 可继续发现 orphan |

## 面试讲法

可以说：删除知识不是“LLM 判断完直接删”，而是固定 workflow：retrieve 只找候选，resolve 只解析目标，真实删除副作用必须经过 `delete_note` 工具、PolicyEngine 和 HITL 确认。确认后执行的是软删除并写入删除快照，这样把语义判断和高风险副作用隔离开，既可恢复，也可审计。
