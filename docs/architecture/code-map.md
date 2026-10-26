# 代码地图与依赖

> 2026-10-16 按源码、装配与静态导入核对。本文用于定位修改范围；系统信息流见[当前核心架构](core-architecture-current-state.md)，架构约束由 [ARC](../devSpec/architecture-ownership.md)拥有。

## 1. 逻辑角色与实际包

架构角色按事实与责任划分，Python 包按当前代码布局解释。一个角色可能由多个包协作实现，目录名称不证明已经满足全部分层规则。

下表路径均相对 [`src/personal_agent/`](../../src/personal_agent/)。

| 包 | 当前实现与阅读入口 | 修改时的边界 |
| --- | --- | --- |
| `adapters` | [CLI](../../src/personal_agent/adapters/cli/main.py)、[Web](../../src/personal_agent/adapters/web/api.py)、[飞书](../../src/personal_agent/adapters/feishu/service.py) | 传输、认证、输入转换；业务动作复用 Application 入口 |
| `orchestration` | [AgentService](../../src/personal_agent/orchestration/service.py)、[AgentRuntime](../../src/personal_agent/orchestration/runtime.py)、[worker](../../src/personal_agent/orchestration/worker.py) | 外观、依赖装配和现有协调逻辑；新增独立业务规则归业务模块 |
| `application` | [Conversation](../../src/personal_agent/application/conversation/service.py)、[Knowledge](../../src/personal_agent/application/knowledge/service.py)、[Research](../../src/personal_agent/application/research/service.py) 等 | 用例、领域语义与结果契约；详细功能定位见下表 |
| `domain` | [`__init__.py`](../../src/personal_agent/domain/__init__.py) 仅含包声明 | 目前没有独立领域实现；不能为补齐图形新增空壳模型或复制业务事实 |
| `capabilities` | [定义](../../src/personal_agent/capabilities/definitions.py)、[投影解析](../../src/personal_agent/capabilities/resolver.py)、[模型准入](../../src/personal_agent/capabilities/model_resolution.py)、[contracts](../../src/personal_agent/capabilities/contracts/) | 跨业务协议、准入与只读能力投影；业务能力语义归 Application |
| `execution` | [invocation](../../src/personal_agent/execution/contracts/invocation.py)、[journal](../../src/personal_agent/execution/contracts/journal.py) | 当前主要提供调用与执行日志契约，不是一个独立通用执行引擎 |
| `runtime` | [ProcedureRuntime](../../src/personal_agent/runtime/procedure_runtime.py)、[运行管理原语](../../src/personal_agent/runtime/run_manager.py) | 固定程序物化、运行和 lease 等技术协议；是否用于某入口须核对装配与消费者 |
| `governance` | [ToolExecutor](../../src/personal_agent/governance/gateway.py)、[PolicyEngine](../../src/personal_agent/governance/policy/engine.py) | 工具执行准入、授权、限流、幂等与审计；不补业务语义 |
| `tools` | [业务工具工厂及外部工具](../../src/personal_agent/tools/) | 工具定义和执行适配，复用业务用例及受治理网关 |
| `agents` | [AgentGateway](../../src/personal_agent/agents/gateway.py)、[GPT Researcher Adapter](../../src/personal_agent/agents/gpt_researcher_a2a.py) | 委派、submission、子运行状态及服务方协议；父级仍拥有目标验收 |
| `planning` | [StepProjectionValidator](../../src/personal_agent/planning/step_projection_validator.py) | 步骤投影校验；当前 Conversation 工作清单位于其 Application 内 |
| `memory` | [MemoryFacade](../../src/personal_agent/memory/facade.py)、[Graphiti](../../src/personal_agent/memory/graphiti/store.py)、[结构检索](../../src/personal_agent/memory/structural_retriever/store.py) | 记忆访问、可见性及检索；本包也包含具体服务方实现，不能视作纯 Domain |
| `infra` | [模型工厂](../../src/personal_agent/infra/structured_model.py)、[响应解析](../../src/personal_agent/infra/model_response.py)、[存储实现](../../src/personal_agent/infra/storage/) | SDK、网络、数据库和外部协议适配；通过现行 Port 交回结果 |
| `kernel` | [contracts](../../src/personal_agent/kernel/contracts/)、[共享模型](../../src/personal_agent/kernel/models.py)、[Prompt 注册](../../src/personal_agent/kernel/prompt_registry.py)、[配置](../../src/personal_agent/kernel/config.py) | 现有共享契约与基础设施辅助；禁止因底层可被导入就堆入新的业务规则 |

