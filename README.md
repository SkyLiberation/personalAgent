# “数字第二大脑” Agent

一个面向个人知识生命周期管理的主动式 AI Agent。

它不是单纯的笔记应用或 RAG 问答 Demo，而是一个让个人知识持续完成“采集、连接、检索、验证、
复习、整理、研究、发现缺口、主动触达”的长期认知系统。工程同时覆盖 Agent runtime、工作流编排、
知识存储、图谱推理、外部情报研究、主动任务、治理审计和多端交互。

顶层框架不是“让模型输出 JSON”，而是一条可信决策与事实链：

```text
模型提出开放语义 Proposal
  -> Admission / Policy 确定性准入
  -> Gateway / Executor 执行并产生事实
  -> Verifier 判断语义满足
  -> Completion Gate 关闭用户结果契约
```

短动态请求、固定事务和 durable 动态长任务分别进入 Conversation、明确 Application Workflow
和 Investigation Project。实现可以更换 Provider、Tool Calling 协议或编排技术，但 Proposal
不是权限、模型自述不是执行事实、Tool success 不是用户目标完成。

## 项目目标

这个项目的目标是构建一套可持续演进的“个人知识与外部情报闭环”，让 Agent 不只回答一次问题，
还能够长期积累知识、维护知识质量、跟踪外部变化并主动行动。当前目标能力包括：

1. **统一多端入口**：Web、CLI、飞书文本/文件和 SSE 请求进入同一 Conversation Use Case；模型输出 typed answer/tool/agent proposal，Application 负责预算、执行与验证。
2. **多来源知识采集**：接收文本、网页链接、PDF/上传文件和对话结论，完成正文提取、结构化分块、来源指纹、重复检测、摘要、标签和引用定位。
3. **长期记忆与知识连接**：以 Postgres 分别保存知识事实、Interaction journal、领域运行状态和
   Artifact ref，以 Graphiti/Neo4j 保存可重建的实体、关系、事实和 episode 检索投影。
