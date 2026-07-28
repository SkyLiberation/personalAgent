# Knowledge Delete / Restore Workflow

知识删除不是开放式 Agent 规划问题。调用方必须先给出 canonical `note_id`；
系统只负责确认、幂等执行、恢复和审计，因此使用固定 Application Use Case。

## 生产主链

```text
POST /api/notes/{note_id}/delete-commands
  -> KnowledgeLifecycleService.prepare_delete
  -> knowledge_lifecycle_operations(awaiting_confirmation)

POST /api/knowledge-delete-commands/{command_id}/decision
  -> identity/scope + command_digest + confirmation_ref 校验
  -> one transaction:
       KnowledgeItem/Claim state transition
       Workspace KnowledgeStateEvent
       knowledge_lifecycle_receipts
  -> KnowledgeDeleteOperationView(executed, receipt)
```

prepare 没有业务副作用。进程重启后，客户端可以 GET operation 并继续 decision。
重复 confirm 返回同一 Receipt，不重复状态迁移。

## 恢复主链

```text
executed delete command
  -> prepare restore command
  -> independent confirmation
  -> read previous states from delete receipt
  -> restore KnowledgeItem/Claim + state events + restore receipt
```

Restore 使用独立 Command/Receipt，因为 payload、前置条件和执行结果与 Delete
不同；两者共享 operation/receipt 表，不创建通用 Workflow、Planner 或 lifecycle
Event 体系。

## 安全边界

- HTTP 入口解析 authenticated user；body 中的 user 不能扩大 scope；
- 一个 `command_digest` 绑定 canonical command payload，不能代替身份或 Policy；
- command owner、workspace、digest 或 confirmation 不匹配时 fail closed；
- reject 后不能 confirm；
- delete receipt 是恢复 previous states 的唯一依据；
- Workspace aggregate 拥有 Item/Claim 状态，Lifecycle Service 不能复制事实；
- 旧直接 DELETE、snapshot restore、Conversation Tool/Procedure 路径不可达。

## 为什么不用 Agent Workflow

模型可以在更上游帮助用户寻找候选知识，但候选选择不能隐式触发删除。目标
一旦成为明确 `note_id`，后续依赖固定且无开放语义分支。Planner、LangGraph
interrupt、ToolGateway 包装和 lifecycle Event 都不会改善确认、重启、replay
或恢复结果，只会增加第二状态机和同步路径，因此不进入该主链。

## E2E

Release E04/E10 和 notes API integration 覆盖：

- prepare 零副作用；
- scope、digest、确认和 reject 反事实；
- prepare/confirm 与 delete/restore 之间的进程重启；
- exactly-once Receipt 和不重复状态事件；
- Item/Claim previous states 精确恢复；
- 旧路径不可达。

详细架构理由见 [ADR 0001](../adr/0001-governed-knowledge-delete-command.md)。
