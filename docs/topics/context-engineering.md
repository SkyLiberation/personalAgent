# Context 工程

本文是当前模型上下文收集、过滤和物化规则的 canonical 文档。Context 是一次模型调用的受控输入，
不是新的事实库，也不是覆盖 Conversation、Workspace 和 Project 的共享状态对象。

## 四阶段协议

```text
1. Visibility
2. Requirement Retrieval
3. Semantic Selection
4. Budget Materialization
```

### Visibility

入口解析 authenticated principal 和 tenant/workspace/user/thread/task scope。Repository、Tool、
Artifact、Memory 和 Retrieval Adapter 必须先按 scope 过滤；禁止先取回全部内容再让 Prompt 隐藏
不可见数据。

### Requirement Retrieval

Application 根据当前用户目标调用明确能力：

- Conversation 历史：读取 committed message/observation；
- Workspace/local：检索可见 Artifact、EvidenceSpan、Claim 或 Note；
- Graph：检索 fact、edge、episode 和 citation ref；
- Web/Tool：只经过 Policy/Gateway 获取当前执行结果；
- Investigation：读取 Project definition、accepted plan、journal 和 ArtifactRef。

该阶段只产生候选和执行事实，不生成业务答案。

### Semantic Selection

开放世界的相关性、冲突表达和回答重点由模型或领域语义组件判断。确定性 Admission 只检查候选是否
来自本次可见集合、ref 是否存在、scope 是否一致和预算是否满足，不补造 evidence 或改写用户目标。

### Budget Materialization

候选统一为 typed context item，经去重、排序、压缩和字符/token 预算形成 ContextPack。大对象以
ArtifactRef 或 source span 读取必要片段，不复制进 runtime state。最终 Prompt 只包含本次模型调用
真正可见的内容。

## Conversation 上下文

Conversation 的短期事实由 Interaction journal 持有：

```text
committed user/assistant messages
+ accepted ActionObservation / DecisionFeedback
+ current usage and action order
-> bounded model context
```

历史 assistant reply 只用于指代和会话连续性，不能作为事实证据。Tool/Agent observation 必须保留
typed status、artifact/receipt ref 和错误分类；不能只压成一段无法区分来源的自然语言。

普通 Conversation 不创建 `TaskContract`、`GoalGraph` 或通用 checkpoint。需要跨进程维护动态
交付义务的 Investigation Project 使用自己的 aggregate 和 journal，不把 Project state 镜像回
Conversation。

## Ask 上下文

Ask 的 retrieval stage 将 workspace、local、graph 和 web 候选归一为 `EvidenceItem`。Evidence
Engine 负责 canonical 去重、融合、rerank 和 ContextPack；compose 只读取物化后的证据，Ask
Verifier 再判断候选答案是否被证据支持。

```text
Question + visible conversation hints
  -> Query understanding
  -> source retrievers
  -> EvidenceItem pool
  -> ContextPack
  -> candidate answer
  -> verification / bounded repair
```

`WorkspaceRetriever` 只调用 evidence selection；Graph provider 只返回
`GraphRetrievalResult`。任何 retriever 都不能在内部生成一个候选答案再伪装成 evidence。

## 上下文腐化防护

- assistant 历史、provider answer、trace text 和 model self-report 不成为 evidence；
- visibility 在 retrieval 前执行；
- ContextPack 的 item 必须能回指 canonical source 或 execution fact；
- verifier 只能引用本次 admitted evidence；
- repair 使用原 Goal、当前候选和 typed verification feedback，不修改权限或 Command；
- summary 只能是非权威的上下文压缩视图，不能覆盖原消息或 Claim；
- Prompt 不承担授权、唯一性、幂等和状态迁移。

## 持久化规则

只在恢复、审计、重放、授权边界或长生命周期一致性要求下持久化上下文来源。可从 canonical facts
确定性重建的 ContextPack、排序分数和压缩文本默认不持久化为第二事实源。

| 数据 | 是否持久化 | 原因 |
| --- | --- | --- |
| Interaction committed input | 是 | Conversation 恢复与审计 |
| Workspace Claim/EvidenceSpan | 是 | 长期知识事实 |
| Project journal/ArtifactRef | 是 | durable execution |
| Retrieval candidate pool | 默认否 | 可重建的单次运行视图 |
| LLM Context/Prompt | 默认否 | 临时物化；必要时只保存 digest/ref |
| embedding / graph index | 可持久化投影 | 可失效并从 canonical source 重建 |

Memory 生命周期和事实 owner 见 [Memory 与知识事实边界](memory.md)；验证后的关闭条件见
[Verification 与 Completion](verification-and-completion.md)。
