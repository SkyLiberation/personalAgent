# 领域设计：知识、研究与动态调查

> **领域边界按“谁拥有长期事实和生命周期”划分，而不是按存储技术、Tool 名或任务时长划分。** Knowledge、ResearchRun 和 InvestigationProject 不能被一个通用 Task 抹平，向量库、MCP 和 Agent 也不能成为业务事实源。

## 1. 知识事实链不是 Document + Embedding

```text
Source -> Artifact -> EvidenceBlock / EvidenceSpan -> Claim -> Relation / KnowledgeItem
                                                        |
                                                        -> Retrieval / Graph projection
```

| 对象 | 权威事实 | 不拥有 |
| --- | --- | --- |
| Artifact | 原始/规范化资源及引用 | 内容一定为真 |
| EvidenceBlock/Span | 支撑位置与 provenance | Claim 生命周期 |
| Claim | 可维护陈述与 active/superseded/deleted 状态 | 检索排名 |
| Relation/KnowledgeItem | 支持、冲突、取代和产品读取结构 | 原始资源正文 |
| Retrieval/Graph projection | 可重建召回视图 | 业务事实和写入口 |

一次索引失败只能影响召回，不能覆盖 Claim。引用必须回到实际 Evidence，而不是只返回相似 chunk id。

## 2. 一个事实一个 owner

| 事实 | owner / 唯一写入口 |
| --- | --- |
| Artifact | ArtifactService + Artifact Store |
| Evidence / Claim | KnowledgeService ingestion transaction |
| Conversation committed inputs / ProjectReference | ConversationService + Interaction journal |
| Delete/Restore Command、Event、Receipt | KnowledgeLifecycleService |
| Subscription、ResearchRun、Digest、Delivery | ResearchService |
| Project definition、Plan、SubGoal、Completion | InvestigationProject aggregate + service |
| Tool policy、idempotency、audit | ToolGateway governance store |
| Child run 与 AgentArtifact | AgentGateway |

UI View、Trace、Capability projection、向量索引和 Graph 都是读取投影，不得成为第二写入口。

## 3. Context、Journal、Artifact 和 Memory 不能合并

| 存储 | 目的 | 失效/恢复边界 |
| --- | --- | --- |
| LLM Context | 当前模型调用可见输入 | 可裁剪、压缩和重建 |
| Interaction Journal | 恢复 Conversation committed facts | 不重复已提交 action |
| Artifact Store | 保存大内容与中间产物 | 通过 scoped ResourceRef 读取 |
| Long-term Knowledge | 跨会话可维护事实 | 只能走 Knowledge 写入口 |
| Retrieval Index | 高效生成候选 | 可从权威事实重建 |

结构相似不代表生命周期相同。把它们合成 God State 会让 Context 摘要、运行恢复和长期事实互相污染。

## 4. Grounded answer 是只读证据链

```text
authenticated principal + question
  -> visible knowledge
  -> bounded personal evidence Observation
  -> optional Tool/MCP observations
  -> answer generation
  -> grounding/conflict verification
  -> one Conversation FinalMessage
```

**最终回答由 Conversation 拥有，Knowledge 拥有 evidence/claim 语义。** `ASK-001A` 覆盖 personal-only 冲突证据，`ASK-001B` 覆盖 personal + official web；两者都断言不写 Claim、不跨 principal。当前只证明 principal ownership，不外推 workspace/membership/role Aggregate。

## 5. 写入首要目标是防污染

**保存、纠错和删除分别使用与其来源、生命周期和恢复边界匹配的写入口，不从模型回答直接派生长期事实。**

### 显式保存

Ask 默认零写入。Save 需要明确意图、user-authored exact span、来源索引和必要确认；assistant candidate 包含推断与生成措辞，当前不是已准入长期知识来源。

### 纠错

```text
old Claim(active) -> old Claim(superseded)
new Claim(active) -> Relation(supersedes/conflicts) -> old Claim
```

不覆盖旧 Claim，才能保留“原来是什么、谁在何时更正、为什么新旧冲突”的 provenance，同时让默认检索只选择 active facts。

### 删除与恢复

DeleteCommand 和 RestoreCommand 是两个 immutable 动作；prepare 零副作用，Confirmation 绑定服务端冻结 payload，相同 digest replay 返回已有 Receipt。只有确认、幂等和跨请求恢复消费者存在，才值得创建 Command/Receipt。

## 6. Review 与 Maintenance 只消费知识事实

- Review 生成 ReviewCard、记录用户反馈并更新 schedule projection；
- Maintenance 产生 conflict/orphan/backlink 候选并引用 source Claim；
- 二者都不能绕过 KnowledgeService 直接改写 Claim。

它们共享 Knowledge 读取模型，不拥有第二套知识权威事实。

## 7. ResearchRun 适合固定结果契约

```text
Subscription -> Scheduler -> ResearchRun -> Digest -> Delivery -> Feedback
```

Subscription 定义计划，ResearchRun 保存单次执行状态，Delivery 保存幂等投递事实。模型和 Web Provider 可以参与检索总结，但领域状态迁移、来源要求、partial/limitation 和 exactly-once delivery 由 Research Application 决定。修改订阅不能篡改历史 Run，Feedback 必须关联同一 Subscription/Run。

## 8. InvestigationProject 适合动态 durable facts

| 维度 | ResearchRun | InvestigationProject |
| --- | --- | --- |
| 目标 | 稳定研究/摘要契约 | 显式 required result 的开放调查 |
| 编排 | 固定 pipeline/state machine | Observation 驱动 accepted Plan/ready set |
| 用户控制 | Run/Subscription 操作 | steering、pause/cancel、progress |
| 恢复 | run state、Digest、Delivery | Plan、journal、submission key、evidence |
| 完成 | Digest/Delivery 领域终态 | Verification + CompletionReport |

Project 的区分标准不是“运行很久”，而是动态依赖和独立长期业务事实。Conversation 只保存 ProjectReference；读取 projection 不推进状态，steering 走 Project 唯一写入口。普通请求已有路径能满足时，不能因为框架支持 durable graph 就迁入 Project。

## 9. MCP 与 A2A 只拥有执行事实

- MCP discovery/schema 不定义 Claim、Subscription 或 Project 状态；
- A2A completed 只表示 child run 终止，不表示父 Goal 完成；
- Adapter 只转换协议，不补业务 payload、不绕过 Policy、不把远端状态写成领域终态。

## 10. 只持久化不能安全重建的事实

**持久化的判据是存在恢复、审计或幂等消费者，而不是对象看起来重要。** immutable Command、Receipt、accepted Plan、Delivery fact 和 Claim 需要保存；Context projection、ready set、检索排名和模型可见 capability projection 能从权威事实重建，不应成为第二事实源。

通用 Context、HITL、预算和恢复机制见[能力设计](03-capability-axes.md)，证据边界见[证据与发布](05-evidence-and-release.md)。
