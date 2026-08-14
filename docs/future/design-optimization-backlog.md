# 设计优化队列

> **定位：本文件只保存尚未解决、且有明确退出条件的设计问题。** A0 只允许执行 baseline 和补证据；A1 才能分析局部根因；A2 评审通过后才能修改生产设计。已经解决、baseline 未失败或根因不符的问题必须移出本文件。

## 当前结论

**当前没有已准入的设计优化问题。** `HARNESS-003` 已由同输入产品 baseline、单变量消融和正式 target 关闭；当前 Working Plan 的事实、证据和边界已迁移到[当前架构说明](../summary/core-architecture-current-state.md)与[当前 E2E 用例盘点](../evals/02-current-case-inventory.md)。

这不表示当前实现无需继续审视，而是表示：在新的同输入失败证据出现前，不继续增加 Plan 字段、Planner、依赖图、第二套 Todo、Workflow、Task 表或并发协议。

## 准入状态

| 状态 | 含义 | 允许动作 |
| --- | --- | --- |
| A0 | 风险假设，尚无对应 baseline | 只执行正式入口 baseline、保存证据并确认用户契约 |
| A1 | baseline 已失败 | 定位局部根因并执行单变量消融 |
| A2 | 根因、目标 E2E、owner、净复杂度和删除项齐全 | 实现最小纵向切片并删除旧路径 |

退出条件：baseline 未失败、根因不符、候选被否决或目标 E2E/工程验收已通过。退出后把当前事实迁移到 canonical summary/topic/ADR，把用例语义迁移到 eval 文档，不在 future 保存完成阶段和排查流水帐。

## 当前不准入的复杂度

- 不以文件行数、框架范式或“优秀 Agent 也有”为由新增对象和层；
- 不为 Working Plan 再建一套内部 Todo、Task、Workflow 或 Projection；
- 不把 Tool success、reason code 命中、对象存在或状态为 completed 当成用户结果；
- 不通过字符串判断、同义 Prompt 堆叠或确定性 fallback 替模型完成开放语义判断；
- 不在并发失败 baseline 之前引入 Lease、CAS Repository、分布式锁或队列。

## 新条目准入模板

```markdown
## <ID>：<用户错误或可量化工程约束>
状态：A0 | A1 | A2

### 同输入 baseline 与反事实
### 根因与决策/事实 owner
### 参考实现（等级与可复核坐标）
### 最小生产改动与同步删除项
### target E2E、复杂度预算与退出条件
```

新增项必须先说明用户结果、关键反事实和最简单正式入口。外部实现只回答机制怎样做，不构成需求；产品变更没有同输入失败 E2E、纯重构没有工程约束基线与行为保持 E2E 时，条目只能停在 A0。
