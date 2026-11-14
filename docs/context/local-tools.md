# 本地工具的描述、Schema 与可见性

本文汇总当前源码可注册的 39 个固定名称本地工具，以及按已配置目录生成的本地知识检索工具。下文的用途是工具描述的中文摘要，参数表记录输入 Schema 的字段、默认值和关键约束。实际部署的注册结果可从 `GET /api/capabilities/inventory` 查看，其中 `local_tools` 保留 `description` 和完整 `input_schema`。Conversation 直接声明的本地动作见第 5 节，远端发现的 MCP 工具见独立契约。[工具注册](../../src/personal_agent/orchestration/runtime.py) · [能力清单](../../src/personal_agent/orchestration/capability_inventory.py) · [MCP 契约](../mcpDesign/README.md)

## 1. 工具在什么场景可见

| 场景 | 可见范围 |
| --- | --- |
| 普通对话 | 注册表从 `public_agent` 工具中按认证主体和入口平台筛选，排除策略拒绝或需要升级授权的工具。Conversation 再按任务阶段、资源、部署绑定及已发生的结果收窄工具声明。需要确认的动作仍受对应执行门禁约束。 |
| Web 工具清单和直接执行 | `GET /api/tools` 列出默认暴露的 `public_agent`、`scoped_agent` 和 `admin` 工具的名称、描述和曝光级别。直接执行走自己的身份、作用域与网关策略。 |
| 专用入口 | `scoped_agent` 工具供有明确授权的专用入口使用，`admin` 工具由管理入口治理。本页盘点的注册工具中没有 `admin` 条目。 |
| 内部工作流 | `workflow_activity` 工具由 Runtime 的固定流程调用，例如采集、周期研究和稿件核验。能力清单可以列出这些定义。 |

