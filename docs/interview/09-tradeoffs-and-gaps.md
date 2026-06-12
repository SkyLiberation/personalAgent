# 工程取舍与不足

### 1. 为什么没有一开始就做完整权限系统？

当前项目优先把 Agent 的主链路和关键工程边界跑通：入口统一、router 分流、LangGraph 编排、短期/长期记忆分离、WorkflowSpec、PolicyEngine、ToolGateway、PlanValidator、HITL、evidence 出口和基础观测。

现在 `permission_scope` 已经进入治理契约和 `PolicyEngine`，基础策略判断已落地：工具调用、记忆访问和入口来源都能通过统一 `PolicyInput -> PolicyDecision` 做 allow / deny / require confirmation / require escalation。还不能说完整 SaaS 权限系统已落地，是因为 workspace/tenant 维度、角色/属性权限、长期审计查询和审批流仍需补齐。

### 2. 为什么 Graphiti 不直接替代 Postgres？

Graphiti 擅长语义关系和实体检索，但不适合作为业务事实真源。Postgres note/chunk 保存原文、摘要、source、chunk、review card、graph mapping 和可引用证据。

这样图谱抽取失败、关系不完整或 episode 残留时，系统仍然有可回溯的业务真源。

### 3. 为什么没有所有任务都用 ReAct？

ReAct 有探索能力，但也有不确定性和循环风险。普通任务有确定分支，高风险任务需要受控计划和 HITL，不适合让 ReAct 自主决定。

项目只把 ReAct 用在单步内部的低风险只读探索，并通过 allowlist、risk guard 和 max iterations 限制边界。

### 4. 如果只能优化一周，你会优先做哪三件事？

第一，为删除 `resolve` 增加候选确认 UI，降低误删风险。第二，把工具审计和 policy decision 落到独立审计表，并关联 step id、tool call id、side effect、policy rule 和 decision effect。第三，建立 memory/planning eval 的最小集，覆盖删除目标解析、solidify 长会话干扰和 evidence 引用正确率。

这三件事直接提升生产安全性和可验证性。

### 5. 当前项目最大的生产风险是什么？

主要风险有：PolicyEngine 还缺 workspace/tenant/RBAC/ABAC 等生产级权限模型；审计未独立落库（当前只走日志和内存 sink）；幂等账本不是持久化（进程内 `InMemoryIdempotencyStore`）；结构化 ThreadSummary 虽已落地并随 checkpoint 持久化，但 solidify 还没强制只消费其已确认字段，长会话噪声仍可能渗入；知识冲突虽然已有版本链和 conflicted 标记，但缺少自动冲突检测和置信度模型。

这些不是概念缺失，而是从原型走向生产时需要补齐的治理能力。

---

[← 返回索引 INDEX.md](INDEX.md)
