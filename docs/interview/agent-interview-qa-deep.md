# 当前项目面试问答准备

这份文档总结面试中可能围绕当前 personal agent 项目追问的问题和参考回答。回答口径重点不是背概念，而是讲清楚项目里的真实边界：哪些已经落地，哪些是设计方向，为什么这样拆层，以及当前风险在哪里。

项目最核心的一句话：

> 这个项目不是简单让 LLM 多调用几个工具，而是把 Agent 的记忆、行动和规划都放进可恢复、可校验、可审计、可评测的系统边界里：LangGraph checkpoint 管短期执行现场，Postgres note/chunk 管长期事实，LangExtract 管文档预抽取和查询理解，Graphiti 做语义索引，Evidence 管回答依据，ToolGateway 管副作用，PlanValidator 管计划安全，evals 模块验证检索、问答和规划策略是否真的有效。

## 它解决了什么问题

### 1. 这个 Agent 面向什么场景？

这是一个面向个人知识管理的 Agent。它帮助用户把零散文本、网页、上传文件和对话结论沉淀为长期知识，并在后续提问时基于这些知识进行检索、推理和回答。

它不是只做一次性聊天，而是围绕“知识从哪里来、怎么存、怎么找、怎么引用、怎么安全删除”形成闭环。

### 2. 用户为什么不用普通 ChatGPT，而要用这个 personal agent？

普通 ChatGPT 更擅长一次性对话，但默认不会稳定维护用户自己的长期知识库，也不一定能把回答依据和本地知识来源清楚绑定。

这个 Agent 的价值在于：

- 用户可以显式 capture 文本、链接、文件和对话结论。
- 知识会进入长期 note/chunk 存储，而不是只留在聊天窗口里。
- 回答时会从长期记忆、图谱和工具结果中组织 evidence。
- 删除等高风险动作有目标解析、确认、幂等和审计边界。
- 同一 thread 的复杂任务可以通过 checkpoint 暂停和恢复。

所以它解决的是“个人知识如何长期沉淀并被可靠使用”的问题，而不只是“让模型回答一句话”。

### 3. 它具体解决了哪些用户痛点？

第一是知识沉淀问题。用户平时输入的文本、网页、文件和多轮对话结论很容易散落在不同聊天里，事后很难找回。这个项目通过 `capture_text / capture_url / capture_upload / solidify_conversation` 把这些内容写入长期知识库。

第二是知识检索和回答问题。用户后续提问时，Agent 不只依赖模型参数记忆，而是从 Postgres note/chunk、Graphiti 语义关系和工具结果中取 evidence，再组织回答，降低凭空回答的风险。

第三是长会话连续性问题。LangGraph checkpoint 保存当前 thread 的 `messages`、计划状态、工具归属、pending confirmation 和事件，使多轮任务、确认暂停和恢复执行有稳定现场。

第四是高风险操作安全问题。删除知识不是用户一句话就直接删，而是经过 planning、retrieve、resolve、HITL confirmation、idempotency key 和工具审计，降低误删和重复执行风险。

第五是 Agent 工程边界问题。项目把模型决策和系统执行拆开：模型可以理解意图、生成计划和草稿，但真正触碰长期存储、外部网络或删除动作前，必须经过 `PlanValidator`、`ToolGateway`、`ToolGovernance` 和 evidence 边界。

### 4. 它和普通 RAG Bot 的区别是什么？

普通 RAG Bot 通常重点是“上传文档后检索回答”。这个项目更像一个个人知识 Agent，除了 RAG 检索，还包含：

- 长期记忆写入：文本、链接、文件和对话固化都能进入知识库。
- 语义预抽取：LangExtract 会在 capture 中产出 section、topic、summary、`graph_worthy` 和 `source_span`，辅助 chunk 调和和图谱路由。
- 短期执行现场：checkpoint 保存多轮任务和暂停恢复状态。
- 图谱语义索引：Graphiti 提供实体、关系和 episode 检索，但不替代 Postgres 真源。
- 工具治理：工具调用有 schema、gateway、timeout、retry、rate limit、HITL、幂等和审计。
- Workflow / step planning：ask、capture、delete、solidify 本质上都是 workflow；其中删除和固化会额外投影成 `PlanStep`，用于步骤展示、HITL、checkpoint 和前端计划面板。
- 高风险恢复：删除知识支持确认、拒绝、resume 和依赖步骤跳过。
- 评测闭环：`evals/` 和 `docs/rag-eval-results.md` 用 Open RAGBench、MultiHopRAG、ask quality、plan/replan 等评测证明策略变化是否真的提升效果。

所以它不是单纯“检索文档回答”，而是围绕个人知识生命周期构建的 Agent。

### 5. 这是一个合格的 Agent 吗？

如果按“个人知识 Agent 原型 / 工程型 Agent”来看，它是合格的。因为它已经具备 Agent 的核心闭环：

- 能识别用户意图。
- 能调用工具完成真实动作。
- 能沉淀和检索长期知识。
- 能基于 evidence 回答。
- 能规划复杂流程。
- 能对高风险操作确认和恢复。
- 能把短期现场和长期事实分开。

