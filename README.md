# “数字第二大脑” Agent

一个面向个人知识管理的 AI Agent。

它不是单纯的笔记应用，而是一个把个人输入沉淀为“可采集、可连接、可复习、可问答”长期记忆系统的后端与前端一体化项目。

## 项目目标

这个项目当前聚焦 4 件事：

1. 把零散输入沉淀成结构化笔记
2. 把笔记升级成实体与关系图谱
3. 让问答优先利用图谱关系，而不只是相似度检索
4. 给后续的复习、总结、可视化留出稳定扩展点

## 当前工程的 Agent 结构

| 组件 | 代码落点 | 能力总结 | 文档 |
| --- | --- | --- | --- |
| `入口层` | [web/api.py](src/personal_agent/web/api.py), [feishu/service.py](src/personal_agent/feishu/service.py), [main.py](src/personal_agent/main.py) | 具备 Web API、前端、CLI、飞书多入口，核心请求可以进入统一 Agent 流程 | [docs/topics/entry.md](docs/topics/entry.md) |
| `意图识别 / 路由层` | [agent/router.py](src/personal_agent/agent/router.py), [agent/entry_nodes.py](src/personal_agent/agent/entry_nodes.py) | 通过 `DefaultIntentRouter` 统一处理入口意图，支持 LLM 优先和启发式兜底 | [docs/topics/routing.md](docs/topics/routing.md) |
| `规划层` | [agent/planner.py](src/personal_agent/agent/planner.py), [agent/plan_validator.py](src/personal_agent/agent/plan_validator.py), [agent/replanner.py](src/personal_agent/agent/replanner.py), [agent/orchestration_nodes.py](src/personal_agent/agent/orchestration_nodes.py) | 已具备结构化规划、动态工具校验、阻断式安全门禁、计划节点执行、目标解析、失败重试/重规划和前端计划面板 | [docs/topics/planning.md](docs/topics/planning.md) |
| `运行时 / 编排层` | [agent/runtime.py](src/personal_agent/agent/runtime.py), [agent/orchestration_graph.py](src/personal_agent/agent/orchestration_graph.py), [agent/orchestration_nodes.py](src/personal_agent/agent/orchestration_nodes.py), [agent/orchestration_models.py](src/personal_agent/agent/orchestration_models.py), [agent/graph.py](src/personal_agent/agent/graph.py), [agent/nodes.py](src/personal_agent/agent/nodes.py) | `AgentRuntime` 默认进入 LangGraph entry 总编排，支持 route/plan/step/ReAct/HITL/checkpoint；`AgentService` 是兼容入口并继承 runtime | [docs/topics/runtime.md](docs/topics/runtime.md)、[docs/topics/langgraph-checkpoint.md](docs/topics/langgraph-checkpoint.md) |
| `工具层` | [tools/](src/personal_agent/tools), [capture/service.py](src/personal_agent/capture/service.py), [graphiti/store.py](src/personal_agent/graphiti/store.py) | 具备统一 Tool 协议、注册中心、意图匹配和失败回退链；已注册 `capture_text / capture_url / capture_upload / graph_search / web_search / delete_note` | [docs/topics/tools.md](docs/topics/tools.md) |
| `记忆层` | [memory/](src/personal_agent/memory), [storage/](src/personal_agent/storage), [core/models.py](src/personal_agent/core/models.py) | 有工作记忆、会话摘要、Postgres 长期记忆/问答历史/pending action/cross-session 状态和图谱字段映射 | [docs/topics/memory.md](docs/topics/memory.md) |
| `检索与推理层` | [agent/runtime.py](src/personal_agent/agent/runtime.py), [agent/verifier.py](src/personal_agent/agent/verifier.py), [graphiti/store.py](src/personal_agent/graphiti/store.py) | 支持三层检索回退（图谱 → 本地 → 网络搜索）、Graphiti `node / edge / fact` 优先的语义推理、回答校验、低置信度自修正和 `relation_fact + snippet` 证据锚点；多跳推理、锚点可视化和评测仍可增强 | [docs/topics/retrieval-reasoning.md](docs/topics/retrieval-reasoning.md) |
| `执行与反馈层` | [web/api.py](src/personal_agent/web/api.py), [agent/runtime.py](src/personal_agent/agent/runtime.py), [agent/orchestration_models.py](src/personal_agent/agent/orchestration_models.py) | 支持同步 API、SSE、结构化 `AgentEvent`、run snapshot、LangGraph interrupt/resume、图谱失败降级、异步图谱同步、问答历史记录和前端确认面板 | [docs/topics/execution-feedback.md](docs/topics/execution-feedback.md)、[docs/api.md](docs/api.md) |
| `观测与治理层` | [core/logging_utils.py](src/personal_agent/core/logging_utils.py), [web/auth.py](src/personal_agent/web/auth.py), [tests/](tests) | 具备日志、health、reset、API Key 鉴权、限流、用户隔离、pending action 审计和基础测试；外部工具权限仍可补充 | [docs/topics/observability-governance.md](docs/topics/observability-governance.md) |

## Entry 编排图

