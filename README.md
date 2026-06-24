# “数字第二大脑” Agent

一个面向个人知识生命周期管理的主动式 AI Agent。

它不是单纯的笔记应用或 RAG 问答 Demo，而是一个让个人知识持续完成“采集、连接、检索、验证、
复习、整理、研究、发现缺口、主动触达”的长期认知系统。工程同时覆盖 Agent runtime、工作流编排、
知识存储、图谱推理、外部情报研究、主动任务、治理审计和多端交互。

## 项目目标

这个项目的目标是构建一套可持续演进的“个人知识与外部情报闭环”，让 Agent 不只回答一次问题，
还能够长期积累知识、维护知识质量、跟踪外部变化并主动行动。当前目标能力包括：

1. **统一多端入口**：Web、CLI、飞书文本/文件和 SSE 请求进入同一 Agent 入口；Router 支持语义目标拆分、复合请求、澄清和会话指代理解。
2. **多来源知识采集**：接收文本、网页链接、PDF/上传文件和对话结论，完成正文提取、结构化分块、来源指纹、重复检测、摘要、标签和引用定位。
3. **长期记忆与知识连接**：以 Postgres 保存笔记、chunk、复习卡、版本关系、运行历史和 checkpoint，以 Graphiti/Neo4j 保存实体、关系、事实和 episode 映射。
4. **多源检索与证据问答**：组合图谱、本地语义/关键词、结构化文档、情景记忆、反思记忆和公网搜索，经过融合、去冗余、上下文压缩、生成与事实校验后输出可追溯回答。
5. **知识生命周期管理**：支持会话固化、同主题知识整理、supersede、冲突标记、软删除、删除快照、人工确认、幂等执行和恢复。
6. **复习与知识巩固**：采集时生成复习卡，按用户时区生成和投递知识简报，通过 Web/飞书接收“记得、忘了、稍后”反馈并调整复习计划。
7. **主动知识维护**：检测知识孤岛、薄弱连接和潜在矛盾，主动提出少量问题；按主题生成综合笔记，并保留知识演进与来源关系。
8. **一次性外部研究**：围绕指定主题规划多个查询，调用公网搜索和网页抓取，进行来源归一、事件聚类、重复消除、可信度判断和个人知识关联，生成结构化研究简报。
9. **周期性情报订阅**：支持“每天 9 点收集 AI 新闻”等订阅；外部 cron 负责到期扫描和入队，Postgres durable worker 负责研究与独立投递任务。
10. **个性化情报反馈**：简报条目支持展开、有用、不感兴趣、收藏和确认入库；反馈会更新订阅偏好，外部事件可带来源和可信度保存为长期知识。
11. **可恢复 Workflow 执行**：WorkflowSpec 定义拓扑、工具、风险和确认策略；LangGraph 提供 checkpoint、interrupt/resume、step retry/replan、事件流、回放和 fork。
12. **受治理的工具行动**：ToolGateway 统一执行参数校验、权限策略、ReAct allowlist、超时、瞬时重试、限流、外部域名约束、HITL、幂等和结构化审计；管理类 workflow 可在局部工具箱内做受治理的工具决策。
13. **后台任务与主动触达**：具备 Postgres durable queue、lease、heartbeat、重试和 dead-letter；支持图谱异步同步、研究任务、研究投递、复习简报与知识缺口提醒，并可通过工具诊断队列与重试失败任务。
14. **多用户安全与可观测性**：提供 API Key、管理员范围、用户数据隔离、日志、health、LangSmith 脱敏 trace、工具/策略审计、run snapshot 和调试重放。
15. **持续质量评测**：测试和 eval 覆盖 Router、Workflow、工具治理、对话、RAG、编排、知识整理、知识缺口和 Research 事件质量，并支持 Workflow 发布门禁。

整体闭环可以概括为：

```text
Capture / Conversation
  → Notes / Chunks / Review Cards / Knowledge Graph
  → Retrieval / Evidence Fusion / Grounded Answer / Verification
  → Review Digest / Feedback / Consolidation / Supersede
  → Knowledge-gap Detection / Proactive Questions

External Cron / Manual Research
  → Web Search / Source Fetch
  → Event Clustering / Verification / Personal Relevance
  → Intelligence Digest / Feedback / Approved Save
  → New or Updated Knowledge
```

## 当前工程的 Agent 结构

