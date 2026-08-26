# 设计优化队列

> 本文件只保存当前判断、尚未关闭的设计问题、准入证据和退出条件。已完成、已撤回或仅用于诊断的候选不再保留执行流水；对应事实由[当前端到端用例盘点](../evals/02-current-case-inventory.md)、checksum 归档和 Git 历史保存。核心架构、调查项目状态、Phase 0 入口和生产风险文档已收缩为当前事实和权威链接，不再复制历史实验表。

## 1. 当前判断

当前工程的主要风险不是缺少更多 Agent 名词，而是独立调查项目仍未交付最终用户结果。Plan、Memory、工具和安全边界已经分别形成可执行机制证据；它们不能与失败的调查项目链路拼成“完整调查能力已经交付”。

| 领域 | 当前状态 | 允许的下一步 |
| --- | --- | --- |
| 对话 Plan | A2；当前 15 样本完整 target 已通过 | 模型、服务提供方或用户契约变化时重新执行 O0，不继续增加 Plan 类型 |
| Memory | 已关闭已证明的授权、规模检索和工作记忆问题 | 只有新的自然失败才能准入纠错、情景记忆或程序记忆 |
| 工具 | 当前规模下不需要 Tool Search；授权与结果契约已有真实证据 | 运行中能力漂移或组织级授权失败后重新准入 |
| 独立调查项目 | 20 个正式请求均创建 Project，但当前完整样本为 `0/20 delivered` | 停止局部补丁链，先评审重复编排架构 |

当前服务提供方为 MiMo。历史 DeepSeek、AnySearch、TalorData 和旧 MiMo 归档只证明各自冻结配置下的结果，禁止跨配置拼接。运行命令、证据身份和发布规则见[评测执行与发布](../evals/04-running-and-release.md)。

当前收敛状态保存在 `refs/evidence/design-convergence-20260826-target`：干净快照全工程回归为 `849 passed`，Ruff 与 Markdown 本地链接检查通过。该快照是代码和文档的可还原身份，不改变下文各项产品证据的适用边界。

## 2. 优化执行与停止契约

优化必须以用户结果为终点。中间状态、事件数、Artifact、工具或智能体调用只能定位阶段，不能自动生成下一项生产改动。

### 2.1 准入等级

| 等级 | 已有证据 | 允许动作 | 退出条件 |
| --- | --- | --- | --- |
| A0 | 风险或单次异常 | 复核正式入口、配置和评测器，执行失败 baseline | 当前路径满足目标、环境失败或无法稳定复现时退出 |
| A1 | 可归因失败 baseline | 定位唯一责任主体，执行失败优先断言和可还原消融 | 消融不能解释失败时撤回；跨多个局部主体时转入架构评审 |
| A2 | target 与消融形成因果对照 | 保留最小生产改动，删除旧路径并执行完整回归 | target 未达到预声明门槛时撤回，不追加补丁 |

### 2.2 架构评审升级条件

出现以下任一事实时，当前局部优化必须停止并转入架构评审：

1. 两个以上局部机制已经改善 Proposal、事件、预算或延迟，但同一产品评测器的用户结果没有改善；
2. 同一自然请求存在两个自治 Planner、Agent loop、状态恢复责任主体或可写 Plan；
3. 新增字段需要同时修改三个以上 Schema、Admission、Projection 或恢复分支，且差异不对应独立信任边界或生命周期；
4. target 失败后只能通过增加超时、预算、重试、样本窗口或服务提供方专用 Prompt 继续推进；
5. 生产 Model、状态和写入口持续增加，删除量为零。

架构评审仍然服从 baseline、target 和消融。优秀 Agent 只回答机制应如何组织，不能替代本工程的需求证据。

### 2.3 单项执行预算

每个候选只允许一个连续闭环：

1. 一组正式失败 baseline；
2. 一个最小失败优先断言；
3. 一个独立可还原的单变量消融；
4. 一个真实 target；
5. 一次完整回归和删除审计。

target 失败后必须选择“撤回、冻结 A1、转入架构评审”之一。本轮不得继续修复 target 新暴露的下一个局部问题。

## 3. 独立调查项目的开放架构问题

独立调查生命周期已经由正式入口、Web 重启和后台 worker 证明必要，但当前执行拓扑尚未证明必要。当前唯一产品目标是：用户提出后台调查后无需发送新消息，系统最终交付覆盖冻结要求、带可复核来源且通过 Verification 的中文报告。

