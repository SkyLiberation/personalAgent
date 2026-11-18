# ADR 0001：最小可恢复知识生命周期操作

2026-07-24 决定，2026-08-11 修订。删除与恢复共用受治理生命周期，现行路径见[知识删除流程](../workflow/delete-knowledge-workflow.md)。

## 背景与决定

直接删除无法同时保证确认前零写入、重启后继续、重复提交只执行一次，以及精确恢复 Item 和 Claim 的原状态。旧 Procedure、快照入口、六张专用表和两类 digest 承担重复职责。

`KnowledgeLifecycleService` 拥有删除和恢复的 Application 写入口。准备阶段冻结 immutable Command；决策入口校验认证主体、状态、命令 ID 和确认引用。服务端摘要绑定命令和回执，确认后在同一事务提交知识状态变化及 Receipt。重复确认返回原结果，恢复只接受已执行的删除 Receipt，按其中记录还原原状态。Personal Knowledge 继续拥有 Item、Claim 与状态事件。

分别保留 typed 删除和恢复契约，共用 operation 与 receipt 表。删除通用 Procedure、无消费的生命周期事件和第二套 digest。原快照表只保留运维导出与清理责任。[存储实现](../../src/personal_agent/infra/storage/postgres_knowledge_lifecycle_store.py)

## 验证与迁移例外

E04/E10 的原验证覆盖确认前零写入、重启接续、重复确认、跨主体拒绝和恢复原状态。GOV-002 的旧入口在合法确认请求时返回 422，迁移后同目标通过。历史成绩按原入口和配置解释。[评测盘点](../evals/02-current-case-inventory.md)

旧六表迁移的最晚移除日为 2026-10-31。当前存储初始化仍调用 `_migrate_legacy_tables`。各部署的旧表状态待核实。[迁移规则](../devSpec/migration-release.md#1-迁移与兼容边界)
