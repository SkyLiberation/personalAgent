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
5. `记忆层`：短期上下文、长期知识、问答历史、图谱记忆，以及候选待固化知识
6. `检索与推理层`：围绕问题找到证据，再组织成回答
7. `执行与反馈层`：把结果回给用户，并支持流式、异步、失败降级
8. `观测与治理层`：日志、健康检查、重试、权限、多用户隔离、评测

这个项目的定位是面向个人知识管理的 `knowledge agent`。判断它是否合格，重点在于是否能稳定完成知识采集、知识连接、记忆沉淀、检索问答、复习反馈和多入口接入这条主链路。

## 当前工程的 Agent 结构判断

| 组件 | 当前状态 | 代码落点 | 当前判断 |
| --- | --- | --- | --- |
| `入口层` | `合格` | [web/api.py](src/personal_agent/web/api.py), [feishu/service.py](src/personal_agent/feishu/service.py), [main.py](src/personal_agent/main.py) | 具备 Web API、前端、CLI、飞书多入口，核心请求可以进入统一 Agent 流程 |
| `意图识别 / 路由层` | `合格` | [agent/router.py](src/personal_agent/agent/router.py), [agent/entry_nodes.py](src/personal_agent/agent/entry_nodes.py) | 通过 `DefaultIntentRouter` 统一处理入口意图，支持 LLM 优先和启发式兜底 |
| `规划层` | `基础合格` | [agent/planner.py](src/personal_agent/agent/planner.py) | 已有 `DefaultTaskPlanner`，可以为 capture、ask、summarize 生成面向知识管理流程的基础步骤 |
| `运行时 / 编排层` | `合格` | [agent/runtime.py](src/personal_agent/agent/runtime.py), [agent/graph.py](src/personal_agent/agent/graph.py), [agent/nodes.py](src/personal_agent/agent/nodes.py) | `AgentRuntime` 统一执行入口，`LangGraph` 承担固定流程编排，`AgentService` 保持为薄 facade |
| `工具层` | `合格` | [tools/](src/personal_agent/tools), [capture/service.py](src/personal_agent/capture/service.py), [graphiti/store.py](src/personal_agent/graphiti/store.py) | 具备统一 Tool 协议、注册中心、意图匹配和失败回退链 |
| `记忆层` | `合格` | [memory/](src/personal_agent/memory), [storage/](src/personal_agent/storage), [core/models.py](src/personal_agent/core/models.py) | 有工作记忆、会话摘要、本地长期记忆、Postgres 问答历史和图谱字段映射 |
| `检索与推理层` | `基础合格` | [agent/runtime.py](src/personal_agent/agent/runtime.py), [agent/verifier.py](src/personal_agent/agent/verifier.py), [graphiti/store.py](src/personal_agent/graphiti/store.py) | 支持本地检索、图谱增强、回答校验和低置信度自修正；复杂推理和精确证据锚定仍可增强 |
| `执行与反馈层` | `合格` | [web/api.py](src/personal_agent/web/api.py), [agent/runtime.py](src/personal_agent/agent/runtime.py) | 支持同步 API、SSE、图谱失败降级、异步图谱同步和问答历史记录 |
| `观测与治理层` | `基础合格` | [core/logging_utils.py](src/personal_agent/core/logging_utils.py), [web/auth.py](src/personal_agent/web/auth.py), [tests/](tests) | 具备日志、health、reset、API Key 鉴权、限流、用户隔离和基础测试；审计和外部工具权限仍可补充 |

## 是否合格

当前工程已经可以判断为一个 `合格的知识管理 Agent`。它不是只把 LLM 接到接口上的问答应用，而是围绕个人知识管理目标，具备入口路由、运行时编排、工具调用、记忆、检索、回答校验、失败降级和基础治理的完整主干。

从当前定位看，它已经覆盖知识沉淀、问答、图谱增强、复习和飞书接入等核心场景。后续更值得投入的方向，是补齐知识生命周期节点，例如删除过时知识、从多轮对话中固化知识，以及继续提升检索质量、证据可追踪性、非结构化输入处理和持续评测能力。

