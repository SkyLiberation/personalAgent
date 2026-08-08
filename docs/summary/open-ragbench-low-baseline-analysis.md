# Open RAGBench / Galileo RAGBench 检索优化现状

更新时间：2026-07-09

## 当前结论

当前评估不能再被解读为“lexical 比 embedding 更好”或“Open v2 是通用最优 RAG”。更准确的结论是：

1. `ask_retrieve_high_accuracy` v2 是 Open RAGBench 单榜最优，但主要依赖论文 / section / same-doc refinement 等 Open 结构先验，只能作为 Open profile feature。
2. `shared evidence selector` 是当前最稳的 sparse/support baseline，已在 Open、Galileo、多 seed 和 Galileo validation held-out 上稳定优于 keyword，但它不是最终 RAG 架构。
3. 目标架构应回到通用 hybrid RAG：dense semantic retrieval + sparse lexical retrieval + fusion + reranker + context packing + claim grounding。
4. 当前生产 Ask 默认 fast reranker 已从纯启发式切到 `support`，并在 context packing 中增加 parent companion 保护。Open 100q 与 Galileo covidqa 100q 都显示 `support` 相对 keyword/heuristic baseline 有明显收益；`llm_gated` 已能消费 support/grounding 信号，在 top evidence 缺少直接 support 且候选池内存在直接证据时触发 LLM rescue。

## 目标架构

新的默认方向不以 Open/Galileo 任一数据集为中心，而以可迁移 RAG 架构为中心：

```text
query
  -> query normalization / optional intent-aware rewrite
  -> dense semantic retrieval
  -> sparse lexical retrieval
  -> optional personal knowledge / graph / metadata candidates
  -> dedupe + chunk/parent grouping
  -> RRF or normalized score fusion
  -> reranker over fused candidates
  -> context packing with budget and source diversity
  -> answer generation
  -> claim-level grounding / citation verification
```

设计原则：

| 原则 | 含义 |
| --- | --- |
| dense 是必要召回通道 | embedding 负责语义相似、改写表达、同义概念召回 |
| sparse 是必要召回通道 | lexical/BM25 负责关键词、实体、数字、代码、标题等精确匹配 |
| fusion 只合并候选 | RRF/score fusion 不等于最终相关性判断 |
| reranker 是核心缺口 | 需要判断候选是否直接回答 query，而不是只看主题相似 |
| claim 用于 grounding gate | claim 机制不替代 retrieval，但用于回答后 citation 和事实支持检查 |
| 禁止数据集拟合式默认策略 | doc-first、same-doc slot refinement、yes/no expansion 只能作为 profile/消融项 |

推荐分层：

```text
Retrieval:
  dense / sparse-support / personal knowledge / graph / metadata

Fusion:
  RRF / normalized score fusion / source quotas / dedupe

Rerank:
  fast reranker first
  LLM gated semantic rescue second

Packing:
  budget / diversity / parent-child / citation readiness

Verification:
  answer claim grounding / citation support / insufficient evidence detection
```

## 优秀 RAG 对当前问题的处理方式

当前问题不应被简化为“embedding 是否有用”或“LLM 是否应该上链路”。更成熟的 RAG 系统通常把不同组件的职责拆开：召回阶段尽量不漏，融合阶段合并多路候选，reranker 判断候选是否直接回答问题，packing 保证证据可被模型利用，claim/grounding 负责回答后的事实校验。

| 当前问题 | 优秀 RAG 的处理方式 | 对当前系统的含义 |
| --- | --- | --- |
| embedding 单独使用不稳定 | dense retrieval 与 sparse/BM25 并行召回，再用 RRF 或归一化融合，避免直接比较不同分数尺度 | embedding 仍是必要召回通道，但不能单独决定最终排序 |
| lexical 当前表现很强 | 保留 lexical 作为实体、术语、数字、标题、代码等精确匹配通道 | `shared evidence selector` 应沉淀为 sparse/support branch，而不是最终架构 |
| doc-first / same-doc / yes-no expansion 泛化差 | 数据集结构先验只作为 profile feature 或消融项，不进入 universal default | Open profile 可以保留结构优化，但默认链路不能依赖 Open 论文/section 形态 |
| RRF 后仍有误排 | fusion 只合并候选，最终相关性由 cross-encoder、late-interaction reranker、轻量 reranker 或 gated LLM 判断 | 已新增 `support` reranker 作为默认 fast reranker；后续再评估更强 cross-encoder/late-interaction |
| LLM 全量重排慢且有 harmed 风险 | LLM 作为 gated semantic rescue，仅在低置信、检索分歧、证据缺直接 support、grounding 不足时触发 | `llm_gated` 已接入 weak-top-support、low-score、source disagreement、dense/sparse rank gap 等强触发；score-margin 仍只做负向对照 |
| claim 对 retrieval 提升有限 | claim 不替代召回和排序，主要用于 citation verification、unsupported claim 检测、补检索或拒答 | `support` reranker 会尊重已有 support/grounding 元数据，允许 verifier 结果非侵入式驱动 LLM rescue |
| top-k 证据堆叠仍回答不稳 | context packing 控制预算、来源多样性、parent-child chunk、证据位置和 citation readiness | packing 需要成为质量环节，不能只是把 fused top-k 原样塞进上下文 |
| child section 命中但 parent 背景被挤出 | 优秀 RAG 会使用 parent-child / small-to-big retrieval，并在 packing 阶段保护引用上下文 | 已新增 parent companion packing：选中 chunk 时，预算允许则紧跟选择父级证据 |

