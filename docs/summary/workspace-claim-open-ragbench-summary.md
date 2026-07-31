# Workspace Claim / WorkspaceRetriever 机制与 Open RAGBench 验证总结

> 状态：历史实验记录。下文使用的 disabled `ms_graphrag` 仅用于当时关闭 graph；当前 runner
> 已改为显式关闭 Graphiti，Microsoft GraphRAG 生产 Adapter 和配置已删除。

## 结论

当前 Claim / Workspace 机制不是纯解释性增强。它会把 Workspace 中的 `EvidenceSpan` / `Claim` / conflict diagnostics 转成 Ask 统一证据池里的 `EvidenceItem`、`Citation` 和 `KnowledgeNote`，因此会实际影响 Ask 的候选证据、引用和最终回答上下文。

但在本次关闭 web、graph、langextract 后，用 Open RAGBench 验证 `WorkspaceRetriever` 时，没有观察到稳定的 RAG quality 提升。10-query 样本里 MRR 小幅上升，但 Recall@5、Recall@10、NDCG@5、NDCG@10 均下降；3-query 和 5-query 样本下降更明显。当前更合理的判断是：WorkspaceRetriever 已经能参与 Ask 检索，但对 Open RAGBench 这种学术段落检索任务，现有 workspace overlap 检索和统一 rerank 融合方式还不足以稳定提升检索质量。

## 当前 Claim 机制如何生效

Workspace 的知识链路是 evidence-first，然后可选进入 Claim 生命周期：

```text
raw input
  -> Artifact
  -> EvidenceBlock
  -> EvidenceSpan
  -> optional Claim
  -> GroundingRun
  -> ClaimAdmissionDecision
  -> KnowledgeRelation / Conflict
  -> KnowledgeStateEvent
  -> ProjectionJob
```

在 e2e 用例中，这套机制主要通过以下质量边界生效：

- `EvidenceBlock` / `EvidenceSpan` 必须生成，保证回答引用能回溯到原始证据。
- `Claim` 进入 active 之前必须经过 grounding / admission，不是抽出来就直接变长期记忆。
- 高风险、助手推断、冲突 claim 会被降级为 candidate、pending decision 或 conflict，而不是静默保存。
- `answer_with_evidence()` 返回独立 `verification` assessment，由 Workspace Answer Verifier
  判断整体支持、冲突、coverage 和 unsupported claim；回答组装器不再写验证结论。
- 回答阶段不会把答案里的新 claim 自动写回 active claim，避免 Ask 越答越污染长期记忆。

所以 Claim 的价值不只是“解释为什么这么答”，它承担了长期知识准入、证据绑定、冲突诊断和状态审计。

## 对 Ask 的帮助边界

Ask 接入 Workspace 有两层：

1. `WorkspaceService.select_evidence()`：只读选择 EvidenceSpan、citation、Claim 支持状态和冲突事实，不生成或验证答案。
2. `WorkspaceRetriever`：把 selection 投影到 Ask 的统一 evidence pool，和 local / graph / web / episodic 等来源一起进入 `EvidenceEngine` 去重、融合、压缩和 rerank。

独立产品入口 `WorkspaceService.answer_with_evidence()` 复用同一 selection，随后组装并验证正式
Workspace Answer。Ask 不调用该回答入口，避免在最终 Ask compose/verify 之前嵌套一套被丢弃的
answer/verify。

因此它对 Ask 的帮助不是只增强可解释性。只要 Workspace 证据进入 pool，它就会改变：

- 召回候选数量和来源；
- `ContextPack` 的 selected evidence；
- citations 和 match_refs；
- verifier / repair 后续看到的证据；
- 最终回答可引用的事实边界。

但它能否提升回答准确率，取决于 Workspace 检索出的证据是否比 local retriever 更准，以及 EvidenceEngine 是否能正确融合它们。当前机制提供了“提升准确率的路径”，但不保证对所有数据集天然提升。

## 采纳的架构判断

这次评估最值得沉淀的结论是：不要把 Claim / Workspace 默认定义成“RAG 检索增强器”。它更准确的定位是：

```text
Claim / Workspace
  = 知识生命周期治理层
  + 语义状态约束层
  + 证据审计与冲突诊断层
```

Ask 的默认路径应该保持 Evidence-first：

```text
QueryUnderstanding
  -> local / evidence_span / artifact retrieval
  -> source-aware rerank
  -> ContextPack
  -> answer / verify / repair
```

Claim 不应默认和 local chunk、EvidenceSpan、artifact section 竞争 top-k 预算。它更适合在以下场景中条件触发：

