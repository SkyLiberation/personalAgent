# 智能体运行外壳与关键能力

> **本篇集中介绍运行外壳拥有的六项关键能力：受治理的模型调用、按需工作清单、有界模型上下文、受治理执行、恢复与 Completion。** 每项都按“解决什么错误、如何工作、能力收益、证据、边界”完整展开；Memory 的跨时间分类由[智能体 Memory](04-memory-architecture.md)主讲，知识生命周期和后台调查由[领域设计](05-knowledge-and-domain-workflows.md)主讲，本篇不复制第二套解释。

## 1. 运行外壳把模型建议变成可靠的用户结果

**运行外壳是包围模型的工作闭环，不是新的业务层。** 模型负责理解用户目标和提出下一步；运行外壳准备本轮可见信息、约束模型权力、执行获准动作、提交 `Observation`，并在发送答案前组织 Verification 和 Completion 判断。

```text
用户目标
  -> 组装当前身份允许且本轮需要的信息与能力
  -> 模型提出回答、澄清、工作清单或动作 Proposal
  -> 确定性 Admission 检查结构、权限、风险、预算和当前事实
  -> 按事实归属执行获准动作
  -> 提交有界 Observation 并交回模型
  -> 模型依据新事实继续、等待用户或准备结束
  -> Verification 与 Completion 判断
  -> 用户可见结果
```

这条闭环阻止五类错误：模型 Proposal 直接获得权限、外部数据升级为控制指令、恢复时重复已提交动作、工具成功冒充目标完成、预算耗尽被包装成正常答案。

| 判断 | 责任主体 | 不能越过的边界 |
| --- | --- | --- |
| 用户想完成什么、下一步做什么 | 用户或模型 | 只能提出语义 Proposal，不能直接写事实 |
| 当前身份能否看见或调用 | 策略与具体业务 | 先检查权限范围，再暴露和执行 |
| 参数和状态迁移是否合法 | 确定性 Admission | 接受或拒绝，不能替模型补业务语义 |
| 动作是否真实发生 | 执行系统或外部权威 | 形成 Observation，不宣布用户目标完成 |
| 目标是否满足 | Verification | 不能推翻已经发生的副作用 |
| 用户要求是否全部交付 | Completion 门禁 | 不能把单个成功动作升级为完成 |

运行外壳不拥有个人知识、订阅、后台项目或业务完成标准。它统一的是 Proposal、Admission、Observation、再决策、Verification 和 Completion 的权力协议；长期事实继续由具体业务的唯一写入口负责。

### 1.1 模型调用必须服从结构、数据外发与失败契约

**模型不是一个可以随处调用的全局函数；每次调用都必须说明目的、可见上下文、结构化输出、预算和数据外发边界。** 如果这些信息只存在于提示词，服务提供方切换、空响应或结构变化就可能被误判为业务语义失败。

当前模型调用链先形成带用途和上下文引用的请求，再由确定性准入检查输出预算与敏感级别。外部服务提供方只负责生成候选结构；类型解析、有限技术重试、语义反馈和失败关闭分别由运行系统负责。只有网络、服务端错误、传输结构损坏或空结构化内容属于可重试的技术失败；一般结构不合法和语义不满足进入 `DecisionFeedback`、Verification 或明确限制，不能静默切换模型制造答案。

当前部署使用固定模型和服务提供方，不根据单次请求动态路由。历史 DeepSeek 同配置样本组中的 `PLAN-REPLAN-001` v51 达到 `15/15 delivered`；该结果只证明当时的模型、结构化输出方式和重试配置。当前 MiMo 配置已经通过后台生命周期选择的 20 样本正式 E2E，但后台最终报告仍未达到发布门槛，因此不能沿用 DeepSeek 归档声明 MiMo 具备相同的完整能力。模型调用的输入输出、令牌和延迟进入脱敏追踪记录，但完整性能画像仍受[证据与发布](06-evidence-and-release.md)说明的样本完整度限制。

### 1.2 切换服务提供方不是替换三个环境变量

**服务提供方会同时改变结构化传输、思考令牌、Proposal 语义、能力选择、重试次数和端到端延迟，因此会改变整个智能体闭环。** `base_url`、密钥和模型名称只解决连接问题；最小 JSON 冒烟成功，不能证明模型能够稳定承担语义路由、Plan、工具选择、Verification 和 Completion。

本工程在 MiMo 切换中依次遇到三个不同层次的失败：

| 配置 | 实际结果 | 暴露的边界 |
| --- | --- | --- |
| `json_object`，默认思考模式 | 最小 JSON 与 GPT Researcher A2A 冒烟成功；正式入口只完成 2 个项目创建，第 3 个请求超时 | HTTP 200 不代表存在可解析正文；800、1,600 和 3,000 令牌上限都可能被思考内容耗尽 |
| `json_object`，关闭思考模式 | `InteractionIntentProposal` 聚焦探针连续 `3/3` 通过；正式入口第 3 个请求返回 503 | 正文恢复后，模型连续生成只有 1 个步骤的 `WorkingPlan`，违反权威 Schema；关闭思考只修复传输，不修复类型约束 |
| 原生 `json_schema`，关闭思考模式，混合决策面 | `InteractionIntentProposal` 与大型 `AgentTurnDecision` 聚焦探针分别 `5/5` 类型合法；正式 20 样本全部返回 HTTP 200 | 类型合法没有带来正确语义：19 个请求停在 `plan_ready`，1 个返回 `limitation`，`project_selected=0/20`、`delivered=0/20` |
| 原生 `json_schema`，关闭思考模式，生命周期先行 | 正式入口达到 `20/20 background_started`，全部返回 ProjectReference | 模型先选择 Application 生命周期，再编译该分支的最小参数；没有工作清单、工具或子智能体进入同一决策面 |

第三组最容易误判。MiMo 已经证明支持原生 `json_schema` 的机械协议，但模型在混合决策面中把“离开当前请求后继续推进”系统性解释为等待用户审阅的前台工作清单。Admission 只能拒绝非法 Proposal 并返回 `DecisionFeedback`，不能替模型选择后台生命周期。如果确定性代码看到用户说“后台”就直接创建调查项目，它会接管开放语义路由，并让产品 E2E 失去证明模型能力的意义。

后续聚焦诊断把错误进一步定位到生命周期竞争，而不是“模型完全看不到工具”。完整生产投影包含 19 个工具和 1 个子智能体；四类请求的第一轮均同时提出 `gpt_researcher` 委托与前台工作清单，后台启动为 `0/4`。把已有后台说明移动到工作清单之前后，MiMo 会改选 `start_durable_investigation`，但仍附带工作清单；再明确要求互斥表达也没有移除清单。最后尝试由 Admission 保持模型已经提出的后台动作、只反馈移除协调清单，完整 Application 样本仍在 8 轮、59,874 tokens 后返回 `limitation`，并实际执行了一次对话内子智能体委托。四个候选都按预声明门槛撤回，生产路径没有保留服务提供方专用 Prompt、关键词路由或 Proposal 改写。

这个过程揭示了三个不同对象：对话内子智能体委托会阻塞当前请求并返回一个产物，`ConversationWorkingPlan` 只协调前台跨轮义务，后台调查项目才拥有请求返回后的独立生命周期。它们都能处理“复杂研究”，但时间边界和事实归属不同。当前实现没有继续加长能力描述，而是把现有交互意图派生破坏式替换为 `interaction_intent:v2`。模型先在 `conversation` 与 `durable_investigation` 之间作开放语义选择；只有选择后台生命周期后，第二次类型化调用才编译 `StartDurableInvestigationArguments`，Application 随后复用唯一 Project 写入口。确定性代码只验证来源片段、类型和当前是否已有 Project，不根据关键词选择生命周期。

这个分层不是多加一个 Router。交互阶段和验收标准原本就需要一次模型调用；`InteractionIntentProposal` 只把 Application 生命周期并入同一个事实 owner。普通对话继续进入 Agent loop，后台调查不再暴露 18 个普通工具、子智能体和 `ConversationWorkingPlan`。决策面缩小后，MiMo 的语义能力没有被伪造，运行系统只是避免让不同生命周期的资源互相竞争。

