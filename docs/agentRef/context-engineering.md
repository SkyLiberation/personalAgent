# Context Engineering 能力参考

**成熟实现通常把 Context 构造成分层、可选择、可压缩的运行输入，而不是把仓库、历史和全部工具一次性塞入 Prompt。** 可复用的核心是“发现最小规则 → 按任务加载程序性知识 → 隔离子任务上下文 → 在压力下保留可恢复事实”。

本页只拥有外部 Context 机制比较；资料等级、固定提交与采用边界见[参考索引](README.md)。

## 1. 四层能力

| 层次 | 需要解决的问题 | 代表实现 |
| --- | --- | --- |
| 指令发现 | 哪些稳定规则对当前位置生效 | Codex 按全局、仓库根和更近目录组装 [`AGENTS.md`](https://developers.openai.com/codex/guides/agents-md)；Claude Code 从 `CLAUDE.md` 与项目规则建立常驻上下文 |
| 按需披露 | 哪些流程知识只在当前任务需要时展开 | [Codex Skills](https://developers.openai.com/codex/skills)先暴露名称与描述，命中后加载完整 `SKILL.md`；[OpenHands Skills](https://docs.openhands.dev/overview/skills)支持关键词和路径触发；Hermes 的 [Skills System](https://github.com/NousResearch/hermes-agent/blob/9dfbde19db7b108f9e961eec367ca5b54c8ad7d6/website/docs/user-guide/features/overview.md)采用相同的渐进式披露方向 |
| 任务投影 | 如何避免子任务污染主会话 | [Claude Code Subagents](https://code.claude.com/docs/en/subagents)为子级提供隔离 Context，只把结果摘要带回；Codex 子级同样面向独立任务并由父级汇总 |
| 压力治理 | Context 过长时保留什么 | [DeepSeek Harness Compaction](https://github.com/deepseek-ai/deepseek-harness/blob/b150a551b8d465e31e418e1b2eaf5e79bbb7d28e/docs/subsystems/compaction.md)把压缩作为可替换 seam，并将压缩事件写入 durable log；[Letta MemFS](https://github.com/letta-ai/letta-docs-md/blob/0bfd40b73de18fca8fd9c370263d2e46ac5379df/concepts/memfs/index.md)只把 `system/` 文件常驻 Prompt，其余文件按需读取 |

## 2. 突出的机制差异

- GPT-5.6 的 [Model guidance](https://developers.openai.com/api/docs/guides/latest-model)强调精简重复指令、只暴露任务相关工具，并在代表性任务上逐项消融；这是 Prompt 和工具面的预算纪律，不是自动的权限过滤。
- Codex 把目录指令与 Skill 分开：前者随位置形成稳定约束链，后者由任务语义触发。这种区分避免把所有流程手册常驻到每轮 Context。
- Claude Code 把 Skill、Subagent 和 Hook 分成不同 Context 成本：Skill 扩展当前会话，Subagent 隔离探索，Hook 可在模型 Context 外确定性执行。
- OpenHands 允许仓库级 `AGENTS.md` 和按路径激活 Skill，把“项目规则”与“任务程序”分开选择。
- DeepSeek Harness 的 session log 是可重建 Context 的 durable source；压缩是日志中的事件，而不是静默改写历史。
- Letta 把常驻记忆与按需文件物理分区，突出“哪些内容必须每轮可见”是独立设计决策。

## 3. 机制比较时必须追问

1. 可见性是否在检索前确定，还是依赖模型在 Prompt 中自行过滤。
2. 指令、事实、工具描述、历史和临时观察分别由谁选择、失效和删除。
3. 压缩后是否仍能恢复工具调用配对、关键 ID、未决义务和失败事实。
4. 子级返回的是摘要、结构化结果还是完整历史；父级是否仍拥有最终回答。
5. 新 Context 层是否减少了已测量的遗漏或成本，而不是只增加一个缓存或索引。

这些问题只能用于形成候选。personalAgent 的 Context 权威边界仍由[上下文、记忆与检索规范](../devSpec/context-memory-retrieval.md)和当前代码定义。