对应的通用链路应保持为：

```text
query
  -> intent/query normalization
  -> dense retrieval + sparse retrieval + personal knowledge/metadata candidates
  -> dedupe + parent/section grouping
  -> RRF or normalized fusion
  -> semantic reranker or gated LLM rescue
  -> context packing
  -> answer generation
  -> claim grounding / citation verification
  -> failed grounding triggers rescue retrieval or insufficient-evidence response
```

## 当前策略定位

| 策略 / 组件 | 当前定位 |
| --- | --- |
| `ask_retrieve_high_accuracy` v2 | Open profile feature，不能作为通用默认 |
| `shared evidence selector` | sparse/support baseline，可抽象为 sparse retriever 或 reranker feature |
| `shared embedding evidence selector` | dense 通道已跑通，但当前 fusion/reranker 不足，不能无条件抬升 top-k |
| `shared evidence policy selector` | 已支持 uuapi + 低思考强度 + concurrency=3；适合做 gated semantic rescue，不适合无条件默认重排 |
| `support` reranker | 生产 Ask 默认 fast reranker；消费 question/evidence 文本、fusion metadata、dense/sparse 共识和 support/grounding 元数据 |
| `llm_gated` reranker | 在 `support` 排序和诊断之后，只对弱 top support、低置信、来源分歧或 dense/sparse rank gap 触发 LLM |
| claim grounding | 适合做 answer/citation verification，不应直接当 retrieval 排序主逻辑 |

`shared evidence selector` 不应继续叠加 Open/Galileo 特异规则。它应该沉淀为：

1. 无 embedding / 无 Postgres / 无模型服务时的 fallback；
2. hybrid RAG 的 sparse/support retriever；
3. `support` reranker 的 lexical/support feature；
4. dense 低置信或候选分歧较大时的稳定补充。

## 补充评估结论

### Open Profile 对照

Open 100q，seed=13，limit=10：

| strategy | MRR | R@1 | R@3 | R@5 | R@10 | NDCG@5 | NDCG@10 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| pure external embedding baseline | 0.7191 | 0.3050 | 0.4850 | 0.6050 | 0.7800 | 0.5568 | 0.6246 |
| high-accuracy v2 | 0.8545 | 0.3750 | 0.7150 | 0.9300 | 0.9850 | 0.8033 | 0.8269 |

结论：Open v2 单榜最高，但依赖 Open 论文/section 结构先验；只能作为 Open profile feature，不能作为通用默认。

### Embedding/Profile 30q

Galileo covidqa test 30q，seed=13；LangSmith/tracing 已关闭：

| strategy | label | MRR | R@1 | R@5 | R@10 | NDCG@10 | elapsed |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| shared selector | relevant | 0.7789 | 0.2443 | 0.5682 | 0.8300 | 0.7008 | 0.030s |
| shared embedding selector | relevant | 0.8011 | 0.2554 | 0.5615 | 0.8286 | 0.7071 | 188.165s |
| shared selector | utilized | 0.7053 | 0.3287 | 0.6430 | 0.8802 | 0.6894 | 0.030s |
| shared embedding selector | utilized | 0.7108 | 0.3398 | 0.6252 | 0.8394 | 0.6771 | 188.165s |

结论：Postgres embedding 已跑通，但当前 dense 融合会提升部分 top-rank，同时损伤 utilized recall/NDCG。问题不是 embedding 不需要，而是缺少稳定的 fusion/reranker。

### LLM Policy 消融结论

LLM policy 在 Open / Galileo 30q 消融中出现过 semantic rescue 信号，但全量调用成本过高，并且在 Galileo utilized 上损伤 R@10/NDCG@10。该结果只保留为经验结论：LLM 可能 rescue，也可能 harm；不能作为当前默认链路收益依据。

