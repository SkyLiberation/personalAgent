# 迁移、ADR 与完成门禁细则（REL）

> 本细则在任务涉及 Schema、Model、内部协议迁移、兼容窗口、ADR、发布评审或合并验收时生效。变更证据由[变更证据与设计准入](change-evidence.md)主讲。

## 1. 迁移与兼容边界

正式上线兼容期前，Schema、Model 和内部协议迁移默认直接建立 canonical 新模型，迁移全部数据与调用方，并在同一变更关闭旧写入口。回滚依赖版本控制和数据备份，不依赖旧生产链。只有真实外部契约、存量生产数据或混合版本部署需要兼容窗口、迁移观测和最终删除日期。

## 2. ADR 准入

以下情况必须创建 ADR：

- 跨模块边界调整或引入新框架或基础设施；
- 新增 Planner、通用状态、持久化投影、多智能体拓扑或其他主链复杂度；
- 新增持久化事实，或引入 Event Sourcing、Saga、兼容窗口；
- 改变 Command、digest、Replay、Approval、Verification 或 Completion 语义；
- 偏离主文档或细则中的“必须”“禁止”。

ADR 必须包含 `Complexity Justification`、外部参考来源与分级、事实与决策 owner、迁移或退出条件、未采用方案和已执行 E2E 证据。ADR 不能代替 E2E。

## 3. 完成检查表

一项变更只有全部满足下列适用条件，才可合并并视为完成：

- [ ] 变更类型、目标和 Out of Scope 明确。产品能力变更有同输入失败 baseline、单变量消融、真实 target E2E 和预设指标门槛与结果；纯重构有失败工程基线及重构前后通过的行为保持 E2E。
- [ ] 产品 E2E 没有泄漏内部名称、对象或步骤来迎合设计；重构 E2E 未被冒充为产品能力改善。
- [ ] 所需能力已盘点，并形成从正式入口、Application/Domain、真实 Adapter/Provider/Persistence 到 Verification/Completion 和用户结果的纵向切片。
- [ ] 架构分类、Decision/Fact owner、canonical model、唯一写入口和依赖方向明确；工具、Workflow 或 Project 未冒充用户能力。
- [ ] 机制选型及适用的遇阻复核已检索优秀智能体与业界实现，来源分级和可复核坐标已记录；活动方案已经收敛，未采纳、撤回和调整部分有理由。
- [ ] 每个新增 Model、状态、digest、表、层或类具有不可合并职责、生产构造点和调用者或消费者；持久化事实或投影有真实写读者，注入式协作者已装配；结构性不变量有确定性失败判据。
- [ ] 新增或增长文件与类已报告职责和拆分理由，类数量及净复杂度受控；不存在镜像事实、双写、隐藏 fallback、无期限兼容或仅测试可达的死代码。
- [ ] Proposal、Command、Execution Fact、Verification、Completion 和框架/Application 边界正确；框架抽取具有两个生产消费者或强制边界。
- [ ] 旧字段、旧路径、临时状态和无消费者结构已删除或有期限 ADR；baseline 或消融代码未作为生产 flag、fallback 或双轨保留，Fake 未被外推为真实接入。
- [ ] baseline、消融和真实 target 证据分别可还原并封存；Real E2E 及适用的 Unit、Contract、Integration 和 Golden Set 已通过，指标达到预设门槛并覆盖失败、拒绝、恢复或 replay。
- [ ] 已按 [`docs/README.md`](../README.md) 更新权威文档，没有冲突正文、重复 owner、失效链接或未来设计冒充当前事实；新增和修改段落符合 [`docs/chinese-writing-spec.md`](../chinese-writing-spec.md)，文档结构与链接检查已通过。
- [ ] 验证命令、结果、净复杂度变化和未验证风险已如实记录。

产品能力变更没有失败 baseline、单变量消融、真实 target E2E 和达标对照指标就不得落地；正式代码只保留 target。纯重构没有工程约束证据与行为保持 E2E 就不得合并。
