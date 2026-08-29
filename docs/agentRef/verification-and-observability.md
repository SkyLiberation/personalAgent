# 验证与可观测能力参考

**优秀实现会保留足以定位模型、工具、权限与运行阶段的证据，但 Trace、Observation、Review 或状态 success 都不能单独证明用户 Goal 完成。** 可观测负责回答“发生了什么”，Verifier 判断“结果语义是否满足”，Completion 再判断必需证据是否齐全。

本页只拥有外部验证与可观测机制比较；资料等级、固定提交与采用边界见[参考索引](README.md)。

## 1. 代表机制

| 实现 | 可观测或验证能力 | 不能推出的结论 |
| --- | --- | --- |
| GPT / Codex | GPT-5.6 [Model guidance](https://developers.openai.com/api/docs/guides/latest-model)要求在相同代表性任务上比较最终答案完整性、证据、token、延迟和成本；[Codex CLI](https://developers.openai.com/codex/cli/features)提供 Review 模式 | 更少调用或更低 token 只有在最终结果通过既有评测时才是改善；Review 不是生产 E2E |
| Codex | [Approvals and security](https://learn.chatgpt.com/docs/agent-approvals-security)可让独立 review agent 检查待执行动作，并在 review 失败时 fail closed | 动作通过安全 review 只表示可执行，不表示动作成功或用户完成 |
| Claude Code | [Hooks](https://code.claude.com/docs/en/hooks)覆盖工具前后、失败、权限、子级和会话生命周期；agent hook 可读取代码与测试输出后返回结构化判断 | Hook 结果的语义范围由配置决定，不能泛化成产品 Goal verifier |
| OpenHands | [Runtime architecture](https://docs.openhands.dev/openhands/usage/architecture/runtime)把每个 Action 的执行结果返回为 Observation；[Security](https://docs.openhands.dev/sdk/guides/security)可组合规则、模式与模型分析器 | Observation 证明执行结果；风险分类与 confirmation policy 是两个独立配置，均不等于用户结果 |
| DeepSeek Harness | [Architecture](https://github.com/deepseek-ai/deepseek-harness/blob/b150a551b8d465e31e418e1b2eaf5e79bbb7d28e/docs/architecture.md)的 append-only event stream 支撑 session 重建；能力图还提供 telemetry seam | 日志完整只证明运行可追溯，不证明 Context 选择或最终语义正确 |
| LangGraph | [Persistence](https://docs.langchain.com/oss/python/langgraph/persistence)支持状态检查与历史；[Human-in-the-loop](https://docs.langchain.com/oss/python/langchain/human-in-the-loop)在工具动作前暂停并保存状态，支持 approve、edit、reject、respond | 人工批准决定动作下一步，不应把 `respond` 或 checkpoint 当作副作用执行成功 |

## 2. 最小证据链

1. **输入与 Context 身份**：用户目标、约束、权限 scope、模型和配置可复核。
2. **Proposal 与准入**：模型原始选择、类型校验、授权或拒绝原因分开记录。
3. **执行事实**：动作参数摘要、幂等身份、Observation / Receipt、错误类型和外部资源 ID。
4. **语义验证**：以目标和关键反事实检查结果内容，不从工具次数或状态字段推断。
5. **Completion**：required result contract 的证据齐全后才关闭，并保留未验证风险。

## 3. 机制比较时必须追问

- Trace 是否能关联同一用户目标下的模型回合、子级、工具与外部动作。
- 敏感 Prompt、工具参数和结果如何脱敏、授权访问与设置保留期。
- review 或 grader 的输入是否包含真实用户结果，而非只有内部轨迹。
- 失败是否区分 Validation、Authorization、Execution、Verification 与 Completion。
- 成本、延迟和恢复指标是否与质量门槛同样预声明，避免事后挑选指标。

personalAgent 的发布证据仍由[测试、评估、观测与安全规范](../devSpec/quality-security.md)及 `evals/` 的 canonical catalog 管理；本页不登记本工程评测结果。
