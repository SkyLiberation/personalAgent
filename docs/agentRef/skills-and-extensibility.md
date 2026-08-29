# 技能与扩展能力参考

**Skill 的突出价值是按任务加载可复用程序性知识；Plugin、MCP 和 Provider seam 则扩展工具或运行实现。** 把这些机制分开，才能同时控制 Context 成本、权限面和部署耦合。

本页只拥有外部技能与扩展机制比较；资料等级、固定提交与采用边界见[参考索引](README.md)。

## 1. 代表机制

| 实现 | 披露或扩展方式 | 突出能力 |
| --- | --- | --- |
| Codex | [`SKILL.md`](https://developers.openai.com/codex/skills)、Plugin、[MCP](https://learn.chatgpt.com/docs/extend/mcp) | 会话开始只暴露 Skill 名称和描述，显式或语义命中后加载正文；Skill 可带脚本与资源，MCP 连接外部工具和 Context |
| Claude Code | [`CLAUDE.md`、Skill、Subagent、Hook、Plugin、MCP](https://code.claude.com/docs/en/features-overview) | 为常驻规则、按需知识、隔离角色、确定性生命周期动作和分发单元分别提供机制 |
| OpenHands | [Skills](https://docs.openhands.dev/overview/skills)与 Runtime plugin | `AGENTS.md`保持仓库级简洁规则，Skill 可用关键词或路径确定性触发；Runtime plugin 注入执行能力 |
| Gemini CLI | [Plan Mode Skills](https://github.com/google-gemini/gemini-cli/blob/3c311beac2e78336816dd4a123db39743f9fbf85/docs/cli/plan-mode.md)、Extension、Hook、MCP | Skill 可定制研究和计划流程；策略引擎继续限制计划态工具，扩展不能因被加载而自动获得写权限 |
| Hermes Agent | [Skills、Plugin、MCP、memory/context Provider](https://github.com/NousResearch/hermes-agent/blob/9dfbde19db7b108f9e961eec367ca5b54c8ad7d6/website/docs/user-guide/features/overview.md) | Skill 遵循渐进式披露；Plugin 可增加工具和 Hook；memory/context Provider 可替换跨会话与 Context 实现 |
| Letta | [MemFS Skills](https://github.com/letta-ai/letta-docs-md/blob/0bfd40b73de18fca8fd9c370263d2e46ac5379df/concepts/memfs/index.md) | Skill 可由智能体作为记忆文件拥有、维护并与记忆仓库一起共享 |
| DeepSeek Harness | [Capability seams](https://github.com/deepseek-ai/deepseek-harness/blob/b150a551b8d465e31e418e1b2eaf5e79bbb7d28e/docs/capability-seams.md) | 服务声明、Provider 与消费者分离，可替换 compaction、subagent、sandbox、web、storage 等实现 |

## 2. 机制边界

- **Instruction**：稳定且必须始终生效的约束，按作用域发现。
- **Skill**：只对某类任务有用的知识、流程、脚本和资源，命中后进入当前 Context。
- **Subagent**：需要独立角色、工具或 Context 的任务执行者，不是更大的 Skill。
- **Hook**：由生命周期事件确定性触发的检查或副作用，通常不需要模型选择。
- **MCP / Plugin / Provider**：提供外部能力或替换实现；它们扩大能力面，因此必须单独治理权限、配置和失败。

## 3. 机制比较时必须追问

1. 触发依赖描述语义、关键词、路径还是显式调用；误触发与漏触发如何评测。
2. Skill 正文、脚本和资源何时进入 Context，是否有最小权限与可复核版本。
3. 扩展只是注册成功，还是存在生产构造点、真实消费者和删除后失败的测试。
4. Plugin 或 Provider 是否复制业务事实、吞掉错误或形成默认 fallback。
5. 同一流程应由稳定代码、Skill 还是模型动态决定，是否存在更小的 owner。

Skill 与扩展只提供机制复用方式，不能成为新增能力的需求来源。
