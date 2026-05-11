# “数字第二大脑” Agent

一个面向个人知识管理的 AI Agent。

它不是单纯的笔记应用，而是一个把个人输入沉淀为“可采集、可连接、可复习、可问答”长期记忆系统的后端与前端一体化项目。

## 项目目标

这个项目当前聚焦 4 件事：

1. 把零散输入沉淀成结构化笔记
2. 把笔记升级成实体与关系图谱
3. 让问答优先利用图谱关系，而不只是相似度检索
4. 给后续的复习、总结、可视化留出稳定扩展点

## 从 Agent 视角看，这个工程的关键组件

如果把一个 Agent 拆开看，通常至少有下面 8 类关键组件：

1. `入口层`：用户从哪里把任务和信息送进来
2. `意图识别 / 路由层`：系统先判断“这是要记录、提问、总结，还是调用某个能力”
3. `编排层`：把一个请求拆成若干节点并串成稳定流程
4. `工具层`：抓网页、解析文件、查图谱、写存储、调用模型
5. `记忆层`：短期上下文、长期知识、问答历史、图谱记忆
6. `检索与推理层`：围绕问题找到证据，再组织成回答
7. `执行与反馈层`：把结果回给用户，并支持流式、异步、失败降级
8. `观测与治理层`：日志、健康检查、重试、权限、多用户隔离、评测

这个项目目前已经具备一个可运行 Agent 的主干，但还没有完全走到“通用自主 Agent”那一步。更准确地说，它现在是一个以 `个人知识沉淀 / 问答 / 图谱增强` 为中心的 `knowledge agent`。

## 当前工程的 Agent 结构判断

| 组件 | 当前状态 | 代码落点 | 当前判断 |
| --- | --- | --- | --- |
| `入口层` | `可用` | [web/api.py](src/personal_agent/web/api.py), [feishu/service.py](src/personal_agent/feishu/service.py), [main.py](src/personal_agent/main.py) | 具备 Web API、前端、飞书、CLI 多入口，但不同入口的能力闭环还不完全一致 |
| `意图识别 / 路由层` | `可用` | [agent/router.py](src/personal_agent/agent/router.py), [agent/entry_nodes.py](src/personal_agent/agent/entry_nodes.py), [agent/service.py](src/personal_agent/agent/service.py) | 能区分 `capture / ask / summarize / unknown` 一类单轮意图，但仍以路由分发为主，不具备多步规划 |
| `编排层` | `可用` | [agent/graph.py](src/personal_agent/agent/graph.py), [agent/nodes.py](src/personal_agent/agent/nodes.py) | 已有 `LangGraph` 状态流，但主要覆盖 `capture / ask / entry` 这类固定流程 |
| `工具层` | `可用` | [tools/](src/personal_agent/tools), [capture/service.py](src/personal_agent/capture/service.py), [capture/providers](src/personal_agent/capture/providers), [graphiti/store.py](src/personal_agent/graphiti/store.py) | 已有统一 Tool 抽象和注册中心，但工具编排、回退和选择策略仍较轻 |
| `记忆层` | `基础可用` | [memory/](src/personal_agent/memory), [storage/memory_store.py](src/personal_agent/storage/memory_store.py), [storage/ask_history_store.py](src/personal_agent/storage/ask_history_store.py), [core/models.py](src/personal_agent/core/models.py) | 有工作记忆、会话摘要和长期存储，但统一读写和跨会话一致性仍有继续收敛空间 |
| `检索与推理层` | `基础可用` | [agent/nodes.py](src/personal_agent/agent/nodes.py), [graphiti/store.py](src/personal_agent/graphiti/store.py), [agent/service.py](src/personal_agent/agent/service.py), [agent/verifier.py](src/personal_agent/agent/verifier.py) | 已有本地检索、图谱增强和回答后校验，但复杂推理、计划分解和证据组织仍偏轻 |
| `执行与反馈层` | `可用` | [web/api.py](src/personal_agent/web/api.py), [agent/service.py](src/personal_agent/agent/service.py) | 具备同步调用、SSE、异步图谱同步和失败降级，但不是完整的 agent runtime |
| `观测与治理层` | `部分具备` | [core/logging_utils.py](src/personal_agent/core/logging_utils.py), [web/api.py](src/personal_agent/web/api.py), [agent/service.py](src/personal_agent/agent/service.py) | 已有日志、trace、health、reset 和基础测试，但权限、配额、多用户治理和回归评测仍不足 |

## 一句话判断

当前工程已经具备 `场景化 Agent` 的基础骨架，可以支撑个人知识沉淀、问答和图谱增强这条主链路。

