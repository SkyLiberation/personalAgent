# Verification 与 Completion

本文是 Agent 内部 Verification 架构、决策所有权和当前生产实例的 canonical 文档。产品用例和
Workflow 文档只引用这里，不复制另一套通用 Verifier 定义。

## 定位

Verification 是 Agent 内部元能力：

> 候选结果产生后、宣告完成前，依据用户 Goal、required result contract 和可见 Evidence，
> 判断候选结果是否语义满足，并产生 typed assessment 与 repair feedback。

“元能力”描述运行时义务。Conversation 的来源支持、研究覆盖、最终交付以及周期 Research digest 各有明确输入、判据和失败消费者，按各自业务契约核验。个人知识只返回证据；独立 Knowledge Answer 与后台 Investigation 的生产入口已经撤回。

用户显式要求“审查并修订一段文本”是 Conversation Review 产品能力，不是通用 Verification 的
触发前提，也不代表普通知识任务已经自动验证。

## 决策所有权

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

外部研究当前采用版本化 claims 作为中间产物：研究 Verifier 拥有来源支持与事实覆盖；复合论断识别 Verifier 已停用，不再生成结构诊断。研究选证、写作和覆盖共享冻结验收项的只读编号。覆盖接收当前 claims、全部实际返回的去重可引用读窗及执行派生读取状态，独立判断原项的必要事实关系，反馈绑定原项、当前 claim 和实际坐标；未读正文经原动作入口取得。Runtime 校验原项全集、claim 身份及引用，汇总研究充分性。URL 呈现、语言与提交过程通过 `delivery_check` 交给最终核验；来源网址无需再次出现在网页正文行或 claim 正文中。运行系统从已引用证据的执行来源确定性生成 `ResearchBasis.sources`，独立汇总接收该绑定并负责呈现用户要求的 URL；最终 Verifier 拥有对已核验事实的忠实性及用户结果判据。最终 Receipt 绑定当前 `research_ref`，Completion 同时校验研究版本和完整正文，研究通过不等于最终交付。普通非研究草稿继续直接对提交依据核验。装配和证据边界见 [ADR 0032](../adr/0032-conversation-research-claims.md)。

普通非研究候选由 Conversation 原生正文段提交引用；运行系统恢复每段全部指定的可见原文，局部 Verifier 先检查本段与依据。未引正文保留空证据，引用错误或支持拒绝返回既有循环。普通审查只取得提交引用的并集，不复制 Journal 或重新暴露未读全文。候选状态及验证边界见 [ADR 0023](../adr/0023-native-answer-segments-and-visible-citations.md)。模型逐条产生 criterion status 与 feedback，Verifier
adapter 只把所有 `satisfied` 聚合为 `passed`，任一 `not_satisfied` 或 `insufficient_evidence` 都聚合为 `failed`。逐判据三态与 feedback 仅供智能体诊断与恢复，运行系统不再根据失败类别重新开放或隐藏工具。汇总反馈缺失时，adapter 只从未满足 criterion 已有的 feedback 派生；逐判据反馈同样缺失时仍 fail closed。该派生不增加语义事实，也不能替代 Completion。

逐行引用当前通过 `CitedEvidence.source` 保留执行记录中的 `ResourceRef`、已知来源 URL、行号及起始列；来源元数据与读取覆盖共用确定性派生入口。局部核验接收原文及来源，普通整稿语义核验还接收实际读取状态。模型仍只提交 `evidence_id`，未知 URL 为空，完整工具结果保留原有内容；来源正确不能替代原文支持。修复的局部证据及完整 E2E 限制见 [ADR 0028](../adr/0028-preserve-citation-source-binding.md)。

普通整稿的局部支持核验使用 `interaction_verification.cited_support:v3-asserted-scope`。研究来源核验使用 `conversation.research.support:v1-bounded-feedback`，两者共享来源支持判据正文；研究 typed 反馈分别表达无据声明、已有支持范围、缺少前提和当前片段 ID，相关证据 ID 从原绑定确定性恢复给选证模型及写作者。模型先确定草稿实际主体、条件、强度及范围，再逐项核对可见依据；局部句内观察不能被扩大为全文否定，一个事实有据不能替同段其他事实放行。模型仍只输出相关证据 ID 和具体支持缺口；工具以 `checked_draft` 绑定本次精确段落，连同拒稿正文与意见交回原循环。证据 ID 只在当前单元校验；空发现继续后续核验，不证明完整用户结果。调用绑定由 [ADR 0029](../adr/0029-bind-verifier-feedback-to-input-unit.md)拥有，判别效果与限制见[范围一致性记录](../optimization/claim-verifier-consistency.md)。