## 当前框架摘要

当前后端以 `AgentRuntime` 为核心，`AgentService` 只保留兼容性的 facade 职责。入口请求进入 runtime 后，会经过意图路由、可选任务规划、LangGraph 节点编排、工具调用、记忆读写、答案生成、verifier 校验与必要的自修正，最后返回给 Web、CLI 或飞书入口。

需要特别说明的是：`execute_entry()` 当前虽然会在 pre-route 后调用 `DefaultTaskPlanner` 并把结果写入 `WorkingMemory.plan_steps`，但这些步骤还没有真正驱动后续执行。实际 entry 处理仍然由 `LangGraph` 的固定分支节点完成，因此 planner 目前更接近“已生成但未执行的计划记录”，而不是运行中的调度器。

当前目录形态：

```text
src/personal_agent/
├─ agent/
│  ├─ runtime.py          # AgentRuntime：统一执行入口
│  ├─ service.py          # AgentService：兼容性 facade
│  ├─ router.py           # IntentRouter：LLM-first + heuristic fallback
│  ├─ planner.py          # DefaultTaskPlanner：任务步骤分解
│  ├─ graph.py            # LangGraph 状态图编排
│  ├─ nodes.py            # capture / ask 节点
│  ├─ entry_nodes.py      # entry 分支节点
│  └─ verifier.py         # AnswerVerifier：回答证据校验
├─ tools/
│  ├─ base.py             # ToolSpec / ToolResult / BaseTool
│  ├─ capture_url.py
│  ├─ capture_upload.py
│  ├─ graph_search.py
│  └─ registry.py         # ToolRegistry：注册、匹配、回退执行
├─ memory/
│  ├─ facade.py           # MemoryFacade：工作记忆 + 长期记忆统一入口
│  └─ working_memory.py   # WorkingMemory：会话级短期状态
├─ web/
│  ├─ api.py              # FastAPI 路由
│  └─ auth.py             # API Key 鉴权与限流
└─ feishu/
   └─ service.py          # 飞书长连接、webhook、文件和消息回溯
```

典型 entry 执行链路：

```text
Entry
  -> Intent Router
  -> Planner (generate only, not execution-driving yet)
  -> WorkingMemory.plan_steps
  -> LangGraph branch
  -> Tool Execution
  -> Memory Update
  -> Verifier / Retry
  -> Final Response
```

## 当前框架已有能力

- `多入口接入`：Web API、前端、CLI、飞书长连接和 webhook 入口
- `统一运行时`：`AgentRuntime` 管理 capture、ask、digest、entry、图谱同步等核心流程
- `意图路由`：`DefaultIntentRouter` 支持 LLM 分类和启发式兜底
- `任务规划`：`DefaultTaskPlanner` 支持 capture、ask、summarize 的基础步骤分解，当前结果会写入 `WorkingMemory.plan_steps`
- `规划可视化基础`：运行时已经能产出 `plan_steps`，后续应把它作为可展开的用户可见规划，而不只停留在内部字段
- `工具系统`：`BaseTool / ToolSpec / ToolResult / ToolRegistry` 提供统一工具协议、匹配和回退执行
- `采集链路`：支持文本、链接、上传文件和飞书文件消息进入知识库
- `知识记忆`：本地笔记、复习卡、会话记录、Postgres 问答历史和图谱 episode 映射
- `工作记忆`：会话摘要、任务目标、推理步骤、工具缓存和规划步骤
- `问答链路`：本地检索问答、图谱增强问答、引用返回和证据片段组织
- `回答校验`：引用有效性、证据充分度评分、低置信度标注和自修正重试
- `飞书能力`：文本消息、文件消息、原消息回复、群聊消息回溯和总结入口
- `基础治理`：API Key 鉴权、用户隔离、限流、CORS 白名单、health 和 reset
- `测试覆盖`：单元测试、agent flows、API、CLI、storage 和 ask eval；当前 `pytest --collect-only` 收集到 107 条测试

## 仍需改进的地方

