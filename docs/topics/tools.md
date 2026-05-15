# 工具层说明

本文汇总当前项目工具层的职责划分、注册与执行路径、已有工具、已知限制和后续改进方向。对应代码主要位于 [src/personal_agent/tools/](../../src/personal_agent/tools/)、[src/personal_agent/capture/](../../src/personal_agent/capture/) 和 [src/personal_agent/graphiti/](../../src/personal_agent/graphiti/)。

## 设计目标

当前工具层的目标不是做一个完整插件市场，而是把项目内可执行的业务能力封装为统一接口，供 router、planner、validator 和 executor 调用：

- 用 `BaseTool` 统一工具协议
- 用 `ToolRegistry` 管理工具注册、发现和执行
- 用 `ToolSpec` 暴露工具描述和输入 schema
- 用 `ToolResult` 统一成功、失败和返回数据格式
- 让 planner 生成 `tool_call` 步骤，再由 `PlanExecutor` 统一执行

## 组件分层

### 1. `BaseTool`

代码位置：[base.py](../../src/personal_agent/tools/base.py)

作用：

- 定义所有工具必须实现的 `spec`
- 定义所有工具必须实现的 `execute(**kwargs)`
- 让上层只依赖 `tool_name + tool_input -> ToolResult`

### 2. `ToolSpec`

代码位置：[base.py](../../src/personal_agent/tools/base.py)

作用：

- 描述工具名 `name`
- 描述工具用途 `description`
- 描述输入结构 `input_schema`
- 描述治理属性 `risk_level / requires_confirmation / writes_longterm / accesses_external`

`ToolSpec` 会被 `ToolRegistry.list_tools()` 暴露给 planner、API 和前端。

### 3. `ToolResult`

代码位置：[base.py](../../src/personal_agent/tools/base.py)

作用：

- `ok=True` 表示工具执行成功
- `data` 承载结构化结果
- `error` 承载失败原因

`PlanExecutor` 会根据 `ok` 判断步骤是否失败。

### 4. `ToolRegistry`

代码位置：[registry.py](../../src/personal_agent/tools/registry.py)

作用：

- 注册工具实例
- 按名称执行工具
- 根据 intent 匹配默认工具
- 暴露已注册工具列表
- 提供工具级 fallback 执行接口

当前 intent 到工具的显式映射是：

```text
capture_text -> capture_text
capture_link -> capture_url
capture_file -> capture_upload
ask -> graph_search
delete_knowledge -> delete_note
solidify_conversation -> capture_text
```

## 已注册工具

### 1. `capture_text`

代码位置：[capture_text.py](../../src/personal_agent/tools/capture_text.py)

作用：

- 将纯文本采集为 `KnowledgeNote`
- 复用 runtime 的 `execute_capture()`
- 生成标题、摘要、标签和复习卡
- 可触发图谱同步

主要用于文本采集，也被 `solidify_conversation` 复用为草稿入库工具。

当前 `capture_text` 复用的是 runtime 的基础 capture pipeline。短文本和固化草稿生成单条 `KnowledgeNote`；长文章（>2000 字符）自动按标题/段落拆分为 parent + N chunk notes。

### 2. `capture_url`

代码位置：[capture_url.py](../../src/personal_agent/tools/capture_url.py)

作用：

- 接收一个明确 URL
- 调用 `CaptureService.capture_text_from_url()`
- 返回网页正文文本

注意：

- 这里是已知 URL 抓取，不是网络搜索
- Firecrawl 当前通过 `FirecrawlUrlCaptureProvider` 调 `/v2/scrape` 抓取指定网页正文

### 3. `capture_upload`

代码位置：[capture_upload.py](../../src/personal_agent/tools/capture_upload.py)

作用：

- 接收上传文件路径或文件名
- 通过上传 provider 提取文本
- 服务 PDF、文档等文件采集入口

### 采集 provider 分层

采集链路已经从 Web 层拆到独立的 `capture` 模块：

- [web/api.py](../../src/personal_agent/web/api.py)：负责 HTTP 路由、参数接收和返回响应
- [capture/service.py](../../src/personal_agent/capture/service.py)：负责采集流程编排和 provider 注册
- [capture/providers/](../../src/personal_agent/capture/providers)：负责具体来源实现，例如上传文件和 URL 抓取
- [capture/utils.py](../../src/personal_agent/capture/utils.py)：负责文件名、URL 校验、HTML/PDF 文本抽取等公共工具

当前 provider 包括：

- `DefaultUploadCaptureProvider`
- `FirecrawlUrlCaptureProvider`
- `BuiltinUrlCaptureProvider`

后续接入新的采集来源时，应优先扩展 `capture/providers` 或在 `CaptureService` 中注册新 provider，避免把外部平台集成逻辑继续塞回 `web/api.py`。

