# 项目面试总结

## 一分钟版本

这是一个面向个人知识工作的 Agent Runtime。它不是靠 Router 把请求塞进几个固定 workflow，而是由 Task Analyzer 形成 Goal Graph，Executive 根据每轮 Observation 选择下一动作，CapabilityResolver 动态绑定 native、MCP 或 A2A 实现，Protocol 只承载写入、删除、Research lifecycle 等稳定事务。模型负责语义决策，确定性系统负责权限、依赖图、副作用、HITL、事件投影和完成验证。

## 主链路

```text
EntryInput
  -> TaskAnalyzer: Goal + GoalRelation + ResourceHint
  -> GoalGraphCompiler: TaskSpec + ExecutionLedger
  -> Executive: one ControlDecision
  -> Decision/Patch validation
  -> BoundedAction / Delegate / ProcedureCall
  -> Observation
  -> GoalVerifier
  -> Executive again
  -> CompletionVerifier
  -> EntryResult
```

Task Analyzer 不判断 capability coverage，也不选择工具。`intent_hint` 是开放语义提示；只有精确命中 Protocol Registry 时才形成 Protocol Goal。

## 为什么 Agentic

Agentic 体现在控制会被反馈改变，而不是“用了 ReAct”：

- Executive 每轮看到完整 ready Goal、Ledger、Observation、Skill、Macro、capability class 和剩余预算；
- 初始 inferred dependency 可被新 Observation 受控修订；
- MCP/A2A 是动态 provider，不是固定入口 workflow；
- 失败被归一为 Observation，可触发换能力、澄清、委派、修订或停止；
- action success 不等于 Goal success，必须经过 criterion-specific verification；
- Task 完成还要通过 CompletionVerifier。

模型不能直接修改 Ledger、扩大 scope、绕过确认、执行未声明副作用或宣布完成。

## 核心分层

| 层 | 责任 |
| --- | --- |
| Entry | Web、CLI、飞书输入归一与 guard |
| Task Analysis | 目标、关系、资源与澄清 |
| Goal Graph | 编译 TaskSpec、criterion、mutation intent 和初始 Ledger |
| Executive | 选择 Goal、元能力、Skill/Macro、委派、Protocol 或图修订 |
| Capability | requirement 到 native/MCP/A2A 的 eligibility、coverage 和 rank |
| Action Executor | 当前有界动作、局部 ReAct 和 artifact 产出 |
| Protocol | 稳定事务、HITL、幂等、admission、receipt |
| Verification | Goal criterion 与 Task completion 独占判定 |
| Runtime | LangGraph checkpoint、interrupt/resume、事件与 SSE |

## MCP 与 A2A

MCP capability 和 native tool 进入统一 Registry。Resolver 先做硬 eligibility/policy/scope/provider binding，再做 lexicographic rank；调用仍经过 ToolGateway。

A2A 只在 Executive 选择 `delegate` 后参与。主 Agent 发送最小 `SubtaskSpec`，AgentGateway 管生命周期和数据边界，返回 artifact 默认 unverified。主 Agent 保留上下文、交叉验证和最终回答所有权。

## Executive 与 Procedure

Ask、direct response、GitHub/Notion provider 和 GPT Researcher 都不是 Procedure。Executive 根据 Observation 选择开放动作、委派或稳定事务；ProcedureMaterializer 只物化已经批准的 ProcedureCall，不理解自然语言或推断任务依赖。mutation、HITL 和 receipt 不变量以 ProcedureSpec 为事实源。

## 记忆与证据

LangGraph checkpoint 保存短期执行现场；Postgres/Workspace 保存长期 Artifact、Evidence、Claim、Decision 和 lifecycle；Graphiti 是语义索引而不是事实真源。外部工具和 A2A 产物先作为带 provenance 的 Observation，经 ContextAdmission 和 verifier 后才能支撑结论或进入长期知识。

## 工程保障

- `DecisionValidator`：控制决策、依赖、预算、并行和副作用；
- `LedgerPatchValidator`：计划修订、关系可变性和图不变式；
- `ToolGateway/AgentGateway`：scope、policy、audit、幂等与 provider boundary；
- `GoalVerifier/CompletionVerifier`：证据、receipt 和完成条件；
- LangGraph/PostgresSaver：checkpoint 与 HITL resume；
- Golden suites：Task Analysis、Goal/Executive、Protocol、Capability、RAG、E2E 和 Conversation 分层归因。

## 设计取舍

项目没有使用无约束的全局 autonomous loop，也没有退回 workflow-first。开放任务使用 incremental deliberation，稳定事务使用 deterministic Protocol。这样既保留模型对目标、证据缺口和下一动作的智能判断，也让权限、状态和完成语义可验证、可恢复、可审计。