它目前更适合被定义为 `knowledge agent 原型`，而不是通用自主 Agent 或生产级 Agent 平台。

## 当前框架已有能力

从代码结构看，当前框架已经具备以下能力：

- `统一输入模型`：通过 `EntryInput / RawIngestItem / AgentState` 规范入口数据与状态传递
- `基础状态编排`：基于 `LangGraph StateGraph` 组织 `capture / ask / entry` 固定流程
- `工具抽象`：通过 `BaseTool / ToolSpec / ToolResult / ToolRegistry` 统一工具注册与执行
- `采集链路`：支持文本采集、链接抓取、文件上传解析，并沉淀为 `KnowledgeNote`
- `知识存储`：本地维护笔记、复习卡片、会话记录，并保留图谱字段映射
- `问答链路`：支持本地检索问答，以及图谱可用时的图谱增强问答
- `工作记忆`：支持会话级摘要、最近推理步骤、工具缓存等短期上下文
- `回答校验`：支持回答后做引用有效性和证据充分度检查
- `多入口接入`：支持 Web API、前端界面、CLI、飞书消息入口
- `基础可靠性`：图谱不可用时降级、本地重试同步、SSE 输出、健康检查与日志
- `基础测试`：已有 router、tools、memory、verifier 的单元测试，以及 ask 质量 eval

## 当前需要改进的地方

### 1. Agent 抽象仍未完全收口

- `AgentService` 仍承担较多协调职责，尚未抽象成独立的 `AgentRuntime`
- 路由逻辑在 `router.py` 与 `service.py` 中存在重复实现，运行时入口尚未完全统一
- 当前更像“单轮路由 + 固定分支”，还不是完整的 `plan-and-act` 执行器

### 2. 多步规划能力不足

- 还没有真正的 `Planner`
- 还不能根据问题自动规划“检索 -> 工具调用 -> 整理证据 -> 回答”
- 也还没有更成熟的 `Tool Selection` 与 fallback 策略

### 3. 部分入口能力只做到识别，未形成闭环

- `capture_file` 已识别，但在 `entry` 链路里仍未完整接通
- `summarize_thread` 已识别，但尚未接入消息回溯与群聊总结执行
- 飞书入口当前主要覆盖文本消息，文件消息和线程回溯仍待补齐

### 4. 记忆层仍需继续收敛

- `WorkingMemory` 已存在，但更偏进程内会话缓存
- `MemoryFacade` 虽已建立，但对本地存储、问答历史和会话摘要的统一读写仍可继续加强
- 多实例、跨进程、跨入口的一致性设计还不完整

### 5. 检索与回答质量仍有优化空间

- 本地检索排序仍偏启发式，复杂问题下可能串题
- 图谱事实与 `citation` 的精确锚定还不够严格
- 回答虽然有校验与上下文注入，但证据组织、可读性和稳定性还有提升空间
- 当前 verifier 主要做“事后校验”，还没有形成更完整的自修正闭环

### 6. 治理与生产化能力不足

- 缺少用户认证与 API 鉴权
- 缺少系统性的多用户隔离边界
- 缺少外部工具权限控制、限流和配额
- 缺少生产运行所需的审计、操作边界和安全治理

### 7. 测试与评测覆盖面还不够

- 现有测试更集中在 `router / tools / memory / verifier`
- `AgentService.entry()`、采集主链路、SSE、飞书入口的集成测试仍需补齐
- 图谱检索质量、citation 精度和回归评测体系仍不完整

## 如果继续演进，建议怎么设计

建议按 `不推翻现有结构` 的思路演进，分三层推进。

### 第一层：先把现有主干抽象稳

优先做这 4 件事：

1. 统一 `AgentRuntime` 执行入口
2. 收口 `IntentRouter` 的运行时接入
3. 继续收敛 `MemoryFacade` 的读写职责
4. 拆分 `AgentService` 里的协调逻辑

建议的目录形态可以是：

```text
src/personal_agent/
├─ agent/
│  ├─ runtime.py          # AgentRuntime：统一执行入口
│  ├─ router.py           # IntentRouter：规则版 / LLM 版 ✅
│  ├─ planner.py          # 任务规划器，先留接口
│  ├─ executor.py         # Tool 执行器
│  ├─ verifier.py         # AnswerVerifier：回答证据校验 ✅
│  ├─ graph.py            # LangGraph 编排
│  └─ nodes.py
├─ tools/                 ✅
│  ├─ base.py             # ToolSpec / ToolResult / BaseTool
│  ├─ capture_url.py
│  ├─ capture_upload.py
│  ├─ graph_search.py
│  ├─ registry.py         # ToolRegistry
│  └─ note_store.py
├─ memory/                ✅
│  ├─ facade.py           # MemoryFacade：工作记忆 + 长期记忆统一读写
│  ├─ working_memory.py   # WorkingMemory：会话级推理状态
│  ├─ long_term_memory.py
│  └─ conversation_memory.py
```