但如果按完整生产级 SaaS Agent 来看，它还不能说完全成熟。当前仍需补齐真实权限后端、审计落库、持久化幂等账本、知识冲突治理、结构化 ThreadSummary 和专项 eval。

更稳的面试表述是：

> 它已经是一个具备核心闭环的个人知识 Agent：能采集、沉淀、检索、回答、固化和删除知识，并且对工具调用和高风险操作建立了工程边界。它目前更像一个生产化方向明确的 Agent 系统骨架，核心链路已经打通，但权限、审计落库、知识冲突治理和专项 eval 还需要继续补齐。

## 高频总览问题

### 1. 这个 personal agent 的核心链路是什么？

用户请求先进入 LangGraph entry，经过 router 判断 intent。普通问答、capture、direct answer、summarize 会走各自分支；需要明确步骤边界的高风险或复杂任务，例如 `delete_knowledge` 和 `solidify_conversation`，会进入 planning。

问答路径会从长期记忆、图谱或外部工具中检索证据，统一成 `EvidenceItem`，再由 `ContextPack` 做去重、排序和预算裁剪，最后进入 prompt。写入路径通过 capture 工具把内容沉淀到 Postgres `knowledge_notes`，并可同步 Graphiti。删除路径会先规划、解析目标、生成确认，再通过 HITL resume 真正执行。

### 2. 你为什么采用多层 Agent 架构？

README 里当前工程不是只拆成 memory、tools、planning，而是分成入口层、意图识别 / 路由层、规划层、运行时 / 编排层、工具层、记忆层、检索与推理层、执行与反馈层、观测与治理层；此外 `evals/` 作为评测模块，用来验证检索、问答和规划策略。

这样拆是因为一个 Agent 从用户请求到真实行动，中间不只是“模型回答”这一件事，而是包含入口适配、意图判断、上下文组织、计划生成、工具执行、状态恢复、证据检索、结果反馈和治理审计等多个职责。每一层都应该有清楚边界：

- 入口层统一 Web API、前端、CLI、飞书等来源。
- 路由层判断请求应该走 ask、capture、delete、solidify、direct answer 还是 summarize。
- 运行时 / 编排层用 LangGraph 管理 entry 总流程、checkpoint、interrupt/resume 和状态流转。
- Workflow / step planning 层处理固定 workflow 的步骤投影，例如删除和固化，把关键步骤变成可展示、可恢复、可确认的 `PlanStep`。
- 工具层把模型意图转换为受治理的系统动作。
- 记忆层区分短期执行现场和长期知识。
- 检索与推理层用 LangExtract 做 query understanding，再把图谱、本地知识和网络搜索组织成 evidence。
- 执行与反馈层通过 SSE、run snapshot、事件和前端确认面板暴露过程。
- 观测与治理层提供日志、鉴权、限流、用户隔离和测试基础。
- 评测模块用 Open RAGBench、MultiHopRAG 和项目自定义用例评估检索、问答、rerank、plan/replan 等策略。

所以 `memory / tools / planning` 是其中最关键的三条工程边界，但不是全部架构。它们分别解决“什么能作为知识”、“动作如何安全执行”、“复杂任务如何可恢复编排”。如果这些职责全部塞进一个 Agent loop，短期对话、长期事实、工具副作用、计划状态和审计反馈会混在一起，很容易出现历史回答被当事实、工具结果归属错误、删除动作绕过确认、checkpoint 恢复后状态不一致等问题。

### 3. LangGraph 在这里承担什么价值？

LangGraph 主要承担可恢复的状态机和 checkpoint 能力。项目把同一 `thread_id` 下的对话、计划步骤、工具归属、pending confirmation、执行事件都保存在 `AgentGraphState` 中，并通过 Postgres checkpoint 恢复。

它的价值不是“让 Agent 更智能”，而是让多轮任务、高风险确认、暂停恢复和步骤状态变成可控流程。尤其是删除知识时，系统可以在确认节点 `interrupt()`，用户确认后用同一 checkpoint resume，而不需要重新规划。

### 4. LangExtract 在这里承担什么价值？

LangExtract 是项目里的“轻量结构化理解层”，主要出现在两个位置。

第一个位置是 capture 流水线。原始文本先经过确定性 parent/chunk 草案，再由 LangExtract 产出 `SectionMap / SectionRecord`，包括 section、topic、summary、`contains_entities`、`graph_worthy`、reason 和 `source_span`。如果抽到多个语义 section，系统会用这些 section 调和机械 chunk；如果某个 chunk `graph_worthy=False`，它仍然进入本地长期记忆和检索，但会跳过 Graphiti 深抽取，从而降低图谱构建成本。

第二个位置是 ask 前的 query understanding。`query_planner.py` 优先复用 LangExtract 的 OpenAI-compatible 配置，用 `qwen3-coder-flash` 和 strict `json_schema` 生成 `QueryUnderstanding / RetrievalPlan`，做 query rewrite、子查询拆分、filters 抽取和检索源路由。这样复杂问题不会直接拿原始用户句子去搜，而是先变成结构化检索计划。

### 5. LangExtract 和 LangGraph、Graphiti 的区别是什么？

