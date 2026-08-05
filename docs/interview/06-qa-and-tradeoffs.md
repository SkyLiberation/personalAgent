# 高频追问速答与取舍

本文是**答话稿**，用于现场快速应答；同一问题的完整理念、代码位置和证据在
[能力轴](03-capability-axes.md)，证据编号口径在 [证据与发布](05-evidence-and-release.md)。
写法遵守 [面试文档规范](00-writing-spec.md)。为避免双轨事实，本文不重复展开实现细节，只给
可直接说出口的答案，必要时附一条「深挖去哪」。

## A. 定位类

### A1 这是 RAG 系统还是 Agent 系统

> RAG 是系统的一种读取能力，不是总架构。除检索回答外，模型还能根据 Observation 动态选择 Tool、
> MCP 或子 Agent，并处理知识生命周期、受控副作用、恢复和投递。真正体现 Agent 的是模型驱动的多轮
> Interaction loop；真正体现生产工程的是权限、Command、Receipt、Verifier 和 E2E 都不交给模型自述。

### A2 用户需要在 Conversation、Workflow 和 Project 之间做选择吗

> 不需要。普通用户只描述目标和业务约束。Conversation 的模型决定使用 request-local capability、
> 粗粒度领域 Use Case，还是在用户明确要求跨交互持续、进度查询、暂停/steering 时创建 Project。
> Workflow 只是具体领域 owner 的固定事务不变量，不是用户模式；Project 仍独立拥有 Plan 和状态。

深挖去哪：[01 第 3 节](01-project-story.md)。

### A3 当前是否用 LangGraph 作为核心主链

> 不是。仓库仍有 LangGraph 和部分迁移代码，但普通 Conversation 主链由 `ConversationService` 的显式
> Interaction loop 拥有，固定流程进 Application Use Case，动态 durable 长任务进 Investigation
> Project。Project 的 accepted Plan 属于自身 aggregate，不代表 LangGraph 是目标责任链的共同父框架。
> 旧 EntryGraph/GoalGraph 不是当前生产入口。

### A4 为什么不用一个通用 DurableTask 覆盖所有请求

> 直接回答没必要伪造 Task、Command 和 CompletionReport；ResearchRun、DeleteCommand、Delivery 又有
> 完全不同的状态和恢复语义。合并的代价是一个 God Aggregate 混装所有 lifecycle，收益只是「看起来
> 统一」。现在按 owner 分别持久化 InteractionTrace、Knowledge facts、ResearchRun、Command/Receipt、
> Project journal 和 WorkerTask。

深挖去哪：[能力轴 8](03-capability-axes.md)。

### A5 Conversation 能创建 Project，为什么不把 Project 状态也藏进去

> Conversation 只做一次受治理 handoff 并保存 ProjectReference。Project 的 definition、accepted Plan、
> SubGoal、approval、budget、steering、cancel、verification 和 Completion Gate 仍由 Project aggregate
> 独立拥有；查询继续走只读 Project API。这样既不要求用户先选模式，也避免 Conversation journal
> 成为第二个 Project owner。

## B. 决策与治理类

### B1 Agent 如何选择 Tool

> Runtime 从真实 registry 和 Agent profile 构造 `EffectiveCapabilities`（名称、描述、schema、
> read-only、retry 属性）。模型结合用户消息、已有 Observation 和预算返回 typed `ToolCallProposal`。
> Admission 只校验存在性、参数 schema、action 去重和预算，不用关键词改写 Tool，也不补业务 payload。

### B2 为什么不用关键词 Intent Router

> 「不要保存」和「保存」包含相同关键词，「解释删除机制」和「执行删除」也很相似。Intent 和业务
> payload 属于开放世界语义，确定性字符串规则不能证明。

### B3 如何防止模型幻觉一个 Tool 或错误参数

> 模型只看到 `EffectiveCapabilities`，输出必须满足 `AgentTurnDecision` schema。Admission 再查
> registry 和参数 schema：不存在返回 `capability_missing`，参数错误返回 `invalid_arguments`，并标明
> 可修字段。Validator 不偷偷换 Tool 或补 payload。

### B4 Admission 顺手补一个 `note_id` 有什么问题

> 那一刻语义 owner 从模型转移到 if/else。这个 if/else 不在 Prompt 里，Golden Set 覆盖不到，线上
> 出错无法归因。宁可返回 `invalid_arguments` 并标明 repairable field，让模型自己修。

### B5 为什么不让模型直接调用数据库

