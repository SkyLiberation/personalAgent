# ADR 0011: Personal Knowledge 证据选择与回答验证边界

> **状态：Superseded（2026-08-12）。** ASK-001 证明 Conversation 已覆盖 personal-only 与 multi-source grounded answer；独立 `/api/knowledge/ask`、`EvidenceGroundedAnswer` 与专用 answer verifier 已删除。本文仅保留历史决策背景，当前契约见 [Capture 与 Conversation Grounded Answer](../workflow/capture-ask-model-flow.md)。

- 状态：Accepted
- 日期：2026-07-31
- 影响范围：`POST /api/knowledge/ask` 的候选回答与验证，以及 Ask 的 Personal Knowledge 证据检索
- Baseline archive：`20260731T063040.820774Z-16696-c3646c8a`
- Target-failure archive：`20260731T063538.487874Z-48204-345f5a84`

## Goal / Current Incorrect Behavior / Expected User-visible Result

用户要求核对两份互相矛盾的知识材料时，响应必须明确冲突，并且不得因为每条陈述各自能指向
一段 Evidence 就把整体结论标成已支持。

当前 `KnowledgeService.answer_with_evidence()` 同时组装回答和写入
`grounding_status`、`answer_claim_grounded_count`。B04 从正式 HTTP 入口实际证明：响应同时包含
“日期是 2026-09-10”和“日期不是 2026-09-10，而是 2026-10-15”，没有标出冲突，却返回
`grounding_status=supported`，并把全部生成 Claim 计为 grounded。

期望结果是候选回答与独立 `verification` assessment 同时返回。assessment 必须绑定本次可见
EvidenceSpan；冲突未在候选回答中正确表达时返回 `needs_revision/conflicted`，不能宣告支持。

另一个已执行 baseline 证明：claim-sensitive Ask 通过 `KnowledgeRetriever` 召回证据时，会调用
`answer_with_evidence()`，生成一个不会交付的 Personal Knowledge 候选回答、执行一次 Personal Knowledge Answer
Verifier，再丢弃候选回答，只把 citation 和 answer-level assessment 复制到 Ask evidence。最终
Ask 随后还会再次 compose 和 verify。这使检索能力内部嵌套了完整回答框架，也让一个未交付答案的
语义结论参与单条 evidence 的评分。

## Business Expansion or Proven Constraint / Out of Scope

已证明约束：局部 citation 存在不能确定性推出候选回答整体语义成立。回答组装器不是
Semantic Verification owner。

Out of Scope：通用反思 Agent、Planner、自动多轮修订、持久化 VerificationReport、Project
Completion 语义、长期 Claim/Relation 生命周期重写，以及 Ask 最终 Verifier 的替换。

## Simplest Baseline E2E / Executed Result / Root Cause

Persona：使用个人知识工作区核对项目迁移日期的用户。

Given：通过正式 HTTP 写入两份互相矛盾、带随机业务主体的材料。

When：调用 `POST /api/knowledge/ask`，自然要求逐项列出候选结论和原文证据、明确冲突，并禁止在
冲突未解决时标成已支持。

Then：B04 自动断言相反日期同时出现在回答中、没有 conflict 事实、却返回 supported 且所有
answer claim grounded。命令：

```text
uv run pytest -q evals/e2e_quality/test_product_capability_outcomes.py::test_baseline_b04_knowledge_answer_misses_conflict_and_marks_supported --e2e-scope=diagnostic -s
```

实际结果：`1 passed in 22.11s`。根因是回答组装代码按 selected Evidence 数量和“存在任一
selected”直接写验证结论；`AnswerCoverageJudge` 只判断选择覆盖，不读取候选回答，无法拥有
answer-level verification。

Ask 边界 baseline 从 `AskService` 正式 Application Use Case 进入，输入
“Northstar 的迁移日期是否冲突？”。改造前实际结果是 Personal Knowledge evidence 成功进入统一证据池，
同时记录到一次 `knowledge_answer_semantic_verification`，且每条 evidence 都包含
`answer_verification` 镜像。命令：

```text
.\.venv\Scripts\python.exe -m pytest -q tests/test_knowledge_ask_boundary.py
```

baseline 断言执行结果：`1 passed in 2.45s`。

## Target E2E and Counterfactuals

E20 使用同一正式入口、事实形状和自然用户目标，要求：

- 响应包含独立 `verification`；
- `verdict=needs_revision`、`conclusion_status=conflicted`；
- conflict 引用只能绑定本次 citation 中的 EvidenceSpan；
- Ask 前后 Claim 数不变；
- 不再暴露由回答组装器写入的 `grounding_status`、`evidence_coverage`、
  `missing_sections`、`answer_claim_grounded_count`。

改造前目标 E2E 已实际失败：`KeyError: verification`，archive
`20260731T063538.487874Z-48204-345f5a84`。

Ask 边界的目标用同一自然输入执行 retrieve、compose、Ask verify 和 repair，要求最终答案包含
两个日期及 Personal Knowledge citation，同时 Personal Knowledge Answer Verifier 调用次数为零，Ask evidence 不含
`answer_verification`。改造前实际失败于 metadata 镜像仍存在。

## Decision Ownership / Fact Owner and Write Path

