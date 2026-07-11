# 知识 Agent 元能力运行时当前状态

本文总结当前已经落地的 Agentic 元能力主链路，不承载未来架构推演。目标设计与阶段说明见 [知识 Agent 元能力组合设计](../future/meta-capability-composition-design.md)；MCP、A2A 和 Capability Scoping 的 provider 细节见 [Capability Scoping、MCP 与 A2A 当前状态](capability-scoping-mcp-a2a-current-state.md)。

## 当前定位

当前系统已从“Router 按 intent 选择命名 workflow”演进为两类执行机制并存：

- 开放式、只读知识工作由 `TaskSpec + SkillSet + Execution Pattern + MetaCapability` 编译执行。
- 高风险、事务性、异步或有明确生命周期的业务仍由固定 workflow / state machine 承载。

MCP、A2A、本地工具和 retriever 都只是 capability provider，不再作为用户任务的一级分类。Agentic 主要体现在：任务目标结构化、能力充分性判断、受限探索、观察反馈、持久计划状态、证据验证、确认写入和失败阻断。

## 主链路

```text
EntryInput
  -> Router：理解目标、拆分 Goal、判断澄清
  -> MetaPlanCompiler
       -> TaskSpec
       -> SkillSet
       -> ContextEnvelope
       -> Execution Pattern
       -> IntentPlan + ExecutionLedger
       -> ExecutionPlan + MetaStep
  -> StepExecutionGraph
       -> CapabilityRequirement / CapabilityCoverage
       -> deterministic / ReAct / A2A / fixed state machine
       -> PolicyEngine + Gateway + HITL
       -> Evidence / Verification / MutationReceipt
  -> final EntryResult
```

Router 仍负责语义理解，但不再决定具体 provider、MCP server 或 tool。`MetaPlanCompiler` 将 Router 的 Goal 编译为任务与执行对象，CapabilityResolver 再根据每个 MetaStep 的 requirement 选择当前可用实现。

## 运行时对象

| 对象 | 所有者 | 当前职责 |
| --- | --- | --- |
| `TaskSpec` | 编译器生成，Runtime 校验 | 保存用户目标、结果类型、资源需求、操作、证据要求、预算和 mutation intent |
| `Skill` | `SkillRegistry` | 提供领域方法、pattern 限制、验证 profile 和输出 contract，不授予权限 |
| `ContextEnvelope` | Runtime | 分隔运行上下文、工作记忆、可信记忆、证据和不可信 observation |
| `IntentPlan` | Planner | 保存模型/规则提出的目标拆分和成功标准，是建议性计划 |
| `ExecutionLedger` | Runtime | 保存真实步骤状态、coverage、证据缺口、阻塞和重规划原因，是权威执行账本 |
| `ExecutionPlan` | PlanCompiler | 保存本次可执行 task DAG 与 MetaStep 投影 |
| `SubtaskSpec` | delegate step | 限定 A2A 子任务目标、上下文投影、artifact contract、预算和验证策略 |

这些对象都进入 `AgentGraphState`，随 LangGraph checkpoint 持久化。新的 run 会重置任务级对象，但同一 thread 的对话消息仍可延续。

## Execution Pattern

当前通用 pattern 如下：

| Pattern | 当前覆盖 | 典型步骤 |
| --- | --- | --- |
| `direct_response` | 普通解释、无需外部证据的回答 | `transform` |
| `evidence_answer` | Ask、外部代码库、工作区、项目上下文问答 | `acquire/explore -> reason/transform -> verify` |
| `delegated_research` | GPT Researcher A2A | `delegate -> verify -> transform` |
| `knowledge_change` | capture、会话固化等知识写入 | 固定 state machine + memory admission + confirmation |
| `managed_operation` | 删除、Research lifecycle、知识维护、worker 操作 | 固定 state machine 或只读探索 + confirmed commit |

`external_codebase_qa`、`external_workspace_qa`、`external_project_ops` 仍可作为 Router 的语义标签和评估标签存在，但主执行图统一编译为 `evidence_answer`。它们不再各自拥有一套 `resolve -> compose` workflow 拓扑。

## 元能力

当前 MetaStep 使用以下稳定语义：