三者职责完全不同。

LangGraph 管编排和 checkpoint，解决“流程怎么走、怎么暂停恢复”。LangExtract 管结构化抽取和查询理解，解决“原始文本和用户问题如何变成稳定结构”。Graphiti 管图谱语义索引，解决“实体、关系和 episode 如何被检索”。

可以这样讲：

```text
LangExtract：把文本 / query 变结构
LangGraph：把任务流程变状态机
Graphiti：把知识关系变语义图谱
```

### 6. 为什么 LangExtract 要独立配置模型？

因为它需要稳定的结构化输出。项目默认用 `qwen3-coder-flash + DashScope OpenAI-compatible endpoint`，关键原因是它支持 OpenAI 风格的 `response_format=json_schema` strict 输出。

主对话模型、Graphiti 抽取模型和 LangExtract 模型解耦，可以让每条链路选最适合的模型：主对话关注回答质量，Graphiti 关注实体关系抽取，LangExtract 关注 schema 稳定性和低成本结构化理解。

如果 LangExtract 未配置或调用失败，ask query planner 会 fallback 到默认 plan 和启发式 filters；capture 侧根据 `fallback_on_error` 决定降级为机械 chunk，或抛出 `PreExtractError`。这个降级边界也很重要：LangExtract 增强结构，但不能让整个知识入库链路脆弱到一失败就不可用，除非配置明确要求失败即中止。

### 7. 这个项目最体现 Agent 工程能力的点是什么？

最值得讲的是“边界设计”：短期 checkpoint 和长期 note/chunk 分离，LangExtract 做结构化预抽取和查询理解，Graphiti 只做语义索引，回答前统一 evidence；工具不是裸函数，而是通过 ToolGateway 执行 timeout、retry、rate limit、HITL、幂等和审计；规划不是普通 Todo，而是通过 PlanValidator 校验后进入 checkpoint-safe 的步骤执行。

也就是说，项目的重点不是 prompt 写得多复杂，而是把 LLM 的不确定输出放进了系统级安全边界里。

### 8. evals 模块在这里承担什么价值？

`evals/` 是项目的评测闭环，作用是回答一个很关键的问题：这些检索、图谱、rerank、planning 改动到底有没有让 Agent 变好。

当前评测分几类：

- `evals/open_ragbench/`：基于 Open RAGBench 做单跳 RAG 检索评估，关注 MRR、Recall@k、NDCG@k。
- `evals/multihoprag/`：基于 MultiHopRAG 做多跳检索评估，关注跨文档 evidence set 是否被召回。
- `evals/test_ask_quality.py`：验证 Ask 质量和回答链路。
- `evals/test_retrieval_strategies.py`：对比本地、图谱、hybrid、rerank 等检索策略。
- `evals/test_plan_replan.py`：评估 plan / replan 行为是否符合预期。

配套的 [docs/rag-eval-results.md](rag-eval-results.md) 记录了关键结果，例如 Open RAGBench 上 optimized hybrid 的 MRR、Recall，MultiHopRAG 上 graphiti / structural / hybrid 的对照，以及 Microsoft GraphRAG CLI provider 的实验结论。

### 9. evals 和普通单元测试有什么区别？

单元测试主要证明代码边界是对的，例如 schema 校验、工具确认、PlanValidator 阻断危险计划、checkpoint 状态转移。它回答的是“代码有没有按预期运行”。

evals 证明策略效果，例如 query rewrite 有没有提升召回，Graphiti 是否改善多跳 top-k，LLM rerank 是否优于 heuristic，hybrid provider 是否比单一路径更稳。它回答的是“这个 Agent 是否真的更会找证据、更会回答、更会规划”。

所以 evals 是 Agent 工程里很重要的一层：没有评测，很多改动只是看起来更高级；有了 MRR、Recall、NDCG、按 question_type 的拆分和结果文件，才能判断策略是否值得保留。

## 记忆层

### 1. 你怎么区分短期记忆和长期记忆？

短期记忆是当前 thread 的执行现场，由 LangGraph checkpoint 承载，包括 `messages`、plan、react、tool tracking、events、pending confirmation 等。它用于理解当前任务、恢复执行、继续多轮对话。

长期记忆是用户明确 capture 或 solidify 后写入的正式知识，由 Postgres `knowledge_notes` 和 `review_cards` 承载。它才是可反复检索和引用的业务知识。

一句话：checkpoint 管现场，`knowledge_notes` 管事实。

### 2. 为什么 checkpoint messages 不能直接当长期事实库？

因为对话历史里混有用户事实、用户临时想法、助手推测、错误回答、废弃方案和未验证判断。如果直接把聊天记录当事实库，后续回答很容易把“助手曾经说过”误当成“真实事实”。

所以项目里同一 thread 的 `messages` 是短期真源，只用于理解上下文和恢复任务；长期事实必须经过 capture 或 solidify 后进入 `knowledge_notes`。

### 3. `knowledge_notes` 为什么要设计 parent/chunk 两层？

parent note 表达文档级或主题级知识，chunk note 保存片段证据、原文定位和 citation 单元。这样可以避免把长文直接塞进 prompt，也能在回答时从命中的 chunk 回溯到 parent note。

