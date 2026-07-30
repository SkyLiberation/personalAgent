# 高频追问、取舍与改进方向

## 1. 这是 RAG 系统还是 Agent 系统

参考回答：

> RAG 是系统的一种读取能力，不是总架构。系统除了检索回答，还允许模型根据 Observation 动态选择 Tool、MCP 或子 Agent，并处理知识生命周期、受控副作用、恢复和投递。真正体现 Agent 的地方是模型驱动的多轮 Interaction loop；真正体现生产工程的地方是权限、Command、Receipt、Verifier 和 E2E 都不交给模型自述。

## 2. 什么任务用 Conversation、Workflow 和 Investigation Project

参考回答：

> 短动态请求进入 Conversation，例如根据 Observation 决定下一次查询或是否委托 specialist；流程和状态迁移可以提前枚举时进入领域 Workflow，例如删除确认、Subscription 入队和 Delivery exactly-once；只有路径动态，同时跨进程、用户轮次或审批边界维持 required result contract 时，才显式创建 Investigation Project。模型可以选择用户级 Workflow，但不能重排内部事务步骤；Conversation 也不会隐式升级成 Project。

## 3. Agent 如何选择 Tool

参考回答：

> Runtime 从真实 Tool registry 和 Agent profiles 构造 `EffectiveCapabilities`，包含名称、描述、schema、read-only 和 retry 属性。模型结合用户消息、已有 Observation 和预算返回 typed `ToolCallProposal`。Admission 只校验 Tool 是否存在、参数 schema、action 去重和预算，不用关键词改写 Tool，也不补业务 payload。

## 4. 为什么不用关键词 Intent Router

参考回答：

> “不要保存”和“保存”包含相同关键词，“解释删除机制”和“执行删除”也很相似。Intent 和业务 payload 属于开放世界语义，确定性字符串规则不能证明。系统让模型生成 typed Proposal，再让确定性 Policy 和 Domain 判断能否执行。

## 5. 为什么不让模型直接调用数据库

参考回答：

> 数据库是持久化 Adapter，不是业务能力。模型直接写数据库会绕过 scope、唯一写入口、状态机、幂等和审计。模型只能提出保存、删除或订阅 Proposal，Application Use Case 将合法 Proposal 转成 Command 或领域变更，再通过 Repository 持久化。

## 6. ToolGateway 比普通函数调用多了什么

参考回答：

> ToolGateway 是统一执行边界，负责 exposure、permission scope、risk、side effects、confirmation metadata、idempotency、timeout、retry、rate limit 和 audit。Tool 本身只实现能力，不自行决定授权，也不把自己的 success 当成用户目标完成。

## 7. Proposal、Command 和 Receipt 有什么区别

参考回答：

> Proposal 是模型建议做什么，没有权限语义；Command 是 Application 接受后形成的不可变执行请求，适用于审批、副作用和恢复边界；Receipt 是执行系统记录已经做了什么。三者不能用同一个 Model 混装，否则 replay 时可能把旧 Proposal 当新 Command，或者把模型自述当执行事实。

## 8. 为什么普通 Conversation 不再强制 Plan

参考回答：

> 旧 WorkingPlan 只进入 Prompt/Trace，没有生产调度消费者，却增加首次 action 和恢复的模型轮次。现在系统只持久化 messages、Observation、Feedback、usage 和 action order，重启后直接基于 committed facts 继续。真正驱动 ready set、coverage 和恢复的 Plan 只存在于显式 Investigation Project。

## 9. 进程崩溃后怎么避免重复 Tool

参考回答：

> Interaction journal 保存 committed action_id 和 execution order，恢复后 Admission 拒绝重复 action_id。受治理副作用还使用 immutable Command、canonical command digest 和 Receipt，replay 命中同一 digest 时返回已有 Receipt，不重新调用模型生成 Command，也不重复执行外部副作用。

## 10. Tool success 为什么不等于完成

参考回答：

> Tool success 只证明一次调用成功。例如 Web Search 返回结果，不代表用户问题已经被正确综合；子 Agent completed 也不代表父回答完成。系统把 Execution Fact、Semantic Verification 和 Domain Completion 分开，由不同 owner 判断。

## 11. Verifier 会不会推翻真实执行事实

参考回答：

> 不会。Verifier 只能判断答案或 Artifact 是否满足语义标准，不能把失败 Tool 说成成功，也不能改变 Command Receipt。反过来，Tool `ok=true` 也不能替代 Verifier 判断回答是否有证据支持。

## 12. 如何防止模型幻觉一个 Tool 或错误参数

参考回答：

> 模型只看到 EffectiveCapabilities；输出必须满足 `AgentTurnDecision` Pydantic schema。Admission 再检查 Tool registry 和参数 schema。不存在时返回 `capability_missing`，参数错误返回 `invalid_arguments`，并明确可修字段。Validator 不偷偷换 Tool 或补 payload。

