# ADR 0016：分离 Plan 控制与具体动作执行

2026-08-30 决定。动作参数与 Plan 状态继续各负其责。活动项可选、进度可修订以及新计划的边界由 [ADR 0025](0025-revisable-plan-progress.md)更新。

## 背景与决定

研究用例已经执行真实搜索，仍因 `plan_step_binding_required`、`working_plan_no_change` 和 Final 步骤枚举无法交付。旧协议要求模型在每次业务动作中重复编码 Plan 外键。

删除 Tool 和 Agent 动作中的模型侧 `plan_step_id`。模型通过独立 Plan 操作维护步骤，运行系统有活动步骤时从已接纳状态关联执行事实。移除答复中的步骤枚举。Verification、Completion 和 Plan 进度由各自入口处理。复用原 Journal 和执行网关。

初版要求可执行 Plan 恰有一个活动步骤，并限制已完成步骤的修改。这两项历史约束后来移除。初版最终成文采用 [ADR 0017](0017-separate-action-selection-from-final-delivery.md)的两阶段协议，现行提交由 [ADR 0045](0045-native-intent-loop-and-recorded-model-output.md)和 [ADR 0055](0055-unified-conversation-answer.md)决定。

## 历史证据

clean 基线 `c66fe9455d723e47ca3956e7a85980bb559c4eb7` 的归档 `20260829T134532.983717Z-22796-e4dc8084` 中，四次工具成功但未交付。隔离 Schema 对照为 3/3，定向 dirty target 交付 1/1。后续 `HARNESS-003` 证明 Plan 与执行事实可跨进程恢复，在进一步的交付协议验证中得到用户结果。这些轨迹保留各自身份，单独移除逐动作绑定的因果对照未完成。[历史评测盘点](../evals/02-current-case-inventory.md)
