# Agent 能力设计：五个关键判断

> **能力设计不是十二项功能清单，而是五个可验证的边界：谁做语义决策、模型看见什么、动作如何治理、状态如何恢复、目标如何证明完成。** 每个机制只在本地可执行基线成立后引入。

## 1. 模型有语义提议权，没有事实所有权

```text
Context + capability/tool projection
  -> AgentTurnDecision
       |-> FinalMessage / Clarification / Limitation
       |-> ContinueTurn(ToolCallProposal / AgentDelegationProposal)
  -> Admission / Policy
  -> owner-based execution
  -> bounded Observation
  -> next turn or stop
```

**Agentic 的关键不是循环次数或是否先写 Plan，而是每轮只依据已提交输入，并让所有终止语义显式化。** 目标满足、需要用户输入、能力缺失、预算耗尽和执行失败不能都压成 `success=false`。

| 判断 | owner | 机械边界 |
| --- | --- | --- |
| 用户想完成什么、下一步语义动作 | 模型或用户 | typed Proposal，不直接写事实 |
| 当前身份能否看见/调用 | Policy / Application | scope、permission、exposure |
| 参数是否符合 schema 和冻结约束 | Admission | 接受或返回 typed feedback，不补业务语义 |
| 副作用是否发生 | 执行系统 | Event/Receipt/外部权威 |
| 目标语义是否满足 | Verifier | 不能推翻执行事实 |
| required result 是否齐全 | Completion Gate | 不把单个 Tool success 升级为完成 |

Structured output 只让字段和分支可机械解析，不证明模型选对了目标或 Tool。Provider Adapter 可以转换 wire protocol，不能创造缺失语义、权限或业务 payload。

## 2. Context 只注入当前允许且需要的信息

**Context engineering 的顺序是 Visibility → Requirement Retrieval → Semantic Selection → Budget Materialization。** 权限必须在召回和 Prompt 之前生效；把越权内容取回后再要求模型忽略，已经越界。

### 2.1 大 Observation 卸载与精确重读

```text
large Tool result
  -> resource owner 保存完整内容
  -> journal 提交 bounded Observation + ResourceRef + omitted metadata
  -> model decides whether/where to read
  -> read_action_output(ref, offset/range)
  -> bounded Observation
```

责任分开：模型判断证据是否充分和下一段读什么；Tool 校验 ref、scope、range 与单次上限；Runtime 限制总轮次和总预算。停止条件也不是只有 EOF：目标证据充分、资源耗尽、预算不足、能力失败或需要用户输入都能终止。

`CTX-001` 证明长 Conversation 在多个大结果和早期证据下仍保持有界 materialization，并能重读后回答；它不证明所有问题都能在固定页数内完成。完整机制见 [ADR 0013](../adr/0013-bounded-observation-and-offloaded-read.md)。

### 2.2 Personal Knowledge 与 Project context

- personal evidence 在 principal/scope 过滤后有界预取，作为 `personal_knowledge_context` Observation 进入同一 Conversation；
- linked Project 每轮预取有界 plan/progress projection，Conversation 不复制 accepted Plan；
- Artifact、Journal、Long-term Knowledge 和 Retrieval Index 保留目的不同，不合并成 God State。

这两个预取机制都是只读 materialization，不是第二事实源，也不能自动触发知识写入或 Project 状态推进。

## 3. Application Capability 与执行资源按 owner 分开

**Application Capability 表达用户可理解、可验收的业务动作；Tool、MCP、Agent 是实现目标时可选的执行资源。** Workflow 是 Capability 内的固定事务编排，Project 是拥有动态长期事实的 Aggregate。

| 模型可见动作 | 语义/事实 owner | 执行入口 |
| --- | --- | --- |
| 低风险只读 Tool / MCP | Tool/Provider contract | ToolGateway |
| 保存、删除、创建 Project 等 application action | 具体 Application / Aggregate | capability-specific Admission + Use Case |
| bounded sub-goal | parent goal + child run contract | AgentGateway |