本地注册名通常投影为模型的 `tool_...` 调用名，文稿写入按操作拆成两个声明。服务方适配器将描述和参数约束分别放入 `tools[].function.description` 和 `tools[].function.parameters`。核对具体一轮时，使用该轮实际请求中的工具名、字段和枚举值。[曝光与策略筛选](../../src/personal_agent/governance/registry.py) · [出站声明](../../src/personal_agent/infra/structured_model.py) · [直接执行 API](../api.md#post-apitoolsnameexecute)

| 对话条件 | 对工具声明的影响 |
| --- | --- |
| 当前有获准读取的原件 | 声明原件读取与搜索，并将 `resource_id` 限于当前可读集合。文件检查要求存在可检查材料，历史恢复快照按其读取边界使用。 |
| 已装配个人知识读取器 | Conversation 提供面向当前主体的知识检索和清单动作，并隐藏 `list_recent_notes`、`get_note`、`find_similar_notes` 三个底层读取工具。本轮个人知识检索成功后，后续决策移除该检索动作。 |
| 已获准执行 Python 或检索实验 | 两者分别依赖已装配服务和当前运行的授权绑定。`execute_python` 还检查执行预算。适用时将输入文件引用限制在当前可用 Artifact 中。 |
| 启用内联任务理解且本轮目标待维护 | 主请求保留增量维护、已有目标的只读查询、澄清及受限结束动作。目标提交后按执行控制开放业务工具。 |
| 进入论断式研究写作 | 回答模块按当前研究阶段声明选证、创建或修订论断稿等动作。是否进入写作以及可编辑基稿、片段和引用均由当轮状态决定。 |

部署还决定网络和核验工具是否注册。网页读取和采集依赖采集服务，网页搜索依赖可用搜索配置，内部核验工具依赖结构化模型客户端。[Conversation 投影](../../src/personal_agent/application/conversation/service.py) · [目标动作声明](../../src/personal_agent/application/conversation/model_actions.py) · [研究写作投影](../../src/personal_agent/application/conversation/answer_results.py)

## 2. 对话可用的注册工具

本节工具声明为 `public_agent`。参数表中的数字范围包含两端。资源引用对象 `ResourceRef` 包含必填的 `resource_id`（资源 ID）、`resource_type`（资源类型）和 `owner`（含 `tenant_id`、`user_id` 的所有者），可选 `revision` 表示版本，默认 1。涉及用户归属的操作仍由执行入口校验身份和权限。[资源引用类型](../../src/personal_agent/kernel/contracts/resource.py)

### 2.1 网络、文件与执行

| 工具 | 用途 | 必填参数 | 可选参数 |
| --- | --- | --- | --- |
| `web_search` | 按问题发现公网来源，返回标题、URL 和发现摘要。 | `query`（字符串，1–400 字符），搜索问题或关键词。 | `limit`（整数，1–10，默认 5），最大结果数。 |
| `web_read` | 读取指定网页的提取正文，供当前任务取证。 | `url`（字符串，至少 8 字符），单个 HTTP 或 HTTPS URL。 | — |
| `inspect_artifact` | 按问题检查当前可读文件，返回提取内容和引用。 | `resource_id`（非空字符串），文件引用 ID。 | `question`（字符串，默认空），针对该文件的问题或总结要求。 |
| `write_artifact` | 创建或编辑本任务文稿，返回新快照。 | `request`（对象），以 `operation` 区分创建和补丁，字段见下文。 | — |
| `execute_python` | 在当前授权环境中独立执行 Python 源码，返回状态及通过 `print` 产生的输出。 | `code`（字符串），完整 Python 源码，最多 128 KiB。 | `input_files`（对象数组，默认空，最多 32 项且合计不超过 64 MiB），每项的 `name` 是输入目录内的安全文件名，`resource_id` 是可读文件 ID。程序从 `sys.argv[1]` 指定的目录读取。 |
| `retrieval_experiment` | 在获准部署中运行开发实验、冻结结果或执行最终评测。 | `action`（对象），以 `operation` 区分操作，字段见下文。 | — |

`write_artifact.request` 的 `operation=create` 分支要求 `filename`（显示文件名）、`content_type`（`text/x-python`、`application/json` 或 `text/markdown`）、`content`（完整正文）。`operation=patch` 分支要求 `base_resource_id`（确切基稿 ID）和 `edits`（1–32 项）。每项编辑含 `range.start` 和 `range.end`，两者都使用 `line` 与 `column`，以及 `new_text`（该范围的完整替换正文）。坐标以同一基稿为准，从 1 开始，终点不包含在替换范围内。可提交正整数或无前导零的十进制数字字符串。创建文稿和补丁新增文本另受 UTF-8 字节上限校验。[写入参数](../../src/personal_agent/application/conversation/tool_requests.py) · [文稿校验](../../src/personal_agent/application/artifacts/models.py)

| `retrieval_experiment.action.operation` | 对应字段 |
| --- | --- |
| `run_development` | `request` 对象必填。其 `method` 为 `bm25`、`dense`、`rrf` 或 `candidate`，`retrieve_k` 为整数 100–1,000。后两种方法要求 `input_result_refs`（至少两条实际结果引用）。`candidate` 还要求 `program_ref`（本任务已保存的程序），可带 `config_ref`（配置引用，默认 `null`）。 |
| `freeze` | `selected_result_ref` 必填，指向要冻结的实际实验结果。 |
| `evaluate_final` | `frozen_ref` 必填，指向已冻结的方案。 |

[网页搜索](../../src/personal_agent/tools/web_search.py) · [网页读取](../../src/personal_agent/tools/web_read.py) · [文件检查](../../src/personal_agent/tools/inspect_artifact.py) · [Python 参数](../../src/personal_agent/application/python_execution/models.py) · [检索实验参数](../../src/personal_agent/application/retrieval_experiment/models.py)

### 2.2 知识、研究记录与队列

| 工具 | 用途 | 必填参数 | 可选参数 |
| --- | --- | --- | --- |
| `graph_search` | 搜索个人知识图谱中的实体、关系和路径。 | `question`（非空字符串），要查找的实体或关系问题。 | `structured_context`（对象），标题、实体等检索线索。 `user_id`（字符串，默认 `"default"`），知识归属。 |
| `inspect_knowledge_gaps` | 分析知识库中的孤岛、薄弱连接及潜在冲突。 | — | `user_id`（字符串，默认 `"default"`），知识归属。 |
| `list_recent_notes` | 列出近期写入或更新的笔记。 | — | `user_id`（字符串或 `null`，默认 `null`），知识归属。 `limit`（整数，1–50，默认 10），最大条数。 |
| `get_note` | 按 ID 读取笔记详情，适用于核对精确正文。 | `note_id`（非空字符串），已有笔记 ID。 | `user_id`（字符串或 `null`，默认 `null`），知识归属。 `include_content`（布尔，默认 `true`），是否返回正文。 |
| `find_similar_notes` | 按主题搜索笔记，供回忆、查重或更新前定位。 | `query`（非空字符串），主题、问题或待查重内容。 | `user_id`（字符串或 `null`，默认 `null`），知识归属。 `limit`（整数，1–30，默认 8），最大条数。 |
| `list_research_subscriptions` | 列出周期研究订阅。 | — | `user_id`（字符串，默认 `"default"`），订阅归属。 `enabled_only`（布尔，默认 `true`），是否只列启用订阅。 |
| `list_research_runs` | 查看近期研究运行和投递状态。 | — | `user_id`（字符串，默认 `"default"`），运行归属。 `limit`（整数，1–100，默认 20），最大条数。 |
| `get_research_digest` | 读取指定研究运行的简报。 | `run_id`（非空字符串），研究运行 ID。 | `user_id`（字符串，默认 `"default"`），运行归属。 |
| `inspect_worker_queue` | 检查后台任务堆积、失败或终止状态。 | — | `queue`（字符串或 `null`），队列名称。 `statuses`（字符串数组或 `null`），状态筛选。两者默认 `null`。 `limit`（整数，1–100，默认 20），最大条数。 |

[图谱](../../src/personal_agent/tools/graph_search.py) · [知识缺口](../../src/personal_agent/tools/inspect_knowledge_gaps.py) · [笔记](../../src/personal_agent/tools/knowledge_lifecycle.py) · [研究管理](../../src/personal_agent/tools/research_management.py) · [队列](../../src/personal_agent/tools/operations.py)

## 3. 专用入口工具

本节工具声明为 `scoped_agent`。表中的 `user_id` 是归属参数，认证主体与作用域仍来自调用入口。

| 工具 | 用途 | 必填参数 | 可选参数 |
| --- | --- | --- | --- |
| `update_note` | 按明确要求修改已有笔记。 | `note_id`（非空字符串），待修改笔记 ID。 | `title`、`content`、`summary` 分别是新标题、正文、摘要，均为字符串或 `null`。 `tags` 是字符串数组或 `null`。 `user_id`（字符串或 `null`）表示知识归属。这些字段均默认 `null`。 |
| `supersede_note` | 建立新笔记替代旧笔记的版本关系。 | `old_note_id`、`new_note_id`（非空字符串），旧、新笔记 ID。 | `user_id`（字符串或 `null`，默认 `null`），知识归属。 `reason`（字符串，默认空），替代理由。 |
| `mark_note_deprecated` | 将笔记标记为过期并保留记录。 | `note_id`（非空字符串），待标记笔记 ID。 | `user_id`（字符串或 `null`，默认 `null`），知识归属。 `reason`（字符串，默认空），过期原因。 |
| `mark_notes_conflicted` | 标记多条笔记间的冲突。 | `note_ids`（至少两项的字符串数组），冲突笔记 ID。 | `user_id`（字符串或 `null`，默认 `null`），知识归属。 `reason`（字符串，默认空），冲突原因。 |
| `update_research_subscription` | 调整已有订阅的配置。 | `subscription_id`（非空字符串），订阅 ID。 | `user_id`（字符串，默认 `"default"`），订阅归属。 `name`、`topic`、`instructions`、`schedule_time` 分别为名称、主题、筛选说明、运行时间，均为字符串或 `null`。 `max_items`（整数 1–20 或 `null`）为简报条数，`enabled`（布尔或 `null`）为启用状态。除 `user_id` 外均默认 `null`。 |
| `pause_research_subscription` | 暂停指定订阅的后续调度。 | `subscription_id`（非空字符串），订阅 ID。 | `user_id`（字符串，默认 `"default"`），订阅归属。 |
| `resume_research_subscription` | 恢复指定订阅。 | `subscription_id`（非空字符串），订阅 ID。 | `user_id`（字符串，默认 `"default"`），订阅归属。 |
| `run_research_subscription_now` | 为指定订阅创建运行并入队，后台异步执行。 | `subscription_id`（非空字符串），订阅 ID。 | `user_id`（字符串，默认 `"default"`），订阅归属。 |
| `submit_research_feedback` | 记录用户对研究事件的反馈。 | `event_id`（非空字符串），事件 ID。 `action`（字符串）为 `expand`（展开）、`useful`（有用）、`not_interested`（不感兴趣）或 `save`（保存）。 | `user_id`（字符串，默认 `"default"`），用户归属。 `subscription_id`（字符串或 `null`，默认 `null`），关联订阅。 `comment`（字符串，默认空），补充意见。 |
| `save_research_event` | 将研究事件保存为长期知识笔记。 | `event_id`（非空字符串），待保存事件 ID。 | `user_id`（字符串，默认 `"default"`），知识归属。 |
| `retry_worker_task` | 按明确要求重新排队已进入 `dead` 状态的后台任务。 | `task_id`（非空字符串），待重试任务 ID。 | — |
| `enterprise_knowledge_search` | 汇总经批准的企业知识来源，返回统一证据。 | `query`（非空字符串），检索问题。 | `limit`（整数，1–20，默认 5），最大条数。 `user_id`（字符串，默认 `"default"`），兼容归属字段，执行取认证主体。 `run_id`（字符串或 `null`，默认 `null`），传给来源的运行标识。 |
| `enterprise.raw_wiki_<目录名>` | 搜索已配置且存在的目录中的 Markdown。每个目录派生一个工具名。 | `query`（非空字符串），检索问题。 | `limit`（整数，1–20，默认 5），最大条数。 `user_id`（字符串，默认 `"default"`）和 `run_id`（字符串或 `null`，默认 `null`）保留在参数契约中，文件检索不消费二者。 |

[笔记变更](../../src/personal_agent/tools/knowledge_lifecycle.py) · [订阅与事件](../../src/personal_agent/tools/research_management.py) · [队列重试](../../src/personal_agent/tools/operations.py) · [企业知识](../../src/personal_agent/tools/enterprise_knowledge.py) · [本地 Markdown 检索](../../src/personal_agent/tools/raw_wiki.py)

## 4. 内部工作流工具

| 工具 | 用途 | 必填参数 | 可选参数 |
| --- | --- | --- | --- |
| `capture_url` | 抓取指定网页正文，供采集链路后续处理。 | `url`（字符串，至少 8 字符），HTTP 或 HTTPS URL。 | — |
| `capture_upload` | 从已上传资源提取内容，交给统一采集写入口。 | `resource_ref`（资源引用对象），上传件。 `user_id`（非空字符串），采集归属。 | — |
| `capture_text` | 将用户明确要求保存的文本写入长期知识。 | `text`（非空字符串），要保存的正文。 | `user_id`（字符串，默认 `"default"`），知识归属。 `source_type`（字符串，默认 `"text"`），来源类型。 |
| `consolidate_knowledge` | 按主题整合相关笔记并建立替代关系。 | `topic`（非空字符串），整理主题。 | `user_id`（字符串，默认 `"default"`），知识归属。 |
| `review_digest` | 生成当前知识简报。 | — | `user_id`（字符串，默认 `"default"`），知识归属。 |
| `create_research_subscription` | 根据自然语言要求创建周期研究订阅。 | `request`（非空字符串），主题、周期与筛选条件。 | `user_id`（字符串，默认 `"default"`），订阅归属。 `target_id`（字符串，默认空），投递目标。 |
| `research_prepare_run` | 创建研究运行并进入运行状态。 | `topic`（非空字符串），研究主题。 | `user_id`（字符串，默认 `"default"`），运行归属。 `instructions`（字符串，默认空），补充筛选要求。 `max_items`（整数，1–20，默认 5），简报条数。 `lookback_hours`（整数，1–720，默认 24），回溯小时数。 |
| `research_initialize_state` | 初始化指定运行的研究状态、初始动作与查询策略。 | `run_id`（非空字符串），研究运行 ID。 | `user_id`（字符串，默认 `"default"`），运行归属。 |
| `research_run_loop` | 按证据缺口执行搜索、聚类和排序，更新研究状态。 | `run_id`（非空字符串），研究运行 ID。 | `user_id`（字符串，默认 `"default"`），运行归属。 |
| `research_synthesize_digest` | 根据该运行的事件与证据状态生成简报。 | `run_id`（非空字符串），研究运行 ID。 | `user_id`（字符串，默认 `"default"`），运行归属。 `max_items`（整数 1–20 或 `null`，默认 `null`），覆盖简报条数。 |
| `research_verify_digest` | 核对简报来源并降级证据不足条目。 | `run_id`（非空字符串），研究运行 ID。 | `user_id`（字符串，默认 `"default"`），运行归属。 |
| `verify_interaction_draft` | 用 Runtime 提供的成功标准与证据核验稿件，返回语义核验回执。 | `draft`（非空字符串），待验稿。 `success_criteria`（至少一项的字符串数组），成功标准。 | `cited_units`（对象数组，默认空）关联稿件片段和证据。 `source_reading_state`（对象数组，默认空）记录来源和已读范围。 `task_context`（对象或 `null`，默认 `null`）绑定目标定义或回答核验输入。 |

`cited_units` 的每项包含 `draft`（该片段的文本），可带 `execution_evidence`（证据 ID、文本和来源）。`source_reading_state` 的每项包含资源引用、来源 URL、已返回段数、总段数和全文已读状态。完整核验结构及不同职责的输入见源码和核验文档。[采集 URL](../../src/personal_agent/tools/capture_url.py) · [采集上传件](../../src/personal_agent/tools/capture_upload.py) · [采集文本](../../src/personal_agent/tools/capture_text.py) · [知识整合](../../src/personal_agent/tools/consolidate_knowledge.py) · [知识简报](../../src/personal_agent/tools/review_digest.py) · [创建订阅](../../src/personal_agent/tools/research.py) · [研究工作流](../../src/personal_agent/tools/research_pipeline.py) · [核验参数](../../src/personal_agent/tools/interaction_verifier.py) · [目标核验](goal-verifier.md) · [目标遵循核验](goal-compliance-verifier.md)

## 5. Conversation 直接声明的本地动作

这些名称出现在适用的模型请求中。它们由 Conversation 组装或从内部写入能力投影。以下字段按模型实际填写的形状记录。

| 模型调用名 | 用途与可见性 | 参数 Schema 摘要 |
| --- | --- | --- |
| `tool_create_artifact` | 普通文稿写入阶段创建新草稿。 | 必填 `filename`（文件名）、`content_type`（三种类型见第 2.1 节）、`content`（正文），均为字符串。 |
| `tool_patch_artifact` | 编辑现有业务草稿。 | 必填 `base_resource_id`（确切基稿 ID）和 `edits`（1–32 项）。每项必填 `start_line`、`start_column`、`end_line`、`end_column`（起止行列）与 `new_text`（替换文本）。坐标和替换规则同第 2.1 节。 |
| `tool_read_artifact` | 有当前可读原件时读取正文窗口。 | 必填 `resource_id`（原件 ID）。可选 `start_line`（起始行，默认 1）、`start_column`（长行续读起始列，默认 1）和 `limit`（最大行数，整数 1–2,000，默认 200）。 |
| `tool_search_action_output` | 有当前可读原件且已装配搜索时定位正文命中。 | 必填 `resource_id`（原件 ID）与 `keyword`（1–400 字符的关键词或正则）。可选 `regex`（布尔，默认 `false`）和 `result_offset`（从回执取得的分页偏移，非负整数，默认 0）。 |
| `tool_prepare_conversation_knowledge_save` | 已装配知识写入口时，准备待用户确认的保存。 | 必填 `selections`（至少一项），每项含 `source_message_index`（从 0 起计的消息索引）与 `text_span`（该用户消息的非空原文片段）。 |
| `tool_search_personal_knowledge` | 已装配知识读取器且本轮尚未成功检索时，查用户明确要求使用的已存事实。 | 必填 `query`（1–4,000 字符的检索问题），可选 `limit`（整数 1–8，默认 8）。 |
| `tool_list_personal_knowledge` | 已装配知识读取器时，列出条目供浏览或定位删除对象。 | 可选 `limit`（整数 1–50，默认 20）。 |
| `tool_prepare_knowledge_delete` | 已装配知识读取与生命周期服务时，为清单中已观察到的条目准备待确认删除。 | 必填 `target_knowledge_item_id`（条目 ID）和 `reason`（1–1,000 字符的删除理由）。 |
| `tool_prepare_workspace_changes` | 当前 Web 会话绑定获准工作区时，提交有序变更清单供一次确认。 | 必填 `changes`（1–64 项）。每项用 `kind` 区分 `create_directory`（含 `path`）和 `move_file`（含 `source`、`destination`）。路径为授权工作区内的规范 POSIX 绝对路径。 |
| `submit_goal_patch` | 在内联分析中单独提交任务归属和目标增量。 | 必填 `base_version` 和 `changes`。首个补丁可用 `task` 选择 `continue`、`start`、`side_question`、`resume`，显式选择引用本轮原话，恢复附候选任务 ID。省略时沿用当前任务，无当前任务时新开。版本取选中的任务，空目标填 0。条目操作与执行控制见[目标维护契约](../optimization/to_verify/analysis-goal-maintenance.md#当前改造版本化目标条目和增量提交)。 |
| `read_current_goal` | 已有目标时查询版本及本轮有效条目。 | 空对象 `{}`。读取保持目标状态和本轮维护前提。 |
| `control_working_plan` | 读取或维护工作清单。用于复杂、跨阶段、跨轮任务，或用户要求展示计划时。 | 空参数读取。首次创建传 `goal`（目标）和非空 `steps`（最多 12 项）。更新传 `steps`，默认替换，`merge: true` 按已有 `step_id` 合并并追加新项。每项传 `description`（结果与完成条件），可选 `step_id` 和 `status`（`pending`、`in_progress`、`completed`、`cancelled`）。新项默认 `pending`。可选 `grounding` 记录事实依据。先审阅时单独提交并设 `wait_for_user: true`。 |
| `control_request_clarification` | 向用户提出继续所需的澄清问题。 | 必填 `question`（1–2,000 字符，含非空白字符）。 |
| `control_submit_final` | 按当前回答阶段提交正文和沟通状态。 | 必填 `message`（非空正文）和 `disposition`（`answer`、`limitation` 或 `failed`，以当轮枚举为准）。可选 `references`（引用字符串数组，默认空）。 |

论断式研究阶段还会按进展生成 `control_select_research_evidence` 及写作动作。基稿 ID、片段和引用等约束随实际研究状态绑定。核对这些动作时查看当轮工具定义和回答模块。[读搜参数](../../src/personal_agent/application/conversation/artifact_reading.py) · [搜索参数](../../src/personal_agent/application/conversation/artifact_search.py) · [对话参数](../../src/personal_agent/application/conversation/models.py) · [工作区参数](../../src/personal_agent/application/conversation/workspace_changes.py) · [目标参数](../../src/personal_agent/application/conversation/goal_models.py) · [动作定义](../../src/personal_agent/application/conversation/model_actions.py) · [研究写作](../../src/personal_agent/application/conversation/answer_results.py)

`changes` 为一层操作列表。模型在 `add` 或 `replace` 中通过 `criterion` 提交验收条件，多项时在同一字符串内逐行填写。空字符串表示无单列条件，替换时省略该字段表示保留已有条件。Runtime 将合法文本转换为快照中的 `acceptance_criteria` 列表。提问使用 `clarifications`，答复或撤回后用 `resolve_clarification` 提交显示的 `clarification_id` 与当前用户原话 `evidence`。[目标上下文](agent-loop.md#goal-快照与待澄清事项)