### 4. `graph_search`

代码位置：[graph_search.py](../../src/personal_agent/tools/graph_search.py)

作用：

- 查询个人知识图谱
- 返回图谱回答、实体名、关系事实、结构化 node / edge / fact refs 和相关 episode UUID
- 为 ask、delete resolve、证据组织提供图谱侧结果

注意：

- `graph_search` 搜的是个人知识图谱，不是公网互联网
- 图谱不可用或无结果时，会回退到本地检索，再回退到 web search

### 5. `web_search`

代码位置：[web_search.py](../../src/personal_agent/tools/web_search.py)

作用：

- 在公网互联网上搜索与问题相关的最新信息
- 作为 ask 第三层回退（图谱 → 本地 → 网络搜索）
- 仅在个人知识库和图谱无法覆盖时启用
- 依赖 Firecrawl `/v1/search` API，需要配置 `FIRECRAWL_API_KEY`

输入：

```json
{
  "query": "string",
  "limit": 5,
  "scrape": false
}
```

输出：

```json
{
  "results": [
    {
      "title": "...",
      "url": "...",
      "snippet": "...",
      "source": "firecrawl",
      "published_at": null
    }
  ]
}
```

若 `scrape=true`，会复用 `CaptureService.capture_text_from_url()` 抓取前 2 条结果正文，追加到 snippet。

治理属性：`risk_level="low"`, `accesses_external=True`（会触发 PlanValidator 外部副作用 warning）。

### 6. `delete_note`

代码位置：[delete_note.py](../../src/personal_agent/tools/delete_note.py)

作用：

- 删除指定 note
- 同步删除关联复习卡
- 尝试删除对应图谱 episode
- 使用 `PendingActionStore` 做两阶段 HITL 确认

执行分两阶段：

1. 第一次调用创建 pending action，并返回 `action_id / token`
2. 第二次带 `confirmed=True / action_id / token` 执行真实删除

## 注册与执行路径

### 运行时注册

`AgentRuntime` 初始化时创建 `ToolRegistry`，再调用 `_register_tools()` 注册工具：

- 有 `capture_service` 时注册 `capture_url` 和 `capture_upload`
- 始终注册 `graph_search`
- 始终注册 `capture_text`
- 始终注册 `delete_note`
- 当 `FIRECRAWL_API_KEY` 配置时注册 `web_search`

代码位置：[runtime.py](../../src/personal_agent/agent/runtime.py)

### planner 使用

`DefaultTaskPlanner` 会读取 `ToolRegistry.list_tools()`，把可用工具列表放进规划 prompt，避免 planner 在不知道工具列表的情况下凭空生成工具名。

### validator 使用

`PlanValidator` 会从 `ToolRegistry` 动态读取已注册工具，并校验 `tool_call` 步骤里的 `tool_name` 是否存在。这样工具白名单不会和真实注册表漂移。

### executor 使用

`PlanExecutor` 在遇到 `action_type="tool_call"` 时，按步骤里的 `tool_name` 调用：

```text
ToolRegistry.execute(tool_name, **tool_input)
```

若工具返回 `ok=False`，当前步骤会失败，再进入 retry、skip、abort 或 replan 逻辑。

## 当前能力

- 已具备统一工具协议
- 已具备工具注册中心
- 已具备 intent 到工具的显式映射
- 已具备 planner 可见的工具说明
- 已具备 validator 动态工具校验
- 已具备计划执行器中的工具调用
- 已具备采集文本、采集 URL、采集上传文件、图谱检索、网络搜索和删除笔记工具
- 已具备删除类高风险工具的两阶段 HITL 确认
- 已具备 ask 三层检索回退（图谱 → 本地 → 网络搜索）
- 已预留工具级 `execute_with_fallback()` 能力
- 已具备工具级治理字段：`risk_level`、`requires_confirmation`、`writes_longterm`、`accesses_external`
- 已具备 `ToolRegistry.execute()` 输入 schema 前置校验，参数错误在工具执行前即暴露
- 已具备 `validate_tool_input()` 公共校验函数，PlanValidator 可复用做计划阶段参数校验
- 已具备受控 ReAct 工具调用：`ReActStepRunner` 复用 `ToolRegistry.execute()`，并受 `allowed_tools / max_iterations / risk_level / requires_confirmation` 约束
- 已扩展 `ToolResult.evidence` 字段，`graph_search / web_search` 在返回 `data` 的同时填充 `evidence: list[EvidenceItem]`
- `ReActStepRunner` 已支持在 `ReActIteration` 和最终结果中传递工具 evidence

## 已知限制

### 1. 工具级 fallback 没有接入主执行链

`ToolRegistry` 已经有 `execute_with_fallback()`，但当前 `PlanExecutor` 使用的是明确工具名的 `execute()`。