### LLM Policy Endpoint / Concurrency

已完成的工程调整：

1. structured LLM endpoint 切到 uuapi，模型为 `gpt-5.4-mini`。
2. structured extra body 设置为 `{"reasoning":{"effort":"minimal"}}`，用于降低推理强度并提升响应速度。
3. shared LLM policy 在 Open / Galileo runner 中接入 bounded concurrency，默认 `shared_policy_concurrency=3`。
4. policy 调用失败时按 query 记录 `shared_policy_error`，并 fallback 到 policy 前 ranking，不中断整轮评估。
5. 修复配置优先级：`STRUCTURED_*` 现在优先于 `ROUTER_*`，避免 structured endpoint 被 router 配置覆盖。

结论：并发 3 能改善总 wall time，但 uuapi 单次响应仍有明显波动。当前不应把 LLM policy 作为所有 query 的默认重排层，仍应做低置信 / 高歧义触发。

### 多 Seed / Galileo Validation

shared selector 已在以下设置中相对 keyword 全指标上升：

| dataset | split | seed | 结论 |
| --- | --- | ---: | --- |
| Open | sampled 100q | 7 | shared selector 全指标优于 keyword |
| Open | sampled 100q | 42 | shared selector 全指标优于 keyword |
| Galileo covidqa | test 100q | 7 | relevant/utilized 全指标优于 keyword |
| Galileo covidqa | test 100q | 42 | relevant/utilized 全指标优于 keyword |
| Galileo covidqa | validation 100q | 13 | relevant/utilized 全指标优于 keyword |

结论：shared selector 是稳定 sparse/support baseline，不是 seed=13 偶然结果；但这仍不等于真实业务 held-out 已覆盖。

## 已落地

1. 数据与评估：Postgres vector 维度已与 1024 维 embedding 对齐；Open / Galileo runner、metrics、diagnostics、多 seed 和 Galileo validation 验证已跑通。
2. 通用链路边界：生产 Ask 已落地统一 `Candidate` schema；`RetrievalCoordinator` 作为 `HybridRetriever` 边界统一接入 local/personal knowledge/graph/web 等候选源。
3. Fusion 与归因：local 检索会投影 `sparse_rank` / `dense_rank`；`CandidateFusion(rrf)` 统一执行 dedupe + RRF，并写回 `fusion_rank`、`fusion_score`、`fusion_components`、`consensus_count`。
4. LLM 与可靠性：结构化模型客户端已有 retry wrapper；shared LLM policy 已接入 uuapi `gpt-5.4-mini`、低思考强度、concurrency=3 和 per-query fallback。
5. Gate 与默认策略：retrieval default gate 已支持 Open/Galileo profile、baseline alias、latency/cost/grounding/harmed 预算；Open/Galileo 100q full gate 已通过。
6. `support` reranker：生产 Ask 默认 fast reranker 已从纯 `heuristic` 切到 `support`，基于 query/evidence coverage、直接 support、dense/sparse 共识、RRF consensus 和低信息惩罚进行排序。
7. Parent companion packing：`select_ranked_evidence` 选中 child chunk 后，会在预算允许时紧跟选择同 parent 证据，避免 section 正确但父级上下文被 packing 挤出。
8. `llm_gated`：生产 Ask reranker 已接入 gated LLM rescue、telemetry 和 fallback；默认关闭 score-margin 弱触发，新增 weak-top-support grounding trigger，并修正了 Open eval 中召回深度/planner 差异造成的收益污染。

## 最新完整评估

### Shared Sparse/Support 100q Gate

Open RAGBench 100q，seed=13：

| strategy | MRR | R@1 | R@3 | R@5 | R@10 | NDCG@5 | NDCG@10 | elapsed |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| keyword | 0.5632 | 0.1900 | 0.5250 | 0.5550 | 0.6250 | 0.5334 | 0.5688 | 3.873s |
| shared sparse/support | 0.7994 | 0.3300 | 0.8400 | 0.8900 | 0.9350 | 0.8144 | 0.8316 | 23.807s |

Galileo covidqa test 100q，seed=13：

| strategy | label | MRR | R@1 | R@3 | R@5 | R@10 | NDCG@5 | NDCG@10 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| keyword | relevant | 0.7092 | 0.2111 | 0.3962 | 0.4869 | 0.6127 | 0.5226 | 0.5565 |
| shared sparse/support | relevant | 0.7652 | 0.2239 | 0.4467 | 0.5740 | 0.8164 | 0.6190 | 0.7063 |
| keyword | utilized | 0.5925 | 0.2791 | 0.4637 | 0.5522 | 0.6776 | 0.4795 | 0.5285 |
| shared sparse/support | utilized | 0.6461 | 0.2992 | 0.5238 | 0.6436 | 0.8445 | 0.5569 | 0.6441 |

