# Agent 能力轴：理解深度与本项目落地

本文是本目录的主文档，用于面试中展示对现代 Agent 各能力维度的理解，以及这些理解如何落到
具体实现、证据和边界上。写法遵守 [面试文档规范](00-writing-spec.md)：每轴必须答满 D1-D5，
证据按 A-D 分级。它不新增架构事实：与
[当前核心架构](../summary/core-architecture-current-state.md)、
[能力与发布基线](../summary/phase0-capability-release-baseline.md) 或生产代码冲突时，以后者为准。

每一轴固定四段，对应规范的五问：

```text
问题本质        D1 这个轴在解决什么第一性问题
常见做法与失效   D2 + D4 主流方案在什么地方失效，本项目与它们的异同
本项目选择      D3 具体实现、代码位置和判据
证据与边界      D5 哪条 E2E 断言了它（含级别）；还没做到什么
```

最后一段是刻意保留的。只能讲优点、说不出边界的轴，说明理解仍停在术语层。

## 0. 自评矩阵

| # | 能力轴 | 一句话主张 | 当前强度 |
| --- | --- | --- | --- |
| 1 | Agent loop 与决策所有权 | 模型提 Proposal，Runtime 准入并执行；object-root 只是当前 wire format | 强 |
| 2 | 结构化输出与 Provider 边界 | 传输能力不能由协议外观推断，禁止运行中切协议 | 强 |
| 3 | Context engineering | 可见性先于检索、ArtifactRef、sealed context | 部分（无两阶段发现与 compaction） |
| 4 | Tool 与 capability 治理 | Tool 不决定自己是否被授权；配置存在 ≠ 可用 | 强（无 sandbox，有意取舍） |
| 5 | HITL 与受治理副作用 | 一个 digest 绑定确认、执行与 Receipt | 强 |
| 6 | Specialist 协作 | child completed ≠ 父任务完成；不盲目重提 | 相当（单 specialist） |
| 7 | 预算、停止条件与并发 | 耗尽即 limitation，不拼替代答案 | 强 |
| 8 | Durable state 与恢复 | 按事实类型分 owner，删掉无消费者的 Plan | 强（单进程，非分布式） |
| 9 | 长期知识与记忆污染 | Ask 只读，只收 user-authored claim | 强（本项目最大差异化） |
| 10 | 验证与完成判定 | Execution / Verification / Completion 三分且互不冒充 | 强 |
| 11 | 评估与发布证据 | 测试通过 ≠ 发布资格；证据分级 | 强 |
| 12 | 可观测性与故障定位 | 先定位到层，不把一切归因 Prompt | 相当（无在线 eval） |

「强」指有生产实现加正式入口 E2E 证据；「部分」「相当」指实现存在但覆盖窄或缺对照数据。
矩阵本身不构成发布资格，发布资格只能由 clean matching revision 的 release archive 派生。

## 1. Agent loop 与决策所有权

### 问题本质

Agent loop 的难点不是「让模型能循环调用工具」，也不是「把自然语言变成 JSON」，而是如何让
概率模型拥有开放语义决策能力，同时不获得权限、执行事实和完成事实。

顶层协议不是 wire format，而是一条**所有权链**：

```text
User Goal + Context + Observation
  -> Model Proposal
  -> Admission / Policy
  -> Governed Execution
  -> Execution Fact
  -> Verification
  -> Completion
```

它规定每一段事实由谁产生、谁无权产生：

| 阶段 | owner | 关键否定 |
| --- | --- | --- |
| Goal + Context + Observation | Runtime 组装 | 模型不能自行扩写或改写 Goal |
| Model Proposal | 模型 | 只提议，不获得执行权 |
| Admission / Policy | 确定性代码 | 只能接受或返回 typed 反馈，不替模型补语义 |
| Governed Execution | Gateway / Executor | 模型自述不是执行 |
| Execution Fact | 执行结果本身 | 不能由文本推断 |
| Verification | Verifier | 执行成功 ≠ 结果正确 |
| Completion | Domain / Completion Gate | 生成了文本 ≠ 任务完成 |

模型独占的只有一格——开放语义决策。**权限、执行事实、完成事实三样它一样都不拿。**
typed JSON 是 Proposal 的当前传输形式，不是本轴的第一性原理。

权属模糊会产生两类具体故障（D2）：确定性代码偷偷改写了语义，而模型不知道自己被改了；或者
模型自述被当成执行事实。

### 常见做法与失效

| 做法 | 失效点 |
| --- | --- |
| 从 `Action:` / `Final Answer:` 等文本恢复控制流 | Runtime 必须猜测分支，格式漂移后不可可靠断言 |
| root union 输出（`FinalAnswer \| ToolCall`） | 部分 OpenAI-compatible endpoint 上 top-level union 不被执行 |
| Validator 顺手补参数 | 语义 owner 悄悄变成 if/else，Golden Set 无法覆盖 |
| 出错抛异常或返回字符串 | 模型不知道哪个字段可改，只能重试同样的错 |

### 本项目选择