这种结构同时服务检索和引用：检索可以命中细粒度片段，用户可见引用又能回到清楚的来源。

### 4. Graphiti 是不是长期事实真源？

不是。Graphiti 在项目里是语义索引层，负责实体、关系、episode 和 fact 检索。长期事实真源仍然是 Postgres 的 note/chunk。

Graphiti 可以帮助找到语义关系，但回答需要引用原文或业务真源时，仍要回到 `knowledge_notes` 和 chunk 证据。这样做可以避免图谱抽取结果漂移后替代原始知识。

### 5. EvidenceItem / ContextPack 解决了什么问题？

它们把不同来源的上下文统一成回答前的证据出口。不同 evidence source 提供的价值不一样：

- `note`：提供长期知识的主题级信息，例如标题、摘要、用户保存的完整知识背景，适合回答“这个知识点整体是什么”。
- `chunk`：提供更细粒度的原文片段、`source_span` 和 citation anchor，适合支撑精确引用，避免只拿 parent summary 生成泛泛回答。
- `graph_fact`：提供 Graphiti 抽取出的实体、关系和事实边，适合发现跨文档关系、多跳线索、人物 / 组织 / 项目之间的连接。
- `web`：提供外部公开信息或时效性信息，适合本地知识不足、需要最新资料或用户明确要求联网时补充证据。虽然 `web_search` 在执行层是一个工具，但它产出的证据来源是公网网页，所以进入 evidence 层时标记为 `web`，而不是 `tool`。
- `tool`：这是 evidence schema 预留的工具结果来源类型，适合未来把内部 API 查询、计算工具输出、业务系统状态等“非网页、非本地笔记、非图谱事实”的工具结果纳入回答证据。当前生产 Ask 主链路主要使用 `note / chunk / graph_fact / web`；如果禁用 web search，通常不会再出现 `tool` evidence。

这些来源底层结构完全不同：Postgres note/chunk、Graphiti fact、web hit、tool artifact 都不是同一种对象。如果直接塞进 prompt，排序、去重、预算控制和引用都会很乱。

所以项目先把它们归一成 `EvidenceItem`，保留 `source_type / source_id / title / snippet / fact / score / metadata` 等通用字段，再由 `ContextPack` 做去重、排序和字符预算裁剪。只有 selected evidence 会进入 prompt，用户可见 citations 也从 selected evidence 派生，避免“模型看见的内容”和“用户看到的引用”不一致。

### 6. 如果历史摘要和当前证据冲突，信哪个？

信当前 evidence、工具结果或长期记忆检索。短期摘要只帮助理解对话线索，例如用户目标、已确认选择、待办状态，不能作为事实证据。

项目里明确把摘要风险列出来：摘要可能不稳定，也可能把助手推测压缩成确定表述。后续应该升级结构化 `ThreadSummary`，区分用户目标、已确认决策、助手假设和未验证声明。

### 7. `solidify_conversation` 如何避免把助手猜测写入长期知识？

当前做法是先通过 `compose` 从 checkpoint 对话中生成草稿，再通过 `capture_text` 写入长期知识。如果没有足够明确的知识正文，compose 会失败，不写入。

但这仍然是一个风险点。更成熟的方向是结合结构化 ThreadSummary，把用户明确事实、已确认决策、助手假设、未验证声明分开，对助手推测和未确认方案默认不写入，必要时向用户澄清。

### 8. 如果同一主题有新旧冲突记忆，现在怎么处理？未来怎么设计？

当前项目还没有完整的知识版本和冲突消解机制。`source_fingerprint` 可以帮助处理重复采集，但对同一主题的新旧事实、不同来源冲突、过期知识，还没有独立的 supersede、deprecated 或置信度机制。

未来应该引入版本链、来源可信度、时间新鲜度、冲突检测和回答时的冲突提示，避免旧知识被继续当成最新事实引用。

## 工具层

### 1. 你的工具层和直接把函数暴露给 LLM 有什么区别？

项目里的工具不是裸函数，而是受治理的系统能力。每个工具通过 LangChain `@tool` 生成 `BaseTool`，同时绑定显式 Pydantic args schema、`ToolGovernance`、统一 `ToolArtifact` 返回契约，并通过 `ToolGateway` 执行。

模型可以提出工具意图，但真正执行前会经过参数校验、风险判断、ReAct allowlist、确认机制、幂等、timeout、retry、rate limit 和审计。

### 2. 为什么需要 ToolGateway？

ToolGateway 是模型意图和真实系统副作用之间的执行边界。业务工具只负责业务动作，权限、确认、限流、超时、重试、幂等、审计这些系统能力集中在 Gateway。

比如 `delete_note` 不能因为模型生成了调用就直接删除。Gateway 会检查它是高风险工具、需要确认、确认执行时必须有 idempotency key，并记录结构化审计事件。

### 3. `risk_level`、`side_effects`、`permission_scope` 区别是什么？

