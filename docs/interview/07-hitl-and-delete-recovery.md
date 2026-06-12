# HITL 与删除恢复

### 1. 删除 note 的完整确认流程是什么？

用户提出删除请求后，router 进入 `delete_knowledge` planning。计划执行 `retrieve` 找候选，`resolve` 确认真实 `note_id`，然后调用 `delete_note`。

第一次 `delete_note` 不删除数据，只返回 pending confirmation。Graph 把 payload 写入 `AgentGraphState.pending_confirmation` 并 `interrupt()`。用户确认后，Graph 用同一 `thread_id` resume，把 `confirmed=true` 和 `idempotency_key` 注入工具输入，再次调用 `delete_note` 才执行软删除：先写入删除快照，再给 note/chunk 标记 `deleted_at`，默认检索和复习查询不再返回它们。

### 2. 用户拒绝确认时会怎样？

Graph 会把当前步骤标记为 skipped，递归跳过依赖它的后续步骤，清空 `pending_confirmation`，并返回取消说明。不会执行真实删除。

### 3. 为什么确认后还需要 `idempotency_key`？

因为确认请求可能重复提交，checkpoint resume 可能重放，网络或服务异常也可能导致重复执行风险。`idempotency_key` 用 thread/run/step 等信息标识同一次确认动作，Gateway 用它阻断重复副作用。

当前幂等账本已落到 Postgres `tool_idempotency_ledger`。Gateway 在确认副作用执行前先 `reserve()` 幂等 key，底层用 `INSERT ... ON CONFLICT DO NOTHING` 抢占；抢到 key 才继续执行，成功后标记 committed，失败会释放 reservation。这样可以覆盖重复确认、checkpoint 重放、服务重启和横向扩容下的重复执行风险。

### 4. pending confirmation 是长期审批表吗？

不是。它属于当前 thread/run 的短期执行现场，保存在 LangGraph checkpoint 里。它的作用是暂停和恢复当前执行流程，不是长期业务审批系统。

如果未来做生产级审批，应有独立审批表、确认人、确认时间、权限和审计记录。

### 5. `replay_from_checkpoint` 在删除流程里解决什么问题？

它主要解决现网问题复现，不是用户级删除恢复。

如果用户反馈“删除 DNS 知识时卡住了 / 删除目标不对”，后台可以按 `run_id / thread_id` 查 checkpoint history，找到 `intent=delete_knowledge`、`status=waiting_confirmation`、`pending_confirmation.tool_name=delete_note` 的历史点，然后从这个 checkpoint fork 重放。这样保留了当时的 `messages`、plan、tool tracking、tool results、pending confirmation 和 errors，比只拿“删除 DNS”这句话重新跑更容易复现真实问题。

它能帮助定位：resolve 是否选错 note、confirmation payload 是否错、工具结果是否归属到错误 step、resume 后 graph 是否卡在某个节点。修复代码或 prompt 后，也可以用同一个 checkpoint 重放验证。

但它不是业务恢复接口。如果用户在确认阶段反悔，走普通 `resume_entry(decision="reject")`；如果删除已经执行后要恢复，走 `restore_note`，它会从 `knowledge_delete_snapshots` 恢复 note、chunk 和 review card，并且同样经过 ToolGateway、PolicyEngine、幂等账本和审计。`replay_from_checkpoint` 是管理后台 / 事故复现能力，不应裸露给普通用户随意改 state。

---

[← 返回索引 INDEX.md](INDEX.md)