同一组自然输入的历史 DeepSeek 归档提供了诊断坐标，但不是严格的同代码版本 A/B：

| 指标 | DeepSeek 历史混合决策面 | MiMo 混合决策面 | MiMo 生命周期先行 |
| --- | ---: | ---: | ---: |
| 正确进入后台生命周期 | `20/20` | `0/20` | `20/20` |
| 最终交付 | `1/20` | `0/20` | 本组未观察最终报告 |
| 初始入口延迟 P50 / P95 | 3.57 秒 / 4.68 秒 | 76.67 秒 / 167.10 秒 | P95 36.91 秒 |
| 初始模型轮次 | 20 | 76 | 20 |
| 初始总令牌数 | 189,837 | 554,507 | 26,289 |
| 环境失败 / 重复 Proposal | 0 / 0 | 0 / 0 | 0 / 0 |

DeepSeek 组虽然稳定选择了后台生命周期，最终仍只有 `1/20 delivered`；失败继续发生在外部取证、综合和修复预算。MiMo 混合决策面则在业务能力入口之前失败。生命周期先行 target 关闭了 MiMo 的入口缺口，但没有观察后台最终报告。三组不是同代码版本下的严格模型 A/B，因此不能据此宣布 MiMo 优于 DeepSeek；它们证明的是服务提供方差异会改变智能体的失败阶段，而架构可以通过缩小当前决策面降低这种差异。

单变量消融提供了因果证据。同一正式输入仍派生 `execution_lifecycle=durable_investigation`；只移除 Application 的消费分支后，结果从 `background_started` 退化为 `plan_ready`，ProjectReference 消失，模型调用从 2 次增加到 5 次，令牌从 1,300 增加到 27,652。恢复消费点后重新通过。这个反事实说明收益来自生命周期分离，不来自模型波动、关键词路由或放宽 Schema。

当前 canonical `max_retries=2` 的 20 样本组出现一次可恢复的结构化解析失败，但最终请求失败为 0。零重试的独立 20 样本组同样全部通过。面试时应把两条结论分开：有限重试确实提高瞬时故障恢复能力；生命周期选择的正确性并不依赖重试制造成功。

更广的后台最终报告 baseline 又暴露了重复运行方差。同样四类输入各五次时，只有 `18/20` 创建 Project；两个失败样本的生命周期来源片段没有通过 grounding，分别返回 `limitation` 和 `plan_ready`。这不抹掉前两个 `20/20` target 与单变量消融，但说明当前 MiMo 路由尚不能写成稳定发布能力。面试时应说“机制在两个正式样本组通过，后续完整链路组复现 2 次入口失败”，不能只挑最好的一组。

进一步核验发现，两个失败样本并不是模型选择了 Conversation：模型实际提出 `durable_investigation`，只是引用的来源片段没有逐字命中最新用户消息。旧 Admission 随后直接把生命周期改成 Conversation，这等于运行系统在拒绝 Proposal 后替模型生成新的语义决定。当前本地候选改为一次 typed revision：只允许修订生命周期、来源片段和互斥交互阶段，首轮 requirements 保持冻结；第二次仍失败就 fail closed，不进入无限反馈循环。失败优先测试、`101` 个 Conversation 测试、`825` 个全工程测试和单变量 Conformance 消融均已通过。focused target 和后续正式 20 样本预算 cohort 都保持正常后台创建，但两组的 `revision_feedback_count` 都是 0；它们只能证明正常路径无回归，不能证明修订机制改善结果。面试中仍应称其为“边界修复候选”，不能把另一个 cohort 的 `20/20` 写成该机制已经稳定恢复重复运行。

候选后的一个真实 MiMo focused 样本以 1,263 tokens、37.19 秒正常创建 Project，普通 Tool/Agent 调用为 0；但该样本首轮 Proposal 已经通过 grounding，修订次数为 0。它只排除了候选破坏正常路径，不能用于声称修订机制改善了结果。这也是面试中值得说明的评测边界：target 通过不等于目标机制被消费，必须检查 trace 中消融变量是否真实出现。

同一正式组还暴露了 durable worker 的调度粒度问题。10 个队尾 Project 在观察窗口结束时仍停在 `planning/project_created`，9 个连首条 event 都没有；worker 和服务提供方都正常，只是单个 Project 以默认 `max_cycles=100` 连续占用 worker，而一次 MiMo 规划就需要 44 至 80 秒。当前实现让每个调查队列租约只推进一个 Project cycle，已提交事实后重新入队，使已有 FIFO 队列能够调度其他项目。真实 Postgres queue 的组合测试确认等待中的 Project B 会先于 Project A 的 continuation 获得下一个 lease。这个改动没有增加并发或第二套任务状态，失败优先测试、消融和包含生产改动的 `826` 个工程测试已经通过。

两项目真实 focused target 随后从正式 Conversation 入口创建两个 Project，再启动唯一 worker。前两个真实 MiMo 阶段为 `Plan A -> Plan B`，第三个阶段才是 Execution；两次入口均没有消费生命周期修订，两个 Project 都形成 accepted Plan，event sequence 为 10 和 8，观察错误为 0。该结果证明单-cycle 时间片确实改变了真实队列中的首次进展顺序，不只是单元测试中的参数值。

同一调度层后来暴露了另一种“看起来一直在工作”的假进展：真实 Project 等待第二次 GPT Researcher 结果时，300 秒内 `event_sequence` 增长到 1,945，却仍只有 1 个 Artifact、0 个 Outcome。原因是 `pending` 已经释放当前 worker cycle，但 continuation 的 `due_at` 仍是当前时间，单 worker 会立即重新 lease、再次预留并释放预算。当前设计复用既有 Postgres queue 的 `due_at`，把外部等待 continuation 延后 5 秒；失败测试和消费点消融证明旧链立即可 lease，候选到期前不可 lease且到期后 1 秒内恢复。两次真实 MiMo target 的事件数分别降为 75 和 82，后者比 baseline 下降 95.78%，自动记录 `wait_reschedule_passed=true`；worker、命令绑定、ExecutionRef 和 Artifact 保持正常，因此运行成本机制已闭环。但 target 仍为 0 Outcome，并观察到无关或格式异常来源，且没有单独计量真实 Provider ready 到 Project commit 的延迟。面试时应把它描述为 durable execution 的等待成本和调度正确性优化，不能说事件变少就代表 Agent 任务完成。

包含该时间片的当前组合版本又执行了 20 样本正式 target。结果为 `20/20 project_selected`、`20/20 event_sequence >= 1`、`0/20 delivered`，窗口结束时 15 个项目为 `active`、2 个为 `paused`、3 个仍为 `planning/project_created`；15 份 accepted Plan 只推进到 6 个 accepted execution Proposal，没有 ExecutionRef、ArtifactRef、SubGoalOutcome 或最终报告。它比 baseline 的 9 个零事件队尾更好，但没有达到预声明的 `project_created=0`，正式局部门槛失败，因此不执行产品消融。面试时只能说两项目首次进展顺序得到改善，不能宣称 20 项目公平性或最终交付已经闭环。

同一 v3 评测器还提供了更接近 A/B 的服务提供方对照。DeepSeek 归档与 MiMo 归档都为 `0/20 delivered`，所以两者都没有证明后台报告能力；DeepSeek 的入口均值约 4.1 秒、worker 日志尾部模型调用均值约 2.7 秒，MiMo 分别约 23.0 秒和 32.7 秒。DeepSeek 在窗口内形成 4 项服务提供方来源覆盖，MiMo 为 0。面试时应说“DeepSeek 在该任务族中吞吐更高，失败阶段更靠后”，不能说“DeepSeek 效果更好”，因为两组都没有达到用户结果，代码版本也并非完全相同。

