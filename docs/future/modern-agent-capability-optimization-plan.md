# 现代 Agent 能力优化路线图

> 状态：目标路线图，尚未实施。本文定义当前系统相对现代优秀 Agent 的产品能力缺口、交付顺序
> 和目标证据，不拥有当前实现事实。当前事实以
> [当前核心架构](../summary/core-architecture-current-state.md)、
> [能力与发布基线](../summary/phase0-capability-release-baseline.md) 和对应 workflow 文档为准。
> Durable Investigation Project 的模型、状态和发布门禁仍由
> [专项目标设计](durable-investigation-project-design.md) 拥有，本文只引用其交付结果。

## 1. Goal / Current Incorrect Behavior / Expected User-visible Result

### 1.1 Goal

把当前已经存在的 Conversation、知识事实链、领域 Workflow、Tool/MCP/A2A、治理、恢复和
E2E 能力收敛成用户可感知的 Agent 闭环：

```text
自然语言目标
  -> 获取当前 scope 内的必要上下文
  -> 选择适用的读取、领域操作或 bounded specialist
  -> 根据 Observation 修订下一步
  -> 高风险或持久写入时暂停并请求确认
  -> 恢复后执行冻结 Command，且不重复副作用
  -> 验证 Answer/Artifact 和 required result
  -> 返回结果、证据、限制和执行 Receipt
```

第一条必须闭合的用户旅程是：

> 核对当前结论与我的已有知识；发现冲突时先向我说明，得到确认后再保存。处理中断后继续，
> 不能重复写入，也不能把未确认草稿或其他 workspace 内容写入长期知识。

这条纵切同时使用现有最有辨识度的能力：Artifact/Evidence/Claim 事实链、读取与保存分离、
开放语义决策、scope/Policy、不可变执行请求、Receipt、恢复和反事实 E2E。

### 1.2 Current Incorrect Behavior

当前不是某个单点算法错误，而是产品闭环不完整：

1. Conversation 可以直接回答、读取 Tool/MCP 和委托 Agent，但只加载 `public_agent` 能力；
2. `POST /api/workspace/solidify-conversation` 已能显式保存，Delete/Restore、Subscription 等
   领域 Workflow 也有专用入口；
3. 用户无法从同一个自然语言 Conversation 进入 scoped Application Capability、Pending
   Confirmation、Resume 和 Receipt Observation；
4. Investigation Project 的 durable runtime 已装配，但真实模型、真实 Provider、正式
   HTTP/worker 的 live release E2E 尚未闭环；
5. 每轮向模型注入全部 public Tool schema，能力规模扩大后会增加上下文成本和误选风险；
6. 当前定向 E2E 能证明若干路径在对应现场工作，但缺少同输入 baseline、重复运行方差和当前
   clean matching revision 的完整发布证据。

因此，当前系统可以分别展示“会理解”“会读取”“会治理写入”“会恢复长任务”，还不能证明
用户只表达一次目标后，Agent 能把这些能力组合成一件完整、可确认、可恢复和可验收的工作。

### 1.3 Expected User-visible Result

目标用户应能在一个明确的产品入口中观察到：

- Agent 主动检索当前 workspace 内与目标相关的知识和证据；
- Agent 区分已有事实、外部 Observation、推断和待保存草稿；
- 需要保存、删除、外发或高成本执行时，返回明确 target、payload 摘要、风险和确认请求；
- 用户可以确认、拒绝、补充约束或暂停，拒绝和确认前均无目标副作用；
- 进程或 worker 恢复后继续同一工作，已冻结输入、已执行副作用和已有 Receipt 不被重算；
- 最终返回可检查的 Answer/Artifact、引用、未满足项和必要 Receipt；
- 失败时明确处于 capability missing、authorization denied、execution failure、
  verification failure 或 completion failure，而不是生成相似替代结果。

关键反事实：

- “不要保存”“只分析”“先给草稿”不得产生 Claim 或其他长期知识；
- Tool `ok`、Agent `completed`、Artifact 存在和数据库新增记录不得单独完成用户目标；
- scope 不匹配、确认 digest 错误、能力缺失或验证未通过时不得静默降级；
- replay、恢复、重复回调和重复确认不得再次执行同一副作用；
- context retrieval、capability retrieval 和 verifier 不得成为新的事实写入口。

