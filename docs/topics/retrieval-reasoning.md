# Retrieval 与证据推理

本文拥有检索资源与回答责任的边界。个人知识、图谱和网页读取提供证据；当前产品最终回答由 Conversation 唯一拥有，写入与生命周期由对应 Application 管理。

## 当前产品路径

```text
中文用户目标
  -> Conversation 模型选择所需资料
  -> search_personal_knowledge 或受治理只读工具
  -> 按身份与作用域执行读取
  -> bounded Observation 与可引用原文
  -> 研究任务按 claims 核验、覆盖和独立汇总
  -> 唯一 FinalMessage
  -> 适用的 Verification 与 Completion
```

个人资料通过 `ConversationKnowledgeReadPort.select_personal_evidence()` 进入，真实适配器复用 `KnowledgeService.select_evidence()`。它按责任主体、相关性、生命周期和支持状态选择 Claim，再恢复对应原文与冲突关系。事实与读写契约见 [Memory](memory.md)，产品链路与检查点见 [Capture 与 Conversation Grounded Answer](../workflow/capture-ask-model-flow.md)。

外部资料由模型选择 `web_search` 发现、`web_read` 读取，长正文通过 Artifact 搜索和重读。搜索摘要、已返回正文、未读部分及查询执行条件分别物化；坐标和读取覆盖由 [Context](context-engineering.md#查询执行事实与来源证据)拥有。

## 检索资源契约

| 资源 | 执行结果与消费者 |
| --- | --- |
| Personal Knowledge | 可回答 Claim、原文 citation、支持与冲突事实；经只读端口进入 Conversation |
| 本地笔记与结构检索 | 当前用户可见的 Note、chunk 或章节候选；具体 Application 按自身读取契约消费 |
| Graph | `GraphRetrievalResult` 中的实体、关系、来源和 citation 引用；`graph_search` 工具归一为 evidence |
| Web | 搜索发现结果及指定 URL 的实际提取正文；经 Gateway 返回 Conversation |

`graph_result_to_evidence()` 在 [kernel/evidence.py](../../src/personal_agent/kernel/evidence.py)定义，生产 [graph_search.py](../../src/personal_agent/tools/graph_search.py)复用它。该转换保存事实与来源绑定，不生成答案。

## Graph 边界

`GraphRetrievalResult` 由 [kernel/graph_results.py](../../src/personal_agent/kernel/graph_results.py)拥有，包含实体、关系、node/edge/fact 引用、episode 和 citation，以及 `enabled/error` 环境事实。自然语言合成答案不属于该契约；`relation_facts` 来自实际检索结果，不能从服务提供方答案拆句制造。

旧 Microsoft GraphRAG CLI Adapter 因只返回合成答案、缺少所需来源绑定而删除。决定与历史反事实见 [ADR 0012](../adr/0012-graph-retrieval-evidence-only-boundary.md)。

## Evidence Engine 与离线策略

[Evidence Engine](../workflow/evidence-engine.md)提供证据归一、装配和 grounding 组件，周期 Research digest 有真实消费者。Open RAGBench、MultiHopRAG 等评测检索、融合、重排及证据选择；离线策略的 `ContextPack` 或 scorer 结果只证明其组件边界。

当前 Conversation 不运行独立 Ask workflow，也不把多源候选自动串成第二个答案服务。历史 `current_runtime_ask` 结果保留原代码和配置身份；运行方式与证据分类见[评测索引](../evals/README.md)，不得用历史组件得分推导当前产品结果。

## 失败与完成

服务未配置、不可达或读取失败形成明确失败事实；过滤后没有候选就是空候选。模型依据实际资料判断补证、修订、澄清或限制，有范围的未知按原用户结果契约验收。无据声明由来源支持核验处理；来源、坐标或身份越界由确定性准入拒绝。

检索命中、工具成功和非空 `ContextPack` 都不表示用户目标完成。Verification、Completion 及研究阶段的当前实例见[核验专题](verification-and-completion.md)，实际用户结果由[评测盘点](../evals/02-current-case-inventory.md)维护。
