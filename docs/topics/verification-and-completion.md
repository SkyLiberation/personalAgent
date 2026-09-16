# Verification 与 Completion

本文是 Agent 内部 Verification 架构、决策所有权和当前生产实例的 canonical 文档。产品用例和
Workflow 文档只引用这里，不复制另一套通用 Verifier 定义。

## 定位

Verification 是 Agent 内部元能力：

> 候选结果产生后、宣告完成前，依据用户 Goal、required result contract 和可见 Evidence，
> 判断候选结果是否语义满足，并产生 typed assessment 与 repair feedback。

“元能力”描述运行时义务，不表示所有领域共享一个万能 `VerifierService`。Personal Knowledge Answer、
Conversation Review、Ask/RAG 和 Investigation Project 的判据 owner、输入事实、生命周期与
失败消费者不同，因此保留领域 verifier；它们共同遵守相同架构不变量。

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

当前候选由 Conversation 原生正文段提交引用；运行系统恢复每段全部指定的可见原文，局部 Verifier 先检查本段与依据。未引正文保留空证据，引用错误或支持拒绝返回既有循环。普通审查只取得提交引用的并集，不复制 Journal 或重新暴露未读全文。候选状态及验证边界见 [ADR 0023](../adr/0023-native-answer-segments-and-visible-citations.md)。模型逐条产生 criterion status 与 feedback，Verifier
adapter 只把所有 `satisfied` 聚合为 `passed`，任一 `not_satisfied` 或 `insufficient_evidence` 都聚合为 `failed`。逐判据三态与 feedback 仅供智能体诊断与恢复，运行系统不再根据失败类别重新开放或隐藏工具。汇总反馈缺失时，adapter 只从未满足 criterion 已有的 feedback 派生；逐判据反馈同样缺失时仍 fail closed。该派生不增加语义事实，也不能替代 Completion。

Conversation Verifier 当前使用 Registry 中的中文 `interaction_verification.system:v4-cited-evidence`，并固定加入 `interaction_verification.source_support:v1` 标准。模型必须逐条核对声明与实际证据的主体、条件、范围及强度；仅主题相关、URL 正确或没有发现矛盾不能替代支持。两份模板由同一工具消费，版本进入请求；JSON 输入由已有 typed 参数模型序列化，外部内容明确作为数据。

工具对用户标准与系统支持标准合并去重，要求报告恰好覆盖全部项。缺失或重复来源支持项不能形成有效回执，来源支持不通过就参与现有聚合并拒稿。用户原标准由 `InteractionIntent` 冻结，回执 `success_criteria` 与 `criteria_digest` 仍绑定这组原标准；系统判断在 `criterion_results` 中独立保留，不改写用户要求。失败通过现有 Conversation 循环返回模型，修订稿重新验证。既有触发范围与预算保持；原生引用候选改变输入物化和成文 Schema，不增加服务或循环。接入决定及剩余风险见 [ADR 0020](../adr/0020-require-conversation-source-support-verification.md)。

对于保存并卸载的来源，当前目标代码在普通审查前使用 `interaction_verification.document_absence:v3-source-flags`，返回与 `source_reading_state` 等长同序的严格布尔数组 `absence_by_source`，识别稿件是否对每个来源作出文档级缺项声明。Conversation 从可见成功执行记录物化来源读取状态；代码校验数量与来源唯一性，按位置绑定真实来源，对命中且未完整读取的项返回独立覆盖拒绝。模型不再复制原句或来源身份，反馈中的 `unread_sources` 由代码恢复。拒绝经现有工具网关回到修订循环，不生成语义回执；普通 `satisfied` 无权覆盖。完整读取只解除覆盖门禁，原稿仍须接受上述来源支持审查。事实范围、复杂度与未完成产品门禁见 [ADR 0021](../adr/0021-separate-document-absence-from-reading-coverage.md)。

当前验证调用的输出上限为 32,768 tokens，工具执行时限为 480 秒；工具自身不重试。两项上限分别允许 thinking 与完整报告输出、给模型请求及解析留出执行时间，仍可能因模型自身超时或协议错误失败。扩大交互总预算不会自动改变这些局部上限。旧 1,200-token / 60 秒限制已移除，同一真实首稿的预算对照取得完整绑定报告，但仍漏放无据权限归属结论；不能把报告返回与语义正确混为一谈。记录及产品验收限制见[推进记录第 54 节](../optimization/verifier-output-truncation.md#54-验证报告被局部预算截断的单边界资格检查)。

当前已知限制是 Verifier 可能把标题对主题的提及误判为正文已经满足详细比较要求，Draft 与 Evidence 同次输入还会放大该错误。固定反例在当前生产 Verifier 中受控重放三次，模型每次都把只存在于 Evidence 的三项比较正文与两个 URL 当成 Draft 已有内容，五项全部返回 `satisfied`。后续来源隔离与 typed segment 绑定候选虽然阻止了 Evidence 直接进入 Draft 判断，但最终仍有一次把唯一标题 segment 绑定给三项比较正文并错误通过。二态 aggregate 的路由职责不受影响；剩余问题属于 Draft 语义判别能力，不再允许通过增加来源字段、状态或同义 Prompt 修补。

## 当前生产实例

覆盖拒绝的模型可见说明现由版本化模板从真实读取状态生成，明确各来源尚未完整读取、计数单位和剩余范围，沿 `ToolArtifact.error` 进入原循环。它不替代 typed 覆盖事实，也不自动证明 Conversation 会正确修订。契约与验证边界见 [ADR 0021](../adr/0021-separate-document-absence-from-reading-coverage.md)和[第 105 节记录](../optimization/document-absence.md#105-用自然语言解释未完整读取与修订边界)。

| 路径 | 触发 | 验证事实 | 消费者 |
| --- | --- | --- | --- |
| Conversation grounded answer | personal/tool Observations 到达后 | source constraint、citation、conflict 与 required evidence | Conversation revision / FinalMessage |
| Investigation SubGoal | execution + Evidence Admission 后 | bounded SubGoal 是否被 admitted evidence 满足 | Outcome 或 verification repair |
| Investigation Final | final Artifact 生成后 | required coverage、claim/evidence、排除条件 | CompletionReport |
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

普通直接回答不为形式统一创建 CompletionReport；Personal Knowledge Answer 返回临时 assessment，
因为该 assessment 被 HTTP 用户实际消费，不持久化无消费者投影。

## 执行证据

- `ASK-001A`：Conversation 逐项引用互斥个人资料并明确冲突，禁止 web、跨 principal 泄漏和知识写入；
- `ASK-001B`：同一 FinalMessage 同时消费 personal knowledge 与官方 web Observation；
- `E08`：普通回答 Claim delta 为零，显式 solidify 后才发生 Knowledge 写入。