因此实际主链路里的失败处理更多发生在：

- router 的启发式兜底
- planner 的 fallback plan
- executor 的 retry / skip / abort / replan
- delete resolve 的图谱、本地相似检索、关键词和 recent citations 回退

### 2. ReAct 工具调用策略仍是首版

当前工具调用有两条路径：

- 确定性 `tool_call` 步骤：由 planner 生成明确工具名，再由 `PlanExecutor` 调用 `ToolRegistry.execute()`
- ReAct 步骤：由 `ReActStepRunner` 在单个 step 内根据 observation 选择只读工具，并继续通过 `ToolRegistry.execute()` 执行

当前 ReAct 约束包括：

- 每个 ReAct step 可以声明 `allowed_tools`
- 每个 ReAct step 必须受 `max_iterations` 上限约束
- 高风险、写长期知识或需要确认的工具不能被 ReAct 调用
- 每次 action / observation 会进入 `react_iteration` 事件
- 首批主要开放 `web_search / graph_search` 等只读检索工具

后续需要继续扩展工具适配与审计字段，让 ReAct action / observation 能进入统一 evidence/citation 或 `AgentEvent` schema。

### 3. 工具输入 schema 校验仍可增强

`ToolSpec.input_schema` 已通过 `validate_tool_input()` 接入：
- `ToolRegistry.execute()` 默认启用 schema 校验（`validate_schema=True`），参数错误在工具执行前即返回失败
- `PlanValidator` 在计划校验阶段对 `tool_call` 步骤做深度参数校验，缺失必填字段会生成阻断性 issue

当前校验覆盖 required 字段检查和基础类型匹配（string/boolean/integer/number）。复杂嵌套结构校验仍需补充。

### 4. 工具权限和风险分级仍偏基础

已为 `ToolSpec` 增加统一治理字段：

- `risk_level`（low/medium/high）：工具固有风险等级
- `requires_confirmation`：工具是否本身要求用户确认
- `writes_longterm`：工具是否会写入长期知识
- `accesses_external`：工具是否会访问外部网络

`PlanValidator` 已接入治理交叉校验：
- 工具 `requires_confirmation=True` 但步骤未设确认 → warning
- 工具 `writes_longterm=True` 但步骤无确认且非 high 风险 → warning
- 工具 `accesses_external=True` → warning（提示外部副作用）
- 工具固有风险等级高于步骤声明 → warning

更复杂的组织/角色/租户权限模型仍未建立。

### 5. 工具结果已接入统一证据模型

`ToolResult` 已扩展 `evidence` 字段（`list[EvidenceItem]`），`graph_search / web_search` 已填充统一证据。`delete_note` 等写操作工具保留 pending action payload，暂不进入 evidence 主链路。

### 6. 长文采集的 chunk / document 模型已接入

已在 `KnowledgeNote` 上增加 `parent_note_id / chunk_index / source_span` 三个可选字段（默认 None，完全向后兼容）。capture 阶段通过 `core/chunking.py` 的纯函数 `chunk_content()` 按 markdown 标题（`##`/`###`）拆分长文，无标题时回退到双换行段落拆分；短内容（<2000 字符）保持单条笔记不动。

当前 chunk 模型的已实现特性：

- **Capture**：长文自动产出 1 条 parent note（`chunk_index=0`，保留完整 content）+ N 条 chunk notes（`chunk_index=1..N`，各有独立 title/content/source_span）
- **Store**：`get_chunks_for_parent()` / `get_parent_note()` / 级联删除 / `list_notes(include_chunks=False)` / `find_similar_notes` 按 parent 去重
- **Delete**：`delete_note` 和 `confirm_pending_action` 自动检测子 chunk 并级联删除
- **Ask/Evidence**：Graphiti node / edge / fact 已成为 ask 图谱路径的主推理材料；parent/chunk note 主要承担原文回查、snippet、高亮和抽取校验，避免整篇文档直接塞入 prompt
- **Resolve**：候选笔记包含 `parent_note_id` / `parent_title`，前端可展示 chunk 所属文档
- **API**：`GET /api/notes/{note_id}/chunks`、`GET /api/notes?flat=true`、`DELETE /api/notes/{note_id}?cascade=true`
- **Graph Sync**：chunk note 会以 `graph_sync_status="pending"` 进入后台图谱同步，级联删除时也会清理 chunk 持有的 graph episode

## 演进方向

- 根据需要把 `execute_with_fallback()` 接入计划执行链，或明确只作为低层备用接口保留
- 为 `capture_url` 等工具补充 evidence 输出（当前优先改造了 `graph_search` 和 `web_search`）
- 后续可扩展 `ToolResult` 增加统一的 `events` 字段，与 `AgentEvent` 模型对齐
