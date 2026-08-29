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