## 2. Business Expansion or Proven Constraint / Out of Scope

### 2.1 Business Expansion

本路线图只承认三个已经可以由用户结果描述的扩展：

1. **统一自然语言受治理操作**：用户无需切换到专用 API 才能完成明确保存等产品动作；
2. **真实动态长任务交付**：用户可创建、观察、steer、批准、恢复并验收一个 Investigation
   Project，而不只是证明状态机对象存在；
3. **能力规模化后的稳定选择与验证**：能力增加时，完成率、错误副作用、上下文成本和延迟仍
   有可执行证据。

### 2.2 External Reference, Not Requirement Owner

截至 2026-07-28，现代 Agent 产品和 runtime 的共同能力面包括：真实工作环境、Agent loop、
上下文管理、工具和 specialist 协作、Human-in-the-loop、暂停/恢复、steering、验证、trace
和 eval。参考：

- [OpenAI Agents SDK](https://developers.openai.com/api/docs/guides/agents)；
- [Claude Code Agent Loop](https://code.claude.com/docs/en/how-claude-code-works)；
- [Claude Code Best Practices](https://code.claude.com/docs/en/best-practices)。

这些外部系统只用于发现候选能力，不能成为本项目的需求 owner。任何新增 sandbox、computer
use、Agent team、自动反思、通用 Planner 或 memory mechanism，仍必须先用本项目 baseline
证明具体用户错误或约束。

### 2.3 Out of Scope

本路线图不授权：

- 把全部请求迁入 Investigation Project 或通用 Workflow；
- 恢复旧 `Task/GoalGraph/WorkingPlan` 主链；
- 为“像优秀 Agent”而引入通用 shell、computer use、浏览器控制或自治 Agent 团队；
- 让 Conversation 直接调用数据库、Repository 或 `workflow_activity`；
- 自动保存模型回答、Tool Observation、Agent Artifact 或检索摘要；
- 将所有读操作 Command 化、Event 化或 Receipt 化；
- 预建 capability marketplace、通用 DAG 编辑器或多模型 Router；
- 以更多模型轮次、更多 Tool 调用或更多 Agent 数量作为效果指标。

## 3. 当前差异化能力与真实缺口

| 现代 Agent 能力面 | 当前基础 | 是否已形成优势 | 主要缺口 |
| --- | --- | --- | --- |
| Goal-driven loop | typed Conversation loop、Observation、Feedback、预算和安全并发 | 工程基础较强，但不是独特优势 | 主要证据仍是一跳 Action -> Observation -> Final |
| Real environment | Workspace Knowledge、Artifact、GitHub/Notion MCP、Web、A2A | 领域读取有基础 | 缺少可组合的 Knowledge Workspace 操作面和统一写入口 |
| Context engineering | scope 过滤、ArtifactRef、sealed context、知识检索 | 事实边界清晰 | 全量 public schema 注入；缺 capability discovery、预算化 materialization 和质量对照 |
| Human-in-the-loop | 领域确认、Project approval/steering/cancel | 后端语义较强 | Conversation 未统一暴露 Pending Confirmation 和 Resume |
| Durable execution | Command/Receipt、worker queue、Project journal | 设计和 runtime 较强 | 普通 Interaction 是文件 journal；Project 缺 live release E2E |
| Specialist collaboration | AgentGateway、DelegationGrant、poll/cancel/stream、AgentArtifact | owner 边界清晰 | 当前 specialist 和组合场景少，尚无隔离工作区需求证据 |
| Verification | grounded Ask、interaction verifier、Project Completion Gate | Execution/Verification/Completion 分离是优势 | 普通目标的 verifier requirement 仍窄，缺任务级自动检查和 paired eval |
| Long-term knowledge | Artifact/Evidence/Claim/Relation lifecycle、可重建 retrieval projection | 当前最强的领域差异化 | 还没有通过统一 Agent 入口转化为用户闭环 |
| Evaluation | 自然 E2E、反事实、trace archive、release gate | 证据纪律是优势 | 当前完整矩阵未重跑；缺 baseline、方差和规模化 Golden Set |

路线图的目标不是补齐表中所有空格，而是先把已经突出的治理、知识和证据能力转化为一个正式
用户旅程。只有该 baseline 仍失败，才进入后续阶段。

## 4. Decision Ownership / Fact Owner and Write Path

| 决策或事实 | Canonical owner | 唯一入口或约束 |
| --- | --- | --- |
| 用户 Goal、是否需要更多 Observation、语义能力选择 | Conversation semantic model | typed Proposal；不产生权限或执行事实 |
| 当前用户可见能力 | identity/policy-aware capability projection | 先 visibility，再 requirement retrieval |
| Tool/Capability 是否存在、schema、scope、risk、budget | Admission / CapabilityGateway / ToolGateway | 只能接受或拒绝，不补业务 payload |
| 待保存内容和现有 Claim 的语义关系 | typed model proposal + evidence-aware verifier | 只引用 admitted Evidence/Claim ref |
| 长期知识 Artifact/Evidence/Claim | WorkspaceService ingestion transaction | 继续复用现有 solidify/capture canonical write path |
| 需要确认的执行请求 | 对应 Application Use Case / Domain Command | immutable payload + 一个 canonical digest |
| 用户确认或拒绝 | Confirmation boundary | 绑定 principal、scope、task/run 和 command digest |
| 实际执行结果 | Gateway / Executor Receipt | execution fact 不由模型或 verifier 改写 |
| Answer/Artifact 是否语义满足 | 对应 Verifier | 不改变 Execution Fact |
| 用户目标是否完成 | Conversation result contract 或 Project Completion Gate | required evidence/receipt 缺失时 fail closed |
| Interaction 恢复事实 | Interaction journal | Stage 1 必须先明确跨请求确认所需 durable owner |
| Investigation definition/Plan/SubGoal/Completion | InvestigationProject aggregate | 由专项目标设计拥有，不在本文复制模型 |
| Trace、eval、release eligibility | Observability / E2E catalog / release gate | 观测不能改变生产行为 |

Conversation 不得直接暴露 `capture_text`、Repository 或内部 Workflow activity。目标能力应是粗
粒度 Application Capability，例如“准备保存当前会话结论”；内部仍由现有 Workspace
Application Use Case 和 canonical ingestion path 完成写入。

## 5. Required Production Capabilities and Missing-capability Delivery

| 能力 | 当前状态 | 本路线图动作 | 生产消费者 | 失败语义 |
| --- | --- | --- | --- | --- |
| Conversation typed loop | 已有 | 保持，不新增通用 Plan | Conversation | budget/capability limitation |
| identity/policy-aware capabilities | 需扩展 | Stage 1 先投影一个 scoped Application Capability | semantic model + Admission | authorization denied / capability missing |
| Prepare/Confirm/Resume/Receipt Observation | 对话链缺失 | Stage 1 闭合 | 用户、Conversation、Workspace Use Case | confirmation required/rejected/expired |
| Workspace solidify canonical write | 已有专用 API | 复用，不创建第二写入口 | Workspace knowledge | validation/execution failure |
| distributed Interaction confirmation state | 缺失 | Stage 1 只保存恢复确认所必需事实 | Conversation resume | recovery/invariant failure |
| live Investigation delivery | runtime 已装配 | Stage 2 完成专项目标设计中的 live 门禁 | Project 用户和 worker | typed Project terminal failure |
| capability discovery/materialization | 缺失 | Stage 3 在规模证据后实现两阶段加载 | Conversation model context | no eligible capability |
| context compaction | 未证明需要扩展 | Stage 3 先测再决定 | 长 Interaction / Project | context budget limitation |
| task-specific executable verification | 部分已有 | Stage 4 从一个 Artifact/result contract 扩展 | Verifier / Completion Gate | verification/completion failure |
| generic sandbox/computer use | 无业务证据 | 不实施 | 无 | capability missing |
| dynamic Agent team | 无业务证据 | 不实施 | 无 | capability missing |

任何 Stage 不得只交付 Interface、DTO、Fake、Prompt 或 E2E 文件。缺失能力必须在同一 Stage
拥有生产装配、消费者、失败语义、contract test 和正式入口 E2E。

## 6. Simplest Baseline and Evidence of Insufficiency

### 6.1 Baseline A: 当前 Conversation

使用同一自然语言目标：

> 把刚才关于 SLO 的结论核对后保存下来；如果与我已有知识冲突，先告诉我，不要直接覆盖。

最简单 baseline 是当前 `POST /api/conversation/respond`。预期当前只能回答、读取或说明能力
限制，不能完成对话内确认和 canonical solidify。必须保存：

- 最终用户可见结果；
- Tool/Agent/Model 次数、token、延迟；
- Workspace Claim 写入前后差异；
- trace 中实际选择的 capability；
- 是否发生错误写入或相似能力 fallback。

### 6.2 Baseline B: 当前专用 solidify API

使用 `POST /api/workspace/solidify-conversation` 完成相同保存结果，记录其正确结果、调用成本和
已有不变量。Stage 1 不得降低该入口已有的用户 Claim 选择、scope 和 ingestion 语义。

Baseline A 证明统一 Agent 入口缺失；Baseline B 证明保存能力本身已存在，目标不是新建第二套
Save Agent 或 Capture Workflow。

### 6.3 Baseline C: 当前 Investigation diagnostic matrix

使用专项目标设计已登记的 LT diagnostic matrix，证明 Project 状态机、恢复、approval、
steering 和 Completion Gate 的现有基础。Stage 2 只补 live product evidence，不重新设计
Project aggregate，除非 live baseline 暴露明确不变量错误。

### 6.4 Paired Evaluation

每次引入新 Agent 机制，至少对比：

| 指标 | 必须记录 |
| --- | --- |
| 用户目标完成率 | required result contract 是否满足 |
| 错误副作用 | 未确认写入、跨 scope、重复写入、错误外发 |
| 语义错误 | 错选能力、错误引用、遗漏冲突、错误完成 |
| 模型成本 | turns、tokens、model/provider |
| 执行成本 | Tool/Agent calls、并发、重试 |
| 用户成本 | 确认次数、无效澄清、等待时间 |
| 恢复结果 | 是否复用冻结事实、是否重复副作用 |
| 稳定性 | 同输入多次运行的结果与方差 |

如果新机制不提高目标完成率或降低关键错误，只增加轮次、状态和延迟，则拒绝进入强制主链。

## 7. Delivery Roadmap

### Stage 0: 冻结 baseline 与 Golden Set

目标：在任何生产扩展前证明当前错误，并建立同输入对照。

交付：

1. 为“核对后保存”建立自然表达 Golden Set，覆盖明确保存、禁止保存、代词指代、冲突、
   scope denied、能力缺失、确认拒绝和 replay；
2. 实际执行 Baseline A/B，保存 trace、用户结果和反事实；
3. 明确 Stage 1 的复杂度预算和删除项；
4. 在 E2E catalog 登记目标 product evidence，测试可以先失败但不得 skip。

禁止只用内部 capability 名称或预期步骤提示模型。

### Stage 1: Conversation Governed Knowledge Action

目标：从 Conversation 打通一个且仅一个 scoped Application Capability：
“准备保存当前会话中用户明确要求保存的结论”。

目标链：

```text
Conversation message
  -> identity/policy-aware capability projection
  -> model proposes coarse Application Capability + explicit target intent
  -> deterministic admission
  -> Workspace Use Case prepares canonical candidate/Command
  -> Pending Confirmation returned to user
  -> user confirms same run/task and digest
  -> resume frozen Command
  -> existing solidify/ingestion write path
  -> Receipt Observation
  -> parent FinalMessage
```

最小新增：

- 一个粗粒度 scoped capability contract；
- Pending Confirmation/Resume 所需的最小 durable state；
- 对话响应中可恢复的 confirmation reference；
- 将现有 Workspace solidify result/receipt 转成 typed Observation 的 Adapter；
- 对应 Policy、contract test、E2E 和 trace 字段。

必须删除或关闭：

- 任何关键词 `if "保存" in message` 路由；
- Conversation 直接调用 `capture_text` 或 Repository 的旁路；
- 确认前写入、客户端覆盖 server payload、确认后重新调用模型生成保存内容；
- 为兼容而保留的新旧保存入口双写。专用 API 可以继续作为真实外部产品契约，但必须与
  Conversation 复用同一个 Application Use Case 和 canonical write path。

### Stage 2: Live Durable Investigation Closure

目标：把现有 Investigation runtime 从 diagnostic evidence 升级为用户可验收的 live product
capability。

只执行
[Durable Investigation Project 长任务能力交付设计](durable-investigation-project-design.md)
尚未满足的门禁：

- 正式 HTTP 创建、查询、steer、approve/cancel 入口；
- 独立 Web/worker 进程和真实 PostgreSQL；
- 真实 structured model；
- 场景需要的真实 GitHub、Notion、Web 和 A2A profile；
- 最终 generated Artifact、evidence coverage、limitation 和 Completion Gate；
- crash、late result、approval、replay 和 tenant isolation 反事实；
- 相对 Conversation 和固定 Workflow 的同输入 baseline。

Stage 2 不创建第二个 Project 模型、Plan、journal、Artifact owner 或通用 DurableTask。

### Stage 3: Capability and Context Engine

进入条件：Stage 1/2 通过后，实际 trace 证明全量 schema 注入造成上下文成本、误选或延迟问题。

目标管线：

```text
principal + scope
  -> Visibility filtering
  -> small visible capability summaries
  -> Requirement retrieval
  -> load selected full schemas / skill instructions
  -> semantic final selection
  -> budgeted context materialization
```

约束：

- visibility 必须先于 retrieval；
- retrieval 只能缩小候选集合，不能替模型决定开放语义；
- capability summary、full schema 和 availability observation 不得成为三个可写事实源；
- 大型 Artifact 继续使用 ref，不复制进 Agent State；
- compaction 只压缩可丢弃的 LLM Context，不覆盖 Command、Receipt、Evidence 或 Project
  journal；
- 只有第二种真实 materializer 需求出现后才抽取通用策略 registry。

### Stage 4: Executable Verification and Knowledge Workbench

进入条件：Stage 1/2 的错误分布证明“Action 已执行但结果质量不足”是主要失败来源。

先选择一个具体 required result contract，例如“带 Claim/Evidence diff 的知识核对报告”，交付：

- 已有 Claim、候选结论和 Evidence 的可检查 diff Artifact；
- citation/coverage、冲突、unsupported claim 和 scope 的机械检查；
- 模型 Verifier 只判断开放语义，不改变执行事实；
- 用户可以查看、修改或拒绝候选 Artifact；
- 最终保存绑定用户确认的候选版本和 digest；
- 文档或报告需要视觉质量时增加 render-and-inspect E2E。

这不是通用“反思 Agent”。只有验证结果被生产 Completion 或用户确认消费时才持久化相应
report/receipt。

### Conditional Stage 5: Broader Environment or Specialist Collaboration

只有 E2E 证明现有 Knowledge Workspace、MCP 和单 specialist 不能完成具体用户目标时，才选择
一个最小扩展：

- 新增一个真实、受 scope 约束的文档或浏览环境；
- 为两个需要隔离上下文的 specialist 提供 bounded workspace；
- 增加用户可观察的并行 progress 和 Artifact join。

必须先证明为什么现有 Tool、A2A AgentArtifact 或固定 Workflow 不够。第一项 E2E 通过前不创建
通用 sandbox abstraction、Agent team protocol、角色市场或自治协商。

## 8. Target E2E and Counterfactuals

### E2E MA-01: 核对后确认保存

```text
Persona: 已登录且拥有 workspace 写权限的知识工作者，只知道自己的目标和已有知识
Given: workspace 内已有一个与候选结论部分冲突且带 Evidence 的 Claim
When: 从正式 Conversation 入口说“核对刚才的结论，和已有知识冲突就先告诉我，确认后再保存”
Then: Agent 返回冲突、Evidence 和待确认候选；确认后用户可以检索到新 canonical Claim
And not: 确认前零写入；不覆盖旧 Claim；不保存 assistant 未被选中的内容；不跨 workspace
Path evidence: capability projection、Proposal、Admission、Command/digest、Confirmation、
               Workspace ingestion、Receipt Observation、FinalMessage
Allowed fakes: 不可控外部 Evidence Provider；Policy、模型语义选择、Workspace owner 和
               Completion 不得 Fake
Baseline: 当前 Conversation 与当前 solidify API 的同输入结果
Command: uv run pytest -q evals/e2e_quality/test_conversation_governed_knowledge_action.py
```

### E2E MA-02: 禁止保存与拒绝确认

```text
Persona: 同一用户
Given: workspace Claim 数量和 candidate conversation 已冻结
When: 分别表达“只分析，不要保存”和在 Pending Confirmation 后拒绝
Then: 返回分析或明确 rejected 终态
And not: 不创建 Artifact/Claim/Command execution Receipt，不通过相似 Tool 写入
```

### E2E MA-03: 恢复与 replay

```text
Persona: 已确认保存的用户
Given: Command 已冻结；在提交写入或 Receipt 返回边界注入进程终止
When: 通过正式 Conversation resume 入口恢复，并重复同一确认请求
Then: 返回同一执行结果和 Receipt
And not: 不重新调用模型生成 payload，不新增第二个 Claim，不执行第二次副作用
```

### E2E MA-04: Scope denied / capability unavailable

```text
Persona: 无目标 workspace 写权限的用户
Given: 目标知识只存在于其他 workspace，或 scoped capability 当前不可用
When: 从 Conversation 请求核对并保存
Then: 返回 typed authorization denied 或 capability missing
And not: 不泄漏其他 workspace Evidence，不回退到 capture_text、近似 Tool 或本地文件
```

### E2E MA-05: Live Investigation delivery

目标用例、反事实和命令由
[Durable Investigation Project 设计](durable-investigation-project-design.md#6-e2e-first)
拥有。本文只增加验收要求：同一用户目标必须与 Conversation 和固定 Workflow baseline 对照，
并报告完成率、错误副作用、模型轮次、token、延迟和恢复结果。

### E2E MA-06: Capability scale

```text
Persona: 只能看到部分 workspace/tenant capabilities 的用户
Given: registry 中存在大量不可见、语义相近和当前 unavailable 的能力
When: 运行保存、读取、研究、禁止写入等自然语言 Golden Set
Then: 只 materialize 当前可见且相关的少量完整 schema，并选择正确能力或直接回答
And not: 不在 visibility 前检索全部能力，不泄漏隐藏 capability，不以近似能力 fallback
Baseline: 全量 public schema 注入
```

## 9. Affected Modules and Dependency Direction

预期影响边界：

```text
Web Conversation DTO
  -> Conversation Application
     -> Capability Projection Port
     -> Governance/Confirmation Port
     -> existing Workspace Solidify Use Case
     -> Interaction Journal Port

Infrastructure Adapters
  -> implement Ports
  -> PostgreSQL / Gateway / Provider
```

依赖必须保持：

- Interface 只解析身份、scope、输入和 confirmation reference；
- Conversation 只协调 Proposal、Application Capability 和 Observation；
- Workspace Application/Domain 继续拥有保存语义和 canonical facts；
- Governance 不创建目标、候选知识或 payload；
- Adapter 不根据关键词选择业务流程；
- E2E/Trace 只观测，不改变生产选择和完成逻辑。

Stage 2、Stage 3 和 Stage 4 分别在需要时扩展已有 Project、Context 和 Verification 模块，不得
让 Conversation 成为新的 God Service。

## 10. Complexity Added, Removed and Rejected Alternatives

### 10.1 Complexity Budget

Stage 1 最多新增：

- 一个粗粒度 scoped Application Capability；
- 一套 Pending Confirmation/Resume contract；
- 一个必要的 durable confirmation owner/store；
- 一个复用现有 solidify Use Case 的 Adapter；
- 对应 Policy、E2E 和 trace 支持。

每新增一个 Model、状态、digest、表或 Port，实施文档必须说明独立 owner、生命周期、事务边界和
生产消费者。授权内容和最终执行内容相同时只使用一个 canonical command digest。

### 10.2 Removed Complexity

实施时同步删除：

- Conversation 与专用 API 之间重复的 payload 组装；
- 关键词保存/删除 Router；
- Prompt 中为了弥补 capability exposure 缺失而存在的业务硬编码；
- 无消费者的 capability projection、旧 Task/Control contract 和临时 fallback；
- 只为测试存在的兼容字段或双轨状态。

删除项必须以实际调用方搜索为准；当前不存在的旧路径不得为满足清单而先创建再删除。

### 10.3 Rejected Alternatives

| 方案 | 拒绝原因 |
| --- | --- |
| 所有请求统一进入 Project | 让短请求承担 durable 成本，并造成第二 Interaction owner |
| 模型直接调用 `capture_text` | 绕过 Application Capability、确认、scope 和 canonical write path |
| 关键词 Router 识别保存/删除 | 不能区分“不要保存”“解释保存”和真正执行 |
| 每个 Tool 都创建 Command/Event/Receipt | 读操作无对应恢复/审批消费者，增加空转状态 |
| 先建设通用 sandbox | 当前知识用户结果没有证明 shell/filesystem 是缺失能力 |
| 先建设 Agent team | 当前没有第二个同构 specialist 场景和收益 baseline |
| 自动把回答写入 Memory | 形成模型输出自我强化和事实污染 |
| 增加反思轮次 | 没有可执行 verifier 时只增加 token，不能证明结果正确 |

## 11. Delivery Order and Stop Conditions

严格顺序：

1. 执行并归档 Stage 0 baseline；
2. 仅实现 Stage 1 最小纵切，使 MA-01 至 MA-04 通过；
3. 对比结果无收益时停止，不进入 Stage 2/3/4；
4. 按专项目标设计闭合 Stage 2 live evidence；
5. 只有 trace 证明能力规模问题后实施 Stage 3；
6. 只有结果质量错误成为主要瓶颈后实施 Stage 4；
7. Conditional Stage 5 每次只准入一个由 E2E 证明的环境或协作扩展。

停止或退出条件：

- Stage 1 若不能复用现有 Workspace canonical write path，先解决 owner 冲突，不创建旁路；
- 无法机械证明 confirmation 与 frozen payload 绑定时 fail closed；
- 新机制的完成率、错误副作用、成本或恢复结果不优于 baseline 时移除；
- 某阶段落地后，将当前事实迁入 summary/workflow/API 文档，并从本文删除已完成设计；
- 全部目标落地或被拒绝后删除本文，不在末尾追加实施流水账。

## 12. Definition of Done

本路线图不能整体以“代码已存在”完成。每个 Stage 分别满足：

1. 业务目标、反事实和 Out of Scope 未被扩大；
2. baseline 已用相同自然输入实际执行并归档；
3. 缺失生产能力有 owner、唯一入口、消费者、失败语义和真实装配；
4. 不存在第二知识写入口、payload 双写、双 digest 或隐藏 fallback；
5. 正式入口 E2E 通过用户结果、反事实、恢复或拒绝场景；
6. Unit、Contract、Integration、Golden Set、lint/type/layer checks 按风险实际执行；
7. paired evaluation 记录完成率、副作用、turns、tokens、latency 和方差；
8. release archive、catalog、commit、clean worktree 和 checksum 匹配后才声明发布资格；
9. 当前事实迁入 canonical 文档，已完成 Stage 从本文移除；
10. 净新增复杂度小于被删除或被证明必要的复杂度。

最先应交付的不是“更通用的 Agent”，而是一个用户可以从自然语言入口完整验收的受治理知识
动作。只有这条纵切证明现有架构不足，后续环境、上下文、验证和协作能力才获得准入资格。
