# E2E 观测指标

**归档器现在从经过 `InteractionTrace` 类型校验的生产 trace 自动提取 measurement；Product E2E 不再逐条手工选择是否写入。缺失的 provider 或恢复事实仍保持 unavailable。**

## 当前 MeasurementProfile

每个 archive 冻结：

- runtime implementation；
- structured provider/model；
- prompt revision；
- capability catalog revision；
- model/tool/agent/token/concurrency budget；
- fixture revision；
- repetition。

这些字段共同决定 cohort。同一个 `profile_id` 不能替代完整 cohort key。

## 当前可用指标

| 指标 | 当前来源 | 当前覆盖 |
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

## 当前 reporter 输出

`metrics_report.py` 定义：

- goal completion rate；
- input/output/total tokens；
- model calls/turns；
- tool/agent calls；
- case latency min/median/P95；
- recovery success rate；
- recovery duration；
- replay new side effects。

P95 只有同 profile 至少 20 个可用样本时才输出。缺失 measurement 是 unavailable，不是 0。

## Cohort 选择与已执行报告

实际命令：

```powershell
uv run python -m evals.e2e_quality.metrics_report --trace-root data/e2e_traces --list-cohorts
```

历史 `current-runtime` 的 collision 被保留并显式列出；新默认 profile id 包含完整 cohort digest。独立验证 profile `target-eval-infra-20260812-usage` 已成功输出 1/1 completion、0/1 limitation、7041 input / 208 output / 7249 total tokens、2 model calls、1 model turn 和 23.191393 秒 call latency；样本数不足 20，因此 P95 正确保持 unavailable。

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
