# ADR 0002：Investigation Project 聚合与 Journal

2026-07-27 决定，2026-08-26 随 [ADR 0015](0015-withdraw-investigation-project.md)撤回。

## 原决定

旧后台调查使用专用聚合，Project Service 唯一写入定义和计划，PostgreSQL 保存事件并重建投影。Worker 消费已接纳的计划并重新入队非终态项目。用户只能恢复自己暂停的项目，预算、审批等停点需要各自条件满足。取消与交付按已保存事实恢复，执行产物由 Artifact 保存。采用业务特定的持久生命周期，未引入通用任务框架。

## 历史证据与退出

LT09 构造了 Conversation 覆盖值，未经过该生产入口；LT12 是随方案建立的机制检查。两者均不足以证明产品需要独立聚合。早期验证只证明暂停、重启扫描及取消／交付恢复等局部边界；正式后台样本交付 0/20。Project 代码、入口及专属运行资产退出，原测试与归档按原身份追溯。[原记录](https://github.com/SkyLiberation/personalAgent/blob/345c62679a6c1f6a4c70980c868f55b5dee95fef/docs/adr/0002-investigation-project-aggregate-and-journal.md)