工程随后以同一 MiMo、输入和评测器只把调查 worker 从 1 个槽位改成 4 个。候选把 accepted Plan 从 15 增至 18、accepted execution Proposal 从 6 增至 20，并形成 10 个 ExecutionRef、9 个 ArtifactRef、2 个 SubGoalOutcome 和 6 项服务提供方来源覆盖；最终仍为 `0/20 delivered`，另有 23 次 replan 和 4 个 `verification_repair` 暂停。并发候选因此全部撤回。这个失败很适合面试：并发能改善中间吞吐，但 Plan ID 合法性、Verification 收敛和 Completion 没有随之改善，不能用局部指标冒充智能体能力。

归档继续揭示了两种“结构化 JSON 合法、业务对象仍不合法”的 Provider 坑。第一，结构化输出边界允许 `completion_relevance=informational`，领域模型却只接受 `required|supporting`，合法 Provider 响应在 materialize 时被误报为 `provider_unavailable`；当前设计删除重复词表，让输出 Schema 直接引用 canonical `RequirementRelevance`。第二，JSON Schema 的 `uniqueItems` 只能判断整个对象是否重复，不能保证对象数组中的 `logical_subgoal_id` 或 `requirement_id` 唯一；三个真实样本在一次 replan 后仍因重复 logical ID 暂停。当前设计由一个纯函数拥有唯一性规则，结构化 parse 用它触发既有 schema repair，`PlanAdmission` 对绕过边界的 Proposal 继续返回 typed feedback。

两项机制分别完成失败优先测试、局部回归和独立消费点消融：相关性契约的相邻回归为 `63 passed`；身份唯一性为旧实现 `4 failed`、候选 `6 passed`、移除 parse 消费点后重新 `4 failed`，相邻回归 `69 passed`；组合后的全工程回归为 `841 passed`，Ruff、分层检查和 lock 检查通过。相关性机制后来在真实 MiMo Plan revision 2 中物化 3 条 canonical `supporting`，项目保持 `active/plan_accepted`；身份唯一性也在真实 MiMo replan 中两次触发 validator repair，最终三个 SubGoal ID 与七个 mapping ID 全部唯一，并继续产生 ExecutionRef 和 Artifact。两项确定性边界均已闭环，但都不能把 `0 Outcome` 写成调查报告已经交付。

这里还需要区分“多个 Plan 版本”和“多套 Plan 模型”。初始 Plan 定义完整待执行图，修订 Plan 只能修改未冻结部分并保护已有执行事实，因此两者必须保持不同写权限；普通修订与 verification repair 修订却没有不同的事实责任主体，repair 只比普通修订多一个“新工作修复哪个冻结 gap”的条件字段。当前实现已把后二者收敛为单一 `_PlanRevisionDraft`，由同一 validator、materialize 和 Admission 路径处理，动态 Schema 只按当前是否存在 gap 限制 repair 字段。干净快照 `f18b26d` 中，相邻调查回归为 `66 passed`，删除审计没有 legacy consumer；正式 Conversation 入口使用真实 MiMo 为 `1 passed in 36.34s`，仍返回唯一 Project 引用，归档 checksum 错误为 0。这只证明内部重构保持用户行为，不证明最终调查交付率提升。

更重要的架构教训是：Project 外层已经维护 Plan、子目标执行、Verification 和 repair，而 GPT Researcher 内部也自主执行规划、检索、迭代与综合。完整样本仍为 `0/20 delivered`，所以工程没有继续补下一个 Plan 字段，而是用一次有界诊断直接检验 GPT Researcher 能否独立承担研究闭环。

诊断只创建一个 `ChildAgentRunRecord`，没有外层 Plan 或 repair；当前 MiMo 与 GPT Researcher 仍在 240 秒后超时。服务提供方约到第 172 秒才因 agent-role JSON 形状错误回退默认角色，此后才开始检索；最终只有 `Cancellation requested.`，没有官方来源、usage 或报告。工程因此撤回单次研究委托架构，没有用更长超时、更多检索或重试制造通过。这个反例说明优秀 Agent 的拓扑只能提出候选，当前服务提供方能否履行该角色仍必须由本工程诊断证明。

进一步查清的坑是：主工程的 `json_schema` 根本没有进入这次 `agent-role` 调用。GPT Researcher `choose_agent()` 只调用自由文本生成，再依次尝试 `json.loads`、`json_repair` 和正则提取；其提示词的第一个 JSON 示例还缺少 `agent_role_prompt` 键后的结束引号。OpenAI Agents SDK 把 `output_type` 放在产生结果的智能体上，Google ADK 也由当前 `LlmAgent.output_schema` 拥有最终输出约束；两者都不依赖另一进程的全局输出传输方式隐式传递 Schema。生产消费者审计又发现动态 `server` 只用于日志，动态 `role` 只用于后续 Prompt，A2A 本身只暴露一个通用研究能力，因此工程没有增加第二套 Schema 适配，而是在 A2A 构造边界直接绑定确定性研究角色。相同任务从 240.14 秒超时变为 96.26 秒完成，`choose_agent=0`，约 3.2 秒开始检索，并形成 1 个 Artifact、1,711 字符报告及两个官方来源组。完整机制与迁移 grader 仍失败，usage 仍缺失，所以这证明的是二次路由应删除，不是 MiMo 或 GPT Researcher 已经稳定交付。

同一次诊断还暴露了运行事实错误：预算到期原本调用普通 `cancel()`，用户看到的终态是 `cancelled`。当前实现由 `AgentGateway.timeout()` 负责停止外部任务并提交 `timed_out`；用户取消继续由 `cancel()` 拥有。旧路径为 `2 failed`，实现相关断言为 `4 passed`、相邻回归为 `119 passed`、全工程回归为 `851 passed`。干净快照 `f18b26d` 上，Conversation 故障注入和 Gateway 契约为 `2 passed`；只恢复 Conversation 的旧消费点后，同一 Application 用例以 `cancelled != failed` 重新失败，还原后再次 `2 passed`。这证明 timeout 是独立执行事实，不是普通取消的别名；usage 仍不是 typed 事实，面试时应把“研究 Agent 不兼容”“父运行系统错误分类 timeout”和“计量缺失”分成三个责任主体，不能互相替代。

同一真实 Plan revision 2 还曾暴露 repair lineage 的另一半缺口：要求已经从失败的 `subgoal-1` 改映射到 `subgoal-1-repair`，下游综合却仍依赖旧 `subgoal-1`。工程做过一个自动依赖重绑定候选，局部断言与消融都成立；但没有因此宣称有效。A2A 兼容问题关闭后的正式重审真实消费了该候选：`subgoal-2` 升为版本 2 并依赖 `subgoal-1-repair`，两次委托均与 accepted SubGoal 完全绑定，形成 3 个 Artifact 和 4 个来源 URL。结果仍是 0 Outcome：Verifier 先拒绝 repair 报告，因为分析性综合不满足“官方原始内容摘要”，随后 planning token budget 用尽。候选因此连同专用测试和消融一起删除。面试时这个案例更有价值的结论是：类型、Admission 和局部消融只能证明机制正确工作；真实 target 若证明它不是最早阻塞点，就应撤回，而不是继续保留一个看起来合理的 Plan 分支。

随后两项目真实 MiMo focused target 以 2,924 tokens、P95 32.56 秒形成两份 accepted Plan，worker 未退出，归档 checksum 有效；两份 Plan 都没有 derived requirement，日志也没有唯一性或相关性 schema repair。因此这只是包含候选的正常路径回归，不是目标机制被消费的 target。面试时应主动说明这个差别：真实 Provider 运行通过仍可能只有 no-regression 价值，只有 trace 命中消融变量才有机制因果价值。

该完整 baseline 最终为 `0/20 delivered`、8 个暂停、10 个活动，只有 3 次真实 GPT Researcher 调用和 3 份 admitted evidence。由于 `max_search_results` 只在这 3 次调用中成为变量，预声明的 `max=5` target 要求至少新增 4 个全来源覆盖样本，当前责任主体并不匹配，所以工程在 baseline 后停止，没有用一次昂贵对照把 Planner、预算和生命周期失败误归因给检索参数。这类“知道何时不做优化”的证据，同样是智能体工程能力。

