# 待验证优化方案

机制方案按问题维护，产品准入状态见 [Future 队列](../../future/design-optimization-backlog.md)，已解决问题见[完成记录](../completed/README.md)。保留规则由[优化记录规范](../README.md#待验证方案与失效方案的保留规则)维护。

## 近期候选入口

下表提供近期方案入口，已接入部分和待验证条件由正文说明。实际结果见[评测盘点](../../evals/02-current-case-inventory.md)，准入状态见 [Future 队列](../../future/design-optimization-backlog.md)。

| 具体问题 | 上位问题与事实入口 | 唯一候选正文 |
| --- | --- | --- |
| Prompt 语言及生成／评分配置替换 | [封存输入与验证](verify_results/prompt-language-mimo.md) | [语言与 MiMo 配置 Spec](prompt-language-selection.md)；已固化的工程提示与动态反馈见[完成记录](../completed/english-owned-feedback.md) |
| `CONVERSATION-LOOP-BOUNDARIES-001`：模型交互 Schema、原生动作、交付与恢复 | [完整运行结果及适用边界](conversation-loop-schema.md#16-完整运行结果与实际边界) | [统一交互契约](conversation-loop-schema.md)、[终答职责收窄候选](conversation-loop-schema.md#17-终答入口的框架分析与职责收窄候选) |
| `KNOWLEDGE-DECISION-DELIVERY-001`：实验、自主分析与长程分析状态 | [LongDS 设计与事实依据](longds-analysis.md#longds-长程数据分析-spec) | [执行目标维护 Spec](analysis-goal-maintenance.md)；此前约束呈现及核验尝试见[长程语义记录](longtask-semantic-consistency.md)，原件成文独立推进 |
| `KNOWLEDGE-DECISION-DELIVERY-001`：模型自主 Python 数据分析 | [执行链与成文边界](verify_results/research-experiment.md#deepseek-接续-e1-的实际结果与错例分析缺口) | [Python 数据分析工具 Spec](python-data-analysis-tool.md)、[Bash 跨轮任务工作区](python-data-analysis-tool.md#bash-跨轮任务工作区候选) |

独立新业务选型不再作为当前前置待办；[场景比较及未采纳会议规格](non-research-task-directions.md)保留取舍与来源，不单独推进日历接入。

## 研究能力专题与验证记录

[研究能力总 Spec](knowledge-decision-delivery.md)只保留目标、总体职责和推进关系。专题正文按实际修改对象读取，验证结果统一进入用户指定的 `verify_results/`：

| 正文职责 | 唯一入口 |
| --- | --- |
| 受限实验、候选程序、持久接受及当前完成协议 | [实验执行协议](research-experiment-protocol.md) |
| SciFact 自然请求、R 需求、用例、评分及收益判据 | [实验请求与验收](research-experiment-acceptance.md) |
| 共享程序／JSON 产物、快照及坐标 patch | [程序产物契约](program-artifact-contract.md) |
| LongDS 逐轮依赖、LT 需求和 L0—L3 | [LongDS Spec](longds-analysis.md) |
| 跨轮执行目标、每轮维护及核验历史接续 | [目标与回答核验职责分离](analysis-goal-maintenance.md#914-分离目标核验与回答核验的职责及历史) |
| 普通回答拒稿后的原循环重生成 | [实现决定](../../adr/0049-answer-regeneration-in-original-loop.md)、[实际结果](verify_results/analysis-correctness.md#36-普通回答改为原循环完整重提的连续前三轮) |
| 完整核验反馈历史与压缩 | [结果卸载与完整交互压缩](analysis-goal-maintenance.md#920-结果卸载与完整交互压缩)、[实际结果](verify_results/analysis-correctness.md#40-原运行到期后的-task2-独立连续重验) |
| NUM 精度、自检、计算成文及原件提交候选 | [结果成文候选](analysis-result-correctness.md) |
| 既有 SEM 约束呈现、成果适用性及语义核验尝试 | [长程语义候选与记录](longtask-semantic-consistency.md) |
| 已执行验证、当时计划、失败归因及设计审阅 | [验证记录目录](verify_results/README.md) |

这些文档共用原问题编号，本文不另建准入项或运行条件。目标维护的新工具及前置条件由对应子 Spec 唯一说明；已接入与语义通过分开记录，历史结果保持原身份，正式成绩由评测文档拥有。

## 按问题找方案

| 具体问题 | 上位问题与事实入口 | 唯一候选正文 |
| --- | --- | --- |
| `CONVERSATION-LOOP-BOUNDARIES-001`：主循环、答复与核验适用性 | [现行主循环](../../architecture/core-architecture-current-state.md#32-会话运行与主决策的现状) | [主循环与核验边界 Spec](conversation-loop-boundaries.md) |
| `MODEL-PROVIDER-DIAGNOSTICS-001`：模型服务失败的具体诊断在异常转换中丢失 | [原研究 E2E 429 与失败边界](model-provider-diagnostics.md#失败事实与最早责任) | [有界诊断交接](model-provider-diagnostics.md) |

## 旧 Conversation 研究链证据

[ADR 0055](../../adr/0055-unified-conversation-answer.md)已退役旧 Conversation claim。以下入口用于追溯当时的机制、失败和取舍。原指标见[历史消融](../../ablation/claim-verifier.md)，正式结果见[当轮评测记录](../../evals/02-current-case-inventory.md#2026-10-16-统一研究与最终回答的正式验证)。

| 具体问题 | 原事实入口 | 历史方案 |
| --- | --- | --- |
| 选证计量、截断和输入成本 | [计量缺口与修复](../research-selection-usage-commit.md) | [截断与额度调整](../claim-revision-nonconvergence.md#2026-10-02-选证输出截断阻断正式研究)、[输入成本审计](research-input-budget.md) |
| 终稿列举边界及来源归属 | [列举范围变化](../claim-revision-nonconvergence.md#2026-10-02-汇总将部分列举改为完整枚举)、[真实来源错配](../normative-scope-attribution.md#2026-10-02-实际流程步骤的来源错配) | [独立终稿核验](final-revision-comparison.md)、[归属候选](answer-source-attribution.md) |
| `RESEARCH-GOAL-COVERAGE-001`：用户所问事实被相关格式和取证限制替代 | `CONVERSATION-VERIFICATION-FALSE-POSITIVE-001`；[实际覆盖漏放与候选](research-goal-coverage.md) | [逐项用户事实覆盖](research-goal-coverage.md) |
| `CLAIM-SUPPORTED-SCOPE-REPAIR-001`：缺证修订扩大声明 | 同上；支持范围反馈被改写成更广否定的真实修订；引用交接见[完成记录](../completed/claim-atomic-evidence-revision.md) | [支持范围约束](claim-supported-scope-repair.md) |
| `CLAIM-WRITER-TYPED-OUTPUT-001`：首次研究提交的空集合与字符串引用导致 503 | `CONVERSATION-VERIFICATION-FALSE-POSITIVE-001`；[正式入口失败与局部修正](claim-writer-typed-output.md) | [研究写作者 typed 提交契约](claim-writer-typed-output.md) |
| 重复增补（`CLAIM-DUPLICATE-ADDITION-001`）与独立缺项识别停用（`DOCUMENT-ABSENCE-PAUSE-001`） | [重复增补反例](../claim-revision-nonconvergence.md#2026-09-29-暂停拆分与复合识别的正式对比) | [当时的决定与正式验证](../../adr/0033-claim-deletion-and-document-absence-pause.md) |
| `CLAIM-EVIDENCE-SELECTION-001`：研究论断先于证据适合性判断 | `CONVERSATION-VERIFICATION-FALSE-POSITIVE-001`；[当前链路及历史错引](../claim-revision-nonconvergence.md#整体失败链与已有优化) | [先选合适证据，再生成论断](claim-evidence-selection.md) |
| `CLAIM-PARAMETER-RECOVERY-001`：隔离实验在参数拒绝后终止，未让研究模型修复 | 同上；[参数恢复问题](claim-parameter-recovery.md#失败事实与责任边界) | [参数错误回传](claim-parameter-recovery.md) |
| `CLAIM-EVIDENCE-REVISION-001`：真实缺证反馈后只改写正文，引用仍不支持论断 | 同上；[单项替换结果](../revision-feedback-loop.md#141-单个完整-claim-替换与工具分层评估) | [正文与引用独立修改](claim-evidence-revision.md) |
| `CLAIM-MULTI-PROPOSITION-001`：一个论断混合数项可独立失败的判断 | 同上；[停用决定及正式对比](../claim-revision-nonconvergence.md#2026-09-29-暂停拆分与复合识别的正式对比) | [历史拆分方案与证据](claim-multi-proposition.md)，当前不接入生产 |
| `CLAIM-ASSERTION-REINTRODUCTION-001`：整项改写重新带入其他无据判断 | 同上；[无法收敛的整体问题](../claim-revision-nonconvergence.md) | [论断内片段有界修订候选](claim-fragment-revision.md) |
| `CLAIM-REVISION-PROGRESS-001`：反馈后多次编辑而不重新核验 | 同上；[无法收敛的整体问题](../claim-revision-nonconvergence.md) | [协调层新版复验触发候选](claim-revision-progress.md) |
| `CLAIM-LOOP-PROMPT-CONTRACT-001`：研究输入混入运行控制 | 同上；[第 173 次实发输入](../../../.tmp/claim-v53-no-parameter-cap-recovery2-20260924/call-173-request.json) | [研究输入职责收窄候选](claim-research-context-scope.md) |
| `CLAIM-VERIFIER-STAGE-SCOPE-001`：研究论断按最终答复要求被拒 | 同上；[第 18 版来源支持与固定语义诊断](../claim-revision-nonconvergence.md#2026-09-26-连续续接结果) | [研究与最终交付验收边界候选](claim-verifier-stage-scope.md) |

上述编号标识同一产品问题内可独立判断的失败边界，不创建新的产品能力或重复 Future 状态。连续验证及失败过程由[研究论断问题](../claim-revision-nonconvergence.md)和[反馈修订记录](../revision-feedback-loop.md)拥有，各候选记录自己的已证边界、依赖和剩余判据。

尚无新候选的失败事实保留在[阶段动作选择](../claim-action-selection.md)、[字段参数混用](../claim-field-tool-mixup.md)与[核验一致性](../claim-verifier-consistency.md)中；索引不复制各轮实验结果或已固化结论。

## 每项必须保留的内容

Runtime 的独立工程问题见[策略审计隔离规格](runtime-policy-audit-isolation.md)：显式注入已接入并通过真实读取阶段反事实，原完整对话 target 未交付，剩余门禁由该规格说明。

每项写明具体问题编号、上位问题、失败输入与最早责任边界、候选机制与责任主体、已成立证据、未验证部分、依赖方案、代码和归档身份、下一验证判据与预算、直接证伪及退出条件。必须有问题记录或索引的入链，不允许只有工具名或通用技术名称的孤立方案。

历史候选按各自代码和证据身份解释，后续触及时按上述规则整理。
