# ADR 0054：会话拥有轮次历史

2026-11-17 已切换 Turn 接口和 Step 身份。现行存储为文件 Journal，主循环仍按客户端提交的消息前缀选择分支。服务端 Session 接管有序历史及 SQLite 事务存储属于后续设计。[现行实现](../architecture/core-architecture-current-state.md#32-会话运行与主决策的现状) · [生命周期规格](../optimization/to_verify/conversation-loop-boundaries.md#320-sessionturn-与-step-生命周期)

## 后续决定

单条消息入口需要服务端确定前驱。拟由一个事务型 Journal 同时拥有会话、轮次输入、冻结的前驱与步骤身份。开始首轮时一并提交 Session，主模型调用前确定 Step 位置。前驱缺失、归属不符或版本冲突时拒绝提交。授权、执行、核验和交付沿领域边界，Artifact 保留确切原件。以单一提交点避免独立会话索引和轮次记录发生部分写入。[DeepSeek Harness 固定实现](https://github.com/deepseek-ai/deepseek-harness/blob/b150a551b8d465e31e418e1b2eaf5e79bbb7d28e/packages/session/session-persistence-sqlite/src/store.ts#L175)

## 迁移与验收

先在隔离存储核对实际历史、响应续接和回执归属，再验证正式入口与恢复。离线迁移保留旧原件；前驱无法确定或存在未决副作用时停止迁移对应会话。回退前封存新执行事实并对账。原用例、迁移和启用判据由生命周期规格维护。