## 13. MCP 与普通 Tool 有什么区别

参考回答：

> 对 Conversation 来说都通过 `InteractionToolPort`，差异被 Adapter 隔离。MCP Server 拥有远端 tool name/schema 和协议响应；Host 拥有本地映射、权限、风险、data egress、timeout 和 exposure。只有 discovery 和 mapping 都成立时才进入 registry。配置存在不代表可用。

## 14. A2A 与 Tool 有什么区别

参考回答：

> Tool 更适合边界明确、输入输出 schema 稳定的单次能力；Agent Delegation 适合需要自己的多轮推理、工具使用和 Artifact 产出的 bounded sub-goal。A2A 有独立 child lifecycle、poll/cancel/stream 和 Artifact index。子 Agent 不能宣布父请求完成。

## 15. 为什么 Graph/Vector Index 不是事实源

参考回答：

> 它们为检索优化，会重建、延迟或失败。事实源必须支持明确生命周期、事务和审计，所以 Artifact、Evidence、Claim 在 PostgreSQL Workspace Store 中；Graph 和 embedding 是可重建 projection。否则索引更新失败可能错误覆盖业务事实。

## 16. 如何防止 Ask 自动污染长期知识

参考回答：

> Ask 是 read-only Use Case，E2E 会比较前后 Claim 数。只有显式 solidify 才进入写入口，而且只保存 user-authored claim，assistant candidate 全部拒绝。这样模型推断不会在下一轮变成“系统已知事实”。

## 17. 为什么删除需要 Command，而读取不需要

参考回答：

> 读取低风险、可重试，不需要为形式统一持久化 Command。删除有长期副作用、需要确认、重启恢复、幂等 replay 和审计，所以必须形成 immutable Command，并用 digest 将 confirmation、execution 和 Receipt 绑定起来。

## 18. 当前是否使用 LangGraph 作为核心主链

参考回答：

> 不是。仓库仍有 LangGraph 和部分迁移/Procedure 代码，但当前普通 Conversation 主链由 `ConversationService` 的显式 Interaction loop 拥有，固定产品流程进入明确 Application Use Case，动态 durable 长任务进入显式 Investigation Project。Project 的 accepted Plan 和 journal 属于自身 aggregate，不代表 LangGraph 是三条主链的共同父框架。面试中不能再把旧 EntryGraph/GoalGraph 当成当前生产入口。

## 19. 为什么不使用一个通用 DurableTask 覆盖所有请求

参考回答：

> 直接回答没有必要伪造 Task、Command 和 CompletionReport；ResearchRun、DeleteCommand、Delivery 又有完全不同的状态和恢复语义。只有动态路径同时需要 durable completion obligation 时才创建 Investigation Project。当前按 owner 持久化 InteractionTrace、Knowledge facts、ResearchRun、Command/Receipt、Project journal 和 WorkerTask，避免一个 God Aggregate 混装所有生命周期。

## 20. Investigation Project 为什么不做成 Conversation 的隐藏模式

参考回答：

> Project 有独立 definition、accepted Plan、SubGoal、approval、budget、steering、cancel、verification 和 Completion Gate，也有异步 `202`、只读 GET 和 worker 恢复契约。如果把它藏进 Conversation，查询可能意外推进模型、短请求被迫承担 durable 状态、Conversation journal 也会成为第二个 Project owner。显式产品入口让用户知道自己创建了长任务，并让 worker、权限和发布证据都有稳定边界。

## 21. 如何控制成本和延迟

当前机制：

- 直接回答允许单轮结束；
- 固定 Workflow 不调用通用 Planner；
- Investigation Project 只用于动态且必须 durable 的任务；
- model/tool/agent/token budget；
- 安全只读 action 可以并发；
- SDK 隐式 retry 关闭，统一 retry owner；
- Provider wall-clock deadline；
- budget exhaustion fail closed。

当前不足：

- 普通 Conversation 没有跨实例一致的 distributed session store；
- 全部 public Tool schema 每轮进入 Context，Tool 增多后会影响延迟和选择准确率；
- 完整真实 Provider E2E 约 30 分钟，仍需更合理的快速门禁分层。

## 22. 这套框架的核心理念是什么，为什么不是照抄优秀 Agent

参考回答：

> 核心不是 object-root JSON 或某个 Agent SDK，而是“模型提议、系统裁决、执行产事实、证据关
> 目标”。模型 loop、Tool、MCP、A2A 和 subagent 都进入 typed Interaction，但模型输出只是
> Proposal；权限、预算和副作用不依赖 Prompt；Tool success、Agent completed、Verifier passed
> 和 Domain Completion 互不冒充。Conversation、领域 Workflow、Investigation Project 根据路径
> 动态性和 durable 边界分担复杂度，只有 Project Plan 有 ready set、coverage 和恢复等生产
> 消费者。这与现代 Harness 的 typed tool loop、guardrail 和 handoff 方向一致，但当前 object-root
> 是由本项目 terra Provider 失败证据选择的 wire format，不是从某个框架复制的顶层架构。