| 组件 | 代码落点 | 能力总结 | 文档 |
| --- | --- | --- | --- |
| `入口层` | [web/api.py](src/personal_agent/web/api.py), [web/routes/](src/personal_agent/web/routes), [feishu/service.py](src/personal_agent/feishu/service.py), [main.py](src/personal_agent/main.py) | 具备 Web API、前端、CLI、飞书多入口，核心请求可以进入统一 Agent 流程 | [docs/topics/entry.md](docs/topics/entry.md) |
| `目标路由 / Workflow 规划层` | [agent/router.py](src/personal_agent/agent/router.py), [agent/workflow_planner.py](src/personal_agent/agent/workflow_planner.py), [agent/execution_models.py](src/personal_agent/agent/execution_models.py) | Router 只拆分语义 Goal；WorkflowPlanner 从 WorkflowSpec 编译跨 workflow 任务 DAG，支持 `ingest → ask` 等复合请求 | [docs/topics/routing.md](docs/topics/routing.md) |
| `Workflow / 执行校验层` | [agent/workflow.py](src/personal_agent/agent/workflow.py), [agent/workflow_validator.py](src/personal_agent/agent/workflow_validator.py), [agent/step_projection_validator.py](src/personal_agent/agent/step_projection_validator.py), [agent/orchestration_nodes/](src/personal_agent/agent/orchestration_nodes/) | workflow-first：`WorkflowSpec` 是工具、风险、确认和拓扑的流程真源；Orchestrator 只消费编译后的 ExecutionPlan | [docs/topics/workflow-step-projection.md](docs/topics/workflow-step-projection.md) |
| `运行时 / 编排层` | [agent/runtime.py](src/personal_agent/agent/runtime.py), [agent/orchestration_contexts.py](src/personal_agent/agent/orchestration_contexts.py), [agent/orchestration_graph.py](src/personal_agent/agent/orchestration_graph.py), [agent/orchestration_nodes/](src/personal_agent/agent/orchestration_nodes/), [agent/orchestration_models.py](src/personal_agent/agent/orchestration_models.py) | `AgentRuntime` 作为 composition root 显式装配窄 Graph Context；LangGraph 总编排支持 route/workflow projection/step/ReAct/HITL/checkpoint；`AgentService` 是应用 facade | [docs/topics/runtime.md](docs/topics/runtime.md)、[docs/workflow/entry-router-plan-react-output-flow.md](docs/workflow/entry-router-plan-react-output-flow.md) |
| `工具层` | [tools/](src/personal_agent/tools), [capture/service.py](src/personal_agent/capture/service.py), [graphiti/store.py](src/personal_agent/graphiti/store.py) | 具备统一 Tool 协议、ToolGateway、PolicyEngine、幂等与审计；覆盖 capture、graph/web search、研究/订阅管理、知识生命周期、worker 诊断、workflow 诊断、delete/restore、consolidate 等动作 | [docs/topics/tools.md](docs/topics/tools.md) |
| `记忆层` | [memory/](src/personal_agent/memory), [storage/](src/personal_agent/storage), [core/models.py](src/personal_agent/core/models.py) | 有受限会话线索、Postgres 长期记忆、Research 数据、LangGraph checkpoint、run snapshot 和图谱字段映射 | [docs/topics/memory.md](docs/topics/memory.md)、[docs/topics/context-engineering.md](docs/topics/context-engineering.md) |
| `检索与推理层` | [agent/ask/](src/personal_agent/agent/ask), [agent/verifier.py](src/personal_agent/agent/verifier.py), [graphiti/store.py](src/personal_agent/graphiti/store.py) | 支持图谱、结构、本地、网络、情景和反思多路召回，RRF/MMR、上下文压缩、反证检索、引用生成和蕴含级校验 | [docs/topics/retrieval-reasoning.md](docs/topics/retrieval-reasoning.md) |
| `主动知识循环` | [review/](src/personal_agent/review), [insight/](src/personal_agent/insight), [knowledge/](src/personal_agent/knowledge) | 生成并投递复习简报、接收复习反馈、检测知识孤岛/矛盾并主动追问、将同主题笔记整理为综述并建立 supersede 关系 | [docs/review-digest.md](docs/review-digest.md)、[docs/proactive-knowledge-loop.md](docs/proactive-knowledge-loop.md) |
| `持续研究层` | [research/](src/personal_agent/research), [storage/postgres_research_store.py](src/personal_agent/storage/postgres_research_store.py), [web/routes/research.py](src/personal_agent/web/routes/research.py) | 支持一次性研究、定时订阅、来源归一、事件聚类、可信度、个人关联、情报简报、反馈偏好和确认入库 | [docs/future/scheduled-intelligence-research.md](docs/future/scheduled-intelligence-research.md) |
| `后台任务 / 调度层` | [agent/worker.py](src/personal_agent/agent/worker.py), [storage/postgres_worker_queue_store.py](src/personal_agent/storage/postgres_worker_queue_store.py), [deploy/cron/](deploy/cron) | Postgres durable queue 提供 lease、heartbeat、重试、dead-letter 和用户并发限制；生产 Research 使用外部 cron 入队、独立 worker 执行 | [docs/deploy.md](docs/deploy.md) |
| `执行与反馈层` | [web/routes/](src/personal_agent/web/routes), [agent/runtime.py](src/personal_agent/agent/runtime.py), [agent/orchestration_models.py](src/personal_agent/agent/orchestration_models.py) | 支持同步 API、SSE、结构化 `AgentEvent`、run snapshot、LangGraph interrupt/resume、失败降级、异步任务和前端确认面板 | [docs/topics/execution-feedback.md](docs/topics/execution-feedback.md)、[docs/api.md](docs/api.md) |
| `观测、治理与评测层` | [core/observability.py](src/personal_agent/core/observability.py), [web/auth.py](src/personal_agent/web/auth.py), [tests/](tests), [evals/](evals) | 具备日志、health、API Key、限流、用户隔离、工具/策略审计、LangSmith 脱敏 trace、Workflow 回放和多类离线质量门禁 | [docs/topics/observability-governance.md](docs/topics/observability-governance.md) |

