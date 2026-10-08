# Context 工程

本文拥有当前模型上下文收集、过滤和物化规则。Context 是一次模型调用的受控输入；Conversation、个人长期知识和周期研究继续由各自事实责任主体维护。

## Visibility 的定义与分层

**结论：当前不存在 workspace visibility 层。资源 Visibility 是 Application 在 retrieval 前，根据
`AuthenticatedPrincipal`、canonical resource ownership 和当前执行缩权计算出的可见候选集合。**长期个人知识
直接归属 tenant 内的 principal；Conversation、Execution、Project 和 Task 只关联上下文或执行，不能授予另一用户的资源。

资源侧只有四类边界；每类只控制自己的事实，不能向下游转让决策权：

| 层 | 控制什么 | 不控制什么 | 当前实现状态 |
| --- | --- | --- | --- |
| Tenant | 顶层组织隔离、租户级身份与策略边界 | 不直接拥有某个用户的个人知识 | `AuthenticatedPrincipal.tenant_id` 是 typed 边界；Application 校验 tenant 一致性 |
| Principal / User | 操作者身份，以及个人长期知识、Artifact 和偏好的 canonical owner | 不拥有另一 principal 的资源，也不等于一次 Conversation | API key 解析为 `AuthenticatedPrincipal(tenant_id,user_id)`；资源 owner 使用同一 typed principal |
| Thread / Conversation | 本次会话的 committed messages、Observation 和会话内引用 | 不授予长期知识，也不改变资源 owner | Interaction journal 按 conversation/thread 恢复；跨 Conversation 的长期知识仍按 principal 读取 |
| Execution / Project / Task | 当前运行可使用的资源、Tool、预算和父级关联 | 不成为资源 owner，也不能扩大 principal 原有权限 | `ExecutionScope` 绑定 principal、execution 与可选 project/thread/task；授权只能保持或缩小 |

存储中的内部 owner key 由认证 principal 确定性派生，不是调用方可选择的产品 scope。HTTP 请求不能通过提交
`owner_id` 或其他分区 ID 改写资源归属。未来若真实用户目标要求多人共享或同一用户隔离多个知识集合，必须先用
正式入口执行同目标 baseline 并证明当前失败，再引入有明确 owner、membership 和生命周期的业务 Aggregate；不得
恢复一个无场景的通用 workspace。

能力侧是另一条正交链，禁止和资源归属混为一个 `visibility` 字段：

| 阶段 | 回答的问题 | Owner |
| --- | --- | --- |
| Definition / Availability | 能力是否注册、远端是否 discovery、Provider 当前是否可用 | Application capability owner / Runtime observation |
| Exposure | 这种 Agent 是否应该看到 schema，例如 `public_agent`、`scoped_agent`、`workflow_activity` | Tool/Application definition |
| Authorization | 当前 Principal 在当前 scope 是否允许调用 | Policy / Admission / Gateway |
| Requirement Retrieval | 已授权能力中哪些与当前目标相关 | Application retrieval；只能缩小集合 |
| Budget Materialization | 哪些摘要、schema 和事实真正进入本轮 LLM Context | Context builder |

`exposure=public_agent` 不等于所有用户获权，Provider available 不等于获权，retrieval 排名也不等于
获权。原文“visibility 必须先于 retrieval”具体指：**先由前三类权威事实产生 authorized set，再在
集合内按需求检索；不能先全局召回后过滤。**

**当前实现边界**：资源链已按 Principal 先过滤；Conversation 的 capability projection 只消费
definition/availability/exposure，没有 Principal/Policy 输入，也没有 capability requirement retrieval。
因此 `EffectiveCapabilities` 只能称“模型可见集合”，不能称 authorized set。调用时仍必须由
Admission/Gateway 校验 Authorization；只有失败 E2E 证明全量可见集合造成误选、成本或延迟问题后，才准入
per-principal filter 或两阶段 capability discovery。

## 四阶段协议

```text
1. Visibility
2. Requirement Retrieval
3. Semantic Selection
4. Budget Materialization
```

### Visibility

入口先解析 authenticated principal；Application 再从 canonical ownership 和 policy 得到可见资源集合，并用
`ExecutionScope` 表达本次运行的关联与缩权。Repository、Tool、Artifact、Memory 和 Retrieval Adapter 必须先在
这个授权集合内过滤；禁止相信请求体中的裸 owner key，也禁止先取回全部内容再让 Prompt 隐藏不可见数据。

### Requirement Retrieval

Application 根据当前用户目标调用明确能力：

- Conversation 历史：读取 committed message/observation；
- 个人长期知识/local：检索当前 principal 拥有的 Artifact、EvidenceSpan、Claim 或 Note；
- Graph：检索 fact、edge、episode 和 citation ref；
- Web/Tool：只经过 Policy/Gateway 获取当前执行结果；