- 用户问“之前我说过什么 / 我的偏好是什么 / 我的计划是什么”。
- 用户问“这两条说法是否冲突”。
- 问题需要 scope / time / condition disambiguation。
- Research event 可能替代、补充或冲突已有知识。
- verifier / repair 需要检查答案是否违反长期知识状态。
- 回答需要展示 stale / superseded / conflicted / uncertain 等状态。

换句话说：

```text
普通事实问答: Evidence-only 或 Evidence-dominant
状态 / 冲突 / 长期记忆问答: Claim-aware
```

## Open RAGBench 验证设置

本次新增了两个 Open RAGBench 策略：

- `ask_retrieve_no_workspace`
- `ask_retrieve_workspace`

两者都走真实 `AskService.run_retrieval_stage()`，但跳过生成、verifier 和 repair，用 retrieval-stage 指标隔离 `WorkspaceRetriever` 对证据排序的影响。

关闭项：

- web：`web_search.api_key = None`
- graph：`ask.graph_provider = "ms_graphrag"` 且 `ms_graphrag.enabled = False`
- structured / langextract：`structured.api_key = None`、`langextract.api_key = None`
- reranker：使用 `heuristic`

为了避免 full `WorkspaceService.ingest_text()` 的 Claim 生命周期成本淹没检索实验，workspace 变体使用 fixture seeding：把每个 Open RAGBench note 写成 `Artifact + EvidenceBlock + EvidenceSpan`，`artifact_id/source_ref = open_ragbench://{note.id}`，再由真实 `WorkspaceRetriever -> select_evidence()` 路径召回并映射回 note id。

## 实验结果

结果文件：

- `evals/open_ragbench/results/workspace_retriever_ablation_smoke.json`
- `evals/open_ragbench/results/workspace_retriever_ablation_5q.json`
- `evals/open_ragbench/results/workspace_retriever_ablation_10q.json`

3-query smoke：

| strategy | MRR | R@1 | R@3 | R@5 | R@10 | NDCG@5 | NDCG@10 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| no workspace | 0.3810 | 0.1667 | 0.3333 | 0.3333 | 0.5000 | 0.3333 | 0.4015 |
| workspace | 0.0556 | 0.0000 | 0.0000 | 0.0000 | 0.3333 | 0.0000 | 0.1409 |

5-query：

| strategy | MRR | R@1 | R@3 | R@5 | R@10 | NDCG@5 | NDCG@10 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| no workspace | 0.5008 | 0.2000 | 0.3000 | 0.4000 | 0.7000 | 0.3594 | 0.4726 |
| workspace | 0.2667 | 0.1000 | 0.1000 | 0.1000 | 0.4000 | 0.1226 | 0.2487 |

10-query：

| strategy | MRR | R@1 | R@3 | R@5 | R@10 | NDCG@5 | NDCG@10 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| no workspace | 0.4743 | 0.2000 | 0.2500 | 0.4500 | 0.6500 | 0.3789 | 0.4566 |
| workspace | 0.5042 | 0.2000 | 0.2500 | 0.3500 | 0.6000 | 0.3260 | 0.4278 |

10-query 下 delta：

| metric | delta |
| --- | ---: |
| MRR | +0.0299 |
| Recall@1 | 0.0000 |
| Recall@3 | 0.0000 |
| Recall@5 | -0.1000 |
| Recall@10 | -0.0500 |
| NDCG@5 | -0.0528 |
| NDCG@10 | -0.0288 |

## Trace 观察

诊断里确认关闭项生效：

```text
web_enabled=false
structured_enabled=false
langextract_enabled=false
graph_provider=ms_graphrag
graph_selected=0
```

workspace 变体每条 query 都能看到：

```text
Workspace 候选已进入统一证据池 citations=5 evidence=5
本地候选已进入统一证据池 matches=8 citations=8
ContextPack(heuristic): selected=... dropped=...
```

这说明 WorkspaceRetriever 并不是空跑。它确实召回了 workspace evidence，并参与了最终 context pack 选择。指标下降的直接原因是：workspace evidence 在 heuristic rerank 中挤占或压低了原本 local retriever 排到前面的 relevant section / parent note。

## 为什么会下降

这次结果不是 Claim 机制失败，而是暴露出“把 Claim / Workspace 当作并列 retriever”时的天然风险。

第一，Workspace evidence 增加了候选源，但当前候选排序质量没有稳定超过 local retriever。它进入统一 evidence pool 后，如果 reranker 没有足够强的 source calibration，就会挤占更接近 gold section 的 local evidence。

