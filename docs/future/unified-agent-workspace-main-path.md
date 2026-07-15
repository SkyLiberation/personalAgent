# 统一 Agent 工作台主路径设计

本文不考虑对当前 `note/chunk` 模型、旧 `capture_* / ask / research_*` 路由名称、前端 Tab 结构或接口契约的兼容性。目标是重新设计一个更贴近个人知识业务本质的 Agent 工作台。

核心判断：

> 统一工作台不是把 Capture、Ask、Research、Review 放进同一个输入框，而是把它们统一到一条知识生命周期里：Artifact -> Evidence -> Claim -> KnowledgeItem -> KnowledgeState -> Evolution。

Capture / Ask 不再维护独立的 workflow-first 目标文档。其 Artifact / Evidence / Claim 主链路、KnowledgeState 真源和投影边界以本文为准；语义抽取与 grounding 细节见 [语义生命周期抽取非兼容改造设计](semantic-lifecycle-extraction-redesign.md)，当前控制面事实见 [核心架构与主链接入状态](../summary/core-architecture-current-state.md)，剩余并行与 steering 设计见 [并行 Join 与语义 Steering](parallel-steering-runtime-design.md)。

当前工程已经证明了业务型 Agent 的主干能力：统一入口、Executive 控制循环、Governed Procedure、工具治理、长期记忆、证据问答、Research、HITL 和持久化任务。但如果要做真正长期可用的个人知识 Agent，下一阶段不应继续以 note/chunk 或能力模块为中心，而应以知识如何形成、被证据支撑、被使用、被纠错和持续演进为中心。

## 目标定位

统一 Agent 工作台的目标不是更多页面，也不是更多工具，而是一个用户可以长期信任的个人知识系统：

```text
输入资料 / 问题 / 指令 / 反馈
  -> Agent 理解用户目标
  -> 形成 TaskSpec、GoalGraph 和可恢复执行状态
  -> 生成或检索 Artifact / Evidence / Claim
  -> 产出 KnowledgeItem / Answer / Decision
  -> 更新 KnowledgeState / KnowledgeRelation
  -> 后续问答、复习、Research 和纠错继续复用这条链路
```

用户不需要知道 Capture、Ask、RAG、Graph、Procedure。所有能力都表现为：

> 我把资料、问题、判断或反馈交给 Agent；它处理、解释、给证据、要确认、能纠错，并把知识状态维护好。

## 当前工程暴露的问题

从当前代码状态看，目标架构不是凭空发明。工程里已经出现了很多目标模型的局部雏形，但它们分散在不同模块里，没有成为统一知识真源。

### 1. Artifact 目前主要是运行态，不是长期知识来源

当前 `ArtifactRef` 明确是一次 agent run 中可用的用户上传物，注释里也强调它不是默认长期知识。文件上传、网页抓取、Research source、对话片段都已经有“artifact 味道”，但它们没有统一成长期 `Artifact` 对象。

目标设计需要把 Artifact 变成长期可追溯来源：

```text
Artifact
  - artifact_id
  - source_type
  - source_ref
  - content_hash
  - extraction_version
  - owner / workspace
  - raw_location
  - derived_evidence_block_ids
```

否则 Evidence 和 Claim 只能回溯到 note、URL 或 run 里的临时文件，无法稳定回答“这条知识从哪里来”。

### 2. Evidence 已经存在，但还不是知识真源

当前工程已有 `EvidenceItem`、`Citation.evidence_id`、`ContextPack`、EvidenceAssembler、ClaimGrounder 和 answer verifier。Ask 链路已经在事实上使用 evidence 概念。

问题是：这些 Evidence 主要服务一次问答上下文，尚未成为长期可管理对象。Citation 也仍然大量依赖 `note_id / snippet / relation_fact`。

目标设计应把 Evidence 从“检索时临时对象”升级为“长期可引用证据”：

```text
Evidence
  - evidence_id
  - artifact_id
  - locator
  - text_span
  - source_type
  - extraction_method
  - confidence
  - derived_claim_ids
```

这样 citation、verifier、Research 支撑、纠错反馈可以指向同一个 evidence 真源。

### 3. Claim 目前是校验概念，不是长期记忆核心

当前系统已经有几类 claim 原型：

- Ask verifier 会从回答中抽取 claim 并做 grounding。
- Research digest 有 `DigestClaim`、support level、source ids 和 evidence spans。
- Graphiti 抽取 relation facts。
- `NoteVersion` 已经有 superseded、deprecated、conflicted 等状态。

但这些 claim 不是统一实体：

- Ask claim 是回答校验过程中的临时对象。
- DigestClaim 是 Research 简报内部对象。
- Graph fact 是图谱关系事实。
- NoteVersion 状态挂在 note 上，而不是挂在具体主张上。

目标设计必须区分：

| 类型 | 是否长期保存 | 说明 |
| --- | --- | --- |
| `answer_claim` | 默认不长期保存 | 用于校验某次回答，除非用户选择保存结论 |
| `digest_claim` | 可转长期 Claim | Research 简报中的候选主张，需要证据支持和用户反馈 |
| `graph_fact` | 可作为 Evidence 或 Claim 候选 | 需要回溯 Artifact / Evidence |
| `knowledge_claim` | 长期保存 | 个人知识系统的核心事实单元 |

不能把所有生成文本里的句子都直接保存为长期 Claim。长期 Claim 必须有 Evidence、类型、状态和来源。

更准确的 Claim 生命周期应是：

```text
candidate_claim
  -> grounded_claim
  -> verified_claim
  -> active_claim
```

其中：

- `candidate_claim` 是模型或规则抽取出的候选主张。
- `grounded_claim` 已经找到可解释 Evidence 或明确用户陈述来源。
- `verified_claim` 通过规则、verifier、policy 或用户确认。
- `active_claim` 才真正进入长期知识系统。
- `rejected_claim` 被系统或用户拒绝，不进入长期知识。
- `answer_claim` 只服务某次回答校验，默认不进入长期知识。

目标态建议把 `candidate_claim / grounded_claim / verified_claim / active_claim / rejected_claim` 建模为同一张 `claims` 表的不同 `lifecycle_state`，而不是把候选和长期 Claim 分成两套事实对象：

```text
claims.lifecycle_state:
  candidate
  grounded
  verified
  active
  rejected
```

候选噪音通过 `lifecycle_state`、`support_status`、`admission_result` 和索引过滤控制，不进入 active 检索面。这样 answer_claim 转入候选、候选进入 active、rejected 回放和 citation 归因都能复用同一个 Claim ID 链路。

Active Claim 的最低不变量：

- 外部事实类 Claim 必须有 Evidence。
- 用户明确陈述类 Claim 可以把 ThreadMessage 作为 Evidence。
- 助手推断类 Claim 默认不能 active。
- unsupported / contradicted Claim 不能 active。
- 高敏感用户事实需要 memory policy 决定是否确认后保存。

### 4. 版本与冲突现在挂在 Note 上，粒度过粗

当前 `NoteVersion` 已经包含 `superseded / deprecated / conflicted`、confidence、trust level、valid time 等字段。这说明业务已经需要知识状态管理。

问题是状态挂在整条 note 上。真实业务里，通常是一篇资料中的某个主张过期或冲突，而不是整篇资料失效。

目标设计应把状态下沉到 Claim：

```text
KnowledgeItem: 用户可见聚合卡
Claim: 状态和关系的最小单位
KnowledgeStateEvent: Claim 或 KnowledgeItem 的状态变化日志
```

KnowledgeItem 可以因所有核心 Claim 都失效而整体 deprecated，但不能把局部冲突粗暴提升成整篇知识冲突。

### 5. Research 已经接近目标模型，但仍以事件/简报为中心

