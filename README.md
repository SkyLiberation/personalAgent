# “数字第二大脑” Agent

一个面向个人知识生命周期管理的主动式 AI Agent。

它不是单纯的笔记应用或 RAG 问答 Demo，而是一个让个人知识持续完成“采集、连接、检索、验证、
复习、整理、发现缺口、主动触达”的长期记忆系统。工程同时覆盖 Agent runtime、工作流编排、
知识存储、图谱推理、主动任务、治理审计和多端交互。

## 项目目标

这个项目的目标是构建一套可持续演进的“个人知识闭环”，而不只是完成一次采集或回答：

1. **沉淀知识**：把文本、链接、文件和对话结论转成结构化、可分块、可追溯的长期知识。
2. **连接知识**：同时维护原文证据、向量/关键词索引和实体关系图谱，让知识形成可导航网络。
3. **使用知识**：通过本地检索、图谱推理、网络补充和回答校验，生成有证据的回答。
4. **巩固知识**：自动生成复习卡，按订阅产出知识简报，接收反馈并调整后续复习时间。
5. **整理知识**：发现同主题笔记后生成综述，用版本关系标记原知识已被新综述取代。
6. **发现缺口**：识别知识孤岛与潜在矛盾，主动向用户提出少量、可回答的知识缺口问题。
7. **管理生命周期**：支持固化、冲突标记、软删除、确认、快照恢复、审计和幂等执行。
8. **提供 Agent 框架能力**：用 Goal Router、WorkflowPlanner、LangGraph、PolicyEngine 和 ToolGateway
   支撑复合请求、可恢复执行、HITL 和主动后台任务。

整体闭环可以概括为：

```text
Capture / Conversation
  → Notes / Chunks / Review Cards / Knowledge Graph
  → Ask / Evidence / Verification
  → Digest / Review Feedback
  → Consolidation / Supersede
  → Knowledge-gap Detection / Proactive Questions
  → New Knowledge
```

## 当前工程的 Agent 结构