`risk_level` 表示危险程度，例如 low、medium、high。`side_effects` 表示工具会造成什么类型的系统影响，例如本地读、外部网络、写长期记忆、删除长期记忆。`permission_scope` 表示执行这个动作需要什么权限域，例如 `memory:read`、`memory:write`、`memory:delete`。

三者一起描述工具治理：风险决定是否允许自主调用，副作用决定执行保护和审计重点，权限域为未来 policy engine 提供输入。

这里的 policy engine 属于观测与治理层的横切能力，但会被不同业务层消费。落到工具层，它会判断某次工具调用是否 allow / deny / require confirmation / require escalation；落到记忆层，它就是 [memory.md](topics/memory.md) 里提到的 `Memory Policy Engine`，负责长期知识的 capture、search、delete、graph sync 等访问策略。

当前项目已经有 `risk_level / side_effects / permission_scope` 这些治理元数据，以及 ToolGateway 的轻量运行时策略；但完整 policy engine 还没有落地。未来更合理的结构是：观测与治理层提供统一策略判断，`ToolGateway`、`MemoryFacade`、入口层和规划执行流程共同调用它。

### 4. 为什么 `delete_note` 不能被 ReAct 自主调用？

ReAct 是探索式循环，适合低风险只读工具，比如 graph search 或 web search。删除长期知识是高风险副作用，必须经过确定性计划、目标解析、用户确认和幂等保护。

如果允许 ReAct 自主删除，模型可能在没有充分确认目标的情况下执行不可逆动作，所以 Gateway 和 PlanValidator 都会阻止高风险或需确认工具进入 ReAct 自主路径。

### 5. 那 ReAct 还有什么使用场景？

有。当前项目不是不用 ReAct，而是把它限制在**单个计划步骤内部的低风险探索**。

典型场景是检索类步骤：planner 可以生成 `execution_mode="react"` 的 `retrieve` 步骤，让模型在有限轮次内根据观察结果决定是否继续调用 `graph_search` 或 `web_search`。比如删除知识前，系统需要先找候选笔记；这一步可以用 ReAct 探索图谱或网络线索，但最终删除目标仍必须经过 `resolve` 映射到真实 `note_id`，再进入 `delete_note` 的确认流程。

当前 ReAct 的边界是：

- 只在 planning 的单步内部使用，不替代整体计划执行器。
- 默认允许低风险只读工具，例如 `graph_search / web_search`。
- 受 `allowed_tools` 和 `max_iterations` 限制。
- 高风险、写入、删除、需要确认的工具不能进入 ReAct。
- 每轮 thought/action/observation 会进入事件流和 checkpoint 状态。

所以 ReAct 的价值是“受控探索”，不是“自主执行所有动作”。它适合证据不明确、需要迭代检索的场景；不适合删除、写入、外发这类副作用动作。

### 6. ToolArtifact 为什么统一成 `ok / data / error / evidence`？

统一 artifact 可以让编排层不理解每个工具的私有返回结构。成功、失败、证据和待确认状态都走同一种机器可读结构。

这对计划进度、错误恢复、HITL、审计和 evidence 组装都很重要。尤其是工具返回失败时，系统应该看 `ok=false` 和结构化 error，而不是猜 content 里的自然语言。

### 7. 工具结果为什么不直接写入用户 messages？

工具结果属于内部执行通道，不一定适合用户直接看，也不应该污染对话历史。项目用 `tool_messages` 保存内部工具交换，并通过 `ToolTrackingSubState` 记录 pending step id、tool call id、工具名、输入和 ReAct iteration。

这样 checkpoint 恢复后能做归属校验，避免把旧工具结果消费到新的步骤里。

### 8. 当前工具层最大不足是什么？

主要有三个：权限判断还没有真实 policy backend；审计事件还没有独立落库；幂等账本还是进程内实现。

这意味着当前已经有轻量 Tool Runtime 和治理契约，但还不能说完整生产级权限、审计和跨进程幂等都落地了。

## 规划层

### 1. 当前 plan 是真正的自主规划层吗？

严格说，不是。当前 `ask_branch / capture_branch / delete_knowledge / solidify_conversation` 本质上都是 workflow；其中 ask 和 capture 是直接 workflow 分支，delete 和 solidify 则被包装成 `PlanStep` 执行。

所以当前 plan 更像 **workflow 的步骤化 projection / execution adapter**，还不是成熟的通用自主 planner。它把固定或半固定 workflow 的关键节点表达成 `PlanStep / PlanStepState / plan.results / step events`，再接入 ToolGateway、LangGraph checkpoint、HITL 和前端计划面板。

这个判断很重要：如果面试官追问“这些步骤不都是固定的吗”，应该坦诚回答“是的，当前不是让 LLM 自由规划流程，而是用 intent 模板把固定 workflow 结构化”。这样比强行包装成通用 planner 更可信。

### 2. 如果重新设计规划层，你会怎么做？

我会把它重新设计成 **Workflow / Step Planning Layer**，而不是继续把固定流程叫通用 planner。

目标架构是：

```text
Router 识别 intent
  -> WorkflowRegistry 选择 WorkflowSpec
  -> WorkflowRunner 执行固定或半固定 workflow
  -> DecisionNode 只处理局部 LLM 决策
  -> StepProjection 暴露前端步骤、checkpoint 状态、HITL 和审计
```