## 23. 当前最大的产品架构缺口

参考回答：

> 当前缺口已经不是“自然语言完全不能进入写操作”。B02 先证明整条 user message 固化会污染 Claim；E14 随后证明模型可逐字选择 user-authored knowledge span，Admission 机械校验来源，系统冻结 exact span，经确认、恢复、Workspace 唯一写入口保存精确结论，并反证“请求保存/先确认”控制语义没有进入 Claim。删除、订阅、“先核对冲突再保存”、assistant candidate、多实例并发和 commit/Receipt crash window 仍不能从 E14 外推。

## 24. 首条自然语言写操作怎样落地，下一步怎样扩展

目标链路：

```text
User message
  -> model chooses prepare_conversation_knowledge_save
  -> model copies exact user-authored knowledge span + source index
  -> deterministic admission validates exact source membership
  -> Conversation freezes immutable Command + one digest
  -> pending confirmation returned to Conversation
  -> user confirms
  -> WorkspaceService.solidify_conversation
  -> typed Receipt
```

已落地能力只接收逐字 `text_span` 与 source index；Admission 不理解或补写内容，只验证原文
归属，Command/digest 冻结 exact span。确认前零写入，确认后也不重新调用 Conversation 模型
生成 payload。删除和订阅是否需要类似粗粒度能力，必须由它们各自的 baseline
E2E 证明，不能为了“统一”预先注册。固定事务不变量仍由对应 Application Workflow 或 Use Case
控制。

## 25. Tool 很多时怎么扩展

当前做法把 public Tool definitions 全部注入模型。只有自然用户场景证明全量 schema 导致可重复
误选、延迟或 context budget failure 后，才准入两阶段发现：

```text
visible capability summary
  -> requirement retrieval
  -> 加载少量完整 schema
  -> 模型最终选择
```

检索只能缩小当前用户可见的候选集合，不能在可见性过滤前扫描所有 Tool，也不能替模型做语义最终选择。

## 26. 如果只能优化一周，优先做什么

参考回答：

1. 先修复当前已经实际失败的 package DAG gate，并清理会误导开发的旧主链文档；
2. 在 clean revision 重跑当前完整 catalog 和 release gate，建立可采信的发布证据；
3. 完成现有门禁后，再从正式入口执行“冲突核对后保存”或另一个明确用户目标的 baseline；只有
   产品行为失败时才扩展能力。

## 27. 如何评价当前设计是否合理

参考回答：

> 如果目标是安全、可维护并支持动态长任务的知识产品后端，当前三主链方向合理：短请求不承担
> 完整 Project 成本，固定事务不交给 Planner，只有动态且必须 durable 的长任务创建 Project。
> 判断依据不是类图：Conversation、固定产品 Workflow 和首条 governed save 有产品 E2E；
> Project 除 LT01-LT13 诊断证据外，IP01 已从 live HTTP/worker/model/Web Search 路径交付报告。
> E14 仍只证明 exact-span 保存，IP01 仍只证明一个 live 调查目标；当前 package DAG gate 失败且
> clean complete matrix 未建立，因此合理的框架方向不能被夸大成当前已经具备发布资格。

## 28. 一个失败案例怎么定位

以“GitHub 内容没有出现在最终回答”为例：

1. 看 InteractionTrace 中模型是否提出 GitHub ToolCall；
2. 没有提出：检查 EffectiveCapabilities、Tool description 和模型决策；
3. 被拒绝：检查 capability missing、schema、scope、budget Feedback；
4. 已执行失败：检查 ToolGateway audit、MCP discovery/mapping、timeout；
5. Observation 成功但答案错误：检查下一模型轮和 Verifier；
6. 用户结果正确但发布门禁失败：检查 archive revision、clean 状态和 checksum。

这种定位方式把语义决策、Admission、执行、验证和发布证据分开，不会把所有问题都归因于 Prompt。

## 29. 面试收尾口径

> 我在这个项目里最重视的不是堆 Agent 框架，而是建立清晰的权力链：模型负责开放语义 Proposal，
> Admission 和 Policy 负责准入，Gateway 产生执行事实，Verifier 与 Completion Gate 关闭用户
> 目标。短动态请求、固定事务和 durable 动态长任务分别进入 Conversation、领域 Workflow 和
> Investigation Project。E14 与 IP01 分别证明一个 governed save 和一个 live investigation
> 目标，历史 23/23、LT 诊断矩阵与这些定向 archive 都不能冒充当前 clean release evidence。
