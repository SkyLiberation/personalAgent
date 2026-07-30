# Agent 主循环、Tool 与治理

## 1. 当前 Conversation 主循环

正式链路：

```text
Web / CLI / Feishu
  -> AgentService.converse
  -> AgentRuntime.converse
  -> ConversationService.respond
  -> AgentTurnDecision
  -> ToolExecutor or AgentGateway
  -> ActionObservation / DecisionFeedback
  -> next model turn
  -> FinalMessage
```

`AgentRuntime` 是 Composition Root，负责集中装配模型、Store、Tool、Agent、Policy 和 Application Service。它不是第二事实源，不持久化 Workspace、Research 或 Interaction 的镜像字段。

## 2. 顶层逻辑：模型是决策提议者，Runtime 是协议解释器

这一设计首先解决的不是 JSON 格式，而是“概率模型怎样安全地驱动确定性程序”：

```text
用户自然语言 + committed Observation
  -> 模型完成开放语义判断
  -> 产生 typed Proposal
  -> Runtime 做 Admission
  -> 执行系统产生事实
  -> 事实返回下一轮
```

`AgentTurnDecision` 可以类比编译器 IR：它把“模型认为下一步应该做什么”表达成机器可检查的
中间表示，但它还不是权限、Command 或执行事实。当前 IR 的封闭决策集合是：

```text
AgentTurnDecision
└─ decision
   ├─ FinalMessage
   └─ ContinueTurnProposal
      └─ actions[]
         ├─ ToolCallProposal
         └─ AgentDelegationProposal
```

Runtime 不需要从 `Action:`、`Final Answer:` 等文本控制词猜分支。它只接受两种明确状态：

```text
FinalMessage        -> 结束本次 Interaction
ContinueTurnProposal -> Admission 后执行 Action，再把 Observation 返回模型
```

`FinalMessage` 的 disposition 包括：

- `answer`：已形成用户答案；
- `clarification_required`：缺少必须由用户提供的信息；
- `limitation`：能力、预算或环境不足；
- `failed`：执行失败，不能伪装成成功。

### 为什么当前 wire format 使用 object-root

如果直接把根 Schema 定义成 `FinalMessage | ContinueTurnProposal`，Pydantic 会生成顶层
`anyOf`。terra deployment 在该形态上出现过 schema retry 超时。本项目保留语义 union，但把它
下沉到固定对象的 `decision` 字段：

```json
{
  "type": "object",
  "required": ["decision"],
  "properties": {
    "decision": {
      "anyOf": [
        {"$ref": "#/$defs/FinalMessage"},
        {"$ref": "#/$defs/ContinueTurnProposal"}
      ]
    }
  }
}
```

因此必须分清两个层次：

| 层次 | 当前结论 |
| --- | --- |
| 稳定框架原则 | 模型输出 typed Proposal；Runtime 不解析自然语言控制流；Admission 后才执行 |
| 当前实现选择 | 使用 object-root envelope 兼容已观察 Provider schema 能力 |

将来即使改用 Provider 原生 Tool Calling，第一行仍必须成立；没有同输入 E2E 证明当前 envelope
造成用户失败时，也不会仅为追逐框架潮流替换它。

对应模型：[conversation/models.py](../../src/personal_agent/application/conversation/models.py)。

## 3. EffectiveCapabilities 如何形成

每次 Interaction 从真实 registry 和已装配 Agent profile 构造临时能力集合：

```text
EffectiveToolCapability
  - name
  - description
  - input_schema
  - read_only
  - safely_retryable

EffectiveAgentCapability
  - agent_id
  - description
  - task_types
  - allowed_operations
```

然后对 canonical JSON 计算 revision。Revision 只能证明“本轮模型看到了哪组定义”，不能证明远端 Provider 健康。

当前普通 Conversation 只加载 `public_agent` Tool。`scoped_agent` 和 `workflow_activity` 不自动进入模型上下文。

## 4. 模型如何决策

模型输入包括：

- 当前 Conversation messages；
- EffectiveCapabilities；
- 已提交 `ActionObservation`；
- Admission 返回的 `DecisionFeedback`；
- 剩余 model/tool/agent/token budget。

模型负责：

- 是否直接回答；
- 是否需要工具；
- 选择哪个语义能力；
- Tool 的业务参数 Proposal；
- 是否委托 bounded sub-goal；
- 收到 Observation 后如何修改下一步；
- 如何生成或修订最终答案。

模型不负责：

- 授权；
- scope 校验；
- Command 幂等；
- 状态迁移合法性；
- 声称 Tool 实际成功；
- 仅凭自述宣布领域完成。

## 5. Admission 为什么只能接受或拒绝

Admission 检查：

- action_id 是否重复；
- Tool/Agent 是否存在；
- Tool arguments 是否满足 schema；
- 是否超过调用预算；
- 是否重复委托已返回 Artifact 的 Agent；
- 后续 Agent 委托是否引用已有 Artifact dependency。

非法 Proposal 返回 `DecisionFeedback`，其中说明：

- reason code；
- repairable fields；
- immutable fields；
- required repair；
- disposition。

Admission 不能：

- 为模型补 `note_id`；
- 把错误 Tool 换成相似 Tool；
- 拼接缺失 payload；
- 改写 Goal；
- 在预算耗尽后生成替代答案。

这样保证 Proposal 的语义 owner 仍是模型，而不是藏在 Validator 中的 if/else。

## 6. Tool 执行链

```text
ToolCallProposal
  -> ToolExecutor.validate_interaction_call
  -> Conversation Admission
  -> ToolExecutor.invoke_interaction
  -> ToolGateway.invoke
  -> typed ToolArtifact
  -> ActionObservation
```

`ToolExecutor` 负责：

