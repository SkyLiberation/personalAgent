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

## 当前生产实例

| 路径 | 触发 | 验证事实 | 消费者 |
| --- | --- | --- | --- |
| Conversation grounded answer | personal/tool Observations 到达后 | source constraint、citation、conflict 与 required evidence | Conversation revision / FinalMessage |
| Investigation SubGoal | execution + Evidence Admission 后 | bounded SubGoal 是否被 admitted evidence 满足 | Outcome 或 verification repair |
| Investigation Final | final Artifact 生成后 | required coverage、claim/evidence、排除条件 | CompletionReport |
| Conversation Review | 用户显式要求审查文本时 | 最终文本是否满足冻结的用户明示判据 | revision loop / verified bytes |

Conversation Review 的 Runtime-owned trigger 和 receipt-bound bytes 是结构性案例，但不能作为
普通知识目标具备 Verify 元能力的证据。

## Conversation Grounded Answer

**Personal Knowledge 不再生成独立 Answer assessment；它只返回可验证的选择事实。** `KnowledgeService.select_evidence()` 拥有 selected EvidenceSpan、Claim 状态、conflict 与 scope，Conversation 将其作为 `personal_knowledge_context` Observation 消费，并与其他 Tool Observation 共同生成唯一 FinalMessage。

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
