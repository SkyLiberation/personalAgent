# personalAgent 文档索引

本项目是一个 **workflow-first** 的个人知识 Agent：LLM 负责理解语义、生成候选与开放式表达；
确定性代码负责授权、编排、校验、执行、持久化与审计。固定业务流程由 `WorkflowSpec / WorkflowRegistry`
声明，经 deterministic projector 投影为 `ExecutionStep`，进入 checkpoint-safe 的 LangGraph 步骤执行图。

系统级的「LLM 决策点 vs 确定性流程」全景见 [summary/llm-decisions-and-deterministic-flows.md](summary/llm-decisions-and-deterministic-flows.md)。

## 目录分工

| 目录 | 定位 |
| --- | --- |
| `topics/` | 分层设计文档（按能力域拆分：路由、工具、记忆、检索、可观测/治理、动态规划等） |
| `workflow/` | 一次请求或一个业务 workflow 的实际执行链路 |
| `summary/` | 系统级综述（LLM 决策 vs 确定性流程的全局视角） |
| `interview/` | 面试问答稿（同内容的 Q&A 形态，面向讲解场景） |
| `mermaid/` | Model / Layer 依赖类图 |
| `future/` | 未来能力与优化设想 |
| 顶层散文档 | API、部署、环境变量、评测、检索策略等独立主题 |

## 按主题找权威文档

| 主题 | 权威文档 |
| --- | --- |
| Workflow / Step Projection 架构总览 | [workflow/workflow-framework.md](workflow/workflow-framework.md) |
| Entry → Router → Plan → ReAct → 输出 端到端流程 | [workflow/entry-router-plan-react-output-flow.md](workflow/entry-router-plan-react-output-flow.md) |
| Capture 摄取 + Ask RAG 流水线 | [workflow/capture-ask-model-flow.md](workflow/capture-ask-model-flow.md) |
| 检索策略与评测口径 | [retrieval-strategies.md](retrieval-strategies.md) |
| 检索/推理层与 verifier、统一证据模型 | [topics/retrieval-reasoning.md](topics/retrieval-reasoning.md) |
| 路由（Router 传输/领域模型拆分） | [topics/routing.md](topics/routing.md) |
| 入口/传输层（Web / CLI / Feishu） | [topics/entry.md](topics/entry.md) |
| 运行时编排（AgentService / AgentRuntime / replay） | [topics/runtime.md](topics/runtime.md) |
| 工具层（治理 / Gateway / Artifact / 审计） | [topics/tools.md](topics/tools.md) |
| 记忆分层（短期 checkpoint / 长期 Postgres / typed memory） | [topics/memory.md](topics/memory.md) |
| 上下文工程（context-rot 防御） | [topics/context-engineering.md](topics/context-engineering.md) |
| 可观测与治理（LangSmith / PolicyEngine / 审计） | [topics/observability-governance.md](topics/observability-governance.md) |
| 执行反馈 / SSE 事件 | [topics/execution-feedback.md](topics/execution-feedback.md) |
| LangChain / LangGraph 能力取舍 | [topics/langchain-langgraph-capability-adoption.md](topics/langchain-langgraph-capability-adoption.md) |
| 动态规划（未来能力，含 projection vs dynamic 对照表） | [topics/dynamic-planning.md](topics/dynamic-planning.md) |

## 关键业务 Workflow

| Workflow | 文档 |
| --- | --- |
| delete_knowledge（高风险删除 + HITL） | [workflow/delete-knowledge-workflow.md](workflow/delete-knowledge-workflow.md) |
| solidify_conversation（会话固化为长期知识） | [workflow/solidify-conversation-workflow.md](workflow/solidify-conversation-workflow.md) |
| 主动知识闭环（gap 提问 / 巩固 / 简报） | [proactive-knowledge-loop.md](proactive-knowledge-loop.md) |

## 运维与参考

| 主题 | 文档 |
| --- | --- |
| HTTP API | [api.md](api.md) |
| 部署 | [deploy.md](deploy.md) |
| 环境变量 | [env.md](env.md) |
| LLM 提示词清单 | [llm-prompts.md](llm-prompts.md) |
| Golden Set 设计 | [golden-set-design.md](golden-set-design.md) |
| RAG 评测结果 | [rag-eval-results.md](rag-eval-results.md) |
| Microsoft GraphRAG provider | [ms-graphrag-provider.md](ms-graphrag-provider.md) |
| 生产风险优化计划 | [production-risk-optimization-plan.md](production-risk-optimization-plan.md) |
| Review digest | [review-digest.md](review-digest.md) |

> 各子目录另有更细的索引：[workflow/README.md](workflow/README.md)、[interview/INDEX.md](interview/INDEX.md)。
