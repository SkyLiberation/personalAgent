# 旧 E2E 矩阵的观测记录

本文用于解释清理前自建 E2E 矩阵的归档。其 `evals.e2e_quality.metrics_report` 入口随旧矩阵退出当前工作树。查看公开数据集的现行入口、归档和发布要求时，从[评测运行与发布](04-running-and-release.md#公开数据集运行)进入。

## 历史归档字段

每个 archive 冻结：

- runtime implementation；
- structured provider/model；
- prompt revision；
- capability catalog revision；
- model/tool/agent/token/concurrency budget；
- fixture revision；
- repetition。

这些字段共同决定 cohort。同一个 `profile_id` 不能替代完整 cohort key。

## 历史指标来源

| 指标 | 归档来源 | 当时覆盖 |
| --- | --- | --- |
| case pass/fail/skip | `summary.json` | 所有被执行用例 |
| case call duration | pytest call phase | 所有被执行用例 |
| suite wall-clock duration | archive summary | 每个 archive |
| total tokens | typed InteractionTrace → automatic CaseMeasurement | 所有归档了 Conversation trace 的 journey |
| model turns | typed InteractionTrace → automatic CaseMeasurement | 同上 |
| tool calls | typed InteractionTrace → automatic CaseMeasurement | 同上 |
| agent calls | typed InteractionTrace → automatic CaseMeasurement | 同上 |
| input/output tokens | committed provider usage → automatic CaseMeasurement | 新 Conversation run；旧 journal 不补零 |
| model calls | committed provider usage → automatic CaseMeasurement | 新 Conversation run；包含 review admission 与 agent turn |
| recovery duration | CaseMeasurement schema | 当前测试没有写入 |
| replay new side effects | CaseMeasurement schema | 当前测试没有写入 |

自动 extractor 只接受能完整校验为 `InteractionTrace` 的对象，并按 run ref 保留最新 revision；它不会从任意 raw dict 猜测字段或补零。

旧 reporter 按 cohort 汇总完成率、用量、调用、延迟及恢复指标。只有同 profile 至少 20 个可用样本时才输出 P95。缺失 measurement 标为 `unavailable`。

## 已有报告

历史 `current-runtime` 中的 profile ID 冲突被保留，后续 profile ID 使用完整 cohort digest。`target-eval-infra-20260812-usage` 记录 1/1 完成、0/1 受限结束、7,041 输入 tokens、208 输出 tokens、7,249 总 tokens、2 次模型调用、1 个模型轮次及 23.191393 秒用例耗时。该 profile 的 P95 为 `unavailable`。其他历史样本和归档位置见[评测盘点](02-current-case-inventory.md)。

## 指标解释边界

| 指标 | 可以解释 | 不能单独解释 |
| --- | --- | --- |
| completion rate | 固定 workload/profile 的目标达成比例 | 开放世界总体能力 |
| latency | 该用户旅程端到端等待时间 | 模型推理速度或 Provider 网络的独立贡献 |
| token/calls | 完成该 workload 的资源消耗 | 答案质量 |
| recovery success/duration | 故障场景下恢复结果与时间 | 所有 crash window 的 exactly-once |
| replay side effects | 已覆盖副作用在 replay 中是否新增 | 未观测外部系统的一致性 |
| limitation rate | 系统诚实拒绝或受限结束的比例 | 失败率；有些 limitation 是正确用户结果 |

性能比较只有在用户目标、输入、Provider、模型、Prompt、预算、fixture 和 repetition 一致时成立。不同 case 或不同 profile 的耗时不能直接排列为框架优劣。
