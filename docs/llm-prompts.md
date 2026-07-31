# LLM Prompt 与决策点

本文记录当前生产代码中的 Prompt Registry 和关键模型决策边界。Prompt 文本事实源是 `kernel/prompt_templates/`，调用方通过 `kernel.prompts.get_prompt()` 读取版本化 `PromptSpec`。

## 治理契约

每个 registry prompt 声明：

- `name`
- `version`
- `template`
- 可选 `output_contract`

内部决策优先使用 `StructuredModelRequest` 和 Pydantic strict schema；工具选择使用 tool calling。模型输出必须经过领域 validator，不能直接修改 Ledger、授权、scope 或持久化状态。

## Agent 控制 Prompt

| Prompt / 决策点 | 输出 | 职责 | 确定性边界 |
| --- | --- | --- | --- |
| `task_analyzer.system/user` | `TaskAnalysisProposalBody` | 理解用户目标，拆分 Goal，提出带 provenance 的 criterion、constraint、relation 和资源提示 | 经 `TaskAnalysisAdmission` 后才形成 `AcceptedTaskAnalysis`；不选择 tool、MCP、A2A、Skill、Macro、workflow 或 coverage |
| Executive structured decision | `_ModelExecutiveDecision` | 比较 ready Goal、Observation、Skill、Macro 和 capability class，提出下一步控制决策 | Runtime 物化判别联合并经 `DecisionValidator`；Ledger 修订另经 Patch validator |
| Goal verification structured decision | verifier schema | 在确定性证据门槛之后判断 criterion 是否满足 | 模型不能跳过 provenance、receipt、citation 和 source-count 门槛 |
| `react.system` | tool call | 在当前 BoundedAction 或 Protocol step 的 allowlist 内探索 | 受 allowed tools、迭代、token、deadline 和 side-effect 边界约束 |
| `structured.system` | `json_schema` | 通用严格结构化输出约束 | schema 解析失败即显式失败或领域降级 |

Task Analyzer 不存在关键词式离线语义路由。模型输出进入 `TaskAnalysisProposal → TaskAnalysisAdmission → AcceptedTaskAnalysis`；缺少 user-explicit grounding 时受限修订。模型未配置或调用失败时返回 `analyzer_unavailable` 控制性澄清，不恢复已删除的 Router 菜单。

Executive 和 verifier 的任务态 prompt 在各自模块中动态组装，因为它们需要完整 Goal Graph、Ledger revision、Observation provenance、候选 capability 和预算；它们仍通过 `StructuredModelRequest` 记录 schema 与调用元数据。

## Registry Prompt

### Task Analysis

- `task_analyzer.system`
- `task_analyzer.user`

核心约束是最小充分 Goal、独立 Goal 不建关系、关系使用 `consumes_output/requires_completion/ordering_preference`，并区分 `user_explicit/model_inferred` origin。

### Ask 与证据

- `answer_generation.system`
- `answer.dialogue_context_policy`
- `ask.unified_answer.user`
- `ask.correction.user`
- `query_planner.system/user`
- `evidence_rerank.system/user`

这些 prompt 负责 query understanding、证据排序、grounded answer 与修复，不拥有顶层 Goal 或执行关系决策。

### Runtime 与 Protocol

- `react.system`
- `structured.system`
- `delete_candidate_resolve.user`
- `solidify_draft.user`

删除候选解析只允许返回已有候选 ID；solidify 只选择用户指定范围内的对话事实。最终副作用仍由 Protocol、HITL 和 ToolGateway 控制。

### 记忆与图谱

- `thread_digest.user`
- `thread_context_compression.user`
- `graphiti.custom_extraction`

Thread prompt 只压缩会话上下文；Graphiti prompt 只影响实体关系抽取，不替代 Workspace admission 或 Goal verification。

## 非 Registry 决策

Workspace semantic extraction/relation judge、Research extraction 等领域模块也使用 strict `StructuredModelRequest`。它们的 schema 与 validator 位于对应领域模块，原因是输出契约属于领域模型，而不是通用 Agent 路由。

## 已删除 Prompt

以下旧控制 prompt 已从生产代码删除，不应在文档、评测或 registry 中继续出现：

- Router intent/coverage prompt 与 `RouterOutput`；
- GoalInterpreter prompt；
- 顶层 step planner / Execution Pattern selector；
- 失败后自由生成步骤的 Replanner prompt。

计划修订现在由 Executive 基于 Observation 提出受限 `LedgerPatchOperation`，而不是生成一份新的自由步骤列表。

## 变更门禁

修改 prompt 时应运行它所属的 golden suite：

- Task Analyzer：`evals/task_analysis_quality/`
- Procedure 编译：`tests/test_agentic_planning.py`
- Executive / Goal Graph：`tests/test_agentic_planning.py`
- Ask / evidence：RAG 与 orchestration quality suites
- 端到端状态：E2E 与 conversation suites

Prompt 版本变化必须和 schema、validator、eval expectation 同步；只改文案但不验证行为不算完成。
