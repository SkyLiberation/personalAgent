# 评测模块规范（EVM）

> 本文件适用于 `evals/**`。它继承根 [`AGENTS.md`](../AGENTS.md)，只定义评测代码、数据集、grader、case catalog 和证据归档的局部不变量。修改前必须阅读[变更证据与设计准入](../docs/devSpec/change-evidence.md)、[测试、评估、观测与安全](../docs/devSpec/quality-security.md)、[当前评测体系](../docs/evals/README.md)及目标评测目录。

## 1. 证据分类不能混用

- Product E2E 从正式入口断言 typed `UserOutcomeContract`，可以证明限定场景的用户结果；Application E2E、Runtime Conformance、Integration、Capability Profile 和 Offline Eval 只能证明各自边界，不能外推为产品交付。
- 产品失败 baseline 是实现前以相同用户、输入、入口、初始事实和结果契约执行并失败的证据。指标 baseline 是固定 workload 与 profile 后的比较值。回归 E2E 锁定已有行为。名称中出现 `baseline` 不会自动改变证据类别。
- 单变量消融必须在可还原独立代码状态中只移除目标机制的生产消费点，并保持比较身份一致。生产 flag、测试旁路或 Fake 不能成为消融的产品路径。
- Unit 通过、对象存在、状态 success、数据库记录、工具调用、Trace 步骤或 grader 自述都不能替代用户结果。

## 2. Canonical owner 与写入口

- `evals/e2e_quality/evidence_catalog.py` 唯一拥有证据类别、`UserOutcomeContract` 和机器 eligibility；禁止在测试文件、报告或文档中维护第二份 release 清单。
- `evals/e2e_quality/evidence_audit.py` 负责只读语义、重叠和 cohort 审计；`release_gate.py` 负责发布 archive 信任判断；`measurements.py` 负责测量 schema；`metrics_report.py` 负责聚合报表。
- 新增或修改 case 时，必须通过 canonical catalog 注册，并同步修改相应 typed contract、选择器与 [`docs/evals/`](../docs/evals/README.md) 的权威说明。不得靠文件名、pytest marker 或 raw dict 隐式定义证据类别。
- 数据集输入、grader 输出、measurement、principal、scope、模型与 Provider 配置必须 typed。外部 payload 在读取边界校验失败时按事实缺失处理，不得填充默认成功。

## 3. 产品 E2E 与 grader 边界

- Given/When 使用目标用户自然表达，不得泄漏预期 Tool、Agent、Workflow、内部 ID、步骤或执行顺序。内部路径只在执行后通过 Trace、Event、Receipt 或 Report 断言。
- grader 必须在实现前固定版本、输入与结果契约，直接断言用户可观察结果和关键反事实。禁止让 grader 用字符串包含、对象存在、工具调用或模型自述代替语义结果。
- Fake 只允许隔离不可控第三方、注入危险副作用失败或验证低层 Contract/Conformance。Fake 必须实现生产 Port 并有 contract test，不得替模型、Policy、Admission 或 Verifier 决策。
- 真实 target 使用生产 Composition Root、真实持久化，以及用户结果依赖的真实模型、Provider 与隔离沙箱。冻结 Provider 只能支持可重复消融、故障注入或 Conformance。

## 4. 比较身份与归档

- baseline、消融和 target 必须保存用户输入、principal、正式入口、交互模式、初始事实、config cohort、grader 版本、代码与配置身份、trace 或 report 和 checksum。
- baseline 与 target 必须使用相同 seed、用户输入、principal、正式入口、初始事实和 grader。比较器必须拒绝 checksum 失效、role 错误、比较身份不一致，以及代码与配置身份完全相同的伪配对。
- 每次执行生成独立且 checksum 封印的 archive；禁止覆盖历史结果。历史 archive 只读，不能与不同 grader、Provider、transport、Prompt、预算、fixture 或 cohort 的结果合并。
- 结果报告缺失、pytest 失败、internal error、usage error 或调用阶段异常都必须保持 typed 失败。晋级器不得覆盖测试失败，也不得把执行失败解释成用户结果类型。
- 性能比较只有在用户目标、输入、Provider、模型、Prompt、预算、fixture 和 repetition 一致时成立。不同 case 或 cohort 的完成率、耗时、token 或成本不得直接比较。

## 5. 运行与声明

- 运行前预声明指标门槛、样本量、重复次数、最大成本和停止条件。高成本或真实外部 Provider 评测只在任务需要该证据时执行，不属于普通回归套件。
- 定向 target archive 只能证明对应变更边界，不能替代完整 release matrix。dirty revision 的结果必须记录 dirty digest；没有与目标 clean revision 绑定的完整 release gate 时，禁止声明 release-ready 能力集合。
- 失败时保留 trace、event、receipt、report 和 archive，不得为使门禁通过而修改 grader、删除失败样本、重跑后只挑成功结果，或把不可用指标写成零。
- 评测结果必须报告分子、分母、样本量、方差或适用置信边界，并区分完成率、正确性、错误副作用、成本、延迟和恢复。禁止只报告百分比或挑选单个成功例。

具体收集、配对、promotion 和 release gate 命令只由[运行、归档与发布](../docs/evals/04-running-and-release.md)维护，本文件不复制易漂移的命令。