- `知识任务规划`：当前 planner 更像任务步骤模板，后续可以围绕知识整理、专题总结、复习计划等场景做更细的任务分解
- `规划执行断层`：`execute_entry()` 目前只生成 `plan_steps`，但尚未让 planner 参与节点调度、工具执行和校验闭环，文档与实现都应以“已生成、未接入执行”来理解
- `规划结果不可见`：当前 planner 结果只存在于运行时内存，用户无法展开查看 Agent 打算如何执行任务，也无法区分“计划步骤”和“实际执行结果”
- `记忆接入不均衡`：`MemoryFacade` 在 `ask` 链路中已参与会话摘要、上下文拼接和问答历史写入，但在 `entry / capture / HITL` 场景里还没有成为真正的执行核心
- `知识生命周期不完整`：当前主链路偏向 `capture / ask / summarize`，还缺少“删除过时知识”“将多轮对话沉淀为知识”这类显式节点
- `检索质量`：本地检索仍偏启发式，复杂问题下可能跨主题串题
- `证据锚定`：图谱 `relation_fact` 与 citation 的绑定还可以继续做得更精确、更可追踪
- `生成稳定性`：verifier 已能触发自修正，但答案的证据组织、可读性和一致性仍需要评测驱动优化
- `权限审计`：已有 API 鉴权和限流，但外部工具调用权限、操作审计和敏感数据边界仍待完善
- `评测体系`：已有基础测试和 ask eval，但还缺 ask、capture、graph 三条链路的持续回归评测数据集
- `非结构化输入`：文本、网页、PDF 文件已经可用，图片 OCR、音频 ASR 等输入还未接入

## Planner 接入现状与设计计划

### 当前现状

- `AgentRuntime.execute_entry()` 会先做 `pre_intent` 分类，再调用 `self._planner.plan(pre_intent, entry_input.text)`
- 规划结果会被序列化后写入 `WorkingMemory.plan_steps`
- 当前 `build_entry_graph(...).invoke(state)` 仍然只按 `state.intent` 选择 `capture / ask / summarize / unknown` 固定分支
- `entry_nodes.py` 中的节点不会读取 `plan_steps`，也不会根据 `PlanStep.tool / params` 动态执行
- `context_snapshot()` 目前不会把 `plan_steps` 拼入 prompt，因此这些计划也还没有参与回答生成和校验
- planner 结果目前也没有通过 API 返回给前端，用户侧看不到“Agent 计划怎么做”

### 设计目标

- 让 planner 从“记录计划”升级为“可观测、可约束、可逐步执行的运行时计划”
- 保留现有 `LangGraph` 固定主干，避免一次性把 entry 改成完全开放式 agent loop
- 先把 planner 接入 `entry`，验证稳定后再考虑是否复用到 `ask / capture`
- 在 entry 侧补齐知识生命周期节点，让系统不仅能“收”和“答”，还能“删”和“固化”
- 让 planner 结果以可展开的形式暴露给用户，做到“可看见计划、可区分执行进度、可用于调试”

### Planner 的用户可见性设计

planner 不应只是内部调试字段。对于 entry、ask、删除确认、对话固化等复杂任务，建议把“计划”作为界面中的一个可展开区域返回给用户。

推荐交互形态：

- 默认折叠显示一行摘要，例如“Agent 计划执行 4 步”
- 用户点击后展开完整步骤列表
- 每一步至少展示：
  - `step` 类型，例如 `retrieve / tool_call / compose / verify`
  - 对用户友好的说明文字，而不是仅显示原始内部枚举值
  - 对应工具名，例如 `graph_search / capture_url`
  - 当前状态，例如 `planned / running / completed / skipped / failed`
- 如果某一步是高风险动作，例如删除知识，应在展开面板中明确标识“待确认”

推荐的数据结构：

- `plan_id`
- `source_intent`
- `steps`
- `steps[].step`
- `steps[].label`
- `steps[].tool`
- `steps[].params`
- `steps[].status`
- `steps[].notes`
- `planner_mode`
  - 例如 `llm` 或 `heuristic`

