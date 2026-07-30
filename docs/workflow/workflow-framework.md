# 历史设计：Governed Procedure 与 Step Projection

> 状态：本文混合了已删除的 Task/GoalGraph 总主链与仍存在的领域 Procedure 概念，不再是当前
> 权威文档。固定事务当前由明确 Application Use Case/领域状态机拥有，普通 Conversation 由
> `ConversationService` 拥有；当前事实见
> [personalAgent 当前核心架构](../summary/core-architecture-current-state.md)。

## 定位

系统只有一个顶层控制器：Observation 驱动的 Executive Loop。`ProcedureSpec / ProcedureCatalog` 只保护稳定、可审计的事务状态机，不识别原始文本，也不承担请求分类。

```text
TaskAnalyzer
  -> GoalGraphCompiler
  -> Executive
       open goal   -> BoundedAction / Delegate
       stable tx   -> ProcedureCall
                       -> ProcedureMaterializer
                       -> ExecutionStep projection
  -> Observation
  -> GoalVerifier / CompletionVerifier
```

Ask、direct response 和普通分析由开放循环逐轮决定。MCP、本地工具、retriever 和 A2A Agent 是 Capability provider，不是 Procedure；Resolution 在 dispatch 前绑定具体 provider。

## 核心对象

| 对象 | 职责 |
| --- | --- |
| `ProcedureSpec` | 版本化声明 node、依赖、条件边、风险、HITL、恢复、输入输出和不变量 |
| `ProcedureCatalog` | 保存受验证 spec；只按明确 procedure identity 查询 |
| `ProcedureApplicabilityResolver` | 根据结构化 Goal、资源、operation 和副作用判断 mandatory/eligible/ineligible |
| `ProcedureMaterializer` | 将已批准的 `ProcedureCall` 物化为 `ProcedureInstance + ExecutionStep` |
| `ProcedureSpecValidator` | 声明期校验 identity、依赖 DAG、条件边和 capability requirement |
| `StepProjectionValidator` | dispatch 前校验当前工具 schema、动态参数、risk 和 confirmation |
| `ProcedureRuntime` | 启动实例并投影 procedure event，不决定任务语义 |
| `ActionExecutionGraph` | 执行当前 BoundedAction 或 Procedure nodes |

## 当前 Procedure

| Procedure | 保护的不变量 |
| --- | --- |
| `knowledge_ingest` | 来源规范化、确认、durable admission、receipt |
| `knowledge_consolidate` | provenance、supersession、receipt |
| `research_run` | budget、evidence loop、checkpoint、verification |
| `research_subscription_create` | schedule、idempotency、audit |

GitHub、Notion 和 GPT Researcher 不在 Catalog。前两者是 MCP capability，后者是 A2A Agent capability。

知识删除/恢复也不在 Catalog：其输入已经是 canonical target，后续是固定的
确认与事务状态机，由 `KnowledgeLifecycleService` 直接拥有。为它再投影
Procedure/ExecutionStep 会形成重复状态机，详见
[Knowledge Delete / Restore Workflow](delete-knowledge-workflow.md)。

## 选择与物化

TaskAnalyzer 只输出 provider-neutral Goal、ResourceHint 和 GoalRelation。GoalGraphCompiler 生成 `TaskContract`、criterion、mutation intent 与初始 runtime。ProcedureApplicabilityResolver 只读取 materialized Goal 和结构化资源事实：

- mandatory candidate 不可被开放动作绕过；
- eligible candidate 由 Executive 决定是否调用；
- ineligible candidate 不进入 LegalAffordance；
- 未知 procedure 不降级到通用流程。

Executive 产生 `InvokeProcedureDecision` Proposal 后，Decision Admission 校验 Goal ownership、mutation、预算和 mandatory constraint，并编译 `AcceptedControlCommand`。Materializer 再为每个 node 生成带 procedure identity 的 invocation；每个 node 在 dispatch 前获得精确 `ProcedureNodeGrant`。这个过程不读取自然语言猜依赖。

## 执行边界

Procedure node 与开放 BoundedAction 共用 `Decision -> Resolution -> Dispatch`：

1. Resolution 生成 capability binding、resource access plan 和 ContextProjection。
2. Scheduler 校验 resolved read/write set。
3. ToolGateway 或 AgentGateway 执行具体 provider。
4. 输出先成为 artifact/Observation，再由 GoalVerifier 判断 criterion coverage。

局部 ReAct 只能使用 Resolution 提供的 allow-list 和迭代预算。它不能修改 GoalGraph、调用未解析 provider 或宣布任务完成。

## HITL 与恢复

需要确认的 node 通过 LangGraph interrupt 暂停，payload 与 run 状态持久化。确认只授权绑定的具体 operation；成功必须产生可验证 receipt。Procedure branch/recovery policy 只处理其内部事务状态，普通语义替代策略回到 Executive。

PostgreSQL DurableRun repository 保存 run、submission binding 和 lease；revision CAS 与 fencing token 防止旧 worker 写入。重复 mutation 继续由 Gateway 幂等账本约束。

## 评测

Procedure 定义和物化由 planning/platform tests 覆盖；Task Analysis、Executive、Capability resolution、HITL/replay 和最终完成质量分别由对应 suite 负责。E2E 只在真实调用 Procedure 时断言 `procedure_id`，开放 Goal 不伪造 Procedure identity。