Research 侧已经有 Source、Event、DigestClaim、support level、PersonalRelevance、feedback、save event 等结构，离 Artifact/Evidence/Claim 目标模型最近。

当前主要问题是 PersonalRelevance 仍然依赖 `related_note_ids`，Research event 入库容易变成一条摘要知识，而不是进入统一 Claim 演进链路。

目标设计应把 Research source/event 直接映射为：

```text
ResearchSource -> Artifact
ResearchEvent -> Candidate Claim group
DigestClaim -> Candidate Claim
support_level/source_ids -> Evidence support
PersonalRelevance -> KnowledgeRelation candidate
feedback/save -> Decision
```

这样 Research 就不是独立情报模块，而是外部变化驱动的知识演进机制。

### 6. Review 与 Gap 仍偏 Note/Card，不是 Claim State

当前 ReviewCard 以 note 为核心，Knowledge Gap 也主要围绕笔记/图谱连接发现问题。目标架构下，Review 和 Gap 应更多依赖 Claim 状态：

- active 且高价值 Claim 进入复习。
- uncertain Claim 进入澄清。
- conflicted Claim 进入冲突解决。
- superseded Claim 不应继续复习。
- 用户复习反馈应更新用户对 Claim 的记忆状态，而不是只更新 card 间隔。

这意味着需要拆出 `claim_review_state` 或类似模型，避免复习系统继续被 note 粒度限制。

## 核心对象

新的知识核心对象应从 `note/chunk` 升级为以下模型：

| 对象 | 含义 |
| --- | --- |
| `Workspace` | 用户的知识工作区 |
| `Thread` | 用户和 Agent 的交互上下文 |
| `Task` | 一次用户目标的执行单元 |
| `WorkflowRun` | 真实可恢复执行过程 |
| `Artifact` | 原始输入或外部资料，例如网页、PDF、上传文件、对话片段、Research source |
| `Evidence` | 可定位、可引用、可回溯的证据片段 |
| `Claim` | 结构化事实、观点、偏好、判断、计划或不确定结论 |
| `KnowledgeItem` | 用户可见知识卡，可聚合多个 Claim |
| `KnowledgeRelation` | duplicate / supplement / supersede / conflict / derived_from |
| `KnowledgeState` | active / uncertain / conflicted / superseded / deprecated / deleted |
| `Decision` | 用户确认、拒绝、纠错、反馈 |
| `ExtractionRun` | 从 Artifact 生成 Evidence / Claim 的可重放抽取过程 |
| `GraphProjection` | 从 Evidence / Claim 投影到图谱的实体、关系和事实 |
| `ClaimReviewState` | 用户对某个 Claim 的记忆状态和复习计划 |

对象关系：

```text
Artifact
  -> Evidence
  -> Claim
  -> KnowledgeItem
  -> KnowledgeRelation
  -> KnowledgeState
```

原则：

- `Evidence` 必须能回溯到 `Artifact`。
- `Claim` 必须能回溯到一个或多个 `Evidence`。
- `KnowledgeItem` 是用户可见卡片，不是唯一事实源。
- `KnowledgeRelation` 表达知识之间的重复、补充、替代、冲突和来源关系。
- `KnowledgeState` 记录知识状态，而不是靠覆盖文本隐式表达。

这个模型要能回答：

- 这条知识从哪里来？
- 它由哪些证据支撑？
- 它是用户事实、外部事实、偏好、计划、判断，还是助手推断？
- 它和旧知识是重复、补充、替代还是冲突？
- 它是否仍有效？
- 它被哪些回答引用过？
- Research 新事件是否改变了它？

## 四层架构

### 1. 用户层：统一任务流

用户层只有一个默认工作区：

```text
左侧：会话 / 最近知识 / 待确认 / 今日复习 / Research 事件
中间：统一输入和任务流
右侧：当前任务的证据、知识关系、引用和状态
```

中间任务流展示四类核心卡片：

- `KnowledgeItemCard`：采集或整理后形成的知识卡。
- `AnswerCard`：基于 Evidence / Claim 生成的回答。
- `DecisionCard`：需要用户确认、澄清、拒绝或选择的动作。
- `ResearchEventCard`：外部事件及其对个人知识的影响。

### 2. 语义层：Goal / Task / Decision

语义层描述用户想达成什么，以及系统如何组织任务，但不直接执行副作用。

```text
UserInput
  -> Goal
  -> TaskPlan
  -> WorkflowRun
```

`Goal` 描述用户目标，例如：

- ingest artifact
- answer with evidence
- solidify conversation claims
- revise knowledge
- resolve conflict
- research external change
- review due knowledge

`TaskPlan` 描述任务依赖，例如：

```text
用户：保存这个 PDF，并告诉我三个风险点，然后把结论也记住。

Goal 1: ingest_artifact
Goal 2: answer_from_new_artifact
Goal 3: solidify_answer_claims

Task 1: ingest document
Task 2: grounded analysis over Task 1 artifact
Task 3: capture verified conclusion from Task 2
```

关键边界：

- Goal / Task 不拥有工具执行权。
- 高风险动作不能由模型直接授权。
- 目标引用、证据策略和依赖关系可以由语义层提出，但必须被 GoalGraph、GoalDecompositionValidator、TaskSpec revision validator 和 policy 校验。
- TaskPlan 只能引用 Artifact / Evidence / Claim / KnowledgeItem 的 ID 或候选 ID，不能直接携带不可校验的大段模型结论作为执行真源。

### 3. 知识层：Claim / Evidence / State

知识层是新架构的核心。所有长期记忆都应围绕 Claim 和 Evidence 管理。

Claim 类型至少包括：

| 类型 | 含义 |
| --- | --- |
| `user_fact` | 用户明确陈述的事实 |
| `user_preference` | 用户偏好 |
| `user_plan` | 用户计划或待办 |
| `external_fact` | 外部资料中的事实 |
| `analysis_judgment` | 系统或用户形成的判断 |
| `uncertain_claim` | 证据不足或待确认结论 |
| `assistant_inference` | 助手推断，默认不能直接作为长期事实 |

Claim 粒度必须收敛，否则系统会产生大量低价值、重复或弱证据主张。一个可长期保存的 Claim 至少应满足：

- 只表达一个核心判断。
- 有明确主体。
- 有明确类型。
- 有来源归属：用户、外部资料、助手、Research source 或系统分析。
- 有作用范围，例如 topic、workspace、valid_time 或 source scope。
- 有 evidence set，或明确标记为 user asserted。
- 有 canonical key，用于去重、聚合和冲突检测。
- 初始状态不能默认 active。

不应直接保存的例子：

```text
用户可能更偏好复杂 Agent 架构。
```

这是助手推断，只能成为 `assistant_inference` 候选，不能直接 active。

可保存但需要来源边界的例子：

```text
这篇文章认为 GraphRAG 适合多跳知识检索。
```

这是带来源归属的 `external_fact`。不能被泛化成“GraphRAG 一定适合所有多跳知识检索”。

KnowledgeState 至少包括：

| 状态 | 含义 |
| --- | --- |
| `active` | 当前有效 |
| `uncertain` | 证据不足或待确认 |
| `conflicted` | 与其他 Claim 冲突 |
| `superseded` | 被新 Claim 替代 |
| `deprecated` | 过期或不再推荐使用 |
| `deleted` | 用户删除，但保留可恢复状态链 |

KnowledgeRelation 至少包括：

| 关系 | 含义 |
| --- | --- |
| `duplicate` | 重复知识 |
| `supplement` | 新知识补充旧知识 |
| `supersede` | 新知识替代旧知识 |
| `conflict` | 新旧知识矛盾 |
| `derived_from` | 由来源或上游结论派生 |
| `cited_by` | 被回答或研究引用 |

