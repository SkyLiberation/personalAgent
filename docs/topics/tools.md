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

### 4. `graph_search`

代码位置：[graph_search.py](../../src/personal_agent/tools/graph_search.py)

作用：

- 查询个人知识图谱
- 返回图谱回答、实体名、关系事实和相关 episode UUID
- 为 ask、delete resolve、证据组织提供图谱侧结果

注意：

- `graph_search` 搜的是个人知识图谱，不是公网互联网
- 图谱不可用或无结果时，需要依赖本地检索、resolve fallback 或后续可能新增的 web search

### 5. `delete_note`

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
- 已具备采集文本、采集 URL、采集上传文件、图谱检索和删除笔记工具
- 已具备删除类高风险工具的两阶段 HITL 确认
- 已预留工具级 `execute_with_fallback()` 能力

## 已知限制

### 1. 缺少公网网络搜索工具

当前项目没有 `web_search(query)` 这类工具。已有的搜索能力分别是：

- `graph_search`：搜索个人知识图谱
- ask history search：搜索历史问答
- `capture_url`：抓取已知 URL 的正文

Firecrawl 当前接入的是网页正文抓取能力，不是 query 搜索能力。因此它可以作为未来 `web_search` 的 provider，但当前还没有被封装成网络搜索工具。

合理的触发点是：

- 图谱和本地记忆无法匹配
- LLM 判断不应直接回答
- 问题确实需要外部事实或最新资料

### 2. 工具级 fallback 没有接入主执行链

`ToolRegistry` 已经有 `execute_with_fallback()`，但当前 `PlanExecutor` 使用的是明确工具名的 `execute()`。

因此实际主链路里的失败处理更多发生在：

- router 的启发式兜底
- planner 的 fallback plan
- executor 的 retry / skip / abort / replan
- delete resolve 的图谱、本地相似检索、关键词和 recent citations 回退

### 3. 工具输入 schema 目前只做描述，没有强校验

`ToolSpec.input_schema` 已经存在，但工具参数校验主要散落在各工具的 `execute()` 内部。后续可以考虑把 schema 校验前移到 `ToolRegistry.execute()` 或 `PlanValidator`，让错误更早暴露。

### 4. 工具权限和风险分级还不完整

当前高风险删除通过 `PendingActionStore` 做了 HITL，但工具层本身还没有统一的权限模型，例如：

- 工具是否允许外部入口直接调用
- 工具是否需要用户确认
- 工具是否允许写入长期知识
- 工具是否可以访问公网

### 5. 工具结果还没有统一证据模型

`graph_search` 会返回 relation facts 和 episode UUID，`capture_url` 返回正文文本，`delete_note` 返回 pending action 信息。不同工具的 `data` 结构还没有统一成可追踪 citation/evidence 模型。

## Web Search 建议设计

建议新增 `web_search`，而不是把搜索逻辑塞进 `capture_url`。

原因：

- `capture_url` 的职责是抓取已知 URL
- `web_search` 的职责是根据 query 找候选网页
- `graph_search` 的职责是搜索个人知识图谱

建议输入：

```json
{
  "query": "string",
  "limit": 5,
  "scrape": false
}
```

建议输出：

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

若 `scrape=true`，可以复用现有 `CaptureService.capture_text_from_url()` 抓取前几个结果正文。

## 演进方向

- 新增 `web_search` 工具，并明确它只在个人知识无法覆盖时启用
- 将 Firecrawl search 能力作为 `web_search` provider，而保留现有 scrape 能力给 `capture_url`
- 在 router/planner 中加入外部搜索触发语义，例如 `allow_external_search` 或 `candidate_tools=["graph_search", "web_search"]`
- 将 `ToolSpec.input_schema` 接入统一参数校验
- 为工具增加统一风险等级、权限和确认策略
- 将工具结果逐步规范为可追踪 evidence/citation 结构
- 根据需要把 `execute_with_fallback()` 接入计划执行链，或明确只作为低层备用接口保留