Gate 结果：open + galileo quality gate passed。

### Production `support` / Parent Packing

Open RAGBench 100q，seed=13，retrieval-stage only：

| strategy | MRR | R@1 | R@3 | R@5 | R@10 | NDCG@5 | NDCG@10 | elapsed |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| heuristic + parent packing | 0.5561 | 0.1750 | 0.5550 | 0.6200 | 0.7000 | 0.5333 | 0.5654 | 288.35s |
| `support` + parent packing | 0.6080 | 0.2100 | 0.5750 | 0.6550 | 0.7350 | 0.5744 | 0.6059 | 297.49s |

对比结果：`support` 相对 heuristic 全指标上升；100q 中 rescued 18 个 query、harmed 1 个 query，且 recall harmed 为 0。说明当前默认 fast reranker 的收益主要来自更好 top-rank 排序和 parent-child packing，而不是牺牲 recall 换 MRR。

Galileo covidqa test 100q，seed=13，LangSmith/tracing 关闭，sentence-level retrieval：

| strategy | label | MRR | R@1 | R@3 | R@5 | R@10 | NDCG@5 | NDCG@10 | elapsed |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| keyword | relevant | 0.7092 | 0.2111 | 0.3962 | 0.4869 | 0.6127 | 0.5226 | 0.5565 | 0.012s |
| production `support` | relevant | 0.7729 | 0.2335 | 0.4048 | 0.5270 | 0.7678 | 0.5741 | 0.6615 | 0.688s |
| shared sparse/support | relevant | 0.7652 | 0.2239 | 0.4467 | 0.5740 | 0.8164 | 0.6190 | 0.7063 | 0.150s |
| keyword | utilized | 0.5925 | 0.2791 | 0.4637 | 0.5522 | 0.6776 | 0.4795 | 0.5285 | 0.012s |
| production `support` | utilized | 0.6623 | 0.3143 | 0.4901 | 0.5893 | 0.8229 | 0.5227 | 0.6203 | 0.688s |
| shared sparse/support | utilized | 0.6461 | 0.2992 | 0.5238 | 0.6436 | 0.8445 | 0.5569 | 0.6441 | 0.150s |

结论：`support` 不只在 Open 上有效，在 Galileo sentence-level 上也相对 keyword 全指标上升，尤其 R@10/NDCG@10 提升明显。shared sparse/support 仍在 R@3/R@5/R@10/NDCG 上更强，说明生产 `support` 已验证方向正确，但 eval-only shared selector 的部分候选覆盖/排序能力还没有完全沉淀进生产链路。

### Production `llm_gated`

新增 weak-top-support trigger 后，Open RAGBench 30q，seed=13，retrieval-stage only：

| strategy | MRR | R@1 | R@3 | R@5 | R@10 | NDCG@5 | NDCG@10 | elapsed | LLM calls |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `support` | 0.6139 | 0.2333 | 0.5833 | 0.6500 | 0.7000 | 0.5868 | 0.6078 | 99.47s | 0 |
| `llm_gated` | 0.6389 | 0.2500 | 0.6167 | 0.6667 | 0.7000 | 0.6113 | 0.6259 | 113.60s | 4 |

结论：

1. `llm_gated` 在 30q 上只调用 4 次，触发原因均为 `weak_top_support`。
2. 相对 `support`，`llm_gated` 继续提升 MRR、R@1、R@3、R@5、NDCG@5、NDCG@10，R@10 持平。
3. 30q 中 LLM rescued 2 个 query、harmed 1 个 query；`preserve_top_k=1` 消融没有更好，因此暂不作为默认。

## 当前缺口

1. 还缺真实业务 held-out，包括个人知识库、技术文档、跨文档问答；没有该集就不能判断泛化默认链路。
2. default gate 已能消费 eval 产物，但还没有进入 CI / release gate；business held-out 缺失时不能声明默认链路可准入。
3. `support` reranker 已在 Open 100q 和 Galileo covidqa 100q 验证提升，但还没有业务 held-out 和 CI gate，不能声明默认链路已全量准入。
4. 当前 `support` reranker 是轻量 lexical/support semantic layer，还不是 cross-encoder 或 late-interaction reranker；后续可评估更强 reranker，但不应继续增加数据集规则。
5. `shared evidence selector` 已定位为 sparse/support baseline；其可迁移思想已进入 `support` reranker，但 eval-only selector 在 Galileo 上仍强于 production `support` 的部分指标，需继续沉淀其通用候选覆盖能力，而不是直接把 benchmark selector 作为生产实现。

