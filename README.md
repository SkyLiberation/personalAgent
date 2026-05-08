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

### 4. Digest

- 查看最近新增笔记
- 查看到期复习卡片

### 5. Web UI

- 提供基于 `FastAPI + React` 的前后端分离架构
- 前端支持调用 `capture / ask / digest / notes`
- 构建后 `frontend/dist` 可由 FastAPI 自动托管

## 已接入的图谱能力

当前已经接入并验证过以下链路：

- `DeepSeek` 作为聊天/抽取模型
- `DashScope text-embedding-v4` 作为 embedding 模型
- `Graphiti` 作为知识图谱抽取与检索层
- `Neo4j` 作为图数据库

### 自定义本体

本体定义位于 [graphiti_ontology.py](/d:/mySoft/workspace/personalAgent/src/personal_agent/graphiti_ontology.py)：

- `Person`
- `Project`
- `Concept`
- `Organization`
- `Source`

### 兼容层说明

由于 `DeepSeek` 和 `Graphiti` 的结构化输出约定并不完全一致，项目里增加了兼容层：

- [deepseek_compatible_client.py](/d:/mySoft/workspace/personalAgent/src/personal_agent/deepseek_compatible_client.py)
- [dashscope_compatible_embedder.py](/d:/mySoft/workspace/personalAgent/src/personal_agent/dashscope_compatible_embedder.py)
- [graphiti_store.py](/d:/mySoft/workspace/personalAgent/src/personal_agent/graphiti_store.py)

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
- `capture()` 已成功写入 Graphiti episode
- `POST /api/capture` 已成功返回：
  - `graph_episode_uuid`
  - `entity_names`
  - `relation_facts`
- `POST /api/ask` 已成功走图谱检索

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
4. 图谱结果已经可写入和检索，但前端还没有图谱可视化

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

因此，上传后的数据会同时存在两处：

- 原始文件在 `data/uploads/`
- 结构化笔记在 `data/notes.json`

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

## 后端接口

主要接口定义位于 [api.py](/d:/mySoft/workspace/personalAgent/src/personal_agent/api.py)。

### `GET /api/health`

返回服务状态与图谱配置状态。

示例响应：

```json
{
  "status": "ok",
  "graphiti": {
    "enabled": true,
    "configured": true,
    "base_url": "https://api.deepseek.com",
    "model": "deepseek-v4-flash",
    "embedding_base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "embedding_model": "text-embedding-v4"
  }
}
```

### `POST /api/capture`

请求体：

```json
{
  "text": "Bob 在搜索系统升级项目里决定先上 BM25 + 向量召回",
  "source_type": "note",
  "user_id": "default"
}
```

### `POST /api/capture/upload`

使用 `multipart/form-data` 上传文件。

表单字段：

- `file`
- `user_id`

### `POST /api/ask`

请求体：

```json
{
  "question": "搜索系统升级项目里，Bob 先决定采用什么方案？",
  "user_id": "default"
}
```

### `GET /api/digest`

返回最近笔记与到期复习任务。

### `GET /api/notes`

返回当前用户的全部本地笔记。

## 环境变量

参考 [.env.example](/d:/mySoft/workspace/personalAgent/.env.example)。

### 基础配置

```env
PERSONAL_AGENT_DATA_DIR=./data
PERSONAL_AGENT_DEFAULT_USER=default
PERSONAL_AGENT_GRAPHITI_ENABLED=false
PERSONAL_AGENT_GRAPHITI_URI=bolt://localhost:7687
PERSONAL_AGENT_GRAPHITI_USER=neo4j
PERSONAL_AGENT_GRAPHITI_PASSWORD=password
PERSONAL_AGENT_GRAPHITI_GROUP_PREFIX=personal-agent
```

### LLM 配置

```env
OPENAI_BASE_URL=https://api.deepseek.com
OPENAI_API_KEY=your_llm_key
OPENAI_MODEL=deepseek-v4-flash
OPENAI_SMALL_MODEL=deepseek-v4-flash
```

### Embedding 配置

```env
EMBEDDING_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
EMBEDDING_API_KEY=your_embedding_key
OPENAI_EMBEDDING_MODEL=text-embedding-v4
```

只有同时满足下面条件，Graphiti 才会真正启用：

1. `PERSONAL_AGENT_GRAPHITI_ENABLED=true`
2. Neo4j 可连接
3. `OPENAI_API_KEY`、`OPENAI_BASE_URL`、`OPENAI_MODEL` 已配置
4. `EMBEDDING_API_KEY` 或 `OPENAI_API_KEY` 可用
5. `EMBEDDING_BASE_URL` 或 `OPENAI_BASE_URL` 可用

## 本地开发

### 1. 安装 Python 依赖

```bash
uv sync
```

### 2. 安装前端依赖

```bash
cd frontend
npm install
```

### 3. 配置环境变量

```bash
cp .env.example .env
```

然后填写你的：

- `OPENAI_API_KEY`
- `OPENAI_BASE_URL`
- `OPENAI_MODEL`
- `EMBEDDING_API_KEY`
- `EMBEDDING_BASE_URL`
- `OPENAI_EMBEDDING_MODEL`

### 4. 启动 Neo4j

```bash
docker compose up -d neo4j
```

默认地址：

- Neo4j Browser: `http://127.0.0.1:7474`
- Bolt: `bolt://127.0.0.1:7687`

默认账号密码：

- username: `neo4j`
- password: `password`

### 5. 启动后端

```bash
uv run uvicorn personal_agent.api:app --reload
```

默认地址：

- API: `http://127.0.0.1:8000`
- Docs: `http://127.0.0.1:8000/docs`

### 6. 启动前端

```bash
cd frontend
npm run dev
```

默认地址：

- Frontend: `http://127.0.0.1:5173`

### 7. 构建前端

```bash
cd frontend
npm run build
```

构建完成后，FastAPI 会自动托管 `frontend/dist`。

## Docker Compose

当前 `docker-compose.yml` 包含：

- `backend`
- `frontend`
- `neo4j`

直接启动：

```bash
docker compose up --build
```

## CLI 用法

当前仍保留 CLI 入口：

```bash
uv run python -m personal_agent.main capture --text "服务降级是在系统压力过大时，主动关闭非核心能力"
uv run python -m personal_agent.main ask --question "什么是服务降级？"
uv run python -m personal_agent.main digest
```

## 前端与后端版本

当前仓库里的主要版本：

- 后端依赖定义见 [pyproject.toml](/d:/mySoft/workspace/personalAgent/pyproject.toml)
- 前端依赖定义见 [frontend/package.json](/d:/mySoft/workspace/personalAgent/frontend/package.json)

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
3. 在前端增加实体图谱、关系图谱和时间线视图
4. 扩展 `capture` 到网页、PDF、语音和 OCR
5. 用真实生成式答案替代当前“关系事实拼接式”回答
