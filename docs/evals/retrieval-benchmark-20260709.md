# Open / Galileo 历史检索评测

本报告收敛原更新于 2026-07-09 的检索盘点，保留当轮指标、配置与比较限制。它对应旧 Ask 及离线策略，不定义当前 Conversation 架构或活动候选。当前读取链见[检索专题](../topics/retrieval-reasoning.md)，未解决问题只由 [Future 队列](../future/design-optimization-backlog.md)登记。

## 历史结论与复用边界

当轮 Open 结构先验策略在已报告样本上领先，shared sparse/support 在 Open、Galileo 和多个 seed 上相对 keyword 有局部收益。Embedding 融合与 LLM 重排同时观察到改善和损伤，指标只支持对应检索分布，不能外推为真实用户回答质量。

旧报告没有逐表绑定完整代码身份、运行 manifest 和 checksum；以下数据按原值保留，复用前须补查对应原始归档。原 `production` 标签仅指当时 Ask 实现，不能表示这些组件仍由当前回答链消费。

相关离线入口为 [Open runner](../../evals/open_ragbench/runner.py)、[Galileo runner](../../evals/galileo_ragbench/runner.py)与[检索指标 gate](../../evals/retrieval_gate.py)。本次未运行这些入口，未重新验证历史指标。


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

当轮结论：embedding 路径已跑通；该融合策略提升部分前排指标，同时损伤 utilized recall/NDCG。该表不能单独判断 embedding 通道的必要性或定位唯一失败机制。

### LLM Policy 消融结论

LLM policy 在 Open / Galileo 30q 消融中出现过 semantic rescue 信号，但全量调用成本过高，并且在 Galileo utilized 上损伤 R@10/NDCG@10。该结果只保留为经验结论：LLM 可能 rescue，也可能 harm；不能作为当前默认链路收益依据。

### 当轮 LLM 配置与失败处理

当轮 runner 采用以下配置：

1. structured LLM endpoint 切到 uuapi，模型为 `gpt-5.4-mini`。
2. structured extra body 设置为 `{"reasoning":{"effort":"minimal"}}`，用于降低推理强度并提升响应速度。
3. shared LLM policy 在 Open / Galileo runner 中接入 bounded concurrency，默认 `shared_policy_concurrency=3`。
4. policy 调用失败时按 query 记录 `shared_policy_error`，并 fallback 到 policy 前 ranking，不中断整轮评估。
5. 修复配置优先级：当时 `STRUCTURED_*` 优先于 `ROUTER_*`，避免 structured endpoint 被 router 配置覆盖。

当轮记录报告并发 3 改善总耗时，同时存在单次响应波动；本页没有独立并发对照表，不能据此声明当前成本或延迟收益。

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

## 当轮完整评估

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

### 当时 Ask 实现的 `support` / Parent Packing

Open RAGBench 100q，seed=13，retrieval-stage only：

| strategy | MRR | R@1 | R@3 | R@5 | R@10 | NDCG@5 | NDCG@10 | elapsed |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| heuristic + parent packing | 0.5561 | 0.1750 | 0.5550 | 0.6200 | 0.7000 | 0.5333 | 0.5654 | 288.35s |
| `support` + parent packing | 0.6080 | 0.2100 | 0.5750 | 0.6550 | 0.7350 | 0.5744 | 0.6059 | 297.49s |

对比结果：`support` 相对 heuristic 全指标上升；100q 中 rescued 18 个 query、harmed 1 个 query，且 recall harmed 为 0。两组均启用 parent packing，该对照支持更换 reranker 的局部排序收益，不能单独归因 parent packing。

Galileo covidqa test 100q，seed=13，LangSmith/tracing 关闭，sentence-level retrieval：

| strategy | label | MRR | R@1 | R@3 | R@5 | R@10 | NDCG@5 | NDCG@10 | elapsed |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| keyword | relevant | 0.7092 | 0.2111 | 0.3962 | 0.4869 | 0.6127 | 0.5226 | 0.5565 | 0.012s |
| production `support` | relevant | 0.7729 | 0.2335 | 0.4048 | 0.5270 | 0.7678 | 0.5741 | 0.6615 | 0.688s |
| shared sparse/support | relevant | 0.7652 | 0.2239 | 0.4467 | 0.5740 | 0.8164 | 0.6190 | 0.7063 | 0.150s |
| keyword | utilized | 0.5925 | 0.2791 | 0.4637 | 0.5522 | 0.6776 | 0.4795 | 0.5285 | 0.012s |
| production `support` | utilized | 0.6623 | 0.3143 | 0.4901 | 0.5893 | 0.8229 | 0.5227 | 0.6203 | 0.688s |
| shared sparse/support | utilized | 0.6461 | 0.2992 | 0.5238 | 0.6436 | 0.8445 | 0.5569 | 0.6441 | 0.150s |

结论：`support` 不只在 Open 上有效，在 Galileo sentence-level 上也相对 keyword 全指标上升，尤其 R@10/NDCG@10 提升明显。shared sparse/support 仍在 R@3/R@5/R@10/NDCG 上更强，说明当时 `support` 在这些样本上有局部收益，但 eval-only shared selector 的部分候选覆盖/排序能力还没有完全沉淀进生产链路。

### 当时 Ask 实现的 `llm_gated`

新增 weak-top-support trigger 后，Open RAGBench 30q，seed=13，retrieval-stage only：

| strategy | MRR | R@1 | R@3 | R@5 | R@10 | NDCG@5 | NDCG@10 | elapsed | LLM calls |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `support` | 0.6139 | 0.2333 | 0.5833 | 0.6500 | 0.7000 | 0.5868 | 0.6078 | 99.47s | 0 |
| `llm_gated` | 0.6389 | 0.2500 | 0.6167 | 0.6667 | 0.7000 | 0.6113 | 0.6259 | 113.60s | 4 |

结论：

1. `llm_gated` 在 30q 上只调用 4 次，触发原因均为 `weak_top_support`。
2. 相对 `support`，`llm_gated` 继续提升 MRR、R@1、R@3、R@5、NDCG@5、NDCG@10，R@10 持平。
3. 30q 中 LLM rescued 2 个 query、harmed 1 个 query；当轮 `preserve_top_k=1` 消融没有取得更好的指标，未被选为当时默认。