## Entry 编排图

[docs/mermaid/entry-orchestration.md](docs/mermaid/entry-orchestration.md) 是由 [scripts/draw_entry_graph.py](scripts/draw_entry_graph.py) 生成的当前 LangGraph entry 总编排可视化图源，用来对齐 `normalize_entry -> route_intent -> clarify / workflow planning -> step / ReAct / HITL -> finalize_entry_result` 的真实节点结构和条件流转关系。运行 `uv run python scripts/draw_entry_graph.py` 可刷新该图；`uv run python scripts/export_thread_checkpoints.py <thread_id>` 会把持久化 checkpoint 导出到 `scripts/assets/`。

## 当前技术栈

- `Python 3.11+`
- `FastAPI`
- `LangGraph`
- `Graphiti`
- `Neo4j`
- `Postgres`
- `React 19`
- `Vite 8`
- `TypeScript 6`
- `Docker Compose`
- `uv`

## 快速开始

完整本地开发、Neo4j/Postgres、飞书长连接、前端构建和 Docker Compose 说明统一维护在 [docs/deploy.md](docs/deploy.md)。

README 只保留最短路径：

1. 按 [docs/env.md](docs/env.md) 准备 `.env`
2. 按 [docs/deploy.md](docs/deploy.md) 启动后端、前端和可选基础设施
3. 打开前端工作台或 API 文档验证服务

常用入口：

- 前端：`http://127.0.0.1:3000`
- API 文档：`http://127.0.0.1:8000/docs`

## 当前业务能力范围

### 1. Capture

- 可以接收文本、链接和上传文件三类采集输入
- 采集结果会被整理成 `KnowledgeNote`
- 长文（>2000 字符）会自动按标题/段落拆分为 1 条 parent note + N 条 chunk notes，每个 chunk 独立拥有 title/summary/tags/citation anchor
- 当前采集链路包含网页正文抓取、PDF 文本提取、标题/摘要/标签生成、复习卡生成等处理步骤
- 图谱可用时，采集结果会继续尝试写入 Graphiti，parent note 与 chunk notes 均会进入图谱同步链路

### 2. Knowledge Connection

- 默认使用 Postgres 持久化知识数据，并提供简单匹配检索
- 图谱开启后，会为笔记补充实体、关系和图谱 episode 映射信息
- 当前数据模型中已经为图谱字段预留了 `graph_episode_uuid / entity_names / relation_facts / graph_node_refs / graph_edge_refs / graph_fact_refs`
- 相似笔记检索已支持按 parent 去重，避免同一文档的多个 chunk 重复出现
- 问答证据呈现区分语义层和证据层：Graphiti `node / edge / fact` 作为主推理材料，parent/chunk note 作为原文证据、snippet、高亮和抽取校验来源

