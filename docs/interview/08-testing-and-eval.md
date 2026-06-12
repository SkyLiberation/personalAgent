# 测试与评测

### 1. 你会怎么测试 workflow projection 不会生成危险步骤？

可以做几类测试：校验没有 `resolve` 的删除计划必须失败；`delete_note` 不允许出现在 ReAct 步骤中；`delete_note` 必须声明 high risk 和 requires confirmation；`capture_text` 在 solidify 中必须依赖 compose；工具参数不满足 args schema 时不能执行。

这些是 unit / contract tests，目标是证明危险计划不能越过校验。实际分两份：`tests/test_plan_validator.py` 测运行时投影层（PlanStep 危险计划拦截），`tests/test_workflow_validator.py` 测 spec 契约层（WorkflowSpec 自洽性 + spec↔工具能力一致性闸门，例如未注册工具、要求确认的工具但步骤没声明确认都会被拦）。

### 2. 怎么测试 `delete_note` 必须经过确认？

构造删除请求，让第一次工具调用返回 pending confirmation，并断言长期存储没有被删除。然后模拟用户确认 resume，断言带 `confirmed=true` 和 idempotency key 后才删除目标 note、chunk、review card 和 graph mapping。

还要测用户拒绝、重复确认、缺失 idempotency key、目标不存在等边界。

### 3. 怎么评估长期记忆召回质量？

可以建立 memory eval：准备一批已 capture 的文档和问题，标注应该命中的 note/chunk，评估召回率、引用正确率、chunk 命中率、parent 回溯准确率、错误引用率。

还要加冲突和过期知识样例，测试系统是否能发现证据冲突，而不是引用旧知识。

### 4. 怎么评估 solidify 有没有写入错误事实？

设计长会话干扰样例：用户提出方案后否定、助手做出猜测但用户未确认、用户纠正前文、多个主题混杂。然后让用户要求固化，检查写入的 note 是否只包含用户明确要求固化的内容。

指标可以包括错误写入率、遗漏率、助手假设污染率、废弃方案污染率。

### 5. 单元测试和 Agent eval 的区别是什么？

单元测试验证确定性代码边界，例如 schema 校验、Gateway 策略、HITL 状态转移。Agent eval 验证模型参与后的整体行为，例如是否选对工具、是否解析对目标、是否把错误对话固化、是否在证据不足时澄清。

两者都需要：单元测试防回归，eval 发现模型和 prompt 层面的行为问题。

### 6. 线上 Agent 问题怎么复现？

不能只拿用户原始输入重新跑一遍。Agent 的线上失败往往依赖当时的执行现场：同一 thread 的历史 `messages`、router / planner 中间状态、`plan.steps`、ReAct 当前轮次、`tool_tracking`、`tool_results`、`pending_confirmation`、`errors` 和下一步 graph node。重新输入一句话只能复用入口文本，复现不了当时的 checkpoint 状态。

项目里用 LangGraph checkpoint 做现网复现：先按用户反馈找到对应 `run_id / thread_id`，通过 `GET /api/entry/runs/{run_id}/history` 查看 checkpoint 时间线摘要，选择失败前或失败中的 `checkpoint_id`，再用 `replay_from_checkpoint(thread_id, checkpoint_id, updates)` 从这个历史现场 fork 一条新执行线继续跑。

例如用户反馈“删除 DNS 知识时卡住 / 删除目标不对”，后台可以找到 `intent=delete_knowledge`、`status=waiting_confirmation`、`pending_confirmation.tool_name=delete_note` 的 checkpoint，从这里重放。这样可以判断问题发生在 planner 选错候选、确认 payload 错、工具返回异常、状态归属错，还是 graph edge 卡住。

这个能力的价值是现网问题复现和修复验证：修代码或 prompt 后，可以用同一个 checkpoint 再 replay，确认修复是否真的覆盖线上失败现场。它不是普通用户的“撤销删除”功能；已删除数据恢复仍需要软删除、删除前快照或回收站。带副作用的 replay 还必须依赖幂等账本，避免重复删除或重复写入。

---

[← 返回索引 INDEX.md](INDEX.md)
