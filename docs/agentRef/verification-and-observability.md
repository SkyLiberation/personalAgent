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

## 5. 核验波动与重复阻塞的处理机制

2026-10-12 核对以下独立机制。它们分别处理评测、核验输入、循环控制与恢复，不构成消除 LLM 随机性的统一保证。及时检索和采用准入由 [EVD 重复阻塞复审](../devSpec/change-evidence.md#72-重复阻塞先复审方案再继续)拥有，本节只保存外部依据。

| 实现与证据身份 | 已核对的机制 | 可借鉴范围与限制 |
| --- | --- | --- |
| Anthropic 官方工程文章，2026-01-09，B 级：[Agent evals](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents) | 区分至少一次成功的 `pass@k` 与所有试次成功的 `pass^k`；用清楚标准、合法与错误对照校准模型评分 | 一致性主张须在实验前定义试次与判据；不能在旧用例通过后临时追加可靠性门槛，也不能反复采样只留一次成功 |
| Anthropic Managed Agents，官方动态文档于本日复核，A 级：[Define outcomes](https://platform.claude.com/docs/en/managed-agents/define-outcomes) | Grader 使用独立上下文，按明确 rubric 核查交付物并把反馈送回 Agent；`max_iterations` 限制修订循环 | 隔离实现者自评、逐项核验结果和有界修订；独立上下文不能保证语义判断正确，不自动要求按每类新建模型调用 |
| Anthropic 官方动态文档于本日复核，A 级：[Develop tests](https://platform.claude.com/docs/en/test-and-evaluate/develop-tests) | 按判断性质选择代码、人工或模型评分，模型评分先检验可靠性再扩大使用 | 结构、身份等确定性约束与开放语义分工；其精确词面示例不适合直接判断本项目含混的规范性质 |
| OpenHands software-agent-sdk 公共提交 `c0471362d340ade1e334595ba98417108b415e88`，A 级：[StuckDetector](https://github.com/OpenHands/software-agent-sdk/blob/c0471362d340ade1e334595ba98417108b415e88/openhands-sdk/openhands/sdk/conversation/stuck_detector.py#L208-L244)、[LocalConversation](https://github.com/OpenHands/software-agent-sdk/blob/c0471362d340ade1e334595ba98417108b415e88/openhands-sdk/openhands/sdk/conversation/impl/local_conversation.py#L744-L768) | 启用检测时，相同动作连续报错达到阈值产生一次纠正反馈；再重复则判为 `STUCK`，运行循环据状态退出 | 借鉴有界纠正和确定停止；这是动作错误循环检测，不是规范性质核验，也不是自动检索外部方案的实现。该坐标是已核对公共提交，不宣称最新发布版 |
| LangGraph 官方动态文档于本日复核，A 级：[Checkpointers](https://docs.langchain.com/oss/python/langgraph/checkpointers) | 恢复复用已完成节点写入；显式 replay 从检查点后重新执行，包括 LLM 调用 | 明确恢复与重新判决的边界；无效结构响应尚不是已接受业务结果，不能为保留语义而直接将其作为合法发现消费 |

这些资料支持先明确可判关系与评分边界、控制重复成本、保留真实结果的方向。新增多评审、模型替换或恢复协议仍需本工程真实失败、最小因果方案及预声明验收；外部品牌或机制存在本身不是收益证据。

## 6. 研究核验与汇总的职责边界

2026-10-15 按“研究是否足够、依据是否支持、汇总是否忠实”复核以下资料。前两项是独立实现的 A 级官方动态文档；源码项固定提交，不称作最新版本。

| 实现与坐标 | 实际机制、消费者及生命周期 | 本工程取舍 |
| --- | --- | --- |
| Anthropic Managed Agents，[Define outcomes](https://platform.claude.com/docs/en/managed-agents/define-outcomes)，A 级 | Grader 在独立上下文按 rubric 检查交付物，把结果反馈给执行 Agent；迭代受 `max_iterations` 限制，失败增加实际修订成本 | 采纳明确被评产物、验收要求及反馈消费者。独立上下文用于隔离实现过程，不据此增设 Source 后复核，也不推定每个判据都应单独调用 |
| Anthropic，[Multi-agent research system：Effective evaluation](https://www.anthropic.com/engineering/multi-agent-research-system)，B 级官方工程文章 | 研究结果按事实准确性、引用准确性、完整性等 rubric 评分；团队比较过多个评审，报告其单次 LLM 调用更符合人工判断 | 支持在一次判断中保留不同判据的设计方向。这是其研究评测结果，不是通用优劣结论，也不提供本工程 Source／Final 的生产协议或准确率保证 |
| LangSmith，[Evaluate a RAG application](https://docs.langchain.com/langsmith/evaluate-rag-tutorial#define-evaluators)，A 级 | 评测分别比较回答与问题、回答与资料；判据是数据集评估结果，由实验消费，不产生生产权限或完成状态 | 采纳目标充分性与证据支持的语义区别。本工程由同一研究核验器处理，仍按类别及真实用例分别验收；资料没有证明合并调用必定更准或更省 |
| Open Deep Research，提交 `1b7d2e80db9faa586165c60e09096dbbfd483a64`，A 级：[supervisor／final_report_generation](https://github.com/langchain-ai/open_deep_research/blob/1b7d2e80db9faa586165c60e09096dbbfd483a64/src/open_deep_research/deep_researcher.py#L607-L657)、[报告 Prompt](https://github.com/langchain-ai/open_deep_research/blob/1b7d2e80db9faa586165c60e09096dbbfd483a64/src/open_deep_research/prompts.py#L228-L248) | 研究 supervisor 收集结果后交接 notes；报告节点消费 research_brief、消息及 findings 成文。节点另有输出预算及超限恢复，研究停止条件也可能来自迭代耗尽 | 采纳依据原研究问题和完整笔记组织整体回答；本工程的事实综合由现有研究 writer 承担。不复制多智能体拓扑、笔记压缩或超限裁剪；该代码没有提供本工程的 typed Source 审批与 Final 融合回执，研究停止也不能直接充当研究合格 |

2026-10-15 补充核对 STORM 官方公开 `main` 源码，A 级动态坐标：[提纲生成](https://github.com/stanford-oval/storm/blob/main/knowledge_storm/storm_wiki/modules/outline_generation.py)、[正文生成](https://github.com/stanford-oval/storm/blob/main/knowledge_storm/storm_wiki/modules/article_generation.py)。提纲节点消费收集到的研究对话；正文节点按主题、章节提纲和检索资料成文。采纳由完整问题组织材料及写作的机制，不据此新增提纲事实、关系图、多智能体或独立模型阶段；该实现没有本工程的 claims／Source 协议，也不能证明其消除本例漏放。Open Deep Research 仍以上表固定提交解释，不声称最新实现。

同日针对核验再次漏放复核 [LangSmith RAG 评测](https://docs.langchain.com/langsmith/evaluate-rag-tutorial)：回答对问题的 relevance 与回答对原文的 groundedness 是不同比较，其示例分别使用对应输入；[Anthropic outcomes](https://platform.claude.com/docs/en/managed-agents/define-outcomes)把 rubric 应用于实际交付物并限制迭代次数。两者均为 A 级官方动态文档。采纳目标满足与事实有据分别校准、按交付物验收和有界纠正；不照搬多个评测调用或解释字段，也不据此认定“如实说明未知”自动满足本工程的核心目标。用户允许未知的具体边界仍由本任务要求及真实用例决定。

上述资料均未直接规定本工程的统一产物、八类核验及完成契约。该候选依据真实失败和用户最新要求设计，唯一正文见[研究与最终回答统一核验](../optimization/to_verify/research-goal-coverage.md#2026-10-15-sourcecoverage-与-final-合并设计)。参考实现的模型输出只提供语义判断或正文；权限、原文身份、版本及完成条件仍由各自宿主负责，本工程不从参考架构继承权限或恢复保证。

2026-10-21 针对“程序算对、最终报告仍写错”补充复核两个独立机制。smolagents 固定提交 `96f33faaf028479119ec8d34507b47694cf14e34` 的 [CodeAgent 执行返回](https://github.com/huggingface/smolagents/blob/96f33faaf028479119ec8d34507b47694cf14e34/src/smolagents/agents.py#L1720-L1764)与 [最终检查消费](https://github.com/huggingface/smolagents/blob/96f33faaf028479119ec8d34507b47694cf14e34/src/smolagents/agents.py#L577-L618)分别把代码结果交回模型、对拟交付答案调用可选检查；检查失败可反馈并继续，步数耗尽路径不据此保证检查通过。Anthropic [Programmatic Tool Calling](https://platform.claude.com/docs/en/agents-and-tools/tool-use/programmatic-tool-calling)的官方动态契约支持代码筛选、聚合后回传结果；其 [Define outcomes](https://platform.claude.com/docs/en/managed-agents/define-outcomes)另以独立上下文 grader 核查实际产物并限制修订次数。以上均按 A 级解释，闭源部分仅证明公开契约，不推测内部实现。

可借鉴的分工是“程序拥有计算事实，写作者组织论证，核验消费者判断实际成文与事实是否一致”。程序结果正确、引用存在或写作者自检都不能替代最后一个边界；增加 checker 也不自动证明它准确。是否复用当前核验器、输入是否充分、反馈能否驱动有界修订，仍须由本工程真实轨迹及既定判据验证，不照搬框架或增加按错误类别划分的多套核验。

## 7. 数据库执行入口的局部观察

2026-10-21 为研究验收取证的重复启动阻塞核对 OpenTelemetry Python contrib 固定提交 `de43f819a4a919213d246a23e62a1b256aeca7b9`，A 级源码；[两份原件及 SHA](../../.tmp/research-capability-20261020/t5/sql-observer-external-1/source-index.json)已封存，未安装或执行第三方项目。

[`wrapped_connection`](https://github.com/open-telemetry/opentelemetry-python-contrib/blob/de43f819a4a919213d246a23e62a1b256aeca7b9/instrumentation/opentelemetry-instrumentation-psycopg/src/opentelemetry/instrumentation/psycopg/__init__.py#L324-L338)配置 cursor factory；其[同步 Cursor 子类](https://github.com/open-telemetry/opentelemetry-python-contrib/blob/de43f819a4a919213d246a23e62a1b256aeca7b9/instrumentation/opentelemetry-instrumentation-psycopg/src/opentelemetry/instrumentation/psycopg/__init__.py#L384-L418)将 execute／executemany 交给 `CursorTracer.traced_execution`。该[实际执行方法](https://github.com/open-telemetry/opentelemetry-python-contrib/blob/de43f819a4a919213d246a23e62a1b256aeca7b9/instrumentation/opentelemetry-instrumentation-dbapi/src/opentelemetry/instrumentation/dbapi/__init__.py#L867-L910)在未开启 SQL commenter 时调用原 query method 并保留其返回或异常，执行后记录观测。参数收集和 SQL commenter 为不同选项；该框架也支持保存查询文本，不能把使用它等同于已满足本工程隐私要求。

可借鉴其把观察限定在真实数据库调用边界的取舍，不继承全进程 Python profile、连接代理、exporter 或新的持久总账。本工程若选择在专用评测进程透明包装现有 Cursor 方法，与上述 cursor factory 装配存在差异，须另核本地池、所有调用入口、实际参数／返回／异常保持和未知消费；不能只凭外部实现证明覆盖或省时。用途及重新准入由[研究交付 Spec](../optimization/to_verify/knowledge-decision-delivery.md#62-同一任务的最终证据汇总)拥有，执行记录不替代知识事实前后对照或产品结果。
