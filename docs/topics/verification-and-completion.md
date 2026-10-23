# Verification 与 Completion

本文是 Agent 内部 Verification 架构、决策所有权和当前生产实例的 canonical 文档。产品用例和
Workflow 文档只引用这里，不复制另一套通用 Verifier 定义。

## 定位

Verification 是 Agent 内部元能力：

> 候选结果产生后、宣告完成前，依据用户 Goal、required result contract 和可见 Evidence，
> 判断候选结果是否语义满足，并产生 typed assessment 与 repair feedback。

“元能力”描述运行时义务。Conversation 的统一研究核验、普通回答核验以及周期 Research digest 各有明确输入、判据和失败消费者，按各自业务契约核验。个人知识只返回证据；独立 Knowledge Answer 与后台 Investigation 的生产入口已经撤回。

用户显式要求“审查并修订一段文本”是 Conversation Review 产品能力，不是通用 Verification 的
触发前提，也不代表普通知识任务已经自动验证。

## 当前核验覆盖与适用边界

当前普通回答通过冻结的 `ReviewCriteria.requires_review` 决定是否执行整稿模型核验；进入该工具后，会把通用来源支持标准追加到用户标准。研究则采用同版本统一核验，交付不再重复普通核验。工具授权、引用合法性、业务写入和 Completion 各有确定性边界，不能因为某条回答没有额外模型核验就省略。

