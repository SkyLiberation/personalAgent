# 迁移、ADR 与完成门禁细则（REL）

> 本细则适用于 Schema、Model、内部协议迁移、兼容窗口、ADR 和合并验收。本文拥有迁移例外与完整完成检查表；证据分类和设计由[EVD](change-evidence.md)拥有。

## 1. 迁移与兼容边界

正式上线兼容期前按[根规范第 2.3 节](../../AGENTS.md#23-只实现最小生产纵向切片)破坏式替换：建立 canonical 新模型，迁移全部数据与调用方，在同一变更关闭旧写入口。回滚依赖版本控制和数据备份，不依赖旧生产链。

只有真实外部契约、存量生产数据或混合版本部署需要兼容时，才允许保留有期限的兼容窗口。ADR 必须记录适用消费者与范围、原因、风险、验证、迁移计划、观测指标、退出条件和最终删除日期；没有这些消费者时不得以回滚或未来上线为由保留旧链路。

## 2. ADR 准入

以下变更必须创建 ADR：

- 跨模块边界调整，或引入框架、基础设施；
- 新增 Planner、通用状态、持久化投影、多智能体拓扑或其他主链复杂度；
- 新增持久化事实，或引入 Event Sourcing、Saga、兼容窗口；
- 改变 Command、digest、Replay、Approval、Verification 或 Completion 语义；
- 偏离根规范或细则的“必须”“禁止”。

ADR 按[中文文档结构](../chinese-writing-spec.md#6-各类文档的附加要求)组织，须包含 `Complexity Justification`、外部参考等级与坐标、事实与决策责任主体、未采用方案、迁移或退出条件，以及已执行的适用 E2E 证据。ADR 不能替代 E2E。

## 3. 完成检查表

一项变更只有满足全部适用项，才可合并并声明完成；不适用项须说明原因，不能把未执行写成通过。

- [ ] 目标、变更类型与范围外事项明确，[根规范第 4 节](../../AGENTS.md#4-变更准入速查)的分类证据和预设指标达标；重构未被冒充为产品能力改善。
- [ ] E2E 满足[真实生产链与用户结果资格](change-evidence.md#2-产品-e2e-的最低资格)，未泄漏内部名称、对象或步骤迎合设计。
- [ ] 按[ARC](architecture-ownership.md)确认能力盘点、架构分类、事实与决策归属、canonical model、唯一写入口和依赖方向；工具、Workflow、Project 未冒充用户能力。
- [ ] 新增结构满足[生产可达性](architecture-ownership.md#7-生产可达性)与[复杂度准入](change-evidence.md#5-复杂度说明complexity-justification)，注入式协作者已装配，持久化事实或投影有真实写读者。
- [ ] 按[COD](code-structure.md)报告新增或增长文件与类的职责、拆分理由及净复杂度；结构性不变量有确定性失败判据。
- [ ] 决策、执行与完成满足[EXE](agentic-execution.md)，框架抽取满足[独立消费者或强制边界](architecture-ownership.md#4-framework-capability-准入与边界)。
- [ ] 适用的[外部比较与遇阻复核](change-evidence.md#6-外部参考的证据分级)已执行并保留坐标；活动方案收敛，未采纳、撤回或调整部分有理由。
- [ ] 旧字段、路径、临时状态、镜像事实、隐藏 fallback、无消费者结构、测试旁路和无期限兼容已清理；兼容例外满足第 1 节，实验代码符合[EVD 隔离要求](change-evidence.md#3-删除优先与兼容边界)。
- [ ] 适用的 Real E2E、Offline Eval（含 Golden Set）、真实环境 smoke、lint、type check、dead-code 与[QLT 覆盖要求](quality-security.md#1-测试职责与覆盖)通过；未新增、维护、收集或运行 `tests/` 及等价单元测试，Test Double 未被外推为真实接入。
- [ ] 证据按[归档规则](../../evals/AGENTS.md#5-比较身份与归档)分别封存且可还原；发布声明另满足[评测模块发布边界](../../evals/AGENTS.md#6-运行与声明)。
- [ ] 权威文档已同步，按[DOC 检查](../AGENTS.md#5-提交前检查)确认事实、中文写作、生命周期、链接与结构。
- [ ] 如实报告验证命令、实际结果、样本量、净复杂度和未验证风险。

局部机制验收必须满足[EVD 的检查点与因果条件](change-evidence.md#1-用户结果与工程约束的可执行基线)，并保留原始 E2E 失败。它不能勾选产品契约完成或发布门禁；原始用户结果只有在 Real E2E 通过后才可声明闭环。
