# 现代 Agent 能力优化路线图

> 状态：历史混合路线图。Stage 1 exact-span 保存与 Stage 2 IP01 已落地，当前事实已迁入
> summary/ADR；Stage 3–5 尚未取得各自正式入口 baseline，不能据此实施。剩余收敛与候选准入的
> 唯一 active owner 是
> [可信 Agent Runtime 演进与收敛](trusted-agent-runtime-evolution.md)。
>
> 原状态记录：Stage 1 的最小“从同一 user message 选择精确知识 span、确认后保存”纵切已由
> B02 -> E14 定向通过；冲突核对、assistant candidate 保存及其他 governed action 尚未准入。本文只拥有
> 未完成目标和交付顺序，当前实现事实以
> [当前核心架构](../summary/core-architecture-current-state.md)、
> [能力与发布基线](../summary/phase0-capability-release-baseline.md) 和对应 workflow 文档为准。
> Durable Investigation Project 的模型、状态和发布门禁仍由
> [专项目标设计](durable-investigation-project-design.md) 拥有，本文只引用其交付结果。
> Stage 1 仍仅由 ADR 0006 的临时实验例外保留至 2026-08-28，尚不满足合并门禁；到期前未
> 收敛净复杂度并取得 clean release evidence 时必须删除。
> Stage 2 的 B03 failing baseline 与 IP01 target 已闭环；IP01 archive
> `20260729T101501.732689Z-53628-6c5f02f2` 已从正式 HTTP/worker 交付 verified report。
> 完整 live capability matrix、paired baseline 和重复运行方差仍是发布门禁；不得把单一
> IP01 通过外推为整个 Investigation 产品可发布。

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

下一条候选用户旅程是：

> 核对当前结论与我的已有知识；发现冲突时先向我说明，得到确认后再保存。处理中断后继续，
> 不能重复写入，也不能把未确认草稿或其他 workspace 内容写入长期知识。

这条纵切同时使用现有最有辨识度的能力：Artifact/Evidence/Claim 事实链、读取与保存分离、
开放语义决策、scope/Policy、不可变执行请求、Receipt、恢复和反事实 E2E。

### 1.2 Current Incorrect Behavior

当前不是某个单点算法错误，而是更丰富的产品闭环仍不完整：

1. Conversation 可以直接回答、读取 Tool/MCP、委托 Agent，并准备确认后保存 user message
   中由模型逐字选择且经 Admission 校验的知识 span；
2. `POST /api/workspace/solidify-conversation` 已能显式保存，Delete/Restore、Subscription 等
   领域 Workflow 也有专用入口；
3. B02 -> E14 已证明显式 exact-span save 可进入 Pending Confirmation、恢复、精确 Claim、
   Receipt 和 replay，且保存/确认控制语义不进入 Claim；
   保存 assistant candidate、先核对冲突再保存、删除和订阅变更仍未贯通；
4. Investigation Project 的 durable runtime、正式 HTTP/worker 和 live B03/IP01 harness 已
   装配；B03 已证明 verification repair 会死锁，修复后 IP01 又证明同反馈重规划曾无限循环，
   两者已由 conformance 回归闭合，IP01 最终 live report 已交付；完整 capability matrix 未闭合；
5. 每轮向模型注入全部 public Tool schema，能力规模扩大后会增加上下文成本和误选风险；
6. 当前定向 E2E 能证明若干路径在对应现场工作，但缺少同输入 baseline、重复运行方差和当前
   clean matching revision 的完整发布证据。

因此当前已经有一个自然语言 governed write 的完整样本，但不能从一个样本外推到所有写操作，
也不能声称路线图开头的“核对冲突后保存”复合目标已经完成。

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
| Durable execution | Command/Receipt、worker queue、Project journal | verification repair 保留冻结执行、按 lineage 隔离证据且局部反馈有界；IP01 已通过 | 普通 Interaction 仍是文件 journal；完整 live matrix 未闭环 |
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
| identity/policy-aware capabilities | 部分已有 | 已投影一个 save Application Capability；其他能力必须重新走 baseline | semantic model + Admission | authorization denied / capability missing |
| Prepare/Confirm/Resume/Receipt Observation | save 已闭合 | 只在新失败证据下扩展其他 action | 用户、Conversation、Workspace Use Case | confirmation required/rejected |
| Workspace solidify canonical write | 已有专用 API | 复用，不创建第二写入口 | Workspace knowledge | validation/execution failure |
| Interaction confirmation state | save 已由 FileInteractionJournal 持有 | 先测跨实例/提交窗口，再决定是否下沉 | Conversation resume | recovery/invariant failure |
| live Investigation delivery | B03 baseline 与 IP01 target 已闭环 | 执行完整 live matrix 和方差；新扩展重新走 baseline | Project 用户和 worker | typed Project terminal failure |
| capability discovery/materialization | 缺失 | Stage 3 在规模证据后实现两阶段加载 | Conversation model context | no eligible capability |
| context compaction | 未证明需要扩展 | Stage 3 先测再决定 | 长 Interaction / Project | context budget limitation |
| task-specific executable verification | 部分已有 | Stage 4 从一个 Artifact/result contract 扩展 | Verifier / Completion Gate | verification/completion failure |
| generic sandbox/computer use | 无业务证据 | 不实施 | 无 | capability missing |
| dynamic Agent team | 无业务证据 | 不实施 | 无 | capability missing |

