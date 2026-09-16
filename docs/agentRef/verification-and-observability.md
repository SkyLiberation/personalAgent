# 验证与可观测能力参考

**优秀实现会保留足以定位模型、工具、权限与运行阶段的证据，但 Trace、Observation、Review 或状态 success 都不能单独证明用户 Goal 完成。** 可观测负责回答“发生了什么”，Verifier 判断“结果语义是否满足”，Completion 再判断必需证据是否齐全。

本页只拥有外部验证与可观测机制比较；资料等级、固定提交与采用边界见[参考索引](README.md)。

## 1. 代表机制

| 实现 | 可观测或验证能力 | 不能推出的结论 |
| --- | --- | --- |
| GPT / Codex | GPT-5.6 [Model guidance](https://developers.openai.com/api/docs/guides/latest-model)要求在相同代表性任务上比较最终答案完整性、证据、token、延迟和成本；[Codex CLI](https://developers.openai.com/codex/cli/features)提供 Review 模式 | 更少调用或更低 token 只有在最终结果通过既有评测时才是改善；Review 不是生产 E2E |
| OpenAI Agents SDK | [Output guardrails](https://openai.github.io/openai-agents-python/guardrails/)在最终输出形成后运行，返回带 tripwire 的校验结果；命中后阻止结果继续交付 | 输出校验负责接纳或阻止当前结果，不证明应重新开放动作，也不支持从校验反馈文本推导控制流 |
| Codex | [Approvals and security](https://learn.chatgpt.com/docs/agent-approvals-security)可让独立 review agent 检查待执行动作，并在 review 失败时 fail closed | 动作通过安全 review 只表示可执行，不表示动作成功或用户完成 |
| Claude Code | [Hooks](https://code.claude.com/docs/en/hooks)覆盖工具前后、失败、权限、子级和会话生命周期；agent hook 可读取代码与测试输出后返回结构化判断 | Hook 结果的语义范围由配置决定，不能泛化成产品 Goal verifier |
| OpenHands | [Runtime architecture](https://docs.openhands.dev/openhands/usage/architecture/runtime)把每个 Action 的执行结果返回为 Observation；[Security](https://docs.openhands.dev/sdk/guides/security)可组合规则、模式与模型分析器 | Observation 证明执行结果；风险分类与 confirmation policy 是两个独立配置，均不等于用户结果 |
| DeepSeek Harness | [Architecture](https://github.com/deepseek-ai/deepseek-harness/blob/b150a551b8d465e31e418e1b2eaf5e79bbb7d28e/docs/architecture.md)的 append-only event stream 支撑 session 重建；能力图还提供 telemetry seam | 日志完整只证明运行可追溯，不证明 Context 选择或最终语义正确 |
| LangGraph | [Persistence](https://docs.langchain.com/oss/python/langgraph/persistence)支持状态检查与历史；[Human-in-the-loop](https://docs.langchain.com/oss/python/langchain/human-in-the-loop)在工具动作前暂停并保存状态，支持 approve、edit、reject、respond | 人工批准决定动作下一步，不应把 `respond` 或 checkpoint 当作副作用执行成功 |
| LangGraph | [Evaluator-optimizer workflow](https://docs.langchain.com/oss/python/langgraph/workflows-agents#evaluator-optimizer)把生成器与评估器分开；评估器返回接纳或反馈，未接纳时由生成器修订结果 | 该循环只证明评估结果可以驱动结果修订，不证明所有证据不足都应重跑动作，也不要求照搬其图拓扑 |
| OpenAI Evals / Agents SDK | [Evals](https://developers.openai.com/api/docs/guides/evals)把待评 `sample.output_text` 与数据集标签分开；[Output guardrails](https://openai.github.io/openai-agents-python/ref/guardrail/)把 `agent_output` 作为独立 typed 输入并返回 guardrail 结果 | 明确被评对象和 rubric 可以减少输入串扰，但不能让同一个 grader 同时可靠拥有内容覆盖、事实抽取、证据支持和 Completion |
| Anthropic | [Develop tests](https://platform.claude.com/docs/en/test-and-evaluate/develop-tests)要求成功标准具体、复杂目标可使用多项 rubric；[Agent evals](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents)要求 grader 检查明确并验证其可靠性 | reference answer 与多 rubric 用于校准结果语义，不得演变为固定 Agent 工具、步骤、措辞或推理路径 |
| RAGAS / FActScore | RAGAS [`_faithfulness.py`](https://github.com/explodinggradients/ragas/blob/main/src/ragas/metrics/_faithfulness.py)把 statement 生成与 NLI 支持判断拆开；FActScore [`factscorer.py`](https://github.com/shmsw25/FActScore/blob/main/factscore/factscorer.py)先生成 atomic facts 再逐项取证评分 | 原子 Claim 与 Evidence 支持应独立，但外部评分、检索、缓存和数值阈值不能直接成为本项目 Completion 事实 |

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