第二，Claim statement 不等于 Evidence。Claim 是主张、状态、scope、valid_time、support_status 等语义状态对象；Evidence 是可引用、可回溯、可进入 verifier 的原文依据。Claim 可以作为高密度索引入口，但最终回答应优先回到 `claim.evidence_refs -> EvidenceSpan / EvidenceBlock`。

第三，Open RAGBench 评估的是 section / parent note 的 top-k 命中。Workspace 中更精炼的 span 或 claim-like 文本即使对真实问答有价值，也可能不命中 benchmark 期望的原始段落边界。

第四，当前 WorkspaceRetriever 的 score / rerank 没有校准。Workspace 候选如果固定较高 score 或和 local 候选裸融合，会造成低增益候选进入 top-k。

## 对 RAG Quality 的判断

当前 Claim / Workspace 机制能提升“可审计性”和“知识生命周期质量”：

- 引用可追踪；
- 无证据时保守；
- 部分覆盖可诊断；
- 冲突 claim 不静默合并；
- 长期 claim 不随意保存。

它也具备提升回答准确率的结构条件，因为它能把经过证据绑定和准入的 Workspace 知识加入 Ask evidence pool。

但本次 Open RAGBench 结果不支持“当前 WorkspaceRetriever 已提升 RAG_quality”。更准确的结论是：

- 对个人知识库、长期偏好、冲突记忆、证据审计场景，Claim/Workspace 对 Ask 有实质帮助。
- 对 Open RAGBench 的学术段落 top-k 检索，当前 WorkspaceRetriever 的 lexical overlap 选择和融合策略没有稳定提升，甚至带来 recall / NDCG 下降。
- 若要让它提升 RAGBench 类指标，需要继续优化 workspace evidence 粒度、召回打分、source-aware rerank 权重，或只在 workspace 置信度明显高于 local 时注入。

## 后续建议

优先改三点：

1. WorkspaceRetriever 输出 source-aware score，不要所有 citation 固定 `0.9`。
2. EvidenceEngine rerank 对 workspace/local 做融合校准，避免 workspace 证据无条件挤占 local top-k。
3. Workspace evidence span 粒度从整段/整节变成更细的句级或段内 span，减少长文本 overlap 噪声。

然后再跑同一组 ablation，至少观察 10-query 和 20-query 的 Recall@5/10、NDCG@5/10 是否同时改善。

## 建议的实现调整

WorkspaceRetriever 应从“并列召回源”改成“受控增强源”。

### EvidenceRef expansion

不要把 Claim statement 直接当作最终 evidence 注入 ContextPack。更合理的路径是：

```text
retrieve Claim
  -> check ClaimQualityGate / state / support_status
  -> read claim.evidence_refs
  -> fetch EvidenceSpan / EvidenceBlock
  -> inject original evidence into ContextPack
```

这样 Claim 只作为高密度索引入口，最终回答仍基于可回溯原文证据。

### Source quota / cap

Workspace 候选不能无限挤占 local 候选。建议按 query type 设置 quota：

```text
普通事实问答:
  workspace quota = 0 或 1

claim_sensitive 问题:
  workspace quota = 2~3

冲突 / 过期 / 个人记忆问题:
  workspace quota 可提高
```

### Source-aware rerank

Workspace 和 local 的分数不应直接裸比较。建议引入 query-dependent source weighting：

```text
final_score =
  semantic_relevance
  + source_weight(query_type)
  + evidence_ref_quality
  + coverage_score
  + claim_quality_bonus
  - conflict_or_uncertainty_penalty
```

这能避免 workspace 候选仅因来源或固定 score 偏置进入 top-k。

### QueryUnderstanding 扩展

建议给 QueryUnderstanding 增加显式字段：

```text
claim_sensitive: true | false
retrieval_mode:
  evidence_only
  evidence_dominant
  claim_expand_to_evidence
  claim_state_diagnostic
```

建议路由规则：

| query 类型 | retrieval_mode |
| --- | --- |
| 普通事实问答 | `evidence_only` / `evidence_dominant` |
| “这篇资料讲了什么” | `evidence_only` |
| “之前我说过什么 / 我的偏好是什么” | `claim_state_diagnostic + evidence refs` |
| “这两条是否冲突” | `claim_expand_to_evidence + relation judge` |
| “最新说法是否替代旧说法” | `claim_state_diagnostic + research evidence` |
| answer verification / repair | `claim_state_diagnostic` 作为约束信号 |

### No-regression guard

`claim_sensitive` 只是启用 Claim-aware 的第一道门，不应该成为“误判后强行注入”的开关。Claim-aware 需要降级保护：

