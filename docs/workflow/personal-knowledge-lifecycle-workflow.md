# Personal Knowledge 知识生命周期

`KnowledgeService` 将资料保存与知识论断准入分为两个阶段。资料成功入库后，即使语义提取失败，原文和诊断仍可保存；面向回答的读取则先选择可回答 Claim，再恢复其有效原文引用。事实归属、读取过滤及纠错规则由 [Memory 专题](../topics/memory.md)拥有。

## 摄取与增强入口

生产入口位于 [KnowledgeService](../../src/personal_agent/application/knowledge/service.py)，返回结构由 [知识模型](../../src/personal_agent/application/knowledge/models.py)定义。

| 入口 | 执行内容 | 结果边界 |
| --- | --- | --- |
| `ingest_knowledge()` | 保存 `Artifact`、`ExtractionRun`、`EvidenceBlock`、`EvidenceSpan` 和初始 `KnowledgeItem`，提交证据索引与界面卡片投影任务 | 资料和可定位原文已保存，Claim 仍待增强 |
| `enhance_claim_lifecycle()` | 在摄取结果上抽取 Claim，执行 grounding、准入和关系判断，保存支持、状态、冲突及投影事实 | 各 Claim 按自己的支持和准入结果进入生命周期 |
| `ingest_text()` | 顺序调用上述两个入口 | 一次请求完成资料摄取和 Claim 增强，仍保留两阶段结果 |

```text
资料原文
  -> Artifact / EvidenceBlock / EvidenceSpan
  -> 初始 KnowledgeItem + 证据投影任务
  -> Claim 提取 Proposal
  -> Grounding / Admission / Relation
  -> Claim 状态、支持记录、冲突与知识卡片
  -> Claim / Review / Graph 投影任务
```

语义提取结果作为 Proposal 进入 Application。保存 `EvidenceSpan` 前，Application 按 `EvidenceBlock.full_context` 校验位置；局部原文片段扩展到包含它的最小完整句子，并重算 offset、locator 和 quote hash。Claim 的 `source_role`、`assistant_inference` 与实际 `created_by/source_type` 对应；`uncertain_claim` 必须带非空 `uncertainty_reason`。

提取或结构校验失败时，现行代码在 `ExtractionRun` 记录 `partial` 与具体错误，再调用本地提取器重建候选。Admission 接收重新构造的候选，不静默改写已被拒绝的模型 Proposal。该实现事实不代表语义提取或完整用户结果已通过验收。

## 状态与投影

`Artifact` 保存来源原文，`EvidenceBlock/EvidenceSpan` 提供上下文和位置，Claim 保存被准入的论断，`KnowledgeItem` 展示生命周期状态。初始卡片使用 `evidence_ready` 与 `claims_pending`；语义证据提取失败时标为 `partial_failed`。增强产生 Claim 卡片后，初始卡片转为 `deprecated`，避免同一资料在活动视图中重复展示。

`ProjectionJob` 将事实写入与下游刷新分开：

| 阶段 | 投影任务 |
| --- | --- |
| 资料摄取 | `project_evidence_indexes`、`project_ui_card` |
| Claim 增强 | `project_claim_indexes`、`project_review`、`project_graph` 等适用任务 |

投影由任务执行者刷新，可按来源重建；业务修改继续经过 Knowledge 写入口。投影失败与原文是否保存、Claim 是否准入分别判断，不能用索引存在代替业务成功。

## Conversation 读取与 Capture 协作

Conversation 在模型选择 `search_personal_knowledge` 后，通过 `ConversationKnowledgeReadPort` 复用 `KnowledgeService.select_evidence()`。读取先检查身份和生命周期，再从可回答 Claim 恢复有效 `EvidenceRef`、原文 citation 与冲突事实，返回有界 `Observation`。没有可回答 Claim 的原始 `EvidenceSpan` 不独立进入答案。

Conversation 消费个人证据及其他获准只读结果，生成唯一 `FinalMessage`。问答不写回长期知识；用户明确保存时走确认和 canonical 写入口。完整交接见 [Capture 与 Conversation Grounded Answer](capture-ask-model-flow.md)，最终验收见[核验专题](../topics/verification-and-completion.md)。

Capture 管理笔记、去重、chunk 和适用的复习、图谱同步；Personal Knowledge 管理原文证据与 Claim 生命周期。两者提供各自的资源与投影，当前产品由 Conversation 选择、消费和交付，不再通过独立 Ask workflow 自动合成第二份答案。

## 验证依据

用户结果、引用保真、身份隔离、冲突展示及问答零写入，按[当前用例盘点](../evals/02-current-case-inventory.md)中的实际证据分别验收。对象存在、投影任务生成和历史回答 DTO 中的 `evidence_coverage/missing_sections` 不作为当前产品完成判据。新验证遵守 [QLT](../devSpec/quality-security.md#1-测试职责与覆盖)，历史单元测试只读保留。
