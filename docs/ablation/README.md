# 机制消融

本目录保存隔离实验的规格、结果与证据边界。实验回放按 Offline Eval 解释；当前生产契约见[核验专题](../topics/verification-and-completion.md)，完整用户结果与发布资格见[评测体系](../evals/README.md)。

## 按阅读目标进入

| 阅读目标 | 正文与数据 |
| --- | --- |
| 额外 claim 的比较规格、局部收益、成本与未测边界 | [主报告](claim-verifier.md)、[原始汇总](claim-verifier-data.json) |
| 固定指标与历史基线的只读重算 | [指标规格](claim-verifier.md#21-具体评估指标)、[冻结计划](claim-verifier-baseline.plan.json)、[指标快照](claim-verifier-metrics.json)、[运行命令](../evals/04-running-and-release.md#claim-指标持续评估) |
| 全部反馈的事后 AI 初审及限制 | [初审报告](claim-complete-review-20261020.md)、[逐行数据](claim-complete-review-20261020.json) |
| N2 的真实修订与用户收益边界 | [恢复预检](claim-n2-continuation-preflight-20261020.md)、[条件续跑](claim-n2-continuation-20261021.md)、[价值复核](claim-verifier.md#223-claim-收益价值复核)、[反馈交接续验](claim-verifier.md#224-历史反馈交接的真实续验) |
| 海岸漏报的输入、任务与判断诊断 | [Context 删除与输入归属](claim-verifier.md#23-context-定向删除验证)至[直接追问](claim-verifier.md#213-直接追问未分类原因)；每节链接对应结果数据 |
| 分类方法、反馈结构及字段顺序 | [反馈输出结构审查](feedback-output-schema.md)；包括[字段顺序](feedback-output-schema.md#7-字段顺序敏感性诊断)与[未绑定原文片段](feedback-output-schema.md#8-未绑定原文片段的加入诊断) |
| 固定输入重复、逐轨审计、理由输出及语言对照 | [固定输入重复](claim-verifier.md#217-固定输入的二十次重复)至[基础反馈验收复核](claim-verifier.md#222-中文单类核验恢复基础反馈与验收复核)；每节保留原分母、成本及未执行量 |
| 研究题目来源、采样与中文改编 | [任务来源与采样](research-tasks.md) |

主比较未证明额外 claim 的稳定整体优势或净收益。局部发现、研究资源纠错、反馈可用性、实际修订和最终用户结果分别计量；不以发现条数或单点命中替代用户收益。后续诊断各有独立身份，不并入主比较分母，也不覆盖旧标签和成绩。具体判断及证据由上述正文拥有，本索引不复制逐轮结果。
