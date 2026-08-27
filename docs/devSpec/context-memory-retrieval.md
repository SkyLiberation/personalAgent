# 上下文、记忆与检索细则（CTX）

> 本细则在任务涉及 Context、Memory、RAG、Artifact、检索、权限过滤、预算物化或 Capability Projection 时生效。通用事实归属见[架构边界与事实归属](architecture-ownership.md)，测试要求见[测试、评估、观测与安全](quality-security.md)。

## 1. Context 的处理顺序

Context 必须依次经过：

1. Visibility：先按权限和 scope 过滤；
2. Requirement Retrieval：按当前需求召回；
3. Semantic Selection：模型选择语义相关内容；
4. Budget Materialization：压缩并注入 LLM Context。

禁止先召回全部内容再让 Prompt 过滤权限。

## 2. 存储边界

- Agent State：保存当前运行所需的结构化状态；
- LLM Context：保存当前模型调用实际可见的内容；
- Checkpoint：保存恢复执行所需的快照；
- Artifact Store：保存大文本、文件和中间产物；
- Long-term Memory：保存跨会话可召回的事实或经验；
- Retrieval Index：保存检索投影，不作为事实权威源。

State 优先保存 `ArtifactRef`，不得复制大型 Artifact。RAG 只负责检索和证据组织，不得成为隐藏的 Router 或 Planner。检索策略必须由数据与评测驱动，禁止为单一 benchmark 硬编码；中间检索指标不能替代最终答案与证据正确性。

## 3. Capability Projection 与服务提供方绑定

Capability definition 由对应 Application owner 管理。模型可见 capability、工具 schema、服务提供方可用性和检索结果都是临时只读投影，必须先经过 visibility 或 policy，再进行 materialize。投影可以帮助模型选择 Application Capability，不能替智能体完成开放语义选择，也不能反向成为定义或可用性事实源。

只有完整满足同一 `CapabilityEquivalenceClass` 的服务提供方才能确定性绑定。存在语义差异时，必须由模型或外部权威选择。
