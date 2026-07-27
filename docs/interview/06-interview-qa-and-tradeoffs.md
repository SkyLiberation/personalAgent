# 高频追问、取舍与改进方向

## 1. 这是 RAG 系统还是 Agent 系统

参考回答：

> RAG 是系统的一种读取能力，不是总架构。系统除了检索回答，还允许模型根据 Observation 动态选择 Tool、MCP 或子 Agent，并处理知识生命周期、受控副作用、恢复和投递。真正体现 Agent 的地方是模型驱动的多轮 Interaction loop；真正体现生产工程的地方是权限、Command、Receipt、Verifier 和 E2E 都不交给模型自述。

## 2. 什么任务用 Agent，什么任务用 Workflow

参考回答：

> 当下一步取决于开放语义和未知环境结果时用 Agent，例如研究问题需要哪些查询、搜索后是否继续、是否委托 specialist。流程和状态迁移可以提前枚举时用 Workflow，例如删除确认、Subscription 入队、Delivery exactly-once。模型可以选择用户级 Workflow，但不能自由重排 Workflow 内部事务步骤。

## 3. Agent 如何选择 Tool

参考回答：

> Runtime 从真实 Tool registry 和 Agent profiles 构造 `EffectiveCapabilities`，包含名称、描述、schema、read-only 和 retry 属性。模型结合用户消息、已有 Observation、WorkingPlan 和预算返回 typed `ToolCallProposal`。Admission 只校验 Tool 是否存在、参数 schema、action 去重和预算，不用关键词改写 Tool，也不补业务 payload。

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

## 8. 为什么 WorkingPlan 不持久化为业务事实

参考回答：

> WorkingPlan 是模型对当前环境的临时判断，环境变化或恢复后可能失效。系统持久化 messages、Observation、Feedback、usage 和 action order；重启后让模型基于 committed facts 生成 `context_rebuild` 计划。这样恢复的是事实，不是旧推理。

## 9. 进程崩溃后怎么避免重复 Tool

参考回答：

> Interaction journal 保存 committed action_id 和 execution order，恢复后 Admission 拒绝重复 action_id。受治理副作用还使用 immutable Command、ExecutionCommandDigest 和 Receipt，replay 命中同一 digest 时返回已有 Receipt，不重新调用模型生成 Command，也不重复执行外部副作用。

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

> 不是。仓库仍有 LangGraph 和部分迁移/Procedure 代码，但当前普通 Conversation 主链由 `ConversationService` 的显式 Interaction loop 拥有，恢复边界是 `FileInteractionJournal`。固定产品流程进入明确 Application Use Case。面试中不能再把旧 EntryGraph/GoalGraph 当成当前生产入口。

## 19. 为什么不使用一个通用 DurableTask 覆盖所有请求

参考回答：

> 直接回答没有必要伪造 Task、Command 和 CompletionReport；ResearchRun、DeleteCommand、Delivery 又有完全不同的状态和恢复语义。当前按领域持久化 InteractionTrace、Knowledge facts、ResearchRun、Command/Event/Receipt 和 WorkerTask，避免一个 God Aggregate 混装所有生命周期。

## 20. 如何控制成本和延迟

当前机制：

- 直接回答允许单轮结束；
- 固定 Workflow 不调用通用 Planner；
- model/tool/agent/token budget；
- 安全只读 action 可以并发；
- SDK 隐式 retry 关闭，统一 retry owner；
- Provider wall-clock deadline；
- budget exhaustion fail closed。

当前不足：

- ContinueTurn 首次强制 WorkingPlan，单步 Tool 也可能产生额外 token；
- 全部 public Tool schema 每轮进入 Context，Tool 增多后会影响延迟和选择准确率；
- 完整真实 Provider E2E 约 30 分钟，仍需更合理的快速门禁分层。

## 21. 当前架构相比现代优秀 Agent Harness 的优点