几个关键变化：

- `ask / capture / direct_answer / summarize` 明确是普通 workflow，不需要 `PlanStep`。
- `delete_knowledge / solidify_conversation` 下沉成显式 workflow，保留 `PlanStep` 作为前端、checkpoint、HITL 和审计 projection。
- LLM 不再负责自由编排整个流程，只负责局部决策，例如 query understanding、删除候选选择、solidify 草稿、evidence rerank、低风险 ReAct 检索。
- `PlanValidator` 重新定位为 `WorkflowSpecValidator / StepProjectionValidator`，校验 workflow projection 和 intent 规则，不再被描述成通用 planner 的万能安全门。
- 真正 autonomous planner 只作为未来能力，用于无法映射到已有 workflow、需要多个低风险工具组合、且有 eval 和 guardrail 覆盖的开放式任务。

这样设计更符合当前项目实际，也更符合生产 Agent 的常见取舍：确定流程用 workflow，不确定局部用 LLM decision node，开放式 planner 只在确实需要时启用。

### 3. 规划层和普通 Todo list 的区别是什么？

普通 Todo list 只是自然语言步骤，本身不参与系统执行。项目里的规划层更准确地说是**步骤化编排层**：它不独占校验、恢复和审计能力，而是把这些能力接到同一个执行流程里。

具体来说：

- 规划层负责把复杂任务拆成结构化 `PlanStep`，表达步骤类型、依赖关系、工具意图、风险等级和失败策略。
- 执行期把 `PlanStep` 转成 `PlanStepState`，把每一步状态和结果放进 `AgentGraphState.plan`。
- 校验有两部分：计划结构、依赖图和 intent 规则由 `PlanValidator` 做；工具参数、风险治理和执行策略则依赖工具层的 args schema、`ToolGovernance` 和 `ToolGateway`。
- 可恢复能力来自 LangGraph checkpoint；规划层的作用是把 step status、`plan.results`、pending step 和依赖关系保存成 checkpoint-safe 状态，让恢复后知道从哪一步继续。
- 审计和事件也不是 planning 独有，工具调用审计来自工具层，运行事件来自 `AgentEvent`；规划层负责把 `plan_created / step_started / step_completed / step_failed` 等步骤事件串起来。

所以更准确的表述是：规划层不是单独实现所有安全能力，而是把 workflow 的关键步骤拆成可被工具层校验、可被 checkpoint 恢复、可被事件系统观察的步骤图。它的价值是“组织和约束执行顺序”，不是替代 ToolGateway、checkpoint 或审计系统。

### 4. 哪些任务会进入 planning？哪些不会？

当前真正进入 planning 的主要是 `delete_knowledge` 和 `solidify_conversation`。

普通 ask、capture、direct answer、summarize 不进入规划层，因为它们有直接 Graph 分支和 `execution_trace`，不需要额外步骤状态。这样可以避免所有请求都被过度规划。

需要注意的是，当前这里的 planning 不是完全开放式的自主规划，更像 **intent-specific workflow planner**。`delete_knowledge` 和 `solidify_conversation` 的主干确实是固定模板：

```text
delete_knowledge: retrieve -> resolve -> delete_note -> compose
solidify_conversation: compose -> capture_text
```

它们进入 planning 的原因不是“需要 LLM 自由编排步骤”，而是需要复用统一的 `PlanStep / PlanStepState / PlanValidator / plan.results / HITL / step events / checkpoint resume` 这一套执行壳。也就是说，当前 planning 的价值更偏“把固定 workflow 表达成可校验、可观察、可恢复的步骤图”，而不是让模型随意设计流程。

如果从工程简化角度看，完全可以把这两个流程做成显式 workflow：`DeleteKnowledgeWorkflow` 和 `SolidifyConversationWorkflow`。这样会更确定、更少 LLM 编排风险。当前保留 planning 入口的取舍是：一方面利用模板约束降低自由度，另一方面复用 `PlanStep` 作为 UI、checkpoint、HITL 和审计 projection，并保留未来扩展到更多复杂任务、失败重规划和前端计划面板的统一结构。

面试里可以坦诚讲：这不是“通用自主 planner 已经成熟”，而是“基于 intent 模板的结构化 workflow planning”。如果项目继续生产化，删除和固化这种固定流程可以进一步下沉成显式 workflow，planner 只负责选择 workflow、填充目标、解释步骤，或者生成低风险检索类子步骤。

### 5. `delete_knowledge` 为什么是 `retrieve -> resolve -> delete_note -> compose`？

删除的关键风险是目标不明确。`retrieve` 先找候选线索，比如 graph episode uuid；`resolve` 再把线索映射成本地真实 `note_id`；`delete_note` 首次调用只生成确认 payload，用户确认后才真正删除；`compose` 最后生成用户可见结果。

这个流程保证删除不是 planner 直接拍脑袋决定，而是先从真实知识库候选中解析目标，再通过 HITL 执行。

### 6. 为什么 `delete_note.note_id` 不能由 planner 直接填？

