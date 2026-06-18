# Multi-Agent 设计方案

本文设计一个**不考虑向后兼容**的目标形态:在当前确定性 workflow 骨架内,把若干 step 的实现从"函数 / 单 ReAct 循环"升级为"role-based sub-agent 编排"。

这不是引入一个自主 agent swarm。它是一个**受控的、checkpoint-safe 的、工具治理统一的 multi-agent 层**,嵌在现有 `StepExecutionGraph` 之内。

平台化见 [Workflow 平台化优化设计](workflow-platform-optimization.md),RAG 质量见 [Capture / Ask RAG 质量优化设计](rag-quality-optimization.md)。本文与两者正交,只回答一个问题:**哪些节点值得 agent 化,如何在不推翻确定性骨架的前提下做到。**

## 设计哲学:确定性骨架 + agent 化节点

当前架构(见 [Entry / Checkpoint / 输出整体流程](../workflow/entry-router-plan-react-output-flow.md))刻意反"全局自主 agent loop":

- `WorkflowStepProjector` 确定性投影拓扑,不让 LLM 生成流程。
- ReAct 只嵌在某个 step 内,只给只读工具。
- 所有工具调用下沉 `ToolGateway`,统一权限 / timeout / retry / HITL / 幂等 / 审计。
- 中间态进 `AgentGraphState` / `AskRunContext` artifact,run 可恢复、可重放。

本方案**继承全部约束**,只在一个维度上扩展:把"单个 step 内部的实现"从单一函数或单 agent,扩展为**多个有明确角色的 sub-agent 协作**。

```text
不变 (确定性骨架):
  Router -> WorkflowStepProjector -> StepExecutionGraph -> ToolGateway -> Checkpoint

可变 (step 内部实现):
  单函数 / 单 ReAct  ==>  orchestrator + workers / generator + critic + judge
```

三条不可逾越的边界:

1. **agent 不能绕过 ToolGateway**。任何 sub-agent 的工具调用仍走 gateway,受同一套治理。
2. **agent 不能自主改写流程拓扑**。编排权留在确定性 `StepExecutionGraph`,agent 只在分配给它的 step 内活动,不能自主 spawn 新 step 或互相委派到骨架之外。
3. **agent 中间态必须进 checkpoint / artifact**。不允许 checkpoint 之外的隐藏对话状态,否则恢复 / 重放失效。

## ROI 分级:不是所有节点都该 agent 化

multi-agent 在本工程的收益高度不均。诚实排序如下,实施按此优先级:

| 接入点 | agent 化收益 | 原因 | 优先级 |
| --- | --- | --- | --- |
| **verify** → generator / critic / judge | **高,质变** | 对抗性验证、反证、裁定是 multi-agent 不可替代的能力,直接降幻觉、提 grounding | P0 |
| **retrieve** → orchestrator / worker | **中,边际** | 六路并行 + RRF 融合已拿走大部分收益,agent 化只多了"自适应子查询",延迟 / token 成本高 | P1 |
| **capture enrich** → 并行抽取 agent | **低,几乎为零** | 实体 / 日期 / 作者抽取是结构化任务,好 prompt + 并行调用即可,不需要 agent 协作 | 不做 |

核心判断:**multi-agent 最值钱的"并行召回 + 融合"你已经用确定性 coordinator 实现了。剩下唯一不可替代的是"对抗性验证"。** 因此 P0 是 verify,P1 是 retrieve,enrich 明确不做。

## 目标架构

```text
ask-verify (P0)  ── VerifyAgentTeam subgraph
  GeneratorAgent   出答案 (基于 ContextPack)
    -> CriticAgent    逐 claim 找反证 / 漏洞, 可申请反证检索 (经 ToolGateway)
    -> JudgeAgent     裁定 entailed / contradicted / insufficient
    -> 聚合 VerificationReport -> retry / web fallback / 标注不确定

ask-retrieve (P1) ── RetrieveAgentTeam subgraph
  OrchestratorAgent  拆解检索意图, 分发给 workers, 决定是否追查
    -> RetrieverWorker[graph/local/structural/web/...]  (现有六路, 受控只读)
    -> 自适应 sub-query (worker 反馈不足时 orchestrator 追加)
    -> EvidenceFusion (RRF, 复用 rag-quality 设计)

骨架不变:
  StepExecutionGraph -> execute_step -> {VerifyAgentTeam | RetrieveAgentTeam} subgraph
  所有 tool 调用 -> ToolGateway
  所有中间态 -> AskRunContext artifact / checkpoint
```