### 3. Ask

- 提供本地检索问答链路
- 图谱可用时，问答流程会优先使用 Graphiti 抽取的 `node / edge / fact` 构造图谱事实网络，再回查 note/chunk 生成可追溯引用
- 图谱不可用或图谱证据不足时，问答会回退并合并本地链路；本地检索证据不足时，自动触发网络搜索作为第三层兜底
- 问答支持 `session_id` 会话上下文；对话与运行历史以 LangGraph checkpoint、run snapshot 和事件历史为真源
- Web 侧提供同步问答和 `SSE` 返回方式；`ask_stream` 已升级为模型 token 流，边生成边推送
- 图谱问答会构造 `relation_fact + snippet` 证据锚点，前端支持点击 citation 自动定位并高亮回答中的对应证据片段
- 前端可按会话查看最近运行、执行步骤、引用、事件和 checkpoint 恢复结果

### 4. Direct Answer

- 提供无需检索、无需工具的低风险 workflow
- 适用于问候、感谢、澄清性问题和简单说明
- LLM 可用时使用小模型简短回答，不可用时退回启发式回复
- 父图中的 `direct_answer_branch` 只用于 Router 不可用、无 Goal 或步骤校验失败后的 fallback

### 5. Knowledge Lifecycle

- `delete_knowledge` 支持高风险 workflow step projection 和 LangGraph HITL 删除确认
- 删除计划包含 `resolve` 步骤，可通过图谱 episode、本地相似检索和关键词匹配解析待删笔记
- `delete_note` 工具会返回确认 payload，entry 总图通过 LangGraph interrupt/resume 完成前端确认后继续删除笔记、复习卡和可用的图谱 episode
- 删除 parent note 时自动检测子 chunk 并级联删除
- `solidify_conversation` 已具备草稿生成、`draft_ready` 事件和 `capture_text` 入库工具基础
- 删除前写入快照，`restore_note` 可在确认、幂等和审计约束下恢复 note、chunk 与 review card
- 知识版本支持 supersede 与 conflicted 状态，为自动整理和冲突治理提供基础

### 6. Review & Knowledge Digest

- capture 时自动为长期知识生成 `review_card`
- `/api/digest` 提供最近笔记、到期复习内容和知识增长概览
- 支持 Digest 订阅、时区与发送时间配置、手动立即发送和投递历史查询
- 后台 Job/Scheduler 可按计划通过飞书主动投递，不要求用户持续打开前端
- `digest_deliveries` 通过 `subscription_id + digest_date` 保证同日投递幂等
- 用户可以从 Web 或飞书提交“记得 / 模糊 / 忘记”等反馈，系统据此更新复习间隔和下次到期时间

详见 [Review Digest](docs/review-digest.md)。

### 7. Automatic Knowledge Consolidation

- `consolidate_knowledge` 意图按主题选择相关笔记并生成一篇新的综合笔记
- 新综述进入标准 capture/ingestion 链路，继续获得 chunk、review card 和 graph sync 能力
- 原笔记会通过版本关系标记为被新综述 supersede，保留知识演进轨迹
- Review Digest、知识整理、知识缺口检查均可通过自然语言意图触发；scheduler、CLI 与意图入口复用同一应用用例

详见 [主动知识循环](docs/proactive-knowledge-loop.md)。

### 8. Proactive Knowledge-gap Questions

- `KnowledgeGapAnalyzer` 会结合本地笔记和图谱检测知识孤岛与潜在矛盾
- 系统会把检测结果整理为少量主动问题，而不是一次推送大量提醒
- 复用知识简报的订阅与飞书投递目标，但使用独立调度时间
- `knowledge_gap_deliveries` 按订阅和日期做跨重启幂等，避免同日重复打扰
- 图谱不可用或 LLM 改写失败时具备确定性降级路径
- 单次问题数量由 `max_gaps_per_run` 控制

