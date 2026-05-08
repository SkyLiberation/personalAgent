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
- 支持网页链接正文抓取与 PDF 文本提取
- 自动生成标题、摘要、标签
- 保存为本地 `KnowledgeNote`
- 自动生成复习卡片 `ReviewCard`
- 可选写入 Graphiti 图谱

### 2. Knowledge Connection

- 默认使用本地 JSON 存储与简单匹配
- 启用 Graphiti 后，升级为实体抽取 + 关系抽取 + 图谱写入
- 每条笔记会记录：
  - `graph_episode_uuid`
  - `entity_names`
  - `relation_facts`

### 3. Ask

- 图谱关闭时：走本地问答链路
- 图谱开启时：优先利用图谱事实、引用片段和相关笔记生成回答
- 支持把图谱命中的 episode 反查成本地笔记引用
- 支持多轮对话与 `session_id` 会话上下文管理
- 支持 `SSE` 实时展示回答
- 支持把问答历史持久化到 `Postgres`
- 前端支持查看服务端问答历史

### 4. Digest

- 查看最近新增笔记
- 查看到期复习卡片

### 5. Web UI

- 提供基于 `FastAPI + React` 的前后端分离架构
- 前端采用左侧导航多 Tab 工作台
- 当前视图包括 `Capture / Ask / Entity Graph / Relation Graph / Digest / Timeline / Memory`
- 前端支持调用 `capture / capture/upload / ask / ask-history / digest / notes`
- `Ask` 页面支持聊天式多轮对话、会话切换和 SSE 实时回答
- `Capture` 页面提供一键清空调试数据入口，可同时清理本地数据、问答历史、上传源文件和当前用户图谱分组
- 构建后 `frontend/dist` 可由 FastAPI 自动托管

## 已接入的图谱能力

当前已经接入并验证过以下链路：

- `DeepSeek` 作为聊天/抽取模型
- `DashScope text-embedding-v4` 作为 embedding 模型
- `Graphiti` 作为知识图谱抽取与检索层
- `Neo4j` 作为图数据库

### 自定义本体

本体定义位于 [ontology.py](src/personal_agent/graphiti/ontology.py)：

- `Person`
- `Project`
- `Concept`
- `Organization`
- `Source`

### 兼容层说明

由于 `DeepSeek` 和 `Graphiti` 的结构化输出约定并不完全一致，项目里增加了兼容层：

- [deepseek_compatible_client.py](src/personal_agent/graphiti/deepseek_compatible_client.py)
- [dashscope_compatible_embedder.py](src/personal_agent/graphiti/dashscope_compatible_embedder.py)
- [store.py](src/personal_agent/graphiti/store.py)

当前已经兼容这些常见差异：

- 列表根对象自动包装为 Graphiti 期望的对象结构
- `entity -> name`
- `type / entity_type -> entity_type_id`
- `facts -> edges`
- `source_entity / target_entity -> source_entity_name / target_entity_name`
- 字典式摘要转换为 `summaries: [{name, summary}]`
- DashScope embedding 单批限制自动分片

## 项目结构

```text
personalAgent/                  # 项目根目录
├─ data/                        # 本地知识数据、复习卡片、上传文件
├─ frontend/                    # React + Vite 前端工程
├─ log/                         # 运行日志目录
└─ src/
   └─ personal_agent/           # Python 应用主包
      ├─ agent/                 # Agent 主流程编排层
      ├─ cli/                   # 命令行入口层
      ├─ core/                  # 配置、日志、核心数据模型
      ├─ graphiti/              # Graphiti、Neo4j、LLM、Embedding 接入
      ├─ storage/               # 本地 JSON 和 Postgres 存储层
      └─ web/                   # FastAPI Web 接口层
```

## 关键落点

- 本地知识数据：`data/notes.json`、`data/reviews.json`、`data/conversations.json`
- 上传源文件：`data/uploads/`
- 服务端问答历史：`Postgres.ask_history`
- 运行日志：`log/run.log`

更完整的数据流、接口和部署细节请直接查看：

- [docs/api.md](docs/api.md)
- [docs/env.md](docs/env.md)
- [docs/deploy.md](docs/deploy.md)

## 文档导航

- 接口说明：[docs/api.md](docs/api.md)
- 环境变量：[docs/env.md](docs/env.md)
- 本地开发与部署：[docs/deploy.md](docs/deploy.md)

## CLI 用法

当前仍保留 CLI 入口：

```bash
uv run python -m personal_agent.main capture --text "服务降级是在系统压力过大时，主动关闭非核心能力"
uv run python -m personal_agent.main ask --question "什么是服务降级？"
uv run python -m personal_agent.main digest
```

## 已知限制

当前工程已经具备可运行的主链路，但仍有一些遗留问题需要继续收敛：

1. `ask` 的检索排序仍然偏启发式，复杂问题下仍可能出现跨主题串题
2. `citation` 与图谱 `relation_fact` 的绑定已经有所增强，但还没有做到严格可追踪的精确锚定
3. `capture` 目前已支持文本、网页链接和 PDF 文本提取，但 OCR、语音 ASR 等非结构化输入仍未接入
4. 当前回答已经接入基于上下文的生成式总结，但证据组织和答案质量仍有继续打磨空间
5. SSE 现在是服务端分段推送已有答案，还不是直接透传上游模型 token 流
6. `ask history` 已支持会话维度和服务端持久化，但搜索、删除和更完整的多用户隔离还不完善
7. 调试重置已支持清理当前用户本地数据、问答历史、上传源文件和图谱分组，但还没有做更细粒度的选择式清理

## 后续建议

最值得继续推进的方向是：

1. 优化 `ask` 的检索排序，减少跨主题串题
2. 继续增强 `citation` 与 `relation_fact` 的精确绑定
3. 继续增强 `Entity Graph / Relation Graph / Timeline` 的交互联动
4. 继续扩展 `capture` 到语音和 OCR
5. 继续提升生成式答案的证据组织、可读性和稳定性
6. 给 `ask history` 增加搜索、删除和更完整的会话管理能力
