# 项目介绍与面试讲稿

## 1. 项目是做什么的

personalAgent 不是一个只负责聊天的 Bot，而是一个围绕“个人知识如何进入、被引用、被修正、被复习、被持续研究”的 Agent 系统。

它解决四类用户问题：

1. 用户的资料来自文本、网页、上传文件和历史会话，系统需要形成可追溯的知识，而不是只把原文塞进向量库；
2. 用户提问时，回答需要受 workspace、用户权限和可见证据约束，并给出引用；
3. 保存、删除、恢复、订阅和投递有真实副作用，需要确认、幂等、恢复和审计；
4. 开放式研究无法预先写死全部步骤，需要模型根据搜索结果、Tool Observation 和子 Agent 产物继续决策。

产品能力包括：

- 普通连续对话；
- Workspace 资料采集和有证据问答；
- 对话结论显式固化；
- 知识纠错、删除和恢复；
- Review Card 和知识缺口分析；
- 一次性研究和周期性情报订阅；
- GitHub、Notion MCP 读取；
- GPT Researcher A2A 委托。

## 2. 面试时最先说清楚的架构结论

系统没有把所有请求都包装成一个通用 Task，也没有让一个 Planner 控制全部业务。当前按“路径是否动态”和“是否跨越 durable 边界”分成三条生产主链：

```text
短动态请求
  -> ConversationService Interaction loop
  -> 模型决定直接回答、调用 Tool 或委托 Agent
  -> Observation 返回模型
  -> FinalMessage

固定事务
  -> 明确的 Application Use Case
  -> Domain Command / State Machine
  -> Repository / Worker / Provider
  -> typed result、Receipt 或 terminal state

动态且跨进程、用户轮次或审批边界的长任务
  -> explicit Investigation Project
  -> accepted Plan + deterministic ready set
  -> ToolGateway / durable AgentGateway / synthesis
  -> Verification + Completion Gate
```

“固定事务”指执行拓扑和不变量固定，不是输入必须来自按钮。例如删除知识一旦被接受，就必须依次经过 prepare、confirmation、execute、receipt，不能让模型自由重排。Investigation Project 也不是 Conversation 的隐藏模式；只有 accepted Plan 真正驱动 ready set、coverage、恢复和完成义务时，才承担 durable 调度复杂度。

## 3. 30 秒介绍稿

> 我做的是一个个人知识与持续研究 Agent。它不是传统 RAG Bot：除了检索回答，还支持多来源知识采集、显式保存、知识纠错与删除恢复、周期研究、MCP 和 A2A。架构有三条生产主链：短动态请求进入 Conversation ReAct，固定事务进入 Application Workflow，只有动态路径同时跨越进程、用户轮次或审批边界时才创建 Investigation Project。模型负责开放语义，Runtime 和 Domain 负责权限、状态、幂等、Evidence 与 Completion。历史完整产品/主循环矩阵曾 23/23 通过，但当前 catalog 的完整 clean revision 矩阵尚未重跑；LT01-LT13 也只是 durable runtime 诊断证据，不能据此声称可发布。

## 4. 2 分钟介绍稿

> 这个项目解决的是个人知识从采集到使用再到维护的完整闭环。用户可以导入文本、网页、文件和会话，系统会保存 application-owned Artifact，再形成 EvidenceBlock、Claim 和 KnowledgeItem。问答只读取当前 workspace 可见证据，并给出 citation；Ask 本身不会把模型回答写回长期知识，只有用户显式保存才进入唯一写入口。
>
> Agent 主链是一个 typed Interaction loop。模型每轮返回 `AgentTurnDecision`：要么直接给 `FinalMessage`，要么返回带 ToolCall/AgentDelegation actions 的 `ContinueTurnProposal`。Runtime 只做 schema、能力存在性、scope、预算、重复 action 和并发安全等确定性 Admission，不能替模型补参数或修改目标。Tool 或子 Agent 执行后产生 `ActionObservation`，模型再根据真实结果继续。
>
> 对有外部副作用或需要恢复的操作，我没有机械地把它们当普通 ToolCall。以知识删除为例，系统创建 immutable Command，用一个 command digest 同时绑定确认和 Receipt。错误 digest 被拒绝，重启后可以恢复，replay 返回同一 Receipt，不重复删除；无消费者的 lifecycle Event 和第二个 digest 已被移除。
>
> 当任务既需要根据新 Observation 动态调整，又必须跨进程、用户轮次或审批边界保持完成义务时，用户显式创建 Investigation Project。Project 持久化 immutable definition 和 append-only journal，accepted Plan 驱动 ready set、dispatch、join、coverage 和 Completion Gate；普通 Conversation 不会隐式升级成 Project。
>
> 外部能力通过 MCP 和 A2A Adapter 接入，但 Adapter 只做协议转换。MCP 是否可用由 discovery、Host mapping 和 policy 共同决定；子 Agent completed 也不会自动完成父请求，父 Agent 必须读取 Artifact 后综合答案。
>
> 测试上不是只看对象存在或数据库新增，而是从独立 Web 进程的真实 HTTP 入口，使用真实模型、PostgreSQL 和场景要求的真实 Provider，断言用户结果和反事实。历史 23/23 archive 和当前定向 archive 只能证明对应工程现场可执行；当前完整矩阵尚未重跑。Investigation 的 LT01-LT13 使用生产 Domain、Store 和 Worker，但模型与 Provider 是 scripted/frozen Port，因此只属于诊断证据。当前主要产品缺口仍是多数写操作没有与 Conversation 的 scoped capability 和对话内确认机制贯通。