KnowledgeRelation 不应只支持 Claim-to-Claim。真实业务里既有 Claim 粒度关系，也有产品聚合层关系。推荐设计成多态关系：

```text
source_type: claim | knowledge_item | artifact | research_event
source_id
target_type: claim | knowledge_item | artifact | research_event
target_id
relation_type
confidence
evidence_span_ids
decision_id
```

例如：

- Claim A conflict Claim B。
- KnowledgeItem A 属于同一主题 KnowledgeItem B。
- ResearchEvent 补充某个 KnowledgeItem。
- Artifact derived_from ResearchSource。

### 4. ClaimAdmissionPolicy

Claim 类型不同，准入策略必须不同。不能因为系统抽取出 Claim，就默认进入长期 active。

`ClaimAdmissionPolicy` 负责判断：

```text
这个 Claim 能否进入 active？
需要哪些 Evidence？
是否需要 DecisionCard？
是否允许自动保存？
是否需要过期时间？
是否涉及敏感信息？
```

基础策略：

| Claim 类型 | Evidence 要求 | 是否可自动 active | 确认策略 |
| --- | --- | --- | --- |
| `external_fact` | 必须有外部 Evidence | 可自动，但依赖 source trust 和 support_status | 通常不需要 |
| `user_fact` | ThreadMessage 可作为 Evidence | 低敏可自动 | 高敏必须确认 |
| `user_preference` | 用户明确表达即可 | 可自动，但必须可撤回 | 通常不需要 |
| `user_plan` | 用户明确表达即可 | 不一定进入长期知识，也可能进入 task/reminder | 视场景 |
| `analysis_judgment` | Evidence + 推理摘要 | 默认 candidate / verified，不建议直接 active | 常需要确认 |
| `assistant_inference` | 不能作为事实 Evidence | 默认不能 active | 若保存必须确认 |
| `uncertain_claim` | 证据不足 | 不能 active | 需要澄清 |

准入决策应输出：

```text
admission_result: allow_active | keep_candidate | require_decision | reject
reason
required_evidence
decision_policy
memory_policy
retention_policy
```

`ClaimAdmissionPolicy` 应作为所有长期 Claim 写入的唯一入口。无论 Claim 来自 Capture、Ask、Conversation solidify、Research digest 还是 GraphProjection candidate，都不能绕过准入策略直接写入 active。

它不应和 `DecisionPolicy` 合并实现：

| 策略 | 负责的问题 | 典型输出 |
| --- | --- | --- |
| `ClaimAdmissionPolicy` | 某个 Claim 能不能成为长期知识 | allow_active / keep_candidate / require_decision / reject |
| `DecisionPolicy` | 某个动作是否需要用户确认、如何展示风险 | auto_execute / ask_confirmation / block |

`ClaimAdmissionPolicy` 可以调用 `DecisionPolicy`，但 `DecisionPolicy` 还要服务删除、恢复、替代、冲突解决、高敏 Research 入库等动作。不要把它做成 Claim 准入内部的枚举。

### 5. EvidenceBlock / EvidenceSpan

Evidence 粒度必须控制，否则系统会在两个极端之间摆动：

- Evidence 太小：每句话一个 Evidence，数量爆炸，检索和展示困难。
- Evidence 太大：整段或整页作为 Evidence，citation 不精确，verifier 难判断。

推荐拆成两层：

```text
EvidenceBlock
  - evidence_block_id
  - artifact_id
  - locator
  - section / page / paragraph
  - full_context
  - extraction_run_id

EvidenceSpan
  - evidence_span_id
  - evidence_block_id
  - start_offset
  - end_offset
  - text_span
  - quote_hash
  - claim_ids
```

原则：

- citation 指向 `EvidenceSpan`。
- 回答和 UI 展开时可展示 `EvidenceBlock`。
- verifier 可以使用 Span 做精确判断，也可以回看 Block 获取上下文。
- 同一段原文不应因为多个 Claim 被重复存成多个孤立 Evidence。

### 6. Support Status 与 KnowledgeState

`support_status` 和 `KnowledgeState` 必须严格区分：

| 字段 | 含义 | 示例 |
| --- | --- | --- |
| `support_status` | 证据是否支持该 Claim | supported / partially_supported / unsupported / contradicted / user_asserted |
| `KnowledgeState` | 该 Claim 在知识系统中的业务状态 | active / uncertain / conflicted / superseded / deprecated / deleted |

它们不是一回事：

- 一个 Claim 可以 supported，但仍然 superseded。
- 两个 Claim 都 supported，但彼此 conflicted。
- 用户明确陈述的 Claim 可以是 user_asserted，而不是 unsupported。
- contradicted 通常不能 active，应进入 rejected 或 conflicted。

状态转移应由以下因素共同决定：

```text
support_status + claim_type + decision_policy + sensitivity_level -> allowed KnowledgeState transition
```

最小状态转移表：

| 转移 | 条件 |
| --- | --- |
| candidate -> grounded | 找到 Evidence 或 user_asserted 来源 |
| grounded -> verified | 通过 verifier / rule / policy |
| verified -> active | ClaimAdmissionPolicy 允许，且无需确认或用户已确认 |
| candidate / grounded / verified -> rejected | unsupported、contradicted、低价值、用户拒绝 |
| active -> conflicted | 新 Claim 与其冲突，且冲突候选超过阈值 |
| active -> superseded | 用户确认新 Claim 替代旧 Claim |
| active -> deprecated | 过期、来源失效、不再推荐或用户降权 |
| active / conflicted / deprecated -> deleted | 用户删除，写入 KnowledgeStateEvent |

每个状态转移都必须记录：

```text
actor
reason
evidence_span_ids
grounding_run_id
decision_id
policy_result
created_at
```

`support_status` 与 `KnowledgeState` 之外，还需要明确两个策略层字段，避免命名混乱：

| 字段 | 层次 | 说明 |
| --- | --- | --- |
| `support_status` | 证据层 | 当前证据是否支持 Claim |
| `admission_result` | 准入层 | ClaimAdmissionPolicy 对长期入库的判断 |
| `decision_policy` | 决策层 | 是否需要用户确认、阻断或自动执行 |
| `knowledge_state` | 业务生命周期层 | Claim 在知识系统里的当前状态 |

`support_status` 可以在 `claims` 上保留当前投影值，但权威来源应是 `grounding_runs` 或 `claim_support_events`。证据变化、Research 发现反例、用户补充来源时，应追加支撑状态事件，再更新 Claim 当前投影。

还应把非法状态转移作为 critical invariant，而不是只靠产品约定：

| 禁止转移 | 原因 |
| --- | --- |
| unsupported -> active | 证据不足不能成为可信长期知识 |
| contradicted -> active | 已被反证的 Claim 必须先进入冲突处理或拒绝 |
| assistant_inference -> active | 助手推断不能直接变成用户事实 |
| user_denied -> active | 用户拒绝后不能被后台流程重新激活 |
| sensitive_claim -> active without decision | 高敏知识必须经过 DecisionPolicy |
| graph_fact -> active | 图谱投影不是事实源，必须回链 Evidence / Claim 并重新准入 |

这些非法转移必须进入 fixture/replay gate 和 e2e scorer，一旦发生就是 critical failure。

### 7. 执行层：Executive 与 Governed Procedure

即使不考虑兼容性，也不应让 LLM 自由执行一切，但也不能把每个业务动词固化成流程。开放式抽取、证据回答、冲突分析、Research 和知识缺口检查由 Executive 组合元能力；只有需要保护稳定不变量的写入、删除、固化、订阅创建等事务进入 Governed Procedure。

每个 Procedure 必须声明：

```text
steps
input artifacts
output artifacts
tools
risk
confirmation
side_effects
recovery
user_visible_events
audit policy
```

