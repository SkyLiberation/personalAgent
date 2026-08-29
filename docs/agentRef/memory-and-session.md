# 记忆与会话能力参考

**优秀的记忆机制首先区分运行恢复、短期会话、长期事实和程序性知识，再分别定义写入、召回、共享与失效。** “把历史保存下来”只解决存储，不能自动成为可信 Memory。

本页只拥有外部记忆与会话机制比较；资料等级、固定提交与采用边界见[参考索引](README.md)。

## 1. 不同状态的责任

| 状态类型 | 典型生命周期 | 代表实现与突出能力 |
| --- | --- | --- |
| 运行中会话 | 同一 thread 或 run | [LangGraph Persistence](https://docs.langchain.com/oss/python/langgraph/persistence)用 checkpointer 保存 thread 的图状态，支持中断、恢复、状态检查和 time travel |
| 跨会话长期记忆 | 跨 thread、可维护 | [Letta MemFS](https://github.com/letta-ai/letta-docs-md/blob/0bfd40b73de18fca8fd9c370263d2e46ac5379df/concepts/memfs/index.md)让每个智能体拥有 Git 仓库记忆，编辑可版本化；`system/` 常驻，其他文件按需读取 |
| 精炼用户事实 | 跨 session、容量受控 | Hermes 的 [Persistent Memory](https://github.com/NousResearch/hermes-agent/blob/9dfbde19db7b108f9e961eec367ca5b54c8ad7d6/website/docs/user-guide/features/overview.md)把偏好、项目和环境写入有界的 `MEMORY.md` / `USER.md` |
| 子级局部记忆 | 单次或跨调用可选 | [Claude Code Subagents](https://code.claude.com/docs/en/subagents)可配置持久记忆；[LangGraph Subgraphs](https://docs.langchain.com/oss/python/langgraph/use-subgraphs)明确区分 per-invocation、per-thread 与 stateless |
| durable 运行日志 | 跨进程恢复 | [DeepSeek Harness Architecture](https://github.com/deepseek-ai/deepseek-harness/blob/b150a551b8d465e31e418e1b2eaf5e79bbb7d28e/docs/architecture.md)以 session log 作为模型可见 Context 的可重建来源 |

## 2. 突出的能力点

- Letta 把记忆作为智能体可操作的文件系统，而不是只暴露向量检索；版本历史、分支工作树和按需文件使纠错、审计与维护成为一等能力。
- LangGraph 将同 thread 的 checkpoint 与跨 thread 的 store 分开，避免把恢复状态、会话消息和长期用户事实混成一个对象。
- DeepSeek Harness 强调 durable log 与派生 Context 的关系：重启后从同一事件事实重建，而非另存一份不可核对的 Prompt 快照。
- Hermes 把 Memory 与 Skill 分开：前者保存“关于用户或环境的事实”，后者保存“如何完成任务的程序”。
- Claude Code 和 LangGraph 都允许子级选择是否跨调用保留状态，说明多智能体系统不应默认共享全部主会话记忆。

## 3. 机制比较时必须追问

1. 写入是用户授权、模型 Proposal、确定性事件，还是执行系统自动产物。
2. 同一事实的 canonical owner 在哪里；索引、摘要和 Prompt 片段能否确定性重建。
3. 记忆是否记录来源、scope、时间、修订和删除语义；错误事实如何纠正并防止再次召回。
4. 多智能体共享的是事实、文件、摘要还是同一可写存储；并发冲突由谁解决。
5. checkpoint 恢复的是运行进度还是业务完成，是否可能重复外部副作用。

这些参考不改变 personalAgent 的 Memory owner。具体边界仍由[上下文、记忆与检索规范](../devSpec/context-memory-retrieval.md)与当前架构文档定义。
