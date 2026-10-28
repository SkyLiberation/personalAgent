# 待验证优化方案

本目录按具体优化问题保留尚未充分证明、尚未覆盖或仅取得局部证据的方案，防止方案随会话与失败实验丢失。它不是第二份产品准入队列；产品准入仍由 [Future 队列](../../future/design-optimization-backlog.md)拥有，记录生命周期由[优化规则](../README.md#待验证方案与失效方案的保留规则)拥有。

本目录同时保存生产候选与尚有证据价值的历史方案。生产接入不等于用户结果通过；历史章节的“当前”只对应其代码身份，不能据此恢复已停用机制。当前行为见 [ADR 0032](../../adr/0032-conversation-research-claims.md)及[验证专题](../../topics/verification-and-completion.md)，拆分、复合识别和独立文档缺项识别按 [ADR 0033](../../adr/0033-claim-deletion-and-document-absence-pause.md)停用。

已解决问题统一见 [completed 索引](../completed/README.md)，本目录只维护仍待验证的方案入口。

## 近期候选入口

下表提供近期方案入口，已接入部分和待验证条件由正文说明。实际结果见[评测盘点](../../evals/02-current-case-inventory.md)，准入状态见 [Future 队列](../../future/design-optimization-backlog.md)。

| 具体问题 | 上位问题与事实入口 | 唯一候选正文 |
| --- | --- | --- |
| Prompt 语言及生成／评分配置替换 | [封存输入与验证](verify_results/prompt-language-mimo.md) | [语言与 MiMo 配置 Spec](prompt-language-selection.md)；已固化的工程提示与动态反馈见[完成记录](../completed/english-owned-feedback.md) |
| `CONVERSATION-LOOP-BOUNDARIES-001`：模型交互 Schema、原生动作、交付与恢复 | [完整运行结果及适用边界](conversation-loop-schema.md#16-完整运行结果与实际边界) | [统一交互契约](conversation-loop-schema.md)、[终答职责收窄候选](conversation-loop-schema.md#17-终答入口的框架分析与职责收窄候选) |
| `KNOWLEDGE-DECISION-DELIVERY-001`：实验、自主分析与长程分析状态 | [LongDS 设计与事实依据](longds-analysis.md#longds-长程数据分析-spec) | [约束接续与语义核验候选](longtask-semantic-consistency.md#长程分析约束接续与语义核验候选)；原件成文和 claim 消融分别推进 |
| `KNOWLEDGE-DECISION-DELIVERY-001`：模型自主 Python 数据分析 | [执行链与成文边界](verify_results/research-experiment.md#deepseek-接续-e1-的实际结果与错例分析缺口) | [Python 数据分析工具 Spec](python-data-analysis-tool.md) |
| `RESEARCH-GOAL-COVERAGE-001`：用户事实覆盖及 claim 增量贡献 | [统一链正式结果](../../evals/02-current-case-inventory.md#2026-10-16-统一研究与最终回答的正式验证) | [复核标注与实际修订比较](research-goal-coverage.md#当前推荐复核标注再比较实际修订)、[统一核验 Spec](research-goal-coverage.md#2026-10-15-sourcecoverage-与-final-合并设计) |
| `RESEARCH-INPUT-MATERIALIZATION-BUDGET-001`：输入物化的费用与延迟 | [预算事实](research-input-budget.md) | [预算复审与待证收益](research-input-budget.md) |
| `ANSWER-NORMATIVE-SCOPE-001`：真实范围反馈与修订 | [来源核验已固化边界](../completed/source-proof-boundary-isolation.md) | [范围校准与真实反馈消费](normative-context-acquisition.md#用户确认范围后的-c7-实际修订验收) |
| `ANSWER-ENUMERATION-SCOPE-001`：反馈修订扩大列举范围且最终核验漏判 | [真实连续修订反例](../claim-revision-nonconvergence.md#2026-10-02-汇总将部分列举改为完整枚举) | [当前稿独立核验与修订反馈分工](final-revision-comparison.md) |
| `RESEARCH-SELECTION-USAGE-COMMIT-001`：后置写作或选证输出失败造成已完成用量漏计 | [正式用量差额](../research-selection-usage-commit.md) | [已完成选证用量的及时提交](research-selection-usage-commit.md) |
| `RESEARCH-SELECTION-OUTPUT-TRUNCATION-001`：单次输出截断阻断正式研究 | [正式选证失败](../claim-revision-nonconvergence.md#2026-10-02-选证输出截断阻断正式研究) | [研究请求采用服务方默认输出额度](research-provider-output-default.md) |
| `ANSWER-NORMATIVE-SCOPE-001`：多来源稿的指代导致具体页面归属错误 | [真实来源错配](../normative-scope-attribution.md#2026-10-02-实际流程步骤的来源错配) | [最终稿具体来源归属](answer-source-attribution.md) |

独立新业务选型不再作为当前前置待办；[场景比较及未采纳会议规格](non-research-task-directions.md)保留取舍与来源，不单独推进日历接入。

## 研究能力专题与验证记录

[研究能力总 Spec](knowledge-decision-delivery.md)只保留目标、总体职责和推进关系。专题正文按实际修改对象读取，验证结果统一进入用户指定的 `verify_results/`：

| 正文职责 | 唯一入口 |
| --- | --- |
| 受限实验、候选程序、持久接受及当前完成协议 | [实验执行协议](research-experiment-protocol.md) |
| SciFact 自然请求、R 需求、用例、评分及收益判据 | [实验请求与验收](research-experiment-acceptance.md) |
| 共享程序／JSON 产物、快照及坐标 patch | [程序产物契约](program-artifact-contract.md) |
| LongDS 逐轮依赖、LT 需求和 L0—L3 | [LongDS Spec](longds-analysis.md) |
| NUM 精度、自检、计算成文及原件提交候选 | [结果成文候选](analysis-result-correctness.md) |
| SEM 约束接续、成果适用性及语义核验候选 | [长程语义候选](longtask-semantic-consistency.md) |
| 已执行验证、当时计划、失败归因及设计审阅 | [验证记录目录](verify_results/README.md) |

这些文档共用原问题编号，不新增能力、准入项或运行条件。当前实现与候选、历史结果的事实强度保持原身份；正式成绩由评测文档拥有。

## 按问题找方案

| 具体问题 | 上位问题与事实入口 | 唯一候选正文 |
| --- | --- | --- |
| `CONVERSATION-LOOP-BOUNDARIES-001`：主循环、研究协作与核验适用性边界 | [当前主循环职责混合](../../architecture/core-architecture-current-state.md#31-当前主循环的职责混合) | [主循环与核验边界 Spec](conversation-loop-boundaries.md) |
| `MODEL-PROVIDER-DIAGNOSTICS-001`：模型服务失败的具体诊断在异常转换中丢失 | [原研究 E2E 429 与失败边界](model-provider-diagnostics.md#失败事实与最早责任) | [有界诊断交接](model-provider-diagnostics.md) |
| `RESEARCH-GOAL-COVERAGE-001`：用户所问事实被相关格式和取证限制替代 | `CONVERSATION-VERIFICATION-FALSE-POSITIVE-001`；[实际覆盖漏放与候选](research-goal-coverage.md) | [逐项用户事实覆盖](research-goal-coverage.md) |
| `CLAIM-SUPPORTED-SCOPE-REPAIR-001`：缺证修订扩大声明 | 同上；支持范围反馈被改写成更广否定的真实修订；引用交接见[完成记录](../completed/claim-atomic-evidence-revision.md) | [支持范围约束](claim-supported-scope-repair.md) |
| `CLAIM-WRITER-TYPED-OUTPUT-001`：首次研究提交的空集合与字符串引用导致 503 | `CONVERSATION-VERIFICATION-FALSE-POSITIVE-001`；[正式入口失败与局部修正](claim-writer-typed-output.md) | [研究写作者 typed 提交契约](claim-writer-typed-output.md) |
| `CLAIM-DUPLICATE-ADDITION-001`：增补后缺少单条撤回能力 | `CONVERSATION-VERIFICATION-FALSE-POSITIVE-001`；[重复增补反例](../claim-revision-nonconvergence.md#2026-09-29-暂停拆分与复合识别的正式对比) | [单条研究论断撤回候选](claim-deletion.md) |
| `DOCUMENT-ABSENCE-PAUSE-001`：独立缺项识别反复拒稿后的剩余保护边界 | `CONVERSATION-VERIFICATION-FALSE-POSITIVE-001`；[正式调用与拒绝计数](../../evals/02-current-case-inventory.md#2026-09-29-拆分与复合识别停用对比) | [独立文档缺项识别暂停候选](document-absence-pause.md) |
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