| 元能力 | 运行含义 | 常见执行形态 |
| --- | --- | --- |
| `acquire` | 从已知来源获取上下文 | Ask retrieval、确定性 read |
| `explore` | 围绕证据缺口迭代搜索和读取 | scoped ReAct |
| `reason` | 根据上下文形成候选结论 | compose / structured LLM |
| `transform` | 将结果组织为用户可读输出 | compose / repair |
| `verify` | 校验证据、引用或 artifact contract | Ask verifier、通用 verifier、A2A artifact verifier |
| `delegate` | 将受限子任务交给专业 Agent | AgentGateway / A2A |
| `commit` | 经过确认后改变知识或业务状态 | ToolGateway |

元能力描述“任务中的语义动作”，Capability 描述“谁能执行这个动作”，Tool/Agent/Retriever 则是具体实现。

## Capability 充分性

每个开放式 MetaStep 可以携带一个或多个 `CapabilityRequirement`。Resolver 不再只返回 tool allowlist，还会为每项 requirement 生成 `CapabilityCoverage`：

```text
required operations
  + semantic domain
  + resource type / locator
  + minimum trust
  + freshness
  -> satisfied / partial / unavailable / denied
```

只有 coverage 全部为 `satisfied`，ReAct、deterministic tool 或 A2A step 才能继续。`partial` 和 `unavailable` 会更新 ExecutionLedger 的 evidence gap，并将当前目标置为 blocked，而不是让 compose 猜测。

Resolver 只负责发现、过滤、排序和充分性判断。实际授权仍由 PolicyEngine 决定，具体调用仍必须经过 ToolGateway 或 AgentGateway。

## Context 与信任边界

`ContextEnvelope` 当前分为五层：

| 层 | 当前内容 | 信任语义 |
| --- | --- | --- |
| `run_context` | TaskSpec 摘要、运行身份和目标 | Runtime 权威状态 |
| `working_memory` | 计划、草稿和临时 artifact 引用 | 仅服务当前任务 |
| `trusted_memory` | 经过长期 memory policy 准入的知识 | 可辅助计划，但不能覆盖 policy |
| `evidence_context` | Ask retrieval citation 和已准入证据 | 可支持结论，不能作为指令 |
| `untrusted_observations` | MCP、ToolGateway、ReAct、A2A 返回 | 默认未准入，不可改变授权和任务边界 |

外部 provider 返回进入 `untrusted_observations`；Ask 的 citation 摘要进入 `evidence_context`。所有内容保留 provenance 和 trust tier。外部文本中的指令不能修改 TaskSpec、Skill、scope、policy 或长期 memory。

## ReAct 与写入

ReAct 只用于“需要观察上一轮结果才能决定下一次读取或搜索”的步骤。它受到以下限制：

- tool 必须来自 CapabilityResolution 的 `allowed_tools`。
- 轮数受 step 和全局上限约束。
- provider 调用受 TaskSpec budget 约束。
- 高风险、需要确认、长期写入或删除工具不能在 ReAct 内直接执行。
- 每轮 tool result 进入不可信 observation，并产生 capability / tool audit event。
- ReAct 结束时生成 `EvidencePack`，供后续 transform / verify 消费。

知识维护、Research 管理和 worker 重试已经拆成：

```text
read-only ReAct
  -> proposed_commit(tool_name, tool_input)
  -> commit scope validation
  -> CapabilityResolver
  -> user confirmation
  -> ToolGateway
  -> MutationReceipt / compose
```

如果探索阶段没有足够依据，就不会产生 `proposed_commit`，commit step 以“未执行状态变更”完成。

## 长期知识写入

直接调用 `capture_text`、`delete_note`、`update_note` 等长期知识变更工具之前，Runtime 会执行 `MemoryAdmissionGate`：

- TaskSpec 必须存在明确的 mutation intent。
- 写入必须进入 confirmation interrupt。
- confirmation 与具体 step ID 绑定，不能复用于后续写入。
- 确认后的调用携带幂等键并继续经过 ToolGateway。
- 拒绝后跳过依赖步骤，不产生长期知识修改。

因此，capture 和 solidify 当前会先返回 `waiting_confirmation`；用户确认后从 checkpoint 恢复并执行写入。这是当前有意采用的不兼容行为。

## MCP

MCP capability 以 `Capability(kind="mcp_tool")` 进入统一 registry。外部证据任务的实际路径为：