该阶段只产生候选和执行事实，不生成业务答案。

### Semantic Selection

开放世界的相关性、冲突表达和回答重点由模型或领域语义组件判断。确定性 Admission 只检查候选是否
来自本次可见集合、ref 是否存在、scope 是否一致和预算是否满足，不补造 evidence 或改写用户目标。

### Budget Materialization

候选统一为 typed context item，经去重、排序、压缩和字符/token 预算形成 ContextPack。大对象以
ArtifactRef 或 source span 读取必要片段，不复制进 runtime state。最终 Prompt 只包含本次模型调用
真正可见的内容。

## Conversation 上下文

Conversation 的短期事实由 Interaction journal 持有：

```text
committed user/assistant messages
+ accepted ActionObservation / DecisionFeedback
+ current usage and action order
-> bounded model context
```

历史 assistant reply 只用于指代和会话连续性，不能作为事实证据。Tool/Agent observation 必须保留
typed status、artifact/receipt ref 和错误分类；不能只压成一段无法区分来源的自然语言。

### 单次 Observation 的体积边界

**回合 token 上限不约束单次工具返回，因此单次体积必须由独立机制执行。** owner 是
`application/conversation/observation_bounds.py`，语义与判据见
[ADR 0013](../adr/0013-bounded-observation-and-offloaded-read.md)：

| 事实 | 写入口 |
| --- | --- |
| 一次 Observation 能进入 Context 的体积（`MAX_OBSERVATION_PAYLOAD_CHARS = 20_000`） | `bound_observation_payload` |
| 被卸载文本的形态 | 通用结果由 `select_offload_text` 选择；网页正文明确选择 `source_text`；网页搜索保存不含查询参数的完整结果 JSON |
| 某个正文窗口的内容 | `read_artifact_text` 按正文行读取；长行的实际列范围与 `next_read` 明确续读位置 |
| 「读哪一段」 | 模型用 `search_action_output` 搜索，用 `read_artifact` 的 `start_line` / `limit` 读取同一正文 |
| 「未读完能否收尾」 | `ConversationService._unread_offloaded_resource`；所有 disposition 均受约束 |

被界定的 Observation 回带 `retrieval.omitted_chars`、`original_chars` 与 `resource_ref`，
所以「这个远端输出读过没有」是对 committed inputs 的纯函数判定，不需要另存已读集合。
卸载失败时 `unavailable_reason` 可见，不静默。

### 网页来源正文保留与重读

**已取得的提取文本先保留，再由 Observation 边界限制模型输入；搜索摘要不能冒充网页正文。** `CaptureService.capture_url()` 返回 typed `UrlCaptureResult(url, text, provider)`，抓取 Provider 不再把返回文本静默截成 12,000 字符。完整仅指保留 Provider 实际交付的提取文本，不保证动态网页、图片或 Provider 未返回内容也已取得。

内置 HTML 提取的唯一 owner 是 `application/capture/utils.py`：页面有唯一外层 `main` 或 `role="main"` 时选择该区域，并移除其中明确的 `nav`／`role="navigation"`；位于 `script/style/noscript` 祖先中的区域不参与选择。无主区域或多个外层主区域时保留原全文范围，不按题目关键词、长度或站点规则猜测正文。正文内的 `header`、`footer` 不额外过滤。