```text
if claim_sensitive=false:
  不注入 Workspace / Claim，保持 evidence_only 或 evidence_dominant

if claim_sensitive=true:
  只有 ClaimQualityGate、EvidenceRef、source-aware score 达标时才注入
  否则自动退回 evidence_only
```

具体保护规则：

- Claim 不确定时，不用它挤占 evidence slot。
- Workspace 分数不明显优于 local 时，不挤占 local top-k。
- Claim 没有有效 EvidenceRef 时，不进入 ContextPack。
- Claim 可以提供状态诊断，但不一定获得 evidence slot。
- Source quota 默认保守，只有在 Claim-sensitive 场景证明增益后再提高。

这个 guard 的目标是让 Claim-aware 成为“有把握时增强”，而不是普通 RAG 的回归风险。

## 建议的评估拆分

后续不应只用 Open RAGBench 判断 Claim 机制价值。Open RAGBench 适合检查它是否伤害普通段落检索，但 Claim 的主价值需要单独指标。

### RAG 检索指标

```text
Recall@5 / Recall@10
NDCG@5 / NDCG@10
MRR
selected evidence gold hit rate
```

这组指标如果下降，Claim / Workspace 就不应默认参与普通 top-k 竞争。

### Claim 增量指标

```text
claim_sensitive_precision
claim_sensitive_recall
retrieval_mode_accuracy
false_claim_injection_rate
ordinary_rag_regression_rate
scope disambiguation accuracy
superseded claim filtering success
conflict warning precision
stale claim avoidance
assistant_inference_active_rate = 0
answer_claim_auto_persisted = 0
```

这是 Claim 机制的主战场。其中 `claim_sensitive_precision` 尤其重要：宁可少启用 Claim，也不要把普通事实问答误判成 claim-sensitive，导致 Workspace / Claim 候选误注入。

### 端到端回答质量指标

```text
grounded answer accuracy
unsupported answer rate
citation correctness
coverage gap recall
correction success rate
```

Claim 可以不提升 top-k recall，但应该降低无证据乱答、提升冲突提示、纠错能力和长期知识安全。

## 下一轮 Ablation

下一轮不要只比较 workspace on/off，应拆成更细的策略：

| 策略 | 目的 |
| --- | --- |
| `local_only` | 普通 RAG baseline |
| `workspace_evidence_only` | 看 EvidenceSpan 自身检索能力 |
| `workspace_claim_only` | 验证 Claim statement 直接注入是否有害 |
| `workspace_claim_expand_to_evidence` | 验证 Claim 作为 EvidenceRef 入口是否有效 |
| `hybrid_no_cap` | 当前类似方案 |
| `hybrid_with_source_cap` | 验证 source quota 是否减少挤占 |
| `hybrid_source_aware_score` | 验证 score calibration |
| `claim_sensitive_only` | 只在需要 Claim 的问题启用 |
| `claim_sensitive_with_no_regression_guard` | 验证误判或低置信时是否能自动退回 evidence-only |
| `rerank_local_first_then_claim_expand` | 先 local 命中，再用 Claim 扩展相关证据 |

优先级最高的是：

```text
workspace_claim_expand_to_evidence
hybrid_with_source_cap
claim_sensitive_only
claim_sensitive_with_no_regression_guard
```

需要避免的过度推论是“Claim 机制没价值”或“Workspace 不应进入 Ask”。更准确的边界是：Claim 不应默认作为普通 RAG retriever，也不应直接和 chunk/evidence 竞争 top-k；它应作为条件触发的语义治理层，通过 EvidenceRef expansion、状态诊断、冲突/过期过滤和 verifier 约束参与 Ask。

## 工程落地门槛

在真正默认开启 Claim-aware Ask 前，至少需要满足这些门槛：

1. `claim_sensitive` router 有独立 precision / recall 评估，且 precision 优先。
2. 普通 RAG 有 no-regression gate，Claim-aware 不得显著降低 Recall@5/10 与 NDCG@5/10。
3. Claim 注入必须强制经过 `ClaimQualityGate + EvidenceRef expansion`。
4. Source quota 默认保守，workspace 只有在 query 类型和 score 都达标时才占用 top-k。
5. `claim_ask_incremental_gain` 达标的 query 类型才允许提高 Claim-aware 权重。

最终目标不是证明 Claim 能普遍提升 Open RAGBench，而是证明两件事：它不伤害普通 RAG；它在 scope/time/conflict/supersede/长期记忆等 Claim-sensitive 场景有可测增量。

## 当前落地状态

已按新设计完成第一阶段落地：