推荐的返回策略：

- `EntryResult` 后续可增加 `plan` 字段
- SSE 场景可先返回 `plan_created` 事件，再逐步返回 `plan_step_updated` 事件
- Web 前端把它渲染为“可展开计划面板”
- 飞书等聊天入口可以退化为简版文本计划，例如“计划：1. 检索 2. 整理 3. 校验”

需要注意的边界：

- 用户看到的是“计划”和“执行状态”，不是完整的内部推理过程
- 不应暴露敏感 prompt、原始系统指令或不稳定的中间 reasoning
- `params` 需要做脱敏和裁剪，避免把过长原文、密钥、内部路径直接返回到 UI

### 建议新增的 entry 节点

当前 entry graph 主要覆盖 `capture / ask / summarize / unknown`。为了更贴近知识库真实使用过程，建议补入以下节点，并将其视为一级能力，而不是隐藏在普通对话里。

1. `delete_knowledge`

- 适用场景：用户明确表示某条知识已过时、错误、重复，想删除或撤销
- 典型表达：
  - “把刚才那条关于旧部署流程的笔记删掉”
  - “这个结论已经过时，不要再保留”
  - “删除我昨天记的那条关于供应商联系人信息”
- 建议节点职责：
  - 解析删除目标，优先支持按 `note_id`、标题、最近命中的 citation 删除
  - 先检索候选笔记，再做二次确认或安全校验，避免误删
  - 同步清理本地 note、review card，以及必要的图谱映射或失效标记
  - 返回结构化结果，例如“已删除 / 未找到 / 命中多个候选待确认”

2. `solidify_conversation`

- 适用场景：用户在多轮对话后认为某些结论值得沉淀进知识库，而不是只留在会话历史里
- 典型表达：
  - “把我们刚才讨论的结论记下来”
  - “把这个方案沉淀成知识卡片”
  - “把刚才关于缓存一致性的结论收进知识库”
- 建议节点职责：
  - 从当前 `session_id` 的最近若干轮对话中抽取候选事实、结论、决策和待办
  - 结合最近回答、`citations`、用户最后确认语气，生成适合固化的知识文本
  - 复用现有 `capture` 流程，把整理后的结果写入 `KnowledgeNote`
  - 在 note metadata 中标记来源为 `conversation` 或 `session_summary`

3. `confirm_delete_knowledge`

- 适用场景：删除命中多个候选，或系统判定存在误删风险时
- 建议节点职责：
  - 返回候选列表供用户确认
  - 记录一次“待确认删除”的短期状态，等待用户下一轮确认
  - 用户确认后再真正执行删除

4. `preview_solidify_conversation`

- 适用场景：用户希望先看将被沉淀的内容，再决定是否写入知识库
- 建议节点职责：
  - 先生成候选知识摘要，不立即写入 store
  - 返回给用户进行确认
  - 用户确认后再走 `capture`

### 新节点的数据与状态设计

- `EntryIntent` 建议新增：
  - `delete_knowledge`
  - `confirm_delete_knowledge`
  - `solidify_conversation`
  - `preview_solidify_conversation`
- `EntryInput.metadata` 建议逐步支持：
  - `note_id`
  - `candidate_note_ids`
  - `target_session_id`
  - `confirm_token`
  - `solidify_source`
- `WorkingMemory` 建议新增短期状态：
  - `pending_action`
  - `pending_candidates`
  - `pending_confirmation_token`
  - `last_answer_citations`
- `AgentState` 后续可考虑新增：
  - `pending_notes`
  - `pending_action`
  - `target_note_id`
  - `target_session_id`

### 新节点的推荐执行链路

1. 删除过时知识

```text
Entry
  -> Intent Router
  -> delete_knowledge
  -> retrieve candidate notes
  -> safety check / optional confirm
  -> delete local note + related review
  -> sync graph invalidation
  -> final reply
```

2. 从多轮对话固化知识

```text
Entry
  -> Intent Router
  -> solidify_conversation
  -> load recent conversation turns
  -> extract candidate facts / conclusions
  -> optional preview / confirm
  -> capture normalized knowledge text
  -> final reply
```

