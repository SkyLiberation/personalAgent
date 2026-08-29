# 工具执行与安全能力参考

**成熟的工具能力不是“模型能调用函数”，而是能力发现、动作准入、最小权限执行、执行事实和失败恢复的完整边界。** 沙箱限制能触达什么，审批决定当前动作能否越界，两者不能互相替代。

本页只拥有外部工具执行与安全机制比较；资料等级、固定提交与采用边界见[参考索引](README.md)。

## 1. 代表机制

| 实现 | 突出能力 | 安全边界 |
| --- | --- | --- |
| Codex | [Approvals and security](https://learn.chatgpt.com/docs/agent-approvals-security)把 sandbox mode 与 approval policy 分开；工具、MCP、规则和 Skill 脚本可有不同权限 | 沙箱是操作系统强制的资源边界；审批是具体动作的授权边界，受保护目录继续限制写入 |
| Claude Code | [Hooks](https://code.claude.com/docs/en/hooks)覆盖 `PreToolUse`、权限请求、失败、子级和会话事件，可用命令或策略判断阻止动作 | Hook 可以拒绝或补充 Context，但不能把模型判断冒充底层隔离；权限模式仍单独生效 |
| OpenHands | [Runtime architecture](https://docs.openhands.dev/openhands/usage/architecture/runtime)以 Action → ActionExecutor → Observation 明确请求和结果；[Security](https://docs.openhands.dev/sdk/guides/security)把 confirmation policy 与 security analyzer 分开 | `AlwaysConfirm`、`NeverConfirm`、`ConfirmRisky` 决定审批；风险分析器不自动改变确认策略；Docker sandbox 是推荐隔离边界 |
| Gemini CLI | [Sandbox](https://github.com/google-gemini/gemini-cli/blob/3c311beac2e78336816dd4a123db39743f9fbf85/docs/cli/sandbox.md)在命令受限时请求一次性的目录或网络扩权；Plan Mode 另有只读策略 | 扩权必须显示所需资源并逐次批准；计划态既有批准不应自动扩张成实现态权限 |
| DeepSeek Harness | [Capability seams](https://github.com/deepseek-ai/deepseek-harness/blob/b150a551b8d465e31e418e1b2eaf5e79bbb7d28e/docs/capability-seams.md)把工具注册、guarded execution pipeline、沙箱策略、审批与文件系统 Provider 分成 seam | seam 允许替换实现，但权限、审批、沙箱与执行结果仍需各自 owner |

## 2. 可复用的执行分层

1. **能力投影**只暴露当前主体、scope 和会话允许的工具子集。
2. **Proposal**保留模型选择的工具与原始参数，不携带执行成功含义。
3. **准入**确定性检查类型、权限、风险、幂等与是否需要用户批准。
4. **隔离执行**在最小文件、网络、凭据和进程权限内产生 Observation 或 Receipt。
5. **结果处理**区分拒绝、暂时失败、执行失败与成功，不以空值或 fallback 伪装成功。

## 3. 机制比较时必须追问

- 权限由身份与 scope 决定，还是仅靠 Prompt 提醒模型不要调用。
- 批准绑定原始动作、参数摘要和时效，还是批准后允许模型改写 payload。
- 只读、可重试动作与不可逆副作用是否采用不同执行协议。
- 安全分析器失败时是 fail closed、请求人工判断还是静默放行。
- 工具结果是否成为可审计执行事实，是否与语义验证和 Completion 分离。

personalAgent 的正式执行契约仍以[智能体决策与受治理执行](../devSpec/agentic-execution.md)和[测试、评估、观测与安全](../devSpec/quality-security.md)为准。