Provider 还会放大缺失的确定性不变量。本轮一个 MiMo Proposal 生成了极大的 `time_budget_seconds`；旧 Schema 只有大于零的约束，`ExecutionProposalAdmission` 因而接受它，并让同一 Proposal 产生 Agent ExecutionRef。即使外层 A2A timeout 最终限制真实网络等待，这个值也已经污染 canonical Proposal、digest 和审计事实。

当前候选没有新增硬编码 timeout。既有 `SubagentProfile.max_runtime_seconds` 继续拥有每个 Agent 的最大运行时间；Capability inventory 只读投影该值，动态输出 Schema 先限制模型可提范围，Admission 再拒绝绕过 Schema 构造的越界 Proposal，AgentGateway 最后拒绝绕过 Application 准入的越界 Grant。越界值不会被截断，因为截断会让用户授权、digest 与最终执行不再指向同一个 Command。相邻 focused target 为 `45 passed`；分别撤去 Admission 与 Gateway 消费点后，对应越界对象都会重新通过，恢复后测试再次通过。

真实 MiMo 正式 target 随后得到 `18/20 background_started`，未达到预声明的 `20/20`，所以整体结论仍是未闭环。已到达预算边界的 8 个 Agent Proposal 全部为 120 或 240 秒，4 个 ExecutionRef 全部绑定合规 Proposal，越界 Proposal、Command、未绑定 ExecutionRef、环境失败和 Provider failure 均为 0；但 2 个样本因生命周期来源片段未 grounding 而降为 Conversation，另有 10 个 Project 在观察窗口结束时仍处于 planning。面试时应把这组结果拆开说：模型负责提出预算，Profile 拥有资源上界，Schema 降低错误率，Admission 与 Gateway 在两个信任边界 fail closed；局部机制证据成立，不等于完整用户路径已通过。Provider 切换把边界漏洞暴露出来，而严格 E2E 又证明上游生命周期和后台推进仍是独立缺口。

后续归档审计发现，上一段的“越界为 0”只适用于运行时间。v1 评测器没有检查调查项目的 token/cost：同一正式组接受过 `120000` 和 `30000` tokens，而调查项目的外部委托上限为 `20000`；worker focused target 还接受了 `24000` tokens 与 `100000.0` cost，直到执行预留才以 `project cost budget exhausted` 暂停。这个错误说明，服务提供方返回类型合法值不等于授权合法，预算也不能只在真正执行时才检查。

当前候选让 `ProjectBudgetLedger` 从权威上限、已记账用量和活动 reservation 唯一派生剩余额度。动态 Schema 先缩小模型可提范围，`ExecutionProposalAdmission` 再拒绝绕过 Schema 的越界 Proposal，执行预留负责处理接受后发生的并发消耗。系统不会截断值或把 0 扩成 1，因为这会让 Proposal、digest、Command 与实际 `DelegationGrant` 不再表达同一授权。失败优先测试、Application 局部修订和两份消费点消融已经通过；全工程回归为 `832 passed`。真实 MiMo v2 target 随后达到 `20/20 background_started`，6 个 Agent Proposal 的运行时间、token 与 cost 越界均为 0；只撤去剩余额度 Context、动态 Schema 和 Admission 消费点的完整消融在 8 个 Proposal 中重新接受了 2 个 cost 越界值，分别为 500 和 50，而 Project 上限为 20。该结果把预算授权边界升级为 A2 机制证据；GPT Researcher A2A 仍未返回可核验的实际 token/cost Receipt，因此面试时不能说“外部账单已经被精确计量或限制”。

工程上的处理原则如下：

1. 服务提供方配置必须形成明确的能力配置档案，至少记录模型、结构化传输、思考模式、超时、重试和输出预算；
2. 先用真实类型化 Schema 做一致性测试，再从用户正式入口执行自然表达的 E2E；
3. `json_schema` 只保证机械形状，能力选择、Plan 修订和 Completion 仍需语义证据；
4. 服务提供方变化必须创建新的同配置样本组，禁止把历史结果拼成当前 target；
5. target 失败后恢复原配置，不放宽领域 Schema、不增加重试，也不静默切换服务提供方制造答案。

面试时可以这样概括：

> 我踩过的坑是把服务提供方切换理解成改密钥、地址和模型名。MiMo 的最小 JSON 和 A2A 冒烟都成功，但正式智能体先后暴露思考令牌吃光正文、`json_object` 无法稳定满足类型化 Schema，以及 `json_schema` 合法却在混合决策面选错业务生命周期三个问题。我们没有为 MiMo 写关键词路由，而是让模型先选择 Application 生命周期，再只物化该分支的最小契约。正式入口从 `0/20` 提升到 `20/20 background_started`，同输入消融又退回 `plan_ready`。最关键的认识是：结构化输出成功只证明协议兼容；智能体还必须评测语义选择，并通过 Context 与决策面设计让模型只解决当前阶段的问题。

当前结论和候选退出条件见[设计优化队列](../future/design-optimization-backlog.md) §3。当前实现坐标是 `StructuredConfig`、`OpenAIModelClient._chat_kwargs`、`derive_interaction_intent`、`ConversationService._start_durable_investigation` 与正式后台用例 `test_background_request_enters_the_project_lifecycle_before_resource_selection`。

## 2. 按需工作清单提升复杂任务的跨轮完成能力

### 2.1 它解决的不是“没有步骤”，而是跨边界后失去任务连续性

**工作清单解决的是复杂目标跨越预算、模型上下文、进程或用户调整边界后，智能体容易忘记未交付结果、看不到已取得事实、重复执行或过早结束的问题。** 一次模型调用能够完成的请求不需要它；单纯多调用几个工具也不是准入理由。

当前对话只保存一份可验收工作项清单。每项描述：

- 要向用户形成什么结果；
- 什么条件下可以接受为完成；
- 当前是待完成还是已完成。

“提取三份档案中的准确口令”是结果；“搜索资料”“调用工具”只是活动，不是合格工作项。清单不预先写死工具、顺序或模型的思考过程，下一步仍由新 `Observation` 决定。

### 2.2 真正产生能力收益的是完整闭环

**单独保存一个计划对象不会提升能力；有依据的计划、已绑定 `Observation` 和 Completion 门禁共同形成协调能力。**

| 组成 | 回答的问题 | 对智能体的实际影响 |
| --- | --- | --- |
| 规划安全探索与 `grounding` | 为什么这样计划、依据来自哪里 | 允许先读取文件、网页或记录，再把已观察约束和来源交给用户审阅；不把“以后再查”伪装成依据 |
| 可验收工作清单 | 还欠用户哪些结果 | 约束下一动作必须服务未完成结果 |
| 与工作项绑定的成功 `Observation` | 已经取得了什么 | 跨轮复用结果或本地副本，不从聊天文本猜测 |
| Completion 门禁 | 现在是否可以结束 | 仍有未完成结果时拒绝最终回答 |

```text
模型按需执行规划安全读取并取得 Observation
  -> 模型提出带 grounding 的工作清单
  -> 用户有明确验收条件时，Verifier 检查即将展示的同一份计划
  -> Admission 检查工作项可验收、已完成项不可被篡改
  -> 对话日志提交当前清单
  -> 动作绑定某个待完成工作项
  -> 执行系统提交成功或失败 Observation
  -> 下一轮恢复当前清单及其绑定的成功 Observation
  -> 模型继续处理未完成结果，或根据用户调整修订清单
  -> 所有当前有效结果满足后，才允许最终回答
```

日志只筛选同一对话、同一身份范围、同一清单且绑定当前工作项的成功 `Observation`；失败动作、未绑定事实和其他用户范围的内容不会恢复。日志不决定下一步，也不把工具成功自动解释成工作项完成。

### 2.3 什么时候创建，什么时候直接执行