任何 Stage 不得只交付 Interface、DTO、Fake、Prompt 或 E2E 文件。缺失能力必须在同一 Stage
拥有生产装配、消费者、失败语义、contract test 和正式入口 E2E。

## 6. Simplest Baseline and Evidence of Insufficiency

### 6.1 Baseline A: pre-change Conversation

使用同一自然语言目标：

> 把刚才关于 SLO 的结论核对后保存下来；如果与我已有知识冲突，先告诉我，不要直接覆盖。

最简单 baseline 使用正式 `POST /api/conversation/turn`。B01 已实际执行并保存 archive
`20260728T083321.588087Z-48120-2ce6f484`：模型要求确认，但没有 pending state、Tool call 或
Claim 写入；同输入经 Workspace solidify 可写入，根因是 Conversation 协议缺口。

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

### Stage 0: 每项扩展先冻结 baseline 与 Golden Set

目标：在任何生产扩展前证明当前错误，并建立同输入对照。明确 user-message 保存的 B01 已执行，
archive 为 `20260728T083321.588087Z-48120-2ce6f484`；“冲突核对后保存”等更丰富目标尚未执行
baseline，因此尚未准入。

交付：

1. 选择一个尚未满足的具体用户目标并建立自然表达 Golden Set；
2. 从最简单生产入口实际执行同输入 baseline，保存 trace、用户结果和反事实；
3. baseline 未失败或失败来自环境/测试时立即停止；
4. 只有产品失败成立后，才定义目标 E2E、复杂度预算、删除项和 catalog evidence。

禁止只用内部 capability 名称或预期步骤提示模型。

### Stage 1: Conversation Governed Knowledge Action（定向 E2E 已通过，合并门禁未闭合）

已完成范围：从 Conversation 打通一个且仅一个 Application Capability：模型从用户明确要求
保存的既有 user message 逐字选择知识 span，Admission 校验来源后冻结，确认后复用 Workspace
canonical write。B02 baseline archive 为 `20260729T031804.415533Z-15972-214cb81c`；E14
target archive 为 `20260729T033339.065714Z-22692-16415241`。

目标链：

```text
Conversation message
  -> EffectiveCapabilities exposes coarse save capability
  -> model proposes ToolCallProposal + exact user-authored spans/source indexes
  -> deterministic admission proves exact source membership
  -> Conversation freezes spans in immutable Command
  -> Pending Confirmation returned to user
  -> user confirms same run/task and digest
  -> resume frozen Command
  -> Workspace solidify/ingestion canonical write path
  -> Receipt returned by typed decision endpoint
```

已落地：

- 一个粗粒度 capability 与 typed exact-span/source-index arguments，禁止保存/确认控制语义
  进入冻结 payload；
- immutable Command、单 digest、三态 operation、Receipt 和 journal revision；
- typed decision endpoint 与 Workspace writer Port；
- E14 及 confirm/reject/replay Runtime conformance test。

未完成且不能由 E14 外推：冲突检索/核对、保存 assistant candidate、跨实例共享 journal、
Workspace commit 与 journal Receipt 之间的 crash injection，以及把 Receipt 再交给父模型生成
FinalMessage。它们必须分别由新的 baseline 失败证据准入。

必须删除或关闭：

- 任何关键词 `if "保存" in message` 路由；
- Conversation 直接调用 `capture_text` 或 Repository 的旁路；
- 确认前写入、客户端覆盖 server payload、确认后重新调用模型生成保存内容；
- 为兼容而保留的新旧保存入口双写。专用 API 可以继续作为真实外部产品契约，但必须与
  Conversation 复用同一个 Application Use Case 和 canonical write path。

### Stage 2: Live Durable Investigation Closure