主要风险：

1. 过度神化 `shared evidence selector`，把 sparse/support baseline 误当最终架构。
2. 误把 `CandidateFusion` 当最终相关性判断；fusion 只负责候选合并和多路共识，最终仍需要 reranker 判断是否直接回答 query。
3. LLM policy 虽已并发化，但全量默认开启仍有延迟、成本和 recall 风险。
4. profile 和 universal default 混淆，导致 Open/Galileo/个人知识库规则泄漏进默认链路。

## 下一步

优先级从高到低：

1. 补业务 held-out，并把 `evals/retrieval_gate.py` 接入 CI / release gate，形成默认链路准入记录。
2. 将 shared sparse/support 的通用候选覆盖能力继续沉淀进 production `support` / hybrid retriever，重点缩小 Galileo 上 production `support` 与 eval-only shared selector 的 R@3/R@5/NDCG 差距。
3. 对 `llm_gated` 继续做 100q 和 harmed bucket 消融：weak-top-support、dense/sparse conflict、top_n，并仅把 score-margin / preserve_top_k 作为负向对照。
4. 对 harmed query bucket 做归因：区分 dense 误召回、sparse 主题相似、fusion 过度奖励、support reranker 误判、LLM rescue 误排和 packing 预算截断。

默认链路准入条件：

```text
A strategy can become default only if:
  1. Open RAGBench 不回退；
  2. Galileo relevant/utilized 不出现系统性 recall 或 NDCG 回退；
  3. business held-out 不回退；
  4. latency 在预算内；
  5. cost 在预算内；
  6. harmed query bucket 可解释；
  7. citation grounding 不下降。
```

## 参考依据

1. Azure AI Search hybrid search：full-text 与 vector 并行检索，并用 RRF 合并结果；semantic ranker 位于 RRF 之后。
   <https://learn.microsoft.com/en-us/azure/search/hybrid-search-overview>
   <https://learn.microsoft.com/en-us/azure/search/hybrid-search-ranking>
2. Weaviate hybrid search：并行执行 vector search 与 BM25，并通过 fusion method / alpha 调整两路权重。
   <https://docs.weaviate.io/weaviate/concepts/search/hybrid-search>
3. Qdrant hybrid / multi-stage queries：强调 dense 与 sparse 分数尺度不同，建议使用 RRF 或归一化融合，并支持后续 reranking。
   <https://qdrant.tech/documentation/search/hybrid-queries/>
   <https://qdrant.tech/documentation/tutorials-search-engineering/reranking-hybrid-search/>
4. Cohere Rerank：reranker 用于对已有 retrieval 结果按 query relevance 重新排序，适合作为二阶段排序组件。
   <https://docs.cohere.com/v2/docs/rerank-overview>
5. RAG 2020：retrieval-augmented generation 的基本范式是先检索外部知识，再以证据增强生成。
   <https://arxiv.org/abs/2005.11401>
6. RRF：按 rank 融合多路检索结果，适合处理 dense/sparse 分数尺度不可直接比较的问题。
   <https://dl.acm.org/doi/10.1145/1571941.1572114>
7. ColBERT：late interaction 用于更细粒度地判断 query-token 与 passage-token 的相关性，是 dense retrieval 与精排之间的重要路线。
   <https://arxiv.org/abs/2004.12832>
8. RankGPT：LLM 可以作为 reranking agent，但工程上需要控制候选规模、延迟和 harmed query 风险。
   <https://arxiv.org/abs/2304.09542>
9. Self-RAG：将 retrieve / generate / critique 拆开，强调证据是否需要、是否相关、回答是否被支持。
   <https://arxiv.org/abs/2310.11511>
10. Lost in the Middle：长上下文不保证证据被稳定利用，context packing 和证据位置仍会影响回答质量。
   <https://arxiv.org/abs/2307.03172>
11. Evidence-grounded RAG 近期论文：hybrid retrieval 先取候选 evidence chunks，再用 reranking 选择高相关 passage 后生成答案。
   <https://arxiv.org/abs/2605.01664>

## 一句话总结

Open v2 是 Open profile 最优，不是通用默认；shared selector 是稳定 sparse/support baseline，不是最终 RAG。当前已把通用 hybrid RAG 的 Candidate、HybridRetriever、CandidateFusion、context packing 与 claim grounding 边界接入生产 Ask 链路；下一步应围绕跨数据集、真实业务 held-out、latency/cost/grounding gate 验证默认链路，而不是继续堆数据集拟合规则。
