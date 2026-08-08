# 项目介绍与面试讲稿

本文提供开场讲稿与白板顺序。写法遵守 [面试文档规范](00-writing-spec.md)；深度理解与逐轴举证在
[能力轴](03-capability-axes.md)。与生产代码或 summary 冲突时以后者为准。

## 1. 项目是做什么的

personalAgent 不是一个只负责聊天的 Bot，而是一个围绕「个人知识如何进入、被引用、被修正、
被复习、被持续研究」的 Agent 系统。

它解决四类用户问题：

1. 资料来自文本、网页、上传文件和历史会话，需要形成可追溯的知识，而不是只把原文塞进向量库；
2. 提问时回答需要受 authenticated user scope、资源 ownership 和可见证据约束，并给出引用；
3. 保存、删除、恢复、订阅和投递有真实副作用，需要确认、幂等、恢复和审计；
4. 开放式研究无法预先写死全部步骤，需要模型根据搜索结果、Tool Observation 和子 Agent 产物继续决策。

产品能力：连续对话、个人资料采集与有证据问答、对话结论显式固化、知识纠错/删除/恢复、
Review Card 与知识缺口分析、一次性研究与周期性情报订阅、GitHub/Notion MCP 读取、
GPT Researcher A2A 委托。

## 2. 最先说清楚的一件事：权力边界

项目不是围绕某个模型、JSON 格式或 Agent 框架搭建，而是围绕一条长期稳定的所有权链：

```text
用户目标与上下文
  -> 模型提出 Semantic Proposal
  -> Admission / Policy 接受或拒绝
  -> Gateway / Executor 执行并产生事实
  -> Verifier 判断结果是否有证据支持
  -> Completion Gate 判断用户结果契约是否齐全
```

可以替换的是 object-root JSON、Pydantic、Provider、Tool Calling 协议和编排技术。不能替换的是
下面六条——**每条后面都跟着它阻止的具体故障，这是判断「不是为了设计而设计」的唯一方式**：

| 不变量 | 它阻止的具体故障 |
| --- | --- |
| 模型输出不是授权 | 模型幻觉一个 Tool 名或越权 scope，就直接产生了真实副作用 |
| 模型自述不是执行事实 | 模型说「已保存」但写入从未发生，用户以为存了 |
| Admission 不补业务语义 | 语义 owner 悄悄变成不在 Prompt 里的 if/else，Golden Set 覆盖不到，线上无法归因 |
| Tool success 不代表用户目标完成 | Web Search 返回了结果就宣布问题已回答 |
| canonical fact 只有一个 owner 和一个写入口 | 索引重建失败覆盖业务事实，且无处查证原本是什么 |
| 无 baseline 失败证据的新机制不进强制主链 | 为想象中的问题增加复杂度，撤除成本远高于加入成本 |

这套边界解决的现实矛盾是：知识与研究任务需要模型处理开放语义，但权限、真实副作用、恢复和审计
不能交给概率模型。设计目标**不是消除模型的不确定性**，而是让不确定性只存在于它应该负责的语义层。

## 3. 三条生产主链，不是一个 God Task

系统没有把所有请求包装成通用 Task，也没有让一个 Planner 控制全部业务。按「路径是否动态」和
「是否跨越 durable 边界」分成三条：

```text
短动态请求
  -> ConversationService Interaction loop
  -> 模型决定直接回答 / 调用 Tool / 委托 Agent
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

不合并的理由是具体故障，不是「更清晰」：合并后**直接回答会被迫伪造 Task/Command/
CompletionReport**，而 ResearchRun、DeleteCommand、Delivery、Project 的状态机与恢复语义完全不同，
一个 God Aggregate 装下它们只会让每种恢复都走最保守路径。

两个易被误解的点：

- 「固定事务」指执行拓扑与不变量固定，**不是输入必须来自按钮**。删除一旦被接受就必须依次经过
  prepare、confirmation、execute、receipt，模型不能自由重排；
- Investigation Project **不是 Conversation 的隐藏模式**。只有 accepted Plan 真正驱动 ready set、
  coverage、恢复和完成义务时，才承担 durable 调度成本。

## 4. 30 秒介绍稿

> 我做的是一个个人知识与持续研究 Agent，核心是一套可信 Agent Runtime：模型负责提出开放语义
> Proposal，确定性系统负责 Admission、权限和执行，执行事实再经过 Verification 与 Completion。
> 短动态请求、固定事务和 durable 动态长任务分别进入 Conversation、Application Workflow 和
> Investigation Project。这个边界不是画出来的，是由错误 digest、知识污染、重复副作用、
> Provider 协议失败和 live Investigation repair 等 E2E 反事实撑出来的；当前完整 clean-revision
> 发布矩阵仍未重跑。

## 5. 2 分钟介绍稿

> 项目解决个人知识从采集到使用再到维护的闭环。用户导入文本、网页、文件和会话，系统保存
> application-owned Artifact，再形成 EvidenceBlock、Claim 和 KnowledgeItem。问答只读取当前
> authenticated user scope 内的可见证据并给出 citation；Ask 本身不会把模型回答写回长期知识，只有用户显式保存才进入
> 唯一写入口——这条是为了阻断「模型输出在下一轮变成系统已知事实」的污染循环。
>
> Agent 主链不是「自然语言转 JSON」。模型每轮产生一个 typed Proposal：`FinalMessage`，或带
> ToolCall/AgentDelegation 的 `ContinueTurnProposal`。Runtime 只做 schema、能力存在性、scope、
> 预算、重复 action 和并发安全等确定性 Admission，不替模型补参数或改目标。Tool 或子 Agent 执行后
> 产生 `ActionObservation`，模型再根据真实结果继续。JSON 是当前 wire format，Proposal 与执行事实
> 分离才是稳定框架。
>
> 有外部副作用或需要恢复的操作没有当成普通 ToolCall。以知识删除为例，系统创建 immutable
> Command，用一个 command digest 同时绑定确认和 Receipt。错误 digest 被拒绝，重启后可恢复，
> replay 返回同一 Receipt 不重复删除。这里也做过删减：无消费者的 lifecycle Event 和第二个 digest
> 已被移除。
>
> 任务既需要根据新 Observation 调整、又必须跨交互或审批边界保持完成义务时，模型可以从普通
> Conversation 提出 durable investigation。它调用同一 Project Application Service，只把
> ProjectReference 留在 Interaction；Project 自己持久化 definition、journal 和 accepted Plan，驱动
> ready set、dispatch、join、coverage 和 Completion Gate。短任务不会因此承担 Project 成本。
>
> 外部能力通过 MCP 和 A2A Adapter 接入，Adapter 只做协议转换。MCP 是否可用由 discovery、Host
> mapping 和 policy 共同决定；子 Agent completed 也不会自动完成父请求。
>
> 测试上不看对象存在或数据库新增，而是从独立 Web 进程的真实 HTTP 入口，用真实模型、PostgreSQL
> 和场景要求的真实 Provider，断言用户结果和反事实。历史 23/23 与当前定向 archive 只证明对应工程
> 现场可执行；完整矩阵尚未在 clean revision 重跑，release gate 按设计 fail closed。

## 6. 5 分钟白板顺序

### 第一步：一套目标入口与内部责任链

```text
普通用户目标 -> Conversation semantic decision
├─ request-local capability        短动态请求
├─ concrete Application Use Case   固定事务与领域状态机
└─ Project handoff                  动态且必须 durable 的长任务
```

先讲路由标准：开放问题无法预定义步骤；领域事务不能由模型随意编排；动态任务只有跨越进程、
用户轮次或审批边界时才值得创建 durable Project。

### 第二步：Interaction loop

```text
Message -> EffectiveCapabilities -> AgentTurnDecision -> Admission
  -> ToolGateway / AgentGateway -> Observation / Feedback -> next model turn -> FinalMessage
