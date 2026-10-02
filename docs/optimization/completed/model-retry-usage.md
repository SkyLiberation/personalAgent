# 模型重试累计全部已完成响应用量

**已修复 `MODEL-RETRY-USAGE-001`：有界修复失败后进入外层重试，全部已完成 Provider 响应的用量保留并累计。** 已知 total 与响应汇总一致，缺失输入或输出用量保持未知。

## 原问题与最早责任边界

[真实固定输入审计](../../../.tmp/evidence-first-restored-20260930/coordinate-probe/audit.json)记录九次 typed 操作、十三次 Provider 完成共 224,770 tokens，Adapter 只报告 200,590。c2 前两次失败完成响应 `0008/0010` 共 24,180 tokens；原 `_generate_structured` 在聚合前抛出异常，唯一外层重试没有接收这些消耗。

## 责任、机制与生产消费

Provider 产生执行用量。非流式 Adapter 收集初次生成和有界修复的实际响应：成功返回聚合结果，结构修复耗尽或后续传输失败将已完成响应的用量附在 typed failure 上。失败载体不包含已准入动作。

`RetryingStructuredModelClient` 是唯一外层重试 owner，消费每次实际失败与最后响应，按分项聚合；成功与最终耗尽均保留先前消耗。某次输入或输出用量未知时，对应总字段保持未知；total_tokens 保存已知下界，完整分项齐全时可确定性推导缺失 total。latency 覆盖整个操作及重试等待，retry_attempts 累计有界修复与外层重试。

生产 `build_structured_model_client`、`build_chat_model_client` 继续装配同一 Retry → UsageRecording 链。现行记录器在成功及携带已知响应的 typed 失败上记录一次，避免双计。未增加持久计量镜像、业务状态或 Provider 请求。

## 决定性验证

[责任边界回放](../../../.tmp/research-convergence-integration-20261001/usage-replay.json)通过真实归档响应和 SDK 传输边界消费生产 Adapter、Retry 与 UsageRecording；这是历史失败的局部反事实。

| 边界 | 核对结果 |
| --- | --- |
| 两次空输出耗尽后外层恢复 | 四份已完成响应 45,393 tokens，旧计量 21,213，新计量 45,393；补齐 24,180。历史九次操作汇总由 200,590 恢复为 224,770。 |
| 修复最终耗尽 | 已完成两份响应 24,180 tokens 保留在 typed failure，记录器消费一次。 |
| 修复传输失败后恢复 | 两份已完成响应 21,213 tokens 保留，输入输出完整性保持未知。 |
| 外层传输最终耗尽 | 先前已完成两份响应 24,180 tokens 保留，未知消耗不补零。 |

同入口真实 target 的已完成响应、Journal 与实际用户结果由[评测登记](../../evals/02-current-case-inventory.md#2026-10-01-重试计量与研究设计接入)及[正式归档](../../../.tmp/research-convergence-integration-20261001/target/identity.json)拥有。

后续引用继承正式 target 自然触发该恢复分支：[实际计量审计](../../../.tmp/research-retained-reference-repair-20261001/actual-retry-usage-audit.json)保存第 6 版 c1 的六份 Provider 完成，前五份长度截止，第六份返回有效报告。全部 56,167 tokens 与前后 Journal 增量逐分项相等；Journal 的 typed 操作计数增加 1，物理响应数为 6。修复与重试聚合后的用量已由正式 Conversation 消费。

原机制只返回最后成功操作的小计，导致失败完成消耗丢失；现行方案先保留失败用量再由唯一重试层聚合。若已完成响应漏计、重复累计或缺失用量被标为完整，则重新打开本问题。
