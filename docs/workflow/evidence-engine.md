# Evidence Engine

**EvidenceEngine 提供证据归一、装配和 grounding 组件。** 周期 Research digest 的验证链是其生产消费者；Conversation 的个人知识读取直接使用 `KnowledgeService.select_evidence()`，最终回答由 Conversation 唯一拥有。

## 代码边界

| 模块 | 职责 |
| --- | --- |
| `kernel/evidence.py` | `SourceDocument`、`EvidenceItem`、`ContextPack` 与纯转换/选择函数 |
| `application/evidence_engine.py` | source normalization、evidence assembly、compression、claim grounding |
| `application/candidate_fusion.py` | 多检索来源候选融合 |
| `application/rerankers.py` | 显式配置的 component reranker |
| `application/candidate_enrichers.py` | parent/child 候选补全机制 |

分层的判据是生产消费者与不变量，不是为了凑齐 facade。`EvidenceEngine` 不保存 canonical business facts；输入和输出都是可重建的运行投影。

## 核心流程

```text
SourceDocument / EvidenceItem
  -> SourceNormalizer
  -> EvidenceAssembler
       -> dedupe / candidate fusion
       -> optional enrichment / rerank
       -> budgeted ContextPack
  -> ClaimGrounder.verify_claims
  -> typed EvidenceClaimCheck
```

### Source normalization

不同 Provider 必须保留 `source_id/source_ref/canonical_url/title/snippet/provider`。只有 synthesized answer、没有 source/citation binding 的结果不能进入 evidence pool。

### Assembly

`EvidenceAssemblyRequest` 显式携带 question、候选、预算、policy 和 caller 提供的 reranker/enricher。结果包含 selected/dropped evidence、ContextPack 与 trace；非空 ContextPack 只说明材料被选择，不证明 Goal 完成。

### Claim grounding

`verify_claims()` 把候选文本拆为 claim，并返回 `supported/partially_supported/unsupported/contradicted`、supporting evidence ids 与 spans。当前默认使用 [HeuristicEntailmentJudge](../../src/personal_agent/application/entailment.py)，依据词重叠、数字与极性信号判断；Research digest 创建默认 `EvidenceEngine()`，没有注入模型 Judge。该标签属于组件检查结果，不能作为开放语义已经满足的证明。

## 生产消费者

Research digest verification 把 `ResearchSource` 投影为 `EvidenceItem`，检查每个 digest claim 与 source binding。

Research digest 的实际调用位于 [application/research/service.py](../../src/personal_agent/application/research/service.py)。Conversation 的 claims 与 Final 核验由独立结构化模型调用承担，当前链路见[核验专题](../topics/verification-and-completion.md)；已撤回 Investigation 不再是消费者。

Personal Knowledge 的 Claim、Evidence、conflict 和 scope 仍由 `KnowledgeService` 拥有。模型选择只读 `search_personal_knowledge` 后，Conversation 才把选择结果物化为有界 `tool_result`，而不是先运行一个子 RAG answer service。

## 责任边界

具体 Application 决定任务、来源与结果契约，原业务服务保存 Artifact、Claim 或 ResearchEvent。Evidence Engine 消费调用方输入，返回可重建证据视图与检查结果；最终回答、语义验收及状态关闭由原消费者负责。

## 验证

检索、重排和证据选择使用有明确样本及前置条件的 Offline Eval；实际 Application 从正式入口验证最终用户结果，组件得分不代替 Product E2E。历史 Unit/Contract 证据只读保留，现行分工见 [QLT](../devSpec/quality-security.md#1-测试职责与覆盖)。