每个 AgentTeam 是一个 LangGraph subgraph,作为某个 step 的 `execution_mode="agent_team"` 实现,与现有 `execution_mode="react"` 平级。

## P0:VerifyAgentTeam(generator-critic-judge)

这是 ROI 最高、唯一不可替代的接入点。落在现有 `AnswerVerifier` 接口内,替换实现。

### 角色

```text
GeneratorAgent
  输入: question + ContextPack
  输出: 答案草稿, 每句带 candidate citation
  约束: 只能引用 ContextPack 内证据, 不得引入外部知识

CriticAgent (对抗性)
  输入: 答案草稿 + ContextPack
  职责: 逐 claim 找反证 / 过度断言 / 证据不足 / 引用错配
  工具: 可申请反证检索 (contrastive retrieval), 经 ToolGateway, 只读
  输出: list[Critique{claim, issue_type, counter_evidence?}]

JudgeAgent (裁决)
  输入: 草稿 + critiques + ContextPack
  职责: 对每个 claim 裁定 entailed / contradicted / insufficient
  输出: VerificationReport{claims:[{text, verdict, citations}], overall}
```

### 子图流程

```text
START
  -> verify_init        (从 AskRunContext 取 ContextPack + answer)
  -> generator_node     (出/复用草稿)
  -> critic_node        (找反证, 可触发 ToolGateway 反证检索)
  -> judge_node         (裁定, 产出 VerificationReport)
  -> aggregate
       overall=pass        -> 写回 ctx, END
       contradicted        -> retry (回 generator, 注入 critique) 或 web fallback
       insufficient        -> 触发反证检索 / web, 不足则标注不确定
  -> END
```

### 为什么是 multi-agent 而非单 verifier

单 verifier 同时扮演"生成者"和"挑错者",存在确认偏差——它倾向于认可自己刚生成的内容。把 critic 拆成独立 agent、独立 prompt、独立对抗目标,才能稳定产出反证。judge 再独立裁决,避免 critic 过度否定。三角色分离是这个收益的本质来源,不是结构花哨。

### 治理边界

- critic 的反证检索**必须经 ToolGateway**,与主检索同一套权限 / 审计。
- generator / critic / judge 的每轮输出**进 `AskRunContext` artifact**,`VerificationReport` 进 step result,checkpoint 可恢复。
- 整个 team 仍是 `ask-verify` 这**一个 step** 的内部实现,对骨架不可见。
- 迭代次数受 step `max_iterations` + 全局 cap 限制,防止 generator↔critic 死循环。

## P1:RetrieveAgentTeam(orchestrator-worker)

收益边际(确定性 coordinator 已拿走大部分),仅在 P0 验证成功后再做。落在现有 `Retriever` / `RetrievalCoordinator` 结构内。

### 与现状的差异

当前 `RetrievalCoordinator` 是确定性的:按 `RetrievalPlan` 固定分发六路、固定融合。agent 化只改两点:

```text
OrchestratorAgent (取代固定 plan 执行)
  -> 动态决定本轮派哪几个 worker、用什么子查询
  -> 看 worker 回传的证据质量, 决定是否追加子查询 / 换源 / 停止
  -> 收敛条件: 证据充分 或 达到轮次上限

RetrieverWorker (现有六路, 基本不变)
  -> 仍是受控只读召回, 仍归一成 EvidenceItem
  -> 仅增加: 向 orchestrator 回传 "本路是否还有空间深挖" 的信号
```

### 克制原则

- worker **不变成自由 LLM agent**,仍是确定性召回函数 + 一个质量自评。只有 orchestrator 是 LLM。这样把 agent 化成本压到一个节点,保留并行召回的低延迟。
- 默认仍走确定性单轮;只有 `understanding.needs_graph_reasoning` 或证据明显不足时才进 orchestrator 多轮模式。avoid paying agent latency on simple queries。
- 多轮上限严格 cap,RRF 融合复用 [rag-quality 第 4 节](rag-quality-optimization.md) 设计。

