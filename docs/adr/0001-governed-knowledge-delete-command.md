# ADR 0001: 最小可恢复知识生命周期操作

- 状态：Accepted
- 日期：2026-07-24
- 修订：2026-08-11

## 问题

知识删除是需要用户确认、重启恢复和幂等执行的高风险操作，不能由普通
Conversation Tool 或 HTTP Adapter 直接改库。恢复还必须精确还原删除前的
Knowledge Item 与 Claim 状态。

旧实现为此同时引入了通用 Procedure、`delete_note`/`restore_note` Tool、
快照 Store、六张 Command/Event/Receipt 表和
`AuthorizationDigest`/`ExecutionCommandDigest`。这些机制有多个重叠写入口，
生命周期 Event 也没有独立订阅或重放消费者。它们增加了同步和恢复路径，
但没有改善 E04/E10 所要求的用户结果，属于超过当前约束的设计。

## 最简单 baseline 与不足

直接软删除只需一次状态更新，但不能满足：

- prepare 阶段零副作用并在重启后继续确认；
- 确认内容与实际执行内容一致；
- 相同请求只执行一次并返回同一 Receipt；
- 恢复 Item 和所有 Claim 的删除前状态；
- 跨 user/personal knowledge 操作 fail closed。

因此需要 durable operation，但不需要通用 Planner、Procedure、生命周期
Event 或两套 digest。

## 决策

`KnowledgeLifecycleService` 是删除和恢复的唯一 Application 写入口。

1. prepare 创建 immutable `KnowledgeDeleteCommand` 或
   `KnowledgeRestoreCommand`，状态为 `awaiting_confirmation`，不修改业务事实；
2. 一个服务端 `command_digest` 对 canonical command payload 做 SHA-256，绑定
   Operation 和 Receipt；digest 是内部一致性与幂等指纹，不是身份、授权或客户端确认凭据；
3. decision 由 path 中的 `command_id` 选择 immutable Command，校验入口身份、command owner、
   状态和 `confirmation_ref`；客户端不能回传或覆盖 digest；
4. confirm 在一个数据库事务中更新 Personal Knowledge canonical facts、写 Personal Knowledge
   `KnowledgeStateEvent` 并写 Receipt；
5. replay 已执行 command 时直接返回原 Receipt，不再次产生副作用；
6. restore 必须引用已执行的 delete command，并以 delete receipt 中记录的
   previous states 为恢复依据。

持久化只保留两张共享表：

- `knowledge_lifecycle_operations`：delete/restore command、kind、status 和确认信息；
- `knowledge_lifecycle_receipts`：不可变执行结果和恢复所需 previous states。

Delete 与 Restore 保留不同的 typed Command/Receipt，因为它们的 payload、
前置条件和恢复责任不同；它们共享表结构，不复制生命周期框架。

不创建 `KnowledgeDeleteEvent`/`KnowledgeRestoreEvent`。Operation status 已能表达
等待、拒绝和执行；真正的 Item/Claim 状态变化由 Personal Knowledge
`KnowledgeStateEvent` 记录，它有审计消费者。

## 所有权

- Command、operation status、Receipt：`KnowledgeLifecycleService` /
  `PostgresKnowledgeLifecycleStore`；
- Knowledge Item、Claim 和其状态事件：Personal Knowledge aggregate；
- 用户身份与 scope：正式 HTTP 入口解析，body 不得扩大 scope；
- 执行事实：Receipt；完成结果：Operation View 中 `status=executed` 且 Receipt
  存在。

## 被删除的方案

- 通用 `knowledge_delete` Procedure 和 LangGraph interrupt 路径；
- `delete_note`、`restore_note` Tool 及 MemoryFacade 写入口；
- `knowledge_delete_snapshots` 运行时读写路径；
- 分离的 delete/restore Command、Event、Receipt 六表；
- 无独立消费者的 lifecycle Event models；
- 双 digest 确认协议。

旧六表数据在 schema 初始化时迁入两张新表后删除。旧
`knowledge_delete_snapshots` 不再创建、读取或写入；已有物理表仅作为待运维
导出/清理的历史数据，不是兼容入口或权威事实。

Legacy 六表迁移代码只服务本次滚动升级。所有部署环境完成一次启动并确认六个
旧表均不存在后删除该代码及迁移测试，最晚移除日期为 2026-10-31。历史 snapshot
表由运维在导出或确认无保留义务后清理，不得重新接入生产读取。

## 目标 E2E 与反事实

- prepare 返回 command 与服务端诊断用 `command_digest`，业务事实不变；
- 错误 user/personal knowledge、错误/不存在的 command id、缺失确认或 rejected command 均不执行；
- 进程重启后可以确认同一个 command；
- 同 command replay 返回同一 Receipt，状态事件不增加；
- restore 在重启后精确恢复 Item/Claim previous states；
- 响应不存在 lifecycle `events` 投影；
- 旧 DELETE、snapshot restore、普通 Conversation Tool 路径不可达。

对应测试为 release E04/E10 和 notes API integration。GOV-002 baseline 曾证明客户端只携带
`command_id + authenticated principal + confirmation_ref` 时旧 API 返回 422；目标 E2E 现已通过，
而内部 digest、Receipt 绑定和 replay 行为保持不变。

## 复杂度结论

最小 durable baseline 仍需 Command、Receipt、确认状态和事务恢复依据；删除它们
会破坏已证明的 E2E。Planner、Procedure、双 digest、生命周期 Event 与独立六表
没有独立 owner、信任边界或生产消费者，因此移除。若未来出现独立授权编译、
事件订阅或跨 Provider 绑定，必须以新的 baseline 失败证据和 ADR 重新准入，
不能预留空壳。
