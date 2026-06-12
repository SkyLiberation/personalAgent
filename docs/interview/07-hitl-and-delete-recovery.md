# HITL 与删除恢复

### 1. 删除 note 的完整确认流程是什么？

用户提出删除请求后，router 进入 `delete_knowledge` planning。计划执行 `retrieve` 找候选，`resolve` 确认真实 `note_id`，然后调用 `delete_note`。

第一次 `delete_note` 不删除数据，只返回 pending confirmation。Graph 把 payload 写入 `AgentGraphState.pending_confirmation` 并 `interrupt()`。用户确认后，Graph 用同一 `thread_id` resume，把 `confirmed=true` 和 `idempotency_key` 注入工具输入，再次调用 `delete_note` 才真正删除 note、chunk、review card 和可用的 graph episode 映射。

### 2. 用户拒绝确认时会怎样？

Graph 会把当前步骤标记为 skipped，递归跳过依赖它的后续步骤，清空 `pending_confirmation`，并返回取消说明。不会执行真实删除。

### 3. 为什么确认后还需要 `idempotency_key`？

因为确认请求可能重复提交，checkpoint resume 可能重放，网络或服务异常也可能导致重复执行风险。`idempotency_key` 用 thread/run/step 等信息标识同一次确认动作，Gateway 用它阻断重复副作用。

当前幂等账本是进程内实现，所以能覆盖单进程重复确认，但服务重启或横向扩容后还需要持久化幂等账本。

### 4. pending confirmation 是长期审批表吗？

不是。它属于当前 thread/run 的短期执行现场，保存在 LangGraph checkpoint 里。它的作用是暂停和恢复当前执行流程，不是长期业务审批系统。

如果未来做生产级审批，应有独立审批表、确认人、确认时间、权限和审计记录。

---

[← 返回索引 INDEX.md](INDEX.md)