保留的安全边界：

```text
LLM 理解语义并提出有界决策
Executive 根据 Observation 控制开放任务
Procedure 保护事务不变量和副作用顺序
Policy 控制权限
Evidence 控制回答
User confirmation 控制高风险动作
```

## 理想知识生命周期

完整主路径：

```text
1. 用户提交资料、问题、对话结论或反馈
2. 系统生成 Goal 和 TaskPlan
3. Executive action 或 Procedure node 生成 Artifact
4. 系统抽取 Candidate Claims
5. 系统建立 Evidence
6. 系统生成 KnowledgeItem
7. 系统检测与旧知识的关系
8. 用户确认重要变更或高风险动作
9. 后续 Answer 基于 Evidence / Claim
10. 用户纠错回写 Claim / Evidence / KnowledgeState
11. Research 事件进入同一知识演进链路
12. Review / Gap 基于 KnowledgeState 选择提醒对象
```

在这个模型下：

- Capture 是 Artifact 到 Evidence / Claim / KnowledgeItem 的形成过程。
- Ask 是 Evidence / Claim 的受控再使用过程。
- Research 是外部事件对已有 Claim 的挑战、补充或更新过程。
- Review 是 KnowledgeState 和用户记忆状态的再激活过程。
- Delete 不是物理删除文本，而是更新 KnowledgeState 并保留恢复链。
- Graph 不是独立知识真源，而是 Evidence / Claim 的关系投影。

领域模型上，Active Claim 必须能回溯 Evidence 或明确用户陈述来源；但执行顺序不必永远先 Evidence 后 Claim。不同 workflow 可以走两种路径：

```text
路径 A：先 Evidence 后 Claim
Artifact -> chunks / spans -> Evidence -> CandidateClaim

路径 B：先 CandidateClaim 后 Grounding
Artifact -> CandidateClaim -> grounding -> Evidence
```

路径 A 适合网页、PDF、上传文件等结构化来源；路径 B 适合 Research digest、对话固化、回答校验和长文摘要。系统不变量不是“执行顺序必须先 Evidence”，而是：

- Active Claim 必须有可解释来源。
- 外部事实类 Claim 必须有 Evidence。
- 用户明确陈述类 Claim 可以用 ThreadMessage 作为 Evidence。
- answer_claim 可以临时存在，但默认不进入长期知识。

## 主业务闭环

### 1. 采集到证据问答

目标路径：

```text
用户提交文本 / URL / 文件
  -> ingest_knowledge
  -> Artifact
  -> Evidence
  -> Candidate Claims
  -> KnowledgeItem
  -> 用户追问
  -> answer_with_evidence
  -> AnswerCard + citations
  -> verification / repair
```

关键要求：

- 保存后不只是出现一条 note，而是形成可引用 Evidence 和可验证 Claim。
- 回答不能凭空创建 citation。
- citation 必须能定位到 Evidence。
- 回答中的关键结论应能追溯到 Claim。

Ask 的最低要求是 evidence-grounded，增强要求才是 claim-aware。也就是说，用户刚上传 PDF 后立即追问时，系统不应为了先抽完所有长期 Claim 而阻塞回答：

```text
Evidence-grounded answer
  -> 临时 answer_claim 校验
  -> 用户选择保存结论
  -> solidify_conversation_claims / revise_knowledge
  -> long-term Claim
```

长期 Claim 是保存和演进的核心，不是每次回答的前置条件。

### 2. 问答纠错到知识更新

目标路径：

```text
回答不准 / citation 不对
  -> 用户反馈
  -> 定位 AnswerCard / Evidence / Claim
  -> 判断错误类型
  -> revise_knowledge 或重新 answer_with_evidence
  -> 更新 KnowledgeState
```

错误类型至少区分：

- 没有检索到相关 Evidence。
- Evidence 选错。
- Evidence 正确但生成误读。
- Claim 已经过期。
- Claim 与其他知识冲突。
- 用户问题需要澄清。

纠错不应只记录 UI 点踩，而应进入 Claim / Evidence / KnowledgeState。

### 3. 会话固化到长期知识

目标路径：

```text
用户说“把刚才结论记住”
  -> solidify_conversation_claims
  -> 从 Thread 中选择候选 Claim
  -> 区分用户确认事实 / 助手推断 / 临时假设 / 待办
  -> 生成 EvidenceBlock / EvidenceSpan 或 user_asserted 来源
  -> 必要时 DecisionCard 确认
  -> 写入 KnowledgeItem / Claim
```

必须避免：

- 把助手猜测直接固化为用户知识。
- 把用户临时假设固化为长期事实。
- 把已被用户否定或修正的旧事实继续入库。
- 把“帮我保存一下”这句指令本身入库。

### 4. 知识演进与冲突治理

目标路径：

```text
新 Claim 形成
  -> 查找相关旧 Claim
  -> 判断 duplicate / supplement / supersede / conflict
  -> 生成用户可理解的演进建议
  -> 用户确认
  -> 更新 KnowledgeRelation / KnowledgeState
```

这应成为默认主循环，而不是后台整理工具。

### 5. Research 与个人知识碰撞

Research 不应只是“每天总结新闻”。它应回答：

- 这个外部事件和我已有知识有什么关系？
- 它是否补充了某个 Claim？
- 它是否推翻或削弱了某个 Claim？
- 它是否和我的长期关注目标有关？
- 我之前不感兴趣的主题是否应降低权重？

目标路径：

```text
research_external_change
  -> external Artifact / Event
  -> Evidence
  -> Candidate Claims
  -> 与已有 Claim 对照
  -> supplement / supersede / conflict / irrelevant
  -> ResearchEventCard
  -> 用户反馈
  -> 更新 KnowledgeRelation / subscription preference
```

Research relevance 不应只依赖已有 Claim，否则系统会失去探索能力。Research 相关性应来自三类信号：

| 信号 | 含义 |
| --- | --- |
| `existing_claim_match` | 与已有 Claim 相关，用于知识演进 |
| `explicit_subscription` | 用户主动订阅的主题 |
| `exploratory_interest` | 从长期兴趣和反馈推断出的探索方向 |

第一类服务知识演进，第二类服务订阅，第三类服务发现。三者需要分开记录和评估。

Research 的负反馈也必须结构化，否则“不感兴趣”只会变成一个粗糙降权信号。

| negative_feedback_reason | 应调整的对象 |
| --- | --- |
| `topic_not_interested` | topic weight |
| `source_not_trusted` | source trust |
| `duplicate_or_known` | duplicate filter / novelty threshold |
| `too_shallow` | depth preference |
| `too_frequent` | cadence |
| `not_relevant` | relevance model |
| `already_covered` | existing Claim matching / novelty threshold |

同时需要 `interest_decay_policy`，让长期未反馈、反复忽略或持续不相关的主题逐步降权，而不是永久占用 Research 配额。

## 产品形态

### KnowledgeItemCard

采集或整理成功后展示：

- 标题。
- 摘要。
- Claim 列表。
- Evidence 概览。
- 来源 Artifact。
- KnowledgeState。
- 相关 KnowledgeRelation。
- 可追问、修正、合并、标记冲突、删除。

### AnswerCard

回答必须包含：

- 直接回答。
- citation。
- 支撑 Claim。
- 不确定性提示。
- 相关 KnowledgeItem。
- 反馈入口。
- 保存本次结论入口。

### DecisionCard

用于澄清、确认、删除、恢复、冲突解决、批量替换等动作。

必须包含：

- Agent 准备做什么。
- 影响哪些 KnowledgeItem / Claim / Evidence。
- 为什么需要确认。
- 确认 / 拒绝 / 修改 / 需要更多信息。