“所有流程都有验收责任”与“所有回答都另调一次模型核验”是不同要求。现行来源标准对计算答案造成过实际拒稿，完整请求审计仍待完成；适用性设计、外部实践及目标场景矩阵统一见[主循环与核验边界 Spec](../optimization/to_verify/conversation-loop-boundaries.md#4-是否所有流程都需要答案核验)。该矩阵是候选，不改变本文的现行触发或标准。

## 决策所有权

统一研究核验的类别、target 与引用在同一 typed 输出校验中绑定当前输入；非法输出进入 Model Port 已有有界恢复，最多两次，语义报告不额外复核。报告被接受后恢复 canonical 类型，内容不改写。旧 Coverage 的引用恢复保留为[历史证据](../optimization/completed/coverage-reference-recovery.md)。

```text
Goal / Required Result
  -> Candidate Result
  -> Execution Facts + Evidence
  -> Domain Verifier
  -> Verification Assessment
  -> Repair or Completion Gate
```

| 决策 | Owner | 禁止越界 |
| --- | --- | --- |
| Tool/Command 实际执行了什么 | Gateway / Executor | Verifier 不得改写 Receipt |
| 候选结果是否语义满足 | 领域 Verifier | 不得授权、执行或宣告完成 |
| Evidence ref 是否属于本次可见集合 | 确定性 Admission | 不得补造 Evidence |
| required result contract 是否齐全 | Domain Completion Gate | Receipt 或 verifier verdict 不能替代 |
| 何时触发、预算和修复次数 | Application Runtime | 模型不能自行跳过必需验证 |

Verifier 的开放语义输出由模型或外部权威拥有；引用集合、digest、scope 和状态迁移由确定性代码
拥有。模型不可用时只能返回 `insufficient_evidence`、暂停或请求缺失能力，不能用 fixture、
关键词或回答组装器生成替代“通过”。

普通外部研究采用同一版本的 claims 与最终回答。一个研究核验器检查来源支持、两份正文一致性及最终回答对原目标的满足，返回八类发现；用户要求只从原会话与冻结 requirements 取得，目标满足只能基于最终回答正文。Runtime 校验引用、版本与当前实际输入，缺少回答时继续研究；同版本空报告才允许确切回答进入 Completion。实际反馈交回同一 writer，不再有独立 Coverage、汇总、研究 Final 或反向重开。普通非研究草稿继续原提交依据核验。详细契约与接入范围见 [ADR 0032](../adr/0032-conversation-research-claims.md)，验收见[统一 Spec](../optimization/to_verify/research-goal-coverage.md#2026-10-15-sourcecoverage-与-final-合并设计)。

普通非研究候选仍由 `verify_interaction_draft` 检查其实际提交原文、来源支持及冻结用户要求，Receipt 绑定确切正文和原标准；研究不再调用该工具的第二次判断。模板由注册表拥有，typed 参数序列化动态输入，外部内容作为数据。

工具对用户标准与系统支持标准合并去重，从本次完整原文只读派生 `VerificationCriterion` 的 `criterion_id` 与 `criterion`。普通最终模型只返回每个 ID 的三态及反馈，动态 Schema 列出当前合法身份与结果数量；工具再检查全部项恰好一次。Runtime 从当前输入恢复原文，形成 `BoundVerificationCriterionResult` 和回执，不以模型重抄文字识别验收项。未知、遗漏或重复 ID 产生明确输出契约失败，不形成有效回执；来源支持不通过参与现有聚合并拒稿。

用户原标准由 `InteractionIntent` 冻结，回执 `success_criteria` 与 `criteria_digest` 仍绑定这组原标准；系统判断在 `criterion_results` 中独立保留，不改写用户要求。回执保留原文用于反馈和审计；三态和修订意见由模型判断，恢复引用不改变它们。失败通过现有 Conversation 循环返回模型，修订稿重新验证。既有触发范围与预算保持，不增加模型阶段、服务或循环。原文引用规范由 [COD](../devSpec/code-structure.md#21-已有文字通过引用传递)拥有，接入责任见 [ADR 0020](../adr/0020-require-conversation-source-support-verification.md)。

当前生产链暂停独立文档缺项分类及其覆盖拒绝，统一研究与普通 Final 分别检查仍适用的来源支持。普通整稿语义核验保留实际读取状态作为数据，但不能将未读内容当成已知事实；无据全文否定仍须按来源支持与用户结果判据拒绝。`evidence_sufficiency` 原先只负责越过独立覆盖拦截，现已随该分支移除。历史覆盖拒绝与补读恢复检查点见 [ADR 0021](../adr/0021-separate-document-absence-from-reading-coverage.md)，当前取舍、风险及退出条件见 [ADR 0033](../adr/0033-claim-deletion-and-document-absence-pause.md)。

统一研究请求输出上限为 131,072 tokens，本轮正式验证模型时限为 2,400 秒；普通回答核验保留 32,768 tokens 和 480 秒工具执行时限；工具自身不重试。两项上限分别允许 thinking 与完整报告输出、给模型请求及解析留出执行时间，仍可能因模型自身超时或协议错误失败。扩大交互总预算不会自动改变这些局部上限。旧 1,200-token / 60 秒限制已移除，同一真实首稿的预算对照取得完整绑定报告，但仍漏放无据权限归属结论；不能把报告返回与语义正确混为一谈。记录及产品验收限制见[推进记录第 54 节](../optimization/verifier-output-truncation.md#54-验证报告被局部预算截断的单边界资格检查)。

当前已知限制是 Verifier 可能把标题对主题的提及误判为正文已经满足详细比较要求，Draft 与 Evidence 同次输入还会放大该错误。固定反例在当前生产 Verifier 中受控重放三次，模型每次都把只存在于 Evidence 的三项比较正文与两个 URL 当成 Draft 已有内容，五项全部返回 `satisfied`。后续来源隔离与 typed segment 绑定候选虽然阻止了 Evidence 直接进入 Draft 判断，但最终仍有一次把唯一标题 segment 绑定给三项比较正文并错误通过。二态 aggregate 的路由职责不受影响；剩余问题属于 Draft 语义判别能力，不再允许通过增加来源字段、状态或同义 Prompt 修补。

## 当前生产实例

研究写作者以完整 `base_ref`、claim_id 和首尾片段 ID 指定正文修订范围；Runtime 从当前 canonical 稿恢复原文并合并。正文使用新依据时，模型同次明确提交 `additional_references`，Runtime 保留已有引用、去重合并新增项，并检查新位置属于本轮选择且实际可见；版本、片段及引用全部成立才产生一个新版。临时 typed 片段视图不写入 Journal，统一研究 Verifier 消费完整正文。每轮 Provider Schema 从本轮已选引用目录派生文档、连续行及部分行范围，并列出当前 claim 与片段身份；合法性仍由唯一 citation binder 和研究准入确定。

研究写作者当前可用 `delete_claim` 撤回一个已有论断；准入层核对当前版本和身份，保留其余项后重新核验完整集合。独立文档缺项分类及对应覆盖反馈已暂停，原用户目标、来源支持及最终回答一致性由统一研究核验检查。现行边界见 [ADR 0033](../adr/0033-claim-deletion-and-document-absence-pause.md)。

周期 Research digest 当前使用默认 `EvidenceEngine` 的启发式 grounding，具体判断及过滤由 [Research 链路](../workflow/research-once-workflow.md#digest-核验与投递)拥有。该组件标签与 Conversation 的模型语义核验分别记录，不能替代用户结果证据。

| 路径 | 触发 | 验证事实 | 消费者 |
| --- | --- | --- | --- |
| Conversation grounded answer | personal/tool Observations 到达后 | source constraint、citation、conflict 与 required evidence | Conversation revision / FinalMessage |
| Conversation 普通外部研究 | 同版本 claims 与最终回答已提交 | 来源支持、回答与研究一致性、回答满足原目标 | 原研究修订、补证或确切正文 Completion |
| Conversation Review | 用户显式要求审查文本时 | 最终文本是否满足冻结的用户明示判据 | revision loop / verified bytes |

Conversation Review 的 Runtime-owned trigger 和 receipt-bound bytes 是结构性案例，但不能作为
普通知识目标具备 Verify 元能力的证据。

## Conversation Grounded Answer

**Personal Knowledge 不再生成独立 Answer assessment；它只返回可验证的选择事实。** 模型选择 `search_personal_knowledge` 后，`KnowledgeService` 按 EvidenceSpan、Claim 状态、conflict 和 scope 产生有界结果。Conversation 把该 `tool_result` 与其他工具的 `Observation` 共同交给唯一 FinalMessage 责任主体。

执行事实、语义验证和完成仍分离：Tool/selection success 只证明读取发生；模型必须根据引用与冲突事实形成回答；缺 required evidence 时不能宣称完成。回答不会自动写回 Claim，显式保存必须另走确认写路径。

当前不维护第二个 Knowledge answer assessment；产品证据由 `ASK-001A/B` 直接从 Conversation 断言 scope、引用、冲突、source constraint 与零写入。

## Verification 与 Completion

**Verification 通过表示判断主体对当前候选给出了允许交付的判断，不能当作语义必然正确的证明。** Completion 检查任务契约所需的执行事实、适用判断及产物是否成立，并绑定当前交付；它不独立解释任意自然语言目标。普通直接回答使用 Conversation 的结果契约，个人知识读取只返回证据选择事实。

当前门禁分布在 [ConversationService](../../src/personal_agent/application/conversation/service.py)和 [research.accepted_research](../../src/personal_agent/application/conversation/research.py)等原责任入口，并非一个能自动验收所有能力的通用引擎。下列代码关系分别只能证明自己的边界：

- `_unread_offloaded_resources()` 在同一资源有成功补读后移除“从未查看”阻塞；读过一个窗口不能证明读全、证据充分或目标满足。
- `accepted_research()` 要求当前完整非空回答、有适用且无 findings 的研究报告，并恢复合法引用；`respond()` 进一步要求交付 segments 等于当前已批准回答。它们能约束报告适用性和正文绑定，不能纠正报告本身的语义漏放。
- `_verify_before_send()` 消费普通核验回执，检查通过结果及被评正文与当前提交一致；回执形状合法、条件枚举齐全，不等于判断正确。
- `InteractionIntent` 的原文片段准入证明被引文字确实来自用户；条件提取是否完整、改写是否忠实仍属于语义边界。

现行研究核验保留原会话、冻结 requirements、完整当前回答及实际资料，不能只凭提取条件列表或 Plan 完成状态交付。开放目标的解释和判断仍可能出错，已知标题被误判为完整正文的漏放见上文。设计中的依据归属、交付准入及停止分支由[主循环 Spec](../optimization/to_verify/conversation-loop-boundaries.md#41-完成依据从哪里来)拥有；本轮仅澄清事实和证明范围，未增加生产门禁或修改现行核验触发。

## 执行证据

研究实验完成按[ADR 0037](../adr/0037-experiment-submission-first-delivery.md)暂不接入claim／语义verifier：实际SubmittedFinal与usage先持久，确定性代码检查引用、原开发／最终执行、冻结及权限，缺口交回模型。通过后直接提交并返回同一Final，不创建清单、ZIP、报告副本或下载资源列表。Python原件仍由Artifact保存，终态和输入身份继续检查；Final、提交后恢复和已完成返回复用同一完成契约。入口为[research_delivery.py](../../src/personal_agent/application/conversation/research_delivery.py)，有效范围由[研究Spec §8.5](../optimization/to_verify/knowledge-decision-delivery.md#85-agent能力范围收回与删除计划)拥有。局部完成链通过不能替代研究语义或长任务证据。

- `ASK-001A`：Conversation 逐项引用互斥个人资料并明确冲突，禁止 web、跨 principal 泄漏和知识写入；
- `ASK-001B`：同一 FinalMessage 同时消费 personal knowledge 与官方 web Observation；

引用继承的决定性证据见[引用继承记录](../optimization/completed/claim-retained-references.md)；旧逐项来源报告的适用性与复用经验见[来源报告复用记录](../optimization/completed/claim-source-review-reuse.md)。当前研究按完整版本统一核验，报告复用须保持任务、Prompt、版本、绑定原文、实际返回资料和读取状态等决定性输入不变，契约见 [ADR 0032](../adr/0032-conversation-research-claims.md#2026-10-16-当前决定)。旧逐项 Source、Coverage 和独立汇总不再是生产阶段。