Conversation Verifier 当前使用 Registry 中的中文 `interaction_verification.system:v5-criterion-references`，并固定加入 `interaction_verification.source_support:v1` 标准；研究最终核验使用 `conversation.research.final_verification:v5-revision-comparison`。研究最终请求保留 canonical binder 恢复的 `cited_units`，按顺序与 `research_segments` 的完整文字一一对应；每段带入其实际引用的原文及来源 URL。最终 Verifier 对照整段指代和具体页面的支持关系；多来源合法，某页面的陈述须由该页面支持。修订时 Runtime 从最近适用拒绝 Receipt 恢复旧稿和失败反馈，校验相同研究版本、冻结原项及上一稿正文；工具校验 digest/ID，并只带入旧稿、失败项与反馈。最终核验分别检查旧问题修复、全部语义变化及当前支持，核对完整清单数量和全文事实一致性；旧稿和旧意见不成为事实权威。接入与验证边界见[修订比较候选](../optimization/to_verify/final-revision-comparison.md)。模型必须逐条核对声明与实际证据的主体、条件、范围及强度；仅主题相关、URL 正确或没有发现矛盾不能替代支持。模板由同一工具消费，版本进入请求；JSON 输入由 typed 参数模型序列化，外部内容明确作为数据。

工具对用户标准与系统支持标准合并去重，从本次完整原文只读派生 `VerificationCriterion` 的 `criterion_id` 与 `criterion`。普通和研究最终模型只返回每个 ID 的三态及反馈，动态 Schema 列出当前合法身份与结果数量；工具再检查全部项恰好一次。Runtime 从当前输入恢复原文，形成 `BoundVerificationCriterionResult` 和回执，不以模型重抄文字识别验收项。未知、遗漏或重复 ID 产生明确输出契约失败，不形成有效回执；来源支持不通过参与现有聚合并拒稿。

