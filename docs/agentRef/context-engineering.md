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

- OpenAI 的 [Model guidance](https://developers.openai.com/api/docs/guides/latest-model#favor-leaner-prompts)建议减少重复指令与工具描述，在自身代表性任务上验证；这是输入设计建议，不是自动权限过滤，也不绑定固定模型名称。
- Anthropic 的 [Prompting best practices](https://docs.anthropic.com/en/docs/build-with-claude/prompt-engineering/prompt-templates-and-variables)要求指令清楚直接，在顺序重要时使用编号步骤，并用一致标签分隔指令、Context、输入和示例；它把代表性边界示例视为稳定格式和分类的重要手段。
- Google Gemini 的 [Prompt design strategies](https://ai.google.dev/gemini-api/docs/prompting-strategies)同样要求明确目标、约束和输出格式，并建议用一致分隔结构与多样的少样本示例缩小含混边界；结构化输出仍应由 API schema 约束，而不是只靠 Prompt 描述 JSON。
- Gemini CLI 固定提交中的 [`prompt-suggest.toml`](https://github.com/google-gemini/gemini-cli/blob/3c311beac2e78336816dd4a123db39743f9fbf85/.gemini/commands/prompt-suggest.toml)要求从已观察行为定位指令歧义，并把修复提升为可泛化边界；它明确反对为单一场景缩窄 Prompt 或在建议中写死具体样本。该源码说明失败样本用于发现行为类别，不应成为生产 Prompt 的固定答案。
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

## 4. 模型可见反馈与机器协议的表达分工

**以下两个独立实现为模型专门组织可读反馈，同时保留供程序解析的工具调用结构。** 这支持按消费者设计表达方式，不支持“所有输入都应转成散文”或“JSON 导致模型判断错误”的结论。本节于 2026-09-16 复核固定源码，均为 A 级实现证据；它们没有实现本工程相同的文档缺项门禁。

| 实现与固定坐标 | 模型可见反馈与生产消费链 | 机器协议与边界 |
| --- | --- | --- |
| Gemini CLI，`3c311beac2e78336816dd4a123db39743f9fbf85` | [`ReadFileToolInvocation.execute`](https://github.com/google-gemini/gemini-cli/blob/3c311beac2e78336816dd4a123db39743f9fbf85/packages/core/src/tools/read-file.ts#L158-L171)在截断时向 `llmContent` 写入文字，说明截断、显示行范围、总行数和续读参数；[`ToolExecutor.createSuccessResult`](https://github.com/google-gemini/gemini-cli/blob/3c311beac2e78336816dd4a123db39743f9fbf85/packages/core/src/scheduler/tool-executor.ts#L371-L387)将其转换为模型工具响应。界面展示另有字段，不能把界面提示当成模型已见内容 | 同一读取工具通过 `parametersJsonSchema` 声明模型调用参数，并由代码检查路径和参数。文件系统与执行代码拥有读取事实；可读说明没有替代参数协议、路径权限和错误分类。它说明单次窗口，不证明累计全文已读 |
| OpenHands，发布版本 `0.59.0` | [`CmdOutputObservation.to_agent_observation`](https://github.com/OpenHands/OpenHands/blob/0.59.0/openhands/events/observation/commands.py#L196-L204)将目录、解释器和退出码组织为带含义的文本；[`ConversationMemory._process_observation`](https://github.com/OpenHands/OpenHands/blob/0.59.0/openhands/memory/conversation_memory.py#L387-L403)消费该文本，错误与用户拒绝也分别附说明。生产 [`CodeActAgent._get_messages`](https://github.com/OpenHands/OpenHands/blob/0.59.0/openhands/agenthub/codeact_agent/codeact_agent.py#L283-L289)调用这个消息构造过程 | [`response_to_actions`](https://github.com/OpenHands/OpenHands/blob/0.59.0/openhands/agenthub/codeact_agent/function_calling.py#L90-L112)解析模型工具参数 JSON，并检查必需参数后构造 Action。Observation 保有执行事实，文本属于模型输入投影；MCP 与文件内容仍可直接保留原内容，并非统一改写成自然语言 |

共同机制是已有 typed 执行事实向本轮模型消息的单向投影，没有必要为此新增第二份持久状态。窗口变化或重新执行后，说明随对应事实重新生成；权限检查仍在执行边界，格式化不扩大授权。执行失败保留失败身份，不能靠措辞变成成功；外部证据也不能因进入文字消息就获得指令权威。这些是本工程采纳时必须保留的边界，不能据上表推断两个项目的全部权限、取消、恢复或持久化语义相同。

本工程反馈表达规则由 [CTX 第 1.1 节](../devSpec/context-memory-retrieval.md#11-模型输入优先表达语义机器消费保持结构化)拥有；具体读取问题与历史依据见[优化记录](../optimization/document-absence.md#104-按来源顺序返回缺项分类)。参考页不维护第二份生产缺口、采用状态或修订成功率。

## 5. 压缩的实际装配、消费与恢复

2026-10-18 核对两个独立开源实现的固定源码，以及 DeepAgents 锁定的 `langchain==1.4.6` 配对切割实现。共取得 27 个源码／依赖锁文件，见[来源及 SHA-256](../../.tmp/context-compaction-review-20261018/sources/source-manifest.json)和[校验记录](../../.tmp/context-compaction-review-20261018/sources/verification.json)。未运行第三方项目、模型或测试。以下是该版本机制，不代表当前所有部署配置。

| 实现 | 实际生产调用链 | 触发、保留与失败边界 |
| --- | --- | --- |
| DeepSeek Harness `b150a551b8d465e31e418e1b2eaf5e79bbb7d28e` | [`standard/agent.cordis.yml`](https://github.com/deepseek-ai/deepseek-harness/blob/b150a551b8d465e31e418e1b2eaf5e79bbb7d28e/apps/cli/config/agent-presets/standard/agent.cordis.yml#L137)装配 basic compactor 及工具结果 pruner；agent loop 派发 pre-step，进入 [`compaction-basic`](https://github.com/deepseek-ai/deepseek-harness/blob/b150a551b8d465e31e418e1b2eaf5e79bbb7d28e/packages/compaction/compaction-basic/src/index.ts#L137)，先裁剪再选择历史区间，生成摘要并替换本轮 surface | 默认按窗口 80% 触发、保留 16% 尾部，token meter 使用实际请求锚点及变化估计。区间切割保持工具调用／结果配对；[`region.ts`](https://github.com/deepseek-ai/deepseek-harness/blob/b150a551b8d465e31e418e1b2eaf5e79bbb7d28e/packages/compaction/compaction-basic/src/region.ts#L98)要求替换后严格缩小，保留原事件及 `sourceEventSeqs`。空摘要、截断及错误拒绝提交；overflow 仅在实际缩减后有界恢复。Session 通过原日志及 surface 替换重放；未核实模型可直接按 seq 调工具召回原文 |
| DeepAgents `fd3e64ab6b605450bed5a2c22ef2ec84cd40542e` | [`create_deep_agent`](https://github.com/langchain-ai/deepagents/blob/fd3e64ab6b605450bed5a2c22ef2ec84cd40542e/libs/deepagents/deepagents/graph.py#L918)为父级及默认子级装配 summarization middleware；[`wrap_model_call`](https://github.com/langchain-ai/deepagents/blob/fd3e64ab6b605450bed5a2c22ef2ec84cd40542e/libs/deepagents/deepagents/middleware/summarization.py#L1526)重建有效历史、裁剪旧参数、外置历史、生成摘要并记录 `_summarization_event`，后续请求消费摘要及近期尾部 | 有 profile 时默认 85% 触发、保留 10%；[`请求预算`](https://github.com/langchain-ai/deepagents/blob/fd3e64ab6b605450bed5a2c22ef2ec84cd40542e/libs/deepagents/deepagents/middleware/summarization.py#L1434)统计消息、system、工具，显式扣 configured output。配对切割委托给锁定 LangChain 实现。原始 messages 保留，历史有读取路径；外置失败会告警后继续摘要，不能据此保证原文可读。重启持久性依赖调用方 checkpointer/backend，不由 factory 默认保证 |

两者都把摘要用于后续实际请求，而非只生成一段摘要后继续发送全部旧历史；也都没有用语义 Judge 保证摘要忠实。DeepSeek 本次未见与 DeepAgents 相同的显式输出预留，不能把阈值和安全保证合并描述。

本工程可借鉴“按实际容量触发、保留配对尾部、原历史可追溯、后续真正消费压缩视图、失败有界”的责任划分。原目标、权限、预算、执行及批准仍从 canonical facts 恢复，摘要仅辅助理解。本工程若承诺原文可重读，外置或恢复失败时不能照搬继续有损压缩的降级。具体候选由[主循环 Context 设计](../optimization/to_verify/conversation-loop-boundaries.md#311-context-压力与压缩)拥有；这里的源码不替代本地失败 baseline 或压缩后交付证据。