- `QueryUnderstanding` / `RetrievalPlan` 增加 `claim_sensitive` 与 `retrieval_mode`。
- query planner prompt 与 fallback heuristic 已支持 claim-sensitive 判断。
- `WorkspaceRetriever` 默认保持 evidence-first：普通问题下 `workspace_default_quota = 0`，不会注入 Workspace 候选。
- claim-sensitive 问题下按 `workspace_claim_sensitive_quota` 受控注入，默认上限为 3。
- Workspace evidence 不再以 Claim id / `workspace_claim` 作为主要证据形态进入 Ask，而是对齐 `EvidenceSpan` id，并以 `workspace_evidence` 表达原文证据；Claim id 只保留在 metadata / element_ids 中。
- Workspace 注入顺序调整为 local/graph 主召回之后，再作为受控增强进入 evidence pool。
- Workspace evidence score 不再固定为 `0.9`，改为保守的 source-aware 初始分。
- Ask trace 会记录普通问题跳过 Workspace 的原因。
- Open RAGBench 新增 `ask_retrieve_workspace_forced_claim_sensitive` 和 `ask_retrieve_workspace_evidence_only`，用于验证强制注入和 workspace-only 的边界。
- Open RAGBench eval store 在每次策略运行前清理当前 eval user，避免 Postgres 中同 user 的历史 RAGBench notes 污染指标。
- Postgres local retrieval 增加稳定 tie-break，避免没有 Workspace 注入时也出现非确定性排序抖动。

测试命令：

```text
uv run pytest tests/test_query_planner.py \
  tests/test_agent_flows.py::TestAskFlow::test_workspace_miss_does_not_short_circuit_existing_ask_pipeline \
  tests/test_agent_flows.py::TestAskFlow::test_workspace_skipped_for_non_claim_sensitive_question \
  tests/test_agent_flows.py::TestAskFlow::test_workspace_used_for_claim_sensitive_question \
  tests/test_prompt_registry.py \
  tests/test_open_ragbench_structural.py::test_ask_pipeline_eval_variants_are_registered \
  -q
```

结果：

```text
23 passed
```

20-query no-regression：

```text
uv run python -m evals.open_ragbench.runner \
  --num-queries 20 \
  --corpus-mode relevant \
  --strategies ask_retrieve_no_workspace,ask_retrieve_workspace \
  --graphiti-user-id ragbench_workspace_guard_20q_stable_20260705 \
  --output evals/open_ragbench/results/workspace_retriever_guard_20q_stable.json
```

结果：`ask_retrieve_no_workspace` 与 `ask_retrieve_workspace` 指标完全一致。

| strategy | MRR | R@1 | R@3 | R@5 | R@10 | NDCG@5 | NDCG@10 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| no workspace | 0.3346 | 0.1250 | 0.1750 | 0.3000 | 0.4750 | 0.2513 | 0.3212 |
| workspace | 0.3346 | 0.1250 | 0.1750 | 0.3000 | 0.4750 | 0.2513 | 0.3212 |

Workspace trace 显示：

```text
Workspace 检索已跳过：当前问题未判定为 claim-sensitive，保持 evidence-first
```

这说明普通 Open RAGBench 学术问答已触发 no-regression guard，不再因为 Workspace 候选误注入而挤占 local evidence。

forced 5-query：

```text
uv run python -m evals.open_ragbench.runner \
  --num-queries 5 \
  --corpus-mode relevant \
  --strategies ask_retrieve_workspace_forced_claim_sensitive,ask_retrieve_workspace_evidence_only \
  --graphiti-user-id ragbench_workspace_forced_5q_20260705 \
  --output evals/open_ragbench/results/workspace_retriever_forced_5q.json
```

| strategy | MRR | R@1 | R@3 | R@5 | R@10 | NDCG@5 | NDCG@10 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| forced claim-sensitive hybrid | 0.3250 | 0.1000 | 0.1000 | 0.3000 | 0.6000 | 0.2283 | 0.3461 |
| workspace evidence only | 0.2000 | 0.1000 | 0.1000 | 0.1000 | 0.1000 | 0.1226 | 0.1226 |

观察：

- `ask_retrieve_workspace_forced_claim_sensitive` 会在 local evidence 后注入 3 条 workspace evidence，trace 显示 `quota=3`。
- `ask_retrieve_workspace_evidence_only` 能单独跑通，但在普通学术问题上显著弱于 local/hybrid，继续支持“Workspace 不应默认作为普通 top-k retriever”的结论。
- forced 诊断中 workspace match id 为 `espn_...`，source_ref 为 `open_ragbench://...`，说明当前注入已经从 Claim statement 形态转为 EvidenceSpan / EvidenceRef 形态。