| 组件 | 代码落点 | 能力总结 | 文档 |
| --- | --- | --- | --- |
| `入口层` | [web/api.py](src/personal_agent/web/api.py), [web/routes/](src/personal_agent/web/routes), [feishu/service.py](src/personal_agent/feishu/service.py), [main.py](src/personal_agent/main.py) | 具备 Web API、前端、CLI、飞书多入口，核心请求可以进入统一 Agent 流程 | [docs/topics/entry.md](docs/topics/entry.md) |
| `目标路由 / Workflow 规划层` | [agent/router.py](src/personal_agent/agent/router.py), [agent/workflow_planner.py](src/personal_agent/agent/workflow_planner.py), [agent/execution_models.py](src/personal_agent/agent/execution_models.py) | Router 只拆分语义 Goal；WorkflowPlanner 从 WorkflowSpec 编译跨 workflow 任务 DAG，支持 `ingest → ask` 等复合请求 | [docs/topics/routing.md](docs/topics/routing.md) |
| `Workflow / 执行校验层` | [agent/workflow.py](src/personal_agent/agent/workflow.py), [agent/workflow_validator.py](src/personal_agent/agent/workflow_validator.py), [agent/step_projection_validator.py](src/personal_agent/agent/step_projection_validator.py), [agent/orchestration_nodes/](src/personal_agent/agent/orchestration_nodes/) | workflow-first：`WorkflowSpec` 是工具、风险、确认和拓扑的流程真源；Orchestrator 只消费编译后的 ExecutionPlan | [docs/topics/workflow-step-projection.md](docs/topics/workflow-step-projection.md) |
| `运行时 / 编排层` | [agent/runtime.py](src/personal_agent/agent/runtime.py), [agent/orchestration_contexts.py](src/personal_agent/agent/orchestration_contexts.py), [agent/orchestration_graph.py](src/personal_agent/agent/orchestration_graph.py), [agent/orchestration_nodes/](src/personal_agent/agent/orchestration_nodes/), [agent/orchestration_models.py](src/personal_agent/agent/orchestration_models.py) | `AgentRuntime` 作为 composition root 显式装配窄 Graph Context；LangGraph 总编排支持 route/workflow projection/step/ReAct/HITL/checkpoint；`AgentService` 是应用 facade | [docs/topics/runtime.md](docs/topics/runtime.md)、[docs/workflow/entry-router-plan-react-output-flow.md](docs/workflow/entry-router-plan-react-output-flow.md) |
| `工具层` | [tools/](src/personal_agent/tools), [capture/service.py](src/personal_agent/capture/service.py), [graphiti/store.py](src/personal_agent/graphiti/store.py) | 具备统一 Tool 协议、ToolGateway、PolicyEngine、幂等与审计；覆盖 capture、graph/web search、delete/restore、consolidate 等知识操作 | [docs/topics/tools.md](docs/topics/tools.md) |
| `记忆层` | [memory/](src/personal_agent/memory), [storage/](src/personal_agent/storage), [core/models.py](src/personal_agent/core/models.py) | 有受限会话线索、Postgres 长期记忆/问答历史、LangGraph checkpoint 和图谱字段映射 | [docs/topics/memory.md](docs/topics/memory.md)、[docs/topics/context-engineering.md](docs/topics/context-engineering.md) |
| `检索与推理层` | [agent/runtime.py](src/personal_agent/agent/runtime.py), [agent/verifier.py](src/personal_agent/agent/verifier.py), [graphiti/store.py](src/personal_agent/graphiti/store.py) | 支持三层检索回退（图谱 → 本地 → 网络搜索）、Graphiti `node / edge / fact` 优先的语义推理、回答校验、低置信度自修正和 `relation_fact + snippet` 证据锚点；多跳推理、锚点可视化和评测仍可增强 | [docs/topics/retrieval-reasoning.md](docs/topics/retrieval-reasoning.md) |
| `主动知识循环` | [review/](src/personal_agent/review), [insight/](src/personal_agent/insight), [tools/consolidate_notes.py](src/personal_agent/tools/consolidate_notes.py) | 生成并投递复习简报、接收复习反馈、检测知识孤岛/矛盾并主动追问、将同主题笔记整理为综述并建立 supersede 关系 | [docs/review-digest.md](docs/review-digest.md)、[docs/proactive-knowledge-loop.md](docs/proactive-knowledge-loop.md) |
| `执行与反馈层` | [web/routes/](src/personal_agent/web/routes), [agent/runtime.py](src/personal_agent/agent/runtime.py), [agent/orchestration_models.py](src/personal_agent/agent/orchestration_models.py) | 支持同步 API、SSE、结构化 `AgentEvent`、run snapshot、LangGraph interrupt/resume、图谱失败降级、异步图谱同步、问答历史记录和前端确认面板 | [docs/topics/execution-feedback.md](docs/topics/execution-feedback.md)、[docs/api.md](docs/api.md) |
| `观测与治理层` | [core/logging_utils.py](src/personal_agent/core/logging_utils.py), [web/auth.py](src/personal_agent/web/auth.py), [tests/](tests) | 具备日志、health、reset、API Key 鉴权、限流、用户隔离和基础测试；外部工具权限仍可补充 | [docs/topics/observability-governance.md](docs/topics/observability-governance.md) |

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
- 问答支持 `session_id` 会话上下文和服务端问答历史持久化
- Web 侧提供同步问答和 `SSE` 返回方式；`ask_stream` 已升级为模型 token 流，边生成边推送
- 图谱问答会构造 `relation_fact + snippet` 证据锚点，前端支持点击 citation 自动定位并高亮回答中的对应证据片段
- 问答历史支持关键词搜索、单条删除和按会话删除

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