[scripts/assets/entry-orchestration.md](scripts/assets/entry-orchestration.md) 是由 [scripts/draw_entry_graph.py](scripts/draw_entry_graph.py) 生成的当前 LangGraph entry 总编排可视化图源，用来对齐 `normalize_entry -> route_intent -> (按需 clarify) / capture / ask / summarize / direct_answer / plan_task -> step / ReAct / HITL -> finalize_entry_result` 的真实节点结构和条件流转关系。运行 `uv run python scripts/draw_entry_graph.py` 可刷新该图；`uv run python scripts/export_thread_checkpoints.py <thread_id>` 会把持久化 checkpoint 导出到 `scripts/assets/`。

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

- 提供无需检索、无需工具的低风险直接回复分支
- 适用于问候、感谢、澄清性问题和简单说明
- LLM 可用时使用小模型简短回答，不可用时退回启发式回复

### 5. Knowledge Lifecycle

- `delete_knowledge` 支持高风险规划和 LangGraph HITL 删除确认
- 删除计划包含 `resolve` 步骤，可通过图谱 episode、本地相似检索、关键词匹配和最近 citations 解析待删笔记
- `delete_note` 工具会创建 pending action 载荷，entry 总图通过 LangGraph interrupt/resume 完成前端确认后继续删除笔记、复习卡和可用的图谱 episode
- 删除 parent note 时自动检测子 chunk 并级联删除
- `solidify_conversation` 已具备草稿生成、`draft_ready` 事件、cross-session 草稿持久化和 `capture_text` 入库工具基础，候选结论抽取仍需增强

### 6. Digest

- 提供最近笔记与到期复习卡片的聚合视图

### 7. Web UI

- 提供基于 `FastAPI + React` 的前后端分离结构
- 前端工作台覆盖 `Capture / Ask / Entity Graph / Relation Graph / Digest / Timeline / Memory` 等视图
- 前端主要围绕采集、问答、历史查看和调试数据管理几个场景展开
- 构建后的 `frontend/dist` 可以由 FastAPI 托管

### 8. Feishu

- 当前以 `官方 Python SDK + 长连接接收事件` 为主
- 文本、文件、群聊总结和简单直接回复可以进入统一 `entry` 路由
- 详细配置见 [docs/deploy.md](docs/deploy.md)，入口设计见 [docs/topics/entry.md](docs/topics/entry.md)

## 项目结构

```text
personalAgent/                  # 项目根目录
├─ data/                        # 上传源文件（checkpoint 持久化于 Postgres）
├─ frontend/                    # React + Vite 前端工程
├─ log/                         # 运行日志目录
└─ src/
   └─ personal_agent/           # Python 应用主包
      ├─ agent/                 # Agent 核心层（runtime / router / planner / orchestration graph / verifier）
      │  ├─ runtime.py          # AgentRuntime：统一执行入口
      │  ├─ service.py          # AgentService：兼容入口，继承 runtime
      │  ├─ router.py           # DefaultIntentRouter：LLM-first 意图分类
      │  ├─ planner.py          # DefaultTaskPlanner：任务步骤分解
      │  ├─ orchestration_graph.py   # LangGraph entry 总图装配
      │  ├─ orchestration_nodes.py   # route / plan / step / ReAct / HITL 节点
      │  ├─ orchestration_models.py  # AgentGraphState / AgentEvent / run snapshot
      │  ├─ graph.py            # capture / ask 等固定分支图
      │  ├─ nodes.py            # capture / ask 基础节点
      │  ├─ entry_nodes.py      # entry 路由节点
      │  └─ verifier.py         # AnswerVerifier：回答证据校验
      ├─ capture/               # 采集编排、provider 和抽取工具层
      ├─ cli/                   # 命令行入口层
      ├─ core/                  # 配置、日志、核心数据模型、长文分块
      ├─ feishu/                # 飞书接入（长连接、文件下载、消息回溯）
      ├─ graphiti/              # Graphiti、Neo4j、LLM、Embedding 接入
      ├─ memory/                # 工作记忆与会话摘要（MemoryFacade / WorkingMemory）
      ├─ storage/               # Postgres 业务存储层
      ├─ tools/                 # 统一 Tool 抽象与注册中心
      ├─ web/                   # FastAPI Web 接口层
      │  ├─ api.py              # API 路由（capture / ask / digest / notes / tools / pending-actions）
      │  └─ auth.py             # AuthMiddleware + RateLimiter
├─ tests/                       # 单元 + 集成测试（300 条：router / planner / validator / executor / replanner / tools / memory / API / CLI / chunking / regression）
└─ evals/                       # ask 质量评测用例
```

## 关键落点

- 业务持久化：`Postgres.knowledge_notes`、`review_cards`、`ask_history`、`pending_actions`、`cross_session_artifacts`
- 上传源文件：`data/uploads/`
- 运行日志：`log/run.log`

## 文档导航

- 接口说明：[docs/api.md](docs/api.md)
- 环境变量：[docs/env.md](docs/env.md)
- 本地开发与部署：[docs/deploy.md](docs/deploy.md)

## CLI 用法

当前仍保留 CLI 入口：

```bash
uv run python -m personal_agent.main entry "记一下：服务降级是在系统压力过大时，主动关闭非核心能力"
uv run python -m personal_agent.main entry "什么是服务降级？"
uv run python -m personal_agent.main entry "总结一下当前会话内容"
```
