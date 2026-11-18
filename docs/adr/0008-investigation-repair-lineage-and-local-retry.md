# ADR 0008：Investigation 的修复沿袭关系与局部重试

2026-07-29 决定，2026-08-26 随 [ADR 0015](0015-withdraw-investigation-project.md)退出。

## 背景与原决定

SerpAPI 已取回官方 MCP 事实，但后续 A2A 修复消费了错误主题的候选。修复的修复会丢掉原沿袭关系，重复错误调用，或耗尽全局计划预算。

当时用不可变关联绑定被修复的冻结子目标与版本，只物化当前依赖和同沿袭范围内的证据。普通执行提议拒绝在原计划内有界修复，语义重规划与证据修复各用对应额度。模型选择已观察的 URL 候选 ID，代码恢复确切地址。沿用原计划与 Journal，替换全项目证据注入和把局部失败升级为全局重规划的分支。

## 历史证据与退出

主要失败与修复记录见[原归档清单](https://github.com/SkyLiberation/personalAgent/blob/345c62679a6c1f6a4c70980c868f55b5dee95fef/docs/adr/0008-investigation-repair-lineage-and-local-retry.md)。同题 IP01 正式 target `20260729T101501.732689Z-53628-6c5f02f2` 一次交付报告，3/3 语义结果满足，五条证据接纳。该次修复成立，后续后台组的交付失败和退役决定仍按各自身份保留。
