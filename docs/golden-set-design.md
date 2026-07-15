# Golden Set 设计

## 目标

工程使用多套职责互斥的 golden set 评估 Task Analysis、Goal/Procedure 编译、Executive 控制、Capability、工具治理、检索回答和多轮状态。

统一形状为：

```text
Case -> RunOutput -> pure scorer -> baseline -> regression gate
```

baseline 是不得下降的地板，不是质量目标。降低 baseline 必须说明原因；模型、prompt、schema 或控制策略变化必须先补能定位问题的 case。

## 设计原则

1. case 标注用户可观察行为和架构不变式，不锁定无意义的内部实现细节。
2. scorer 只消费 thin `RunOutput`，不直接依赖 runtime 对象。
3. 离线 deterministic gate 与真实模型/真实 provider gate 分开报告。
4. 副作用、权限、幂等、HITL 和完成条件使用硬断言，不能被平均分掩盖。
5. 每套 suite 只拥有一个清晰决策边界，避免同一个语义在 TaskAnalyzer、Executive、Protocol 和 E2E 重复打分。
6. Observation 驱动的计划修订必须评估触发证据、Patch 合法性和最终效果，不能只评估初始计划。

## 评测矩阵

| Suite | 评测单元 | 负责 | 不负责 |
| --- | --- | --- | --- |
| `task_analysis_quality` | 单轮 EntryInput/对话上下文 | outcome、Goal 拆分、ResourceHint、typed GoalRelation、clarification | capability coverage、provider 选择、执行步骤 |
| Goal Graph / Executive tests | TaskAnalysis + Ledger + Observation | graph 不变式、ready Goal、决策合法性、依赖修订、verification/completion | 自然语言分析质量 |
| Procedure tests | ProcedureSpec + ProcedureCall | spec 校验、节点投影、事务不变量、版本隔离 | 开放式 Goal、语义依赖推断 |
| Capability quality | CapabilityRequirement + Registry/Policy | native/MCP/A2A eligibility、coverage、scope、binding、rank、拒绝原因 | 最终答案质量 |
| Tool quality | tool definition/call | governance、schema、risk、HITL、幂等、artifact contract | 为什么选择这个工具 |
| RAG quality | retrieval + answer run | recall、ranking、faithfulness、citation、contradiction | 顶层控制决策 |
| Orchestration quality | 单次 entry 到 terminal | 关键事件、禁止事件、终态、不挂死、事故回归 | 跨 turn 状态继承 |
| Conversation quality | 完整多轮轨迹 | thread 连续性、clarification/confirmation resume、状态 delta | 单点组件指标 |
| E2E quality | 真实环境完整任务 | 用户目标、provider、数据与终态的综合结果 | 组件级精确归因 |

## Task Analysis 金标

位置：`evals/task_analysis_quality/`。

Case 口径：

```text
EntryInput
  -> expected_outcome: ready / clarify / rejected
  -> expected_result_contracts
  -> optional expected relations/resource hints/clarification fields
```

这里不再标注 `route_type`、`coverage`、`matched_capabilities` 或 `missing_requirements`。Task Analyzer 不读取 Capability Registry，因此不能判断当前部署是否能完成任务。

重点覆盖：

- 简单请求只产生一个最小充分 Goal；
- 复合请求拆为独立可验证 Goal；
- 明确“先 A，再基于 A 做 B”形成 `user_explicit consumes_output/requires_completion`；
- 只有展示或时间偏好时使用非阻塞 `ordering_preference`；
- 独立 Goal 不因出现“然后”就自动串行；
- 明确 provider 只形成 required/preferred ResourceHint；
- 信息不足会改变目标或副作用边界时才澄清；
- 模型不可用时显式 `analyzer_unavailable`，不启用关键词兜底。

离线 gate 使用 deterministic structured-output fixture 验证 schema/scorer；real gate 使用真实 structured model，允许单独 baseline 和波动范围。

