# BrowseComp-Plus 五题对照结果

2026 年 11 月 26 日，两边各执行一次发布顺序的五道公开题 `769`–`773`。本 Agent 关闭 Conversation Goal，完整作答 4 题并全部通过。DeepSeek Harness 完整作答 5 题并全部通过。双方都交付完整答复的 4 道题全部通过。

| 题号 | 本 Agent 结果 | 本 Agent 工具调用 | DeepSeek Harness 结果 | DeepSeek Harness 工具调用 |
| --- | --- | ---: | --- | ---: |
| `769` | 通过 | 6 | 通过 | 4 |
| `770` | 通过 | 30 | 通过 | 13 |
| `771` | 通过 | 5 | 通过 | 3 |
| `772` | 通过 | 24 | 通过 | 78 |
| `773` | `limitation`，未交付完整答复 | 40 | 通过 | 69 |

## 第 773 题

两边首个检索请求就命中了官方金标文档，整轮均命中两篇金标文档。本 Agent 连续使用 `search`，39 次成功、1 次遇到 SSL 读取异常。达到 40 次工具调用上限后，实际 HTTP 终态为 `limitation`。DeepSeek Harness 调用了 64 次 `search` 和 5 次 `get_document`，其中读取了一篇金标文档的全文，最终答复通过评分。该题的交付差异伴随全文读取行为和工具调用额度两项差异。

本 Agent 初版采集脚本把预算到顶后的工具声明收缩误记为接线异常。修正后使用原始封存的 HTTP 终态及实际模型请求重新校验，确认本例未交付完整答复。保留原始采集记录和复核来源。 [本 Agent 轨迹](../../../.tmp/browsecomp-plus-2026-11-26/run-01/773/personal/turn-trace.json) · [DeepSeek Harness 轨迹](../../../.tmp/browsecomp-plus-2026-11-26/run-01/773/deepseek/turn.json) · [单题评分](../../../.tmp/browsecomp-plus-2026-11-26/grade-01/773.json)

## 比较条件

- 校验了四份官方 8B 向量分片的 SHA-256，共 1,642,386,509 字节，索引包含 100,195 个文档。两边共用同一检索服务，查询使用硅基流动的 `Qwen/Qwen3-Embedding-8B`，正文按固定 Hugging Face 语料修订读取。
- 两边均使用 `MiniMax-M3.1-Flash`、`medium` 推理和 32,768 输出 token 上限，分别走正式 Conversation HTTP 与 DeepSeek Harness `0.2.2-rc.5` SDK。两边模型步骤上限均为 40。本 Agent 另有 40 次工具调用和 200 万总 token 上限。SDK 的 600 秒按单次通知等待计。
- 双方作答和轨迹封存后，使用上游评分模板、解析规则和硅基流动托管的 `Qwen/Qwen3-32B` 评分。正反评分校准通过。核对了 10 个独立会话、原题逐字一致以及本 Agent 5 轮的 Goal 配置。

[接入和复现](../../../evals/BrowseComp-Plus/README.md) · [运行计划与数据校验](../../../.tmp/browsecomp-plus-2026-11-26/run-01/plan.json) · [评分汇总](../../../.tmp/browsecomp-plus-2026-11-26/grade-01/summary.json)
