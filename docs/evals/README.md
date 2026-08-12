# 评测文档索引

**评测按所回答的问题分层；发布证据、语义质量和运行效率不能用同一个分数替代。**

| 层次 | 回答的问题 | 权威来源 |
| --- | --- | --- |
| Product E2E / release evidence | 用户目标和关键反事实是否从正式入口成立，证据是否可用于当前 revision 发布 | [E2E 与发布证据](e2e-quality-cases.md)、`evals/e2e_quality/evidence_catalog.py`、`release_gate.py` |
| Offline semantic eval | 检索、路由、Conversation 或答案等局部语义质量是否改善 | 各 `evals/<suite>/README.md`、数据集、runner 与 scorer |
| Runtime measurement | 达成同一用户结果需要多少 token、调用、时间，重复运行和恢复是否稳定 | `MeasurementProfile`、`CaseMeasurement` 与 `python -m evals.e2e_quality.metrics_report` |

## 使用边界

- **E2E pass 是用户结果证据，不是效率指标。**对象存在、状态为 success 或单个 Tool 成功不能替代它。
- **离线 scorer 是诊断证据，不是发布证明。**检索 Recall、路由 F1 或 trace grade 改善后，仍需对应产品 E2E。
- **release gate 是信任门禁，不是统计报表。**它只判断 catalog、revision、archive 和执行结果是否可信。
- **框架比较必须固定 workload 与运行条件。**报表会拒绝混合 profile；当前只有一套真实 runtime profile，因此只能建立基线，不能声称框架 A/B 优势。

## 生成运行报告

```powershell
uv run python -m evals.e2e_quality.metrics_report `
  --trace-root data/e2e_traces --profile current-runtime `
  --require-complete-profile --output data/e2e_metrics/current-runtime.json
```

缺失 Provider usage 会明确标为 unavailable，不会按零计；diagnostic 不进入产品完成率，少于 20 个同 profile 重复样本不输出 P95。

评测结果和一次性运行状态不在本目录手工维护；它们应由 runner 生成并与 revision、profile 和 archive 绑定。