领域事实的文件位置与 owner 分开判断。例如，知识模型在 `application/knowledge/models.py`，删除与恢复契约在 `application/knowledge_lifecycle/models.py`，Research 模型在 `kernel/contracts/research.py`。已有事实在其现行入口修改；需要迁移位置时迁移全部消费者并删除原定义，遵守 [ARC 唯一契约](../devSpec/architecture-ownership.md#11-同一职责采用唯一契约)。

## 2. 从功能进入代码

| 修改目标 | 主要入口与直接协作者 | 详细契约 |
| --- | --- | --- |
| 对话决策、执行与交付 | [ConversationService](../../src/personal_agent/application/conversation/service.py)；同目录的 `ports.py`、`model_actions.py`、`working_plan.py`、`verification_admission.py` | 当前还直接编排请求内研究，混合点见[架构 §3.1](core-architecture-current-state.md#31-当前主循环的职责混合)；契约见 [Runtime](../topics/runtime.md)、[Verification/Completion](../topics/verification-and-completion.md) |
| 可替换回答结果 | [answer_results.py](../../src/personal_agent/application/conversation/answer_results.py)、[装配契约](../../src/personal_agent/kernel/contracts/answer_result.py) | Runtime 分别装配 direct/claims writer 与 required/none 核验。模块拥有提交协议及接纳，主循环继续拥有模型准入、执行、计量和唯一 Final；Journal 冻结配置，恢复不能换装配。默认 claims+required；临时无核验流程不计产品通过，见 [ADR 0041](../adr/0041-replaceable-answer-result-modules.md) |
| 原生消息及动作模型接口 | [model_actions.py](../../src/personal_agent/application/conversation/model_actions.py)、[answer_results.py](../../src/personal_agent/application/conversation/answer_results.py)、[ModelActionDefinition](../../src/personal_agent/capabilities/contracts/model.py) | 同轮定义绑定工具直接参数，普通assistant正文经回答模块形成同一候选；调用优先，非法调用不降正文，无通用决策包装或第二Final相位，见[ADR 0045](../adr/0045-native-intent-loop-and-recorded-model-output.md) |
| 原生工具历史续接 | [model_history.py](../../src/personal_agent/application/conversation/model_history.py)、[决策及控制事实](../../src/personal_agent/application/conversation/models.py)、原 Model Port／Adapter | Journal 与费用一并保存 host／请求模型绑定的完整原响应；结果从 canonical 事实派生，控制结果在实际接纳点提交，完整交换服从原压缩，见 [ADR 0042](../adr/0042-native-model-tool-continuation.md) |
| 对话中的个人知识读取投影 | [ConversationKnowledgeReadAdapter](../../src/personal_agent/application/conversation/knowledge_reading.py)；消费 KnowledgeService，按现行 `ConversationKnowledgeReadPort` 返回候选与证据 | 筛选和结果投影归 Application；AgentRuntime 构造并注入，知识事实仍归 KnowledgeService |
| Context、来源读取与引用 | Conversation 内的 [Context 物化](../../src/personal_agent/application/conversation/context_materialization.py)、[来源读取](../../src/personal_agent/application/conversation/source_reading.py)、[引用](../../src/personal_agent/application/conversation/citations.py) | [Context Engineering](../topics/context-engineering.md)、[引用坐标 ADR](../adr/0030-document-line-citation-identity.md) |
| 旧执行历史压缩与恢复 | [HistoryCompactor](../../src/personal_agent/application/conversation/history_compaction.py)、[检查点契约](../../src/personal_agent/application/conversation/history_models.py)；由 ConversationService 装配与消费 | 原 Journal 保留输入／用量，Artifact 保留原件，协作者只拥有派生视图；按 [ADR 0038](../adr/0038-history-compaction-before-natural-pressure.md)提前接入，自然压力验收未覆盖 |
| 知识捕获与入库 | [CaptureService](../../src/personal_agent/application/capture/service.py)、[IngestionPipeline](../../src/personal_agent/application/capture/ingestion_pipeline.py)、[KnowledgeService](../../src/personal_agent/application/knowledge/service.py) | [Memory](../topics/memory.md)；原始材料、知识事实与图投影按各自 owner 处理 |
| 知识删除与恢复 | [KnowledgeLifecycleService](../../src/personal_agent/application/knowledge_lifecycle/service.py)、同目录 `models.py` 与 `store.py` | [删除链路](../workflow/delete-knowledge-workflow.md) |
| Research 与周期任务 | [ResearchService](../../src/personal_agent/application/research/service.py)、同目录 `scheduler.py`、[Web 装配](../../src/personal_agent/adapters/web/context.py) | [Research 链路](../workflow/research-once-workflow.md) |
| 复习简报与知识缺口 | [ReviewDigestUseCase](../../src/personal_agent/application/review/service.py)、[KnowledgeGapUseCase](../../src/personal_agent/application/insight/service.py)、各自 job/scheduler | [主动知识闭环](../proactive-knowledge-loop.md) |
| 工具与委派接入 | [ToolExecutor](../../src/personal_agent/governance/gateway.py)、[AgentGateway](../../src/personal_agent/agents/gateway.py)、[Conversation Port](../../src/personal_agent/application/conversation/ports.py) | [工具专题](../topics/tools.md)、[A2A 链路](../workflow/gpt-researcher-a2a-workflow.md) |
| 检索实验与候选程序执行 | [实验用例](../../src/personal_agent/application/retrieval_experiment/service.py)、[外层 Docker](../../src/personal_agent/infra/retrieval_experiment/backend.py)、[唯一引擎](../../src/personal_agent/infra/retrieval_experiment/controller.py) | Runtime 按显式许可部署注册一个受治理工具，原 Conversation Journal 保存接受／命令／执行／回执；模型选择实验及程序，代码拥有评分、冻结及终态。完整 target 尚未验收，契约由[研究 Spec](../optimization/to_verify/knowledge-decision-delivery.md)拥有 |
| 模型自主 Python 分析 | [Python 用例](../../src/personal_agent/application/python_execution/service.py)、[执行适配器](../../src/personal_agent/infra/python_execution/backend.py)、[共享沙箱](../../src/personal_agent/infra/python_execution/sandbox.py)、[工具](../../src/personal_agent/tools/execute_python.py) | 与检索实验并列，经原工具循环执行；原 Journal 拥有接受、命令、进程事实和回执，共享执行额度；原 Artifact 保存程序、确切输入清单及输出。Runtime 将检索部署或独立对话许可映射为同一 Profile；Journal 按许可聚合分析任务消费并投影历史原件，统计及解释由模型选择，见 [ADR 0039](../adr/0039-model-directed-python-execution.md)及 [ADR 0040](../adr/0040-scoped-python-analysis-authorization.md) |
| 共享程序产物及用户文件 | [ArtifactService](../../src/personal_agent/application/artifacts/service.py)、[文本坐标](../../src/personal_agent/application/artifacts/text_coordinates.py)、[认证内容路由](../../src/personal_agent/adapters/web/routes/artifacts.py) | 一个 owner 保存确切字节、完整 producer 与不可变引用；模型以现有 resource_id 选文件，Artifact 从当前获准集合恢复唯一完整引用；typed 初始／成功来源供读搜，草稿修改、实验执行和下载分别检查权限；上传不自动入库 |
| 研究实验完成与恢复 | [Conversation完成](../../src/personal_agent/application/conversation/research_delivery.py)、[实验校验](../../src/personal_agent/application/retrieval_experiment/delivery.py) | 核对当前SubmittedFinal、真实执行、冻结／test和原件引用后直接返回同一Final；不发布清单／ZIP／报告副本。既有[CLI读取](../../src/personal_agent/infra/retrieval_experiment/reproduction.py)只保留现有离线消费者，退出Agent验收门槛 |
| 模型 transport、重试与观测 | [模型工厂](../../src/personal_agent/infra/structured_model.py)、[模型 Port](../../src/personal_agent/capabilities/contracts/model.py)、[响应解析](../../src/personal_agent/infra/model_response.py)、[请求内 HTTP 诊断](../../src/personal_agent/infra/model_transport.py) | [横切机制](cross-cutting.md)、[模型协议 ADR](../adr/0007-structured-output-transport-capability.md) |
| Loop 原生意图及逐响应恢复 | [动作投影](../../src/personal_agent/application/conversation/model_actions.py)、[回答模块](../../src/personal_agent/application/conversation/answer_results.py)、[Journal](../../src/personal_agent/application/conversation/journal.py) | [ADR 0045](../adr/0045-native-intent-loop-and-recorded-model-output.md)；普通提交携带正文，Journal一次保存请求／响应原件，typed引用与continuation恢复，真实生成／完整E2E待验收 |
| SSE 答案展示 | [entry_stream.py](../../src/personal_agent/adapters/web/routes/entry_stream.py)；调用现有 `AgentService.converse()`，将验收后的完整答案分块输出 | [API](../api.md)；模型仍通过统一 `StructuredModelClient.generate()` 调用，展示层不另建模型执行链 |
| 策略审计归属 | [PolicyDecisionRecorder](../../src/personal_agent/kernel/observability.py)、[typed 事件](../../src/personal_agent/kernel/contracts/policy.py)、[PostgreSQL 写入口](../../src/personal_agent/infra/storage/postgres_tool_governance_store.py)；Runtime 显式注入三个调用点 | [观测与治理](../topics/observability-governance.md)、[ADR 0034](../adr/0034-runtime-policy-audit-isolation.md)；可选 sink 不承担授权或完成判断 |

一次局部修改从对应入口、typed 契约和直接协作者开始阅读。跨越业务写入、权限或恢复边界时再沿实际调用链扩展，模块组织遵守 [COD](../devSpec/code-structure.md#32-功能模块化与开发上下文)。

## 3. 正式入口与装配

```mermaid
flowchart TD
    CLI["CLI / Web / 飞书"] --> Facade["AgentService 统一外观"]
    Web["build_web_app_context"] --> Facade
    Web --> Jobs["渠道、Research 与简报调度器"]
    Facade --> Root["AgentRuntime 装配及现有协调"]
    Root --> Conversation["ConversationService"]
    Root --> Business["Knowledge / Lifecycle / Research 等用例"]
    Root --> Mechanism["模型、ToolExecutor、AgentGateway、存储实现"]
    Conversation --> Ports["typed 模型、工具、Agent、Artifact 与知识 Port"]
    Mechanism -. "实现并注入" .-> Ports
    Jobs --> Business
```

此图表达构造与调用关系，不是 import DAG。CLI 入口由 [`pyproject.toml`](../../pyproject.toml) 指向 `personal_agent.main:app`；Web 从 `create_app()` 与 `build_web_app_context()` 装配。直接业务 API 与 Conversation 工具路径复用业务用例及其写入契约。

## 4. 依赖检查的权威来源与覆盖

[`scripts/check_layers.py`](../../scripts/check_layers.py) 的 `ALLOWED_DEPENDENCIES` 是包间**允许直接依赖**的唯一机器定义。本页不复制允许矩阵；允许的边不代表已发生的边，传递可达也不授权新增直接 import。

该脚本扫描包内静态 `import` / `from`，检查未知包、缺失包、包间循环及禁止依赖；当前 CI 在 [architecture.yml](../../.github/workflows/architecture.yml) 执行。它不检查第三方依赖、包内职责混装、动态导入、事实 owner 或运行可达性，不能据此宣布架构已完全纯化。

当前物理布局与逻辑分层存在上述差异。新增或调整生产代码时先核对相关调用方与契约；实质改变包依赖或责任边界时按 [ARC 演进规则](../devSpec/architecture-ownership.md#8-架构基线与持续演进)说明必要性、同步架构与检查规则。禁止为消除报错直接扩大允许集合，或通过动态导入、`kernel` 中转和运行时查找绕过依赖门禁。
