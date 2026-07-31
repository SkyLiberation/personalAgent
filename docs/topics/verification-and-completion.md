# Verification 与 Completion

本文是 Agent 内部 Verification 架构、决策所有权和当前生产实例的 canonical 文档。产品用例和
Workflow 文档只引用这里，不复制另一套通用 Verifier 定义。

## 定位

Verification 是 Agent 内部元能力：

> 候选结果产生后、宣告完成前，依据用户 Goal、required result contract 和可见 Evidence，
> 判断候选结果是否语义满足，并产生 typed assessment 与 repair feedback。

“元能力”描述运行时义务，不表示所有领域共享一个万能 `VerifierService`。Workspace Answer、
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
| Workspace Answer | 候选 `EvidenceGroundedAnswer` 组装后 | 回答整体是否支持、冲突、coverage、unsupported claim | `/api/workspace/ask` 响应 |
| Ask/RAG | compose 后固定 stage，repair 后重验 | citation、claim grounding、evidence sufficiency | bounded retry / repair |
| Investigation SubGoal | execution + Evidence Admission 后 | bounded SubGoal 是否被 admitted evidence 满足 | Outcome 或 verification repair |
| Investigation Final | final Artifact 生成后 | required coverage、claim/evidence、排除条件 | CompletionReport |
| Conversation Review | 用户显式要求审查文本时 | 最终文本是否满足冻结的用户明示判据 | revision loop / verified bytes |

Conversation Review 的 Runtime-owned trigger 和 receipt-bound bytes 是结构性案例，但不能作为
普通知识目标具备 Verify 元能力的证据。

## Workspace Answer

`WorkspaceService.select_evidence()` 是 read-only 检索边界，只返回 typed EvidenceSpan、Citation、
Claim 支持状态和冲突事实，不生成候选回答，也不触发 Answer Verifier。Ask 的
`WorkspaceRetriever` 只调用该边界。

`WorkspaceService.answer_with_evidence()` 在 evidence selection 之后组装候选回答、Citation 和展示
projection。
`WorkspaceAnswerVerifier` 是唯一 answer-level semantic verification 写入口，输入为：

- 用户问题；
- 候选回答；
- 本次 selected/available EvidenceSpan；
- CoverageManifest。

输出的 canonical `AnswerVerificationAssessment` 包含：

```text
verdict: passed | needs_revision | insufficient_evidence
conclusion_status: supported | conflicted | insufficient_evidence
evidence_coverage
conflicts -> evidence_span_ids
unsupported_claims
missing_sections
feedback
verifier identity/version
```

`conclusion_status=conflicted` 表示知识结论仍冲突；它不同于 `verdict`。一个明确、忠实呈现冲突的
报告可以通过验证，而一个只是并列两条互斥陈述却未标出冲突的候选回答必须
`needs_revision`。

Verifier 返回的 conflict ref 必须由确定性 Admission 证明属于本次 selected EvidenceSpan。
Assessment 是正式 Workspace Answer 的当前响应事实，不写回长期 Claim/Relation，也不投影到 Ask
evidence。Ask 自己的最终回答由 Ask Verifier 判断，避免对被丢弃的内部答案重复验证。

旧 `grounding_status`、`answer_claim_grounded_count`、顶层 `evidence_coverage` 和
`missing_sections` 已删除。它们由回答组装器根据 selected 数量推导，会形成第二个验证写入口。

## Verification 与 Completion

Verification 通过只说明某个候选结果满足相应语义标准。只有 required result contract 的全部
义务、assessment evidence 和 Artifact 齐全后，Completion Gate 才能进入领域终态。

普通直接回答不为形式统一创建 CompletionReport；Workspace Answer 返回临时 assessment，
因为该 assessment 被 HTTP 用户实际消费，不持久化无消费者投影。

## 执行证据

- B04 baseline：archive `20260731T063040.820774Z-16696-c3646c8a`。正式 HTTP 回答同时包含互斥日期，
  未标 conflict，却写 `supported` 和“全部 grounded”。
- E20 target-failure：archive `20260731T063538.487874Z-48204-345f5a84`，缺少独立
  `verification`。
- E20 target：archive `20260731T064446.108938Z-8804-52b29d3c`，独立 Verifier 返回
  `needs_revision/conflicted`，conflict refs 全部绑定本次 citations，Ask 前后 Claim 数不变。

设计、迁移和复杂度证据见 [ADR 0011](../adr/0011-independent-workspace-answer-verification.md)。
