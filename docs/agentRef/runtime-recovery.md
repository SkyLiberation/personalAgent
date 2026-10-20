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

这些实现区分模型提示与确定性硬停止，但不证明本工程某次失败由预算感知导致。本工程预算提示的准入由 [EVD](../devSpec/change-evidence.md)拥有，实际输入与事实投影由 [CTX](../devSpec/context-memory-retrieval.md)拥有；本页不另设实现门禁。

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