DecisionCard 不能泛滥。不是所有不确定性都需要打扰用户，因此必须引入 `decision_policy`：

| 类型 | 处理方式 | 例子 |
| --- | --- | --- |
| `must_confirm` | 必须展示 DecisionCard | 删除、恢复、替代旧知识、冲突解决、把助手推断写成长期事实、高敏感用户事实入库、批量修改 |
| `auto_with_notice` | 自动执行但在任务流提示 | 低风险补充、明确重复合并建议、citation 修复、非核心 Claim 降权 |
| `silent_record` | 不打扰用户，只记录事件 | 低置信度候选 Claim 被丢弃、unsupported claim 被阻止 active、graph projection 失败 |

HITL 应控制真正影响长期知识状态的动作，而不是控制每个抽取细节。

### ResearchEventCard

Research 输出不应是长文本摘要，而应是可操作事件：

- 事件标题。
- 来源 Evidence。
- 可信度状态。
- 关联或冲突的已有 Claim。
- 为什么推荐给用户。
- 有用 / 不感兴趣 / 收藏 / 入库 / 标记冲突。

## Task 与 Procedure 映射

| 用户表达 | Task/Procedure 边界 | 说明 |
| --- | --- | --- |
| “帮我记住这段话” | `ingest_knowledge` | 形成 Artifact / Evidence / Claim / KnowledgeItem |
| 粘贴 URL | `ingest_knowledge` | URL 是 Artifact 来源 |
| 上传文件 | `ingest_knowledge` | 文件先形成 Artifact，再形成 Evidence 和 Claim |
| “这篇文章讲了什么” | `answer_with_evidence` | 回答消费 Evidence / Claim |
| “保存这个文件，并总结风险” | `ingest_knowledge -> answer_with_evidence` | 复合任务通过 artifact 依赖串联 |
| “把刚才结论记住” | `solidify_conversation_claims` | 固化已确认 Claim |
| “整理最近关于 X 的知识” | `consolidate_topic` | 整理 Claim 和 KnowledgeRelation |
| “删掉之前那条 X” | `delete_or_restore_knowledge` | 更新 KnowledgeState 并保留恢复链 |
| “这两条说法冲突吗” | `resolve_conflict` | 冲突解决是一等 workflow |
| “每天关注 X” | `research_external_change` | 外部事件进入知识演进链路 |
| “这个研究事件有用，存起来” | `research_external_change -> ingest_knowledge` | 入库时建立 relation，而不是孤立保存 |

## 存储模型

建议核心表或领域模型：

```text
workspaces
threads
tasks
workflow_runs
artifacts
extraction_runs
evidence_blocks
evidence_spans
grounding_runs
claim_support_events
claims
claim_admission_decisions
knowledge_items
knowledge_relations
knowledge_state_events
decisions
answer_cards
research_events
review_items
claim_review_states
graph_projections
projection_jobs
```

关键设计：

- `claims` 是长期知识的核心事实单元。
- `evidence_blocks` 是可展开上下文块。
- `evidence_spans` 是 citation 和 verifier 的精确事实源。
- `knowledge_items` 是用户可见聚合卡，不替代 Claim。
- `extraction_runs` 记录某次抽取使用的模型、规则、版本、输入 Artifact 和产出的 Evidence / Claim。
- `grounding_runs` 记录 Claim 与 Evidence 的支撑性判断过程。
- `claim_support_events` 记录支撑状态变化来源，`claims.support_status` 只是当前投影。
- `claim_admission_decisions` 记录 ClaimAdmissionPolicy 的准入判断。
- `knowledge_state_events` 使用 append-only 事件记录状态变迁。
- `knowledge_relations` 显式表达补充、替代、冲突和来源。
- `decisions` 记录用户确认、拒绝、纠错和反馈。
- `claim_review_states` 记录用户对 Claim 的记忆状态、复习间隔和反馈。
- `graph_projections` 记录 Claim / Evidence 到图谱实体关系的投影结果，不作为原始事实源。
- `projection_jobs` 记录索引、UI 卡、图谱、复习计划等投影任务的 pending / completed / failed / retrying 状态；投影失败不回滚 Artifact / Evidence / Claim。

典型投影任务包括 `project_evidence_indexes`、`project_claim_indexes`、`project_ui_card`、`project_graph`、`project_review`。这些任务可以由 ingest 或 claim lifecycle enqueue，但执行结果不改变事实真源。

关键字段建议：

```text
Claim
  - claim_id
  - workspace_id
  - claim_type
  - statement
  - canonical_statement
  - subject / predicate / object
  - scope
  - valid_time
  - source_attribution
  - confidence
  - support_status
  - state
  - sensitivity_level
  - memory_policy
  - retention_policy
  - created_from
  - created_by
  - evidence_span_ids
  - canonical_key

EvidenceBlock
  - evidence_block_id
  - artifact_id
  - locator
  - full_context
  - source_type
  - extraction_run_id
  - confidence
  - modality
  - created_at

EvidenceSpan
  - evidence_span_id
  - evidence_block_id
  - start_offset
  - end_offset
  - text_span
  - quote_hash
  - claim_ids

GroundingRun
  - grounding_run_id
  - claim_id
  - evidence_span_ids
  - support_status
  - verifier
  - verifier_version
  - rationale
  - created_at

ClaimSupportEvent
  - event_id
  - claim_id
  - from_support_status
  - to_support_status
  - grounding_run_id
  - reason
  - actor
  - created_at

ClaimAdmissionDecision
  - admission_id
  - claim_id
  - admission_result
  - reason
  - required_evidence
  - decision_policy
  - memory_policy
  - retention_policy
  - created_at

KnowledgeStateEvent
  - event_id
  - target_type
  - target_id
  - from_state
  - to_state
  - reason
  - actor
  - decision_id
  - created_at

Decision
  - decision_id
  - decision_type
  - proposed_action
  - impact_set
  - risk_level
  - policy_reason
  - user_response
  - created_at
  - resolved_at
```

其中 `memory_policy`、`sensitivity_level` 和 `retention_policy` 对个人知识 Agent 很关键。用户事实、偏好和敏感信息不能默认长期保存，应支持：

```text
auto_save_allowed
requires_user_confirmation
never_store
expires_after
```

## 用户级事件

前端主路径不应消费底层调试事件，而应消费用户级事件：

```text
task_started
artifact_created
evidence_ready
claim_candidates_ready
knowledge_item_created
answer_delta
answer_completed
citation_ready
decision_required
knowledge_state_changed
research_event_ready
task_failed
task_retriable
```

底层 tool audit、checkpoint、workflow event、policy decision 继续存在，但只作为调试和治理层。

## 阶段计划

### P0 工程冻结线

P0 的目标不是完整个人知识系统，而是证明知识主链路可靠。第一冻结线应先证明 Artifact / Evidence / EvidenceRef 能成为事实主链路，再逐步接入 Claim、Admission 和 AnswerClaim verify：

```text
Artifact -> EvidenceBlock / EvidenceSpan -> evidence-grounded Answer
CandidateClaim -> Grounding -> ClaimAdmissionDecision 作为可恢复增强链路逐步接入
```

P0 必须实现：

- `Artifact`
- `ExtractionRun`
- `EvidenceBlock`
- `EvidenceSpan`
- `EvidenceRef`
- 最小 `KnowledgeItem` 投影
- evidence-grounded Answer

P0 分阶段引入：

- P0a 只冻结 Artifact / Evidence / EvidenceRef。
- P0b 让 Ask 基于 Evidence 回答，不等待长期 Claim。
- P0c 再引入 CandidateClaim / Grounding / ClaimAdmissionDecision。
- P0d 最后引入 answer_claim 级 verify。
- P0e 补齐 KnowledgeItemCard 的部分投影状态。