### 与 planner 的结合方式

- `delete_knowledge` 的计划模板建议为：
  - `retrieve`
  - `verify`
  - `tool_call`
  - `compose`
- `solidify_conversation` 的计划模板建议为：
  - `retrieve`
  - `compose`
  - `verify`
  - `tool_call`
- 对删除类操作，planner 不应直接决定最终删除，必须经过运行时安全门禁
- 对固化类操作，planner 负责组织步骤，但最终写入仍建议复用现有 `capture` 主链路，避免出现两套知识入库逻辑

### 删除类操作的 HITL 与 checkpoint 设计

删除知识属于高风险操作，建议默认接入 `HITL`，不要让 planner 或普通 entry 分支在单轮请求里直接完成最终删除。

这里可以区分两种实现方式：

1. `轻量 HITL`

- 第一轮请求只负责识别删除意图、检索候选笔记、生成确认提示
- 系统将候选项、删除目标、确认 token、过期时间持久化到存储层
- 第二轮由用户显式确认后，再进入真正的删除执行
- 这种模式不要求 LangGraph 在中途暂停恢复，因此不强依赖 checkpoint

2. `图中断恢复式 HITL`

- 删除流程在 LangGraph 中执行到“待人工确认”节点时中断
- 图状态通过 checkpoint 持久化
- 用户确认后，从原图状态继续执行后续删除节点，而不是重新做整轮路由和候选解析
- 这种模式通常需要 LangGraph 的 checkpoint / interrupt 能力配合

当前工程更建议先落地 `轻量 HITL`，再评估是否升级到 checkpoint 模式，原因是：

- 当前 `entry` 仍是固定分支 graph，而不是长生命周期 agent loop
- `WorkingMemory` 是进程内短期状态，不适合承载跨请求确认
- 当前最紧迫的问题是“删除前确认状态如何跨轮持久化”，这可以先在应用层解决
- 如果过早引入 checkpoint，会把运行时、存储和恢复语义一起复杂化

### 推荐的第一阶段删除确认方案

- 新增一张持久化的 `pending_actions` 或 `approval_requests` 表，用于保存待确认删除动作
- 首轮 `delete_knowledge` 不直接删数据，只写入：
  - `action_type=delete_knowledge`
  - `user_id`
  - `session_id`
  - `candidate_note_ids`
  - `resolved_note_id`
  - `confirm_token`
  - `expires_at`
  - `status=pending`
- 用户下一轮输入“确认删除”“删除第 2 条”之类消息时，路由到 `confirm_delete_knowledge`
- `confirm_delete_knowledge` 根据 token 或最近 pending action 找到目标，再执行真实删除
- 删除完成后，把 pending action 标记为 `confirmed`、`cancelled` 或 `expired`

### 什么时候值得引入 LangGraph checkpoint

当以下场景开始明显增多时，可以考虑把删除类 HITL 从“应用层两阶段确认”升级为“LangGraph 中断恢复”：

- 不止删除，审批、发布、外部写操作、批量修订等都需要人工确认
- 一个流程里存在多个连续的人工确认点
- 希望确认后从原执行上下文继续，而不是重新走 route / retrieve / match
- 希望统一观测“图暂停中”“等待用户确认”“恢复后继续执行”的状态机

换句话说：

- `要删除前确认` 不必然意味着必须立刻上 checkpoint
- `要在图执行中暂停并从原状态恢复` 才更明确地意味着需要 checkpoint

### 对当前项目的推荐顺序

1. 先把 `delete_knowledge` 做成应用层两阶段 HITL
2. 待确认状态放到持久化存储，不放在 `WorkingMemory`
3. 打通 Web / 飞书 / API 的确认交互
4. 等 `delete_knowledge`、`solidify_conversation`、更多审批类节点都稳定后，再评估统一接入 LangGraph checkpoint

## 记忆模块接入现状与设计缺口

### 当前已经接入的部分