详见 [知识缺口主动追问](docs/proactive-knowledge-loop.md#1-知识缺口主动追问)。

### 9. Research & Scheduled Intelligence

- `research_once` 已拆为 workflow-native pipeline：prepare run、plan queries、collect sources、cluster events、rank events、compose digest 和最终呈现
- 查询计划会驱动 `web_search` 和 `capture_url`，并通过 `graph_search` 对照个人已有知识
- 搜索结果按 canonical URL、内容指纹、标题语义、实体和时间窗口归一为事件，减少转载和重复新闻
- 事件区分 `verified / reported / uncertain / conflicted`，简报保留来源链接、可信度和个人知识关联
- `create_research_subscription` 支持“每天 9 点收集 AI 新闻”等自然语言订阅
- 订阅、运行、来源、事件、简报、投递和反馈均持久化到 Postgres
- 生产环境使用外部 cron 调用一次性 scheduler 入队，独立 durable worker 通过 `execute_research_run` workflow 执行研究，再独立投递
- 研究任务和投递任务解耦；投递失败可独立重试，不重复执行搜索
- 飞书条目支持 `N1 展开 / 有用 / 不感兴趣 / 收藏 / 入库`
- 用户反馈会更新订阅内容偏好；“入库”会保存事件摘要、可信度与来源

详见 [持续研究与定时情报简报](docs/future/scheduled-intelligence-research.md)。

### 10. Workflow, Tools & Durable Execution

- Router 可以把一个请求拆分为按顺序执行的多个 Goal
- WorkflowPlanner 从固定 `WorkflowSpec` 编译跨 workflow 任务 DAG
- LangGraph 支持 step projection、ReAct 子图、checkpoint、interrupt/resume、失败重试、replan、replay 和 fork
- ToolGateway 统一治理 deterministic、ReAct 和 direct 三类工具调用
- `manage_research`、`maintain_knowledge`、`inspect_operations`、`inspect_workflow` 等管理类 workflow 在 scoped allowed tools 内做局部工具决策
- 工具面补齐 Research 订阅管理、知识生命周期维护、worker 队列诊断和 workflow run 诊断
- 工具契约包含 Pydantic schema、风险、副作用、权限域、确认、幂等、超时、重试、限流和域名白名单
- Postgres worker queue 提供 durable enqueue、lease、heartbeat、优先级、重试和 dead-letter
- Workflow 定义、部署、版本、eval gate、事件和调试 artifact 均可查询

### 11. Observability, Governance & Evaluation

- API Key 与管理员 Key 提供用户身份和跨用户管理边界
- 工具调用和策略决策写入独立 Postgres 审计表
- LangSmith trace 默认脱敏，不上传用户正文和工具参数
- run snapshot、workflow event、checkpoint export、replay/fork 支持问题定位
- `tests/` 覆盖单元、集成、Postgres、API 和完整 Agent flow
- `evals/` 覆盖 Router、RAG、对话、编排、知识整理、知识缺口和 Research 质量
- Research 评测包含事件召回/精度、去重质量、一手来源率和不确定性校准

### 12. Web UI

- 提供基于 `FastAPI + React` 的前后端分离结构
- 前端工作台覆盖 `Capture / Ask / Entity Graph / Relation Graph / Digest / Timeline / Memory` 等视图
- 前端主要围绕采集、问答、历史查看和调试数据管理几个场景展开
- 构建后的 `frontend/dist` 可以由 FastAPI 托管

### 13. Feishu

- 当前以 `官方 Python SDK + 长连接接收事件` 为主
- 文本、文件、群聊总结和简单直接回复可以进入统一 `entry` 路由
- 同时作为知识简报、复习反馈、知识缺口主动提问、Research 情报简报和情报反馈的主要推送渠道
- 详细配置见 [docs/deploy.md](docs/deploy.md)，入口设计见 [docs/topics/entry.md](docs/topics/entry.md)

## 项目结构

```text
personalAgent/                  # 项目根目录
├─ data/                        # 上传源文件（checkpoint 持久化于 Postgres）
├─ frontend/                    # React + Vite 前端工程
├─ log/                         # 运行日志目录
└─ src/
   └─ personal_agent/           # Python 应用主包
      ├─ agent/                 # Agent 核心层（runtime / router / workflow planner / orchestration / verifier）
      │  ├─ runtime.py          # AgentRuntime：统一执行入口
      │  ├─ service.py          # AgentService：Web/CLI/飞书使用的应用 facade
      │  ├─ router.py           # DefaultIntentRouter：复合语义 Goal 拆分
      │  ├─ workflow.py         # WorkflowSpec / WorkflowRegistry：固定业务流程真源
      │  ├─ workflow_planner.py # ordered Goals + WorkflowSpec -> ExecutionPlan
      │  ├─ execution_models.py # WorkflowTask / ExecutionPlan / ExecutionStep
      │  ├─ orchestration_contexts.py # LangGraph 各阶段的窄能力 Context
      │  ├─ orchestration_graph.py   # LangGraph entry 总图装配
      │  ├─ orchestration_nodes/     # route / projection / step / ReAct / HITL / tool bridge
      │  ├─ orchestration_models.py  # AgentGraphState / AgentEvent / run snapshot
      │  └─ verifier.py         # AnswerVerifier：回答证据校验
      ├─ capture/               # 采集编排、provider 和抽取工具层
      ├─ cli/                   # 命令行入口层
      ├─ core/                  # 配置、日志、核心数据模型、长文分块
      ├─ feishu/                # 飞书接入（service / SDK client / 消息解析 / Review Digest 命令）
      ├─ graphiti/              # Graphiti、Neo4j、LLM、Embedding、文档 episode 规范化接入
      ├─ insight/               # 知识孤岛/矛盾检测、主动缺口问题 Job 与 Scheduler
      ├─ knowledge/             # 同主题知识整理、综合笔记与 supersede 编排
      ├─ memory/                # 工作记忆与受限会话线索（MemoryFacade / WorkingMemory）
      ├─ research/              # 一次性研究、定时订阅、事件聚类、情报简报与反馈
      ├─ review/                # 知识简报、订阅、投递、调度与复习反馈
      ├─ storage/               # Postgres 业务存储层（schema / search / repository 分层）
      ├─ tools/                 # 统一 Tool 抽象与注册中心
      ├─ web/                   # FastAPI Web 接口层
      │  ├─ api.py              # FastAPI app factory、生命周期与静态前端挂载
      │  ├─ context.py          # Web 运行期依赖装配（Agent / Feishu / Digest / Research）
      │  ├─ routes/             # 分组路由（entry / notes / review / research / audit / graph）
      │  └─ auth.py             # AuthMiddleware + RateLimiter
├─ deploy/                      # 外部 cron 等生产部署模板
├─ tests/                       # 单元 + 集成测试（router / workflow / tools / research / memory / API）
└─ evals/                       # Router / RAG / 对话 / 编排 / Research 等质量评测
```

## 关键落点

- 业务持久化：`knowledge_notes`、`review_cards`、`digest_*`、`research_*`、
  `intelligence_digests`、`worker_queue_tasks`、`knowledge_gap_deliveries`、
  workflow/checkpoint/artifact/audit 相关 Postgres 表
- 上传源文件：`data/uploads/`
- 运行日志：`log/run.log`

## 上下文工程

项目将上下文拆分为任务状态、对话线索、检索证据、长期知识和可恢复流程状态：历史对话只辅助理解追问与更正，事实结论应由当前可追溯证据支撑；entry ask 会去除重复历史注入，并对线索长度设置预算。

- [docs/topics/context-engineering.md](docs/topics/context-engineering.md) - 当前上下文管理模式、抗腐化边界与演进方向
- [docs/llm-prompts.md](docs/llm-prompts.md) - 完整的提示词汇编与设计模式总结
- [docs/topics/memory.md](docs/topics/memory.md) - 记忆层存储职责与读写路径
- [docs/review-digest.md](docs/review-digest.md) - 知识简报、订阅投递和复习反馈
- [docs/proactive-knowledge-loop.md](docs/proactive-knowledge-loop.md) - 自动整理与知识缺口主动追问
- [docs/future/scheduled-intelligence-research.md](docs/future/scheduled-intelligence-research.md) - 一次性研究、定时情报、durable worker 和反馈闭环
- [docs/future/agent-tool-workflow-redesign.md](docs/future/agent-tool-workflow-redesign.md) - 跨 workflow 的工具决策、局部工具箱和治理边界

## 文档导航

- 接口说明：[docs/api.md](docs/api.md)
- Workflow 流程：[docs/workflow/README.md](docs/workflow/README.md)
- 环境变量：[docs/env.md](docs/env.md)
- 本地开发与部署：[docs/deploy.md](docs/deploy.md)

## CLI 用法

当前仍保留 CLI 入口：

```bash
uv run python -m personal_agent.main entry "记一下：服务降级是在系统压力过大时，主动关闭非核心能力"
uv run python -m personal_agent.main entry "什么是服务降级？"
uv run python -m personal_agent.main entry "总结一下当前会话内容"
uv run personal-agent research-once "AI Agent" --max-items 5
uv run personal-agent research-subscribe "AI" --schedule-time 09:00 --chat-id oc_xxx
uv run personal-agent research-schedule
uv run personal-agent worker --queue research
```