4. **多源检索与证据问答**：组合图谱、本地语义/关键词、结构化文档、情景记忆、反思记忆和公网搜索，经过融合、去冗余、上下文压缩、生成与事实校验后输出可追溯回答。
5. **知识生命周期管理**：支持会话固化、同主题知识整理、supersede、冲突标记、软删除、删除快照、人工确认、幂等执行和恢复。
6. **复习与知识巩固**：采集时生成复习卡，按用户时区生成和投递知识简报，通过 Web/飞书接收“记得、忘了、稍后”反馈并调整复习计划。
7. **主动知识维护**：检测知识孤岛、薄弱连接和潜在矛盾，主动提出少量问题；按主题生成综合笔记，并保留知识演进与来源关系。
8. **一次性外部研究**：围绕指定主题规划多个查询，调用公网搜索和网页抓取，进行来源归一、事件聚类、重复消除、可信度判断和个人知识关联，生成结构化研究简报。
9. **周期性情报订阅**：支持“每天 9 点收集 AI 新闻”等订阅；外部 cron 负责到期扫描和入队，Postgres durable worker 负责研究与独立投递任务。
10. **个性化情报反馈**：简报条目支持展开、有用、不感兴趣、收藏和确认入库；反馈会更新订阅偏好，外部事件可带来源和可信度保存为长期知识。
11. **分层恢复语义**：Conversation 从 committed interaction facts 恢复短 ReAct；固定长流程由领域 Workflow 恢复；动态且跨轮次的调查由 durable Investigation Project journal 恢复。
12. **受治理的能力行动**：CapabilityResolver 统一筛选本地工具、MCP、retriever 和 Agent；ToolGateway/AgentGateway 负责权限、ReAct allowlist、超时、限流、HITL、幂等和结构化审计。
13. **后台任务与主动触达**：具备 Postgres durable queue、lease、heartbeat、重试和 dead-letter；支持图谱异步同步、研究任务、研究投递、复习简报与知识缺口提醒，并可通过工具诊断队列与重试失败任务。
14. **多用户安全与可观测性**：提供 API Key、管理员范围、用户数据隔离、日志、health、LangSmith 脱敏 trace、工具/策略审计、run snapshot 和调试重放。
15. **持续质量评测**：测试和 eval 覆盖 Conversation、领域 Workflow、Investigation Project、Capability Resolution、工具治理、RAG 和 Research 质量。
16. **Durable 架构调查**：显式创建跨进程 Investigation Project，支持动态 SubGoal、并行、steering、审批、预算、取消、Evidence Admission 和 Completion Gate。

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
| `入口层` | [adapters/web/api.py](src/personal_agent/adapters/web/api.py), [adapters/web/routes/](src/personal_agent/adapters/web/routes), [adapters/feishu/service.py](src/personal_agent/adapters/feishu/service.py), [adapters/cli/main.py](src/personal_agent/adapters/cli/main.py) | 具备 Web API、前端、CLI、飞书多入口，核心请求可以进入统一 Agent 流程 | [docs/topics/entry.md](docs/topics/entry.md) |
| `Conversation ReAct` | [application/conversation/](src/personal_agent/application/conversation), [orchestration/runtime.py](src/personal_agent/orchestration/runtime.py) | 短生命周期 typed answer/tool/agent loop；恢复只消费 committed messages、Observation、Feedback、usage 和 action order | [docs/summary/core-architecture-current-state.md](docs/summary/core-architecture-current-state.md) |
| `领域 Workflow` | [application/](src/personal_agent/application), [orchestration/worker.py](src/personal_agent/orchestration/worker.py) | 保存、删除恢复、订阅、研究和投递等固定事务由各自 Use Case、状态机与 durable queue 拥有 | [docs/workflow/README.md](docs/workflow/README.md) |
| `Investigation Project` | [application/investigation_project/](src/personal_agent/application/investigation_project), [domain/investigation_project/](src/personal_agent/domain/investigation_project), [infra/storage/postgres_investigation_project.py](src/personal_agent/infra/storage/postgres_investigation_project.py) | 动态路径且跨进程/轮次/审批的调查；Plan 实际驱动 ready/join/coverage，journal 支持恢复、steering、预算和 Completion | [docs/summary/durable-investigation-project-current-state.md](docs/summary/durable-investigation-project-current-state.md) |
| `运行时 / 编排层` | [runtime.py](src/personal_agent/orchestration/runtime.py), [service.py](src/personal_agent/orchestration/service.py), [worker.py](src/personal_agent/orchestration/worker.py) | `AgentRuntime` 集中装配 Port/Adapter；`AgentService` 暴露用例 facade；worker 消费 durable queue，不成为业务事实 owner | [当前核心架构](docs/summary/core-architecture-current-state.md) |
| `工具层` | [tools/](src/personal_agent/tools), [application/capture/service.py](src/personal_agent/application/capture/service.py), [memory/graphiti/store.py](src/personal_agent/memory/graphiti/store.py) | 具备统一 Tool 协议、ToolGateway、PolicyEngine、幂等与审计；覆盖 capture、graph/web search、研究/订阅管理、知识生命周期、worker 诊断、run 诊断、delete/restore、consolidate 等动作 | [docs/topics/tools.md](docs/topics/tools.md) |
| `记忆与事实层` | [application/knowledge/](src/personal_agent/application/knowledge), [memory/](src/personal_agent/memory), [infra/storage/](src/personal_agent/infra/storage) | Interaction journal、Personal Knowledge canonical knowledge、Artifact、Research/Project journal 与可重建检索投影按生命周期分开 | [当前核心架构](docs/summary/core-architecture-current-state.md) |
| `检索与推理层` | [orchestration/ask/](src/personal_agent/orchestration/ask), [application/verifier.py](src/personal_agent/application/verifier.py), [memory/graphiti/store.py](src/personal_agent/memory/graphiti/store.py) | 支持图谱、结构、本地、网络、情景和反思多路召回，RRF/MMR、上下文压缩、反证检索、引用生成和蕴含级校验 | [docs/topics/retrieval-reasoning.md](docs/topics/retrieval-reasoning.md) |
| `主动知识循环` | [application/review/](src/personal_agent/application/review), [application/insight/](src/personal_agent/application/insight), [application/knowledge/](src/personal_agent/application/knowledge) | 生成并投递复习简报、接收复习反馈、检测知识孤岛/矛盾并主动追问、将同主题笔记整理为综述并建立 supersede 关系 | [docs/review-digest.md](docs/review-digest.md)、[docs/proactive-knowledge-loop.md](docs/proactive-knowledge-loop.md) |
| `持续研究层` | [application/research/](src/personal_agent/application/research), [infra/storage/postgres_research_store.py](src/personal_agent/infra/storage/postgres_research_store.py), [adapters/web/routes/research.py](src/personal_agent/adapters/web/routes/research.py) | 支持一次性研究、定时订阅、来源归一、事件聚类、可信度、个人关联、情报简报、反馈偏好和确认入库 | [docs/workflow/research-once-workflow.md](docs/workflow/research-once-workflow.md)、[docs/env.md](docs/env.md#research--定时情报简报) |
| `后台任务 / 调度层` | [orchestration/worker.py](src/personal_agent/orchestration/worker.py), [application/worker_queue.py](src/personal_agent/application/worker_queue.py), [infra/storage/postgres_worker_queue_store.py](src/personal_agent/infra/storage/postgres_worker_queue_store.py) | 应用层定义 queue port，Postgres adapter 提供 lease、heartbeat、重试和 dead-letter，orchestration worker 组合 handler | [docs/deploy.md](docs/deploy.md) |
| `执行与反馈层` | [adapters/web/routes/](src/personal_agent/adapters/web/routes), [application/conversation/](src/personal_agent/application/conversation), [orchestration/worker.py](src/personal_agent/orchestration/worker.py) | 支持同步 API、SSE、typed Observation/Feedback、受治理确认、异步 worker 与 Project projection | [docs/topics/execution-feedback.md](docs/topics/execution-feedback.md)、[docs/api.md](docs/api.md) |
| `观测、治理与评测层` | [kernel/observability.py](src/personal_agent/kernel/observability.py), [adapters/web/auth.py](src/personal_agent/adapters/web/auth.py), [tests/](tests), [evals/](evals) | 具备日志、health、API Key、限流、用户隔离、工具/策略审计、LangSmith 脱敏 trace、执行回放和多类离线质量门禁 | [docs/topics/observability-governance.md](docs/topics/observability-governance.md) |

## 目标入口与执行责任

普通用户只向 Conversation 描述目标；模型按需选择 request-local capability、具体领域 Use Case，
或在目标明确要求跨交互持续和后续控制时创建 Investigation Project。专用 UI/自动化仍可直接调用
同一 Application Use Case。历史 LangGraph 图不再定义这些 canonical owner，当前事实统一见
[核心架构](docs/summary/core-architecture-current-state.md)。

## 当前技术栈

- `Python 3.11+`
- `FastAPI`
- `LangGraph checkpoint packages`（遗留数据/迁移依赖，不是当前目标责任链的共同编排器）
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
- 问答支持 `session_id` 会话线索；回答事实必须来自本轮可见 Evidence，历史助手文本不能替代证据
- Web 侧提供同步问答和 `SSE` 返回方式；`ask_stream` 已升级为模型 token 流，边生成边推送
- 图谱问答会构造 `relation_fact + snippet` 证据锚点，前端支持点击 citation 自动定位并高亮回答中的对应证据片段
- 前端可查看回答、引用、运行和相关执行状态；不同生命周期的恢复事实由各自 journal/store 拥有

### 4. Conversation Interaction

- Web、CLI、飞书文本请求统一进入 `AgentService.converse -> ConversationService.respond`
- 模型每轮产生 `FinalMessage` 或 `ContinueTurnProposal`，Runtime 不从自然语言控制词猜分支
- Tool/Agent Proposal 经 schema、能力、scope、预算和重复 action Admission 后才能执行
- Tool/Agent 结果形成 `ActionObservation`，拒绝形成 `DecisionFeedback`，共同驱动下一模型轮
- 模型不可用、能力不足或信息不足时进入 typed failure/limitation/clarification，不使用关键词
  fallback 生成业务答案
- 当前粗粒度 Application capability 包括 canonical personal knowledge knowledge list、确认式保存、确认式
  删除和 durable investigation handoff；Conversation 只保存跨领域 ref，不复制 delete/Project 状态

### 5. Knowledge Lifecycle

- `KnowledgeLifecycleService` 是删除与恢复的唯一写入口；Conversation 和直接 API 都只能调用该
  owner，prepare 不执行删除
- prepare 只创建 durable operation；确认时用一个 `command_digest` 绑定 canonical payload，重启后仍可继续
- confirm 在单事务中更新 Knowledge Item/Claim、记录 Personal Knowledge 状态事件并写 Receipt；replay 返回同一 Receipt
- restore 引用已执行的 delete command，并按 delete receipt 中的 previous states 精确恢复
- `solidify_conversation` 已具备草稿生成、`draft_ready` 事件和 `capture_text` 入库工具基础
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

- 知识整理由结构化 Goal 触发 `knowledge_consolidate` Procedure，按主题选择相关笔记并生成综合笔记
- 新综述进入标准 capture/ingestion 链路，继续获得 chunk、review card 和 graph sync 能力
- 原笔记会通过版本关系标记为被新综述 supersede，保留知识演进轨迹
- Review Digest、知识整理、知识缺口检查均可由自然语言 Goal 触发；scheduler 与 CLI 复用同一应用用例

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

- `research_run` Procedure 编排 prepare run、plan queries、collect sources、cluster events、rank events、compose digest 和最终呈现
- 查询计划会驱动 `web_search` 和 `capture_url`，并通过 `graph_search` 对照个人已有知识
- 搜索结果按 canonical URL、内容指纹、标题语义、实体和时间窗口归一为事件，减少转载和重复新闻
- 事件区分 `verified / reported / uncertain / conflicted`，简报保留来源链接、可信度和个人知识关联
- `create_research_subscription` 支持“每天 9 点收集 AI 新闻”等自然语言订阅
- 订阅、运行、来源、事件、简报、投递和反馈均持久化到 Postgres
- 生产环境使用外部 cron 调用一次性 scheduler 入队，独立 durable worker 执行研究任务并独立投递
- 研究任务和投递任务解耦；投递失败可独立重试，不重复执行搜索
- 飞书条目支持 `N1 展开 / 有用 / 不感兴趣 / 收藏 / 入库`
- 用户反馈会更新订阅内容偏好；“入库”会保存事件摘要、可信度与来源

当前一次性研究流程见 [research_once workflow](docs/workflow/research-once-workflow.md)，订阅、调度和运行配置见 [Research环境配置](docs/env.md#research--定时情报简报)；尚未落地的来源验证与事件触发能力见 [持续研究 P1/P2](docs/future/scheduled-intelligence-research.md)。

### 10. Agent Harness, Capability & Durable Execution

- Conversation、明确 Application Workflow 和 Investigation Project 按路径动态性与 durable
  边界分担复杂度，不存在覆盖所有请求的通用 Task/GoalGraph/Planner 主链
- Conversation 模型逐轮选择 Tool 或 Agent Proposal；Admission 约束 schema、能力、scope、预算、
  重复 action 和并发安全
- 固定事务由对应 Use Case/Domain state machine 拥有，模型不能重排确认、执行、Receipt 和补偿
- Investigation Project 的 accepted Plan 驱动 ready set、dispatch、join、coverage、repair 和
  Completion；普通 Conversation 不持久化无消费者 Plan
- `ToolGateway`/`AgentGateway` 独占受治理执行，Adapter 只做协议转换
- AgentGateway 主链使用 durable submit/poll；PostgreSQL run repository 提供幂等 submission、lease、fencing 与 cancel race 收敛
- 工具契约包含 Pydantic schema、风险、副作用、权限域、确认、幂等、超时、重试、限流和域名白名单
- Postgres worker queue 提供 durable enqueue、lease、heartbeat、优先级、重试和 dead-letter
- E2E catalog、trace archive 和 release gate 分别拥有证据分类、执行事实与发布准入

### 11. Observability, Governance & Evaluation

- API Key 与管理员 Key 提供用户身份和跨用户管理边界
- 工具调用和策略决策写入独立 Postgres 审计表
- LangSmith trace 默认脱敏，不上传用户正文和工具参数
- Interaction/Project journal、execution event、trace archive 和 receipt replay 支持问题定位
- `tests/` 覆盖单元、集成、Postgres、API 和完整 Agent flow
- `evals/` 覆盖 Conversation、Gateway、Personal Knowledge/RAG、Research、Investigation 和组合用户旅程
- Research 评测包含事件召回/精度、去重质量、一手来源率和不确定性校准

### 12. Web UI

- 提供基于 `FastAPI + React` 的前后端分离结构
- 前端工作台覆盖 `Capture / Ask / Entity Graph / Relation Graph / Digest / Timeline / Memory` 等视图
- 前端主要围绕采集、问答、历史查看和调试数据管理几个场景展开
- 构建后的 `frontend/dist` 可以由 FastAPI 托管

### 13. Feishu

- 当前以 `官方 Python SDK + 长连接接收事件` 为主
- 文本对话进入统一 Conversation 用例；文件、群聊与主动投递进入对应明确 Application 能力
- 同时作为知识简报、复习反馈、知识缺口主动提问、Research 情报简报和情报反馈的主要推送渠道
- 详细配置见 [docs/deploy.md](docs/deploy.md)，入口设计见 [docs/topics/entry.md](docs/topics/entry.md)

## 项目结构

```text
personalAgent/                  # 项目根目录
├─ data/                        # 上传源文件、Artifact 与 Interaction journal
├─ frontend/                    # React + Vite 前端工程
├─ log/                         # 运行日志目录
└─ src/
   └─ personal_agent/           # Python 应用主包
      ├─ adapters/              # Web、CLI、飞书与外部协议入口
      ├─ application/
      │  ├─ conversation/       # 短 typed Interaction loop
      │  ├─ investigation_project/ # durable Project 应用编排
      │  ├─ personal knowledge/          # Artifact/Evidence/Claim/Knowledge 生命周期
      │  ├─ knowledge_lifecycle/# 删除、恢复、Command 与 Receipt
      │  ├─ capture/            # 文本、URL、上传采集
      │  ├─ research/           # 一次性研究、订阅、Digest 与 Delivery
      │  └─ review/, insight/   # 复习、反馈与知识缺口
      ├─ domain/
      │  └─ investigation_project/ # Project aggregate 与状态机
      ├─ orchestration/         # Composition Root、facade、worker、Ask pipeline
      ├─ governance/            # Tool registry、Policy、Gateway、Admission
      ├─ agents/                # AgentGateway 与 A2A Adapter
      ├─ capabilities/          # Model/Interaction/Procedure Port 与能力投影
      ├─ infra/                 # Provider 与 PostgreSQL/Artifact Adapter
      ├─ memory/                # Graphiti、检索和受限记忆能力
      ├─ runtime/               # 受限 Procedure/runtime contracts
      └─ tools/                 # Agent 可见 Tool schema 与业务 Adapter
├─ deploy/                      # 外部 cron 等生产部署模板
├─ tests/                       # Unit、Contract、Integration 与 Runtime Conformance
└─ evals/                       # 产品 E2E、组合旅程、复杂 loop 与质量评测
```

## 关键落点

- 业务持久化：`knowledge_notes`、`review_cards`、`digest_*`、`research_*`、
  `intelligence_digests`、`worker_queue_tasks`、`knowledge_gap_deliveries`、
  workflow/journal/artifact/audit 相关 Postgres 表
- 上传源文件：`data/uploads/`
- 运行日志：`log/run.log`

## 上下文工程

项目将上下文拆分为 Conversation committed inputs、检索证据、Artifact、长期知识和 durable
Project journal：历史对话只辅助理解追问与更正，事实结论必须由当前可追溯证据支撑。

- [docs/llm-prompts.md](docs/llm-prompts.md) - 完整的提示词汇编与设计模式总结
- [docs/review-digest.md](docs/review-digest.md) - 知识简报、订阅投递和复习反馈
- [docs/proactive-knowledge-loop.md](docs/proactive-knowledge-loop.md) - 自动整理与知识缺口主动追问
- [docs/future/README.md](docs/future/README.md) - 仅包含尚未落地且由目标 E2E 驱动的未来设计
- [docs/future/trusted-agent-runtime-evolution.md](docs/future/trusted-agent-runtime-evolution.md) - 当前文档、架构门禁和 clean release 收敛
- [docs/future/scheduled-intelligence-research.md](docs/future/scheduled-intelligence-research.md) - 持续研究尚未落地的来源验证、connector 和事件触发 P1/P2
- [docs/summary/core-architecture-current-state.md](docs/summary/core-architecture-current-state.md) - 框架理念、系统分层、目标责任链、知识与运行时当前事实

## 文档导航

- 接口说明：[docs/api.md](docs/api.md)
- Agent/Procedure 流程：[docs/workflow/README.md](docs/workflow/README.md)
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
uv run personal-agent worker --queue investigation
```