- `AgentRuntime` 已统一持有 `MemoryFacade`
- `execute_ask()` 会绑定 `session`、刷新会话摘要、读取 `working context`，并在回答后写入问答历史
- `MemoryFacade.record_turn()` 会把问答写入 Postgres 或本地会话存储，并回刷会话摘要
- `execute_entry()` 也会绑定 `session`、刷新摘要、写入 `task_goal` 和 `plan_steps`

### 当前尚未真正接上的部分

- `plan_steps` 目前只写入 `WorkingMemory`，没有被 entry 节点或 planner executor 读取
- `WorkingMemory.context_snapshot()` 当前不会把 `plan_steps` 拼入 prompt，因此规划结果没有真正进入生成链路
- `capture` 链路几乎只使用了 `task_goal`，没有利用会话级上下文来辅助知识整理
- `entry` 虽然会刷新会话摘要，但实际路由和分支执行并不依赖记忆模块决策
- 删除确认、固化确认、待处理候选项等跨轮状态还没有纳入 memory 体系
- `WorkingMemory` 是进程内短期状态，不适合承载跨请求的人机确认流程

### 当前判断

当前项目的记忆模块不是完全未接入，而是“在 `ask` 中已起作用，在 `entry / capture / HITL` 中仍偏挂接状态”。

更具体地说：

- `ask` 链路里，memory 已经参与上下文组织和历史沉淀
- `entry` 链路里，memory 目前更多承担“记录 goal / plan / summary”的角色
- 对删除、固化、确认这类知识生命周期动作，memory 还没有成为统一状态中枢

### 推荐补齐方向

1. `先补可见性`

- 在 `context_snapshot()` 中显式加入 `plan_steps`、最近命中的 `citations`、待确认动作摘要
- 为 memory 读写增加日志，便于观察哪些链路真正消费了 memory

2. `再补 entry 侧消费`

- 让 `entry` 节点读取 `WorkingMemory` 中的 `plan_steps`、最近回答引用、待确认动作
- 让“删除确认”“固化确认”优先利用最近一轮 `citations` 和会话摘要做目标解析

3. `区分短期记忆与持久化待办`

- `WorkingMemory` 继续承载进程内短期上下文和运行时 scratchpad
- 跨请求状态，例如 `pending delete`、`pending solidify preview`，放入持久化存储，而不是只放在 `WorkingMemory`

4. `让记忆服务于知识生命周期`

- `solidify_conversation` 直接消费最近若干轮问答历史和回答引用
- `delete_knowledge` 优先从最近 `citations`、最近新增 note、最近命中的候选项里解析删除目标
- 后续如果加入“更新知识”“合并重复知识”，也应该共用这套 memory + pending action 机制

### 分阶段接入计划

1. `观测接入`

- 在 `WorkingMemory.context_snapshot()` 中加入 `plan_steps` 摘要，让后续生成与校验阶段能够感知当前计划
- 为 `execute_entry()` 和分支节点增加日志字段，至少记录 `pre_intent`、最终 `intent`、`plan_steps`、实际执行分支、命中的工具
- 补一组测试，明确当前 planner 仅生成不执行的行为，作为后续重构基线
- 同时为 `delete_knowledge` 与 `solidify_conversation` 先补意图识别测试和文档化样例
- 让 API 至少能返回只读的 `plan_steps`，前端先以折叠面板形式展示“计划草案”

2. `只读约束接入`

- 在 `EntryNodeDeps` 或 `AgentState` 中显式传入 `plan_steps`
- 各 entry 分支节点开始读取计划，但第一阶段只做一致性检查，不改变执行路径
- 例如 `ask` 分支可校验计划里是否包含 `retrieve -> compose -> verify`，`capture_link` 分支可校验是否声明了 `tool_call`
- 当计划与实际分支明显冲突时，记录 warning，并继续走固定分支，先不阻断请求
- 同阶段补充 `delete_knowledge` 与 `solidify_conversation` 的只读路由和候选解析测试，但先不开放真实删除执行

3. `受控执行接入`

