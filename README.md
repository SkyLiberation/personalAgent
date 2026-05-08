# “数字第二大脑” Agent

一个面向个人知识管理的 AI Agent。

它不是单纯的笔记应用，而是一个把个人输入沉淀为“可采集、可连接、可复习、可问答”长期记忆系统的后端与前端一体化项目。

## 项目目标

这个项目当前聚焦 4 件事：

1. 把零散输入沉淀成结构化笔记
2. 把笔记升级成实体与关系图谱
3. 让问答优先利用图谱关系，而不只是相似度检索
4. 给后续的复习、总结、可视化留出稳定扩展点

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

## 当前能力

### 1. Capture

- 接收文本输入
- 支持前端文件上传
- 自动生成标题、摘要、标签
- 保存为本地 `KnowledgeNote`
- 自动生成复习卡片 `ReviewCard`
- 可选写入 Graphiti 图谱

当前上传策略：

- 纯文本类文件：直接读取内容并进入 capture
- 图片、音频、PDF 等文件：先保存文件并记录为“文件元信息笔记”
- 更深的 OCR / PDF 解析 / ASR 还没有接入
- 上传文件默认先快速入库，再在后台执行 Graphiti 同步

### 2. Knowledge Connection

- 默认使用本地 JSON 存储与简单匹配
- 启用 Graphiti 后，升级为实体抽取 + 关系抽取 + 图谱写入
- 每条笔记会记录：
  - `graph_episode_uuid`
  - `entity_names`
  - `relation_facts`

### 3. Ask

- 图谱关闭时：走本地问答链路
- 图谱开启时：优先基于实体和关系事实返回结果
- 支持把图谱命中的 episode 反查成本地笔记引用
- 支持 `SSE` 实时展示回答
- 支持把问答历史持久化到 `Postgres`
- 前端支持查看服务端问答历史

### 4. Digest

- 查看最近新增笔记
- 查看到期复习卡片

### 5. Web UI

- 提供基于 `FastAPI + React` 的前后端分离架构
- 前端采用左侧导航多 Tab 工作台
- 当前视图包括：
  - `Capture`
  - `Ask`
  - `Entity Graph`
  - `Relation Graph`
  - `Digest`
  - `Timeline`
  - `Memory`
- 前端支持调用 `capture / capture/upload / ask / ask-history / digest / notes`
- `Ask` 页面支持 SSE 实时回答和历史问题回看
- 构建后 `frontend/dist` 可由 FastAPI 自动托管

## 已接入的图谱能力

当前已经接入并验证过以下链路：

- `DeepSeek` 作为聊天/抽取模型
- `DashScope text-embedding-v4` 作为 embedding 模型
- `Graphiti` 作为知识图谱抽取与检索层
- `Neo4j` 作为图数据库

### 自定义本体

本体定义位于 [graphiti_ontology.py](src/personal_agent/graphiti_ontology.py)：

- `Person`
- `Project`
- `Concept`
- `Organization`
- `Source`

### 兼容层说明

由于 `DeepSeek` 和 `Graphiti` 的结构化输出约定并不完全一致，项目里增加了兼容层：

- [deepseek_compatible_client.py](src/personal_agent/deepseek_compatible_client.py)
- [dashscope_compatible_embedder.py](src/personal_agent/dashscope_compatible_embedder.py)
- [graphiti_store.py](src/personal_agent/graphiti_store.py)

当前已经兼容这些常见差异：

- 列表根对象自动包装为 Graphiti 期望的对象结构
- `entity -> name`
- `type / entity_type -> entity_type_id`
- `facts -> edges`
- `source_entity / target_entity -> source_entity_name / target_entity_name`
- 字典式摘要转换为 `summaries: [{name, summary}]`
- DashScope embedding 单批限制自动分片

## 当前验证状态

这条链路已经做过真实联调：

- `Neo4j` 已成功启动并可连接
- `Postgres` 已成功启动并可连接
- `capture()` 已成功写入 Graphiti episode
- `POST /api/capture` 已成功返回：
  - `graph_episode_uuid`
  - `entity_names`
  - `relation_facts`
- `POST /api/ask` 已成功走图谱检索
- `GET /api/ask/stream` 已成功返回 `status / metadata / answer_delta / done` 事件流
- `GET /api/ask-history` 已成功从 `Postgres` 读取服务端问答历史

例如，下面这类输入已经能抽出图谱关系：

```text
Bob 在搜索系统升级项目里决定先上 BM25 + 向量召回，再逐步引入 reranker。
团队认为索引热更新可以降低发布风险。
```

可抽出的关系示例：

- `Bob DECIDES_TO_USE BM25`
- `Bob DECIDES_TO_USE 向量召回`
- `Bob PLANS_TO_USE reranker`

## 已知限制

当前版本已经可用，但还不是最终产品态，主要限制有：

1. `ask` 的相关性排序还比较粗，跨主题笔记可能会串题
2. `citation` 和图谱 `relation_fact` 的绑定还不够精细
3. 目前 `capture` 主要面向纯文本，还没扩展到网页、PDF、OCR、ASR
4. SSE 现在是服务端按段推送现有答案，不是直接透传上游模型 token 流
5. `ask history` 已经服务端持久化，但还没有做删除、搜索和多用户隔离增强

