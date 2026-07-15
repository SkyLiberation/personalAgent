# Procedure / Step Projection 层

### 1. 当前 planning 如何落地？

开放任务不是预先选择固定流程。TaskAnalyzer 输出 Goal、资源提示和 typed relation；GoalGraphCompiler 生成 TaskSpec 与 Ledger；Executive 根据 Observation 逐轮选择 BoundedAction、Delegate、Procedure、计划修订或完成提案。

稳定事务由 ProcedureSpec 声明内部节点。ProcedureMaterializer 只物化已被 Executive 选择且通过 Validator 的 ProcedureCall，不理解自然语言，也不为开放任务生成 DAG。

### 2. ProcedureSpec / ProcedureCatalog 解决什么？

它们集中保护知识写入、删除、对话固化、知识整理、研究运行和订阅创建的不变量：依赖、风险、HITL、幂等、receipt、恢复和条件边。ProcedureApplicabilityResolver 只读取结构化 Goal/Resource/operation，不按原始文本路由。

```text
Executive decision
  -> DecisionValidator
  -> ProcedureMaterializer
  -> ExecutionStep
  -> Resolution
  -> StepProjectionValidator
  -> ToolGateway / AgentGateway / HITL
  -> Observation
  -> GoalVerifier
```

### 3. Step projection 和 Todo list 有什么区别？

Todo list 是展示文本；ExecutionStep 是 checkpoint-safe dispatch unit，携带依赖、风险、output contract、capability requirement、procedure provenance 和恢复策略。StepRunState 保存运行状态、artifact ref、失败原因和重试次数。

### 4. 哪些任务进入 Procedure？

只有稳定事务进入 Procedure。Ask、direct response、普通分析、MCP 和 A2A provider 不在 Catalog：Ask 由 Executive 逐轮组合 acquire/reason/verify，MCP/A2A 由 CapabilityResolver 在 Resolution 阶段绑定。

### 5. 删除为什么需要 `retrieve -> resolve -> delete -> receipt`？

删除目标必须来自真实候选，不能由模型编造 note id。resolve 只能从已检索候选中选择；不明确时澄清。删除前通过 HITL 绑定 exact target，提交后产生删除快照和 receipt，最后仍由 verifier 判断 Goal 是否完成。

### 6. StepProjectionValidator 防什么？

它在 dispatch 前校验工具是否注册、参数 schema、动态参数来源、risk/confirmation、ReAct allow-list 和迭代预算。ProcedureSpecValidator 更早校验 node identity、依赖 DAG、条件边和 capability requirement。两者分别保护声明和运行投影。

### 7. ReAct 能替代 Procedure 或 Executive 吗？

不能。ReAct 只是一个 BoundedAction 内的局部探索策略，只能消费已解析 allow-list。它不能修改 GoalGraph、扩大权限、选择未解析 provider、提交未确认 mutation 或宣布任务完成。

### 8. 这套设计为什么更 Agentic？

模型持续拥有语义策略选择权，Runtime 只强制合法性、安全、资源、状态和完成门禁。固定 Procedure 没有消失，但从“任务类别”降为 Executive 可调用的事务能力，因此不会把未知问题硬塞进几个 workflow。

---

[← 返回索引 INDEX.md](INDEX.md)