这样改完之后，`AgentService` 就能从“超大协调类”逐步收敛成“面向接口的 runtime facade”。

### 第二层：补齐多步 Agent 能力

当第一层稳定后，再补这几件事情：

1. 增加 `Planner`
2. 增加 `Tool Selection`
3. 增强 `Working Memory Summary`
4. 增加回答失败后的自修正与重试策略

推荐执行链路：

```text
Entry
  -> Intent Router
  -> Planner
  -> Tool Selection
  -> Tool Execution
  -> Memory Update
  -> Verifier
  -> Final Response
```

其中最值得优先落地的是：

- `Planner` 先只支持 3 类任务：`capture / ask / summarize`
- `Tool Selection` 先覆盖本地检索、图谱查询和采集工具三类能力
- `Verifier` 从“只打标”逐步演进到“触发重试或降级”

### 第三层：补齐生产化治理

如果目标是长期跑在团队或个人生产环境里，建议继续补：

1. API Key / Session 鉴权
2. 多用户存储边界审计
3. 限流和配额
4. 回放测试数据集
5. ask / capture / graph 三条链路的回归评测

## 推荐的下一步实现顺序

如果只选最值得继续推进的 5 项，建议按这个顺序：

1. 收口 `AgentService.entry(...)` 的路由实现，统一到 `IntentRouter`
2. 补齐 `capture_file` 和 `summarize_thread` 的执行闭环
3. 抽象 `AgentRuntime / Planner / Tool Selection`
4. 补强 `entry / capture / SSE / Feishu` 的集成测试与回归评测
5. 增加鉴权、多用户隔离、限流等生产化治理能力

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

## 当前业务能力范围

### 1. Capture

- 可以接收文本、链接和上传文件三类采集输入
- 采集结果会被整理成 `KnowledgeNote`
- 当前采集链路包含网页正文抓取、PDF 文本提取、标题/摘要/标签生成、复习卡生成等处理步骤
- 图谱可用时，采集结果会继续尝试写入 Graphiti

### 2. Knowledge Connection

- 默认使用本地 JSON 存储与简单匹配
- 图谱开启后，会为笔记补充实体、关系和图谱 episode 映射信息
- 当前数据模型中已经为图谱字段预留了 `graph_episode_uuid / entity_names / relation_facts`

### 3. Ask

- 提供本地检索问答链路
- 图谱可用时，问答流程会尝试结合图谱事实、相关笔记和引用片段生成回答
- 图谱不可用时，问答会回退到本地链路
- 问答支持 `session_id` 会话上下文和服务端问答历史持久化
- Web 侧提供同步问答和 `SSE` 返回方式

### 4. Digest

- 提供最近笔记与到期复习卡片的聚合视图

### 5. Web UI

- 提供基于 `FastAPI + React` 的前后端分离结构
- 前端工作台覆盖 `Capture / Ask / Entity Graph / Relation Graph / Digest / Timeline / Memory` 等视图
- 前端主要围绕采集、问答、历史查看和调试数据管理几个场景展开
- 构建后的 `frontend/dist` 可以由 FastAPI 托管

### 6. Feishu

- 已预留飞书机器人接入链路
- 当前实现以 `官方 Python SDK + 长连接接收事件` 为主
- 飞书文本消息可以进入 `entry` 路由并分发到采集或问答分支
- 仍保留 `POST /api/integrations/feishu/webhook` 作为兼容入口

## 当前图谱相关接入点

当前代码中包含以下图谱相关接入点：

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
      ├─ agent/                 # Agent 主流程编排层（含 router / graph / nodes / verifier）
      ├─ capture/               # 采集编排、provider 和抽取工具层
      ├─ cli/                   # 命令行入口层
      ├─ core/                  # 配置、日志、核心数据模型
      ├─ graphiti/              # Graphiti、Neo4j、LLM、Embedding 接入
      ├─ memory/                # 工作记忆与会话摘要（MemoryFacade / WorkingMemory）
      ├─ storage/               # 本地 JSON 和 Postgres 存储层
      ├─ tools/                 # 统一 Tool 抽象与注册中心
      └─ web/                   # FastAPI Web 接口层
  ├─ tests/                     # 单元测试（router / tools / verifier / memory）
  └─ evals/                     # ask 质量评测用例
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