因为 planner 是 LLM 输出，可能编造 ID、误解用户指代或选错对象。`note_id` 必须来自运行时 `resolve` 步骤，从 graph episode 映射或本地 note 候选中选择。

后续 `delete_note.tool_input.note_id` 通过 `plan.results` 动态注入，避免把模型臆造参数直接传给高风险工具。

### 7. `resolve` 如何防止 LLM 编造 note id？

`resolve` 给 LLM 的输入只包含已有候选的 `note_id / title / summary`，要求它只能从候选 ID 中选择；不确定或多候选时返回 null。系统不接受 LLM 生成的新 ID。

如果图谱 episode 能映射回 note，就优先用真实映射；如果仍然没有明确候选，就失败并要求用户提供更具体描述。

### 8. `PlanValidator` 具体防住了什么？

它会检查步骤类型是否合法、依赖是否存在、依赖图是否有环、工具是否注册、工具参数是否满足 args schema、风险等级和失败策略是否合法、ReAct 是否越权调用高风险工具，以及 intent 特定规则是否满足。

比如 `delete_knowledge` 必须包含 `delete_note`，且 `delete_note` 必须依赖 `resolve`；`solidify_conversation` 的 `capture_text` 必须依赖 `compose`。校验不通过就不会执行危险工具。

### 9. `PlanStep` 和 `PlanStepState` 区别是什么？

`PlanStep` 是 planner 输出的计划意图，描述打算做什么。`PlanStepState` 是进入 LangGraph 后的执行状态，描述做到了哪里、是否失败、重试几次、结果是什么。

一个偏静态计划，一个偏 checkpoint 中的可恢复运行现场。

### 10. ReAct 能不能替代 planning？

不能。ReAct 是单步内部的探索策略，适合低风险只读检索。Planning 是跨步骤的编排和恢复机制，负责依赖、状态、HITL 和高风险流程。

项目刻意把 ReAct 限制为 planning 的局部能力，而不是让它替代计划执行器。

## HITL 与删除恢复

### 1. 删除 note 的完整确认流程是什么？

用户提出删除请求后，router 进入 `delete_knowledge` planning。计划执行 `retrieve` 找候选，`resolve` 确认真实 `note_id`，然后调用 `delete_note`。

第一次 `delete_note` 不删除数据，只返回 pending confirmation。Graph 把 payload 写入 `AgentGraphState.pending_confirmation` 并 `interrupt()`。用户确认后，Graph 用同一 `thread_id` resume，把 `confirmed=true` 和 `idempotency_key` 注入工具输入，再次调用 `delete_note` 才真正删除 note、chunk、review card 和可用的 graph episode 映射。

### 2. 用户拒绝确认时会怎样？

Graph 会把当前步骤标记为 skipped，递归跳过依赖它的后续步骤，清空 `pending_confirmation`，并返回取消说明。不会执行真实删除。

### 3. 为什么确认后还需要 `idempotency_key`？

因为确认请求可能重复提交，checkpoint resume 可能重放，网络或服务异常也可能导致重复执行风险。`idempotency_key` 用 thread/run/step 等信息标识同一次确认动作，Gateway 用它阻断重复副作用。

当前幂等账本是进程内实现，所以能覆盖单进程重复确认，但服务重启或横向扩容后还需要持久化幂等账本。

### 4. pending confirmation 是长期审批表吗？

不是。它属于当前 thread/run 的短期执行现场，保存在 LangGraph checkpoint 里。它的作用是暂停和恢复当前执行流程，不是长期业务审批系统。

如果未来做生产级审批，应有独立审批表、确认人、确认时间、权限和审计记录。

## 测试与评测

### 1. 你会怎么测试规划层不会生成危险计划？

可以做几类测试：校验没有 `resolve` 的删除计划必须失败；`delete_note` 不允许出现在 ReAct 步骤中；`delete_note` 必须声明 high risk 和 requires confirmation；`capture_text` 在 solidify 中必须依赖 compose；工具参数不满足 args schema 时不能执行。

这些是 unit / contract tests，目标是证明危险计划不能越过 `PlanValidator`。

### 2. 怎么测试 `delete_note` 必须经过确认？

构造删除请求，让第一次工具调用返回 pending confirmation，并断言长期存储没有被删除。然后模拟用户确认 resume，断言带 `confirmed=true` 和 idempotency key 后才删除目标 note、chunk、review card 和 graph mapping。

还要测用户拒绝、重复确认、缺失 idempotency key、目标不存在等边界。

### 3. 怎么评估长期记忆召回质量？

可以建立 memory eval：准备一批已 capture 的文档和问题，标注应该命中的 note/chunk，评估召回率、引用正确率、chunk 命中率、parent 回溯准确率、错误引用率。

还要加冲突和过期知识样例，测试系统是否能发现证据冲突，而不是引用旧知识。

### 4. 怎么评估 solidify 有没有写入错误事实？

设计长会话干扰样例：用户提出方案后否定、助手做出猜测但用户未确认、用户纠正前文、多个主题混杂。然后让用户要求固化，检查写入的 note 是否只包含用户明确要求固化的内容。