目标：把现有 Investigation runtime 从 diagnostic evidence 升级为用户可验收的 live product
capability。

当前已执行 B03 baseline
`data/e2e_traces/20260728T123013.176272Z-42316-76b47a9c`。正式 HTTP、独立 Web/worker、
PostgreSQL、真实 structured model 与真实 Web Search 均进入生产链；Project 在 Verifier 发现
证据缺口后没有交付报告。该证据证明“执行后可能仍有语义缺口”，但不能证明当前
`verification_repair` 实现合理。以下是随后由 IP01 target 验收的最小实现边界：

- deterministic Tool dispatch 使用绑定 Proposal、Tool definition 和 ExecutionScope 的 leaf grant；
- Verifier 临时读取 Artifact owner 的完整正文并校验 digest，不持久化正文副本；
- PlanAdmission 拒绝 required mapping 指向冻结且未验证的 execution，并要求独立可运行 repair；
- accepted repair plan remap requirement 后才清除旧 verification waiting；
- typed `DecisionFeedback` 随 `ReplanRequest` 持久化并交给下一次 Planner；
- 等价 admission feedback 不含 event sequence，并受已有 `same_feedback_revision_limit` 约束。

生命周期 Harness 会直接注入 Plan、revision 和 Tool result，只属于 Runtime Conformance：它能
证明冻结边界、单次 dispatch 和有界暂停，不是用户 E2E，也不能作为 repair 的产品收益证据。

IP01 的早期运行未通过。`20260728T125249.466459Z-45552-410f6188` 证明旧 feedback digest 会造成 600 秒
内持续重规划；修复后的 `20260728T130808.632067Z-17988-0d9bfe10` 在 206 秒内有界暂停，根因是
单个宽 Web Search 返回无关来源，Verifier 正确拒绝。随后仅收紧现有 Planner/Execution
Proposer 的一般搜索语义，要求多对象独立取证、聚焦查询并在需要日期/出处时使用已有
`scrape`。之后 strict `json_schema` 在 DeepSeek deployment 上可被 HTTP 接受但不被执行，
archive `20260728T135746.012529Z-20360-ce914ffb` 在 226.9 秒、约 33.4k token 后因
`_PlanDraft.requirement_mappings` 缺失而 `provider_unavailable`。这证明 Provider transport
capability 不能由 OpenAI-compatible 协议外观推断，并准入显式 Adapter 隔离。

目标对照依次验证了 JSON mode、Tool Strategy 和 thinking profile。Tool Strategy 在复杂
`_PlanDraft` 上产生多 Tool 或不同的连续 JSON，archive
`20260728T142614.040177Z-10488-908e3539`、
`20260728T143017.195570Z-6428-d4a8976d` 均失败，相关 Adapter 已删除。最终
`JsonObjectStructuredAdapter` 配合 deployment 关闭 thinking 的 archive
`20260728T143217.175037Z-28784-bb0ed0e8` 用时 59.7 秒、可计 28,828 token，所有
Plan/Replan/Verification typed parse 通过且 `environment_failed=false`。Project 仍因两项
evidence verification repair 和“plan revision cannot overwrite frozen work”暂停，没有交付报告。

由这些 baseline 定义的 IP01 target 门禁是：

- IP01 从正式 HTTP/worker 以真实 model/Web Search 完成，而非当前非环境的
  `verification_repair` 暂停；
- accepted Plan version 至少为 2，并存在来自 revision 的新 execution proposal；
- 不得再次提案同一 `(logical_subgoal_id, subgoal_version)`，从而避免重放冻结执行；
- 用户可读取最终 generated Artifact，coverage、source、date、limitation 和 Completion Gate 通过；
- 只有 Project completed 后同一 E2E 实际得到 report 404，才准入缺失 report endpoint；
- crash、late result、approval、replay 和 tenant isolation 反事实；
- 相对 Conversation 和固定 Workflow 的同输入 baseline。

Stage 2 不创建第二个 Project 模型、Plan、journal、Artifact owner 或通用 DurableTask。

对应可执行契约是同一 `_run_live_investigation_report_journey`：B03 自动断言当前确有
`verification_repair` wait、没有报告且没有重复 execution proposal；IP01 在同一自然用户目标上
断言 wait 被消除、repair revision 产生新工作、冻结 execution 不重放并交付 verified report。
这些条件已由 `20260729T101501.732689Z-53628-6c5f02f2` 满足；Stage 2 的 IP01 repair
验收完成，但“发布可用”仍取决于本节列出的完整 live matrix、paired baseline 和方差。