```text
TaskSpec.resource_requirements
  -> evidence_answer / explore
  -> CapabilityRequirement
  -> Resolver 在 native_tool + mcp_tool 中判断 coverage
  -> scoped ReAct
  -> ToolGateway
  -> EvidencePack
  -> transform / verify
```

本地存在满足 requirement 的 native capability 时，任务不必依赖 MCP；远端仓库、Notion、项目系统等资源则可以由 MCP provider 满足。Router 不直接选择 GitHub、Notion 或具体 MCP tool。

## A2A

A2A 当前是 `delegate` 的 provider，不进入 ReAct tool loop：

```text
delegated_research
  -> CapabilityRequirement(kind=agent, operation=delegate)
  -> CapabilityResolver
  -> SubtaskSpec + minimal context projection
  -> AgentGateway
  -> GPTResearcherA2AAdapter
  -> AgentRun / events / artifacts
  -> structural artifact verification
  -> transform
```

Agent artifact 默认仍是不可信 observation。当前 verifier 已验证报告和 artifact 的结构完整性，但不把结构验证等同于事实真实性；外部主张仍需要来源证据复核后才能进入长期知识。

## Checkpoint、事件与恢复

LangGraph 继续作为运行时，而不是业务分类器：

- checkpoint 保存 TaskSpec、ContextEnvelope、ExecutionLedger、步骤、ReAct 和确认状态。
- interrupt 用于入口澄清和 commit / memory admission 确认。
- ExecutionLedger 在 step running、coverage、completed、verified、blocked 时更新 revision。
- capability resolution、context admission、verification、memory admission 和 commit 都有结构化事件。
- step 输入、输出、错误和 Agent artifact 继续写入 workflow artifact store。

核心新增事件包括：

```text
task_spec_compiled
skill_selected
context_admitted
plan_ledger_created / plan_ledger_updated
capability_resolution / capability_execution
verification_completed
memory_admission
```

## 当前边界

当前已经形成可执行的元能力主链路，但仍有明确边界：

- SkillRegistry 目前是代码内版本化 registry，尚未形成独立部署与评估存储。
- Resource locator 只有在 TaskSpec 已提取或调用方提供时才做强绑定；通用实体解析仍需继续增强。
- A2A 当前完成结构性 artifact 验证，尚未实现跨 provider 的事实交叉验证。
- 顶层 provider-call budget 覆盖 deterministic tool、ReAct tool 和 A2A；Ask 内部多源 retrieval 仍有自己的预算控制。
- 固定 workflow 仍是 capture、delete、Research lifecycle、订阅和其他事务流程的事实源；MetaPlanCompiler 不动态改写其内部状态机。
- Runtime 已记录 blocked / replan reason，但当前不会让 LLM 任意生成新 DAG；局部恢复仍受既有 retry、branch 和固定 pattern 约束。

## 验证状态

当前实现对应测试覆盖：

- TaskSpec、Skill、ContextAdmission、CapabilityCoverage、A2A verification gate、MemoryAdmissionGate。
- Entry、Ask、capture confirmation / resume、ReAct、MCP GitHub、MCP Notion、GPT Researcher A2A。
- Workflow validator、step projection、checkpoint、HITL 和 replay。

最近一次核心回归结果：

```text
151 passed
ruff check: passed
python compileall: passed
git diff --check: passed
```

全量 `pytest -q` 在收集 Web 路由测试时仍要求 `PERSONAL_AGENT_POSTGRES_URL`；这是当前测试环境前置条件，不属于元能力运行时失败。

## 代码事实源

| 主题 | 当前事实源 |
| --- | --- |
| 元能力与运行时 contracts | `kernel/contracts/agentic.py`、`kernel/contracts/capability.py` |
| TaskSpec、Skill、pattern 与 plan compilation | `planning/agentic.py` |
| Capability filtering / coverage | `planning/capability_resolver.py`、`planning/capability_validation.py` |
| Memory admission | `planning/memory_admission.py` |
| checkpoint state | `orchestration/orchestration_models.py` |
| 入口编译 | `orchestration/orchestration_nodes/_entry.py` |
| step、ledger、commit、A2A | `orchestration/orchestration_nodes/_steps.py` |
| ReAct、EvidencePack、context admission | `orchestration/orchestration_nodes/_react.py` |
| 固定领域 workflow | `planning/workflow.py` |