- 为 entry 引入一个轻量 `plan executor`，只支持有限白名单步骤：`retrieve`、`tool_call`、`compose`、`verify`
- `tool_call` 仅允许映射到已注册工具或 runtime 已暴露的方法，禁止 planner 直接决定任意函数调用
- 将现有 `capture_entry_branch_node / ask_entry_branch_node / summarize_entry_branch_node` 改造成“默认执行器”，由 executor 按计划选择是否触发
- 保留回退策略：计划执行失败、参数不合法、工具未注册时，退回当前固定分支逻辑
- 在这一阶段优先落地 `solidify_conversation`，因为它可以复用当前 `capture` 主链路，风险低于直接删除
- 同阶段把 plan 面板从“静态计划”升级为“带状态的执行计划”，让用户能看到每一步是否已完成

4. `图结构重构`

- 在 `build_entry_graph()` 中增加显式的 `plan_gate` 或 `execute_plan` 节点，把“按计划执行”和“按固定分支执行”分离开
- 让 `route` 的输出不只决定 `intent`，也决定本次是否启用 planner execution
- 逐步把 summarize、capture_link、capture_file 这类强依赖工具的场景优先迁入 plan executor，因为它们的步骤边界更清晰
- 同时引入 `delete_knowledge -> confirm_delete_knowledge` 的两阶段删除路径，把高风险操作从普通分支里隔离出来

5. `稳定性与验收`

- 增加集成测试覆盖 `entry -> planner -> executor -> fallback` 全链路
- 为 planner 产出的步骤建立最小 schema 校验和版本约束，避免 LLM 输出漂移直接影响执行
- 增加评测样本，比较“固定分支执行”和“计划驱动执行”在成功率、延迟和回答质量上的差异
- 为删除与固化场景增加单独验收项：误删率、确认率、固化后知识可读性、重复知识率

### 推荐落地顺序

- 先完成第 1、2 阶段，把 planner 变成可观测、可校验但不改行为的组件
- 再在 `summarize_thread` 和 `capture_link` 场景试点第 3 阶段，因为它们比开放问答更容易控制步骤边界
- 最后再决定是否让 `ask` 真正进入 planner-driven execution；如果收益不明显，可以继续保留当前 `graph_store.ask -> build_ask_graph` 的专用链路

## Planner 可视化设计补充

### 为什么需要展开式计划

- 对用户来说，复杂任务不应只有最终答案，还应该能看到 Agent 准备怎么做
- 对调试来说，计划面板能帮助区分“路由错了”“检索错了”“执行失败了”
- 对高风险操作来说，展开式计划能自然承载“待确认”“已跳过”“执行失败”等状态

### 推荐的前端呈现方式

- 在回答卡片中增加一个 `查看计划` 折叠入口
- 默认只展示简短摘要，不干扰普通用户
- 展开后按时间顺序列出步骤
- 已执行步骤显示状态和时间戳
- 尚未执行的步骤显示为 `planned`
- 被回退替代的步骤显示为 `skipped` 或 `fallback`

### 推荐的后端支持

- `PlanStep` 增加用户可读 `label`
- 增加 `PlanView` / `PlanStepView` 之类的返回模型，避免直接暴露内部 dataclass
- runtime 在生成 plan 后立即构造可返回的视图模型
- 后续 executor 接入后，步骤状态由 `planned` 更新为 `running / completed / failed / skipped`

### 分阶段落地建议

