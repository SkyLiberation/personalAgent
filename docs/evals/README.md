# 评测体系索引

本目录解释评测分类、执行方法、证据和发布边界。用例分类及产品结果契约由 [evidence_catalog.py](../../evals/e2e_quality/evidence_catalog.py)拥有，实际样本和运行结论由[当前用例盘点](02-current-case-inventory.md)维护；本索引只提供阅读入口。

## 文档入口

| 阅读目标 | 权威文档 |
| --- | --- |
| 各类证据可以证明什么 | [证据分类](01-evidence-classes.md) |
| 当前用例、横切套件、实际结果与历史证据 | [当前用例盘点](02-current-case-inventory.md) |
| 实现前失败依据与回归证据的区别 | [baseline-first 审计](03-baseline-first-audit.md) |
| 收集、定向执行、归档和发布判断 | [运行与发布](04-running-and-release.md) |
| 指标来源、缺失语义和比较身份 | [观测指标](05-observability-metrics.md) |
| 2026-07-09 检索指标与旧 Ask 策略 | [Open / Galileo 历史检索报告](retrieval-benchmark-20260709.md) |

## 验证与结果边界

后续验证以真实 E2E 与 Offline Eval 为主，停用范围和静态检查由 [QLT](../devSpec/quality-security.md#1-测试职责与覆盖)拥有。运行时显式选择与改动有关的路径和样本，成本、停止条件及归档身份按 [EVM](../../evals/AGENTS.md)预声明。

产品完成率只消费具备 typed `UserOutcomeContract` 的 Product E2E。Supporting evidence 与横切检查点解释自己的责任边界，不增加发布分母，也不覆盖原始用户结果失败。当前分类与数量以 catalog 和实际收集为准，不在多个入口维护快照。

研究语义、选证、引用、修订和独立评分的最新结果统一见[用例盘点](02-current-case-inventory.md)。评分器的运行条件见[前置校准](04-running-and-release.md#研究答案评测器的前置校准)，已成立机制及重新打开条件见[评分固化记录](../optimization/completed/research-grader-qualification.md)。历史 grader 结果保持原身份，不与当前资格混算。

发布另需匹配目标 clean revision、配置、评测器和 checksum 的完整矩阵；具体检查见 [Release gate](04-running-and-release.md#release-gate)。定向 target、局部通过或历史矩阵不自动构成当前发布资格。

## 三个词不能混用

产品失败 baseline 证明变更必要性，指标 baseline 提供质量或成本参考，回归 E2E 保护已有行为。定义与准入统一见 [EVD](../devSpec/change-evidence.md#1-用户结果与工程约束的可执行基线)；函数、Trace 或 profile 的命名不提升证据资格。

## 机器契约入口

| 责任 | 代码入口 |
| --- | --- |
| 证据分类、结果契约与 eligibility | [evidence_catalog.py](../../evals/e2e_quality/evidence_catalog.py) |
| 横切节点与检查点 | [validation_catalog.py](../../evals/e2e_quality/validation_catalog.py)、[cross_cutting_validation.py](../../evals/e2e_quality/cross_cutting_validation.py) |
| 语义、重叠和 cohort 审计 | [evidence_audit.py](../../evals/e2e_quality/evidence_audit.py) |
| 发布证据信任判断 | [release_gate.py](../../evals/e2e_quality/release_gate.py) |
| 测量结构与聚合 | [measurements.py](../../evals/e2e_quality/measurements.py)、[metrics_report.py](../../evals/e2e_quality/metrics_report.py) |
