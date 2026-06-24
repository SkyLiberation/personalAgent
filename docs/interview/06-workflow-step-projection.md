# Workflow / Step Projection 层

### 1. 当前所谓 planning 是怎么落地的？

当前所谓 planning 已经收敛为 **Workflow / Step Projection Layer**，不是开放式自主 planner。
ask、capture、summarize、direct answer、delete 和 solidify 的固定拓扑都下沉为声明式
`WorkflowSpec / WorkflowStepSpec`，由 `WorkflowPlanner` 确定性编译成 `ExecutionStep`。

所有已识别 Goal 都进入同一个步骤执行图。父图只保留 `direct_answer_branch` 作为 Router 不可用、
无 Goal 或投影校验失败时的 fallback，不再为 capture、ask、summarize 维护平行执行路径。

这个判断很重要：如果面试官追问“这些步骤不都是固定的吗”，应该坦诚回答“是的，固定流程就是系统维护的 WorkflowSpec，不让 LLM 自由发明控制流”。这样比强行包装成通用 planner 更可信。

### 2. WorkflowSpec / WorkflowRegistry 解决了什么？

它把“流程拓扑”和“局部语义判断”拆开。

当前执行链路是：

```text
Router 识别 intent
  -> WorkflowRegistry 选择 WorkflowSpec
  -> projection_policy="step_projection" 时 WorkflowStepProjector 确定性投影 ExecutionStep
  -> StepProjectionValidator 校验步骤结构、依赖、工具和风险
  -> LangGraph 步骤执行图推进 StepRunState
  -> ToolGateway / PolicyEngine / HITL 执行副作用
  -> DecisionNode 只处理局部 LLM 语义判断
```

几个关键点：

- `WorkflowSpec` 是业务流程真源，`WorkflowStepSpec` 定义固定节点、步骤依赖、LLM decision node、工具、风险等级、副作用、HITL、恢复策略，以及分支控制字段 `branch_policy` 和 `conditional_edges`（用于 human_select / clarify / abort 这类条件跳转，target 可为 `END / clarify / abort` 哨兵）。
- `WorkflowRegistry` 负责按 intent 选择 spec，避免 LLM 临场设计流程。
- `WorkflowStepProjector` 的职责不是重新规划 workflow，而是对需要步骤执行的 workflow 做确定性 step projection。
- LLM 只在执行期真正需要语义判断的节点出现，例如 query understanding、删除候选选择、solidify 草稿、evidence rerank、低风险 ReAct 检索。
- 真正 autonomous planner 只作为未来能力，用于无法映射到已有 workflow、需要多个低风险工具组合、且有 eval 和 guardrail 覆盖的开放式任务。

这样更符合生产 Agent 的常见取舍：确定流程用 workflow，不确定局部用 LLM decision node，开放式 planner 只在确实需要时启用。

### 3. Step projection 和普通 Todo list 的区别是什么？

普通 Todo list 只是自然语言步骤，本身不参与系统执行。项目里的 step projection 更准确地说是**步骤化编排视图**：它不独占校验、恢复和审计能力，而是把这些能力接到同一个执行流程里。

具体来说：

- Step projection 负责把需要步骤执行的 `WorkflowStepSpec` 确定性投影成结构化 `ExecutionStep`，表达步骤类型、依赖关系、工具意图、风险等级和失败策略，并保留 `workflow_id / workflow_version / workflow_step_id / projection_kind` 来源字段。
- 执行期把 `ExecutionStep` 转成 `StepRunState`，把每一步状态和结果放进 `AgentGraphState.step_execution`。
- 校验分两层：① **spec 契约层**由 `WorkflowSpecValidator`（`workflow_validator.py`）在声明期校验 WorkflowSpec 自洽性（step_id 唯一、依赖可解析无环、conditional_edges target 合法、projection_policy 枚举、delete_longterm 必须 high+confirmation+hitl 等不变式），并由 `validate_registry_against_capabilities` 做 spec↔真实工具能力的一致性闸门；② **运行时投影层**由 `StepProjectionValidator`（当前兼容入口仍叫 `StepProjectionValidator`）校验投影出的 `ExecutionStep` 结构、依赖图和 intent 规则；工具参数、风险治理和执行策略则依赖工具层的 args schema、`ToolGovernance`、`PolicyEngine` 和 `ToolGateway`。
- 可恢复能力来自 LangGraph checkpoint；step projection 的作用是把 step status、`step_execution.results`、pending step 和依赖关系保存成 checkpoint-safe 状态，让恢复后知道从哪一步继续。
- 审计和事件也不是 step projection 独有，工具调用审计来自工具层，运行事件来自 `AgentEvent`；step projection 负责把 `steps_projected / step_started / step_completed / step_failed` 等步骤事件串起来。

所以更准确的表述是：这里不是自主 planning 层单独实现所有安全能力，而是把 workflow 的关键步骤投影成可被工具层校验、可被 checkpoint 恢复、可被事件系统观察的步骤图。它的价值是“组织和约束执行顺序”，不是替代 PolicyEngine、ToolGateway、checkpoint 或审计系统。