1. 第一阶段只返回静态计划，不显示执行状态
2. 第二阶段把实际执行结果回填到每个 plan step
3. 第三阶段在 SSE 中增量推送 plan 状态变化
4. 第四阶段将删除确认、固化预览等 HITL 节点也并入同一个计划面板

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
      ├─ agent/                 # Agent 核心层（runtime / router / planner / graph / verifier）
      │  ├─ runtime.py          # AgentRuntime：统一执行入口
      │  ├─ service.py          # AgentService：薄 facade
      │  ├─ router.py           # DefaultIntentRouter：LLM-first 意图分类
      │  ├─ planner.py          # DefaultTaskPlanner：任务步骤分解
      │  ├─ graph.py            # LangGraph 状态图编排
      │  ├─ nodes.py            # capture / ask 节点
      │  ├─ entry_nodes.py      # entry 路由节点
      │  └─ verifier.py         # AnswerVerifier：回答证据校验
      ├─ capture/               # 采集编排、provider 和抽取工具层
      ├─ cli/                   # 命令行入口层
      ├─ core/                  # 配置、日志、核心数据模型
      ├─ feishu/                # 飞书接入（长连接 + webhook、文件下载、消息回溯）
      ├─ graphiti/              # Graphiti、Neo4j、LLM、Embedding 接入
      ├─ memory/                # 工作记忆与会话摘要（MemoryFacade / WorkingMemory）
      ├─ storage/               # 本地 JSON 和 Postgres 存储层
      ├─ tools/                 # 统一 Tool 抽象与注册中心
      ├─ web/                   # FastAPI Web 接口层
      │  ├─ api.py              # API 路由（capture / ask / digest / notes / tools）
      │  └─ auth.py             # AuthMiddleware + RateLimiter
  ├─ tests/                     # 单元 + 集成测试（107 条：router / tools / verifier / memory / storage / agent-flows / API / CLI）
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

- 文本消息可以路由到 `capture_text / capture_link / ask`
- 文件消息可以下载、提取正文并进入知识库采集
- 群聊总结可以拉取近期消息并交给 LLM 生成摘要
- 回复优先使用原消息 `message_id`
- 长连接事件做了短时去重，避免重复处理同一事件

### 开发注意事项

- 如果飞书后台配置为“长连接接收事件”，就不要再把问题排查重点放在公网 webhook 地址上
- 如果改回“将事件发送至开发者服务器”，才需要配置 `POST /api/integrations/feishu/webhook`
- 飞书长连接模式下，事件需要在 3 秒内快速确认，因此当前实现采用“事件线程快速接收 + 后台处理”模式
- 同一事件可能被飞书重推，当前代码已做基于 `event_id` 的短时去重

### 后续建议

1. 继续增强意图判别稳定性
2. 如果未来同时保留长连接和 webhook 两种模式，需要在 README 和部署文档里明确说明当前选用哪一种
3. 为文件消息增加更多格式支持（图片 OCR、音频 ASR）

## CLI 用法

当前仍保留 CLI 入口：

```bash
uv run python -m personal_agent.main capture --text "服务降级是在系统压力过大时，主动关闭非核心能力"
uv run python -m personal_agent.main ask --question "什么是服务降级？"
uv run python -m personal_agent.main digest
```

## 已知限制

当前工程已经具备可运行的主链路，但仍有一些问题需要继续收敛：

1. `ask` 的检索排序仍然偏启发式，复杂问题下仍可能出现跨主题串题
2. `citation` 与图谱 `relation_fact` 的绑定还没有做到严格可追踪的精确锚定
3. `capture` 当前覆盖文本、网页链接和 PDF 文本提取，OCR、语音 ASR 等非结构化输入仍未接入
4. 回答链路包含上下文总结和 verifier 自修正，但证据组织和答案质量仍需要持续评测
5. SSE 现在是服务端分段推送已有答案，还不是直接透传上游模型 token 流
6. `ask history` 可以持久化到 Postgres，但搜索、删除等会话管理能力还不完善
7. 调试重置可以清理当前用户本地数据、问答历史、上传源文件和图谱分组，但还没有做更细粒度的选择式清理
8. Windows 下 Vite 默认端口 5173 可能被系统保留（Hyper-V/WSL 动态端口范围），导致 `EACCES` 权限错误，需改用其他端口（如 3000）

## 后续建议

最值得继续推进的方向是：

1. 优化 `ask` 的检索排序，减少跨主题串题
2. 继续增强 `citation` 与 `relation_fact` 的精确绑定
3. 继续扩展 `capture` 到语音和 OCR
4. 继续提升生成式答案的证据组织、可读性和稳定性
5. 给 `ask history` 增加搜索、删除和更完整的会话管理能力
6. 建立 ask / capture / graph 三条链路的回归评测体系