2026-07-28 重新执行 B03 的 archive
`20260728T150928.484946Z-48884-5c941a61` 因 Tavily HTTP 432 配额限制终止，未进入 Verifier，
不能作为产品 baseline；E2E 已将该错误补入 environment failure 分类，禁止把 Provider 限额误报为
repair 缺口。

运行配置随后显式切换到 Firecrawl `/v2/search`，复用既有 `FIRECRAWL_*` credential owner，
没有 runtime fallback 或第二份 key。清理旧 Tavily credential 后重新执行的 IP01 archive
`20260728T154127.518791Z-8584-3899be03` 中三次生产 `web_search` 均成功，provider metadata 为
`firecrawl`，无 Tavily 调用且 `environment_failed=false`。Project 接受 Plan v2、执行一个新 repair
SubGoal 且未重复原 execution；随后因 repair evidence 仍不足，以及下一 revision 没有按规则创建
next SubGoal version 并 supersede 旧版本而暂停。Provider 阻塞已解除，repair 已有局部 E2E 收益，
但该次最终报告仍未交付；这是后续 lineage 修复前的历史失败证据。

2026-07-29 的后续同输入 trace 又依次证明并移除了四个更窄缺口：Web Search 的治理超时没有覆盖
search 加两次 capture；能力不匹配拒绝分支没有按关键字构造 typed `DecisionFeedback`；Execution
Proposal schema 未把 capability identity 收窄到当前 SubGoal 的 deterministic match；Replanner
预算投影只识别旧 `web_search_results`，没有识别 canonical Tool artifact `data.results`。
`20260729T075635.355657Z-17460-0a4c21f8` 已运行四版有界 Plan、8 次真实搜索且没有 exact replay，
并找到 A2A GitHub Releases 页面，但后段出现 Firecrawl 429/402 且没有交付报告，不能作为 target
acceptance。URL reader 现由 `Settings.url_capture_provider` 显式单值绑定，E2E 可令 Search 使用
Firecrawl、正文读取使用 builtin，不存在失败后的 runtime fallback。再次执行的
`20260729T080725.690825Z-11020-b4ee8959` 仍在 Firecrawl `/v2/search` 处收到账户级 HTTP 402，
被正确标为环境失败。因此当时继续保留 B03，且禁止用低层通过替代同输入正式 E2E。

2026-07-29 随后删除 Firecrawl Web Search Adapter，生产搜索唯一绑定迁移为 SerpAPI
`/search.json?engine=google`；`PERSONAL_AGENT_WEB_SEARCH_*` 成为搜索 credential owner，
URL 正文读取继续显式绑定 builtin，二者均无运行时 fallback。真实 Provider 冒烟成功返回
GitHub A2A Releases，SerpAPI contract test 覆盖 organic results、合法空结果、认证/Provider
错误和调用方 limit。迁移后的同输入 IP01 已不再出现搜索 Provider 环境失败，并依次证明：
臆造 capture URL 必须被 observed-locator schema/Admission 拒绝；空搜索结果不能误分类为
Provider unavailable；10 条候选可以取得 MCP GitHub Releases，并由 Verifier 确认
`2025-03-26` 与 `2025-06-18` 两项正式版本。最新 archive
`20260729T085601.806550Z-18988-2e0c1eba` 仍因 repair SubGoal 消费了跨主题候选、把 A2A
修复绑定到 MCP URL 后耗尽 plan revision 而暂停。该失败不是 SerpAPI 环境问题，也不是
target acceptance；下一最小缺口是持久化 repair-to-frozen-gap evidence lineage，并由
Semantic Admission 在执行前拒绝违反来源排除项的 locator。

最终最小改动由 ADR 0008 固化：accepted SubGoal 持久化 frozen-gap lineage，Execution 仅物化
依赖/递归 repair lineage 的 admitted evidence；普通 Execution Admission 拒绝在同一 Plan 上
局部重提；evidence repair 与 semantic Replan 分别计预算；模型选择 observed URL candidate id，
确定性代码绑定 canonical locator。正式 target archive
`20260729T101501.732689Z-53628-6c5f02f2` 在 86.42 秒内完成 Plan v3、3/3 verified outcomes、
5 条 admitted evidence、可读报告与 Completion Gate，且 `environment_failed=false`。Stage 2
的 IP01 repair 门禁据此闭合，剩余项是更广的 live capability matrix 和 paired/variance 证据。

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

第一条 Workspace answer-level verification 已由 B04 准入并通过 E20：回答组装与语义验证已
分离，冲突 assessment 绑定本次 EvidenceSpan，旧镜像 verification 字段已删除。当前事实统一见
[Verification 与 Completion](../topics/verification-and-completion.md)；本节以下内容仍是尚未准入的
Knowledge Workbench 候选。