| 场景 | 当前行为 | 原因 |
| --- | --- | --- |
| 用户明确要求先查证再看方案 | 只执行 `planning_safe` 读取，把已观察事实和来源写入 `grounding`，再展示清单 | 无依据的方案不满足用户目标，读取又不应越过写入/后台执行边界 |
| 用户明确要求先看方案或调整工作项 | 创建清单并停在审阅边界；不能用 `FinalMessage` 中的散文计划替代 | 用户控制本身就是产品契约 |
| 任务会跨真实预算、模型上下文、进程或用户轮次，且存在明显漏项、重复或调整风险 | 智能体可以主动创建 | 清单会在边界后继续约束决策和 Completion |
| 简单问答、一次调用可完成的请求 | 直接回答 | 保存清单没有协调收益 |
| 只是工具多、步骤多或流程固定 | 继续普通执行循环或进入具体业务流程 | 数量不等于动态协调需求 |
| 需要离开当前请求后持续运行、查询、暂停或调整 | 创建后台调查项目，而不是扩大前台清单 | 这是独立长期生命周期 |

默认交互中新清单必须在任何非规划安全执行前展示。为了形成有依据的计划，模型可以先调用投影为 `planning_safe=true` 的低风险读取能力；写长期状态、准备副作用、创建后台项目、委托子智能体及其他能力仍不得夹带。只有调用方明确选择自动执行模式，清单才可以与已授权执行动作同轮提交。模型不能根据用户措辞自行切换交互模式。

### 2.4 用户调整与版本的责任边界

**用户调整改变当前有效目标，版本号只帮助运行系统恢复排序。** 模型提出目标、工作项和语义完成状态；确定性代码保护已经完成的工作项，并在接受更新后生成单调恢复序号。模型看不到也不回传版本号，它不是授权凭证、Completion 证据或并发控制令牌。

用户改变尚未完成的要求时，后续动作只服务新要求；已经发生的 `Observation` 不会被改写。若旧清单全部完成后出现新的用户目标，系统创建新的清单身份，而不是把两个目标混成同一次修订。

### 2.5 从通用计划逻辑到当前工程的能力映射

**通用计划逻辑是比较坐标，不是必须实现的功能清单。** 当前工程只有在本地用户错误、生命周期和生产消费者都成立时才映射对应机制；“充分”只表示满足当前已证明需求，不表示已经证明对所有任务、模型、成本和延迟都最优。

| 通用设计逻辑 | 当前工程映射与生产消费者 | 证据充分性 | 当前判断 |
| --- | --- | --- | --- |
| 修改前允许读取、搜索、形成方案并由用户审阅；Claude Code `permission-modes` 与 Gemini CLI `plan-mode.md` 提供 A 级机制坐标 | 对话运行系统投影 `planning_safe` 读取，模型把已观察约束写入 `grounding`；默认交互在其他执行前返回同一份可审阅清单 | `CONV-004` 有正式入口、真实搜索和干净单变量消融；只覆盖一个目标和一类外部读取 | **已满足**：有来源的执行前规划与审阅边界已经形成最小闭环 |
| 用户能查看并修改尚未执行的方案，而不是只能接受一段散文建议 | 对话日志拥有唯一当前清单；用户调整产生新版本，后续动作只服务新要求 | `CONV-001` 的计划物化单行消融直接证明可见与可修订控制面；未证明答案正确率收益 | **已满足**：显式审阅与修订成立，结论限定为控制能力 |
| 计划项表达待交付结果和停止条件，而不是活动列表；Completion 不能由工具成功冒充 | 工作项保存结果与完成条件；动作绑定待完成项；最新 Goal、验收条件与最终回答在 Completion 前完成单一所有权移交 | `PLAN-REPLAN-001` v4 从正式入口复现三类陈旧义务；当前 v51 目标组为 `15/15 delivered`、最终待完成项为 0、服务提供方失败为 0 | **已满足**：当前配置样本组达到预声明门槛；不能外推所有模型、任务和服务提供方 |
| 上下文压缩、换轮次或重启后重新注入活跃项和已取得事实；Hermes `todo_tool.py` 提供 A 级机制坐标 | 对话日志恢复同一身份、对话和清单下绑定当前工作项的成功 `Observation`，并重新交给模型消费 | `HARNESS-003` v3 有干净单变量消融，重复原始读取从 `2` 降为 `0`；当前完整 Plan 目标组另行证明最终交付 | **机制因果成立**：只证明冻结服务提供方场景中的重复读取变化，不把它扩张为整体完成率或成本收益 |
| 长任务根据依赖和新事实调整可执行集合；Gemini CLI `tools.md` 提供任务状态与依赖坐标 | 依赖、可执行集合、重新规划和要求覆盖只由后台调查项目拥有；前台清单不复制依赖图 | 后台组 baseline 为 `0/20 delivered`、`20/20` 选择调查项目；失败来自整批预算准入和产物内容身份，不是前台清单缺少依赖图 | **边界已确认，交付未闭环**：保留 Project 事实，不扩张通用计划层 |
| 持久目标、进度和可验证停止条件支持跨轮继续；OpenAI `Follow a goal` 提供 A 级产品坐标 | 当前对话拥有短期工作项；离开当前请求后持续运行的目标由后台调查项目拥有 | 当前交互组为 `17/20 delivered` 且 0 次选择 Project；跨轮修订组为 `12/20 delivered` 且 0 次选择 Project；无新请求后台组为 `0/20 delivered` 且 `20/20` 选择 Project | **生命周期因果成立，能力仍未交付**：按生命周期拆分；真实 target 尚未形成合格归档 |
| 独立计划文件、通用任务跟踪器或离线共享产物提供额外协作界面 | 当前响应和日志已经提供唯一清单投影，没有第二个写入口或独立产物消费者 | 当前没有用户需求来源、同输入失败或第二消费者 | **候选未准入**：不是当前缺陷，不引入第二套计划或待办事实 |
| 规划阶段与执行阶段使用不同模型，以质量和成本分工；Gemini 计划模式（Plan Mode）提供机制候选 | 当前生产仍使用同一结构化模型和统一预算策略；第二模型只作为隔离端到端测试配置，不是生产阶段路由 | 没有同输入质量失败、多样本成本收益或延迟门槛 | **候选未准入**：不因跨模型评测引入生产模型路由 |

这份映射仍不支持继续增加计划对象。当前生产链已经完成工作清单审阅、事实绑定、陈旧义务失效、逐项验证和最终 Completion；v51 证明同一当前配置样本组达到既定结果门槛。早期 Mimo、SerpAPI 和不同结构化输出方式的样本属于历史诊断，不能继续承担当前能力结论。前台依赖图、计划文件、通用任务跟踪器和专用模型路由仍没有本地失败基线，因此不进入实现。