- registry；
- Tool definition；
- schema validation；
- interaction exposure projection。

`ToolGateway` 负责：

- policy enforcement；
- permission scope；
- risk 和 confirmation metadata；
- idempotency；
- retry/timeout/rate limit；
- execution audit。

Application 依赖 `InteractionToolPort`，不直接依赖 LangChain `BaseTool`、MCP SDK 或具体 Provider。

对应代码：

- [ToolExecutor](../../src/personal_agent/governance/registry.py)
- [ToolGateway](../../src/personal_agent/governance/gateway.py)
- [Tool contracts](../../src/personal_agent/kernel/contracts/tool.py)

## 7. 普通 ToolCall 与 Governed Command 的区别

### 普通 ToolCall

适用于：

- 只读；
- 低风险；
- 可安全重试；
- 不跨审批或恢复边界。

例如读取笔记、查询 ResearchRun、Graph search。

### Governed Command

适用于：

- 需要用户确认；
- 有外部或长期副作用；
- 不可安全重试；
- 需要 durable execution；
- 需要审计和 replay。

例如删除知识、恢复知识、外部投递。

Command 必须 immutable。参数变化不能覆盖原 Command，只能创建 superseding Command。Confirmation、Grant、Journal 和 Receipt 必须绑定 digest 链。

## 8. 安全并发

同一模型轮可以提出多个 action，但只有所有 action 都能机械证明安全并发时才并行。

当前 Tool 并发判定主要根据 governance side effects：只有没有写入、删除等共享副作用的 Tool 才可能进入 bounded thread pool。Agent profile 也必须只允许 delegate/read。

```text
actions = [read_A, read_B]
  -> concurrent batch
  -> wait all observations
  -> next model turn

actions = [write_A, read_B]
  -> serial execution
```

并发只优化执行，不改变 Proposal 顺序、Observation ownership 或最终完成判断。

## 9. Budget 与停止条件

`LoopBudgetPolicy` 限制：

- max model turns；
- max Tool calls；
- max Agent calls；
- max total tokens；
- max concurrency。

预算耗尽时返回：

```text
disposition = limitation
本次交互已达到执行预算上限，未生成替代答案。
```

Runtime 不能把最后一个 Tool Observation 拼成业务答案，因为如何解释 Observation 属于语义决策。

## 10. Conversation 恢复边界

`InteractionTrace` 保存：

- 用户 messages；
- capability revision；
- committed Observation/Feedback；
- usage；
- execution order；
- concurrent batches；
- final message。

`FileInteractionJournal` 只保存 committed facts。进程重启后，模型直接读取 typed inputs
继续决策；恢复不会重复已有 action_id，也不会重新调用模型生成已经冻结的领域 Command。
普通 Conversation 没有强制 Plan，显式 Investigation Project 的 accepted Plan 才驱动
durable ready set 和恢复。

当前限制：普通 Interaction 主要使用文件 Journal，已经证明单进程重启恢复，但尚不是多实例、分布式一致的 session store。

## 11. Investigation Project 的 durable control

普通 Conversation 的恢复目标是“不重复已提交 action，并让模型继续读取 committed inputs”；它没有 durable Plan、ready set 或 required result contract。

Investigation Project 的恢复目标不同：

```text
immutable definition
  -> Planner Proposal
  -> Plan Admission
  -> accepted Plan
  -> deterministic ready set
  -> governed dispatch / join
  -> verified SubGoal outcomes
  -> Completion Gate
```

accepted Plan 是 Project aggregate 的 canonical fact，并被 worker 实际消费。steering 只能修订未冻结 SubGoal；审批、预算、能力缺口和取消都是 typed Project condition。GET 只读取 projection，不借查询推进任务。

因此 Project 不是给 Conversation 增加 checkpoint，而是为动态长任务增加独立 definition、生命周期、恢复和完成所有权。

## 12. Verifier feedback loop

如果任务需要语义验证，模型先调用 `verify_interaction_draft`：

```text
draft
  -> Verifier
  -> needs_revision + feedback
  -> 模型修订
  -> 再次 Verifier
  -> passed + draft_digest + verified_draft
  -> FinalMessage 必须逐字等于 verified_draft
```

Runtime 只验证最终文本 digest 与 passed receipt 是否匹配，不修改模型草稿。

## 13. Execution、Verification 与 Completion

三者必须分开：

```text
Execution Fact
= Tool、Command 或 Agent 实际执行了什么

Semantic Verification
= Answer/Artifact 是否满足证据和语义标准

Domain Completion
= 领域 Aggregate 是否进入合法终态
```

典型反例：

- Tool 返回 `ok=true`，不代表用户问题已经回答；
- GPT Researcher `completed`，不代表父 Agent 已经综合；
- 数据库新增 Claim，不代表保存的是用户授权事实；
- Verifier 认为文本合理，不能推翻 Tool 的真实 failure；
- ResearchRun 仍为 `running`，不能作为成功展示。

## 14. 决策所有权速查

| 问题 | Owner |
| --- | --- |
| 用户想完成什么 | 模型或用户显式产品操作 |
| 是否直接回答 | 模型 |
| 选择哪个 Tool/Agent | 模型 |
| Tool 是否存在 | Registry |
| Proposal schema 是否合法 | Admission |
| durable Plan 是否 accepted、哪些 SubGoal ready | InvestigationProject aggregate / Project Application |
| 是否允许执行 | Policy/Governance |
| Tool 实际返回什么 | Tool/Provider |
| Command 是否已执行 | Journal/Event/Receipt |
| Answer 是否满足证据 | Verifier |
| Aggregate 是否完成 | Domain state machine |
| Project required result contract 是否齐全 | Investigation Completion Gate |
| 是否具备发布证据 | E2E catalog + release gate |
