# 多智能体与委托能力参考

**多智能体的主要价值是隔离专业 Context、并行独立工作或切换责任主体，而不是增加角色数量。** 一个可审计的委托必须明确任务边界、工具权限、工作空间、返回契约、取消恢复语义和最终结果 owner。

本页只拥有外部多智能体机制比较；资料等级、固定提交与采用边界见[参考索引](README.md)。

## 1. 代表机制

| 实现 | 突出能力 | 责任边界 |
| --- | --- | --- |
| GPT / Codex | GPT-5.6 [Multi-agent](https://developers.openai.com/api/docs/guides/latest-model)协调可并行子级并综合结果；[Codex Subagents](https://learn.chatgpt.com/docs/agent-configuration/subagents)支持专门角色；[Git worktrees](https://learn.chatgpt.com/docs/environments/git-worktrees)隔离并行代码状态 | 适合能拆成独立工作流的任务；父级综合仍需检查覆盖、冲突与最终答案 |
| Claude Code | [Subagents](https://code.claude.com/docs/en/subagents)提供独立 Context、自定义 Prompt、工具、权限、Skill、Hook、前后台运行和 resume | 子级只返回摘要或结果；是否继承项目规则、持久记忆和权限需要显式配置 |
| DeepSeek Harness | [Architecture](https://github.com/deepseek-ai/deepseek-harness/blob/b150a551b8d465e31e418e1b2eaf5e79bbb7d28e/docs/architecture.md)允许从进程内子级到委托给其他产品的 Provider；实验性 teams 用 durable roster、task board 和 mailbox 协调可继续子级 | Provider seam 统一调用面，但不同子级的完成、取消、资源和恢复语义不能仅靠接口同名推定等价 |
| Gemini CLI | [Plan Mode](https://github.com/google-gemini/gemini-cli/blob/3c311beac2e78336816dd4a123db39743f9fbf85/docs/cli/plan-mode.md)允许只读 codebase investigator 与帮助子级协助研究 | 研究子级不能越过计划态工具策略；并行探索不等于执行批准 |
| Hermes Agent | [Features overview](https://github.com/NousResearch/hermes-agent/blob/9dfbde19db7b108f9e961eec367ca5b54c8ad7d6/website/docs/user-guide/features/overview.md)中的 `delegate_task`提供隔离 Context、受限工具集、独立终端和并发子级 | 默认并发度只是运行参数；最终交付仍需要父级消费子级结果 |
| LangGraph | [Subgraphs](https://docs.langchain.com/oss/python/langgraph/use-subgraphs)允许 per-invocation、per-thread 或 stateless 子图，并让父图 checkpointer 支撑中断与恢复 | 每次独立子任务通常使用 per-invocation；只有需要跨调用记忆时才扩大状态生命周期 |
| Letta | [MemFS](https://github.com/letta-ai/letta-docs-md/blob/0bfd40b73de18fca8fd9c370263d2e46ac5379df/concepts/memfs/index.md)支持独立智能体记忆和共享记忆仓库 | 共享存储不自动解决事实 owner、写冲突或不同主体的可见性 |

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
