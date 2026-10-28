# 计划与任务管理能力参考

**有效的计划能力把研究、可修订计划、执行授权和完成判断分开。** 计划的价值在于对齐策略与未决工作；计划文件或 Todo 状态本身既不是执行事实，也不是用户目标完成证明。

本页只拥有外部计划机制比较；资料等级、固定提交与采用边界见[参考索引](README.md)。

## 1. 代表机制

| 实现 | 突出能力 | 明确边界 |
| --- | --- | --- |
| Gemini CLI | [Plan Mode](https://github.com/google-gemini/gemini-cli/blob/3c311beac2e78336816dd4a123db39743f9fbf85/docs/cli/plan-mode.md)先只读研究，与用户讨论策略，再把计划写入受限目录并请求批准；策略引擎限制工具，研究子级可协助探索 | 批准后才进入实现；计划模式只允许写计划 Markdown，不把研究权限扩成代码修改权限 |
| Claude Code | [Subagents](https://code.claude.com/docs/en/subagents)内置 Explore 与 Plan 类型，可在独立 Context 中探索并把结论交回主会话 | Plan 子级的结果仍由主会话消费；隔离探索不自动拥有最终修改权 |
| LangGraph | [Workflows and agents](https://docs.langchain.com/oss/python/langgraph/workflows-agents)区分预定代码路径与动态模型决策，并支持并行、路由和 orchestrator-worker 模式 | 图结构表达运行控制，不天然拥有产品 Goal 或语义 Completion |
| DeepSeek Harness | [Capability seams](https://github.com/deepseek-ai/deepseek-harness/blob/b150a551b8d465e31e418e1b2eaf5e79bbb7d28e/docs/capability-seams.md)把计划协作状态、Goal、工具和运行循环分成独立服务 seam | 分离服务只说明可替换边界，不证明每个项目都需要持久 Plan 或 Goal 对象 |
| Hermes Agent | 官方 [Features overview](https://github.com/NousResearch/hermes-agent/blob/9dfbde19db7b108f9e961eec367ca5b54c8ad7d6/website/docs/user-guide/features/overview.md)把委托、定时任务和批处理作为不同自动化形态 | 自动化触发、任务列表和用户结果具有不同生命周期，不能以调度成功代替交付 |

## 2. 可复用的能力结构

1. **研究态**：只允许读取、搜索和澄清，不产生业务副作用。
2. **策略对齐**：显式暴露方案、取舍、范围外事项和待确认决策。
3. **计划工件**：可编辑、可取消、可替换，并能指出完成项和未决项。
4. **执行准入**：用户批准或确定性策略只决定能否执行，不替模型补业务计划。
5. **结果关闭**：执行事实、语义验证与用户完成分别判断；Todo 全绿不是 Completion。

## 3. 机制比较时必须追问

- 计划由模型、用户还是代码拥有；更新是完整替换、按 ID 合并还是追加事件。
- 已完成项能否被静默重开，删除和取消如何表达，跨压缩后如何重注入。
- 计划审批绑定的是计划版本、具体动作还是宽泛会话授权。
- 动态重新规划何时必要；确定性流程是否被不必要地包装成 Planner。
- 没有已测量的计划失配或恢复缺口时，能否直接删除 Plan 层。

personalAgent 是否引入任何计划机制，只能由本工程失败 baseline 与[智能体决策和受治理执行规范](../devSpec/agentic-execution.md)决定。

## 4. 澄清的入口、上下文与答复消费

2026-10-19 核对以下两个独立开源实现，共取得 17 个源码／配置文件，固定提交及 SHA-256 见[源码清单](../../.tmp/clarification-context-timing-20261019/manifest.json)。两者均为 A 级源码机制证据；未运行第三方项目、模型或测试，不据此主张澄清准确率或行业统一架构。Open Deep Research 仓库已归档，本节将其作为研究工作流参考。

| 实现 | 实际装配与消费链 | 触发、上下文与限制 |
| --- | --- | --- |
| Gemini CLI `ed96faedfd5571f055c44f2c9509d62321d1138d` | [`Config`](https://github.com/google-gemini/gemini-cli/blob/ed96faedfd5571f055c44f2c9509d62321d1138d/packages/core/src/config/config.ts#L4087)注册 `AskUserTool`；[`GeminiClient.startChat`](https://github.com/google-gemini/gemini-cli/blob/ed96faedfd5571f055c44f2c9509d62321d1138d/packages/core/src/core/client.ts#L410)把工具声明、system 和历史送入通用对话。模型选择提问后，Scheduler 经确认交互消费 [`AskUserInvocation.shouldConfirmExecute`](https://github.com/google-gemini/gemini-cli/blob/ed96faedfd5571f055c44f2c9509d62321d1138d/packages/core/src/tools/ask-user.ts#L159)；用户答案由工具返回，CLI 的 [`handleCompletedTools`](https://github.com/google-gemini/gemini-cli/blob/ed96faedfd5571f055c44f2c9509d62321d1138d/packages/cli/src/ui/hooks/useGeminiStream.ts#L2279)将实际工具响应送回模型继续 | 提问是模型可选工具，没有“任务先失败才允许问”的固定边。初始历史由 [`getEnvironmentContext`](https://github.com/google-gemini/gemini-cli/blob/ed96faedfd5571f055c44f2c9509d62321d1138d/packages/core/src/utils/environmentContext.ts#L52)提供日期、系统、会话记忆及配置允许的目录信息；后续历史包含实际交互与工具结果，不代表全部文件自动进入输入。[自主模式 Prompt](https://github.com/google-gemini/gemini-cli/blob/ed96faedfd5571f055c44f2c9509d62321d1138d/packages/core/src/prompts/snippets.ts#L481)对无合理默认值的根本歧义、重大返工或用户要求确认保留提问。非交互模式另有不可询问约束，不能外推同一交互契约 |
| Open Deep Research `1b7d2e80db9faa586165c60e09096dbbfd483a64` | `langgraph.json` 暴露 `deep_researcher` 图；[图装配](https://github.com/langchain-ai/open_deep_research/blob/1b7d2e80db9faa586165c60e09096dbbfd483a64/src/open_deep_research/deep_researcher.py#L696)连接 `START → clarify_with_user`。[该节点](https://github.com/langchain-ai/open_deep_research/blob/1b7d2e80db9faa586165c60e09096dbbfd483a64/src/open_deep_research/deep_researcher.py#L64)按 `allow_clarification` 配置跳过或调用模型；需要澄清时追加问题并 `END`，否则进入 `write_research_brief → research_supervisor` | 澄清模型实际消费格式化会话消息和日期，没有在该节点读取实验材料或工作环境的工具。[Prompt](https://github.com/langchain-ai/open_deep_research/blob/1b7d2e80db9faa586165c60e09096dbbfd483a64/src/open_deep_research/prompts.py#L3)判断信息是否足以开始研究，要求避免重复询问；brief 将未指定维度保留开放，不补造约束。本图可证明入口筛选，不能据此声称研究中具有任意位置的动态提问、默认持久恢复或跨轮统一预算 |

比较支持两种不同装配：面向明确研究委托的入口判断，以及通用执行循环中的按需提问。入口检查不等于必须问一次；工具也不等于必须先执行失败。提问工具的参数是模型生成的问题，不是模型作决定前自动拥有的全部 Context；前置模型请求构造与后续答复消费必须分别核对。

本工程候选采用“明显歧义及时问、可自行取得的事实先查、执行中新出现关键缺口再问”的职责划分，复用原对话与等待结果，不先引入独立澄清模型、固定前置问卷或通用澄清状态平台。通用时机、输入与待验证行为由[主循环 Spec](../optimization/to_verify/conversation-loop-boundaries.md#澄清的时机和决策上下文)拥有，研究中的具体询问方向由[实验交付 Spec](../optimization/to_verify/research-experiment-acceptance.md#13-输入不明确时怎样澄清)拥有。源码机制不是本工程失败 baseline 或行为通过证据。
