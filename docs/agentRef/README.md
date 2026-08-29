# 优秀智能体能力组件参考（REF）

**本目录按能力组件横向归纳已发布智能体与运行框架，不按厂商分别写产品介绍。** 它是外部机制检索入口，不是本工程现状、未来路线或技术选型结论；任何采用决策仍须先满足[变更证据与设计准入](../devSpec/change-evidence.md)的本工程 baseline、双 A 级实现和消融要求。

资料只采用官方产品文档、官方规范或主仓库已发布源码，统一核对于 2026-08-27。产品文档是随发布变化的坐标；GitHub 资料固定到下文提交。文档中的“共同模式”是基于多个来源的归纳，不代表这些实现具有相同语义，也不证明机制在 personalAgent 中有效。

## 1. 按任务信号渐进读取

先读本页，再只打开命中任务的组件文档；一个任务命中多行时取并集。

| 识别信号 | 必读组件 | 主要问题 |
| --- | --- | --- |
| 指令层级、Prompt、Context、压缩、卸载、按需加载 | [Context Engineering](context-engineering.md) | 如何只把当前决策需要的信息送入模型 |
| 跨轮状态、短期记忆、长期记忆、会话、用户画像 | [记忆与会话](memory-and-session.md) | 什么需要保留、由谁写入、何时召回或失效 |
| Plan、Todo、任务分解、计划审批、计划修订 | [计划与任务管理](planning-and-task-management.md) | 如何把研究、计划、执行和完成分开 |
| 工具调用、权限、审批、沙箱、Hook、副作用 | [工具执行与安全](tool-execution-and-safety.md) | 如何限制能力、准入动作并生成执行事实 |
| Subagent、Handoff、并行、团队、委托 | [多智能体与委托](multi-agent-and-delegation.md) | 如何隔离角色与上下文，并明确最终结果 owner |
| Checkpoint、resume、replay、durable execution、长任务 | [运行恢复与长任务](runtime-recovery.md) | 如何恢复必要状态而不重复副作用 |
| Skill、Plugin、MCP、Extension、能力发现 | [技能与扩展](skills-and-extensibility.md) | 如何按需披露可复用流程与外部能力 |
| Trace、Observation、Review、Verifier、评测 | [验证与可观测](verification-and-observability.md) | 如何区分运行记录、语义验证和用户完成 |

## 2. 参考对象与能力类型

这些对象用于覆盖不同机制类型，不构成综合排名。

| 对象 | 类型 | 本目录重点观察的能力 |
| --- | --- | --- |
| GPT / Codex | 推理模型与编码智能体产品 | 结果导向指令、工具编排、渐进式技能、审批沙箱、并行子级与工作树 |
| Claude Code | 编码智能体产品 | `CLAUDE.md`、Skills、隔离子级、权限与生命周期 Hook 的组合 |
| OpenHands | 开源软件开发智能体与运行环境 | Action/Observation 循环、可替换沙箱、技能触发、风险分析与确认策略 |
| DeepSeek Harness | 模块化智能体 Harness | durable session log、能力 seam、压缩、可继续子级、后台作业与团队协调 |
| Gemini CLI | 编码智能体产品 | 只读 Plan Mode、计划协作与批准、策略引擎、Checkpoint 与沙箱扩权 |
| Hermes Agent | 通用个人智能体 Harness | 持久记忆、渐进式技能、项目上下文、委托、自动化与多渠道工具面 |
| Letta | 记忆原生的有状态智能体平台 | 智能体拥有的 Git 记忆、常驻/按需上下文、记忆维护与共享 |
| LangGraph | 状态化智能体编排框架 | thread checkpoint、跨 thread store、interrupt、恢复和子图状态范围 |

## 3. 可复核坐标

| 来源类型 | 固定坐标或复核方式 |
| --- | --- |
| DeepSeek Harness | `deepseek-ai/deepseek-harness@b150a551b8d465e31e418e1b2eaf5e79bbb7d28e` |
| Gemini CLI | `google-gemini/gemini-cli@3c311beac2e78336816dd4a123db39743f9fbf85` |
| Hermes Agent | `NousResearch/hermes-agent@9dfbde19db7b108f9e961eec367ca5b54c8ad7d6` |
| Letta MemFS 文档 | `letta-ai/letta-docs-md@0bfd40b73de18fca8fd9c370263d2e46ac5379df` |
| OpenAI / Codex | [GPT-5.6 Model guidance](https://developers.openai.com/api/docs/guides/latest-model)、[Codex Skills](https://developers.openai.com/codex/skills)、[Codex `AGENTS.md`](https://developers.openai.com/codex/guides/agents-md)及 ChatGPT Work/Codex 官方文档；按核对日期解释 |
| Anthropic / Claude Code | [Features overview](https://code.claude.com/docs/en/features-overview)、[Subagents](https://code.claude.com/docs/en/subagents)、[Hooks](https://code.claude.com/docs/en/hooks)；按核对日期解释 |
| OpenHands | [Skills](https://docs.openhands.dev/overview/skills)、[Runtime architecture](https://docs.openhands.dev/openhands/usage/architecture/runtime)、[Security](https://docs.openhands.dev/sdk/guides/security)；按核对日期解释 |
| LangGraph | [Persistence](https://docs.langchain.com/oss/python/langgraph/persistence)、[Subgraphs](https://docs.langchain.com/oss/python/langgraph/use-subgraphs)、[Human-in-the-loop](https://docs.langchain.com/oss/python/langchain/human-in-the-loop)；按核对日期解释 |

## 4. 使用方式

1. 从本工程已执行 baseline 定位失败阶段和唯一 owner，再按上表打开相关组件。
2. 在组件内选择至少两个相互独立的 A 级实现，重新核对目标版本、构造点、消费者、写入和失败语义。
3. 形成 `External Mechanism Comparison`，明确采纳与拒绝的语义；禁止按产品名照搬对象、拓扑或状态。
4. 把候选约束为可删除、可单变量消融的最小机制，并用本工程真实 target E2E 判断是否有效。

新增参考对象时，只有它提供现有样本未覆盖的能力语义，或能替换失效来源，才进入本目录；只增加品牌数量但没有新机制的资料不收录。
