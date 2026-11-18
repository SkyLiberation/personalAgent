# Verification 与 Completion

本文是 Agent 内部 Verification 架构、决策所有权和当前生产实例的 canonical 文档。产品用例和
Workflow 文档只引用这里，不复制另一套通用 Verifier 定义。

## 定位

Verification 是 Agent 内部元能力：

> 候选结果产生后、宣告完成前，依据用户 Goal、required result contract 和可见 Evidence，
> 判断候选结果是否语义满足，并产生 typed assessment 与 repair feedback。

“元能力”描述运行时义务。Conversation 的目标与回答核验、周期 Research digest 各有明确输入、判据和失败消费者，按各自业务契约核验。个人知识只返回证据；独立 Knowledge Answer 与后台 Investigation 的生产入口已经撤回。

用户显式要求“审查并修订一段文本”是 Conversation Review 产品能力，不是通用 Verification 的
触发前提，也不代表普通知识任务已经自动验证。

## 当前核验覆盖与适用边界

Conversation 分别核验目标定义与普通回答交付。目标核验接收原用户要求、候选及对应修订。普通回答核验接收生效目标、实际稿件和可定位的引用证据。Journal 保存原提议、判决及修订。目标通过只允许目标生效，Completion 继续消费实际交付事实。[统一主循环规格](../optimization/to_verify/analysis-goal-maintenance.md#统一-conversation-主循环)

2026-11-02按用户取消回答前强制读取及相关Prompt，当前完整goal仍逐次提供。精确命中失败缓存时，Runtime复用原语义回执，并将引用原判据与反馈的本次拒绝放在最新提议之后；不付费重判，也不再将该稿恢复为待交付稿。一次真实阶段修正后，新前三轮全部交付、独立[1,0,1]；第三问5次拒稿后的第6稿通过，历史接续及实际修复成立，第二问仍未通过独立评分。目标核验v7及其英文镜像未改；设计与边界由[Spec §9.7—§9.8](../optimization/to_verify/analysis-goal-maintenance.md#98-移除回答前强制读取并重新验证)拥有，原§27失败保留。早期Prompt失败见[历史记录 §12](../optimization/to_verify/verify_results/analysis-correctness.md#12-目标优先-prompt-的中英文修正)。

2026-11-01 当前维护goal交接候选在完整和最小充分输入下均未准确识别第三轮错误，未迁入生产；该历史候选由[Spec §9.6](../optimization/to_verify/analysis-goal-maintenance.md#96-当前执行目标接入既有目标核验)记录，不与本轮问答历史契约混用。

目标与回答核验由 [feature flags](../ablation/experiment.md) 独立控制，默认均开启。关闭核验不产生通过回执，仍检查真实引用、权限、执行及费用；关闭任一核验的采集不计完整 Product E2E 或发布证据。配置在 Journal 绑定，同对话不能切换。开关契约见 [ADR 0050](../adr/0050-verification-feature-flags.md)。

普通问答和外部资料研究均按统一协议提交正文，启用回答核验时按当前 Goal 核验。检索实验另按结果文件与执行事实交付。各路径共用目标维护、工具治理和已提交事实。[ADR 0055](../adr/0055-unified-conversation-answer.md)

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

适用的回答候选由 `verify_interaction_draft` 核对实际提交原文、来源支持及用户要求，回执绑定确切正文和相应判据。模板由注册表拥有，typed 参数序列化动态输入，外部内容作为数据。

Conversation 按目标或回答职责选择判据。目标核验消费原话和候选定义；回答核验消费原话、生效目标、实际稿件及适用证据。运行系统绑定本次核验输入和确切回执，失败返回原 Conversation 循环，修订稿重新验证。早期通用核验采用独立来源支持标准与 `criterion_id` 绑定，历史契约见 ADR 0020。[原文引用规则](../devSpec/code-structure.md#21-已有文字通过引用传递) · [来源标准决定](../adr/0020-require-conversation-source-support-verification.md) · [目标维护决定](../adr/0048-conversation-goal-maintenance.md)

意图提议的criterion为非空字符串，完整限定可超过500字符；不截断、重抄或为字数机械拆项，整体生成继续受原模型与任务预算约束。来源身份和语义正确性仍分别校验／评估，长度合法不等于标准正确。实际超长原件与取消上限的边界见[完整字符串承载](../optimization/completed/intent-criterion-length.md)。

当前整稿核验使用实际读取状态，仍须检查适用的来源支持，不得将未读内容当成已知事实。无据的全文否定须按来源支持与用户结果判据拒绝。独立文档缺项分类及其覆盖拒绝已暂停，取舍与历史证据见 [ADR 0033](../adr/0033-claim-deletion-and-document-absence-pause.md) 和 [ADR 0021](../adr/0021-separate-document-absence-from-reading-coverage.md)。

普通回答核验输出上限为 32,768 tokens。核验工具不设置独立 Gateway 超时或工具重试；模型调用仍受部署超时和交互预算约束，见[环境说明](../env.md#llm-配置)。扩大交互总预算不会改变请求输出上限。历史扩容对照见[推进记录第 54 节](../optimization/verifier-output-truncation.md#54-验证报告被局部预算截断的单边界资格检查)。

当前已知限制是 Verifier 可能把标题对主题的提及误判为正文已经满足详细比较要求，Draft 与 Evidence 同次输入还会放大该错误。固定反例在当前生产 Verifier 中受控重放三次，模型每次都把只存在于 Evidence 的三项比较正文与两个 URL 当成 Draft 已有内容，五项全部返回 `satisfied`。后续来源隔离与 typed segment 绑定候选虽然阻止了 Evidence 直接进入 Draft 判断，但最终仍有一次把唯一标题 segment 绑定给三项比较正文并错误通过。二态 aggregate 的路由职责不受影响；剩余问题属于 Draft 语义判别能力，不再允许通过增加来源字段、状态或同义 Prompt 修补。

## 当前生产实例

周期 Research digest 当前使用默认 `EvidenceEngine` 的启发式 grounding，具体判断及过滤由 [Research 链路](../workflow/research-once-workflow.md#digest-核验与投递)拥有。该组件标签与 Conversation 的模型语义核验分别记录，不能替代用户结果证据。

| 路径 | 触发 | 验证事实 | 消费者 |
| --- | --- | --- | --- |
| Conversation 回答及显式审查 | 回答核验开启，提交适用的答复候选 | 用户原话、生效目标、确切正文及适用证据 | Conversation 修订或确切正文交付 |

Conversation Review 的 Runtime-owned trigger 和 receipt-bound bytes 是结构性案例，但不能作为
普通知识目标具备 Verify 元能力的证据。

## Conversation Grounded Answer

**Personal Knowledge 不再生成独立 Answer assessment；它只返回可验证的选择事实。** 模型选择 `search_personal_knowledge` 后，`KnowledgeService` 按 EvidenceSpan、Claim 状态、conflict 和 scope 产生有界结果。Conversation 把该 `tool_result` 与其他工具的 `Observation` 共同交给唯一 FinalMessage 责任主体。

执行事实、语义验证和完成仍分离：Tool/selection success 只证明读取发生；模型必须根据引用与冲突事实形成回答；缺 required evidence 时不能宣称完成。回答不会自动写回 Claim，显式保存必须另走确认写路径。

当前不维护第二个 Knowledge answer assessment；产品证据由 `ASK-001A/B` 直接从 Conversation 断言 scope、引用、冲突、source constraint 与零写入。

## Verification 与 Completion

**Verification 通过表示判断主体对当前候选给出了允许交付的判断，不能当作语义必然正确的证明。** Completion 检查任务契约所需的执行事实、适用判断及产物是否成立，并绑定当前交付；它不独立解释任意自然语言目标。普通直接回答使用 Conversation 的结果契约，个人知识读取只返回证据选择事实。

当前门禁分布在 [ConversationService](../../src/personal_agent/application/conversation/service.py) 和[检索实验交付](../../src/personal_agent/application/conversation/research_delivery.py)等责任入口。下列关系分别证明各自边界：

- 外置结果是否补读由模型依据任务决定。实际返回的窗口提供可定位证据，逐份检查是否已读的交付条件已退役。[会话文件契约](../context/tool.md#会话文件替换决定)
- `_verify_before_send()` 消费普通核验回执，检查通过结果及被评正文与当前提交一致；回执形状合法、条件枚举齐全，不等于判断正确。
- 目标的确定性准入校验作用域、版本和结构，启用时由语义核验判断候选定义与用户要求是否一致。[目标维护决定](../adr/0048-conversation-goal-maintenance.md)

核验消费适用的用户原话、生效目标、完整候选及其实际引用证据。提取出的条件列表和 Plan 完成状态都不能单独作为交付依据。

## 执行证据

检索实验完成按 [ADR 0037](../adr/0037-experiment-submission-first-delivery.md)检查实际候选、引用、原开发／最终执行、冻结及权限。缺口交回模型；检查通过后直接提交并返回同一 Final。Python 原件仍由 Artifact 保存，恢复和已完成返回消费同一完成契约。入口为 [research_delivery.py](../../src/personal_agent/application/conversation/research_delivery.py)。

- `ASK-001A`：Conversation 逐项引用互斥个人资料并明确冲突，禁止 web、跨 principal 泄漏和知识写入；
- `ASK-001B`：同一 FinalMessage 同时消费 personal knowledge 与官方 web Observation；

独立分析的目标核验与回答核验已按职责拆分，当前契约见[Spec §9.14](../optimization/to_verify/analysis-goal-maintenance.md#914-分离目标核验与回答核验的职责及历史)。两者分别输出`UserRequirementAssessment`并聚合为原回执；新连续前三轮已交付，原分[1,1,1]、预声明用户结果通过／通过／失败，见[记录§34](../optimization/to_verify/verify_results/analysis-correctness.md#34-分离目标与回答核验的空会话连续前三轮)；旧失败由[记录§33](../optimization/to_verify/verify_results/analysis-correctness.md#33-逐项用户要求核验的空会话连续前三轮)保留。
