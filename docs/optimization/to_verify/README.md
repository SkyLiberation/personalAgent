# 待验证优化方案

本目录按具体优化问题保留尚未充分证明、尚未覆盖或仅取得局部证据的方案，防止方案随会话与失败实验丢失。它不是第二份产品准入队列；产品准入仍由 [Future 队列](../../future/design-optimization-backlog.md)拥有，记录生命周期由[优化规则](../README.md#待验证方案与失效方案的保留规则)拥有。

2026-09-28：用户要求完整接入且不运行 Offline 测试。claim 主链已按 [ADR 0032](../../adr/0032-conversation-research-claims.md)装配；目录仍保留待验证身份，生产接入不等于用户结果通过。正式验收统一见[问题入口](../claim-revision-nonconvergence.md#2026-09-28-完整生产接入)。

2026-10-01 固化记录：[正文片段寻址](../completed/claim-fragment-addressing.md)、[当前参数范围](../completed/claim-argument-scope.md)、[模型重试计量](../completed/model-retry-usage.md)及[局部修订引用继承](../completed/claim-retained-references.md)。其余候选与现行停用机制仍按各自问题维护。

## 按问题找方案

| 具体问题 | 上位问题与事实入口 | 唯一候选正文 |
| --- | --- | --- |
| `MODEL-PROVIDER-DIAGNOSTICS-001`：模型服务失败的具体诊断在异常转换中丢失 | [原研究 E2E 429 与失败边界](model-provider-diagnostics.md#失败事实与最早责任) | [有界诊断交接](model-provider-diagnostics.md) |
| `RESEARCH-GOAL-COVERAGE-001`：用户所问事实被相关格式和取证限制替代 | `CONVERSATION-VERIFICATION-FALSE-POSITIVE-001`；[实际覆盖漏放与候选](research-goal-coverage.md) | [逐项用户事实覆盖](research-goal-coverage.md) |
| `CLAIM-SUPPORTED-SCOPE-REPAIR-001`：把特定主体缺证改成更广否定 | 同上；应用主体缺证反馈到任意主体缺失的真实修订 | [支持范围约束缺证修订](claim-supported-scope-repair.md) |
| `CLAIM-WRITER-TYPED-OUTPUT-001`：首次研究提交的空集合与字符串引用导致 503 | `CONVERSATION-VERIFICATION-FALSE-POSITIVE-001`；[正式入口失败与局部修正](claim-writer-typed-output.md) | [研究写作者 typed 提交契约](claim-writer-typed-output.md) |
| `CLAIM-DUPLICATE-ADDITION-001`：增补后缺少单条撤回能力 | `CONVERSATION-VERIFICATION-FALSE-POSITIVE-001`；[重复增补反例](../claim-revision-nonconvergence.md#2026-09-29-暂停拆分与复合识别的正式对比) | [单条研究论断撤回候选](claim-deletion.md) |
| `DOCUMENT-ABSENCE-PAUSE-001`：独立缺项识别反复拒稿后的剩余保护边界 | `CONVERSATION-VERIFICATION-FALSE-POSITIVE-001`；[正式调用与拒绝计数](../../evals/02-current-case-inventory.md#2026-09-29-拆分与复合识别停用对比) | [独立文档缺项识别暂停候选](document-absence-pause.md) |
| `CLAIM-EVIDENCE-SELECTION-001`：研究论断先于证据适合性判断 | `CONVERSATION-VERIFICATION-FALSE-POSITIVE-001`；[当前链路及历史错引](../claim-revision-nonconvergence.md#整体失败链与已有优化) | [先选合适证据，再生成论断](claim-evidence-selection.md) |
| `CLAIM-PARAMETER-RECOVERY-001`：隔离实验在参数拒绝后终止，未让研究模型修复 | 同上；[参数恢复问题](claim-parameter-recovery.md#失败事实与责任边界) | [参数错误回传](claim-parameter-recovery.md) |
| `CLAIM-EVIDENCE-REVISION-001`：真实缺证反馈后只改写正文，引用仍不支持论断 | 同上；[单项替换结果](../revision-feedback-loop.md#141-单个完整-claim-替换与工具分层评估) | [正文与引用独立修改](claim-evidence-revision.md) |
| `CLAIM-MULTI-PROPOSITION-001`：一个论断混合数项可独立失败的判断 | 同上；[第 15 版复合论断与第 9 次拒稿](../revision-feedback-loop.md#145-宽限制下的完整研究修订循环) | [复合论断拆分候选](claim-multi-proposition.md) |
| `CLAIM-ASSERTION-REINTRODUCTION-001`：整项改写重新带入其他无据判断 | 同上；[无法收敛的整体问题](../claim-revision-nonconvergence.md) | [论断内片段有界修订候选](claim-fragment-revision.md) |
| `CLAIM-REVISION-PROGRESS-001`：反馈后多次编辑而不重新核验 | 同上；[无法收敛的整体问题](../claim-revision-nonconvergence.md) | [协调层新版复验触发候选](claim-revision-progress.md) |
| `CLAIM-LOOP-PROMPT-CONTRACT-001`：研究输入混入运行控制 | 同上；[第 173 次实发输入](../../../.tmp/claim-v53-no-parameter-cap-recovery2-20260924/call-173-request.json) | [研究输入职责收窄候选](claim-research-context-scope.md) |
| `CLAIM-VERIFIER-STAGE-SCOPE-001`：研究论断按最终答复要求被拒 | 同上；[第 18 版来源支持与固定语义诊断](../claim-revision-nonconvergence.md#2026-09-26-连续续接结果) | [研究与最终交付验收边界候选](claim-verifier-stage-scope.md) |

上述编号标识同一产品问题内可独立判断的失败边界，不创建新的产品能力或重复 Future 状态。证据选择候选处理首次论断生成及缺证后的取证方向；引用独立修订候选处理已存在论断的字段编辑，两者不能互相充当验证结果。参数与修订方案仍需在同一真实依赖链验证；复合论断候选依赖该链的完整集合与反馈，各自判据不能混用。统一文档行身份及长期观察仍由[独立坐标问题](../citation-coordinate-confusion.md)拥有，不把未返回文档号直接归因为旧编号混用。

本轮另记录[已有集合仍选择首次创建](../claim-action-selection.md)，目前只有失败事实，没有新优化候选；不能为填满本目录而预建方案。

续接验证还记录了[正文工具夹带引用参数](../claim-field-tool-mixup.md)。它是字段分工的具体消费反例，仍关联原独立修订候选；不以新增一个问题名复制另一套方案。该轮涉及的三个候选均继续保留，完整续接结果见[第 144 节](../revision-feedback-loop.md#144-保留三个候选并接续未消费的参数错误)。

用户再次扩大上限后的[能力验证](../claim-field-tool-mixup.md#优先验证合法引用编辑能力)首次观察到合法引用修改并保持正文及其他项。随后的[完整循环验证](../revision-feedback-loop.md#145-宽限制下的完整研究修订循环)已到达主动复验、c1 局部支持通过和 c2 引用修改，但第 15 版仍被拒，下一请求前预算预检停止。完整集合未通过；此前参数混用及本轮局部收益均保留，三个候选不迁入 completed。

相同输入的判决准确性由[核验一致性问题](../claim-verifier-consistency.md)拥有；报告恢复适用性见[来源报告复用固化记录](../completed/claim-source-review-reuse.md)，反馈修订见[支持范围候选](claim-supported-scope-repair.md)。三个责任边界分别验收。

第 15 版拒稿后的[拆分候选连续验证](../revision-feedback-loop.md#146-复合论断拆分工具的连续验证)没有观察到模型选择 `split_claim`，第 22 版又在已修改的 c1 被拒，预算预检阻止后续请求。拆分应用及其语义收益未到达；候选按具体问题保留，不把工具可用误记为工具有效。

[Verifier 粒度反馈验证](../revision-feedback-loop.md#147-verifier-粒度反馈的识别与连续消费)在同一第 15 版 c2 中识别三项独立职责；真实反馈续接出现一次 `split_claim(c1)`，未改项保持，但拆分稿新增无据细节并被拒。反馈识别、动作消费、拆后来源支持和整个集合通过分别计分；具体未证边界仍由[复合论断候选](claim-multi-proposition.md)拥有。

[逐项缺证定位续接](../revision-feedback-loop.md#148-缺证意见逐项定位后的研究修订)已把真实 `finding` 对应到原 claim 片段并送达研究模型；模型四次改写 c2、补读一次来源，未拆分或更新引用，第 19 版未重新核验即遇预算预检。该结果仅证明定位交接，不证明缺证解除；候选及下一责任边界仍见[复合论断方案](claim-multi-proposition.md)。

[延长至第 40 版的同轨迹验证](../revision-feedback-loop.md#150-扩大预算后仍未取得完整研究集合通过)继续观察到自主拆分、逐项反馈消费和独立引用修改，也再次观察到新增无据细节与参数误用。第 17、18 次核验对未改 c6 的相同实发请求给出相反支持判断；第 19 次拒绝已改写 c6，新版第 40 版未提交。完整集合仍未通过，复合论断、证据修订、参数混用和核验一致性分别按各自问题记录推进；一条轨迹的局部动作不迁入 completed，也不计正式 E2E。

[移除参数错误次数上限的续接](../revision-feedback-loop.md#151-移除参数错误次数上限后的连续续接)使第 40 版得到提交与第 20 次真实核验，后者仍拒绝 c7。模型随后改到第 59 版而未提交；第 180 次服务请求没有响应。参数错误累计数不再触发停止的局部结果属于[恢复候选](claim-parameter-recovery.md)，不能扩大成完整研究集合通过或工具动作稳定正确；引用与论断匹配仍由[引用修订候选](claim-evidence-revision.md)验收，同项改写范围和新版复验分别见[片段修订候选](claim-fragment-revision.md)与[触发候选](claim-revision-progress.md)。

## 每项必须保留的内容

每项写明具体问题编号、上位问题、失败输入与最早责任边界、候选机制与责任主体、已成立证据、未验证部分、依赖方案、代码和归档身份、下一验证判据与预算、直接证伪及退出条件。必须有问题记录或索引的入链，不允许只有工具名或通用技术名称的孤立方案。

本批先收敛当前研究论断修订链。其他历史候选继续由原问题记录拥有，在后续触及时按同一规则迁移；本索引不声称全库历史已经迁完。