指标可以包括错误写入率、遗漏率、助手假设污染率、废弃方案污染率。

### 5. 单元测试和 Agent eval 的区别是什么？

单元测试验证确定性代码边界，例如 schema 校验、Gateway 策略、HITL 状态转移。Agent eval 验证模型参与后的整体行为，例如是否选对工具、是否解析对目标、是否把错误对话固化、是否在证据不足时澄清。

两者都需要：单元测试防回归，eval 发现模型和 prompt 层面的行为问题。

## 工程取舍与不足

### 1. 为什么没有一开始就做完整权限系统？

当前项目优先把 Agent 的主链路和关键工程边界跑通：入口统一、router 分流、LangGraph 编排、短期/长期记忆分离、ToolGateway、PlanValidator、HITL、evidence 出口和基础观测。完整权限系统需要用户、workspace、客户端来源、敏感级别、审计落库等配套。

所以现在 `permission_scope` 已经进入治理契约和审计事件，作为未来 policy engine 的输入，但不能说完整权限系统已落地。

### 2. 为什么 Graphiti 不直接替代 Postgres？

Graphiti 擅长语义关系和实体检索，但不适合作为业务事实真源。Postgres note/chunk 保存原文、摘要、source、chunk、review card、graph mapping 和可引用证据。

这样图谱抽取失败、关系不完整或 episode 残留时，系统仍然有可回溯的业务真源。

### 3. 为什么没有所有任务都用 ReAct？

ReAct 有探索能力，但也有不确定性和循环风险。普通任务有确定分支，高风险任务需要受控计划和 HITL，不适合让 ReAct 自主决定。

项目只把 ReAct 用在单步内部的低风险只读探索，并通过 allowlist、risk guard 和 max iterations 限制边界。

### 4. 如果只能优化一周，你会优先做哪三件事？

第一，为删除 `resolve` 增加候选确认 UI，降低误删风险。第二，把工具审计事件落到独立审计表，并关联 step id、tool call id 和 side effect。第三，建立 memory/planning eval 的最小集，覆盖删除目标解析、solidify 长会话干扰和 evidence 引用正确率。

这三件事直接提升生产安全性和可验证性。

### 5. 当前项目最大的生产风险是什么？

主要风险有：权限系统还没有后端化；审计未独立落库；幂等账本不是持久化；结构化 ThreadSummary 未落地，solidify 仍可能受长会话噪声影响；知识冲突和版本管理还不完善。

这些不是概念缺失，而是从原型走向生产时需要补齐的治理能力。

## 追问型问题

### 1. 用户刚刚说“我生日是 1 月 1 日”，这算事实吗？

在当前 thread 中，它可以作为用户刚刚声明的会话事实，用于理解当前对话。但如果要长期记住，应该通过 capture 或 solidify 写入 `knowledge_notes`。如果未来回答需要长期引用用户生日，应该从长期记忆或当前明确上下文取证，而不是从不受治理的历史摘要里直接认定。

### 2. 如果 graph search 找到了关系，但 note/chunk 已经被删了，怎么办？

这说明图谱和 Postgres 之间可能存在孤儿 episode 或 graph fact。回答时应该降低或屏蔽无法回溯到 note/chunk 的 graph fact，不能把它当强证据引用。后续需要图谱对账、孤儿检测和删除同步重试。

### 3. 如果 web search 和本地 memory 冲突，怎么处理？

先看问题类型。如果是用户自己的长期知识或项目内部知识，优先本地 memory 和当前工具结果。如果是外部世界的最新事实，应使用当前 web evidence，并提示与本地记忆存在差异。

关键是不要混在一起让模型自行猜，而是把证据来源、时间、可信度和冲突显式进入 evidence 排序或回答说明。

### 4. 如果工具返回 `ok=false` 但 content 看起来像成功，你信哪个？

信结构化 artifact。`ToolArtifact.ok / error / data` 是工具层契约，content 只是消息流中的观察文本。编排层和审计都应该以 artifact 为准。

### 5. 如果用户说“不要确认，直接删”，系统应该听吗？

不应该。高风险工具的确认要求来自工具治理契约和系统策略，不应该被用户一句话绕过。用户可以表达意图，但系统仍必须走 HITL、幂等和审计。

### 6. 如果做成多用户 SaaS，第一步改哪里？

第一步是接入真实 policy engine 和审计落库。`user_id/session_id` 隔离只是基础，多用户 SaaS 还需要 workspace/tenant 权限、工具级权限、来源权限、敏感数据策略、审计查询、删除恢复和幂等持久化。

## 面试收尾口径

可以用这段话收尾：

> 我这个项目真正想解决的不是“让 Agent 看起来什么都会”，而是让 Agent 在记忆、工具、workflow 编排和评测几个关键位置都有系统边界。短期现场用 checkpoint，长期事实用 note/chunk，语义关系用 Graphiti，回答依据统一成 evidence；工具调用必须经过 Gateway；删除和固化这类 workflow 会被投影成可展示、可恢复、可确认的步骤，并经过 PlanValidator、HITL 和 checkpoint。这样模型可以参与理解和决策，但不能绕过可恢复、可校验、可审计的工程边界。
