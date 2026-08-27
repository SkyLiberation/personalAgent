# 当前评测体系

**canonical catalog 当前登记 30 条证据：9 条有 typed `UserOutcomeContract` 的 Product E2E，以及 21 条 Application/Runtime/Profile supporting evidence。** 产品发布完成率只消费前 9 条；已撤回的 Investigation conformance 不再进入当前矩阵。

## 文档入口

| 文档 | 回答的问题 |
| --- | --- |
| [证据分类](01-evidence-classes.md) | Product E2E、Application E2E、Runtime Conformance、Integration、Capability Profile 和离线 Eval 分别证明什么 |
| [当前用例盘点](02-current-case-inventory.md) | 30 条当前用例及历史撤回证据的入口、Test Double、用户结果强度和可用证据等级 |
| [baseline-first 审计](03-baseline-first-audit.md) | 哪些用例有实现前失败证据，哪些只是已有设计的回归或机制演示 |
| [运行与发布](04-running-and-release.md) | 如何收集、执行、归档和判断当前 revision 的发布证据 |
| [观测指标](05-observability-metrics.md) | 当前 archive 能输出哪些性能指标，哪些指标尚不可用 |

## 当前机器事实

截至 2026-08-26，对当前工作树实际收集：

```text
catalog cases: 30
qualified Product E2E: 9
supporting evidence in e2e_quality: 21
retired Investigation conformance: 0
HTTP process entry: 30
real model required: 30
contains test doubles: 3
process-termination cases: 7
```

当前工作树为 dirty，尚未执行与目标 clean revision 绑定的完整 release gate；因此没有可陈述的 release-ready 能力集合。定向 target archive 只能证明对应变更边界，不能替代发布矩阵。

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
