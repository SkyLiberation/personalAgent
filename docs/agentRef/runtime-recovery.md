# 运行恢复与长任务能力参考

**可靠恢复要求先固定可重建的运行事实，再决定 checkpoint、resume、compaction 或外部 durable orchestrator。** 保存一段对话或代码快照不等于安全重放；外部副作用必须有独立幂等和完成事实。

本页只拥有外部恢复机制比较；资料等级、固定提交与采用边界见[参考索引](README.md)。

## 1. 代表机制

| 实现 | 恢复单位 | 突出能力与边界 |
| --- | --- | --- |
| DeepSeek Harness | session event log | [Architecture](https://github.com/deepseek-ai/deepseek-harness/blob/b150a551b8d465e31e418e1b2eaf5e79bbb7d28e/docs/architecture.md)把 durable log 作为 Context 可重建来源；[Compaction](https://github.com/deepseek-ai/deepseek-harness/blob/b150a551b8d465e31e418e1b2eaf5e79bbb7d28e/docs/subsystems/compaction.md)记录压缩事件并处理压力与错误恢复 |
| LangGraph | thread checkpoint | [Persistence](https://docs.langchain.com/oss/python/langgraph/persistence)保存每一步图状态，支撑 interrupt、fault tolerance、状态历史和 time travel；长期 store 与 checkpoint 分离 |
| Gemini CLI | 文件状态、对话和待执行工具 | [Checkpointing](https://github.com/google-gemini/gemini-cli/blob/3c311beac2e78336816dd4a123db39743f9fbf85/docs/cli/checkpointing.md)在文件修改前写 shadow Git 快照，同时保存对话与工具调用；`/restore`恢复并重新提出原动作 |
| Codex | Git 工作树与任务线程 | [Git worktrees](https://learn.chatgpt.com/docs/environments/git-worktrees)隔离并行状态，Handoff 在本地 checkout 与工作树间移动任务 | 工作树保存代码身份，不替代外部系统副作用或产品 Goal 的 durable state |
| Hermes Agent | 工作目录 checkpoint | [Features overview](https://github.com/NousResearch/hermes-agent/blob/9dfbde19db7b108f9e961eec367ca5b54c8ad7d6/website/docs/user-guide/features/overview.md)在文件修改前快照工作目录并支持 `/rollback` | 文件回滚只覆盖工作空间；网络调用、消息和其他外部动作仍需各自恢复协议 |
| OpenHands | 沙箱与 Action/Observation 会话 | [Runtime architecture](https://docs.openhands.dev/openhands/usage/architecture/runtime)在可隔离环境中执行 Action 并返回 Observation；不同沙箱 Provider 支持本地或远端运行 | 环境隔离提高可重复性，但不自动提供业务级 exactly-once 或 Completion |

## 2. 预算可见与硬停止必须分层

**优秀实现没有把“每回合告诉模型剩余预算”当作通用答案。** 确定性运行系统始终拥有硬上限；模型可见提示只是帮助收敛的软约束，不能替代停止事实。

- OpenAI Agents SDK 在 [Runner](https://github.com/openai/openai-agents-python/blob/89c02c828ee8510fe9a84ee6675608193aa13b02/docs/running_agents.md#the-agent-loop) 中由确定性 `max_turns` 终止循环，超限时抛出 `MaxTurnsExceeded`。SDK 允许应用使用 `call_model_input_filter` 注入自定义系统信息，但不会默认把剩余轮次写给模型。
- Gemini CLI 在 [client.ts](https://github.com/google-gemini/gemini-cli/blob/55b495d6db1794bf5b7f37a9bc03ebcab5103673/packages/core/src/core/client.ts) 中超出 `maxSessionTurns` 后先产生 `MaxSessionTurns` 事件并停止模型调用；[Session management](https://github.com/google-gemini/gemini-cli/blob/55b495d6db1794bf5b7f37a9bc03ebcab5103673/docs/cli/session-management.md#session-limits) 把交互模式定义为停止发送，非交互模式定义为错误退出。该路径也不依赖模型自觉停止。
- Hermes Agent 的[当前配置文档](https://github.com/NousResearch/hermes-agent/blob/37fd6eea9753cb2b6de08b7ab83a9e385a97b144/website/docs/user-guide/configuration.md#iteration-budget) 记录：早期在 70% 和 90% 反复注入轮次压力会让模型过早放弃复杂任务，因而已被移除。显式设置轮次上限后，预算耗尽时只注入一次收尾指令并允许一次宽限调用；可选墙钟预算只在 80% 注入一次收尾提示。

因此，本工程只能在已复现“模型未感知剩余预算”且单变量证据证明收尾改善后，才新增或调整预算提示。提示必须有界、只告知已发生的预算事实，并与 Runtime-owned 的硬停止、工具可见性和 typed 终态分离。

## 3. 可恢复状态的最小集合

1. 已接受的动作身份与不可变参数摘要。
2. 已产生的执行事实、外部资源 ID 和幂等键。
3. 未决动作、等待原因、批准或拒绝事实。
4. 仍有效的 Goal、约束、关键反事实与下一恢复点。
5. Context 压缩或卸载后的来源坐标，而不是无法核验的孤立摘要。

## 4. 机制比较时必须追问

- 恢复从日志重建，还是从多个可变快照猜测当前状态。
- crash 发生在“副作用已发生、Receipt 未保存”之间时如何判定和补偿。
- resume 会重跑模型决策、工具动作还是只继续未完成步骤。
- compaction 是否保持工具调用与结果配对、错误、批准和未决义务。
- 长任务是否真的跨进程、跨授权或跨恢复边界；若否，普通会话循环是否足够。

只有本工程已经复现中断、丢失进度或重复副作用，才应据此提出恢复机制。durable execution 的正式约束见[智能体决策与受治理执行](../devSpec/agentic-execution.md)。