- `consolidate_notes` 工具可以读取多条同主题笔记并生成一篇新的综合笔记
- 新综述进入标准 capture/ingestion 链路，继续获得 chunk、review card 和 graph sync 能力
- 原笔记会通过版本关系标记为被新综述 supersede，保留知识演进轨迹
- 当前可通过 `AgentService.execute_consolidate`、内部任务或工具调用触发
- 当前尚未增加“把关于 X 的笔记整理成一篇”自然语言 Intent；该入口需独立增加 Goal/Workflow

详见 [主动知识循环](docs/proactive-knowledge-loop.md#2-自动主题整理consolidate_notes-工具)。

### 8. Proactive Knowledge-gap Questions

- `KnowledgeGapAnalyzer` 会结合本地笔记和图谱检测知识孤岛与潜在矛盾
- 系统会把检测结果整理为少量主动问题，而不是一次推送大量提醒
- 复用知识简报的订阅与飞书投递目标，但使用独立调度时间
- `knowledge_gap_deliveries` 按订阅和日期做跨重启幂等，避免同日重复打扰
- 图谱不可用或 LLM 改写失败时具备确定性降级路径
- 单次问题数量由 `max_gaps_per_run` 控制

详见 [知识缺口主动追问](docs/proactive-knowledge-loop.md#1-知识缺口主动追问)。

### 9. Web UI

- 提供基于 `FastAPI + React` 的前后端分离结构
- 前端工作台覆盖 `Capture / Ask / Entity Graph / Relation Graph / Digest / Timeline / Memory` 等视图
- 前端主要围绕采集、问答、历史查看和调试数据管理几个场景展开
- 构建后的 `frontend/dist` 可以由 FastAPI 托管

### 10. Feishu

- 当前以 `官方 Python SDK + 长连接接收事件` 为主
- 文本、文件、群聊总结和简单直接回复可以进入统一 `entry` 路由
- 同时作为知识简报、复习反馈和知识缺口主动提问的主要推送渠道
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
      ├─ memory/                # 工作记忆与受限会话线索（MemoryFacade / WorkingMemory）
      ├─ review/                # 知识简报、订阅、投递、调度与复习反馈
      ├─ storage/               # Postgres 业务存储层（schema / search / repository 分层）
      ├─ tools/                 # 统一 Tool 抽象与注册中心
      ├─ web/                   # FastAPI Web 接口层
      │  ├─ api.py              # FastAPI app factory、生命周期与静态前端挂载
      │  ├─ context.py          # Web 运行期依赖装配（Agent / Feishu / Review Digest）
      │  ├─ routes/             # 分组路由（system / entry stream-upload-runs / digest / notes / review / audit / graph）
      │  └─ auth.py             # AuthMiddleware + RateLimiter
├─ tests/                       # 单元 + 集成测试（router / workflow / orchestration / proactive loop / tools / memory / API）
└─ evals/                       # ask 质量评测用例
```

## 关键落点

- 业务持久化：`knowledge_notes`、`review_cards`、`ask_history`、`digest_*`、
  `knowledge_gap_deliveries`、workflow/artifact/audit 相关 Postgres 表
- 上传源文件：`data/uploads/`
- 运行日志：`log/run.log`

## 上下文工程

项目将上下文拆分为任务状态、对话线索、检索证据、长期知识和可恢复流程状态：历史对话只辅助理解追问与更正，事实结论应由当前可追溯证据支撑；entry ask 会去除重复历史注入，并对线索长度设置预算。

- [docs/topics/context-engineering.md](docs/topics/context-engineering.md) - 当前上下文管理模式、抗腐化边界与演进方向
- [docs/llm-prompts.md](docs/llm-prompts.md) - 完整的提示词汇编与设计模式总结
- [docs/topics/memory.md](docs/topics/memory.md) - 记忆层存储职责与读写路径
- [docs/review-digest.md](docs/review-digest.md) - 知识简报、订阅投递和复习反馈
- [docs/proactive-knowledge-loop.md](docs/proactive-knowledge-loop.md) - 自动整理与知识缺口主动追问

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
```
