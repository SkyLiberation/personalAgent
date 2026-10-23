# 运行恢复与长任务能力参考

**长任务能力首先解决多轮决策如何保持目标、积累有效进展并收敛到完整结果；运行恢复负责在中断或执行边界后接续这些工作。** 保存对话或代码快照不能单独证明任务进展，后台运行也只改变执行方式。跨副作用边界的恢复仍需要独立幂等和完成事实。

本页拥有外部长任务推进与恢复机制的比较；资料等级、固定提交与采用边界见[参考索引](README.md)。

## 1. 长任务先保持增量进展，再处理执行边界

以下两项官方资料于 2026-10-13 核对。Claude Code 产品文档解释当前工作闭环；Anthropic 于 2025-11-26 发布的工程文章报告跨上下文编码实验。二者的身份和证明范围分别保留。

| 来源 | 机制与解决的问题 | 比较时应核对什么 |
| --- | --- | --- |
| [Claude Code：How Claude Code works](https://code.claude.com/docs/en/how-claude-code-works) | 模型循环收集上下文、行动和验证，并依据上一动作结果调整下一步；用户可补充信息或改变方向。会话持久化与自动压缩支撑连续工作，但早期细节仍可能丢失 | 新结果是否改变下一决策，用户要求是否持续有效；上下文处理是否保留当前任务所需信息 |
| [Anthropic：Effective harnesses for long-running agents](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents) | 跨上下文实验中，仅靠模型循环和压缩仍会留下未说明的半成品或过早宣告完成。实验用可验收功能清单、每轮增量实现、进展记录和 Git 历史交接，再按实际用户路径验证功能 | 下一会话能否区分完成与未完成事项、消费已有成果；局部进展是否经过验收，是否仍欠完整目标 |

Anthropic 的做法是面向全栈 Web 开发的一组实验机制，不代表 Claude Code 默认提供同一套功能清单和交接流程，也没有证明多智能体优于单智能体。借鉴到研究场景的比较问题是：已有证据、仍欠的依据和当前稿件能否接续，修订是否解除缺口并保留正确事实。这是对机制的场景映射，不能替代本地产品证据或直接决定文件格式、存储选型与生产方案。

## 2. 代表恢复机制

| 实现 | 恢复单位 | 突出能力与边界 |
| --- | --- | --- |
| DeepSeek Harness | session event log | [Architecture](https://github.com/deepseek-ai/deepseek-harness/blob/b150a551b8d465e31e418e1b2eaf5e79bbb7d28e/docs/architecture.md)把 durable log 作为 Context 可重建来源；[Compaction](https://github.com/deepseek-ai/deepseek-harness/blob/b150a551b8d465e31e418e1b2eaf5e79bbb7d28e/docs/subsystems/compaction.md)记录压缩事件并处理压力与错误恢复 |
| LangGraph | thread checkpoint | [Persistence](https://docs.langchain.com/oss/python/langgraph/persistence)保存每一步图状态，支撑 interrupt、fault tolerance、状态历史和 time travel；长期 store 与 checkpoint 分离 |
| Gemini CLI | 文件状态、对话和待执行工具 | [Checkpointing](https://github.com/google-gemini/gemini-cli/blob/3c311beac2e78336816dd4a123db39743f9fbf85/docs/cli/checkpointing.md)在文件修改前写 shadow Git 快照，同时保存对话与工具调用；`/restore`恢复并重新提出原动作 |
| Codex | Git 工作树与任务线程 | [Git worktrees](https://learn.chatgpt.com/docs/environments/git-worktrees)隔离并行状态，Handoff 在 checkout 与工作树间移动任务；代码身份不替代外部副作用或业务持久状态 |
| Hermes Agent | 工作目录 checkpoint | [Features overview](https://github.com/NousResearch/hermes-agent/blob/9dfbde19db7b108f9e961eec367ca5b54c8ad7d6/website/docs/user-guide/features/overview.md)在文件修改前快照并支持 `/rollback`；回滚只覆盖工作空间，外部动作仍需独立恢复协议 |
| OpenHands | 沙箱与 Action/Observation 会话 | [Runtime architecture](https://docs.openhands.dev/openhands/usage/architecture/runtime)在可隔离环境执行 Action 并返回 Observation；本地或远端沙箱不自动提供业务级 exactly-once 或 Completion |

## 3. 预算可见与硬停止必须分层

**优秀实现没有把“每回合告诉模型剩余预算”当作通用答案。** 确定性运行系统始终拥有硬上限；模型可见提示只是帮助收敛的软约束，不能替代停止事实。

- OpenAI Agents SDK 在 [Runner](https://github.com/openai/openai-agents-python/blob/89c02c828ee8510fe9a84ee6675608193aa13b02/docs/running_agents.md#the-agent-loop) 中由确定性 `max_turns` 终止循环，超限时抛出 `MaxTurnsExceeded`。SDK 允许应用使用 `call_model_input_filter` 注入自定义系统信息，但不会默认把剩余轮次写给模型。
- Gemini CLI 在 [client.ts](https://github.com/google-gemini/gemini-cli/blob/55b495d6db1794bf5b7f37a9bc03ebcab5103673/packages/core/src/core/client.ts) 中超出 `maxSessionTurns` 后先产生 `MaxSessionTurns` 事件并停止模型调用；[Session management](https://github.com/google-gemini/gemini-cli/blob/55b495d6db1794bf5b7f37a9bc03ebcab5103673/docs/cli/session-management.md#session-limits) 把交互模式定义为停止发送，非交互模式定义为错误退出。该路径也不依赖模型自觉停止。
- Hermes Agent 的[当前配置文档](https://github.com/NousResearch/hermes-agent/blob/37fd6eea9753cb2b6de08b7ab83a9e385a97b144/website/docs/user-guide/configuration.md#iteration-budget) 记录：早期在 70% 和 90% 反复注入轮次压力会让模型过早放弃复杂任务，因而已被移除。显式设置轮次上限后，预算耗尽时只注入一次收尾指令并允许一次宽限调用；可选墙钟预算只在 80% 注入一次收尾提示。

2026-10-21 再核对两个固定实际装配：[Gemini local executor](https://github.com/google-gemini/gemini-cli/blob/ed96faedfd5571f055c44f2c9509d62321d1138d/packages/core/src/agents/local-executor.ts)用 DeadlineTimer／AbortSignal 控制整次运行，超限收尾另有明确 grace；[OpenHands local conversation](https://github.com/OpenHands/software-agent-sdk/blob/6530325e9dd0ea1b6b4f1994d7dab52764cfc3f1/openhands-sdk/openhands/sdk/conversation/impl/local_conversation.py)核对原成本和迭代上限，写入对应 limit error 后停止。所读路径没有证明“每轮给模型墙钟倒计时”是共同机制。源码与摘要见[本轮归档](../../.tmp/research-capability-20261020/t5/deadline-reference-1/manifest.json)。本工程保留硬限和 Completion，不移植宽限或强制收尾；根据本地真实误估时间提出既有截止的事实投影候选，效果仍由本地用例判定。

这些实现区分模型提示与确定性硬停止，但不证明本工程某次失败由预算感知导致。本工程预算提示的准入由 [EVD](../devSpec/change-evidence.md)拥有，实际输入与事实投影由 [CTX](../devSpec/context-memory-retrieval.md)拥有；本页不另设实现门禁。

### 3.1 窗口、消费与工作量预算的不同口径

2026-10-21围绕长任务累计额度重新核对3个实现及Anthropic Messages API。源码、固定提交、官方文档原件和SHA-256见[来源清单](../../.tmp/long-task-budget-reference-20261021/source-manifest.json)。仅调研，没有运行第三方项目或发出付费模型请求；固定源码证明对应实现，动态官方文档按本次日期解释，不代表本工程已经接入。

| 对象及证据 | 实际装配或文档契约 | 可借鉴的边界 |
| --- | --- | --- |
| Codex `c7234c1174b27d9c55199fba0d546dc27d1b0415`，A类源码 | [`session/turn.rs`](https://github.com/openai/codex/blob/c7234c1174b27d9c55199fba0d546dc27d1b0415/codex-rs/core/src/session/turn.rs#L601-L724)在采样后消费[`context_window_token_status`](https://github.com/openai/codex/blob/c7234c1174b27d9c55199fba0d546dc27d1b0415/codex-rs/core/src/session/context_window.rs#L52-L118)，根据当前活动输入、scope及模型窗口判断自动压缩；[`ModelInfo.auto_compact_token_limit`](https://github.com/openai/codex/blob/c7234c1174b27d9c55199fba0d546dc27d1b0415/codex-rs/protocol/src/openai_models.rs#L529-L541)将该版本的常规阈值限制在实际模型窗口90%以内。压缩路径替换输入历史并保存checkpoint，详见[`compact.rs`](https://github.com/openai/codex/blob/c7234c1174b27d9c55199fba0d546dc27d1b0415/codex-rs/core/src/compact.rs#L406-L435) | 这是单次活动Context压力控制，不是累计费用或压缩次数上限。90%只描述该固定版本及常规scope，不能直接设为本工程通用阈值；窗口、阈值配置由[官方配置说明](https://learn.chatgpt.com/docs/config-file/config-reference)补充 |
| Claude Agent SDK Python `6f068949ab673273715b082e844f57fa75d98887`，A类适配器源码＋B类运行语义 | [`ClaudeAgentOptions`](https://github.com/anthropics/claude-agent-sdk-python/blob/6f068949ab673273715b082e844f57fa75d98887/src/claude_agent_sdk/types.py)分别声明可选 `max_turns` 和 `max_budget_usd`；[`SubprocessCLITransport`](https://github.com/anthropics/claude-agent-sdk-python/blob/6f068949ab673273715b082e844f57fa75d98887/src/claude_agent_sdk/_internal/transport/subprocess_cli.py)组装对应CLI参数。原生运行内部未在本次源码中公开；[官方loop说明](https://code.claude.com/docs/en/agent-sdk/agent-loop#turns-and-budget)说明默认均不设置上限、响应后检查估算费用并覆盖子级消费，可能超过设定值；自动压缩另按窗口压力发生 | 费用、工具回合和窗口分别管理。默认未设上限不是本工程无限授权的依据；[成本说明](https://code.claude.com/docs/en/agent-sdk/cost-tracking)区分客户端估算与实际账单，且query／resume／clear的预算scope与本工程同run恢复不重置不同，不能整套照搬 |
| OpenHands SDK `6530325e9dd0ea1b6b4f1994d7dab52764cfc3f1`，A类复用源码 | [`LocalConversation`](https://github.com/OpenHands/software-agent-sdk/blob/6530325e9dd0ea1b6b4f1994d7dab52764cfc3f1/openhands-sdk/openhands/sdk/conversation/impl/local_conversation.py)分别接受 `max_iteration_per_run` 与可空 `max_budget_per_run`；`_budget_exceeded_detail`读取所有注册LLM的combined metrics，包含agent和condenser。循环在相应边界调用检查，写入具名limit error后停止；已完成时保留FINISHED | 压缩调用应计入任务消费，不能因为主决策回合数未增加而漏账。成本检查是响应／步骤边界的限制，不等于没有在途超额。复用原已核源码，经本轮再次读取与SHA校验，不声称其为所有部署最新版本；另采集的旧0.59实现只作辅助，不替代这条SDK调用链 |
| Anthropic Messages API task budgets，B类官方契约 | [任务预算说明](https://platform.claude.com/docs/en/build-with-claude/task-budgets)区分跨agentic loop的工作量提示与单请求 `max_tokens`。其倒计时对新增生成与tool result计数，不重复扣除每次重传的历史；提示不是硬费用上限。服务端压缩不重置已消耗预算，客户端改写历史须按该协议携带剩余值；建议测代表性任务的工作量分布，从p99起调 | 不能将其数值和每次 `usage.input+output` 的累计相等同。该协议只适用文档列出的模型／接口，不证明MiMo、Claude Code或本工程支持；其p99建议针对该工作量口径，不是统一的累计token推荐值 |

本次比较支持把活动窗口、累计消费、任务时间和模型工作量提示分别解释，没有得到“1M窗口应固定对应200万累计额度”或“累计额度除以窗口就是可压缩次数”的依据。新增工作量计数器或费用门禁是否必要，仍需本工程实际轨迹和Provider计费依据；不能删除真实用量、扣掉cached tokens或在压缩后清零来伪装成新的预算口径。具体候选与尚缺证据回到[研究Spec预算节](../optimization/to_verify/knowledge-decision-delivery.md#长任务预算与诊断范围)，本参考页不决定本例的新额度。

### 3.2 单请求超时、重试与任务截止

2026-10-21 为研究初步E1的单次480秒失败复核两个独立A类实现。[四份固定源码与摘要](../../.tmp/research-initial-closure-20261021/timeout-reference-1/manifest.json)只读保存，未运行第三方代码。

| 实现 | 实际调用边界 | 对本工程的取舍 |
| --- | --- | --- |
| [OpenHands LLM](https://github.com/OpenHands/software-agent-sdk/blob/6530325e9dd0ea1b6b4f1994d7dab52764cfc3f1/openhands-sdk/openhands/sdk/llm/llm.py#L1935)，同提交 [RetryMixin](https://github.com/OpenHands/software-agent-sdk/blob/6530325e9dd0ea1b6b4f1994d7dab52764cfc3f1/openhands-sdk/openhands/sdk/llm/utils/retry_mixin.py#L77) | 异步completion把单次硬截止放在可重试attempt内，流式空闲等待另计；RetryMixin按异常分类、次数和指数退避限制尝试 | 单次生成、传输空闲及整任务额度应分开解释。其默认值和重试不证明MiMo能在同样时间完成，也不覆盖本工程未知费用停止规则，不能直接照搬 |
| [Gemini client](https://github.com/google-gemini/gemini-cli/blob/ed96faedfd5571f055c44f2c9509d62321d1138d/packages/core/src/core/client.ts#L1125)及[retryWithBackoff](https://github.com/google-gemini/gemini-cli/blob/ed96faedfd5571f055c44f2c9509d62321d1138d/packages/core/src/utils/retry.ts#L258) | 生成请求接收原abortSignal，重试受配置的maxAttempts和错误分类约束，AbortError直接抛出；该client调用没有把signal作为retry选项传入，不能据工具函数能力宣称所有退避等待均即时取消 | 保留原取消、尝试身份和实际消费，不能把模型请求重试等同于业务工具可重试，也不因另一个框架会重试就清除未知计费 |

同日复核[MiMo官方接入FAQ](https://mimo.mi.com/docs/en-US/quick-start/faq/api-integration)，按B类契约解释：响应速度受请求复杂度、服务负载和地域影响，长响应建议使用流式及合理客户端超时；该页没有给出480秒服务端上限，也不证明流式可以解除客户端整体截止。

同日核对可调参数，仍按B类官方契约解释：[Chat Completions](https://mimo.mi.com/docs/en-US/api/chat/openai-api)公开的thinking.type只有enabled／disabled；[Responses兼容说明](https://mimo.mi.com/docs/en-US/api/chat/responses)明确none关闭思考，其余effort值当前行为相同，尚不区分强度。因此不能把兼容SDK的low／medium／high字段当作MiMo已支持的强度调节。max_completion_tokens同时限制推理与最终输出，降低它可能截断交付，不能代替单独推理预算；stream只按生成进度传输。公开参数未提供tokens/秒控制，thinking开启时temperature／top_p还会被服务端固定。[Token Plan说明](https://mimo.mi.com/docs/en-US/quick-start/faq/token-plan/desktop-guide)明确当前各档均不支持mimo-v2.6-pro-ultraspeed；按量API的独立模型选项不能当作当前Token Plan的速率开关。

本地真实请求已通过当前容量策略，最后失败没有完整响应或推理，仍无法区分合法慢生成与服务停滞。[本地归因审计](../../.tmp/request-deadline-audit-20261021/diagnosis.md)确认当前观察器只在完整body读取后记录send返回，不能用其response_received=false推断无首字节。下一步围绕同一实际失败body核对响应头、正文进展及本地关闭，再隔离验证单次时限。流式改造和自动重试都需要本服务的协议、取消与完整usage证据，当前不据外部实现准入；具体停止与恢复条件由[研究Spec](../optimization/to_verify/knowledge-decision-delivery.md#长任务预算与诊断范围)拥有。

## 4. 可恢复状态的最小集合

1. 已接受的动作身份与不可变参数摘要。
2. 已产生的执行事实、外部资源 ID 和幂等键。
3. 未决动作、等待原因、批准或拒绝事实。
4. 仍有效的 Goal、约束、关键反事实与下一恢复点。
5. Context 压缩或卸载后的来源坐标，而不是无法核验的孤立摘要。

## 5. 机制比较时必须追问

长任务推进先核对：

- 新的一轮是否仍消费当前用户目标和未完成要求，而不是重置任务或自行降低目标。
- 本轮是否形成可验收的增量结果，还是重复读取、改写和核验同一问题。
- 跨轮或跨上下文后，是否能定位并复用有效成果，避免丢失条件、依据和未完成事项。
- 新证据或反馈是否改变取证与修订策略，既往正确内容是否保留。
- 完成依据是否覆盖原用户结果；局部检查通过是否被误用为整体结束条件。

运行恢复再核对：

- 恢复从日志重建，还是从多个可变快照猜测当前状态。
- crash 发生在“副作用已发生、Receipt 未保存”之间时如何判定和补偿。
- resume 会重跑模型决策、工具动作还是只继续未完成步骤。
- compaction 是否保持工具调用与结果配对、错误、批准和未决义务。
- 任务是否真的要求响应后运行、跨进程或跨授权恢复；现有交互及领域生命周期能否满足同一交付契约。

具体机制须按已定位的本地问题选择。重复研究或修订无效先审查模型决策与实际输入；中断丢失进度或重复副作用再审查对应恢复责任。新增机制的依据由 EVD 拥有，durable execution 的正式约束见[智能体决策与受治理执行](../devSpec/agentic-execution.md)。

## 6. 长任务失败模式与评价边界

2026-10-18 实际检索并读取以下一手资料。工程报告用于提出机制候选，原始研究用于界定测量含义；它们都不证明 personalAgent 已复现对应失败。检索范围与适用限制见[本次来源记录](../../.tmp/long-task-capability-review-20261018/external-review.json)。开源压缩装配另见[源码比较](context-engineering.md#5-压缩的实际装配消费与恢复)。

| 一手来源 | 支持关注的问题 | 不能据此推出的结论 |
| --- | --- | --- |
| [Anthropic 长任务 Harness 实验](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents)，2025-11-26 工程报告 | 跨窗口丢失工作背景、一次做太多留下半成品、局部进展后过早结束，以及缺少用户路径验证；压缩还需与增量成果及交接共同使用 | 全栈开发实验不证明研究场景相同收益，不要求复制 initializer、Git 或多 Agent 拓扑 |
| [Anthropic Context 工程](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents)，2025-09-29 工程报告 | 整体输入随动作增长，需组合按需读取、工具结果清理、压缩和外部工作记录；压缩存在遗漏关键细节的取舍 | 没有给所有任务统一的压缩阈值，也不证明扩大窗口能消除信息利用问题 |
| [METR time-horizon 方法及 FAQ](https://metr.org/time-horizons/) | 连续复杂任务应消费前史并逐次解决依赖问题，不能用大量独立小题或大海捞针冒充；指标按人类专家耗时表示任务难度 | 人类任务时间不是 Agent 自主运行时间，不是 Harness 独立贡献；软件／ML／安全为主的任务分布不能外推本项目总体能力 |
| [原始 τ-bench](https://arxiv.org/html/2406.12045v1)，§3、§5.2、§6 | 复合要求遗漏、工具与政策执行不一致；最终数据库奖励是必要而非充分条件，可能漏掉未经确认执行。`pass^k` 衡量多次全部成功 | 模拟零售／航空及历史模型结果不代表本项目失败率；不能把单次 E2E 或工具步骤通过率写成稳定性 |
| [Lost in the Middle](https://aclanthology.org/2024.tacl-1.9.pdf)，TACL 2024，§2、§3 | 在所测模型中，输入容得下不等于模型能有效使用，相关信息位置影响静态问答与检索结果 | 它不是 compaction 实验，不证明当前模型仍有相同退化，也不直接准入历史摘要或专门埋针产品测试 |

本地应分别核对容量、语义保留、目标覆盖、增量成果、执行失败、恢复、权限、预算及完成结果。后台运行、多 Agent 和跨天调度是否需要，仍由实际业务生命周期决定。研究场景的逐项审计和优先级由[唯一 Spec](../optimization/to_verify/knowledge-decision-delivery.md#31-长任务问题逐项对照)拥有，参考页不另建产品待办。

## 7. 机器产物与模型的读取单位

2026-10-21 为复审研究场景的重复读取阻塞，核对 Gemini CLI 固定提交 `ed96faedfd5571f055c44f2c9509d62321d1138d` 的实际 [read-file 装配](https://github.com/google-gemini/gemini-cli/blob/ed96faedfd5571f055c44f2c9509d62321d1138d/packages/core/src/tools/read-file.ts)、[文件物化](https://github.com/google-gemini/gemini-cli/blob/ed96faedfd5571f055c44f2c9509d62321d1138d/packages/core/src/utils/fileUtils.ts)及 [ripgrep 解析](https://github.com/google-gemini/gemini-cli/blob/ed96faedfd5571f055c44f2c9509d62321d1138d/packages/core/src/tools/ripGrep.ts)。读取以物理行切片并截断超长行，搜索保留 rg 的实际行号；这不能自动把单行 JSON 中的对象当成独立记录。源码及 SHA 见[复核归档](../../.tmp/research-capability-20261020/t5/artifact-record-reference-1/manifest.json)。

[Anthropic 工具实践](https://www.anthropic.com/research/writing-tools-for-agents)，2025-09-11 工程报告，建议从实际轨迹定位低效调用，再调整工具返回的信息、分页和描述。它不规定本工程必须添加分析执行器或使用某种 JSON 格式，也不能替代真实失败与效果验收。

本地只据已发生的按行读取困难评估逐查询指标的标准 JSON 换行，不修改公共搜索的计数含义，不预选错例或放宽模型执行权限；采用、对照和完整交付的条件由[研究 Spec](../optimization/to_verify/knowledge-decision-delivery.md#逐查询产物的可定位格式候选)拥有。格式适配只能直接证明可定位记录；延迟、聚合能力和用户结果须分别验收。

## 8. 重复动作检测只提供停止边界

2026-10-21 为复审三轮相同实验，核对 OpenHands SDK 固定提交 `6530325e9dd0ea1b6b4f1994d7dab52764cfc3f1` 的 [StuckDetector](https://github.com/OpenHands/software-agent-sdk/blob/6530325e9dd0ea1b6b4f1994d7dab52764cfc3f1/openhands-sdk/openhands/sdk/conversation/stuck_detector.py) 和 [LocalConversation](https://github.com/OpenHands/software-agent-sdk/blob/6530325e9dd0ea1b6b4f1994d7dab52764cfc3f1/openhands-sdk/openhands/sdk/conversation/impl/local_conversation.py)，A级源码及 SHA 见[归档](../../.tmp/research-capability-20261020/t5/repeated-experiment-reference-1/manifest.json)。启用时由会话装配 detector，同步／异步循环消费 `_check_stuck_or_nudge`：重复错误先给一次反馈，满足检测则写 STUCK 并停止；动作／观察相等和交替模式各有判据。

它不能替模型分析错例或保证完成。当前比较还会比较动作 thought 和观察正文；本地每次实验的引用、耗时及中间读取不同，不能仅因配置相同就声称会命中该 detector。只读源码、未运行该项目；本工程暂不移植新检测状态、提示或阈值。先核实际输入和重复原因，确定性硬停止与局部拒绝边界继续保留；本地采用准入由唯一研究 Spec 拥有，当前没有新增机制或付费实验准入。