### 4. 哪些任务会进入 step projection？哪些不会？

当前所有已识别 intent 都进入 step projection。`WorkflowSpec` 里 `capture_text / capture_link / capture_file`、`ask`、`summarize_thread`、`direct_answer`、`delete_knowledge`、`solidify_conversation` 全部声明 `projection_policy="step_projection"`，由 deterministic projector 投影成 `ExecutionStep` 进入同一个步骤执行图。只有 `unknown`（`projection_policy="none"`）以及投影/校验失败的场景才落到 fallback branch。

这样做的目的是让所有业务流程共用同一套执行壳：`ExecutionStep / StepRunState / StepProjectionValidator / step_execution.results / HITL / step events / checkpoint resume`，避免 WorkflowSpec 和并行 branch 函数成为两个行为事实源。轻量流程（如 `capture_text` 的单步、`summarize_thread` 的 `sum-compose`）步骤数少，UI 可折叠展示，并不会因为统一投影而被过度步骤化。

不同 intent 的差异在于步骤数量和风险，而不是“走不走 step projection”。`delete_knowledge` 和 `solidify_conversation` 是其中“多步、含高风险副作用、需要 HITL”的代表，主干由 `WorkflowSpec` 固定声明：

```text
delete_knowledge: retrieve -> resolve -> delete_note -> compose
solidify_conversation: compose -> capture_text
```

需要注意的是，这里不是完全开放式的自主规划，而是已经落地的 **intent-specific workflow step projection**：固定 workflow 已经下沉为 `WorkflowSpec`，由 deterministic projector 投影成可执行步骤，而不是让模型随意设计流程。

面试里可以坦诚讲：这不是“通用自主 planner 已经成熟”，而是“固定 workflow 已经下沉为 WorkflowSpec，统一通过 deterministic projector 投影成可校验、可观察、可恢复的步骤图”。如果继续生产化，可以进一步扩展到选择 workflow、填充目标、解释步骤，或在有 eval 和 guardrail 的低风险场景生成局部检索子步骤。

### 5. `delete_knowledge` 为什么是 `retrieve -> resolve -> delete_note -> compose`？

删除的关键风险是目标不明确。`retrieve` 先找候选线索，比如 graph episode uuid；`resolve` 再把线索映射成本地真实 `note_id`；`delete_note` 首次调用只生成确认 payload，用户确认后才执行软删除并写入删除快照；`compose` 最后生成用户可见结果。

这个流程保证删除不是 LLM 或 projector 直接拍脑袋决定，而是先从真实知识库候选中解析目标，再通过 HITL 执行。

### 6. 为什么 `delete_note.note_id` 不能由模型或投影阶段直接填？

因为 `note_id` 如果来自模型生成，可能被编造、误解用户指代或选错对象。`note_id` 必须来自运行时 `resolve` 步骤，从 graph episode 映射或本地 note 候选中选择。

后续 `delete_note.tool_input.note_id` 通过 `step_execution.results` 动态注入，避免把模型臆造参数直接传给高风险工具。

### 7. `resolve` 如何防止 LLM 编造 note id？

`resolve` 给 LLM 的输入只包含已有候选的 `note_id / title / summary`，要求它只能从候选 ID 中选择；不确定或多候选时返回 null。系统不接受 LLM 生成的新 ID。

如果图谱 episode 能映射回 note，就优先用真实映射；如果仍然没有明确候选，就失败并要求用户提供更具体描述。

### 8. `StepProjectionValidator` 具体防住了什么？

它会检查步骤类型是否合法、依赖是否存在、依赖图是否有环、工具是否注册、工具参数是否满足 args schema、风险等级和失败策略是否合法、ReAct 是否越权调用高风险工具，以及 intent 特定规则是否满足。

比如 `delete_knowledge` 必须包含 `delete_note`，且 `delete_note` 必须依赖 `resolve`；`solidify_conversation` 的 `capture_text` 必须依赖 `compose`。校验不通过就不会执行危险工具。

### 9. `ExecutionStep` 和 `StepRunState` 区别是什么？

`WorkflowStepSpec` 是 workflow 源契约，描述固定节点、依赖、decision node、工具、副作用、HITL 和恢复策略。`ExecutionStep` 是需要步骤执行的 `WorkflowStepSpec` 经 deterministic projector 投影后的运行时步骤视图，并携带 workflow 来源字段。`StepRunState` 是进入 LangGraph 后的 checkpoint-safe 执行状态，描述做到了哪里、是否失败、重试几次、结果是什么。

一个偏静态计划，一个偏 checkpoint 中的可恢复运行现场。

### 10. ReAct 能不能替代 step projection？

不能。ReAct 是单步内部的探索策略，适合低风险只读检索。Step projection 是跨步骤的编排和恢复机制，负责依赖、状态、HITL 和高风险流程。

项目刻意把 ReAct 限制为 step projection 中的局部能力，而不是让它替代步骤执行器。

---

[← 返回索引 INDEX.md](INDEX.md)