```

强调 Proposal 既不是权限也不是执行事实。

### 第三步：固定副作用链

```text
Application Capability -> immutable Command -> Confirmation + Digest
  -> execute once -> Receipt -> Domain Completion
```

用 delete/replay 说明模型可以选择用户级能力，但不能重排事务不变量。

### 第四步：Durable Project

```text
immutable definition -> accepted Plan -> deterministic ready set
  -> dispatch / join -> Evidence Admission / Verification -> Completion Gate
```

强调 GET 只读 projection（否则用户刷新页面就推进了任务）、恢复不重新生成冻结 Command、
Tool/Agent success 不能单独完成 Project。

### 第五步：知识事实链

```text
Source -> Artifact -> EvidenceBlock/EvidenceSpan -> Claim -> Relation/KnowledgeItem
  -> Retrieval / Graph Projection
```

强调代码中名为 `PostgresKnowledgeStore` 的知识 Store 是 canonical fact owner；这个历史模块名不证明
Personal Knowledge 是用户可见 Product Aggregate。向量索引与 Graph projection 是可重建投影。

### 第六步：用证据收尾

```text
E01-E05/E08-E14/E20/IP01   应用能力          release evidence
L01-L06                    复杂 Interaction  release evidence
E16-E19/E21                真实 Profile      diagnostic，不单独产生发布声明
LT01-LT08/LT10-LT13        durable runtime   diagnostic，scripted/frozen Port
```

说明外部 profile 不能冒充产品完成，scripted LT 也不能冒充 live release 证据。

## 7. 为什么不是普通 RAG Bot

普通 RAG Bot 的路径是 `问题 -> 向量检索 -> 拼 Prompt -> 回答`。本项目还必须处理：哪个
tenant/principal/Artifact 可见；回答依据的 Claim 与 Evidence 是否可追溯；Ask 为什么不能隐式写知识；
新 Claim 如何 supersede 旧 Claim；删除/恢复/replay 如何避免重复副作用；外部 Research 是否进入真实
终态；Delivery 是否 exactly-once；MCP unavailable 时为什么必须 fail closed；子 Agent Artifact 为什么
不能冒充父级最终答案。

所以 RAG 只是其中一个读取能力，不是总架构。

## 8. 最能体现工程判断力的四个点

选这四个而不是罗列亮点，因为它们各自对应一个**做过的取舍**，面试官追问时有下文。

1. **决策所有权清晰**：模型负责开放语义，确定性代码负责权限、状态机和不变量，执行系统产生事实，
   Verifier 判断语义满足，领域状态机判断完成。既保留灵活性，也避免把治理逻辑写进 Prompt。
2. **入口统一、事实 owner 不合并**：用户只描述目标；短请求不承担 durable 成本，固定事务不调用
   通用 Planner，Project 状态不复制进 Conversation。
3. **做过删除而不只是添加**：旧 `WorkingPlanSnapshot` 只进 Prompt/Trace，没有任何生产调度消费者，
   却增加首次 action 和恢复的模型轮次——所以删掉了。能讲清删掉了什么，比列了多少机制更有说服力。
4. **E2E 断言反事实**：错误 digest 不执行、Ask 不写 Claim、跨用户随机事实不泄漏、预算耗尽不拼替代
   答案、能力缺失不换 Tool、replay 不重复副作用。正向结果容易蒙对，反事实很难。

详细举证见 [能力轴](03-capability-axes.md)，证据口径见 [证据与发布](05-evidence-and-release.md)。
