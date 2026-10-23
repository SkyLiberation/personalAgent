# 待验证优化方案

本目录按具体优化问题保留尚未充分证明、尚未覆盖或仅取得局部证据的方案，防止方案随会话与失败实验丢失。它不是第二份产品准入队列；产品准入仍由 [Future 队列](../../future/design-optimization-backlog.md)拥有，记录生命周期由[优化规则](../README.md#待验证方案与失效方案的保留规则)拥有。

本目录同时保存生产候选与尚有证据价值的历史方案。生产接入不等于用户结果通过；历史章节的“当前”只对应其代码身份，不能据此恢复已停用机制。当前行为见 [ADR 0032](../../adr/0032-conversation-research-claims.md)及[验证专题](../../topics/verification-and-completion.md)，拆分、复合识别和独立文档缺项识别按 [ADR 0033](../../adr/0033-claim-deletion-and-document-absence-pause.md)停用。

已解决问题统一见 [completed 索引](../completed/README.md)，本目录只维护仍待验证的方案入口。

## 近期候选入口

下列候选保留各自边界。当前研究已使用同版本 claims 与最终回答的统一核验，旧独立 Final v6 不再是活动实现候选；其历史成果按原身份保留。当前结果由[评测盘点](../../evals/02-current-case-inventory.md)拥有，选证输出及计量分别按各自前置边界验证。

| 具体问题 | 上位问题与事实入口 | 唯一候选正文 |
| --- | --- | --- |
| `KNOWLEDGE-DECISION-DELIVERY-001`：实验、自主分析、长程状态及历史压缩的整体职责和验证关系 | [当前状态](knowledge-decision-delivery.md#8-当前状态与剩余决定)、[LongDS 36 轮设计](knowledge-decision-delivery.md#9-longds-长程数据分析设计)；新增用例尚未执行，准入由 [Future 队列](../../future/design-optimization-backlog.md)拥有 | [研究能力增强与实验交付 Spec](knowledge-decision-delivery.md) |
| `KNOWLEDGE-DECISION-DELIVERY-001`：模型自主Python数据分析执行；旧自动统计方案已撤回 | [研究事实与范围](knowledge-decision-delivery.md#deepseek-接续-e1-的实际结果与错例分析缺口) | [Python数据分析工具Spec](python-data-analysis-tool.md)，已实施；自主计算链成立，局部整稿失败 |
| `RESEARCH-GOAL-COVERAGE-001`：统一链既有验收保持；claim 增量贡献先补完整标注与实际修订，再决定独立机制候选 | [正式结果](../../evals/02-current-case-inventory.md#2026-10-16-统一研究与最终回答的正式验证) | [claim 评估与优化顺序](research-goal-coverage.md#当前推荐复核标注再比较实际修订)；[统一核验 Spec](research-goal-coverage.md#2026-10-15-sourcecoverage-与-final-合并设计) |
| `RESEARCH-INPUT-MATERIALIZATION-BUDGET-001`：输入优化及实际成本收益尚待证明 | [预算事实与当前边界](research-input-budget.md) | [预算复审](research-input-budget.md) |
| `ANSWER-NORMATIVE-SCOPE-001`：自动复核已删除，真实反馈继续修订；最新 target 原预算未交付 | [已验边界及 c4 闭环](../completed/source-proof-boundary-isolation.md) | [范围校准与真实反馈消费](normative-context-acquisition.md#用户确认范围后的-c7-实际修订验收) |
| `ANSWER-ENUMERATION-SCOPE-001`：反馈修订扩大列举范围且最终核验漏判 | [真实连续修订反例](../claim-revision-nonconvergence.md#2026-10-02-汇总将部分列举改为完整枚举) | [当前稿独立核验与修订反馈分工](final-revision-comparison.md) |
| `RESEARCH-SELECTION-USAGE-COMMIT-001`：后置写作或选证输出失败造成已完成用量漏计 | [正式用量差额](../research-selection-usage-commit.md) | [已完成选证用量的及时提交](research-selection-usage-commit.md) |
| `RESEARCH-SELECTION-OUTPUT-TRUNCATION-001`：单次输出截断阻断正式研究 | [正式选证失败](../claim-revision-nonconvergence.md#2026-10-02-选证输出截断阻断正式研究) | [研究请求采用服务方默认输出额度](research-provider-output-default.md) |
| `ANSWER-NORMATIVE-SCOPE-001`：多来源稿的指代导致具体页面归属错误 | [真实来源错配](../normative-scope-attribution.md#2026-10-02-实际流程步骤的来源错配) | [最终稿具体来源归属](answer-source-attribution.md) |

独立新业务选型不再作为当前前置待办；[场景比较及未采纳会议规格](non-research-task-directions.md)保留取舍与来源，不单独推进日历接入。

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

Runtime 的独立工程问题见[策略审计隔离规格](runtime-policy-audit-isolation.md)：先验证同进程多个正式应用的审计归属，再决定是否准入显式注入修复。

每项写明具体问题编号、上位问题、失败输入与最早责任边界、候选机制与责任主体、已成立证据、未验证部分、依赖方案、代码和归档身份、下一验证判据与预算、直接证伪及退出条件。必须有问题记录或索引的入链，不允许只有工具名或通用技术名称的孤立方案。

本批先收敛当前研究论断修订链。其他历史候选继续由原问题记录拥有，在后续触及时按同一规则迁移；本索引不声称全库历史已经迁完。
