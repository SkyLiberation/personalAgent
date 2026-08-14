# 当前评测体系

**canonical catalog 当前登记 46 条证据：9 条有 typed `UserOutcomeContract` 的 Product E2E、25 条 Application/Runtime/Boundary/Profile supporting evidence，以及 12 条独立的 Investigation Runtime Conformance。** 产品发布完成率只消费前 9 条。

## 文档入口

| 文档 | 回答的问题 |
| --- | --- |
| [证据分类](01-evidence-classes.md) | Product E2E、Application E2E、Runtime Conformance、Integration、Capability Profile 和离线 Eval 分别证明什么 |
| [当前用例盘点](02-current-case-inventory.md) | 46 条用例当前实际入口、Test Double、用户结果强度和可用证据等级 |
| [baseline-first 审计](03-baseline-first-audit.md) | 哪些用例有实现前失败证据，哪些只是已有设计的回归或机制演示 |
| [运行与发布](04-running-and-release.md) | 如何收集、执行、归档和判断当前 revision 的发布证据 |
| [观测指标](05-observability-metrics.md) | 当前 archive 能输出哪些性能指标，哪些指标尚不可用 |

## 当前机器事实

截至 2026-08-12，对当前工作树实际执行：

```text
catalog cases: 46
qualified Product E2E: 9
supporting evidence in e2e_quality: 25
runtime conformance in evals/runtime_conformance: 12
HTTP process entry: 34
in-process service entry: 12
real model required: 34
scripted model: 12
contains test doubles: 15
process-termination cases: 10
```

当前 release gate 对目标 revision `61ffadb041e7424892f5b9948fcd0e484f3b4ad6` 的所有 capability 均返回 `unverified`：工作树为 dirty，且没有同 revision、checksum 完整的 passing archive。当前没有可陈述的 release-ready 能力集合。

历史 `current-runtime` 标签仍包含 3 个不兼容 cohort；新运行默认使用完整 cohort digest 生成 profile id，`--list-cohorts` 可枚举旧数据。2026-08-12 的独立验证 profile 已成功生成 completion/limitation、端到端 latency、provider input/output/total tokens 和 model/tool/agent turn/call 报告；非恢复场景的 recovery facts 保持 unavailable。

## 三个词不能混用

- **产品失败 baseline**：变更前用相同用户、输入、入口和结果契约执行并失败，用于证明“为什么需要改变产品行为”。
- **指标 baseline**：固定 workload/profile 后保存的质量、成本或延迟参考值，用于比较回归。
- **回归 E2E**：锁定已经存在的产品行为；它可以有价值，但不能反向证明该设计最初有必要。

测试函数、trace 文件和 profile 中大量使用 `baseline` 字样；这些名称本身不构成产品失败 baseline 证据。

## 权威来源

- 证据类别、产品结果契约和机器 eligibility：`evals/e2e_quality/evidence_catalog.py`；
- 只读语义、重叠和 cohort 审计：`evals/e2e_quality/evidence_audit.py`；
- 发布 archive 信任判断：`evals/e2e_quality/release_gate.py`；
- 测量 schema：`evals/e2e_quality/measurements.py`；
- 聚合报表：`evals/e2e_quality/metrics_report.py`；
- 本文档集合：解释机器 contract 与结果，不再维护第二份 release 清单。