1. 模型 loop、Tool、MCP、A2A、Observation 和 subagent 已形成统一 Interaction；
2. 权限、预算和副作用不依赖 Prompt；
3. typed Proposal 降低自由 JSON 解析风险；
4. WorkingPlan 与执行事实分离；
5. Command/Receipt 支持真实副作用恢复；
6. E2E 同时断言结果和反事实；
7. 删除旧通用 Task/GoalGraph 主链，减少双轨状态。

## 22. 当前最大的产品架构缺口

参考回答：

> 当前普通 Conversation 只加载 `public_agent` Tool。保存、删除、Subscription 变更等写操作属于 `scoped_agent` 或 `workflow_activity`，因此固定 Workflow 虽然可通过专用 API 执行，但还不能从自然语言对话统一进入。下一步应该增加基于身份和 Policy 的 scoped capability projection，以及对话内 Prepare Command、Pending Confirmation、Resume 和 Receipt Observation，而不是恢复关键词 Router。

## 23. 下一步怎样补自然语言写操作

目标链路：

```text
User message
  -> model chooses typed Application Capability Proposal
  -> CapabilityGateway checks identity/scope/policy
  -> prepare immutable Command
  -> pending confirmation returned to Conversation
  -> user confirms
  -> execute frozen Command
  -> Receipt Observation
  -> parent FinalMessage
```

只向模型暴露粗粒度能力，例如：

- `prepare_conversation_solidify`；
- `prepare_knowledge_delete`；
- `prepare_research_subscription`。

内部 Activity 继续由 Workflow 控制。

## 24. Tool 很多时怎么扩展

当前做法把 public Tool definitions 全部注入模型。规模扩大后应增加两阶段发现：

```text
visible capability summary
  -> requirement retrieval
  -> 加载少量完整 schema
  -> 模型最终选择
```

检索只能缩小当前用户可见的候选集合，不能在可见性过滤前扫描所有 Tool，也不能替模型做语义最终选择。

## 25. 如果只能优化一周，优先做什么

参考回答：

1. 打通一个端到端的 Conversation governed action，优先选择显式保存或删除：自然语言 Proposal、确认、执行、Receipt、恢复和反事实 E2E；
2. 将 EffectiveCapabilities 改为 identity/policy-aware，并只暴露粗粒度 Application Capability；
3. 在 clean revision 重跑完整矩阵，修复全仓历史 lint，建立可采信 release archive。

## 26. 如何评价当前设计是否合理

参考回答：

> 如果目标是安全、可维护的知识产品后端，当前“Agent loop + 领域 Workflow”方向合理，因为没有让模型控制权限和事务。如果目标是所有产品操作都能从统一聊天入口完成，目前还不完整。我的判断依据不是类图，而是 E2E 入口：Conversation 用例和产品 API 用例分别通过，但缺少自然语言到 governed write Workflow 的整链证明。

## 27. 一个失败案例怎么定位

以“GitHub 内容没有出现在最终回答”为例：

1. 看 InteractionTrace 中模型是否提出 GitHub ToolCall；
2. 没有提出：检查 EffectiveCapabilities、Tool description 和模型决策；
3. 被拒绝：检查 capability missing、schema、scope、budget Feedback；
4. 已执行失败：检查 ToolGateway audit、MCP discovery/mapping、timeout；
5. Observation 成功但答案错误：检查下一模型轮和 Verifier；
6. 用户结果正确但发布门禁失败：检查 archive revision、clean 状态和 checksum。

这种定位方式把语义决策、Admission、执行、验证和发布证据分开，不会把所有问题都归因于 Prompt。

## 28. 面试收尾口径

> 我在这个项目里最重视的不是堆 Agent 框架，而是给不确定的模型决策划清确定性边界：模型可以灵活理解目标、选择能力和根据 Observation 调整，但权限、状态机、幂等、副作用和完成证据必须由系统拥有。项目已经用 23 个正式入口 E2E 验证主要生产链，同时我也能明确说出当前自然语言写操作、分布式 Interaction 恢复和 clean release evidence 还没有闭合。