P0 不应实现完整 Research、Review、GraphProjection 和运营看板；这些能力可以保留接口或 fixture，但不能影响主链路验收。P0 成功的定义是：资料能形成可引用证据，Ask 能引用 Evidence，证据不足时不强答，Claim 抽取失败不回滚 Artifact / Evidence，候选 Claim 不会错误 active，回答结论不会默认入库。

### P0a：Artifact + Evidence + EvidenceRef

目标：先保证来源和证据稳定，不急着把所有内容变成长期 Claim。

P0a 文件解析范围必须收窄：必须支持 plain text / markdown、HTML / URL snapshot、带页码的 text-based PDF；简单表格 cell locator 可选；Word、PPT、Excel、图片 OCR、扫描件 PDF、多栏论文和复杂跨页表格后置。

验收任务：

1. 用户提交文本、URL 或文件后生成 Artifact。
2. 系统记录 ExtractionRun，并从 Artifact 中生成 EvidenceBlock / EvidenceSpan。
3. EvidenceBlock 可定位回 Artifact。
4. EvidenceBlock 记录 artifact_id、locator、full_context、source_type 和 extraction_run_id。
5. EvidenceSpan 记录 evidence_block_id、start_offset、end_offset、text_span 和 quote_hash。
6. EvidenceRef 可解析到 EvidenceSpan / EvidenceBlock / Artifact。
7. Web、Research 和 Thread citation 必须落到不可变或可版本化快照。
8. ExtractionRun 可追踪模型、规则、版本、输入和输出。

### P0b：最小证据问答

目标：先让 Ask evidence-grounded，再逐步 claim-aware。

ContextPack 应携带 `evidence_coverage: complete | partial | sparse | none` 和 `missing_sections`。当 Evidence 只覆盖部分页面、章节或元素时，Ask 可以基于已有 Evidence 回答覆盖范围内的问题，但必须对覆盖不足的部分保守说明。

验收任务：

1. Answer 引用 Evidence。
2. citation 可点击定位 EvidenceRef。
3. 证据不足时不强答。
4. Ask 不等待 CandidateClaim 全量抽取。
5. compose 只消费 ContextPack，不做隐藏检索。

### P0c：CandidateClaim + Grounding + Admission

目标：引入 Claim，但只到候选、支撑和准入状态，不默认进入长期 active。

验收任务：

1. 系统从 Artifact 或 Evidence 抽取 Candidate Claims。
2. 每个 CandidateClaim 都能看到 evidence_span_ids 或 user_asserted 来源。
3. GroundingRun 产出 support_status，并追加 ClaimSupportEvent。
4. ClaimAdmissionDecision 记录 allow_active / keep_candidate / require_decision / reject。
5. unsupported / contradicted Claim 不进入 active。
6. candidate / grounded / verified / active / rejected 状态分开。
7. Claim canonical_key 可用于去重和冲突检测。
8. Claim 抽取、grounding 或 admission 失败不回滚 Artifact / Evidence。

### P0d：AnswerClaim Verification

目标：回答中临时 claim 可校验，但不污染长期知识。

验收任务：

1. answer_claim 可临时校验。
2. answer_claim 逐条关联 EvidenceRef。
3. unsupported answer_claim 触发 repair、降级或拒答。
4. answer_claim 默认不保存为长期 Claim。
5. 只有用户明确保存结论时，answer_claim 才转为 CandidateClaim 并重新走 Admission。

### P0e：KnowledgeItemCard 部分投影

目标：形成用户可见聚合，但不把 KnowledgeItem 当作唯一事实源，也不等待所有 Claim 完成后才展示。

验收任务：

1. Artifact 创建后即可生成最小 KnowledgeItemCard。
2. Evidence 完成后更新 Evidence 概览。
3. Claim admission 完成后更新 Claim 列表和 KnowledgeState projection。
4. KnowledgeItem 支持 `primary_state: indexing / evidence_ready / ready / partial_failed`，并用 flags 表达 `claims_pending / index_projection_pending / graph_projection_pending / review_projection_pending`。
5. 用户可以从 KnowledgeItem 展开到 Claim 和 Evidence。
6. 删除不物理抹除知识，而是写入 KnowledgeState 变更。

### P1：证据问答主路径

目标：Ask 先做到 evidence-grounded，再做到 claim-aware。

验收任务：

1. 用户问刚采集资料中的问题，回答引用 Evidence。
2. AnswerCard 中关键结论可追溯到 Claim。
3. 证据不足时明确拒绝强答。
4. citation 错误反馈能定位 Evidence。
5. 回答错误能区分检索错误、生成误读、知识过期和 Claim 冲突。
6. 回答中临时抽取的 answer_claim 不会默认写入长期 Claim，除非用户选择保存结论。

### P2：会话固化与纠错闭环

目标：长期记忆只固化可信 Claim，纠错能回写知识状态。

`solidify_answer_claims` 必须复用 ClaimAdmissionPolicy。用户明确“保存这个结论”只代表允许 answer_claim 转为 candidate Claim 并进入准入流程，不代表可以绕过 grounding、冲突检查、敏感信息策略或用户确认直接 active。

验收任务：

1. `solidify_conversation_claims` 不固化助手推断和临时假设。
2. 用户确认后才把高风险或不确定 Claim 写为 active。
3. 用户修改答案或知识后，Claim 状态发生变更。
4. 被纠错的 Evidence / Claim 可进入 eval 或回归样本。
5. 恢复、删除、替换都通过 DecisionCard 确认。
6. ThreadSummary 中的 assistant assumptions / unverified claims 只能作为候选，不能直接变成 active Claim。

### P3：知识演进与冲突解决

目标：新知识进入系统时自动处理与旧知识的关系。

验收任务：

1. 新 Claim 入库后查找相关旧 Claim。
2. 系统能生成 duplicate / supplement / supersede / conflict 建议。
3. 用户确认后更新 KnowledgeRelation。
4. 冲突 Claim 在 Ask 中被明确标注，不被静默混用。
5. `resolve_conflict` 能生成用户可理解的冲突解释和选择项。

### P4：Research 融入知识生命周期

目标：Research 事件不再是独立简报，而是外部变化对个人知识的更新机制。

验收任务：

1. Research event 生成 Artifact / Evidence / Candidate Claim。
2. Research event 能与已有 Claim 建立 supplement / supersede / conflict / irrelevant 关系。
3. 用户反馈影响后续 topic、source 和 event 排序。
4. Research 入库后生成 KnowledgeItem，而不是孤立摘要 note。
5. ResearchEventCard 能解释“为什么这对你重要”。
6. DigestClaim 的 support_level 映射到 Candidate Claim 的 Evidence 支撑状态，unsupported claim 不进入 active。

### P5：主动复习与知识缺口

目标：Review 和 Gap 基于 KnowledgeState，而不是只基于卡片到期时间。

验收任务：

1. Review 选择 active 且高价值的 Claim。
2. Conflicted / uncertain Claim 优先进入澄清任务。
3. 用户回答 gap 问题后能生成或更新 Claim。
4. Review 反馈更新用户记忆状态和 KnowledgeState 使用权重。
5. 主动提醒以轻量卡片进入工作台，而不是独立运营页。

### P6：图谱投影回归知识核心

目标：图谱服务 Claim / Evidence 的检索、解释和冲突发现，而不是成为另一个事实源。

验收任务：

1. Evidence / Claim 可投影为实体、关系和事实。
2. GraphProjection 记录投影来源、版本和质量信号。
3. 图谱检索结果必须回链到 Evidence 或 Claim。
4. 图谱抽取失败不影响 Artifact / Evidence / Claim 主链路。
5. 冲突发现可以使用图谱关系，但冲突状态必须写回 KnowledgeRelation / KnowledgeState。