模型侧可以统一编码为 callable schema；执行侧不能因此把 Application action 降成普通 Tool。否则 ToolGateway 会被迫拥有知识生命周期、订阅迁移或 Project plan version 等业务事实。

### 3.1 临时 projection 的价值与边界

模型只看到按 identity、scope、policy 和当前可用性生成的 action/schema projection。它有两个作用：控制不可见资源不进入 Context，统一模型调用协议。它**不拥有 capability definition、availability 或 revision 事实**；没有生产消费者的 revision/digest/cache 直接删除。

Tool 多也不自动需要两阶段 discovery。只有全量 schema 已由相同自然输入证明造成选择、token 或延迟失败，才准入候选发现和按需加载；否则 registry 搜索是提前设计。

### 3.2 Tool 可见、获准和健康是三个事实

MCP discovery 只说明远端声明 schema；本地 exposure mapping 决定模型是否看见，Policy/Admission 决定本次是否获准，Gateway 调用结果说明 Provider 是否可用。外部网页、文件和 Tool 输出都是不可信数据，不能借 Observation 获得新工具或覆盖系统控制。`GOV-001` 专门诊断这条“数据不能升级为控制权”的边界。

### 3.3 外部实现如何参考

**主流框架共享的是边界机制，不共享 `ApplicationCapability` 这个领域类名。**

| A 级坐标 | 可复核机制 | 本项目采用 / 不采用 |
| --- | --- | --- |
| OpenAI Agents SDK `running_agents`、`sessions` | 轻量 agent loop、tools、sessions、tracing、HITL | 采用 loop/tool/session 边界；不因此强制通用 Plan |
| LangGraph `checkpoint-postgres` | thread-scoped checkpoint 与 writes | 参考恢复隔离；领域事实继续由 Application/Aggregate 拥有 |
| Hermes `agent-loop.md`、`context-compressor.py` | session persistence、bounded tool loop、context 压缩与重读保护 | 采用真源保留和有界读取；不复制其全部 session/compression 拓扑 |

本地 baseline 回答“要不要做”，外部源码只帮助回答“最小机制怎么做”。

## 4. 治理只放在真实风险边界上

**Command、Grant 和 budget reservation 只服务确认、父子隔离或资源竞争等已证明边界，不作为所有 action 的通用包装。**

### 4.1 Command 与 digest

**只读、低风险、可安全重试的 ToolCall 直接执行；需要确认、跨请求恢复或不可安全重试的副作用才形成 immutable Command。**

```text
Proposal -> immutable Command -> Confirmation -> execute once -> Receipt
                         \-> CommandDigest binds frozen payload
```

一个 `CommandDigest` 的价值是让确认、journal 和执行机械引用同一冻结 payload；它不是身份、授权或成功证明。授权内容与最终执行相同时不拆双 digest。Command、Event、Receipt 也不机械成套创建，各自必须有审批、审计、恢复、重放或外部关联消费者。

### 4.2 Specialist 与父目标

子 Agent 接受 bounded sub-goal，返回 `AgentArtifact`；父 Runtime 仍整合、验证并完成父目标。Grant 限制 scope 和数据外发，stable submission key 防止重启重复提交，late artifact 在 cancel 后隔离。`L04` 证明远端 completed 不会自动完成父请求。

### 4.3 预算与并发

**预算是一份 interaction policy，而不是每层各自维护数字。** 模型轮次、Tool 调用和 Context/token 限制只有在约束不同成本或失败语义时才独立存在；没有独立消费者的参数合并或删除。

并发 batch 必须在执行前根据最新 usage 原子预留，不能让多个 action 都读取旧余额后各自通过。`RUN-001` 证明 cap 为 2 时三个同轮 proposal 最多执行两个，其余得到 typed budget outcome。预算耗尽返回 limitation/暂停/用户输入，不用确定性代码拼“差不多答案”。