### 3.1 当前失败事实

`INVESTIGATION-CONSOLIDATION-001-BACKGROUND` 是当前权威失败入口。单 worker 正式组为 `20/20 project_selected`、`0/20 delivered`；只把 worker 槽位增加到 4 后仍为 `0/20 delivered`。并发候选只改善了 Plan、Execution Proposal、ExecutionRef、Artifact 和少量 Outcome 数量，没有改善最终报告，因此已经撤回。

校验和有效的 focused 归档进一步显示：一次 GPT Researcher 已经完成并形成 `ExecutionRef`、Artifact 和 admitted evidence，外层子目标 Verification 随后拒绝该结果并触发 repair replan；观察结束时仍为 0 个 `SubGoalOutcome`。这说明失败发生在外部研究结果回到 Project 后，不是 Project 创建、worker 存活或 A2A 提交不可达。

权威坐标：

- 完整失败组：`data/e2e_traces/product_baselines/investigation-consolidation-001-background/target/20260826T030327.251670Z-28312-17d18ae1`；
- focused 失败组：`data/e2e_traces/product_baselines/investigation-agent-goal-binding-001-focused/target/20260826T055528.693087Z-23164-28ad3734`；
- 当前分类：[当前端到端用例盘点](../evals/02-current-case-inventory.md)中的“Research、Schedule 与 Investigation”。

### 3.2 当前重复编排

当前一次后台调查跨越三层运行身份：

```text
InvestigationProject
  -> AcceptedPlanVersion / SubGoalExecutionProposal
  -> ChildAgentRunRecord
  -> GPT Researcher A2A task
```

`InvestigationProject` 又执行以下外层循环：

```text
Plan -> Execution Proposal -> Agent Artifact
  -> SubGoal Verification -> repair replan
  -> Synthesis -> final Verification -> Completion
```

`GPTResearcherA2AAdapter` 的生产 profile 已声明一次委托能够生成多条查询、研究多个权威来源并返回一份证据报告。GPT Researcher 因此已经拥有内层规划、检索和综合循环。Project 再把同一研究目标拆成 SubGoal 并自动 repair，形成双重智能体循环；该拓扑是当前首要架构假设，不再默认把每个 `0 Outcome` 归因于下一个 Plan 字段。

### 3.3 优秀 Agent 的机制对照

以下实现均为 2026-08-26 复核的 A 级官方契约：