## 质量指标

指标必须有可操作定义，不能只写概念名。尤其是 LLM 抽取不应要求字面完全复现，更合理的是语义一致性。

### Pipeline Health

| 指标 | 含义 |
| --- | --- |
| artifact_parse_success_rate | Artifact 成功解析并可用于 Evidence 生成的比例 |
| evidence_generation_success_rate | Artifact 成功生成 Evidence 的比例 |
| extraction_failure_rate | ExtractionRun 失败比例 |
| semantic_replay_consistency_rate | 重跑 ExtractionRun 后核心 Evidence / Claim 语义一致的比例 |
| graph_projection_backlink_rate | 图谱实体关系可回链 Evidence / Claim 的比例 |

### Knowledge Quality

| 指标 | 含义 |
| --- | --- |
| artifact_to_supported_candidate_claim_rate | Artifact 成功形成至少一个 supported CandidateClaim 的比例 |
| claim_evidence_coverage_rate | Claim 拥有可定位 Evidence 的比例 |
| unsupported_claim_block_rate | unsupported / contradicted claim 被阻止进入 active 的比例 |
| duplicate_claim_rate | 新 Claim 与已有 Claim 重复的比例 |
| conflict_detection_rate | 新 Claim 入库后发现冲突的比例 |
| claim_conflict_precision | 被标记为冲突的 Claim 中用户确认真实冲突的比例 |
| research_claim_impact_rate | Research event 对已有 Claim 产生补充/替代/冲突的比例 |
| research_unsupported_save_rate | unsupported Research claim 被误保存为 active 的比例 |

### User Trust

| 指标 | 含义 |
| --- | --- |
| cited_answer_rate | 回答带 citation 的比例 |
| unsupported_answer_rate | 证据不足但仍强答的比例 |
| citation_feedback_error_rate | 用户标记 citation 错误的比例 |
| correction_resolution_rate | 用户纠错后成功完成知识状态更新的比例 |
| decision_acceptance_rate | 用户接受 DecisionCard 建议的比例 |
| answer_regeneration_after_feedback_success_rate | 用户反馈后重新回答成功解决问题的比例 |
| solidify_fact_error_rate | 会话固化中误存助手推断或临时假设的比例 |
| review_claim_retention_rate | Review 后 Claim 被用户记住或修正的比例 |

这些指标比页面访问次数或后台任务数量更能反映 Agent 是否真正服务了知识业务。

## E2E Quality Eval 设计

目标架构必须从一开始绑定 e2e quality eval，否则 Artifact / Evidence / Claim / KnowledgeState 很容易停留在漂亮对象模型，无法证明真实业务路径变好。

当前工程已有 live e2e quality suite，覆盖 ask、research、artifact 和 Procedure 分支，并使用 goal kinds、procedure id、steps、matches、citations、evidence、verification score、grounding status、claim status、Research source/event/digest 等指标。新架构应保留这种端到端诊断思路，但把评测中心从“步骤是否跑通”升级为“知识生命周期是否正确推进”。

### Eval 分层

E2E eval 应分三层，不同层承担不同风险：

| 层级 | 目的 | 特点 |
| --- | --- | --- |
| Fixture / replay gate | 验证确定性算法和生命周期不变量 | 固定输入，baseline 应接近 1.0 |
| Live diagnostic gate | 验证真实 LLM、真实 web、真实 artifact 解析下的业务路径 | 允许漂移，用软阈值和 critical cases |
| Regression case gate | 复现线上/评测发现的问题 | 每个 bug 或业务缺口沉淀为 case |

不应把所有质量压力都放在 live e2e。URL canonicalization、Claim 去重、unsupported claim block、DecisionPolicy、KnowledgeState transition、GraphProjection backlink 等稳定行为应优先进入 fixture/replay gate。真实 LLM 和真实 web 的 live suite 负责发现环境漂移和端到端退化。

### 新的 E2E Run 观测字段

当前 `E2EQualityRun` 已有 `result_contracts`、`procedure_id`、steps、answer、matches、citations、evidence、verification、claim statuses、research sources/events/digest 等字段。目标架构应新增生命周期字段：

```text
artifact_count
parsed_document_count
evidence_count
evidence_block_count
evidence_span_count
evidence_ref_resolution_rate
evidence_coverage
missing_section_count
candidate_claim_count
grounded_claim_count
verified_claim_count
active_claim_count
rejected_claim_count
knowledge_item_count
knowledge_relation_count
knowledge_state_events
decision_count
decision_policy_kinds
graph_projection_count
graph_backlink_count
claim_review_state_count
partial_failure_count
regression_case_candidate_count
projection_job_failed_count
```

Ask 相关字段应区分：

```text
answer_claim_count
answer_claim_grounded_count
answer_claim_saved_count
```

这样可以验证“回答临时 claim 不默认入库”这一关键边界。

Research 相关字段应区分：

```text
research_artifact_count
research_candidate_claim_count
research_supported_claim_count
research_unsupported_claim_count
research_claim_relation_count
research_feedback_decision_count
```

这样可以验证 Research 不只是生成 digest，而是真的进入知识演进。

### Critical E2E Cases

最低应覆盖以下 critical cases。

#### E2E-LIFE-001：Artifact 到 Evidence

输入：用户上传或粘贴一段包含明确事实的资料。

期望：

- 生成 Artifact。
- 生成 ExtractionRun。
- 生成至少一个 Evidence。
- Evidence 可回链 Artifact。
- 不要求立即生成 active Claim。

失败信号：

- 只有 KnowledgeItem 文本，没有 Evidence。
- Evidence 没有 locator 或 artifact_id。

#### E2E-LIFE-001B：Partial Ingest Recovery

输入：一份可解析并能生成 Evidence，但 Claim 抽取模拟失败的资料。

期望：

- Artifact 仍然生成。
- Evidence 仍然生成并可引用。
- KnowledgeItem 进入 `claims_pending` 或 `partial_failed`。
- 后台 Claim 增强链路可重试。

失败信号：

- Claim 抽取失败导致 Artifact / Evidence 回滚。
- Ask 因 Claim 未完成而不能基于 Evidence 回答。

#### E2E-LIFE-002：Candidate Claim 不默认 Active

输入：一段包含多个主张、其中部分无证据或过度推断的资料。

期望：

- 生成 CandidateClaim。
- supported candidate 可进入 grounded / verified。
- unsupported / contradicted candidate 被 rejected 或保持 uncertain。
- active_claim_count 不包含 unsupported claim。

失败信号：

- 所有模型抽取句子都直接 active。
- assistant_inference 被当作 user_fact。

#### E2E-LIFE-003：Evidence-grounded Ask

输入：用户刚提交资料后立即提问。

期望：

- Answer 引用 Evidence。
- citation 可定位 Evidence。
- evidence_coverage 反映 complete / partial / sparse / none。
- partial coverage 时 missing_sections 可诊断。
- answer_claim 可用于校验。
- answer_claim_saved_count 为 0，除非用户明确保存结论。

失败信号：

- 为了回答强制等待长期 Claim 全量抽取。
- answer claim 自动进入长期知识。
- Evidence 覆盖不足时仍强答全局问题。

#### E2E-LIFE-004：No Evidence Conservative Answer

输入：用户问知识库和 artifact 中都没有证据的问题。

期望：

- 返回证据不足的保守回答。
- unsupported_answer_rate case 计为通过。
- 不生成 active Claim。

失败信号：

- 生成无证据确定答案。
- 把回答保存为 Claim。

#### E2E-LIFE-005：Solidify Conversation Claim

输入：一段会话中包含用户明确事实、助手推断和用户否定。

期望：

