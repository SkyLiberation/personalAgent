# 设计优化队列

> **定位：所有尚未退出的设计优化问题的唯一队列。** 当前实现事实由 summary、topic、workflow、API 与 ADR 文档拥有；baseline 已通过、已落地或被否决的问题不留在 future。

## 当前队列

**暂无已准入问题。**

## 准入状态

| 状态 | 含义 | 允许动作 |
| --- | --- | --- |
| `A0` | 只有风险假设，尚无适用于该变更类型的失败 baseline | 执行最简单生产/工程 baseline；不得编码 |
| `A1` | baseline 已失败且根因在本工程 | 冻结目标验证、所有权与最小设计 |
| `A2` | 目标验证、复杂度预算和删除路径已评审 | 实施使目标验证通过的最小改动 |

退出条件：baseline 未失败、根因不符、候选被否决或目标 E2E/工程验收已通过。退出时删除本项，不在此保存“已完成阶段”、历史排查或运行结果。

## 新问题模板

```markdown
## <DOMAIN>-NNN：<一句话问题>
### 结论与待验证影响
### 当前实现证据
### Decision / Fact Ownership
### Simplest Baseline E2E / Executed Result / Root Cause
### Referenced Industry Mechanism（grade + verifiable coordinate）
### baseline 失败后的最小条件设计
### Target E2E and Counterfactuals
### Complexity Budget、同步删除项与退出条件
```

新增项必须先说明用户结果、关键反事实、正式入口、生产消费者、事实 owner、失败语义和计划删除项。外部框架只回答机制如何实现，不能替代本工程 baseline 证明“为什么需要”。