- Gemini [Deep Research agent](https://ai.google.dev/gemini-api/docs/deep-research)让一次后台 Interaction 自主完成“Plan、Search、Read、Iterate、Output”；协作式 Plan 审阅是可选边界，调用方保存 Interaction 身份并轮询或接收流式结果。
- OpenAI [深度研究模型](https://developers.openai.com/api/docs/models/o3-deep-research)拥有多步骤搜索与综合，[Responses API](https://developers.openai.com/api/reference/cli/resources/responses/methods/create)向调用方公开后台运行身份、状态、工具结果和最终输出。
- OpenAI Agents SDK 的 [Runner 契约](https://github.com/openai/openai-agents-python/blob/main/docs/running_agents.md#the-agent-loop)让 Runner 拥有工具调用、handoff 和 final output 循环，并明确提醒不要混用会重复上下文的两套持久化策略。

本工程只采纳“自治研究循环由一个责任主体拥有，Application 保存产品生命周期和交付事实”的语义。不复制任何厂商的模型、Interaction、Response、Runner 或内部 Plan。

### 3.4 Project Plan 的当前内聚边界

初始 Plan 与修订 Plan 必须分离。初始 Plan 定义完整待执行图；修订 Plan 只能修改非冻结部分并保留已经发生的执行事实，两者具有不同写权限。

普通 revision 与 verification repair revision 不具有独立事实责任主体。两者都由单一 `_PlanRevisionDraft`、单一物化路径和同一 Admission 语义处理；repair 只多出“新工作修复哪个冻结 gap”的条件字段。动态输出 Schema 按是否存在冻结 gap 限制 repair 字段，不创建第二 canonical revision 类型。

### 3.5 单次深度研究委托已经撤回

`INVESTIGATION-SINGLE-RESEARCH-RUN-001` 已按预声明退出条件撤回，生产路径没有切换。诊断使用当前 MiMo、GPT Researcher、`max_search_results=1` 和 240 秒预算，通过生产 `AgentGateway` 只创建一个 `ChildAgentRunRecord`。任务到期时仍未形成报告，随后由同一 run 的取消入口收敛；归档只有 `Cancellation requested.`，没有官方来源、用量或可验收内容。

服务提供方日志显示，agent-role 选择阶段约 172 秒后仍得到错误 JSON 形状并回退默认角色，此后才开始检索。没有外层 Project Plan、SubGoal Verification 或 repair 时，单次委托仍无法在现有预算内完成，因此双重智能体循环不是唯一根因。工程不得通过增加超时、检索数、预算或重试恢复该候选。

checksum 有效归档：`data/e2e_traces/provider_diagnostics/single-research-run-001/20260826T080644.156807Z-25844-8ca385f4`。该证据属于服务提供方诊断，不是产品 target，也不证明保留现有 Project 外层循环能够交付报告。

### 3.6 结构化输出必须由产生决策的调用拥有

单次委托失败不是主工程 `STRUCTURED_OUTPUT_TRANSPORT` 的错误。主工程的 `StrictJsonSchemaAdapter` 与 `JsonObjectStructuredAdapter` 都在每次 `StructuredModelRequest` 处携带 Schema、解析并用 Pydantic 校验；但 A2A 另一端的 GPT Researcher 不会继承这个进程内配置。

当前部署对应 GPT Researcher 提交 [`18d4051`](https://github.com/assafelovic/gpt-researcher/tree/18d405166948e11b4a0304c0c4ec440bead9e4a5)。[`choose_agent()`](https://github.com/assafelovic/gpt-researcher/blob/18d405166948e11b4a0304c0c4ec440bead9e4a5/gpt_researcher/actions/agent_creator.py) 调用自由文本 `create_chat_completion()`，随后依次尝试 `json.loads`、`json_repair` 和正则提取；[`auto_agent_instructions()`](https://github.com/assafelovic/gpt-researcher/blob/18d405166948e11b4a0304c0c4ec440bead9e4a5/gpt_researcher/prompts.py#L485-L511) 的第一个示例还把 `agent_role_prompt` 的引号写错。这个边界没有类型化输出，因此不能把返回值解析失败归因于 MiMo 不支持主工程的 `json_schema`。

#### 外部机制对照（External Mechanism Comparison）

| A 级实现 | 结构化输出的责任主体 | 失败边界 | 本工程结论 |
| --- | --- | --- | --- |
| OpenAI Agents SDK [`output_type`](https://github.com/openai/openai-agents-python/blob/main/docs/agents.md#output-types) | 产生最终结果的智能体声明 Python/Pydantic 类型，Runner 将其作为结构化输出 | 严格 Schema 不兼容时必须显式选择非严格或自定义 Schema，不由外层调用猜测 | `agent-role` 决策若保留，必须在 `choose_agent` 调用处声明唯一类型化契约 |
| Google ADK [`LlmAgent.output_schema`](https://github.com/google/adk-python/blob/main/src/google/adk/agents/llm_agent.py#L2811-L2840) | 产生输出的 `LlmAgent` 拥有 Schema，只在最终输出阶段强制结构 | 下游智能体工具继承该 Schema，而不是从另一进程的全局配置隐式推导 | A2A 协议只传任务与结果；主工程的输出传输方式不是远端角色决策的责任主体 |
| DeepSeek [JSON Output](https://api-docs.deepseek.com/guides/json_mode/) | 每个 Chat Completions 调用显式设置 `response_format={"type":"json_object"}`，提示词同时给出 JSON 要求和样例 | JSON 合法不等于符合业务 Schema，调用方仍需类型化校验 | 主工程 `JsonObjectStructuredAdapter` 已实现该机制；它不能修复远端的自由文本调用 |

当前不修改主工程的输出传输方式，也不新增服务提供方适配层。生产消费者审计显示，动态 `server` 只进入日志，动态 `role` 只进入后续研究 Prompt；A2A Agent Card 已把该入口定义为单一“生成研究报告”能力，没有第二个领域能力、权限边界或执行路由消费这次动态分类。因而选择对象更少的候选：只在 A2A 构造边界绑定确定性的通用研究角色，核心 GPT Researcher 的其他入口继续保留原有自动角色选择。这不是把开放语义判断搬进确定性代码，而是删除一个没有独立产品消费者的二次路由。

单变量诊断复用 `SINGLE-RESEARCH-RUN-001` 的任务、MiMo 配置、检索上限、240 秒预算和评测器，只改变 A2A 是否执行动态角色调用。target 必须同时满足：trace 不出现 `choose_agent`，研究进入检索的时间早于旧 baseline 的 172 秒，A2A 在预算内形成非空报告和至少一个可复核来源，checksum 有效；任一条件失败即撤回 A2A 角色绑定，不增加超时、检索次数、重试或第二个结构化输出层。单次通过只把该条目推进为服务提供方兼容诊断，不足以声称稳定产品交付。

该诊断已按冻结条件完成。相同任务和配置下，A2A 在 96.26 秒形成 1 个 Artifact 和 1,711 字符报告，覆盖 Gemini 与 OpenAI Agents SDK 两个官方来源组；目标时间窗内 `choose_agent=0`，约 3.2 秒开始检索，归档 checksum 错误为 0。旧 baseline 为 240.14 秒超时、无报告、无来源。A2A 确定性角色绑定因此保留，类型化角色选择候选退出；归档位于 `data/e2e_traces/provider_diagnostics/single-research-run-001/20260826T090627.447856Z-28372-b872fcb7`。相邻 GPT Researcher 的可还原 target 为 `refs/evidence/gpt-researcher-mimo-compatibility-001-target`（`49cf5aa`），干净快照契约为 `5 passed`，Python 编译检查通过。

完整研究结果仍未通过：报告缺少 grader 要求的完整机制覆盖和迁移/退出建议，服务提供方 usage 也没有成为 typed 事实。因此该结果只关闭 `GPT-RESEARCHER-MIMO-COMPATIBILITY-001` 的角色输出兼容问题，不关闭调查报告交付、证据质量或计量问题。

### 3.7 AgentRun timeout 事实必须独立闭环

诊断同时发现，时间预算到期后调用 `cancel()` 会把原因记录为 `cancelled`。用户取消与运行超时具有不同责任主体、恢复策略和可见语义，不能共用一个终态。Conversation 正式 Use Case 的故障注入和 `AgentGateway` 契约测试在旧路径上均失败：前者观察到 `cancelled`，后者没有 timeout 写入口。

当前实现由 `AgentGateway.timeout()` 拥有预算到期事实：执行网关仍调用服务提供方取消以停止外部工作，但 canonical `ChildAgentRunRecord` 记录 `timed_out`、typed error 和 `timed_out` event；如果取消竞态已经返回真实完成或失败，则保留该执行事实。`InteractionAgentPort` 同步拥有 submit、poll、cancel 与 timeout，Artifact Port 不再错误声明 Agent 生命周期方法。旧路径为 `2 failed`，实现相关断言为 `4 passed`、相邻回归为 `119 passed`、全工程回归为 `851 passed`。干净快照 `f18b26d` 上，Conversation 故障注入和 Gateway 契约为 `2 passed`；只把 Conversation 生产消费点改回 `cancel()` 后，同一 Application 断言以 `cancelled != failed` 重新失败，还原后再次 `2 passed`。该证据关闭 timeout 事实归属，不证明真实研究交付。

服务提供方仍没有返回可核验 usage，`ChildAgentRunProjection` 也没有 typed usage 字段。该缺口保持显式未通过；不能用 timeout 修复声称 Agent 计量已经闭环。

### 3.8 已撤回的 repair 依赖候选

`INVESTIGATION-REPAIR-DEPENDENCY-BINDING-001` 曾在 Plan materialize 时把非 frozen 下游依赖从 frozen gap 自动改指向唯一 repair，并由 Admission 拒绝绕过。旧实现、局部断言和消费点消融证明该编译在机械上成立，但当时没有真实 repair Outcome，不能证明它改善用户结果。

A2A 角色输出兼容问题关闭后，只执行了一次正式 `POST /api/conversation/turn` 重审。Plan v2 确实消费了候选：`subgoal-2` 升为版本 2，依赖改为 `subgoal-1-repair`；两次 Agent 委托均与 accepted SubGoal 完全绑定，形成 3 个 Artifact、4 个来源 URL，事件序列为 91。但 Project 仍为 0 Outcome：Verifier 先拒绝 repair 报告，因为“分析性综合”不满足“官方原始内容摘要”契约，随后 planning token budget 用尽并暂停。归档 checksum 错误为 0，位于 `data/e2e_traces/product_targets_repair_reassessment_v1/investigation-agent-goal-binding-001-focused/target/20260826T091932.903518Z-18328-c74e5735`。

因此依赖绑定不是当前最早阻塞点，候选及其专用测试、harness 和消融已经删除。Verifier 对 repair 结果契约的可满足性与拒绝后的 planning budget 是两个不同问题；当前各只有一个样本，不创建新的生产分支。重新准入必须分别建立可重复失败 baseline，不能从本次归档直接推导 Prompt、Verifier 或预算修改。

## 4. 其他领域的重新准入边界

### 4.1 对话 Plan

当前 Plan 只协调一次 Conversation 的待完成结果。模型提出开放语义修订，Application 保护已完成事实，Verification 判断语义满足，Completion 检查结果契约。后台调查 Project 的 Plan 不得复制到 `ConversationWorkingPlan`。

只有以下情况重新准入：

- 用户修改目标后仍执行已撤回义务；
- canonical Plan 已完成后仍重复调用工具；
- 缺少证据却宣布成功；
- 服务提供方或模型变化后完整 target 退化。

### 4.2 Memory

当前 Memory 结论按存储职责分离：

- Agent State 保存当前运行所需结构化状态；
- LLM Context 是当前调用实际可见的临时物化；
- Checkpoint 只保存恢复事实；
- Long-term Memory 保存跨会话可召回事实；
- Retrieval Index 是可重建投影，不是事实源。

授权边界、规模检索和真实工作记忆已经有独立证据。情景记忆、程序记忆和自然纠错没有新的失败 baseline，不进入开发队列。

### 4.3 工具

当前工具路径为“临时能力投影 -> Proposal -> 参数与曝光校验 -> Policy/Admission -> 执行网关 -> Observation -> Verification/Completion”。10、30、100 工具样本没有复现发现规模失败，因此不引入 Tool Search。

以下情况重新准入：

- 工具在一次运行中增加、删除或授权变化，旧投影仍被执行；
- 组织角色与资源权限无法由当前身份范围表达；
- MCP structured content 或资源引用未进入结果契约；
- 工具返回成功但用户结果稳定失败。

### 4.4 多智能体与性能

`MULTI-AGENT-VALUE-001` 的最简单路径已经满足三类输入，target 也没有发生委托，因此自动多智能体优化退出。`AGENT-PERF-001` 的显式委托组只有 `10/20 delivered`，只证明路径可达；在结果缺失和官方来源缺失关闭前，不宣称稳定委托能力。

## 5. 当前开放队列

当前没有处于实现或 target 阶段的优化条目。最近一次正式重审暴露了 repair 结果契约和拒绝后的 planning budget 两个不同现象；在各自形成可重复、可归因 baseline 前，它们只属于观察事实，不进入开发队列。

已撤回的 `INVESTIGATION-SINGLE-RESEARCH-RUN-001` 与 `INVESTIGATION-REPAIR-DEPENDENCY-BINDING-001` 不属于开放队列。恢复它们必须重新提交对应责任边界的失败 baseline，不能复用历史失败归档作为通过证据。

未列入本表的历史候选均不处于活动开发状态。恢复旧候选必须重新提交失败 baseline、当前代码身份、External Mechanism Comparison 和退出条件，不能从历史章节复制实现。

## 6. 共同评测契约

所有产品 target 必须从正式 API、CLI、消息入口或 Application Use Case 进入，并经过生产组合根、真实持久化和用户结果依赖的真实服务提供方。自动断言至少覆盖用户结果、关键反事实、身份范围、重复副作用、服务提供方或环境失败、用量、延迟和校验和。

Unit、对象存在、状态为 success、Artifact、工具调用、智能体调用和 Trace 步骤都不能替代用户结果。服务提供方诊断、Runtime Conformance 和产品 E2E 必须分别标注，禁止拼成组合能力证明。

权威资料：

- [当前端到端用例盘点](../evals/02-current-case-inventory.md)；
- [Baseline-first 审计](../evals/03-baseline-first-audit.md)；
- [评测执行与发布](../evals/04-running-and-release.md)；
- `data/e2e_traces/` 下的 checksum 归档。

## 7. 新条目模板

```markdown
## <编号>：<用户错误或可量化工程约束>

状态：A0 / A1 / A2。

### 同输入 baseline 与关键反事实

### 根因与唯一责任主体

### 两个独立 A 级参考实现

### 单变量消融和最小生产改动

### target、净复杂度预算与退出条件
```
