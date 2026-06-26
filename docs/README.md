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

## 文档书写原则

文档必须基于当前代码和已落地能力书写，而不是把讨论中的新想法直接追加成补丁式段落。更新架构文档前，先确认对应模块、测试和运行链路的真实职责；如果代码和文档不一致，应优先判断是代码需要调整、文档需要修正，还是需要同时修改两者。

写文档时遵守以下约束：

- **单一事实源**：不要在多个文档或多个层次重复维护同一份流程拓扑、工具契约或治理规则。比如 workflow 拓扑以 `WorkflowSpec / WorkflowRegistry` 为准，文档只解释该事实源如何被使用。
- **按现有能力组织**：章节应围绕已经存在的模块边界和能力边界展开，例如声明期 `WorkflowSpecValidator` 与执行前 `StepProjectionValidator` 的职责差异，而不是在发现问题后追加“不能这样做”的孤立说明。
- **避免补丁式写法**：不要在原文后面堆叠“注意 / 但是 / 其实”来修补前文。若原结构表达不准确，应重写相关小节，让最终文档读起来像一版一致的设计说明。
- **不要路径先行**：架构文档不要在开头罗列一串文件路径。文档应先解释层级、职责、关键组件和协作关系；组件名本身足以引导读者在当前目录结构中定位代码。只有在 API、部署、故障排查这类需要精确操作的文档里，才把具体路径作为必要信息出现。
- **区分现状和未来**：已落地能力写在 `topics/`、`workflow/` 或顶层权威文档；未来设想写入 `future/` 或明确标注为演进方向，不能把目标状态写成当前能力。
- **先金标后能力**：每个 Agent 能力的新增、优化或修复，必须先以 golden set / eval case 的形式定义期望行为和验收标准；实现后必须验证新 case 通过，且核心回归集不退化。组件文档只描述已被代码和测试支撑的能力，不把“基于 golden set 开发”写成某个组件的局部补丁说明。
- **测试新增克制**：不能因为每次小改动随意新增单测。新增测试必须服务于清晰的工程边界：新增或修复 Agent 能力边界、复现 golden set / 线上问题并提供可定位信号、保护安全/副作用/权限/幂等不变式、或锁定容易误合并/误路由的核心决策点。纯重构、实现细节调整、已被上层 golden set 清楚覆盖且定位足够明确的变化，不应再额外堆叠单测。
- **语义判断优先 LLM**：涉及意图拆分、目标依赖、候选选择、答案组织、重规划等需要语义理解的 Agent 能力，应优先设计为结构化 LLM 决策，并用 schema、validator、fallback、policy 和 eval 约束输出。流程真源、工具执行、安全边界、幂等和审计仍由确定性系统负责，不能让 LLM 越权生成不可验证的控制流或副作用。
- **和测试/代码同步**：如果文档声明某个模块不承担某职责，代码和测试也应体现这个边界。架构级约束优先沉到 `.github/workflows/architecture.yml` 这类 CI 门禁，而不是放在运行时兜底或只写进文档；其中模块依赖方向和无环性由 `scripts/check_layers.py` 的 `Layer / cycle gate` 执行，workflow contract 由 `Workflow registry gate` 执行。文档不是单独的口径修饰，而是工程事实的索引和解释。

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