| 事实或决策 | Owner | 唯一写入口 |
| --- | --- | --- |
| Artifact、EvidenceBlock、EvidenceSpan | Personal Knowledge Store | ingestion path |
| 长期 Claim 与 conflict Relation | Personal Knowledge Aggregate/Application | Claim lifecycle path |
| 针对问题选择 Evidence 与 Claim 状态 | Personal Knowledge Application | `select_evidence()` |
| 候选回答及 citation 展示 | Personal Knowledge Application | `answer_with_evidence()` |
| 候选回答是否满足用户目标 | Personal Knowledge Answer Verifier | `verify()` |
| Ask 最终回答及其语义验证 | Ask Application / Ask Verifier | compose / verify stages |
| verifier 引用是否属于本次 Evidence | 确定性 Admission | verifier adapter |
| HTTP 展示结构 | Personal Knowledge route / DTO | `EvidenceGroundedAnswer` |

Verifier 不写 Claim/Relation，不改变 Execution Fact，不决定 Project Completion。

## Required Production Capabilities and Missing-capability Delivery

- 已有：真实结构化模型 Port、EvidenceSpan、CoverageManifest、HTTP E2E、PostgreSQL scope。
- 需扩展：读取候选回答、问题和 Evidence 的 answer-level semantic verifier。
- 需分离：一个不生成回答、不触发 Answer Verifier 的 typed read-only evidence selection。
- 删除替代：移除只看 selected/available 的 `AnswerCoverageJudge`，不保留双轨 coverage verdict。
- 能力缺失：返回 typed `insufficient_evidence` assessment，禁止 fixture 或启发式结果冒充生产通过。

## Affected Modules and Dependency Direction

`adapters/web -> application/knowledge -> capabilities/contracts/model`，Domain/Personal Knowledge models 不依赖
模型 SDK。生产模型实现使用已有 `StructuredModelClient` Port；Composition Root 注入。

## Complexity Added, Removed and Rejected Alternatives

Added：一个 answer verification assessment、一个生产 verifier、一个仅供离线 contract/unit 使用的
fixture verifier，以及一个瞬态 `KnowledgeEvidenceSelection`。

Removed：`AnswerCoverageJudgment`、`AnswerCoverageJudge`、LLM/local coverage judge、
`_answer_coverage()`、未使用的 `_evidence_coverage()`、四个镜像响应字段，以及调用方对
`grounding_status` 的读取；Ask 不再调用 `answer_with_evidence()`，不再复制 answer assessment，
也不再用 `conclusion_status` 给单条 evidence 评分。

拒绝：

- 创建跨 Conversation/Ask/Project 的万能 Verifier：三者判据 owner、生命周期和完成消费者不同；
- 只在 `len(selected)` 分支补 conflict 条件：仍由回答组装器冒充语义 Verifier；
- verifier 直接改写回答：会混合 Proposal 与 Verification；
- 自动反思循环：B04 只证明 fail-closed assessment 缺失，没有证明额外模型轮次的收益。

## Removed Legacy Path / Risks

本次是响应契约和内部能力边界迁移，不保留旧字段 alias 或双写。正式 Personal Knowledge Answer 读取
canonical `verification`；Ask 只读取 `KnowledgeEvidenceSelection` 中的 citation、Claim 支持状态
和冲突事实。

风险：一次模型 Verifier 可能增加延迟并出现语义方差；E20、contract tests 和 paired baseline
记录判断质量与耗时。若 E20 重复运行不能稳定识别同一明显冲突，或用户结果不优于 B04，则移除
该实现，回到更具体的 required result contract，而不是增加通用反思层。

## Executed Verification / Net Complexity / Remaining Risk

- B04 baseline：`1 passed in 22.11s`，archive
  `20260731T063040.820774Z-16696-c3646c8a`；
- E20 改造前 target：按预期失败于缺少 `verification`，archive
  `20260731T063538.487874Z-48204-345f5a84`；
- E20 改造后：`1 passed in 22.41s`，archive
  `20260731T064446.108938Z-8804-52b29d3c`；
- E02 + E20 最终对照：`2 passed in 33.25s`，普通回答为 `passed/supported`，冲突核对为
  `needs_revision/conflicted`，archive `20260731T065454.238105Z-51564-b8d1436c`；
- Personal Knowledge/Verifier/catalog/release gate：31 passed；
- Ask verifier、entailment 和 context：27 passed；
- Runtime/retrieval：19 passed；
- Ask 边界目标：`2 passed in 1.18s`；聚焦 Personal Knowledge/Ask 回归：`70 passed in 3.71s`；
- Ruff：通过；`scripts/check_layers.py`：packages=14、edges=53、cycles=none、
  forbidden_edges=0；
- release matrix collect-only：26 个 release 用例成功收集，E20 已进入 `grounded_ask` gate。

净变化：删除 selection coverage 模型、Port、fixture、两个 service 方法和四个镜像响应字段；增加
一个读取候选回答的 Verifier、一个 canonical assessment、一个瞬态 evidence selection 和边界测试。
Direct Personal Knowledge Ask 仍执行一次 answer verification；claim-sensitive Ask 每次检索减少一次被丢弃
答案的生成/验证，并删除其 assessment projection。

剩余风险：当前 direct Personal Knowledge Ask 在 `needs_revision` 时 fail closed 并返回 assessment，尚未
自动修订候选回答；完整 clean-revision release matrix 未执行。一次包含 `tests/test_api.py` 的合并
低层命令超过 180 秒且没有完成结果，不能计入通过；它没有产生指向本次 Personal Knowledge 契约的失败证据。