## 5. Durable state 恢复已提交事实，不重算语义

| 生命周期 owner | 必须恢复 | 不允许重算 |
| --- | --- | --- |
| Conversation | committed inputs、Observation refs、usage、ProjectReference | 已提交 Tool/Agent action |
| Governed side effect | immutable Command、decision、Receipt | 已确认 payload、已发生副作用 |
| ResearchRun | run state、Digest、Delivery fact | 已发送 Delivery |
| InvestigationProject | definition、accepted Plan、journal、evidence、submission key | 冻结 SubGoal、已提交 child run |

**Checkpoint 不是 exactly-once 魔法。** 相同 digest 的技术重试可以复用；外部结果不确定时 reconcile；replay 不能再次让模型生成 Command。`DUR-001` 证明 Conversation Web 重启后 owner 能恢复读取且另一 principal 被拒绝；它不能外推所有 Provider crash window 已闭合。

`PLAN-001` 进一步证明 Conversation journal 只恢复 scoped ProjectReference，Project journal 继续拥有 plan/progress；两者不双写同一业务事实。

## 6. Knowledge、Verification 与 Completion 各自守边界

**知识写入、语义判断和完成证据属于三个 owner；把它们压成一个 `success` 会同时制造污染和错误完成。**

### 6.1 Grounded answer 不等于 memory write

```text
Ask  -> scoped evidence -> answer + citations -> no Claim write
Save -> explicit intent -> exact source/span -> confirmation when required -> Claim write
```

回答含有模型组织和推断，不能自动成为长期事实。纠错创建新 Claim 并用 supersede/conflict 关系连接旧 Claim，不覆盖 provenance。`ASK-001A`、`ASK-001B` 证明 personal-only 和 personal + official web 两条 Conversation 结果；`E08/E14` 证明 Ask 零写入与显式保存边界。

### 6.2 Execution、Verification、Completion 三分

| 阶段 | 回答的问题 | 事实例子 |
| --- | --- | --- |
| Execution | 动作是否真实执行 | ToolResult、Event、Receipt、Artifact |
| Semantic Verification | 结果是否满足 Goal | verdict、verified artifact ref |
| Completion | required result 是否齐全 | terminal outcome、CompletionReport |

Verifier 可以拒绝“已满足”的声明，不能推翻已发生删除或外部发送。Completion Gate 检查证据齐全，不重做开放语义判断。`L06` 覆盖 Runtime-owned verified draft；`IP01` 覆盖 Project 缺 coverage/evidence 时不得完成。

## 7. 可观测性解释失败，不制造事实

**Trace 应能区分未选择、准入拒绝、执行失败、验证失败和完成证据缺失。**

| 阶段 | 记录 | 不记录成什么 |
| --- | --- | --- |
| Proposal | action kind、proposal/model ref | 已执行 Event |
| Admission/Policy | effect、rule、scope、typed reason | 模糊 `failed` |
| Execution | attempt、outcome、artifact/receipt ref | 业务状态写入口 |
| Verification | criterion、verdict、verified ref | Receipt 的替代品 |
| Completion | required item、evidence/missing reason | Tool success 的别名 |

`OBS-001` 验证跨 principal 拒绝既不泄漏内容，又能通过同 run 的 typed policy/trace 定位为 scope 拒绝，而不是误诊为 Provider 空结果。Observability 是只读投影，不需要通用 observability domain。

## 8. 面试时只展开三步

**每个设计选择只回答三件事：**

1. 用户原来会遇到什么错误；
2. 哪个 owner 用什么不变量阻止它；
3. 哪条证据证明到哪里、不能外推什么。

避免“优秀 Agent 都这么做”“有 checkpoint 就 exactly-once”“Tool success 就完成”“用例通过就可发布”。准确证据与发布结论见[证据与发布](05-evidence-and-release.md)。
