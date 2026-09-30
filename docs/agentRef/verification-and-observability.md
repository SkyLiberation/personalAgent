# 验证与可观测能力参考

**优秀实现会保留足以定位模型、工具、权限与运行阶段的证据，但 Trace、Observation、Review 或状态 success 都不能单独证明用户 Goal 完成。** 可观测负责回答“发生了什么”，Verifier 判断“结果语义是否满足”，Completion 再判断必需证据是否齐全。

本页只拥有外部验证与可观测机制比较；资料等级、固定提交与采用边界见[参考索引](README.md)。

## 1. 代表机制

| 实现 | 可观测或验证能力 | 不能推出的结论 |
| --- | --- | --- |
| OpenAI / Codex | [Model guidance](https://developers.openai.com/api/docs/guides/latest-model#favor-leaner-prompts)建议在自身代表性任务上验证输入调整；[Codex CLI](https://developers.openai.com/codex/cli/features)提供 Review 模式 | 输入更少不自动证明质量改善；Review 不是生产 E2E |
| OpenAI Agents SDK | [Output guardrails](https://openai.github.io/openai-agents-python/guardrails/)在最终输出形成后运行，返回带 tripwire 的校验结果；命中后阻止结果继续交付 | 输出校验负责接纳或阻止当前结果，不证明应重新开放动作，也不支持从校验反馈文本推导控制流 |
| Codex | [Approvals and security](https://learn.chatgpt.com/docs/agent-approvals-security)可让独立 review agent 检查待执行动作，并在 review 失败时 fail closed | 动作通过安全 review 只表示可执行，不表示动作成功或用户完成 |
| Claude Code | [Hooks](https://code.claude.com/docs/en/hooks)覆盖工具前后、失败、权限、子级和会话生命周期；agent hook 可读取代码与测试输出后返回结构化判断 | Hook 结果的语义范围由配置决定，不能泛化成产品 Goal verifier |
| OpenHands | [Runtime architecture](https://docs.openhands.dev/openhands/usage/architecture/runtime)把每个 Action 的执行结果返回为 Observation；[Security](https://docs.openhands.dev/sdk/guides/security)可组合规则、模式与模型分析器 | Observation 证明执行结果；风险分类与 confirmation policy 是两个独立配置，均不等于用户结果 |
| DeepSeek Harness | [Architecture](https://github.com/deepseek-ai/deepseek-harness/blob/b150a551b8d465e31e418e1b2eaf5e79bbb7d28e/docs/architecture.md)的 append-only event stream 支撑 session 重建；能力图还提供 telemetry seam | 日志完整只证明运行可追溯，不证明 Context 选择或最终语义正确 |
| LangGraph | [Persistence](https://docs.langchain.com/oss/python/langgraph/persistence)支持状态检查与历史；[Human-in-the-loop](https://docs.langchain.com/oss/python/langchain/human-in-the-loop)在工具动作前暂停并保存状态，支持 approve、edit、reject、respond | 人工批准决定动作下一步，不应把 `respond` 或 checkpoint 当作副作用执行成功 |
| LangGraph | [Evaluator-optimizer workflow](https://docs.langchain.com/oss/python/langgraph/workflows-agents#evaluator-optimizer)把生成器与评估器分开；评估器返回接纳或反馈，未接纳时由生成器修订结果 | 该循环只证明评估结果可以驱动结果修订，不证明所有证据不足都应重跑动作，也不要求照搬其图拓扑 |
| OpenAI Evals / Agents SDK | [Evals](https://developers.openai.com/api/docs/guides/evals)把待评 `sample.output_text` 与数据集标签分开；[Output guardrails](https://openai.github.io/openai-agents-python/ref/guardrail/)把 `agent_output` 作为独立 typed 输入并返回 guardrail 结果 | 明确被评对象和 rubric 可以减少输入串扰，但不能让同一个 grader 同时可靠拥有内容覆盖、事实抽取、证据支持和 Completion |
| Anthropic | [Develop tests](https://platform.claude.com/docs/en/test-and-evaluate/develop-tests)说明成功标准与评分；[Agent evals](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents)是官方工程文章，按 B 级参考 | 校准结果语义不等于固定工具、步骤、措辞或推理路径；文章不能单独作为已发布机制的 A 级坐标 |
| RAGAS / FActScore | [`_faithfulness.py`](https://github.com/explodinggradients/ragas/blob/main/src/ragas/metrics/_faithfulness.py)与 [`factscorer.py`](https://github.com/shmsw25/FActScore/blob/main/factscore/factscorer.py)是动态分支检索入口，关注断言生成与支持评分的分工 | 采用前补齐发布版本与调用链复核；未固定分支不能冒充已核对的发布实现，评分结果也不能直接成为本项目 Completion 事实 |

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

## 4. 工具可靠性的分层评估

2026-09-22 核对两个独立官方 A 级实现：[Google ADK Evaluation Criteria](https://adk.dev/evaluate/criteria/)分别提供工具轨迹、工具使用 rubric 和最终回答质量指标；[LangSmith complex agent evaluation](https://docs.langchain.com/langsmith/evaluate-complex-agent)分别检查最终回答、轨迹和关键单步。两者支持把失败定位到具体边界，而不是只给整条轨迹一个成功状态。这是机制参考，不能证明本工程某个工具名或 Schema 已改善。

工具优化可以沿以下边界保留原始分子与分母，并同时报告样本量及未到达阶段：

| 边界 | 观察内容 | 对应优化方向 |
| --- | --- | --- |
| 动作选择 | 对照当时任务、反馈及工具能力，所选动作是否相关且范围合适 | 名称、职责说明、可选动作集合 |
| 参数消费 | 原始响应能否通过 Schema，身份、版本和资源范围是否有效 | 消除混合职责、矛盾字段与不明确参数；不能静默修复输出后计为首次成功 |
| 执行 | 合法调用是否取得真实结果，失败是否来自服务、权限或执行器 | 先修执行边界，不能都归因于模型 |
| 语义效果 | 工具执行后是否解除实际反馈，是否破坏先前正确结果 | 检查实际模型输入、证据及修改范围，不能靠合法参数推断 |
| 用户结果与成本 | 原始目标是否满足，整条轨迹的时延、tokens 和恢复成本 | 质量达标后再比较效率；局部改善不能覆盖整链失败 |

ADK 的轨迹匹配可要求相同工具与参数顺序，LangSmith 示例也允许参考步骤比对；这些做法只适用于路径本身属于契约的对象。本项目开放研究任务不据此固定搜索顺序、调用次数或选用工具。借鉴其分层诊断，而不照搬固定轨迹评分或示例中的模拟执行。涉及模型前置依赖时仍需连续真实输出，单步定位不能替代完整任务验证。

协议合法率、执行成功率与语义修复率必须分别命名；结构化 JSON 动作的结果也不能冒充供应商原生 function calling 成功率。一次轨迹内的多次调用并非独立任务样本，少量调用只能说明已观察到的失败模式，不能外推稳定性。外部资料没有为本项目提供通用合格阈值，阈值必须由本项目预声明的结果契约决定。