## 项目结构

```text
personalAgent/
├─ README.md
├─ .env.example
├─ docker-compose.yml
├─ pyproject.toml
├─ data/
├─ frontend/
│  ├─ package.json
│  └─ src/
└─ src/
   └─ personal_agent/
      ├─ __init__.py
      ├─ ask_history_store.py
      ├─ api.py
      ├─ config.py
      ├─ dashscope_compatible_embedder.py
      ├─ deepseek_compatible_client.py
      ├─ graph.py
      ├─ graphiti_ontology.py
      ├─ graphiti_store.py
      ├─ main.py
      ├─ memory_store.py
      ├─ models.py
      ├─ nodes.py
      └─ service.py
```

## 本地目录与数据流

当前工程的本地工作区目录是：

`D:\mySoft\workspace\personalAgent`

这也是项目根目录。当前数据在本地的主要落点如下：

- 代码与配置：
  - `src/personal_agent/`
  - `frontend/`
  - `.env`
  - `docker-compose.yml`
- 本地知识数据：
  - `data/notes.json`
  - `data/reviews.json`
- 上传文件原件：
  - `data/uploads/`
- 服务端问答历史：
  - `Postgres.ask_history`
- 运行日志：
  - `log/run.log`

### Capture 数据流

#### 1. 文本输入

前端或 API 提交文本后，会经过：

- `capture -> enrich -> link -> schedule_review`

然后落盘为：

- 笔记：`data/notes.json`
- 复习任务：`data/reviews.json`

如果开启了 Graphiti，还会额外写入：

- `Neo4j`

也就是说，图谱数据不保存在本地 JSON 文件中，而是存进图数据库。

#### 2. 文件上传

前端上传文件后，当前流程是：

1. 文件原件先保存到 `data/uploads/`
2. 后端根据文件类型生成 capture 输入
3. 再像普通文本一样进入 `notes.json / reviews.json`
4. 如果 Graphiti 可用，再尝试写入图谱

当前支持策略：

- 文本类文件：直接读取正文内容后 capture
- 图片、音频、PDF 等非文本文件：先记录文件元信息为笔记

上传笔记会记录图谱同步状态：

- `idle`
- `pending`
- `synced`
- `failed`

因此，上传后的数据会同时存在两处：

- 原始文件在 `data/uploads/`
- 结构化笔记在 `data/notes.json`

### Ask 数据流

当前问答流程分两条：

#### 1. 普通问答

- 前端调用 `POST /api/ask`
- 后端优先走图谱问答，失败时回退到本地问答链
- 问答完成后把历史写入 `Postgres.ask_history`

#### 2. SSE 实时问答

- 前端调用 `GET /api/ask/stream`
- 后端返回：
  - `status`
  - `metadata`
  - `answer_delta`
  - `done`
- 前端一边展示实时回答，一边在问答完成后从服务端刷新历史列表

## 核心数据模型

### `KnowledgeNote`

表示一条沉淀后的知识笔记，当前包含：

- 基础信息：`id`、`user_id`、`title`、`content`、`summary`
- 分类信息：`tags`
- 关联信息：`related_note_ids`
- 图谱信息：`graph_episode_uuid`、`entity_names`、`relation_facts`

### `ReviewCard`

表示一条待复习任务，当前包含：

- `prompt`
- `answer_hint`
- `interval_days`
- `due_at`

### `AskHistoryRecord`

表示一条服务端保存的问答历史，当前包含：

- `user_id`
- `question`
- `answer`
- `citations`
- `graph_enabled`
- `created_at`

## 后端接口

提供 health、capture、ask（含 SSE 流式）、ask-history、digest、notes 等 REST 接口，详见 [docs/api.md](docs/api.md)。

## 环境变量

涵盖基础配置、LLM、Embedding 及 Graphiti 启用条件，详见 [docs/env.md](docs/env.md)。

## 本地开发与部署

涵盖依赖安装、环境变量配置、基础设施启动与前后端运行，详见 [docs/deploy.md](docs/deploy.md)。

## CLI 用法

当前仍保留 CLI 入口：

```bash
uv run python -m personal_agent.main capture --text "服务降级是在系统压力过大时，主动关闭非核心能力"
uv run python -m personal_agent.main ask --question "什么是服务降级？"
uv run python -m personal_agent.main digest
```

## 前端与后端版本

当前仓库里的主要版本：

- 后端依赖定义见 [pyproject.toml](pyproject.toml)
- 前端依赖定义见 [frontend/package.json](frontend/package.json)

关键版本包括：

- `fastapi >= 0.121.0`
- `graphiti-core >= 0.29.0`
- `langgraph >= 0.2.0`
- `react 19.2.6`
- `vite 8.0.11`
- `typescript 6.0.3`

## 后续建议

最值得继续推进的方向是：

1. 优化 `ask` 的检索排序，减少跨主题串题
2. 让 `citation` 与 `relation_fact` 精确绑定
3. 让 `Entity Graph / Relation Graph / Timeline` 支持点击过滤和联动
4. 扩展 `capture` 到网页、PDF、语音和 OCR
5. 用真实生成式答案替代当前“关系事实拼接式”回答
6. 给 `ask history` 增加搜索、删除和会话维度