## Agent 运行时契约

所有 sub-agent 共享一个统一契约,避免每个 team 各写一套:

```text
AgentRole
  name              # generator / critic / judge / orchestrator / worker
  model             # 可按角色配不同模型 (critic 可用更强模型)
  system_prompt
  allowed_tools     # 经 ToolGateway 的工具子集, 默认只读
  output_schema     # 结构化输出 (Critique / VerificationReport / ...)
  max_turns

AgentTeamState (checkpoint-safe, 进 artifact)
  team_id / step_id / run_id
  transcript: list[AgentTurn]   # 每个 agent 的输入/输出, 可重放
  shared_context_ref            # 指向 AskRunContext artifact, 不复制大对象
  status / iteration
```

`transcript` 是 team 的事件历史,既供 checkpoint 恢复,也供离线 eval 回放(对齐 rag-quality 第 8 节)。

## 数据模型改动

不考虑兼容,目标态直接重建:

```text
ExecutionStep
  + execution_mode: "direct" | "react" | "agent_team"   # 新增 agent_team
  + agent_team_spec: AgentTeamSpec | None

AgentTeamSpec
  roles: list[AgentRole]
  topology: "generator_critic_judge" | "orchestrator_worker"
  max_iterations: int

AskRunContext
  + verify_team_state: AgentTeamState | None
  + retrieve_team_state: AgentTeamState | None

VerificationReport (复用 rag-quality 第 7 节)
  claims: list[{text, verdict, citations}]
  critiques: list[Critique]
  overall: pass | needs_fix | uncertain
```

新增事件类型(进 `AgentEvent`,对齐现有事件流):`agent_team_started`、`agent_turn`、`critique_raised`、`verdict_emitted`、`agent_team_completed`。前端可展示 agent 协作过程。

## 框架选择:就用 LangGraph,不引外部框架

明确不引入 AutoGen / CrewAI / OpenAI Swarm(Agents SDK):

| 框架 | 不选的原因 |
| --- | --- |
| AutoGen / CrewAI / Swarm | 假设 agent 自主对话 / 委派 / 决定流程;其状态不按本工程 checkpoint 建模,run 中断无法用 `resume(Command)` 恢复;让 agent 直接持有 tool,绕过 ToolGateway。三点都与本工程命脉对冲。 |
| **LangGraph (已在用)** | 官方 multi-agent 即 subgraph + Command/handoff,与现有 ReAct 子图、StepExecutionGraph 同一套原语。AgentTeam 直接实现成 subgraph,工具下沉 ToolGateway,状态进现有 checkpoint。零新框架。 |

结论:**multi-agent 不需要"引入"框架,需要的框架就是已经在用的 LangGraph。** 引入第二套并行运行时是纯负收益——重复能力、对冲治理、破坏恢复,与本仓 [不引入 LlamaIndex 的判断](rag-quality-optimization.md) 同源。

## 分期

1. **P0 VerifyAgentTeam**:generator-critic-judge subgraph,落在 `AnswerVerifier` 接口,产出 `VerificationReport`。先拿质变收益。
2. **eval 接入**:用 `transcript` 回放,对比单 verifier 基线,量化幻觉率 / grounding 提升。收益不达标则停在 P0。
3. **P1 RetrieveAgentTeam**:仅在 P0 验证 multi-agent 编排基础设施可靠后,再做 orchestrator-worker,且默认仅对复杂 query 启用。

每期都必须先过 eval gate 才扩大范围。

## 非目标

- **不做自主 agent swarm**:不允许 agent 之间在骨架之外自由对话、互相 spawn、自主改写流程。编排权永远在确定性 `StepExecutionGraph`。
- **不引入外部 multi-agent 框架**:AutoGen / CrewAI / Swarm 与 checkpoint-safe + ToolGateway 治理对冲,一律不接。
- **不 agent 化结构化任务**:capture enrich / provenance 抽取用好 prompt + 并行调用,不套 multi-agent。
- **不让 agent 绕过工具治理 / HITL / 审计**:所有工具调用经 ToolGateway,高风险仍触发 HITL interrupt。
- **不追求 agent 数量**:agent 化只在"对抗性验证"这类多视角不可替代处发生,其余保持确定性。