- 用户明确事实可成为 CandidateClaim。
- 助手推断不能 active。
- 被用户否定的旧事实不能 active。
- 高敏感或不确定 Claim 触发 DecisionPolicy。

失败信号：

- ThreadSummary 中 assistant_assumptions / unverified_claims 直接 active。

#### E2E-LIFE-006：Conflict Detection

输入：先保存 Claim A，再保存与其冲突的 Claim B。

期望：

- 生成 conflict KnowledgeRelation。
- 两个 Claim 的 KnowledgeState 标注冲突或需要确认。
- Ask 使用这些 Claim 时提示冲突，不给单一确定结论。

失败信号：

- 冲突 Claim 被静默混用。
- 系统只更新 KnowledgeItem 文本，不记录 relation。

#### E2E-LIFE-007：DecisionPolicy 防 HITL 过载

输入：一段资料产生低风险补充、unsupported candidate、以及高风险替代旧知识。

期望：

- 高风险替代触发 `must_confirm`。
- 低风险补充可 `auto_with_notice`。
- unsupported candidate 走 `silent_record`。

失败信号：

- 所有候选都弹确认。
- 高风险替代绕过确认。

#### E2E-LIFE-008：Research Claim Impact

输入：Research 发现一条与已有 Claim 相关的新事件。

期望：

- ResearchSource 形成 Artifact。
- DigestClaim 形成 CandidateClaim。
- supported claim 关联 Evidence。
- 与已有 Claim 建立 supplement / supersede / conflict / irrelevant 之一。
- unsupported claim 不 active。

失败信号：

- Research 只生成摘要 KnowledgeItem。
- Personal relevance 只输出自然语言，没有 KnowledgeRelation。

#### E2E-LIFE-009：Review Based On Claim State

输入：active、superseded、conflicted、uncertain 多类 Claim 混合存在。

期望：

- Review 选择 active 且高价值 Claim。
- conflicted / uncertain 进入澄清或冲突解决任务。
- superseded 不再进入普通复习。

失败信号：

- Review 仍只按 note/card 到期时间选择。

#### E2E-LIFE-010：GraphProjection Backlink

输入：一条可抽取实体关系的 Claim。

期望：

- 生成 GraphProjection。
- 图谱关系可回链 Evidence / Claim。
- 图谱抽取失败不影响 Artifact / Evidence / Claim 主链路。

失败信号：

- 图谱 fact 成为无来源事实。
- 图谱失败导致知识入库失败。

### Branch Scores

目标架构的 e2e report 应至少提供以下 branch score：

```text
lifecycle
ask_evidence
solidify_claim
research_impact
review_state
decision_policy
graph_projection
```

每个 branch 不只看 workflow 是否完成，还要看对应生命周期不变量是否成立。

### Baseline 与门禁

建议门禁策略：

- P0a/P0b/P0c/P0d/P0e 的 fixture/replay case 必须接近 1.0。
- Live diagnostic suite 使用整体软阈值、branch 阈值和少量 critical case 硬阈值。
- `unsupported claim enters active`、`assistant inference active`、`high risk decision bypassed`、`citation without evidence_ref`、`answer_claim auto persisted`、`claim extraction failure blocks artifact/evidence` 应作为 critical failure。
- 每次目标对象或 workflow 变更，必须同步更新 e2e case 和 scorer 字段。

### Eval 与设计同步规则

任何新增能力必须先回答：

```text
它影响哪些 Artifact / Evidence / Claim / KnowledgeState？
它需要新增哪些 E2EQualityRun 字段？
它是否需要 critical case？
它的失败是否会导致用户错误记忆、错误回答或高风险误执行？
```

如果一个设计无法被 e2e case 验证，它就不应进入主路径文档的 P0/P1。

### Scorer 模板

每个 critical case 都必须从自然语言期望落到可计算断言。推荐模板：

```text
case_id
branch
setup
input
expected_state_delta
hard_assertions
soft_assertions
diagnostic_fields
failure_category
```

当前 critical cases 已足够覆盖主路径，不应为了显得完整继续扩 case。下一步重点是把每个 case 都补齐 fixture、输入、状态 delta、hard assertion 和 failure category，并进入自动化 fixture/replay gate。

示例：`E2E-LIFE-003 Evidence-grounded Ask`

```text
hard_assertions:
  - citation_count > 0
  - every citation has evidence_span_id
  - every evidence_span_id resolves to evidence_block_id
  - every evidence_block resolves to artifact_id
  - answer_claim_saved_count == 0 unless user explicitly saves
  - active_claim_count_delta == 0

soft_assertions:
  - answer contains expected domain terms
  - verification_score >= threshold
  - grounding_status in supported / weak_evidence

diagnostic_fields:
  - selected_evidence_span_ids
  - answer_claim_statuses
  - generation_trace
  - verifier_trace

failure_category:
  - citation_without_evidence
  - unsupported_answer
  - accidental_claim_persistence
```

示例：`E2E-LIFE-005 Solidify Conversation Claim`

```text
hard_assertions:
  - assistant_inference_active_count == 0
  - denied_claim_active_count == 0
  - sensitive_claim_without_decision_count == 0
  - active_claims all have evidence or user_asserted source

soft_assertions:
  - candidate_claim_count >= expected_min
  - rejected_claim_count >= expected_min

diagnostic_fields:
  - claim_admission_decisions
  - decision_policy_kinds
  - thread_message_refs

failure_category:
  - assistant_inference_active
  - user_denial_ignored
  - sensitive_memory_without_confirmation
```

Scorer 不应只统计数量，还要验证 ID 可解析、状态转移合法、policy 决策存在、critical failure 不发生。

## 设计原则

1. **知识核心优先**：以 Artifact / Evidence / Claim / KnowledgeState 为中心，而不是 note/chunk 或功能 Tab。
2. **统一入口不是统一执行权**：用户入口统一，但 workflow、policy、HITL 和 evidence 仍控制副作用。
3. **Evidence 是回答边界**：没有 Evidence 或 Claim 支撑时，系统必须明确不确定。
4. **Claim 是长期记忆核心**：KnowledgeItem 是展示聚合，不是唯一事实源。
5. **抽取过程必须可追溯**：ExtractionRun 记录版本、输入、输出和质量信号，避免 Claim 变成不可解释的模型产物。
6. **纠错是一等能力**：错误反馈必须能回到 Evidence、Claim、KnowledgeState 和 eval。
7. **Research 必须个性化**：外部情报的价值在于影响用户已有 Claim 和判断。
8. **高风险动作不被简化**：删除、恢复、替代、冲突解决必须通过 DecisionCard 和 policy。
9. **图谱服务知识演进**：图谱优先用于关系解释、冲突发现、检索和演进，而不是第一屏装饰，也不是独立事实源。
10. **运维能力后置**：Audit、Replay、部署、指标看板支撑系统，但不主导用户主路径。
11. **先收敛约束再扩能力**：主架构稳定后，优先补 ClaimAdmissionPolicy、Evidence 粒度、状态转移和 scorer，而不是继续扩对象和 workflow。

## 结论

统一 Agent 工作台的终局不是统一 Capture / Ask / Research 页面，而是建立一个以 Artifact、Evidence、Claim、KnowledgeState 和 KnowledgeRelation 为核心的个人知识 Agent。

在这个目标架构下：

```text
Capture = 形成 Artifact / Evidence / 最小 KnowledgeItem；Claim 是可恢复增强链路
Ask = 受控复用 Evidence / Claim
Research = 外部变化挑战或补充已有 Claim
Review = 重新激活和校准 KnowledgeState
Delete = 更新状态并保留恢复链
Correction = 修改 Claim / Evidence / State
```

做到这一点，项目才会从“能力完整的知识 Agent 工程”变成“真正理解个人知识生命周期的 Agent 工作台”。