模型每轮先产生一个 typed Proposal。当前 wire contract 使用 object-root envelope
（[models.py:72](../../src/personal_agent/application/conversation/models.py#L72)）：

```text
AgentTurnDecision
└─ decision
   ├─ FinalMessage          disposition: answer | clarification_required | limitation | failed
   └─ ContinueTurnProposal
      └─ actions[]          ToolCallProposal | AgentDelegationProposal
```

四个刻意的设计：

1. **Proposal 与执行分离**：`ToolCallProposal`/`AgentDelegationProposal` 必须经过 Admission，
   不能因模型生成就执行；
2. **Observation 驱动下一轮**：Tool/Agent 结果形成 typed execution input，模型基于事实再决策；
3. **object root 而非 union root**：这是 terra 顶层 union 失败后的 Provider 适配，不能冒充
   顶层框架理念；
4. **Admission 只能接受或返回 typed `DecisionFeedback`**
   （[models.py:101](../../src/personal_agent/application/conversation/models.py#L101)），
   携带 `reason_code`、`repairable_fields`、`immutable_fields`、`required_repair`、`disposition`。

`FinalMessage` 还把 `answer / clarification_required / limitation / failed` 设为显式 disposition
（[models.py:52](../../src/personal_agent/application/conversation/models.py#L52)），
模型必须自报这是答案、澄清、能力受限还是失败，避免「生成了文本」被 Runtime 一律当作成功。

Admission 明确**不允许**：补 `note_id`、把错误 Tool 换成相似 Tool、拼接缺失 payload、改写 Goal、
预算耗尽后生成替代答案。实现上 `_admit`
（[service.py:678](../../src/personal_agent/application/conversation/service.py#L678)）
的每一条分支只返回 `DecisionFeedback`，从不修改 action 本身。

**必须分清的两个层次**（规范第 4 条）：

| 层次 | 当前结论 | 可替换性 |
| --- | --- | --- |
| 顶层协议 | 模型输出 typed Proposal；Runtime 不解析自然语言控制流；Admission 后才执行 | 不可替换 |
| wire format | object-root envelope，兼容已观察的 Provider schema 能力 | 可替换 |

将来即使改用 Provider 原生 Tool Calling，第一行仍必须成立；反过来，没有同输入 E2E 证明当前
envelope 造成用户失败之前，也不会仅为追逐框架潮流替换它。

### 决策所有权速查（可直接当白板表）

| 问题 | Owner |
| --- | --- |
| 用户想完成什么 | 模型或用户显式产品操作 |
| 是否直接回答、选哪个 Tool/Agent | 模型 |
| Tool 是否存在 | Registry |
| Proposal schema 是否合法 | Admission |
| 是否允许执行 | Policy / Governance |
| Tool 实际返回什么 | Tool / Provider |
| Command 是否已执行 | Journal / Event / Receipt |
| durable Plan 是否 accepted、哪些 SubGoal ready | InvestigationProject aggregate |
| Answer 是否满足证据 | Verifier |
| Aggregate 是否完成 | Domain state machine |
| Project required result contract 是否齐全 | Investigation Completion Gate |
| 是否具备发布证据 | E2E catalog + release gate |

### 证据与边界

- **B 级**：E01 覆盖直接回答、澄清、多轮继续，并反证不伪造 Task/Command/CompletionReport；
  baseline `20260729T033100.290836Z-35328-02db4988` 证明模糊新请求曾被旧答案冒充完成，同输入
  澄清修复后通过 `20260729T033304.468248Z-28272-e91b6630`；
- **B 级**：L01 证明自然用户目标（用户不知道 Tool 名）能驱动真实能力选择；
- **C 级**：terra 的顶层 union retry 超时是 object-root 的直接 Provider 证据，但它不证明自定义
  envelope 普遍优于所有原生 Tool Calling 协议。

边界（两条都要主动说）：

1. 自然语言控制词解析是**被拒绝的行业实现路径**，本项目没有「旧正则 parser 线上事故」baseline，
   面试中不能说成本项目历史故障；
2. 当前主要证据仍是「一跳 Action -> Observation -> Final」，**长链多跳的收敛性未被 E2E 压满**。

还有一条本轴换不来的东西：所有权链约束的是「谁有权产生哪种事实」，**不保证决策质量**。模型可以
合规地提出一个愚蠢的 Proposal，Admission 一样放行。它换来的是可归因——出错时能定位到是 Proposal
层还是 Admission 层，而不是笼统归因 Prompt。

### 预期追问

> 为什么不用 root union？

Provider 兼容性。terra 部署上顶层 union schema 直接导致 retry 超时，见
[phase0 基线](../summary/phase0-capability-release-baseline.md)。object root 同时让
`action/actions` 单复数双轨不可能出现。

> Admission 顺手补一个 `note_id` 有什么问题？

那一刻语义 owner 从模型转移到了 if/else。这个 if/else 不在 Prompt 里，Golden Set 覆盖不到它，
线上出错时无法归因。宁可返回 `invalid_arguments` 并标明 repairable field，让模型自己修。

> 出错为什么不直接抛异常或返回一句错误字符串？

因为模型不知道哪个字段可改，只能重试同样的错。`DecisionFeedback` 用 `repairable_fields` 与
`immutable_fields` 明确告诉模型「这个方向不是你修的」，让重试携带信息量。这是与「structured
error for the model」这一现代 harness 共识相同的地方；不同点是本项目把 feedback 也写进 journal
成为 committed input，所以进程重启后模型仍看得到上一轮为什么被拒。

## 2. 结构化输出与 Provider 能力边界

### 问题本质

typed Agent 的地基是「模型一定返回可解析结构」。这个地基比多数人以为的脆——**Provider 声称支持
某种结构化传输，不等于该 deployment 真的执行它**。

### 常见做法与失效

| 做法 | 失效点 |
| --- | --- |
| 假定 OpenAI-compatible 就有 strict `json_schema` | HTTP 200 被接受，但响应缺字段 |
| 解析失败就运行中降级切协议 | 同一 deployment 出现两种语义，故障不可复现 |
| 保留 SDK 隐式 retry 再叠自己的 retry | 实际调用次数不可预算，超时语义混乱 |
| 只设 connect/read timeout | SSE 持续发 chunk 会不断重置 read timeout，永不超时 |

### 本项目选择

`infra/structured_model.py` 是唯一 OpenAI-compatible 生成边界，Composition Root 按 capability
profile **确定性**选择 Adapter：

```text
StrictJsonSchemaAdapter        Provider 原生 strict json_schema
JsonObjectStructuredAdapter    json_object + canonical Pydantic schema instruction
```

配套四条：

- `STRUCTURED_OUTPUT_TRANSPORT` 声明 deployment 能力，**禁止**根据一次异常在运行中切换协议；
- SDK 隐式 retry 关闭，`RetryingStructuredModelClient` 是唯一 retry owner；
- typed 校验失败最多请求同一模型完整重写一次，第二次仍无效则 fail closed；
- 除 connect/read/write/pool timeout 外，另加完整 Provider 调用的 **wall-clock deadline**，
  structured SSE 消费同受该 deadline 约束。

### 证据与边界

这一轴的证据全是真实踩坑，可以直接讲故事：

| 现象 | archive | 结论 |
| --- | --- | --- |
| strict `json_schema` 在 DeepSeek 被 HTTP 接受但不执行，226.9 秒后因 `_PlanDraft.requirement_mappings` 缺失报 `provider_unavailable` | `20260728T135746.012529Z-20360-ce914ffb` | transport capability 不能由协议外观推断 |
| Tool Strategy 在复杂 `_PlanDraft` 上产生多 Tool 或连续 JSON | `20260728T142614`、`20260728T143017` | 该 Adapter 已删除，不留兼容分支 |
| `JsonObjectStructuredAdapter` + deployment 关闭 thinking | `20260728T143217.175037Z-28784-bb0ed0e8` | 59.7 秒、28,828 token，全部 typed parse 通过 |
| read timeout 被 SSE chunk 持续重置 | E09 从 21702.94 秒降至 92.27 秒 | 根因是超时语义，不是模型慢 |

边界：当前只覆盖两种 transport profile；多 Provider 路由未做也不打算做（无业务证据）。

### 预期追问

> 为什么不做 fallback？失败了自动换协议不是更健壮吗？

fallback 让同一 deployment 在不同时刻有不同语义：故障不可复现，配置错误被永久掩盖，
E2E 也无法断言「这次到底走了哪条路」。宁可 fail closed 并把 transport 作为显式配置事实。

## 3. Context engineering

### 问题本质

不是「塞得越多越好」，而是三件事同时成立：在 token 预算内让模型看到**恰好足够**做对决策的内容；
能**证明**它这一轮看到了什么；上下文里的东西**不会变成事实**。

### 常见做法与失效

| 做法 | 失效点 |
| --- | --- |
| 全量注入 Tool 定义 | Tool 增多后延迟与误选率同时上升 |
| 先语义检索再过权限 | 跨租户泄漏；相似度不是授权 |
| 把大正文复制进 Agent State | State 膨胀，且正文出现第二 owner |
| compaction 连 Command/Evidence 一起压 | 恢复后重复执行副作用 |

### 本项目选择

四条已落地：

1. **可见性先于检索**：先按 user/workspace scope 过滤，再做语义检索；检索只能缩小候选集合，
   不能替模型做最终语义选择；
2. **ArtifactRef 而非正文**：运行状态保存 ref，正文由 `ArtifactService` 持有；Project 只存
   `ResourceRef`，Verifier 临时读正文并校验 digest，不持久化副本；
3. **capability revision**：对 `EffectiveCapabilities` 的 canonical JSON 计算 revision，
   用于证明「本轮模型看到了哪组定义」——但它**不证明远端 Provider 健康**；
4. **sealed context**：`StructuredModelRequest.context_projection_ref` 必填
   （[model.py:24](../../src/personal_agent/capabilities/contracts/model.py#L24)），
   边界明确的调用使用 content-addressed `sealed-context`，上下文变化即改变 digest。

### 证据与边界

诚实说，这是当前最弱的一轴之二：

- 每轮仍注入**全部** public Tool schema；
- **无 context compaction**。

Stage 3 的目标管线已写清，但准入条件是「实际 trace 先证明规模问题」，不是「业界都这么做」：

```text
principal + scope -> visibility filtering -> 小的 capability summary
  -> requirement retrieval -> 加载少量完整 schema -> 模型最终选择 -> budgeted materialization
```

### 预期追问

> Tool 涨到 100 个怎么办？

上面那条两阶段管线。要强调三个约束：visibility 必须先于 retrieval；capability summary、
full schema、availability observation 不能变成三个可写事实源；compaction 只能压可丢弃的
LLM Context，绝不触碰 Command、Receipt、Evidence 或 Project journal。

> 为什么现在不做？

没有 trace 证明当前 Tool 规模已造成完成率下降、误选或延迟约束。先做等于为想象中的问题增加
复杂度，而这套 capability 层一旦加上，撤除成本很高。

## 4. Tool 与 capability 治理

### 问题本质

Tool 不是「一个能被模型调用的函数」，而是权限、副作用、幂等和审计的交汇点。核心判断是：
**Tool 本身不能决定自己是否被授权**。

### 常见做法与失效

| 做法 | 失效点 |
| --- | --- |
| Tool 内部自己判权 | 授权逻辑散落各处，无法统一审计 |
| Application 直接依赖 LangChain BaseTool / MCP SDK | 换 Provider 要改业务层 |
| 配置了 MCP Server 就认为能力可用 | 配置存在 ≠ discovery 成功 ≠ 调用成功 |
| 能力缺失时换一个「最像」的 Tool | 用户以为读了远端，实际是常识编造 |

### 本项目选择

**两层分离**：

```text
ToolExecutor    registry、Tool definition、schema validation、interaction exposure projection
ToolGateway     policy、permission scope、risk/confirmation metadata、idempotency、
                timeout/retry/rate limit、execution audit
```

代码：[registry.py](../../src/personal_agent/governance/registry.py)、
[gateway.py](../../src/personal_agent/governance/gateway.py)。Application 只依赖
`InteractionToolPort`，不直接依赖 LangChain `BaseTool`、MCP SDK 或具体 Provider——换 Provider
不需要改业务层。完整执行链：

```text
ToolCallProposal
  -> ToolExecutor.validate_interaction_call   （schema / registry，属于 Admission）
  -> ToolExecutor.invoke_interaction
  -> ToolGateway.invoke                       （policy / scope / idempotency / audit）
  -> typed ToolArtifact
  -> ActionObservation
```

注意 validate 与 invoke 是**两次**进入 ToolExecutor：先证明可以调，再调。合成一步就无法在不
产生副作用的前提下返回 `invalid_arguments`。

**MCP 准入是三方交集**：Host 接受配置 + 实际 discovery 返回远端 name/schema + 本地 mapping 声明
exposure/scope/risk/data egress/timeout。`RuntimeCapabilityInventory` 明确区分 configuration、
discovery、availability observation 三种事实，不把「配置存在」推断成「Provider 健康」。

**exposure 分层**：当前普通 Conversation 只加载 `public_agent` Tool；`scoped_agent` 与
`workflow_activity` 不自动进入模型上下文。所以模型能选「准备保存会话结论」这种粗粒度
Application Capability，但看不到 `research_initialize_state` 这类内部事务 Activity。

### 证据与边界

- E06/E16/E18 使用真实 GitHub/Notion 数据源与 MCP gateway；
- **E19 是这一轴最有价值的反证**：能力不可用时断言 `tool_calls=0`，系统返回 limitation，
  不换相似 Tool，也不用常识编造远端内容。

边界：**无 sandbox / shell / computer use / 浏览器控制**。这要说成取舍而非遗漏——当前知识域的
用户结果没有证明 filesystem 是缺失能力，路线图把它明确列为 out of scope，等 E2E 证明现有
Tool/MCP/A2A 不足再准入一个最小扩展。

### 预期追问

> 为什么 ToolGateway 比普通函数调用值得？

因为它是唯一能同时回答这几个问题的地方：这次调用被谁授权、是否可安全重试、幂等键是什么、
是否需要确认、外发了什么数据、审计记录在哪。这些问题散进各个 Tool 实现里就没有统一答案了。

## 5. HITL 与受治理副作用

### 问题本质

难点不是「弹一个确认框」，而是**机械证明用户确认的内容和最终执行的内容是同一个东西**。
如果中间模型重新生成过 payload，这次确认就没有意义。

### 常见做法与失效

| 做法 | 失效点 |
| --- | --- |
| 确认后重新调用模型生成执行内容 | 执行内容 ≠ 确认内容，审批形同虚设 |
| 客户端回传 payload | 客户端可覆盖 server 冻结的内容 |
| 确认状态放内存 | 重启丢失；用户第二次确认变成第二次执行 |
| Proposal / Command / Receipt 混用一个 Model | replay 时旧 Proposal 被当新 Command |

### 本项目选择

**三分 + 一个 digest**：

```text
Proposal    模型建议做什么，无权限语义
Command     Application 接受后形成的不可变执行请求
Receipt     执行系统记录已经做了什么
```

一个 canonical `command_digest` 同时绑定 confirmation、execution 和 Receipt。派生规则：

- Command **immutable**：参数变化不能覆盖原 Command，只能创建 superseding Command；
- Restore 不是把 DeleteCommand 状态改回去，而是新建 RestoreCommand，原 Receipt 保留；
- 错误 digest 拒绝；reject 进入明确终态且零副作用；
- 确认后**不重新调用模型**生成 payload。

E14 是当前最完整的样本链：

```text
模型从 user message 逐字选择 knowledge text_span + source index
  -> Admission 机械证明该 span 确实存在于该 user message 且 role=user
  -> Runtime 只冻结 exact span 为 immutable Command + 单一 digest
  -> awaiting_confirmation 返回用户
  -> 用户确认（校验 principal/workspace/digest）
  -> WorkspaceService.solidify_conversation（既有 canonical write path）
  -> typed Receipt
```

### 证据与边界

- E04/E10：governed delete/restore，覆盖错误 digest 拒绝、prepare 后零副作用、reject 零副作用、
  重启恢复、replay 返回同一 Receipt 不重复删除；
- E14：确认前 Claim 零增长、prepare 后重启 Command 不变、跨 scope 404、精确结论 Claim、
  控制语义零写入、Receipt 精确引用该 Claim、replay 同一 Receipt。

**B02 -> E14 这个演进值得单独讲**：B02（archive `20260729T031804.415533Z-15972-214cb81c`）
证明把整条 user message 固化会把「请求保存/先确认」这类**控制语义写成长期 Claim**。这个 bug
很隐蔽——它「保存成功了」，只是保存错了东西。修复方式是加 exact-span 选择 + 机械来源校验，
而不是加关键词过滤。

边界（不能从 E14 外推）：Workspace commit 与 journal Receipt 之间的 **crash window 未覆盖**；
多实例并发同一 digest 未验证，因此不能声称跨边界 exactly-once；删除、订阅、「冲突核对后保存」、
保存 assistant candidate 仍需各自 baseline。候选 Baseline D 就是为 crash window 准备的。

### 预期追问

> 为什么删除要 Command，读取不要？

读取低风险、可安全重试、没有审批或恢复消费者。为「形式统一」给每个读操作造 Command/Event/
Receipt 只会增加空转状态。删除有长期副作用、需要确认、需要重启恢复、需要幂等 replay 和审计
——这五个消费者都真实存在，Command 才有意义。

## 6. Specialist 协作（A2A / subagent）

### 问题本质

判据只有一个：这个 sub-goal 是否需要**自己的多轮推理、自己的工具使用、自己的 Artifact 产出**。
输入输出 schema 稳定、单次调用能完成的，是 Tool，不是 Agent。

### 常见做法与失效

| 做法 | 失效点 |
| --- | --- |
| child `completed` 就返回给用户 | 子执行事实被冒充成父级最终答案 |
| Artifact 直接当 FinalMessage | 父 Agent 跳过了综合与验证 |
| 重启后不确定是否已提交就重提 | 外部副作用重复执行 |
| Adapter 里做授权判断 | 协议转换层变成第二个 policy owner |

### 本项目选择

```text
AgentDelegationProposal（bounded_sub_goal + context_projection_refs
                         + expected_artifact_types + token/cost/time budget）
  -> local profile / scope admission
  -> DelegationGrant
  -> AgentGateway submit / poll / cancel / stream
  -> ChildAgentRunRecord + AgentArtifact
  -> ActionObservation
  -> 父模型综合 FinalMessage
```

见 [models.py:28](../../src/personal_agent/application/conversation/models.py#L28)、
[gateway.py](../../src/personal_agent/agents/gateway.py)。四条不变量：

- `AgentGateway` 拥有 child lifecycle 与 Artifact index，A2A Adapter 只转协议；
- 远端 `completed` 是子执行事实，**不能完成父 Interaction**；
- 同一 Interaction 内该 Agent 已返回 Artifact 后，重复委托被 Admission 拒绝；
- Provider Artifact 先经 `ArtifactService.write_generated` 落入 owner scope，AgentRun 只存
  `ResourceRef`；读正文时重新校验 principal 与 SecurityScope。

**durable 侧的 submit 安全序列**（这条细节含金量高）：

```text
1. 以 stable submission key + immutable definition digest 写 reservation
2. 调用 Provider Adapter
3. 把 provider task id 与同一 run commit
4. 重启后 reservation 存在但 binding 缺失时，只允许 lookup_submission(key)
5. Provider 不支持 lookup 或查不到 -> AgentSubmissionOutcomeUnknown，禁止盲目重提
```

第 5 步是关键：**不确定就 fail closed，而不是赌一次重试**。

### 证据与边界

- E07/E17/C04/L04 使用真实 GPT Researcher，执行后断言 child Artifact 与父级用户结果分离；
- E17 trace 自动断言 `agent_calls == 1`；
- durable Agent uncertain-submit / restart reconcile 自动断言 Provider submit count=1；
- cancel 会 quarantine 终态后返回的 Artifact，不重新打开 Project。

边界：只有一个真实 specialist，**没有 agent team、角色市场或隔离工作区**。Conditional Stage 5
的准入条件是先证明现有 Tool / 单 specialist / 固定 Workflow 完不成某个具体用户目标。

### 预期追问

> 什么时候该拆 subagent？

需要自己的多轮推理 + 自己的 Artifact 时。反过来说，如果只是想「让架构看起来更 Agentic」而拆，
代价是多一套 lifecycle、一套预算、一套恢复语义和一个可能冒充父结果的 owner。

## 7. 预算、停止条件与并发

### 问题本质

Agent 最贵的失败不是「做错」，而是**不知道什么时候该停**。停止条件必须是确定性的，而且
「停下来」不能退化成「随便给个答案」。

### 常见做法与失效

| 做法 | 失效点 |
| --- | --- |
| 只限最大轮数 | token 和外部调用成本仍不可控 |
| 预算耗尽时用最后一个 Observation 拼答案 | Runtime 越界做了语义解释，还可能编出用户没要的结论 |
| 所有 action 一律并发 | 写操作交错，破坏不变量 |
| 所有 action 一律串行 | 只读多目标场景延迟翻倍 |

### 本项目选择

`LoopBudgetPolicy`（[models.py:123](../../src/personal_agent/application/conversation/models.py#L123)）
限制 model turns、tool calls、agent calls、total tokens、concurrency 五项。耗尽时：

```text
disposition = limitation
「本次交互已达到执行预算上限，未生成替代答案。」
```

**Runtime 不把最后一个 Tool Observation 拼成业务答案**——如何解释 Observation 属于语义决策。

并发判据是**机械可证**而非启发式：只有全部 action 都无写入/删除等共享副作用（依 governance
side effects 判定）、且 Agent profile 只允许 delegate/read 时，才进 bounded thread pool。

```text
[read_A, read_B]   -> concurrent batch -> wait all observations -> next model turn
[write_A, read_B]  -> serial
```

并发只优化执行，不改变 Proposal 顺序、Observation ownership 或完成判断。

Project 侧预算更细：按 planning / execution proposal / external delegation / verification /
synthesis 分类，**先 reserve 再调外部能力，最后 charge/release**；evidence repair 用独立的
`max_evidence_repair_revisions`，与 `max_plan_revisions` 互不吞噬。

### 证据与边界

- **L05 是这一轴的核心反证**：预算足以完成读取但不足以让模型在 Observation 后继续时，返回
  limitation，且最终消息**不得泄漏或猜出**那个随机答案，同时 trace 中必须已有真实读取结果。
  这同时证明了两件事：读取真的发生了；Runtime 没有拿它拼答案。
- IP01 早期 archive `20260728T125249.466459Z-45552-410f6188` 证明旧 feedback digest 会造成
  600 秒持续重规划；修复后同反馈按不含 event sequence 的 digest 计数，达到
  `same_feedback_revision_limit` 即局部 fail closed。

边界：成本目标只做到 fail closed，**没有按成本自适应选模型或降级策略**；paired evaluation 的
方差数据尚未积累。

### 预期追问

> 怎么控制成本？

分层：直接回答允许单轮结束；固定 Workflow 不调用通用 Planner；只有动态且必须 durable 的任务
才创建 Project；再叠四类 budget、安全只读并发、统一 retry owner 和 wall-clock deadline。
关键是**不把「更多轮次、更多 Tool 调用」当成效果指标**——路线图明确把它列为拒绝项。

## 8. Durable state 与恢复

### 问题本质

恢复要回答的不是「把内存 dump 回来」，而是：**哪些事实已经提交、哪些副作用已经发生、
哪些冻结的输入不许重算**。不同事实的恢复语义天然不同，用一个 God Aggregate 装不下。

### 常见做法与失效

| 做法 | 失效点 |
| --- | --- |
| 一个通用 Task/RunCheckpoint 覆盖所有请求 | 直接回答被迫伪造 Task/Command/CompletionReport |
| 持久化一个没有调度消费者的 Plan | 增加首次 action 与恢复的模型轮次，却不驱动任何东西 |
| 恢复时重新调模型生成已冻结的 Command | 执行内容 ≠ 已授权内容 |
| 查询接口顺手推进状态 | GET 变成写操作，用户刷新页面就推进了任务 |

### 本项目选择

**按事实类型分 owner**，不存在通用主链：

| 边界 | 实现 | 恢复语义 |
| --- | --- | --- |
| 普通 Interaction | `FileInteractionJournal` | 从 committed inputs 重建 transient context |
| Workspace/Knowledge | `PostgresWorkspaceStore` | 从 Artifact/Evidence/Claim/Event 恢复 |
| Delete/Restore | `PostgresKnowledgeLifecycleStore` | Command/Event/Receipt digest replay |
| Research | `PostgresResearchStore` + queue | Run/Subscription/Delivery lifecycle |
| Investigation Project | `PostgresInvestigationProjectStore` + append-only journal | 重建 Plan、ready set、verification、completion |
| Tool governance | `PostgresToolGovernanceStore` | policy、idempotency、audit |
| Child Agent | `AgentGateway` run store | child status 与父结果分离 |

**普通 Conversation**：只保存 committed facts（messages、capability revision、Observation/
Feedback、usage、execution order、concurrent batches、final message）。恢复后模型直接读 typed
inputs 继续，Admission 拒绝重复 `action_id`。

**这一轴最能体现判断力的是一次删除**：旧 `WorkingPlanSnapshot` 只进入 Prompt/Trace，没有任何
生产调度消费者，却增加首次 action 和恢复的模型轮次——所以把它删了。真正驱动 ready set、
coverage 和恢复的 Plan 只存在于显式 Investigation Project。

**Project 侧**：accepted Plan 是 aggregate 的 canonical fact 且被 worker 实际消费；steering 只
修订未冻结 SubGoal；GET 只读 projection，不调模型不推进状态；worker 启动时扫描 recoverable
Project 并用稳定 idempotency key 重新入队，覆盖「create 已提交但 enqueue 前崩溃」的窗口。

### 证据与边界

- **L03**：在观察到第一个 committed input、最终回答尚未产生时**真实终止进程**；恢复后必须回答
  本用户随机事实、排除另一用户冲突事实，且执行顺序前缀不变、旧 action 不重复；
- LT01-LT13：worker 重启从 PostgreSQL journal 恢复、stable submission key 避免重复 child submit、
  cancel quarantine late Artifact；
- `completing` / `cancelling` 进程崩溃恢复已通过故障注入，恢复不重复 final synthesis。

边界要说清两层：普通 Interaction 用**文件 journal，已证单进程重启恢复，不是多实例分布式
session store**；LT01-LT13 使用生产 Domain/Store/Worker 但 model 与 Provider 是 scripted/frozen
Port，属于 **diagnostic evidence，不是 live release evidence**。

### 预期追问

> 为什么不统一用一个 DurableTask？

因为 ResearchRun、DeleteCommand、Delivery、Investigation Project 的状态机与恢复语义完全不同。
ResearchRun 是固定领域生命周期 + 内部语义决策；Project 是动态 accepted Plan + durable
completion obligation。合并的代价是一个 God Aggregate 混装所有 lifecycle，而收益只是「看起来
统一」。直接回答更不需要伪造 Task。

## 9. 长期知识与记忆污染

> 本项目最大的差异化。面向知识 / RAG / memory 类岗位应该第一个讲。

### 问题本质

Agent memory 的核心风险不是遗忘，而是**模型输出自动变成下一轮的既定事实**，形成自我强化的
幻觉闭环。要破它，必须能回答三个问题：原始内容是什么、来自哪里；答案里的事实由哪段证据支持；
事实被修正、冲突或删除后生命周期如何演进。

### 常见做法与失效

| 做法 | 失效点 |
| --- | --- |
| 每轮对话自动写回向量库 | 污染循环；来源不可审计 |
| Document + Embedding 两层模型 | 无法表达 supersede / conflict 关系 |
| 向量库或图数据库作为事实源 | 索引重建失败会覆盖或删除业务事实 |
| Ask 顺手把答案写入 memory | 读取行为产生长期副作用 |

### 本项目选择

**五层事实链**：

```text
Source -> Artifact -> EvidenceBlock/EvidenceSpan -> Claim -> Relation/KnowledgeItem
                                                        -> Retrieval Index / Graph Projection
```

PostgreSQL Workspace Store 是 canonical fact owner；embedding index 和 Graphiti
**都只是可重建投影**，投影失败不能覆盖或删除 canonical facts。

四条硬规则：

1. **Ask 是 read-only**，E2E 直接比较前后 Claim 数；
2. **只有显式 solidify 进入唯一写入口**，且只收 user-authored claim，assistant candidate 全部拒绝；
3. **纠错是 supersede 而非覆盖**：旧 Claim 转 `superseded`、新 Claim `active`、Relation 记录
   supersedes/conflicts；检索只选 active，但历史可审计；
4. **外部结果不是 Claim**：MCP、Web Search、A2A 返回的是 Observation 或 Artifact，要保存必须走
   Workspace ingestion path；Adapter 不能因为「看起来可信」就直接写入。

配套还要把五种「状态」分开，避免 God State：LLM Context（可丢弃）、Interaction Journal
（恢复用 committed inputs）、Artifact Store（大正文）、Long-term Knowledge（跨会话事实）、
Retrieval Index（找候选，非真源）。

### 证据与边界

- **E02**：回答有 citations，且 Ask 不新增 Claim、不跨 workspace 泄漏；
- **E08**：显式 solidify 后保存用户 Claim，Ask 不写、assistant candidate 不写；
- E09：text/conversation/upload/URL 均形成 Artifact，URL 不只保存链接或指令；
- E10：correction、delete、restart、restore 全链，replay 不重复副作用、deleted Claim 不残留；
- E12：冲突/孤立分析与 backlink **必须绑定 source Claim**，projection 不是新写入口；
- L01：最终回答包含本用户事实并**排除另一用户的冲突事实**。

边界：这套能力**还没有通过统一 Agent 入口转化为完整用户闭环**。E14 只贯通了一条 exact-span
保存；「冲突核对后保存」仍是候选 Baseline B，未准入。

### 预期追问

> 为什么不让 Agent 自动记住对话内容？

因为那会让模型的临时推断在下一轮变成「系统已知事实」，而且无法回答「这条事实是谁授权的」。
E08 的反事实就是为此设计的。用户想保存时，走显式入口、只收用户自己写的结论、留下 Receipt。

> 为什么向量库不能当事实源？

它为检索优化，会重建、会延迟、会失败。事实源必须支持明确生命周期、事务和审计。否则一次索引
更新失败就可能覆盖业务事实，而你没有任何地方可以查证原本是什么。

## 10. 验证与完成判定

### 问题本质

Agent 最常见的误判是**把执行成功当成目标完成**。这需要三分，且由不同 owner 判断、互不冒充：

```text
Execution Fact        Tool/Command/Agent 实际执行了什么
Semantic Verification Answer/Artifact 是否被可见证据支持
Domain Completion     领域 Aggregate 是否满足 definition 并进入合法终态
```

### 常见做法与失效

| 做法 | 失效点 |
| --- | --- |
| Tool `ok=true` 即成功 | Web Search 返回结果 ≠ 问题被正确综合 |
| 数据库新增记录即保存正确 | 新增的可能是控制语义（见 B02） |
| verifier 通过后模型再改文本 | 验证失效，用户拿到未验证内容 |
| verifier 可以推翻执行事实 | 失败的 Tool 被说成成功 |

### 本项目选择

先把**架构不变量**和**具体产品能力**分开。Agent 内部 Verification 元能力是：

```text
Goal / Required Result
  -> Candidate Result + Execution Facts + Evidence
  -> Domain Verifier
  -> typed assessment
  -> repair 或 Completion Gate
```

Runtime 拥有必需验证的触发、预算和修复边界；领域 Verifier 拥有开放语义判断；确定性 Admission
校验 Evidence ref、scope 和 digest；Completion Gate 单独判断 required result contract 是否齐全。
Verifier 只能单向判断语义，不能把失败 Tool 说成成功、改变 Receipt 或直接宣告领域完成。

当前实例不能混成一个万能 Verifier：

| 实例 | 触发 | 判断内容 |
| --- | --- | --- |
| Workspace Answer | 候选回答组装后自动触发 | 整体支持、冲突、coverage、unsupported claim |
| Ask/RAG | compose 后固定 stage，repair 后重验 | citation、claim grounding、证据充分性 |
| Project | SubGoal execution/Evidence Admission 后及 final Artifact 后 | requirement 与报告语义满足 |
| Conversation Review | 用户显式要求审查文本时 | 最终文本是否满足冻结的用户明示条件 |

这里的“领域实例”不等于子能力每次都运行完整实例。Ask 调用 Workspace 时只走
`select_evidence()` 取得 EvidenceSpan、Claim 状态和冲突事实；它不会调用
`answer_with_evidence()`，也不会验证一个随后被丢弃的 Workspace 候选回答。只有独立 Workspace
Answer 产品入口才触发 Workspace Answer Verifier，Ask 最终答案只由 Ask Verifier 判断。

Graph 子能力也遵守同一边界：`GraphRetrievalResult` 禁止 `answer` 字段，只输出可追溯
fact/edge/episode/note refs。旧 Microsoft GraphRAG Adapter 只能拿到 CLI synthesized answer，
没有 source/citation binding，已连同生产配置和 answer projection 删除；不能为了“接入了
Provider”就把 answer 拆成 graph fact。

最后一项是文本审查产品用例，不是通用 Verify 的触发前提。它只展示 Runtime-owned trigger、
判据冻结和 verified bytes 的结构性做法
（[ADR 0010](../adr/0010-runtime-owned-interaction-verification.md)）。完整 canonical 架构见
[Verification 与 Completion](../topics/verification-and-completion.md)。

Project Completion Gate 要求全部 active requirement 已 verified 或由用户显式 waived，且 final
Artifact 与 assessment evidence 齐全。普通直接回答不为形式统一伪造 CompletionReport。

### 证据与边界

- **B04 -> E20**：同一 Workspace 核对目标的 baseline 同时展示互斥日期，却未标冲突，并由回答
  组装器写成 `supported`、全部 Claim grounded。E20 将 answer-level verification 独立为唯一写入口，
  返回 `needs_revision/conflicted`，conflict refs 全部绑定本次 citations，Ask 前后 Claim 数不变
  （baseline `20260731T063040.820774Z-16696-c3646c8a`，target
  `20260731T064446.108938Z-8804-52b29d3c`，[ADR 0011](../adr/0011-independent-workspace-answer-verification.md)）；
- **L06**：用户要求审查一段「声称已完成所有写入却缺执行证据」的答复。最终文本不得保留该无证据
  声明，必须经过至少一次语义验证，并等于 passed receipt 的 `verified_draft`。**当前状态：
  9 次真实模型运行 9 次通过**（收回所有权前为 5/9，判据由模型自拟）。收回判据权后判据形状稳定
  为「不能声称写入已经发生，除非有可核验的执行证据」，`ungrounded_spans` 9 次均空。
  值得记录的是收回控制权与判据权**并不足够**：第一次探针 0/3，确定性地以
  `clarification_required` 终止——模型转而向用户索取那份证据。只有 `answer` 会被验证，非 answer
  的 disposition 因此是第三条降级路径，补上拒绝后 9/9
  （[ADR 0010](../adr/0010-runtime-owned-interaction-verification.md)）；
- L06 还展示了一个**测试设计**上的判断：release E2E **不规定 verifier 调用次数**，因为真实用户
  不关心模型在验证前还是验证后先自行修订；两轮 `needs_revision -> passed` 的状态机由 scripted
  Runtime Conformance 测试覆盖。这是「用户可观察结果」与「内部白盒断言」的正确分工——旧版
  L06 因为断言了「两次 verifier」而失败过（archive `20260727T163802`），移除该错误 claim 后通过；
- IP01 target archive `20260729T101501.732689Z-53628-6c5f02f2`：Plan v3、3/3 outcome satisfied、
  5 条 admitted evidence、可读报告、Completion Gate 通过、`environment_failed=false`、86.42 秒。

边界：E20 只准入 Workspace answer-level semantic assessment，尚未准入自动 repair loop、任务级
可执行检查或跨领域统一 contract。下一项必须继续从具体 required result contract 和同输入 paired
baseline 扩展，而**不是做通用反思 Agent**——没有生产消费者和可执行判据的反思轮次只增加 token。

### 预期追问

> verifier 会不会把真实失败说成成功？

不会，这是单向的。verifier 只判断语义标准是否满足，改不了 Tool Receipt 和 Command 执行事实。
架构上把「谁说了算」写死：执行归 Gateway，语义归 Verifier，完成归 Domain 状态机。

## 11. 评估与发布证据

### 问题本质

**「测试通过」和「具备发布证据」是两件事。** 前者属于一次具体执行；后者要求 archive、catalog、
commit、工作树、checksum 全部匹配。而且证据要分级：scripted Port 的诊断证据不能冒充 live
release evidence。

### 常见做法与失效

| 做法 | 失效点 |
| --- | --- |
| mock 单测通过就认为可用 | 只证明局部；真实 Provider 未验证 |
| 只断言正向成功 | 错误副作用没发生这件事从未被证明 |
| Prompt 里写好期望答案或 Tool 名 | 测的是测试作者的方案，不是 Agent 的选择 |
| 测试文件名/Markdown 各自定分类 | 同一个 E17 在不同地方代表不同能力 |

### 本项目选择

**单一分类 owner**：[evidence_catalog.py](../../evals/e2e_quality/evidence_catalog.py) 拥有用例 ID、
pytest test name、evidence kind、evidence layers、capability profile、是否需真实 Provider、
fault mechanism、是否支持发布声明。

**完整矩阵要求**：真实 HTTP 入口进入独立 Web 进程、真实模型、PostgreSQL、场景需要的真实
Provider、不注入中间 Goal/Proposal/Observation。

**同时断言反事实**（这是最值得讲的部分）：错误 digest 不执行、Ask 不写 Claim、跨 workspace
不泄漏、预算耗尽不拼替代答案、能力缺失不换 Tool、replay 不重复副作用。

**自然用户输入**：L01-L06 与 E16-E19 已改为不泄漏内部 Tool、Agent、Artifact、verdict 或执行顺序；
这些只允许出现在**执行后**的 trace 断言里。E16/E18 还专门移除了 Prompt 内的预期答案。

**证据分级**：

```text
E01-E14/E20 原生产品能力    release evidence
C01-C04  组合用户旅程      release evidence
L01-L06  复杂 Interaction  release evidence
E16-E19  外部 Provider     profile，只作为对应旅程的组成证据，不单独产生发布声明
LT01-LT13 durable runtime  diagnostic，scripted/frozen Port，不是 live release evidence
```

**release gate fail closed**：只接受 catalog 分类正确、clean matching revision、passed summary、
trace envelope、checksum 的交集。

### 最值得讲的：baseline-first 方法论

任何新复杂度准入前，**先用同一自然输入从最简生产入口实际执行 baseline 并归档**：

```text
B01 证明旧 Conversation 只能文本确认，无 pending state / Tool call / Claim 写入
  -> B02 证明整消息固化会把「请求保存/先确认」写成 Claim
    -> E14 才准入 exact-span 修复
```

停止条件同样明确：baseline 没失败就停止；失败根因属于环境或测试也停止（例如 Tavily HTTP 432
配额、Firecrawl 402 都被归为 environment failure，**禁止把 Provider 限额误报成产品缺口**）；
只有产品行为失败成立才定义目标 E2E。

### 证据与边界

诚实状态：**当前完整矩阵未在 clean revision 重跑，发布资格 not established**。旧 23/23
（archive `20260726T011631.187395Z-20684-4a62da6a`）因 L01-L06 语义已改，不再匹配当前 catalog；
当前定向 archive 与工作树均为 dirty。所以 gate fail closed 是**预期结果，不是缺陷**。

### 预期追问

> 你怎么知道 Agent 真的做对了？

看反事实。正向结果容易蒙对，反事实很难：错误 digest 拒绝、Ask 后 Claim 数不变、跨 workspace
查不到、预算耗尽时最终消息不含那个随机答案、能力不可用时 `tool_calls=0`。这些断言不成立时，
即使正向用例通过，我也不认为它对。

## 12. 可观测性与故障定位

### 问题本质

Agent 故障定位的第一步是**判断故障发生在哪一层**：语义决策、Admission、执行、验证，还是发布证据。
分不出层，所有问题都会被归因为「Prompt 不好」，然后进入无休止的 Prompt 调参。

### 常见做法与失效

| 做法 | 失效点 |
| --- | --- |
| 只记录最终输入输出 | 无法判断模型是没提 Tool 还是提了被拒 |
| 观测层顺手做兜底 | 观测改变了生产行为，trace 不再反映真实链路 |
| 完整敏感内容进 trace | 凭据与用户隐私外泄 |

### 本项目选择

trace 记录 usage、latency、provider、action order、receipt、verification 和错误分类；
**观测不改变业务行为**，凭据与不必要的完整敏感内容不进 trace。

配套一份**分层定位清单**（以「GitHub 内容没出现在最终回答」为例）：

```text
1. 模型是否提出 GitHub ToolCall？        -> 否：查 EffectiveCapabilities / Tool description / 模型决策
2. 是否被 Admission 拒绝？               -> 查 capability_missing / schema / scope / budget Feedback
3. 是否执行失败？                        -> 查 ToolGateway audit / MCP discovery-mapping / timeout
4. Observation 成功但答案错？            -> 查下一模型轮与 Verifier
5. 用户结果正确但门禁失败？              -> 查 archive revision / clean 状态 / checksum
```

第 5 行是刻意加的：**用户结果正确和具备发布证据是两个独立问题**，混在一起会导致「明明是对的
为什么不让发」这类误判。

测试分层同样有明确分工：

| 层 | 负责证明 |
| --- | --- |
| Unit | 领域状态迁移、digest、纯函数、不变量 |
| Contract | Model/Tool/MCP/A2A/Repository Port 与 Adapter 契约 |
| Integration | PostgreSQL、ToolGateway、Journal、Worker queue 组合 |
| E2E | 正式入口到用户结果及反事实 |
| Offline Eval | 路由、检索、回答、规划、Verifier 质量分布 |
| Online Eval | 线上成功率、延迟、token/cost、失败分布 |

### 证据与边界

这一轴的实战例子很多，例如 `20260729T074104.409971Z-17204-9d2e066f` 证明 `web_search` 的
「搜索 + 两次正文读取」超过旧 20 秒治理窗口——调整为 60 秒后相关 Tool 测试 29 passed。
根因是治理超时的语义边界，不是搜索质量。

边界：**没有 Online Eval 闭环**（线上成功率、延迟、cost、失败分布尚未接入），paired evaluation
的方差数据也尚未积累。上表最后一行目前是设计而非现状，讲的时候要说明。

## 13. 面试使用建议

### 开场

先给第 0 节的自评矩阵，让面试官挑方向。这比自己顺序讲完 12 轴高效，也显得有备而来。

### 按岗位选三轴深讲

| 岗位 | 建议组合 | 理由 |
| --- | --- | --- |
| 通用 Agent / 基础设施 | 1 → 5 → 8 | 决策所有权、受治理副作用、恢复语义 |
| 知识库 / RAG / memory | 9 → 10 → 3 | 记忆污染、验证、上下文边界 |
| 平台 / 工程效能 | 11 → 12 → 4 | 证据纪律、故障定位、能力治理 |
| 偏研究 / 效果优化 | 2 → 7 → 10 | Provider 边界、停止条件、验证设计 |

### 每轴固定三句话

```text
这个轴在解决什么问题
为什么常见做法不够
我怎么做的 + 哪条 E2E 断言了它
```

然后**主动说边界**。这是本文最重要的用法：说不出边界的轴，等于承认理解停在术语层。

### 全程纪律

不要把任何单一 archive 说成「已可发布」或「所有写操作已闭环」。当前口径是：

- 普通 Conversation 由 `ConversationService` 的 typed Interaction loop 拥有；
- Conversation 目前只贯通一条 governed write（E14 exact-span save），不能外推；
- LT01-LT13 是 scripted/frozen Port 的诊断证据；
- 23/23 是 dirty worktree 的工程执行证据，release gate 仍 fail closed。

能清楚说出自己证据的边界，比多报一个通过用例有用得多。

### 说错就掉分的四句话

| 不要说 | 应当说 |
| --- | --- |
| 所有用户请求都会创建 Task/GoalGraph | 直接回答不伪造 Task/Command/CompletionReport |
| LangGraph checkpoint 是当前 Conversation 主链 | 主链是 `ConversationService` 的显式 Interaction loop |
| Agent 已能从自然语言执行全部保存/删除/订阅 | 目前只有 E14 一条 exact-span save |
| 23/23 通过就代表 clean revision 可发布 | 那是 dirty worktree 的定向执行证据 |

同样不能说 Graphiti 或 embedding index 是知识事实源，也不能说 Tool success 代表用户目标完成。