> 数据库是持久化 Adapter，不是业务能力。模型直连会绕过 scope、唯一写入口、状态机、幂等和审计。
> 模型只能提出 Proposal，Application Use Case 把合法 Proposal 转成 Command 或领域变更。

### B6 ToolGateway 比普通函数调用多了什么

> 它是唯一能同时回答这些问题的地方：这次调用被谁授权、是否可安全重试、幂等键是什么、是否需要
> 确认、外发了什么数据、审计在哪。散进各个 Tool 实现里就没有统一答案。

### B7 Proposal、Command、Receipt 有什么区别

> Proposal 是模型建议做什么，无权限语义；Command 是 Application 接受后的不可变执行请求；Receipt 是
> 执行系统记录已经做了什么。混装一个 Model 的后果是 replay 时可能把旧 Proposal 当新 Command，
> 或把模型自述当执行事实。

### B8 MCP 与普通 Tool 有什么区别

> 对 Conversation 都通过 `InteractionToolPort`，差异被 Adapter 隔离。MCP Server 拥有远端 name/schema
> 和协议响应；Host 拥有本地映射、权限、风险、data egress、timeout 和 exposure。只有 discovery 和
> mapping 都成立才进 registry。配置存在不代表可用。

### B9 A2A 与 Tool 有什么区别

> Tool 适合边界明确、schema 稳定的单次能力；Agent Delegation 适合需要自己的多轮推理、工具使用和
> Artifact 产出的 bounded sub-goal。A2A 有独立 child lifecycle、poll/cancel/stream 和 Artifact index。
> 子 Agent 不能宣布父请求完成。

深挖去哪：[能力轴 4 与 6](03-capability-axes.md)。

## C. 知识与验证类

### C1 为什么 Graph/Vector Index 不是事实源

> 它们为检索优化，会重建、延迟、失败。事实源必须支持明确生命周期、事务和审计，所以 Artifact、
> Evidence、Claim 在 PostgreSQL Workspace Store 里，Graph 和 embedding 是可重建 projection。否则一次
> 索引更新失败就可能覆盖业务事实，而没有地方可以查证原本是什么。

### C2 如何防止 Ask 自动污染长期知识

> Ask 是 read-only Use Case，E2E 直接比较前后 Claim 数。只有显式 solidify 进入写入口，且只保存
> user-authored claim，assistant candidate 全部拒绝。这样模型推断不会在下一轮变成「系统已知事实」。

### C3 为什么删除需要 Command，读取不需要

> 读取低风险、可安全重试，没有审批或恢复消费者。删除有长期副作用、需要确认、重启恢复、幂等
> replay 和审计——这五个消费者都真实存在，Command 才有意义。为形式统一给读操作造
> Command/Event/Receipt 只增加空转状态。

### C4 Tool success 为什么不等于完成

> Tool success 只证明一次调用成功。Web Search 返回结果不代表问题被正确综合，子 Agent completed 不
> 代表父回答完成。系统把 Execution Fact、Semantic Verification 和 Domain Completion 分开，由不同
> owner 判断。

### C5 Verifier 会不会推翻真实执行事实

> 不会，这是单向的。Verifier 只判断语义标准是否满足，改不了 Tool Receipt 和 Command 执行事实。
> 反过来 Tool `ok=true` 也不能替代 Verifier 判断回答是否有证据支持。

### C6 进程崩溃后怎么避免重复 Tool

> Interaction journal 保存 committed action_id 和 execution order，恢复后 Admission 拒绝重复
> action_id。受治理副作用还用 immutable Command、canonical digest 和 Receipt，replay 命中同一 digest
> 返回已有 Receipt，不重新调模型生成 Command。

深挖去哪：[能力轴 9 与 10](03-capability-axes.md)。

## D. 取舍与不足类

### D1 为什么普通 Conversation 不再强制 Plan

> 旧 `WorkingPlan` 只进 Prompt/Trace，没有生产调度消费者，却增加首次 action 和恢复的模型轮次。现在
> 只持久化 messages、Observation、Feedback、usage 和 action order，重启后基于 committed facts 继续。
> 真正驱动 ready set、coverage 和恢复的 Plan 只存在于显式 Investigation Project。

### D2 如何控制成本和延迟

已落地：直接回答允许单轮结束；固定 Workflow 不调用通用 Planner；Project 只用于动态且必须 durable
的任务；model/tool/agent/token budget；安全只读 action 并发；SDK 隐式 retry 关闭、统一 retry owner；
Provider wall-clock deadline；budget exhaustion fail closed。

当前不足（要一起说）：没有跨实例一致的 distributed session store；全部 public Tool schema 每轮进
Context，Tool 增多后影响延迟与选择准确率；完整真实 Provider E2E 约 30 分钟，缺快速门禁分层。