## Goal Graph 与 Executive

Goal Graph 使用单元和场景测试保护确定性不变式：

- relation 端点存在、无重复、自依赖或阻塞环；
- ordering preference 不阻塞；
- `user_explicit` dependency 不可改；
- inferred/runtime dependency 只能在存在触发 Observation 时修订；
- Patch 后仍无环，且不能让开放 Goal 依赖 abandoned Goal；
- Executive 一次只产生一个合法 ControlDecision；
- action success 只到 candidate，必须再经过 GoalVerifier；
- finish 必须通过 CompletionVerifier。

模型 Executive 的独立 quality suite 应按“状态 -> 决策 -> 结果”评估，而不是要求每个 case 命中唯一动作。可接受动作集合、禁止动作、预期信息增益、预算和最终 criterion 达成比 exact next-action 更能衡量 Agentic 决策质量。

## Procedure 编译门禁

Procedure 编译由 `tests/test_agentic_planning.py` 与入口级 case 共同覆盖。Case 直接构造 `ProcedureSpec + ProcedureCall`，不经过 Task Analyzer。指标包括：

- task dependency exact / edge F1；
- step dependency exact / edge F1；
- topology 与 namespace；
- tool sequence 与 forbidden tool；
- risk、confirmation 和 projection contract。

开放式 answer、investigation、summarize 不属于 Procedure 编译门禁。它们由 Executive 组合 BoundedAction，并在 Executive、RAG 和 E2E suites 中评估。

## Capability 与外部 Agent

Capability case 应直接构造 Goal-scoped `CapabilityRequirement`，覆盖：

- required provider 不得被 preferred provider 替代；
- capability class、resource type 和 operation 全部匹配；
- denied、unavailable、partial、satisfied 不混淆；
- lexicographic rank 不允许低信任通过加权分抵消硬约束；
- MCP 调用仍受 ToolGateway scope/policy/audit；
- A2A 委派只接收最小 SubtaskSpec，artifact 默认 unverified；
- provider 失败成为 Observation，由 Executive 决定重试、换 provider、澄清或停止。

## Orchestration 与 Conversation

Orchestration case 一次只执行一个 entry，重点检查事件子序列、禁止事件和 terminal。Conversation case 才负责多个 turn、同 thread checkpoint、clarification/confirmation resume 与副作用 delta。

两者可以共享事件 scorer，但不能合并成一个平均分：单次事故需要精确归因，多轮成功是跨 turn 的合取条件。

有状态 case 必须使用独立 user/thread，并显式 seed 所需数据；没有 seed 的“知识整理/冲突检测”只能测到空数据分支。

## 真实环境分层

| 层 | 依赖 | 用途 |
| --- | --- | --- |
| L0 pure scorer | 无 DB/LLM | 指标数学与边界 |
| L1 hermetic contract | fake model/provider | schema、validator、投影与事故复现 |
| L2 real model | 真实模型，可隔离 DB/provider | prompt 与语义决策质量 |
| L3 live E2E | 真实 DB、模型、MCP/A2A/provider | 部署可用性与综合任务成功 |

报告必须标明层级。fixture 通过不能被表述为真实 Agent 质量通过；live provider 波动也不能替代 hermetic contract gate。

## Baseline 与失败诊断

每次 gate 输出 aggregate 和逐 case mismatch。硬不变式单独失败，不参与宽松平均。baseline 文件只存稳定指标阈值和必要说明，不保存无法复现的临时运行结果。

失败按边界归因：

- Goal/Relation 错：Task Analysis；
- relation 合法但 runtime 未调整：Executive/Patch；
- requirement 正确但 provider 错：Capability Resolver；
- provider 正确但调用越权：Gateway/Policy；
- action 成功但错误完成：Verifier；
- Protocol 内步骤错误：Protocol compilation/execution；
- 单轮正确但 resume 丢状态：Conversation/checkpoint。

这个归因表也是新增 case 选择 suite 的依据。