选定范围后，原解析器按原文顺序连接内联文本，以块、表格单元格和定义项为边界输出，普通段落只折叠 HTML 空白，`pre` 保留换行和缩进；不全局去重文本节点、词语或段落。`script/style/noscript` 仍排除。该实现不运行 JavaScript、不计算 CSS 可见性，不承担来源权威判断或事实校验。新正文使用自身 Artifact 身份和行坐标，不重写历史版本。确定性反事实、最终代码的正式 Capture 消费与精确读取检查点已成立；完整研究仍有修订、预算和成文解析阻塞，不能将局部验收写成 Product E2E 通过。验证与保留边界见[正文提取第 110 节](../optimization/source-extraction.md#110-唯一主区域选择的保真与正式消费验证)。

`web_search(query, limit)` 的 `results/evidence` 只保存发现摘要，`WebSearchOutput` 同时保存执行使用的 `query/limit`，不再接受 `scrape` 或隐式抓取前两个结果。`web_read(url)` 由模型直接选择来源，经同一 `CaptureService` 返回 `WebReadOutput(source_url, provider, source_text)`；失败由 `ToolArtifact` 表达，不返回伪成功正文。原 `capture_url` 仍服务确定性 Research 采集流程，不进入普通模型可见工具面，两者共用抓取事实 owner。

成功正文由 `application/capture/web_source.py` 原样保存在 `source_text`，URL 与服务方由外层 `WebReadOutput` 拥有；不把 JSON 元数据混入正文搜索。网页格式为 `web-source-text-v2`。网络响应上限仍为 4 MiB，提取正文上限为 16 MiB；超限显式失败，不宣称全局容量。

目标代码的搜索与读取共同使用正文行号，分别返回命中位置和连续窗口。只搜索到局部不能视为全文已读；超长行按 `next_read.start_column` 续读，代码累计实际范围，覆盖一整行才计入完整行。正文及参数共同受 20,000 字符 Observation 上限约束。Artifact 的 UTF-8 字节读写保持换行，不让宿主操作系统转换原文。旧读取实现保留但不投影且准入拒绝，无回退；试接入范围、证据与风险见 [ADR 0024](../adr/0024-plain-source-tools-and-inline-citations.md)。

正文保留与重读的历史缺陷证据，以及搜索/读取分离候选的当前结果，分别由[当前评测用例盘点](../evals/02-current-case-inventory.md)维护。既有保真修复闭环不能替代新候选准入，也不证明通用事实合成正确率、网络稳定性或成本下降。

### Artifact-backed Observation 的请求级物化

**Journal 保存完整 bounded Observation；模型后续回合不重复接收其中无证明力的截断正文。**当 Observation 已有
`retrieval.resource_ref` 时，`context_materialization.py` 保留状态、omission metadata 和重读 ref。对具有合法
`WebReadOutput` 的网页结果，还保留已提交的 `source_url/provider`：指定来源和抓取 Provider
不会随正文消失；投影的 `source_text` 为空，已有 omission 标记和同一 ref 表示正文仍在 Artifact 中。
这不代表正文已读，也不构成证据充分或任务完成结论。Final 与 Verifier 复用同一投影，未读门禁不放宽。
当前搜索和 `read_artifact` 返回的窗口原样保留。该投影是 request-local view，不改写 journal，不增加已读
状态，也不把 Artifact 复制成第二事实源。

CTX-001 的正式 HTTP E2E 同时读取三份超大冻结资料。改动前第二轮 typed inputs 为 48,815 字符、累计
37,516 tokens，Runtime 在模型重读前耗尽历史总预算；更早的一次运行还证明模型会直接把截断头尾中的哈希
误报为证据。另一次复跑还暴露模型连续重调原 MCP、12 次取得相同截断结果直至 Tool 预算耗尽。当前
Admission 在同 capability 已有未读卸载结果时拒绝这种无进展 refetch，并要求使用已有 `ResourceRef`；
拒绝不消耗 Tool 预算。最终执行中模型用三个 `read_action_output` 窗口取得随机事实，typed inputs 为
2,025 / 6,332 字符，三轮累计 18,512 tokens，并返回修正后的阈值。

该证据只准入 Artifact-backed Observation 投影、“未重读不得 answer”和“未读结果不得由同资源 refetch
冒充重读”。它**没有证明**普通 Conversation messages
需要 segment index、滚动摘要、向量化历史或 Provider 原生 compaction，因此当前不实现这些机制。若未来同一自然
用户目标在消息历史增长上失败，必须重新取得独立 baseline。

### 拒稿后的完整基稿交接

最新完整提交以 `SubmittedFinal` 保存在原交互日志中，后继请求展示其完整 `segments`、引用关系和带作用域的版本引用；旧提交保留供审计，不重复进入模型上下文。该提交是待核验数据，不是来源支持事实；完整稿及局部修订的消费边界见 [ADR 0031](../adr/0031-complete-final-revisions.md)。交接检查点及证据范围见[固化记录](../optimization/completed/complete-rejected-draft-handoff.md)，不据此声称模型修订稳定。

### 可见证据的随文引用编号

Action 和 Final 在同一可见输入上生成 `CitableInput`，全部引用统一放在 `citations` 中，使用文档号与行号，如 `d1:1698`；同文档版本同位置重复返回沿用身份，连续整行可写为 `d1:1697-1700`，每行都须实际完整返回，部分长行保留实际字符范围。网页正文保留原文行，结构化工具结果以明确的结果文档分行，搜索摘要不能当作网页正文；不再提供整条结果号。Conversation 选择单行、连续整行或实际返回的字符片段，运行系统按同一目录逐行恢复内容和来源；位置一致性断言拒绝同坐标不同内容，不读取隐藏 Artifact、不选择邻片、不代替支持判断。执行记录保持原值，文档号只是当前可见集合的派生别名，不能跨交互复用。失败、Verifier 输出和卸载摘要不产生引用，正文不因漏引被丢弃。契约和 Offline 验证范围见 [ADR 0030](../adr/0030-document-line-citation-identity.md)。

### 查询执行事实与来源证据

当前接入代码由原搜索执行函数提供实际查询参数：网页为 `query/limit`，本地为 `keyword/regex/result_offset/resource_ref`。零命中保留这些条件，不按相同结果、URL 或 Plan 自述合并查询。`CitableInput.executed_query` 是请求内执行说明；引用恢复只使用排除查询字段的来源投影，位置规则由上节引用契约拥有。网页搜索卸载时，完整发现结果保存为可读 JSON，查询留在有界元数据，重读不会把查询词变成来源证据。

查询说明随原 `materialize_citation_context` 进入既有 `Typed execution inputs` 消息，最新 Verification 的原有保留规则不变。整体 Context 行为候选已撤回；当前没有新增历史 user 消息、独立反馈分区或扩源指令。本轮局部成果见[完成文档](../optimization/completed/query-execution-handoff.md)，候选失败、保留范围及产品限制见 [ADR 0026](../adr/0026-separate-query-facts-from-cited-evidence.md)。

### 上下文构成度量

`TurnContextComposition` 逐轮记录**四个互不重叠且加总等于该轮实际发出输入**的字符分段——
capability 投影、system prompt 其余部分、committed messages、typed inputs——以及独立的原生 action definitions 分段，外加 Provider
报告的 `input_tokens` 与 `turn_index`，随 `InteractionTrace` 生命周期存在。

三条边界使它属于 Observability 而非产品行为：

- 记录在 `generate` 调用**之后**发生，不参与 `visible_messages` 组装，`context_projection_ref`
  的 digest 不变；
- 用字符而非 tokenizer：字符由发出的字符串直接派生，tokenizer 会引入第二套 Provider 相关口径；
- 不进入任何终止判据、预算判定或 Admission 分支。

它可由 committed inputs 确定性重算，不构成第二写入口。逐轮构成属于 Observability 事实，不进入
Context 选择、预算、Admission 或终止分支。

Conversation 从原 Interaction Journal 恢复消息、工作清单和已提交执行资料。周期 Research 从自己的业务存储及 worker queue 恢复，具体生命周期见 [Memory](memory.md#恢复边界)。

## 有证据的对话上下文

个人知识由模型按需选择 `search_personal_knowledge` 后，以只读证据进入同一 Conversation；外部工具返回实际执行结果和可见来源。普通交付、研究 claims 与独立汇总按各自相位消费这些事实，不运行第二条 Ask 成文链。检索资源和组件评测的边界见[检索专题](retrieval-reasoning.md)，产品检查点见[Grounded Answer 链路](../workflow/capture-ask-model-flow.md)。

## 上下文腐化防护

- assistant 历史、provider answer、trace text 和 model self-report 不成为 evidence；
- visibility 在 retrieval 前执行；
- ContextPack 的 item 必须能回指 canonical source 或 execution fact；
- verifier 只能引用本次 admitted evidence；
- repair 使用原 Goal、当前候选和 typed verification feedback，不修改权限或 Command；
- summary 只能是非权威的上下文压缩视图，不能覆盖原消息或 Claim；
- Prompt 不承担授权、唯一性、幂等和状态迁移。

## 持久化规则

只在恢复、审计、重放、授权边界或长生命周期一致性要求下持久化上下文来源。可从 canonical facts
确定性重建的 ContextPack、排序分数和压缩文本默认不持久化为第二事实源。

| 数据 | 是否持久化 | 原因 |
| --- | --- | --- |
| Interaction committed input | 是 | Conversation 恢复与审计 |
| Personal Knowledge Claim/EvidenceSpan | 是 | 长期知识事实 |
| ResearchRun 与执行引用 | 是 | 周期研究恢复、审计与投递关联 |
| 被卸载的 Observation 正文 | 是，作为 Artifact | 本次交互内需可重读；`producer_key` 幂等，身份是 `ResourceRef` |
| Artifact-backed Observation 的紧凑模型投影 | 否 | 可从 committed Observation 确定性重建；只用于本次调用 |
| `TurnContextComposition` | 是，随 `InteractionTrace` | 与 committed inputs 同生命周期，可由其重算 |
| Retrieval candidate pool | 默认否 | 可重建的单次运行视图 |
| LLM Context/Prompt | 默认否 | 临时物化；必要时只保存 digest/ref |
| embedding / graph index | 可持久化投影 | 可失效并从 canonical source 重建 |

Memory 生命周期和事实 owner 见 [Memory 与知识事实边界](memory.md)；验证后的关闭条件见
[Verification 与 Completion](verification-and-completion.md)。