上述外部坐标为：Claude Code [`permission-modes`](https://code.claude.com/docs/en/permission-modes)（访问日期 2026-08-17）；Gemini CLI 提交 `c0d192452b4e2df7efb6d62a60385f475bfd6779` 的 [`plan-mode.md`](https://github.com/google-gemini/gemini-cli/blob/c0d192452b4e2df7efb6d62a60385f475bfd6779/docs/cli/plan-mode.md) 与 [`tools.md`](https://github.com/google-gemini/gemini-cli/blob/c0d192452b4e2df7efb6d62a60385f475bfd6779/docs/reference/tools.md)；Hermes Agent 提交 `3c5fd918e3e2537cd74f4f88c990c5de5cbd9f63` 的 [`todo_tool.py`](https://github.com/NousResearch/hermes-agent/blob/3c5fd918e3e2537cd74f4f88c990c5de5cbd9f63/tools/todo_tool.py)；OpenAI [`Follow a goal`](https://learn.chatgpt.com/use-cases/follow-goals)（访问日期 2026-08-17）。这些来源说明机制如何实现，不替代本工程的需求 baseline。

### 2.6 当前证据证明了什么

**当前证据已经覆盖工作清单的控制面、执行前取证、跨轮事实消费和完整 Plan 结果契约，但四类证据不能互相替代。** 当前能力结论以 v51 为准；早期失败和已撤回候选只保留在评测归档与未来设计中。

| 证据 | 直接证明 | 不能外推 |
| --- | --- | --- |
| `CONV-001` | 单行消融丢弃已准入清单后，用户看不到也无法修订；目标路径提供两个可审阅版本 | 工作清单必然提高最终答案正确率或降低成本 |
| `CONV-004` | 规划安全读取产生的 `Observation` 必须能够进入正式 Plan 阶段；目标路径返回带来源和只读约束的清单 | 所有读取都适合在审阅前执行，或单样本代表稳定性能 |
| `HARNESS-003` | 只关闭工作项绑定成功事实的消费时，重复原始读取从 `0` 变为 `2` | 冻结服务提供方等于真实外部服务，或重复读取变化代表普遍完成率收益 |
| `PLAN-REPLAN-001` v4 baseline | 三类自然调整稳定复现陈旧义务、错误完成或最终交付不完整 | 任意一个失败都由同一机制造成 |
| `PLAN-REPLAN-001` v51 target | 正式对话入口下三类场景各五次，结果为 `15/15 delivered`、`15/15 plan_ready`、`15/15 final answer`，最终待完成项为 0，服务提供方失败为 0 | 其他模型、搜索服务、任务分布和更大样本天然达到同样结果 |

v51 的 15 份归档属于同一配置样本组，校验和错误为 0，总令牌为 601,142，低于预声明的 842,495 门槛。当前生产链只保留通过局部反事实、契约消融或回归门禁的最小机制：交互阶段互斥、失效义务使用 `superseded`、Completion 只消费最新 Verification 结果、逐项语义结果唯一推导最终结论，以及经过截断对照确认的最终结构化输出预算。

这些结果证明当前配置下的纵向路径达到已声明门槛，不证明模型或服务提供方永不失败。DeepSeek 文档声明的偶发空结构化内容仍由有限重试与失败关闭处理；模型、服务提供方、提示词、预算或用户契约变化时，必须重新建立同配置样本组，不能复用 v51 直接宣布通过。

### 2.7 为什么不与后台调查规划合并

**前台工作清单和后台调查规划碰巧都含“目标、工作项、版本”，但它们不是同一业务事实。** 两者的修订机制也不同名：前台是用户在下一轮直接表达，模型在同一份 `ConversationWorkingPlan` 上提出新版本；后台是用户提交 `steering`，写入新的要求版本后由工作进程异步触发一次 replan。

| 对比 | 前台工作清单 | 后台调查规划 |
| --- | --- | --- |
| 事实归属 | 当前对话 | 后台调查项目 |
| 内容 | 短期可验收结果 | 子目标、依赖和要求覆盖关系 |
| 消费者 | 用户审阅、动作绑定、跨轮恢复、Completion 判断 | 工作进程、可执行集合、`steering` 修订、覆盖检查、项目 Completion |
| 生命周期 | 当前对话协调 | 跨请求、跨进程长期运行 |
| 不拥有 | 队列、租约和后台项目状态 | 对话审阅状态和前台最终消息 |

两者没有同步、转换或双写；对话只保存后台项目引用。完整的后台调查能力见[领域设计 §8](05-knowledge-and-domain-workflows.md#8-动态后台调查由新证据决定后续路径)，通用计划逻辑与外部机制坐标统一见[§2.5](#25-从通用计划逻辑到当前工程的能力映射)。

## 3. 有界模型上下文保留真源，只注入当前需要的信息

### 3.1 权限先于召回，需求先于压缩

**模型上下文的顺序是：先过滤可见性，再按当前需求召回，随后选择语义相关内容，最后按预算压缩。** 把越权内容取回后再要求模型忽略，本身已经越界。

同时进入模型的信息仍有不同责任主体：

| 注入内容 | 权威来源 | 模型看见什么 | 如何修改 |
| --- | --- | --- | --- |
| 当前工作清单及绑定事实 | 对话日志 | 有界只读视图 | 模型提出更新，Admission 后写回日志 |
| 与问题相关的个人证据 | 个人知识 | 当前用户可见的有界证据 | 进入知识专属写入口 |
| 后台项目进度 | 后台项目日志 | 按项目引用生成的只读投影 | 提交 `steering` 进入项目写入口 |
| 外部大结果 | 资源存储与执行日志 | 摘要、资源引用和按需窗口 | 重新读取，不复制第二份真源 |

上下文组装不拥有这些事实，也不能因为看见某项内容就自动保存知识、推进项目或宣布 Completion。

### 3.2 大型结果通过引用精确重读

**大结果保留完整真源，只把本轮必要片段交给模型。**

```text
大型工具结果
  -> 资源存储保存完整内容
  -> 执行日志提交有界片段、资源引用和省略信息
  -> 模型判断是否需要继续读取以及读取位置
  -> 返回新的有界片段
```

模型判断证据是否充分以及下一段读什么；工具校验引用、权限范围和单次读取上限；运行系统限制总轮次和总预算。`CTX-001` 证明多个大型结果并存时模型上下文仍然有界，并可通过重读完成指定回答；它不证明所有问题都能在固定页数内完成。

## 4. 业务能力与执行资源分开，执行只在获准后发生

**业务能力表达用户可验收的动作和结果责任；工具、MCP 接口和子智能体只是执行资源。** 模型可以用统一结构提出 Proposal，运行系统仍要按照事实归属、权限和风险决定执行入口。

| 模型提出的动作 | 事实归属 | 正式执行入口 |
| --- | --- | --- |
| 低风险只读调用 | 工具或服务提供方契约 | 受治理工具执行 |
| 保存、删除、创建后台项目 | 具体业务 | 能力专属 Admission 与唯一业务写入口 |
| 有界子目标 | 父目标与子任务结果契约 | 受治理的子智能体委托 |

工具可见、当前获准和服务健康是三个不同事实。远端发现接口只说明其声明了结构；本地投影决定模型是否看见，策略和 Admission 决定本次是否允许，真实调用结果才说明服务是否可用。网页、文件和工具输出都是数据，不能借内容获得新的控制权。

```text
本轮可见工具投影
  -> 模型提出 ToolCallProposal
  -> Admission 校验名称、参数、当前阶段和预算
  -> 策略与执行网关校验权限范围、风险和确认
  -> 工具或外部服务产生执行事实
  -> 有界 Observation 进入下一次模型调用
  -> Verification 与 Completion 判断用户结果
```

工具描述和输入结构服务模型选择，但不拥有授权；`ToolCallProposal` 只是候选动作；执行网关只产生执行事实，也不拥有业务完成标准。这条分离使工具数量、模型决策和业务生命周期能够独立演进。

### `Capability Projection` 到底做了什么

**`Capability Projection` 只生成“本轮允许模型看见的动作菜单”，不执行动作，也不拥有工具定义、权限或可用性。** `ConversationService._effective_capabilities()` 从当前已装配的业务入口、公开工具和子智能体配置生成 `EffectiveCapabilities`；`build_interaction_system_prompt()` 随后把这份只读 JSON 放入本次模型上下文。

当前实现做了四类具体裁剪：

- 没有关联调查项目时，菜单包含 `start_durable_investigation`；已经有关联项目时，菜单改为 `steer_investigation_project`。两者不会同时出现。
- 运行系统专用的 `verify_interaction_draft` 和 `exposure != public_agent` 的固定流程工具不进入菜单。它们仍可由自己的运行入口调用。
- 已有知识业务读取入口时，原始笔记读取工具被排除，避免模型绕过知识证据和权限边界。
- 每个保留动作只投影名称、说明、输入结构和 `read_only`、`planning_safe`、`safely_retryable` 等选择信息；服务健康、授权结果、执行状态和 Completion 不进入投影。

例如，注册表同时存在公开网页搜索、隐藏 Verifier 和调查项目动作时，普通新对话只会向模型展示网页搜索与“创建调查项目”。模型提出调用后，Admission 和执行网关仍会重新校验名称、参数、阶段、预算和权限。即使模型猜出隐藏 Verifier 的名字，也不能通过普通对话执行它。

当前证据证明的是边界，不是普遍能力收益。`test_the_real_verifier_is_not_a_capability_the_model_can_see` 证明内部 Verifier 不进入模型菜单；`test_hidden_workflow_tool_cannot_execute_through_ordinary_conversation` 和 `TOOL-AUTH-001` 证明猜出隐藏名称仍会在副作用前被拒绝；`GOV-001` 从自然 Conversation 入口证明恶意文本没有触发隐藏工具；`E19` 证明能力缺失时返回限制而不是伪造执行。当前没有一组干净消融证明“有 Projection 比无 Projection 提高答案正确率或成本”，因此面试中应把它称为模型可见面的安全只读投影，而不是独立业务能力或通用适配层。

### 4.1 治理成本只放在真实风险边界

**普通只读调用在 Admission 后直接执行；需要确认、跨请求恢复或不可安全重试的副作用才冻结为不可变 `Command`。** `digest` 只绑定用户确认、日志和执行过程引用的同一份冻结内容，不是身份、授权或成功证明。`Command`、Event 和 `Receipt` 也不机械成套创建，各自必须有审批、审计、恢复或外部关联的真实消费者。

当前 `exposure` 规则区分模型可动态选择、固定流程专用和管理类工具。`TOOL-AUTH-001` 的运行一致性 baseline 曾证明普通对话可从全量注册表解析隐藏工具；现在模型发起路径的名称校验和执行都通过同一 `ToolExecutor._interaction_tool` 要求 `public_agent`，隐藏工具在副作用发生前被确定性拒绝。`GOV-001` 另从自然 Conversation 入口证明恶意外部文本没有触发隐藏工具：前者证明运行不变量，后者证明一个用户场景，不能相互替代。

### 4.2 子智能体只完成有界子目标

**只有子目标可以独立交付产物，并且隔离上下文或独立执行确有价值时，才委托子智能体。** 普通数据读取优先使用工具，稳定事务优先使用业务服务或固定流程；不能因为任务较长就创建子智能体。

父智能体拥有原始目标、上下文投影和最终结果契约。子智能体只接收有界子目标、允许外发的上下文引用和预算，并返回产物或状态。稳定提交键避免恢复时重复提交，取消后的迟到结果必须隔离。远端显示完成只能证明子任务终止，不能直接完成父请求。

本地契约测试证明父智能体能提交有界子目标、接收 `AgentArtifact` 并继续 Completion。对齐 DeepSeek 配置后的真实 `E17` 已得到成功子任务和父级答案，说明正式委托路径可达；20 个显式委托样本只有 `10/20 delivered`，另外 10 个分别因委托结果缺失和官方来源缺失失败。三类自动委托价值 pilot 中，非委托 baseline 已满足结果契约，target 也没有调用子智能体，因此按 A0 门禁停止剩余样本。面试时可以介绍委托、作用域、恢复、父级验收和真实失败分布；不能声称 GPT Researcher 已稳定上线，也不能声称多智能体提高正确率、成本或延迟。

真实后台归档还暴露了一个比 Prompt 更基础的所有权错误。accepted Plan 已完整保存“研究 A2A/MCP 官方变化”和 required output，Execution Proposer 却允许模型再次填写 `bounded_sub_goal`；MiMo 曾只返回 `sub-2` 或 `acq`，GPT Researcher 随后把它们解释为法律合同术语和 Acquisition.com。当前设计删除模型对该字段的写入口，由 Application 把 accepted SubGoal 的 objective 与 required output 确定性编译为远端任务；Admission 对绕过路径要求完全相等。失败测试、消费点消融和真实 MiMo target 都证明远端实际收到的文本与 accepted SubGoal 一致且不是 logical ID，后者还产生了 A2A 官方 Artifact，因此目标所有权机制已闭环。它证明的是命令绑定，不是最终调查完成，因为两个 focused target 都没有形成 SubGoalOutcome。

第二个坑发生在 Artifact 到下一次 Tool 的边界。首个 focused target 的 Agent Artifact 已包含官方 A2A URL，Verifier 正确要求继续读取直接证据；旧 `observed_url_locators()` 只认识 Web Search 的固定 JSON，导致 repair 的 `capture_url` 获得空参数并被真实 Tool Schema 拒绝。当前 A1 候选把 admitted Artifact 文本中的既有 URL 派生为只读候选，让模型只选择 `candidate_id`，Application 再绑定原 URL；无候选时 Admission fail closed。单元消融成立，但后续真实 target 选择了再次委托 Agent，没有消费 `capture_url`，因此不能把这项修复升级为真实效果证据。

第三个坑是“要求官方来源”仍可能只停留在自然语言目标中。工程曾用一个最小候选把模型提出的来源域沿 `AgentExecutionOperation -> AgentTask -> A2A query_domains -> DuckDuckGo site:` 贯通；旧实现的 9 个失败测试在候选后全部通过，证明 typed 执行链可以机械闭合。但正式 MiMo Proposal 探针先生成了带路径的 GitHub 值和错误的 A2A 域名，hostname 校验拒绝后，一次结构化修订又把域列表清空；该次调用记账 2,748 tokens。候选因此在长链路 target 前撤回。这个案例说明原生 `json_schema` 只约束形状，不证明模型正确识别组织或产品的官方域；校验器也不能擅自截断路径、纠正域名或硬编码答案。面试时应明确区分“本地传递链缺失”和“Provider 无法安全提出语义值”：前者可由类型和契约测试修复，后者未过准入门槛就应停止，而不是用确定性代码伪造模型能力。

这组失败也说明 MiMo 与 DeepSeek 的差异不能压缩成“谁更强”。同一 v3 后台任务族中两者都是 `0/20 delivered`；DeepSeek 的入口和 worker 模型调用更快，失败阶段更靠后，MiMo 则更容易在 Plan、修订和完整链路延迟上消耗窗口。MiMo 的原生 `json_schema` 能保证类型结构，却不能保证 ID 唯一、领域词表一致、委托目标不被缩写或来源属于官方域。面试时更有价值的回答是：服务提供方改变失败分布，确定性边界负责保护 canonical facts 和执行参数，Verifier 负责拒绝离题或非官方证据，最终仍由同入口 Outcome 评测决定是否有效；不能因为某个 Provider 产生更多 Artifact 就宣布效果更好。

### 4.3 预算是一份统一交互策略

**模型轮次、工具调用和上下文令牌只有约束不同成本或失败语义时才分别存在。** 同批动作在执行前按最新用量预留预算，不能各自读取旧余额后同时超限。预算耗尽时返回能力限制、暂停或请求用户输入，不用确定性代码拼出替代答案。`RUN-001` 证明同轮三个 Proposal 在工具上限为 2 时最多执行两个。

子智能体委托还必须满足“子授权不扩大父预算”。`ProjectBudgetLedger` 是调查项目剩余额度的唯一派生责任主体；Context 让模型看见当前可用额度，动态 Schema 降低越界 Proposal 的生成率，Admission 关闭绕过 Schema 的路径，执行预留再处理 Proposal 接受后的并发消耗。正式 MiMo v2 target 为 `20/20 background_started`，6 个 Agent Proposal 的运行时间与 Project token/cost 越界均为 0。只关闭 Schema 和 Admission 的第一次消融无效，因为模型仍从 Context 看到了剩余额度；完整消融同时关闭 Context、Schema 和 Admission 后，8 个 Proposal 中有 2 个把 cost 授权扩大到 500 和 50，而 Project 上限只有 20。这个坑说明，消融必须覆盖机制的全部生产消费点，否则“没有退化”可能只是另一个消费点仍在工作。当前证据证明授权范围闭环，不证明 GPT Researcher 的实际账单或 token/cost Receipt 已闭环。

### 4.4 工具结果必须先成为受约束的执行事实

**工具成功只说明外部动作返回了结果；结果内容是否结构合法、来源可信和足以支撑答案仍需分别判断。** 大型结果先保存完整正文，再把有界片段和资源引用写入 `Observation`；模型需要更多内容时，通过受权限范围和窗口限制的读取重新取得。

`CTX-001` 和 `E21` 分别证明冻结服务提供方和真实 GitHub MCP 下的大结果卸载与精确重读。`TOOL-RESULT-CONTRACT-001` 已把 MCP 配置声明的结构带到实际结果边界：适配器按 JSON Schema Draft 2020-12 校验 `structuredContent`，拒绝 `isError=true`，也拒绝结构化内容与文本 JSON 冲突。外部结果中的提示指令仍只作为数据；是否发生越权调用由确定性授权门禁和 Completion 共同约束，不能依赖模型自律。

### 4.5 当前工具证据证明到哪里

**当前工程已经展示工具发现、真实调用、能力缺失、确定性曝光门禁、结果契约、预算、恢复和大结果处理；100 个公开工具下的规模 baseline 也达到当前门槛。**

| 用例 | 直接证明 | 不能外推 |
| --- | --- | --- |
| `E16/E18` | 真实 GitHub、Notion MCP 能从对话入口返回指定结果 | 任意 MCP 服务、权限和输出结构都正确 |
| `E19` | 工具能力缺失时返回明确限制，调用次数为 0，答案不编造 | 运行中工具撤销或结构变化已经处理 |
| `TOOL-AUTH-001/GOV-001` | 隐藏工具在运行时被确定性拒绝；一个恶意冻结文档样本也没有触发隐藏调用 | 完整组织角色权限或所有提示注入都已覆盖 |
| `RUN-001` | 同轮三个 Proposal 在工具预算为 2 时最多执行两个 | 所有成本、并发和速率限制都已经优化 |
| `L03` | Web 进程重启后复用已提交执行顺序且不重复调用 | 所有第三方副作用天然恰好执行一次 |
| `CTX-001/E21` | 大结果有界进入模型上下文，并能按引用重读目标事实 | 多服务提供方和资源失效均已覆盖 |
| `TOOL-RESULT-CONTRACT-001` | 已声明 MCP 结构不合法、远端错误或双表示冲突时 fail closed | 所有未声明 schema 的开放结果都具有业务语义验证 |
| `TOOL-DISCOVERY-SCALE-001` | 10、30、100 工具组均为 `20/20`；100 工具组逐样本不超过 32,000 总令牌 | 任意更大规模、任意模型或所有相似工具面都无需按需发现 |

当前每轮仍完整物化全部公开工具定义。10、30、100 个候选的预声明规模组均通过，所以按需 Tool Search 已退出本轮优化；这是一条“不增加机制”的证据。只有工具数量、schema 复杂度或模型变化后重新出现用户结果或令牌失败，才从新 baseline 准入。

## 5. 恢复复用已提交事实，只继续未完成语义

**恢复不是根据原始提示重新思考整件事，而是还原已提交事实、对账结果不明的外部动作，并继续处理未完成结果。**

| 恢复前事实 | 恢复动作 |
| --- | --- |
| `Observation`、工作清单或 `Receipt` 已经提交 | 直接复用，不重新生成对应动作 |
| 外部请求已发出但本地结果不明 | 用稳定提交键查询并对账 |
| `Command` 已冻结但尚未执行 | 对同一 `digest` 做幂等执行 |
| 后续路径尚未冻结且新事实改变依赖 | 可以继续调用模型决策 |
| 进度、覆盖率和上下文视图 | 从权威事实重新派生 |

`checkpoint` 不是“恰好执行一次”的魔法；业务副作用仍需要幂等键、查询或补偿。只有承诺跨请求、跨进程或不可重复副作用的路径才承担完整恢复协议，普通单次交互不机械升级为长期项目。

## 6. 动作执行、Verification 和 Completion 必须分开

**动作发生、目标满足和结果齐全是三个不同问题。**

| 阶段 | 回答的问题 | 依据 |
| --- | --- | --- |
| 动作执行 | 动作是否真实发生 | 工具结果、Event、`Receipt` 或产物 |
| Verification | 结果是否满足目标 | 验证结论和已验证引用 |
| Completion | 用户要求是否全部交付 | 终态结果、完成报告或缺失项 |

Verification 可以拒绝“已经满足”的声明，不能推翻已经发生的删除或发送；Completion 门禁检查结果是否齐全，不重新执行开放语义判断。有工作清单时，清单没有未完成项是 Completion 条件之一，但工具成功仍不会自动把工作项变成完成。计划如何参与 Completion 判断已在[§2](#2-按需工作清单提升复杂任务的跨轮完成能力)完整说明。

## 7. 可观测性解释失败，不制造业务事实

**追踪记录要区分未选择、Admission 拒绝、执行失败、Verification 失败和 Completion 证据缺失。** Proposal 不能记录成已执行 Event，策略拒绝不能伪装成服务返回空结果，追踪投影也不能成为第二个业务写入口。`OBS-001` 证明跨用户访问既不泄漏内容，又能通过同一运行引用定位为权限范围拒绝。

### 7.1 安全由权限、数据边界和脱敏共同承担

**提示注入防护不能只靠一个“安全提示词”；真正的安全边界必须在模型之外拒绝越权读取、调用和数据外发。** 当前上下文先按用户作用域过滤，工具执行再经过策略、曝光规则与 Admission，MCP 结果契约在适配边界 fail closed，敏感追踪内容默认脱敏。个人知识不再每轮预取；模型只有在用户正向要求使用已保存事实时，才可选择只读 `search_personal_knowledge`，身份和作用域仍由服务端绑定。

`SECURITY-REAL-001` 的旧路径为 `15/20 delivered`：目标完整性、隐藏调用和跨用户隔离各为 `5/5`，但五个“不要输出我的个人资料”样本都在模型调用前物化了个人知识。当前 target 为 `20/20 delivered`，20 组对照均通过身份和 checksum 校验；正向 Memory 回归另为 `15/15 delivered`。这证明按需个人知识检索解决了本组 Context 外发问题，不等于所有提示注入和个人信息类型都已覆盖。源码审计发现原 Content Guard 没有生产消费点，已删除；当前没有通用个人信息内容检测或提示注入分类器。

## 8. 面试时按“错误—机制—证据—边界”介绍能力

每项关键能力只讲四步：

1. 没有它时用户会遇到什么错误；
2. 哪个责任主体用什么机制阻止错误；
3. 哪条正式证据证明用户结果发生变化；
4. 结论不能外推到什么范围。

不要从类名、字段或流程图开始，也不要用“优秀智能体都这么做”“有 `checkpoint` 就能恰好执行一次”“工具成功就等于完成”替代证据。

## 9. 当前实现坐标

**以下名称只帮助进入代码，不承担前文的设计论证。**

| 设计概念 | 当前代码坐标 |
| --- | --- |
| 对话交互主循环 | `application/conversation/service.py` |
| 模型上下文与指令组装 | `application/conversation/interaction_prompt.py` |
| 结构化模型调用、重试与脱敏追踪 | `infra/structured_model.py` |
| 模型调用准入与数据外发边界 | `capabilities/model_resolution.py` |
| 工具投影、参数校验与调用适配 | `governance/registry.py` |
| 工具策略与统一执行边界 | `governance/policy/engine.py`、`governance/gateway.py` |
| MCP 工具适配 | `tools/mcp.py`、`infra/mcp.py` |
| 工具曝光与运行时调用门禁 | `governance/registry.py` |
| 子智能体执行边界 | `agents/gateway.py` |
| 已提交事实与工作清单恢复 | `application/conversation/journal.py` |
| 工作清单确定性 Admission | `application/conversation/working_plan.py` |
| 一次模型语义 Proposal | `AgentTurnDecision`（历史代码名，不代表完整应用级交互） |
| 模型提出的工作清单 | `WorkingPlanProposal` |
| 当前对话已接受的清单 | `ConversationWorkingPlan` |
| 后台项目拥有的调查规划 | `AcceptedPlanVersion` |
| 后台项目的用户修订入口 | `SteeringCommand` 与 `ReplanRequest` |
