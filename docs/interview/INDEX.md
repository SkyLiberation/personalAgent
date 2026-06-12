# 当前项目面试问答准备 · 索引

这份文档总结面试中可能围绕当前 personal agent 项目追问的问题和参考回答。回答口径重点不是背概念，而是讲清楚项目里的真实边界：哪些已经落地，哪些是设计方向，为什么这样拆层，以及当前风险在哪里。

项目最核心的一句话：

> 这个项目不是简单让 LLM 多调用几个工具，而是把 Agent 的记忆、行动和规划都放进可恢复、可校验、可审计、可评测的系统边界里：LangGraph checkpoint 管短期执行现场，Postgres note/chunk 管长期事实，MemoryEpisode 管情景记忆（过往任务的意图与结果）、MemoryItem 管反思 / 程序经验，独立 planner LLM 管查询理解、Unstructured 管文档结构化（LangExtract 作为休眠的可选抽取层保留），Graphiti 做语义索引，Evidence 管回答依据，WorkflowSpec/WorkflowRegistry 管固定流程拓扑，PolicyEngine 管策略决策，ToolGateway 管副作用，WorkflowSpecValidator/StepProjectionValidator 管 spec 与步骤投影安全，evals 模块验证检索、问答和规划策略是否真的有效。


本文档已按模块拆分。下面按顺序列出各模块及其覆盖的问题，点击模块标题进入对应文件。

## [它解决了什么问题](01-problem-and-positioning.md)

- 这个 Agent 面向什么场景？
- 用户为什么不用普通 ChatGPT，而要用这个 personal agent？
- 它具体解决了哪些用户痛点？
- 它和普通 RAG Bot 的区别是什么？
- 这是一个合格的 Agent 吗？

## [高频总览问题](02-overview.md)

- 这个 personal agent 的核心链路是什么？
- 你为什么采用多层 Agent 架构？
- LangChain 在这里承担什么价值？
- LangGraph 在这里承担什么价值？
- LangExtract 在这里承担什么价值？
- LangSmith 在这里承担什么价值？
- LangChain / LangGraph / LangExtract / LangSmith 各自的边界是什么？
- 为什么查询理解 / 抽取要独立配置模型？
- 这个项目最体现 Agent 工程能力的点是什么？
- evals 模块在这里承担什么价值？
- evals 和普通单元测试有什么区别？

## [记忆层](03-memory.md)

- 你怎么区分短期记忆和长期记忆？
- 为什么 checkpoint messages 不能直接当长期事实库？
- `knowledge_notes` 为什么要设计 parent/chunk 两层？
- Graphiti 是不是长期事实真源？
- EvidenceItem / ContextPack 解决了什么问题？
- 如果历史摘要和当前证据冲突，信哪个？
- `solidify_conversation` 如何避免把助手猜测写入长期知识？
- 如果同一主题有新旧冲突记忆，现在怎么处理？未来怎么设计？
- 情景记忆（MemoryEpisode）和长期 note 有什么区别？为什么不直接把对话结论 capture 成 note？
- 情景记忆什么时候被检索？怎么判断一个问题需要它？
- 情景记忆具体存在哪里？检索是怎么做的？
- 为什么情景记忆不用 LLM 生成摘要？
- 情景记忆只在 ask 分支用，如果 router 没路由到 ask 怎么办？

## [Prompt 工程](04-prompt-engineering.md)

- 项目里的 prompt 是怎么组织的？集中管理还是散落？
- PromptSpec 上的 version 和 output_contract 各解决什么问题？
- 结构化输出怎么约束？为什么不是所有 LLM 调用都用 json_schema？
- evidence 是怎么注入 prompt 的？怎么防止模型引用没给它的证据？
- prompt 里有哪些防幻觉 / 安全边界指令？
- 回答语言和口吻是怎么控制的？
- prompt 有没有版本管理和测试？

## [工具层](05-tools.md)

