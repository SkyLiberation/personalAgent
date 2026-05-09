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

## 快速开始

如果你希望先把项目跑起来，再逐步打开图谱和飞书能力，推荐按下面顺序：

1. 安装依赖

```bash
uv sync
cd frontend
npm install
cd ..
```

2. 复制环境变量

```bash
cp .env.example .env
```

3. 启动后端

```bash
uv run uvicorn personal_agent.web.api:app --host 0.0.0.0 --port 8000 --reload
```

4. 启动前端

```bash
cd frontend
npm run dev
```

如果你要启用图谱问答，再额外启动 Neo4j：

```bash
docker compose up -d neo4j
```

如果你要启用问答历史持久化，再额外启动 Postgres：

```bash
docker compose up -d postgres
```

## 当前能力

### 1. Capture

- 接收文本输入
- 前端单独暴露文本采集、网站抓取、文件上传 3 个入口
- 支持前端文件上传
- 支持网页链接正文抓取与 PDF 文本提取
- 网页抓取优先走 `Firecrawl`，不可用时回退到内置 HTML 正文提取
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
- 图谱开启且 Neo4j 可连接时：优先利用图谱事实、引用片段和相关笔记生成回答
- 图谱开启但 Neo4j 不可连接时：自动降级为本地问答链路，不阻塞飞书或 Web 入口
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

### 6. Feishu

- 已支持飞书应用机器人接入
- 当前默认接入方式为：`官方 Python SDK + 长连接接收事件`
- 已支持飞书文本消息路由到 `capture_text / capture_link / ask`
- 已支持使用 `message_id` 直接回复原消息
- 当图谱不可用时，飞书问答会自动降级到本地问答链路
- 仍保留 `POST /api/integrations/feishu/webhook` 作为 HTTP 回调兼容入口，但当前推荐优先使用长连接模式

## 已接入的图谱能力

当前已经接入并验证过以下链路：

- `DeepSeek` 作为聊天/抽取模型
- `DashScope text-embedding-v4` 作为 embedding 模型
- `Graphiti` 作为知识图谱抽取与检索层
- `Neo4j` 作为图数据库
- `Firecrawl` 作为网站正文抓取能力

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
      ├─ capture/               # 采集编排、provider 和抽取工具层
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

## 当前采集架构

当前采集链路已经从单一 `api.py` 逻辑拆成了独立的 `capture` 模块，目的是让后续接入更多外部来源时，不需要不断膨胀 Web 层。

### 分层方式

- [web/api.py](src/personal_agent/web/api.py)：只负责 HTTP 路由、参数接收和返回响应
- [capture/service.py](src/personal_agent/capture/service.py)：负责采集流程编排和 provider 注册
- [capture/providers/](src/personal_agent/capture/providers)：负责具体来源实现
  - `upload.py`：上传文件采集
  - `url.py`：网站抓取采集
- [capture/utils.py](src/personal_agent/capture/utils.py)：文件名、URL 校验、HTML/PDF 文本抽取等公共工具

### 当前 provider 形态

- `DefaultUploadCaptureProvider`
- `FirecrawlUrlCaptureProvider`
- `BuiltinUrlCaptureProvider`

这意味着后续要继续加入新的采集来源时，优先应该扩展 `capture/providers` 或在 `CaptureService` 中注册新 provider，而不是继续把外部平台集成代码塞回 `web/api.py`。

## 飞书接入

当前工程已经完成飞书最小可用闭环，但接入方式和约束与早期设计稿相比有一些变化，后续开发请以本节为准。

### 当前实现

- 飞书后台推荐配置为：`使用长连接接收事件`
- 后端启动时会自动拉起飞书 SDK `ws.Client(...)`
- 已订阅事件：`im.message.receive_v1`
- 已启用权限：
  - `im:message.p2p_msg:readonly`
  - `im:message:send_as_bot`
- 消息处理链路为：

```text
Feishu long connection event
  -> SDK event handler
  -> FeishuIncomingMessage normalizer
  -> AgentService.entry(...)
  -> capture / ask / summarize / unknown
  -> reply message by message_id
```

### 当前支持范围

- 已支持：文本消息的 `capture_text / capture_link / ask`
- 已支持：原消息回复
- 已识别但未完整接通：
  - `capture_file`
  - `summarize_thread`

### 开发注意事项

- 如果飞书后台配置为“长连接接收事件”，就不要再把问题排查重点放在公网 webhook 地址上
- 如果改回“将事件发送至开发者服务器”，才需要配置 `POST /api/integrations/feishu/webhook`
- 飞书长连接模式下，事件需要在 3 秒内快速确认，因此当前实现采用“事件线程快速接收 + 后台处理”模式
- 同一事件可能被飞书重推，当前代码已做基于 `event_id` 的短时去重

### 后续建议

1. 继续把 `capture_file` 接到飞书文件下载与正文抽取
2. 为 `summarize_thread` 接入会话消息回溯
3. 继续增强 `AgentService.entry(...)` 的意图判别稳定性
4. 如果未来同时保留长连接和 webhook 两种模式，需要在 README 和部署文档里明确说明当前选用哪一种

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
8. 飞书文本消息已接入，但文件消息、群聊回溯和更完整的多入口路由仍需补齐
9. Windows 下 Vite 默认端口 5173 可能被系统保留（Hyper-V/WSL 动态端口范围），导致 `EACCES` 权限错误，需改用其他端口（如 3000）

## 后续建议

最值得继续推进的方向是：

1. 优化 `ask` 的检索排序，减少跨主题串题
2. 继续增强 `citation` 与 `relation_fact` 的精确绑定
3. 继续增强 `Entity Graph / Relation Graph / Timeline` 的交互联动
4. 继续扩展 `capture` 到语音和 OCR
5. 继续提升生成式答案的证据组织、可读性和稳定性
6. 给 `ask history` 增加搜索、删除和更完整的会话管理能力
7. 为飞书等外部入口补齐基于 `LangGraph` 的意图路由层
