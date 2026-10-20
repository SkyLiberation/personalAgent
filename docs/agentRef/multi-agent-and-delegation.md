# 多智能体与委托能力参考

**多智能体的主要价值是隔离专业 Context、并行独立工作或切换责任主体，而不是增加角色数量。** 一个可审计的委托必须明确任务边界、工具权限、工作空间、返回契约、取消恢复语义和最终结果 owner。

本页只拥有外部多智能体机制比较；资料等级、固定提交与采用边界见[参考索引](README.md)。

## 1. 代表机制

| 实现 | 突出能力 | 责任边界 |
| --- | --- | --- |
| Codex | [Subagents](https://learn.chatgpt.com/docs/agent-configuration/subagents)提供专门角色；[Git worktrees](https://learn.chatgpt.com/docs/environments/git-worktrees)隔离并行代码状态 | 父级汇总仍需检查覆盖、冲突与最终答案；可用机制不等于必须委托 |
| Claude Code | [Subagents](https://code.claude.com/docs/en/subagents)提供独立 Context、自定义 Prompt、工具、权限、Skill、Hook、前后台运行和 resume | 子级只返回摘要或结果；是否继承项目规则、持久记忆和权限需要显式配置 |
| DeepSeek Harness | [Architecture](https://github.com/deepseek-ai/deepseek-harness/blob/b150a551b8d465e31e418e1b2eaf5e79bbb7d28e/docs/architecture.md)允许从进程内子级到委托给其他产品的 Provider；实验性 teams 用 durable roster、task board 和 mailbox 协调可继续子级 | Provider seam 统一调用面，但不同子级的完成、取消、资源和恢复语义不能仅靠接口同名推定等价 |
| Gemini CLI | [Plan Mode](https://github.com/google-gemini/gemini-cli/blob/3c311beac2e78336816dd4a123db39743f9fbf85/docs/cli/plan-mode.md)允许只读 codebase investigator 与帮助子级协助研究 | 研究子级不能越过计划态工具策略；并行探索不等于执行批准 |
| Hermes Agent | [Features overview](https://github.com/NousResearch/hermes-agent/blob/9dfbde19db7b108f9e961eec367ca5b54c8ad7d6/website/docs/user-guide/features/overview.md)中的 `delegate_task`提供隔离 Context、受限工具集、独立终端和并发子级 | 默认并发度只是运行参数；最终交付仍需要父级消费子级结果 |
| LangGraph | [Subgraphs](https://docs.langchain.com/oss/python/langgraph/use-subgraphs)允许 per-invocation、per-thread 或 stateless 子图，并让父图 checkpointer 支撑中断与恢复 | 每次独立子任务通常使用 per-invocation；只有需要跨调用记忆时才扩大状态生命周期 |
| Letta | [MemFS](https://github.com/letta-ai/letta-docs-md/blob/0bfd40b73de18fca8fd9c370263d2e46ac5379df/concepts/memfs/index.md)支持独立智能体记忆和共享记忆仓库 | 共享存储不自动解决事实 owner、写冲突或不同主体的可见性 |

### 1.1 子能力调用与内部循环的源码核对

2026-10-17 按下列固定提交检查调用链。四项均为 A 级源码；提交身份不代表发布资格，也未在本地运行这些项目。此次下载 17 个源码及设计文件并保存[来源、提交与文件校验和](../../.tmp/research-module-encapsulation-20261017/sources/source-manifest.json)，只对表中实际路径作出判断。

| 实现与提交 | 模型可见入口到内部执行 | 返回与生命周期边界 |
| --- | --- | --- |
| Deep Agents：`fd3e64ab6b605450bed5a2c22ef2ec84cd40542e` | [`SubAgentMiddleware` 的 `task`](https://github.com/langchain-ai/deepagents/blob/fd3e64ab6b605450bed5a2c22ef2ec84cd40542e/libs/deepagents/deepagents/middleware/subagents.py#L647)选择已构造的子 runnable，再 `invoke`／`ainvoke` 完整子图；声明式子级通过 `create_sub_agent` 调用 `create_agent`，已有编译图也能接入 | `_validate_and_prepare_state` 区分隔离与 fork 输入；`_return_command_with_state_update` 选择结构化结果或最后非空回答，回传 `ToolMessage` 及经过筛选的状态。工具不是只执行子级的一个步骤，父级也不接收全部内部消息 |
| OpenHands SDK：`6530325e9dd0ea1b6b4f1994d7dab52764cfc3f1` | [`DelegateExecutor`](https://github.com/OpenHands/software-agent-sdk/blob/6530325e9dd0ea1b6b4f1994d7dab52764cfc3f1/openhands-tools/openhands/tools/delegate/impl.py#L34)处理 `spawn`／`delegate`，构造子 `LocalConversation`，向其发任务并运行至停止；[`LocalConversation._run`](https://github.com/OpenHands/software-agent-sdk/blob/6530325e9dd0ea1b6b4f1994d7dab52764cfc3f1/openhands-sdk/openhands/sdk/conversation/impl/local_conversation.py#L1933)内部循环调用 `agent.step` | 提取子会话最终回答，返回 `DelegateObservation`；子会话具有自己的运行状态与可选持久化。子级累计用量按子级键覆盖汇入父统计，避免重复累加。确认处理存在默认放行逻辑，不能直接作为本工程授权契约 |
| Gemini CLI：`9656cff4aca74ebd158506c94927c70e9f8e46fb` | [`AgentTool`](https://github.com/google-gemini/gemini-cli/blob/9656cff4aca74ebd158506c94927c70e9f8e46fb/packages/core/src/agents/agent-tool.ts#L41)按名称查定义并委托。已审计的非 Session 本地分支为 [`LocalSubagentInvocation`](https://github.com/google-gemini/gemini-cli/blob/9656cff4aca74ebd158506c94927c70e9f8e46fb/packages/core/src/agents/local-invocation.ts#L276) → `LocalAgentExecutor.run` → 内部多轮执行 | [`执行器`](https://github.com/google-gemini/gemini-cli/blob/9656cff4aca74ebd158506c94927c70e9f8e46fb/packages/core/src/agents/local-executor.ts#L365)以 `complete_task` 提交结果，区分目标完成、超时、轮数耗尽和取消；返回结果及停止原因。定义可带独立 Prompt、工具范围和输出 Schema；`codebase_investigator` 文件自标为概念验证，Session／远端分支本次未完整核对 |
| DeepSeek Harness：`1517a4dbca0a2789ff1d41ba439600f8547d23fa` | [`tool-subagent`](https://github.com/deepseek-ai/deepseek-harness/blob/1517a4dbca0a2789ff1d41ba439600f8547d23fa/packages/subagent/tool-subagent/src/index.ts#L276)调用 `subagents.startActivation`；[`SubagentProvider`](https://github.com/deepseek-ai/deepseek-harness/blob/1517a4dbca0a2789ff1d41ba439600f8547d23fa/packages/subagent/subagent/src/types.ts#L313)区分外部 `start` 与进程内 `prepareContinuable`。后者由 [`manager`](https://github.com/deepseek-ai/deepseek-harness/blob/1517a4dbca0a2789ff1d41ba439600f8547d23fa/packages/subagent/subagent/src/manager.ts#L379)负责创建、投递与恢复 | 当前工具先返回激活句柄，不是阻塞到完整结果。Manager 拥有可继续子级的身份、父子关系与释放；Provider 声明是否继承 Context。外部运行有结果 Promise 和幂等 `dispose` 契约，不能把“已启动”当作任务已完成 |

上述路径说明 Tool 可以作为完整子任务的入口，入口后可运行局部循环；不意味着所有能力都应建成子 Agent。确定性的内部协作可直接调用，已有复杂过程也可作为一个子图节点接入。[LangGraph 子图文档](https://docs.langchain.com/oss/python/langgraph/use-subgraphs)明确以输入输出隔离内部实现；[LangChain 子 Agent 文档](https://docs.langchain.com/oss/python/langchain/multi-agent/subagents)展示工具包装完整子 Agent。两份文档属于同一实现体系，不另算独立样本。

同日补核对统筹层：Deep Agents 的 [`create_deep_agent` 装配末端](https://github.com/langchain-ai/deepagents/blob/fd3e64ab6b605450bed5a2c22ef2ec84cd40542e/libs/deepagents/deepagents/graph.py#L995)向 `create_agent` 传入主模型、工具、middleware 和状态等，子能力通过前述 `task` 接入；该文件只证明装配，不单独证明依赖库内部路由。OpenHands 的 [`Agent._step`](https://github.com/OpenHands/software-agent-sdk/blob/6530325e9dd0ea1b6b4f1994d7dab52764cfc3f1/openhands-sdk/openhands/sdk/agent/agent.py#L694)向模型发送当前消息和工具定义，再按响应处理 Tool Calls 或内容；`LocalConversation._run` 沿实际状态循环调用步骤。Gemini CLI 已审计的 [`LocalAgentExecutor`](https://github.com/google-gemini/gemini-cli/blob/9656cff4aca74ebd158506c94927c70e9f8e46fb/packages/core/src/agents/local-executor.ts#L685)把下一轮消息交回模型，工具声明来自 Registry，调用按名称查找实际工具。它是子级本地执行分支，不能据此外推全部父级与 Session 模式。

这些路径分别支持能力装配、模型选择和 Runtime 推进的责任划分；未发现依据要求为每项业务都固定增加 Router、Planner、Executor 三次模型调用。是否需要独立规划或额外协调，仍由具体用户结果和真实失败决定；各项目对 Hook、停止和权限的语义不相同。

共同可借鉴的是模块交接和内部过程封装。子级是否共享文件、继承会话、采用独立持久化、怎样汇总用量，以及同步等待还是异步回传，必须逐项确定；函数名或 Tool Schema 相似不代表这些契约相同。用于 personalAgent 的具体取舍与验收只由[主循环与能力边界 Spec](../optimization/to_verify/conversation-loop-boundaries.md)拥有。

## 2. 三种常见拓扑

- **Manager + specialists**：父级保留用户对话和最终答案，子级完成有界任务；适合汇总与统一治理。
- **Handoff**：选定的专业智能体成为当前响应 owner；适合职责清晰、无需父级再次整合的路由。
- **Shared task board / mailbox**：可继续子级异步协调；只在确有跨时间、恢复和并发需求时值得承担持久状态复杂度。

## 3. 机制比较时必须追问

1. 子任务能否独立验证，还是多个子级共享同一隐式决策而难以合并。
2. 子级继承哪些指令、身份、权限、记忆和工作树；最小披露是否成立。
3. 返回结果是一次性 output、Artifact、消息还是 durable handle；失败和超时如何区分。
4. 父级是否仍需语义整合和 Completion；子级 success 能否错误地关闭父级 Goal。
5. 并行收益是否以同任务 wall-clock、token、冲突率和最终质量实测，而不是以子级数量推断。

没有并行独立性、Context 隔离或责任转移的已测量需求时，单智能体加明确工具通常是更小的生产边界。