- 你的工具层和直接把函数暴露给 LLM 有什么区别？
- 为什么需要 ToolGateway？
- `risk_level`、`side_effects`、`permission_scope` 区别是什么？
- 为什么 `delete_note` 不能被 ReAct 自主调用？
- 那 ReAct 还有什么使用场景？
- ToolArtifact 为什么统一成 `ok / data / error / error_kind / evidence`？
- 工具结果为什么不直接写入用户 messages？
- 当前工具层最大不足是什么？

## [Workflow / 步骤投影层](06-workflow-step-projection.md)

- 当前 planning 是怎么落地的？
- WorkflowSpec / WorkflowRegistry 解决了什么？
- 步骤投影和普通 Todo list 的区别是什么？
- 哪些任务会进入 step projection？哪些不会？
- `delete_knowledge` 为什么是 `retrieve -> resolve -> delete_note -> compose`？
- 为什么 `delete_note.note_id` 不能由 planner 直接填？
- `resolve` 如何防止 LLM 编造 note id？
- `StepProjectionValidator` 具体防住了什么？
- `ExecutionStep` 和 `StepRunState` 区别是什么？
- ReAct 能不能替代 planning？

## [HITL 与删除恢复](07-hitl-and-delete-recovery.md)

- 删除 note 的完整确认流程是什么？
- 用户拒绝确认时会怎样？
- 为什么确认后还需要 `idempotency_key`？
- pending confirmation 是长期审批表吗？
- `replay_from_checkpoint` 在删除流程里解决什么问题？

## [测试与评测](08-testing-and-eval.md)

- 你会怎么测试 workflow projection 不会生成危险步骤？
- 怎么测试 `delete_note` 必须经过确认？
- 怎么评估长期记忆召回质量？
- 怎么评估 solidify 有没有写入错误事实？
- 单元测试和 Agent eval 的区别是什么？
- 线上 Agent 问题怎么复现？

## [工程取舍与不足](09-tradeoffs-and-gaps.md)

- 为什么没有一开始就做完整权限系统？
- 为什么 Graphiti 不直接替代 Postgres？
- 为什么没有所有任务都用 ReAct？
- 如果只能优化一周，你会优先做哪三件事？
- 当前项目最大的生产风险是什么？

## [深入追问（检索 / 编排 / 治理 / 可靠性）](10-deep-dive-retrieval-orchestration.md)

- evidence 的预算（char_budget 5000、max_items 12）怎么定？预算不够时会丢关键 chunk 吗？
- evidence 排序是启发式还是 LLM？打分维度有哪些？
- query_planner 拆出的子查询是并行还是串行检索？结果怎么合并？
- 几路检索分别能检索什么？怎么互补？默认实际启用哪几路？
- 这么多检索手段，不会有冗余和冲突问题吗？
- 要加一个新 intent（比如"更新知识"），改动面有多大？
- projection_policy 为什么只给 delete/solidify 开，ask 为什么不投影成 ExecutionStep？
- 真要做开放式 autonomous planner，怎么加 guardrail？和 StepProjectionValidator 什么关系？
- PolicyEngine 的规则是硬编码还是可配置？
- owner 校验依赖 user_id，不传 user_id 就跳过，这算不算越权口子？
- checkpoint resume 后，工具执行到一半（graph 删了 note 没删）怎么保证一致性？
- retry 只对 transient 错误重试，怎么判定 transient？判错会怎样？
- 幂等账本持久化后，checkpoint replay 和工具副作用怎么配合？

## [情景判断追问（冲突 / 边界 / 取舍）](11-scenario-judgment.md)

- 用户刚刚说“我生日是 1 月 1 日”，这算事实吗？
- 如果 graph search 找到了关系，但 note/chunk 已经被删了，怎么办？
- 如果 web search 和本地 memory 冲突，怎么处理？
- 如果工具返回 `ok=false` 但 content 看起来像成功，你信哪个？
- 如果用户说“不要确认，直接删”，系统应该听吗？
- 如果做成多用户 SaaS，第一步改哪里？

## [面试收尾口径](12-closing.md)

- （收尾口径，无分项问题）