用户原标准由 `InteractionIntent` 冻结，回执 `success_criteria` 与 `criteria_digest` 仍绑定这组原标准；系统判断在 `criterion_results` 中独立保留，不改写用户要求。回执保留原文用于反馈和审计；三态、修订意见及研究事实缺口由模型判断，恢复引用不改变它们。失败通过现有 Conversation 循环返回模型，修订稿重新验证。既有触发范围与预算保持，不增加模型阶段、服务或循环。原文引用规范由 [COD](../devSpec/code-structure.md#21-已有文字通过引用传递)拥有，接入责任见 [ADR 0020](../adr/0020-require-conversation-source-support-verification.md)。

当前生产链暂停独立文档缺项分类及其覆盖拒绝，研究与普通 Final 均直接进入仍适用的来源支持核验。普通整稿语义核验保留实际读取状态作为数据，但不能将未读内容当成已知事实；无据全文否定仍须按来源支持与用户结果判据拒绝。`evidence_sufficiency` 原先只负责越过独立覆盖拦截，现已随该分支移除。历史覆盖拒绝与补读恢复检查点见 [ADR 0021](../adr/0021-separate-document-absence-from-reading-coverage.md)，当前取舍、风险及退出条件见 [ADR 0033](../adr/0033-claim-deletion-and-document-absence-pause.md)。

当前验证调用的输出上限为 32,768 tokens，工具执行时限为 480 秒；工具自身不重试。两项上限分别允许 thinking 与完整报告输出、给模型请求及解析留出执行时间，仍可能因模型自身超时或协议错误失败。扩大交互总预算不会自动改变这些局部上限。旧 1,200-token / 60 秒限制已移除，同一真实首稿的预算对照取得完整绑定报告，但仍漏放无据权限归属结论；不能把报告返回与语义正确混为一谈。记录及产品验收限制见[推进记录第 54 节](../optimization/verifier-output-truncation.md#54-验证报告被局部预算截断的单边界资格检查)。

当前已知限制是 Verifier 可能把标题对主题的提及误判为正文已经满足详细比较要求，Draft 与 Evidence 同次输入还会放大该错误。固定反例在当前生产 Verifier 中受控重放三次，模型每次都把只存在于 Evidence 的三项比较正文与两个 URL 当成 Draft 已有内容，五项全部返回 `satisfied`。后续来源隔离与 typed segment 绑定候选虽然阻止了 Evidence 直接进入 Draft 判断，但最终仍有一次把唯一标题 segment 绑定给三项比较正文并错误通过。二态 aggregate 的路由职责不受影响；剩余问题属于 Draft 语义判别能力，不再允许通过增加来源字段、状态或同义 Prompt 修补。

## 当前生产实例

研究写作者以完整 `base_ref`、claim_id 和首尾片段 ID 指定正文修订范围；Runtime 从当前 canonical 稿恢复原文并合并。临时 typed 片段视图不写入 Journal，来源 Verifier 和独立汇总继续消费完整正文。每轮 Provider Schema 从本轮已选引用目录派生文档、连续行及部分行范围，并列出当前 claim 与片段身份；合法性仍由唯一 citation binder 和研究准入确定。

研究写作者当前可用 `delete_claim` 撤回一个已有论断；准入层核对当前版本和身份，保留其余项后重新核验完整集合。独立文档缺项分类及对应覆盖反馈已暂停，原用户事实覆盖、来源支持和最终语义核验仍运行。现行边界见 [ADR 0033](../adr/0033-claim-deletion-and-document-absence-pause.md)。

周期 Research digest 当前使用默认 `EvidenceEngine` 的启发式 grounding，具体判断及过滤由 [Research 链路](../workflow/research-once-workflow.md#digest-核验与投递)拥有。该组件标签与 Conversation 的模型语义核验分别记录，不能替代用户结果证据。

| 路径 | 触发 | 验证事实 | 消费者 |
| --- | --- | --- | --- |
| Conversation grounded answer | personal/tool Observations 到达后 | source constraint、citation、conflict 与 required evidence | Conversation revision / FinalMessage |
| Conversation 外部研究 | 当前 claims 提交或合法编辑后 | 每条来源支持及原用户事实覆盖 | 研究修订、补证或独立汇总 |
| Conversation 研究最终交付 | 独立汇总提交后 | 对已核验事实的忠实性、具体来源归属及用户交付判据 | 同版本 FinalMessage / Completion |
| Conversation Review | 用户显式要求审查文本时 | 最终文本是否满足冻结的用户明示判据 | revision loop / verified bytes |

Conversation Review 的 Runtime-owned trigger 和 receipt-bound bytes 是结构性案例，但不能作为
普通知识目标具备 Verify 元能力的证据。

## Conversation Grounded Answer

**Personal Knowledge 不再生成独立 Answer assessment；它只返回可验证的选择事实。** 模型选择 `search_personal_knowledge` 后，`KnowledgeService` 按 EvidenceSpan、Claim 状态、conflict 和 scope 产生有界结果。Conversation 把该 `tool_result` 与其他工具的 `Observation` 共同交给唯一 FinalMessage 责任主体。

执行事实、语义验证和完成仍分离：Tool/selection success 只证明读取发生；模型必须根据引用与冲突事实形成回答；缺 required evidence 时不能宣称完成。回答不会自动写回 Claim，显式保存必须另走确认写路径。

当前不维护第二个 Knowledge answer assessment；产品证据由 `ASK-001A/B` 直接从 Conversation 断言 scope、引用、冲突、source constraint 与零写入。

## Verification 与 Completion

Verification 通过只说明某个候选结果满足相应语义标准。只有 required result contract 的全部
义务、assessment evidence 和 Artifact 齐全后，Completion Gate 才能进入领域终态。

普通直接回答使用 Conversation 的结果契约；个人知识读取返回证据选择事实。内部 assessment 和 Receipt 由适用核验阶段产生，Completion 校验它们与当前提交的一致性。

## 执行证据

- `ASK-001A`：Conversation 逐项引用互斥个人资料并明确冲突，禁止 web、跨 principal 泄漏和知识写入；
- `ASK-001B`：同一 FinalMessage 同时消费 personal knowledge 与官方 web Observation；

2026-10-01 引用继承契约：正文片段修订由 Runtime 保留目标 claim 已绑定引用；替换引用仅对新增坐标检查本轮选择，创建和增补的引用全部经过选择。正式写作者的引用原文目录从本轮选择与当前集合绑定的可见坐标恢复，合法编辑后的完整新版仍经过来源支持和事实覆盖。版本、claim 与片段范围、来源绑定及最终结果门禁继续由原责任主体拥有；本轮证据见[引用继承记录](../optimization/completed/claim-retained-references.md)。

2026-10-01 来源报告消费契约：每次合法编辑先绑定当前所有引用，修改项核验整条正文；同次 `respond` 固定模型绑定范围内，未变正文、引用、原文与来源身份和判据版本的项消费原 Journal 最新适用报告，包括拒绝。新的调用边界及显式重验重新建立来源判断。全部项有适用通过后，仍核验当前完整事实覆盖；研究反馈不作为来源事实，修订补入的否定与解释同样须受原文支持。机制与验收分别见[来源报告复用固化记录](../optimization/completed/claim-source-review-reuse.md)和[支持范围修订候选](../optimization/to_verify/claim-supported-scope-repair.md)。