剩余进入条件：Stage 1/2 的错误分布证明“Action 已执行但结果质量不足”是主要失败来源。

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

## 8. 已准入 E2E 与候选 Baseline Gate

### 已准入：B01 -> B02 -> E14 明确 exact-span 保存

- B01 用同一自然输入证明 Conversation 只能文本确认，缺少 pending operation、恢复、执行和
  Receipt；Workspace 写能力本身存在；
- B02 从正式 Conversation HTTP 入口穿过 prepare/confirm/canonical write，证明整条消息固化会
  缺失精确结论并写入保存/确认控制语义；
- E14 从同一正式入口证明确认前零写入、exact-span Command 重启恢复、跨 scope 拒绝、精确
  结论 Claim、控制语义零写入、Receipt 和成功后 replay；
- Runtime conformance test 补充 reject 终态；
- E14 不证明 assistant candidate、冲突核对、commit/Receipt crash window 或其他写操作。

### 已闭合 Baseline A：结论与控制语句分离

B02 已用同一自然输入检查最终 canonical Claim，archive
`20260729T031804.415533Z-15972-214cb81c` 自动证明精确结论缺失且“请求保存/先确认”成为长期
事实。修复只增加模型 exact-span selection 与机械来源校验，没有 candidate model、关键词解析
或第二写入口；目标 E14 已通过。

### 候选 Baseline B：冲突核对后保存

从正式 Conversation 入口自然表达“核对刚才的结论，和已有知识冲突就先告诉我，确认后再
保存”，断言用户是否获得冲突 Evidence 和待确认候选，并断言确认前零写入、不覆盖旧 Claim、
不跨 workspace。只有当前路径在同输入下失败且根因属于产品行为，才创建对应目标 E2E，定义
assistant candidate owner、版本与验证语义。

### 候选 Baseline C：其他 governed action

删除或订阅等每个动作分别从正式 Conversation 入口执行自然表达，断言含糊目标、确认前副作用、
scope denied 和 capability unavailable。不能把 E14 当作共享失败证据，也不能先注册
`prepare_knowledge_delete` 等未来 capability 再证明其必要性。

### 候选 Baseline D：crash window 与多实例协调

在 Workspace commit 与 journal Receipt 写入之间注入真实进程终止，或由两个生产实例并发处理
同一 digest，断言是否产生重复 Claim/Receipt。只有失败被复现后，才准入 Workspace 幂等键、
共享事务存储或 outbox；当前 E14 不能支持 exactly-once 的跨边界声明。

### 独立目标：Live Investigation 与 Capability Scale

Investigation 的 baseline、目标 E2E 和命令只由
[Durable Investigation Project 设计](durable-investigation-project-design.md#6-e2e-first) 拥有。
Capability retrieval 只有在全量 public schema 注入的实际 trace 证明完成率、误选、token 或延迟
约束后才定义目标 E2E；大量不可见或相近能力的合成数据不能单独成为产品优化证据。

## 9. Affected Modules and Dependency Direction

Stage 1 已落地的影响边界：

```text
Web Conversation DTO
  -> Conversation Application
     -> existing ToolCallProposal + exact-span save arguments
     -> immutable Command / Interaction Journal
     -> existing Workspace Solidify Use Case
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

### 10.1 Stage 1 实际复杂度

Stage 1 新增：

- 一个粗粒度 scoped Application Capability；
- 一套 Pending Confirmation/decision contract；
- 一个复用现有 FileInteractionJournal 的 confirmation owner；
- 一个 Workspace writer Port 及现有 solidify Use Case 装配；
- 对应 E14、Runtime conformance test 和 trace 支持。

每新增一个 Model、状态、digest、表或 Port，实施文档必须说明独立 owner、生命周期、事务边界和
生产消费者。授权内容和最终执行内容相同时只使用一个 canonical command digest。

### 10.2 Removed and Avoided Complexity

实际删除未接入生产执行的 `conversation_solidify` Procedure definition、输入 contract 和冲突的
workflow 文档。没有发现关键词保存 Router，因此不伪造删除项；同时没有新增专用 Proposal
union、第二知识写入口、双 digest、Event/Projection、通用 Workflow 或兼容双轨。

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

1. B01 baseline 与 E14 最小纵切已归档；
2. 下一项扩展先从第 8 节选择一个最简单 baseline，未失败就停止；
3. 产品失败成立后才定义同目标 target E2E、最小改动和同步删除项；
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