## 5. 5 分钟白板介绍顺序

### 第一步：画三条生产主链

```text
正式入口
├─ Conversation ReAct
│  └─ 短动态请求
├─ Application Workflow
│  └─ 固定事务与领域状态机
└─ Investigation Project
   └─ 动态且必须 durable 的长任务
```

先解释路由标准：开放问题无法预定义步骤，领域事务不能由模型随意编排；动态任务只有跨越进程、用户轮次或审批边界时，才值得创建 durable Project。

### 第二步：画 Interaction loop

```text
Message
  -> EffectiveCapabilities
  -> AgentTurnDecision
  -> Admission
  -> ToolGateway / AgentGateway
  -> Observation / Feedback
  -> next model turn
  -> FinalMessage
```

强调 Proposal 不是权限，也不是执行事实。

### 第三步：画固定副作用链

```text
Application Capability
  -> immutable Command
  -> Confirmation + Digest
  -> execute once
  -> Receipt
  -> Domain Completion
```

用 delete/replay 举例说明模型可以选择用户级能力，但不能重排事务不变量。

### 第四步：画 Durable Project

```text
immutable Project definition
  -> accepted Plan
  -> deterministic ready set
  -> dispatch / join
  -> Evidence Admission / Verification
  -> Completion Gate
```

强调 GET 只读 projection，恢复不重新生成冻结 Command，Tool/Agent success 也不能单独完成 Project。

### 第五步：画知识事实链

```text
Source
  -> Artifact
  -> EvidenceBlock / EvidenceSpan
  -> Claim
  -> Relation / KnowledgeItem
  -> Retrieval / Graph Projection
```

强调 PostgreSQL Workspace Store 是 canonical fact owner，向量索引和 Graph projection 只是可重建投影。

### 第六步：用 E2E 收尾

```text
E01-E13: 原生产品能力
C01-C04: 组合用户旅程
L01-L06: 复杂 Interaction loop
E16-E19: 真实 Provider profile
LT01-LT13: durable runtime diagnostic
```

说明前四组的 release 分类与 LT 诊断证据不能混用：外部 profile 不能单独冒充产品完成，scripted/frozen LT 也不能冒充 live model/provider 发布证据。

## 6. 为什么不是普通 RAG Bot

普通 RAG Bot 常见路径是：

```text
问题 -> 向量检索 -> 拼 Prompt -> 模型回答
```

本项目还要处理：

- 哪个 workspace、用户和 Artifact 可见；
- 回答依据的 Claim 和 Evidence 是否可追溯；
- Ask 为什么不能隐式写知识；
- 新 Claim 如何 supersede 旧 Claim；
- 删除、恢复和 replay 如何避免重复副作用；
- 外部 Research 是否进入真实终态；
- Delivery 是否 exactly-once；
- MCP unavailable 时为什么必须 fail closed；
- 子 Agent Artifact 为什么不能直接冒充父级最终答案。

因此 RAG 只是其中一个读取能力，不是系统的总架构。

## 7. 项目中最能体现 Agent 工程能力的四个点

### 7.1 决策所有权清晰

模型负责开放语义，确定性代码负责权限、状态机和不变量，执行系统产生事实，Verifier 判断语义满足，领域状态机判断完成。这样既保留 Agent 灵活性，也避免把治理逻辑写进 Prompt。

### 7.2 执行拓扑按业务约束选择

短动态请求不承担 durable Project 成本；固定事务不调用通用 Planner；只有动态路径同时跨越 durable 边界时才创建 Investigation Project。三条主链不是三个同义框架，而是三个不同生命周期和事实 owner。

### 7.3 Observation 驱动而不是一次性脚本

普通 Conversation 不在一开始生成强制计划。Tool 和 Agent 返回 Observation 后，模型直接提出下一步；进程重启时基于已提交事实继续。只有显式 Investigation Project 才拥有驱动 durable 调度的 accepted Plan。

### 7.4 E2E 验证用户结果和反事实

测试不仅断言“成功”，还断言：错误 digest 不执行、Ask 不写 Claim、跨 workspace 不泄漏、预算耗尽不拼替代答案、能力缺失不换 Tool、replay 不重复副作用。

## 8. 介绍时不能说错的边界

不要说：

- 所有用户请求都会创建 Task/GoalGraph；
- LangGraph checkpoint 是当前普通 Conversation 主链；
- Agent 已经可以从自然语言执行全部保存、删除和订阅操作；
- Tool success 就代表用户目标完成；
- Graphiti 或 embedding index 是知识事实源；
- 23/23 通过就代表 clean revision 可发布。

应当说：

- 普通 Conversation 由 `ConversationService` 的 typed Interaction loop 拥有；
- 固定领域流程由各 Application Use Case 拥有；
- Investigation Project 是显式 durable 产品入口，不是 Conversation 的隐藏模式；
- 当前普通 Conversation 只加载 `public_agent` Tool；
- LT01-LT13 是 scripted/frozen Port 的诊断证据，不是 live release evidence；
- 23/23 是 dirty worktree 的工程执行证据，release gate 仍然 fail closed。