### D3 Tool 很多时怎么扩展

> 当前把 public Tool definitions 全部注入。只有自然用户场景证明全量 schema 导致可重复误选、延迟或
> context budget failure 后，才准入两阶段发现：visible capability summary -> requirement retrieval ->
> 加载少量完整 schema -> 模型最终选择。检索只能缩小当前用户可见的候选集合，不能在可见性过滤前扫描
> 所有 Tool，也不能替模型做最终语义选择。

### D4 这套框架的核心理念是什么，和优秀 Agent 是什么关系

> 核心不是 object-root JSON 或某个 SDK，而是「模型提议、系统裁决、执行产事实、证据关目标」。方向上
> 与现代 harness 的 typed tool loop、guardrail、handoff 一致；不同点都有具体原因：object-root 是本
> 项目 terra Provider 失败证据选择的 wire format，不是从框架复制的顶层架构；Ask 只读、no God Task、
> 删掉无消费者的 Plan 来自单用户、单进程、无 sandbox 这些真实约束。我不会因为某个框架有某个机制就
> 加它——加之前要有 baseline 证明当前路径确实失败。

### D5 当前最大的产品架构缺口

> 缺口已不是「自然语言完全不能进入写操作」。B02 先证明整条 user message 固化会污染 Claim；E14 随后
> 证明模型可逐字选择 user-authored span、Admission 机械校验来源、系统冻结 exact span、经确认后由
> Workspace 唯一写入口保存，并反证控制语义没进 Claim。但删除、订阅、「先核对冲突再保存」、
> assistant candidate、多实例并发和 commit/Receipt crash window 都不能从 E14 外推。

### D6 如果只能优化一周，优先做什么

1. ~~修 package DAG gate~~ 已于 2026-07-30 完成：原 `unknown_packages = context, skills,
   verification` 是已删除包的 `__pycache__` 残骸造成的假阳性，删残骸并让 `discover_packages()`
   要求目录内至少有一个 `.py`，gate 转 PASS；剩下的是清理会误导开发的旧主链文档；
2. 在 clean revision 重跑完整 catalog 和 release gate，建立可采信的发布证据（gate 绿后这条
   成了 A 级证据唯一的剩余障碍）；
3. 门禁绿了之后，再从正式入口做「冲突核对后保存」或另一个明确用户目标的 baseline；只有产品行为
   失败时才扩展能力。

顺序理由：第 2 步之前，任何新功能的「通过」都无法升级成 A 级证据，所以先修门禁的边际收益最高。

### D7 你怎么评价当前设计是否合理

> 目标是安全、可维护并支持动态长任务的知识产品后端，三主链方向合理：短请求不承担 Project 成本，
> 固定事务不交给 Planner，只有动态且必须 durable 的才创建 Project。判断依据不是类图——Conversation、
> 固定 Workflow 和首条 governed save 有产品 E2E，Project 除 LT 诊断外 IP01 已从 live 路径交付报告。
> 但 E14 只证明 exact-span 保存，IP01 只证明一个 live 目标，package DAG gate 失败且 clean complete
> matrix 未建立，所以合理的方向不能被夸大成当前已具备发布资格。

### D8 一个失败案例怎么定位

以「GitHub 内容没出现在最终回答」为例：

1. 模型是否提出 GitHub ToolCall？否 -> 查 `EffectiveCapabilities`、Tool description、模型决策；
2. 被 Admission 拒绝？-> 查 capability_missing / schema / scope / budget Feedback；
3. 执行失败？-> 查 ToolGateway audit、MCP discovery/mapping、timeout；
4. Observation 成功但答案错？-> 查下一模型轮与 Verifier；
5. 用户结果正确但门禁失败？-> 查 archive revision、clean 状态、checksum。

第 5 条刻意保留：用户结果正确和具备发布证据是两个独立问题，混在一起会导致「明明是对的为什么不让
发」这类误判。

## E. 收尾口径

> 我在这个项目里最重视的不是堆 Agent 框架，而是建立清晰的权力链：模型负责开放语义 Proposal，
> Admission 和 Policy 负责准入，Gateway 产生执行事实，Verifier 与 Completion Gate 关闭用户目标。
> 短动态请求、固定事务和 durable 动态长任务分别进入 Conversation、领域 Workflow 和 Investigation
> Project。E14 与 IP01 分别证明一个 governed save 和一个 live investigation 目标；历史 23/23、
> LT 诊断矩阵和这些定向 archive 都不能冒充当前 clean release evidence。
