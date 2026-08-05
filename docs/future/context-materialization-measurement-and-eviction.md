# Context 物化的度量、逐出与两阶段能力加载

本文是 [可信 Agent Runtime 演进与收敛](trusted-agent-runtime-evolution.md) 第 7 节中
「两阶段 capability discovery」与「Context compaction」两行候选的详细设计，不是第二个 owner：
准入与退出仍由那份路线图判定，本文只补齐这两条候选各自的机制、边界和缺失的准入前提。

Context 四阶段协议、持久化规则和腐化防护的 canonical 文档是
[Context 工程](../topics/context-engineering.md)；单次 Observation 的界定与卸载重读已落地，
见 [ADR 0013](../adr/0013-bounded-observation-and-offloaded-read.md)。本文不复制这两处事实。

## 1. 结论先行

这一轴当前缺的不是机制知识，是一把尺子。

`InteractionTrace` 只记录 `CommittedUsage.total_tokens` 一个总数，capability schema、
messages、typed inputs 各占多少无从得知。因此按 §1.1，下面两条候选**都不具备准入资格**——
不是因为机制不清楚，而是因为无法执行同输入 baseline 并断言失败根因。

本文因此分三段，只有第一段现在可以做：

| 阶段 | 内容 | 准入状态 |
| --- | --- | --- |
| P0 | 上下文构成度量 | **可立即实施**：纯观测，不改变生产行为，它生产 P1/P2 的 baseline 能力 |
| P1 | Observation 逐出与重读 | 未准入，等 P0 数据 + 目标 E2E |
| P2 | 两阶段 capability materialization | 未准入，等 P0 数据 + 规模场景 E2E |

P0 不需要 baseline 失败证据，因为它不新增产品行为，也不进入任何模型可见输入；它属于 §2.2 的
Observability 层，唯一职责是让 P1/P2 的 baseline 变得可执行。**这不是给 P1/P2 的免检通道**：
P0 完成后若数据显示 schema 占比与历史增长都不构成约束，正确结论是关闭 P1/P2，而不是继续。

## 2. 已落地前提

只列本文推理依赖的部分，完整状态见 canonical 文档。

| 前提 | 位置 | 本文如何依赖 |
| --- | --- | --- |
| 可见性先于检索 | `topics/context-engineering.md` | P2 的 Tier 1/Tier 2 都在 scope 过滤之后 |
| ArtifactRef 而非正文 | `ArtifactService` | P1 的逐出目标已经是 ref，不需要新存储 |
| capability revision | `_effective_capabilities` | P2 必须继续覆盖全集，见 §6 |
| sealed context | `sealed_context_projection_ref` | P1/P2 改变可见输入即改变 digest，可被 E2E 断言 |
| 单次 Observation 有界 + 卸载重读 | ADR 0013 | P1 复用其全部机制，不新增取回路径 |

ADR 0013 是本文的直接前身：它把「一次返回多大」变成生产事实，本文处理的是「**多次**返回累积
多大」和「**没被用到的定义**占多大」。三者是同一轴的三个不同问题，不能互相替代。

## 3. 已证明约束与未证明缺口

必须分开，否则整份设计会变成无证据优化。

**已证明（ADR 0013 实测）**：单次工具返回不受生产机制约束时，回合预算只是一个声明。一次
`github.get_file_contents` 返回 1,940,197 字符，该回合提交 776,720 tokens，是声明上限
`max_total_tokens=32,000` 的 24 倍。**这条已修复**，不是本文的缺口。

**未证明（本文的三个缺口）**：

| 编号 | 缺口 | 当前为何无法判定 |
| --- | --- | --- |
| G1 | 全量 public tool schema 每轮注入 | 未记录 schema 占提交 token 的比例 |
| G2 | `inputs` 跨轮单调增长，无逐出 | 未记录逐轮增长曲线，不知道 8 轮打满时的实际形态 |
| G3 | token 上限按回合起点判定 | 已知语义如此（ADR 0013 明确不改），但回合内峰值未被记录 |

G1/G2 都是**结构事实清楚、影响未被测量**。结构事实：`_effective_capabilities` 无条件遍历全部
`public_agent` tool 与全部 agent profile，结果由 `_system_prompt` 直接序列化进 system prompt；
主循环对 `inputs` 只 append/extend，从不裁剪。影响未测量：这正是 P0 要解决的。

G3 不是缺陷而是已接受的语义边界，本文不改它，只在 P0 中把回合内峰值记录下来，使「上限按起点
判定」这件事有数据可讨论，而不是每次都靠重读 ADR 0013 回忆。

## 4. Baseline 现状：为什么现在测不出来

按 §6 流程第 2 步，优化前必须执行同输入 baseline。对 G1/G2 这一步**当前无法完成**，原因不是
没有场景，而是没有观测：

- `InteractionTrace` 的字段是 revision、interaction_run_ref、capability_revision、messages、
  inputs、usage、execution_order、concurrent_batches、review_criteria、final_message、
  knowledge_save_operation。其中与体积相关的只有 `usage.total_tokens`，是一个标量总数；
- `StructuredModelResponse` 提供 input_tokens / output_tokens / total_tokens，**没有**任何
  cache 命中字段。因此「prompt cache 是否被破坏」这类判据当前也不可测（见 §7 被拒项）；
- trace 里虽然存了 messages 与 inputs 全文，可以事后算字符数，但那是离线重算，不是可断言的
  生产事实，也无法区分 system prompt 内部构成。

结论：G1/G2 的 baseline 缺的是**测量能力**，而缺失能力必须在同一设计中给出落地方案（§1.5）。
这就是 P0 的全部内容，也是本文唯一现在可实施的部分。

## 5. P0：上下文构成度量

### 5.1 事实与 owner

| 事实 | Owner | 写入口 | 生命周期 |
| --- | --- | --- | --- |
| 一轮模型调用的可见输入构成 | `ConversationService` | 组装 `visible_messages` 处，与调用同一位置 | 随 Interaction journal |
| 各段字符长度 | `observation_bounds.serialized_length` | 已存在，不新增度量函数 | 同上 |

度量必须在**已组装完成的 `visible_messages` 上**进行，不能另起一套估算：估算与真实输入不一致
时，数据会指向不存在的问题。这也是不引入 tokenizer 的原因——字符数由生产输入直接派生，
tokenizer 会引入 Provider 相关的第二套口径。

### 5.2 记录内容

每轮 model turn 追加一条 typed 记录，四个分段互不重叠且加总等于该轮可见输入：

```text
capability_projection_chars   capabilities.model_dump_json() 的长度
system_prompt_other_chars     system prompt 减去上面这段
conversation_messages_chars   committed messages
typed_inputs_chars            observation + feedback
```

外加两个标量：该轮 `input_tokens`（Provider 报告值，用于建立字符与 token 的换算比），以及
`turn_index`。逐轮记录而非只记回合汇总，是因为 G2 要的正是**增长曲线**，汇总值会把它抹平。

### 5.3 边界

- **不改变任何模型可见输入。** 记录发生在 `generate` 调用之后，不参与 `visible_messages` 组装，
  因此 `context_projection_ref` 的 digest 不变，既有 E2E 断言全部保持成立；
- **不新增持久化事实源。** 该记录属于 `InteractionTrace`，与 committed inputs 同生命周期，
  可由 inputs 确定性重算，不构成第二写入口；
- **不进入任何终止判据、预算判定或 Admission 分支。** 观测改变生产行为即违反 §2.2。

### 5.4 用户可见结果

无。P0 是唯一一项不声称用户结果改善的阶段——它的交付物是判据，不是能力。这一点必须写明，
否则它会被误当成「已优化 context engineering」。

### 5.5 验证

两条 Unit，各自守一个风险：

- `test_recorded_context_segments_account_for_the_input_that_was_sent`：逐轮断言四个分段加总
  等于该轮实际发出的 request 消息长度，防止分段口径漂移成第二套算法；同时断言
  `typed_inputs_chars` 从第一轮的 0 变为第二轮的正值，使 G2 的增长曲线本身可观测。
- `test_measuring_the_context_does_not_change_the_sealed_input`：用记录下来的 request 重算
  `sealed_context_projection_ref` 并与该轮实际使用的 ref 比对，同时断言可见消息仍是最小集
  （system + user）。**不是**「记录前 / 记录后」对照：生产路径中记录无条件发生，构造一个未记录
  的对照轮需要为测试新增一个关闭观测的开关，那本身就是为测试增加生产复杂度。重算 seal 证明的是
  同一件事——该轮发出的消息与它封印的消息完全一致，没有任何东西为了 trace 被追加进可见输入。

不新增 E2E：P0 没有用户可观察结果，为它写 E2E 属于用测试证明对象存在。

## 6. P1：Observation 逐出与重读（未准入）

### 6.1 机制来源

**A 级**：Claude Code Agent SDK 的 tool search 文档写明同一形状——"If the conversation is long
enough that the SDK compacts earlier messages to free space, previously discovered tools may be
removed, and the agent searches again as needed."
（<https://code.claude.com/docs/en/agent-sdk/tool-search>）。可复核的机制要点是：**已加载内容
可被逐出，且逐出的前提是重取路径存在**。

本工程采纳的正是这条不变量，而不是它的具体拓扑。重取路径已由 ADR 0013 建成：
`_fit_observation_payload` 卸载为 `ResourceRef`，`_read_action_output` 按 keyword/start_line
取窗口。P1 只是把「超限时被动界定」扩展为「按需主动逐出」。

### 6.2 设计

在组装 `visible_messages` 时，把较早的 **succeeded** observation 投影成 stub：保留 `action_id`、
`capability_id`、`status` 和 `resource_ref`，正文替换为可重读提示。四条约束：

1. **只改投影，不碰 journal。** journal 是 committed inputs 的 canonical owner，逐出是
   `inputs -> visible_messages` 的纯函数。恢复语义因此完全不变，这是本工程分层送的性质，
   不需要为 compaction 另设恢复规则；
2. **不逐出 `DecisionFeedback`。** 被拒原因是模型下一轮的修复依据，逐出它等于让模型重犯同一个
   错，并使 §3.1 的 typed feedback 失效；
3. **被逐出的 observation 必须已卸载。** 未卸载（即未超 20,000 字符）的 observation 若被逐出，
   其内容将无处可取——这正是 ADR 0013 拒绝的「截断但不给重读入口」。因此 P1 必须让卸载不再只由
   超限触发，而由「将被逐出」触发，二者是同一个 owner 的两个入口；
4. **`_unread_offloaded_resource` 保持生效。** 该判据已保证未读完不能以非 answer 收尾；逐出后
   它的意义更强，不需修改。

### 6.3 准入条件

P0 数据显示 `typed_inputs_chars` 随轮次增长并挤占后续轮次，**且**存在一条从正式入口执行的
baseline：用户目标需要多次读取，实际因早期 observation 占据上下文而失败或降质。

两条都不成立时关闭 P1。特别地，若 P0 显示多数回合在 2–3 轮内结束、`typed_inputs_chars` 从未
接近上限，则 G2 是想象中的问题，逐出机制不得实施。

### 6.4 目标 E2E 骨架

```text
Persona: 需要从同一大文件的多个远端位置取事实的用户，不知道任何内部能力名
Given:   一个需要多次定位、单次窗口无法覆盖的真实远端文件
When:    从 /api/conversation/turn 以自然表达提出该目标
Baseline:同输入执行并归档；失败根因必须是早期 observation 挤占，而非模型能力或 Provider 限额
Then:    逐字正确的多个事实同时出现在最终回答中
And not: 不得以 limitation 收尾；不得出现未读完即非 answer 收尾；提交 token 不超过声明上限
Path evidence: trace 断言逐出发生、重读发生、被逐出内容的 resource_ref 与重读的 resource_id 对应
```

`And not` 的第二条依赖既有 `_unread_offloaded_resource`，属于回归而非新断言。

## 7. P2：两阶段 capability materialization（未准入）

### 7.1 机制来源与可复核坐标

| 事实 | 数值 | 等级与坐标 |
| --- | --- | --- |
| 典型多 MCP（GitHub/Slack/Sentry/Grafana/Splunk）definition 开销 | ~55k tokens | A，platform.claude.com `/docs/en/agents-and-tools/tool-use/tool-search-tool` |
| 削减幅度与实际加载量 | >85%，加载 3–5 个 | A，同上 |
| MCP eval 准确率 | Opus 4 49%→74%；Opus 4.5 79.5%→88.1% | B，anthropic.com `/engineering/advanced-tool-use`（官方博客，与上条 A 级交叉） |
| 选择准确率退化规模 | 30–50 个 tool 同时加载 | A，code.claude.com `/docs/en/agent-sdk/tool-search` |
| 自动启用阈值 | definition 超过 context window 10%（`auto:N` 可调） | A，同上 |
| 判定不值得做的条件 | tool < 10 个，或 definition 总量很小 | A，tool-search-tool 同页 |

最后一行与前几行同等重要：官方同时给出了**反向判据**。本工程内置 `public_agent` tool 约 12 个，
接入 GitHub（~30）与 Notion（~15）后才越过 30–50 区间。所以 P2 的准入门大概率落在
「MCP 全开的 capability profile」，而非 baseline profile——这个结论本身应由 P0 数据确认。

### 7.2 采纳与不采纳

**采纳**：两层加载这一机制本身，以及「少数高频能力恒在、其余按需」这一参数选择。

**不采纳**：Anthropic API 的具体形状（`defer_loading` 字段、`tool_reference` block、
服务端 `tool_search_tool_*`）。本工程走自建 object-root envelope 且面向 OpenAI-compatible
endpoint，没有服务端展开机制；照搬字段名只会产生一个不存在的协议依赖。

**有条件借用**：该文档记录的一条实现细节值得对照——deferred tool 被排除在 system-prompt
**prefix** 之外，发现后内联展开在对话体中，因此 prompt cache 前缀不失效。本工程当前把
capabilities JSON 拼在 system prompt 尾部、其后紧跟每轮变化的 remaining budget，前缀复用性
必然很差。但**这条不作为 P2 的收益**：`StructuredModelResponse` 没有 cache 命中字段，
当前部署是否启用上下文缓存也无证据，因此「调整拼接顺序能省钱」目前是推断而非事实。它列为
§8 的一条独立候选，准入前提是先让 cache 命中可观测。

### 7.3 设计

```text
Tier 1 恒在：name + 一行 description + read_only          全部可见 tool
Tier 2 按需：input_schema                                 模型点名后才注入
```

三条约束：

1. **`capability_revision` 必须继续覆盖全集**，不是本轮 materialized 子集。「本轮模型看到了哪组
   定义」是这一轴当前唯一的可证明性优势，不能拿它换 token；若 revision 只覆盖子集，同一
   Interaction 的两轮会得到不同 revision，故障归因随即失效；
2. **Tier 1 summary、Tier 2 schema、availability observation 必须从同一 registry 投影派生**
   （§4 原文约束），不得成为三个可写事实源；
3. **Tier 2 注入是 Admission 前的上下文装配，不是一次 ToolCall。** 它不产生 Observation、
   不计入 `tool_calls` 预算、不形成执行事实。把能力发现做成工具调用会让「模型看到定义」被
   记成一次执行，污染 §3.2 的三分边界。

### 7.4 准入条件

两条同时成立：P0 数据显示 `capability_projection_chars` 换算后超过 context window 10%
（对齐官方阈值）；且存在一条正式入口 baseline，在当前规模下证明误选能力或延迟造成用户结果失败。

按 §7.1 的反向判据，**当前很可能不该做**。这个判断必须由数据关闭，而不是由本文关闭。

### 7.5 目标 E2E 骨架

```text
Persona: 在 MCP 全开 profile 下提出需要一个特定远端能力的用户，不知道任何 tool 名
Given:   完整 MCP capability profile（GitHub + Notion），目标只需其中一个能力
When:    从正式入口以自然表达提出该目标
Baseline:同输入执行并归档；失败必须是误选能力或延迟越界，而非 Provider 限额（限额属环境失败）
Then:    正确能力被选择，用户结果正确
And not: 不得选择相近但错误的能力；不得因上下文规模退化为 limitation
Path evidence: trace 断言 Tier 2 只注入被点名的 schema，且 capability_revision 仍覆盖全集
```

## 8. 被拒与暂缓

| 方案 | 处置 | 理由 |
| --- | --- | --- |
| 模型摘要式 compaction | 拒绝 | 摘要是模型输出回灌为输入，正是长期知识轴要防的污染闭环。要做必须把摘要作为 typed input 提交并带 provenance，否则 replay 不确定。P1 的逐出+重读不产生新事实，严格优于它 |
| 通用 memory tool / note-taking | 拒绝 | 单回合上限 8 轮；跨会话记忆已由 Workspace Claim 拥有。新增等于造第二个记忆 owner |
| embedding 语义能力检索 | 拒绝 | 官方在 ~50 tool 规模用 regex/BM25 即可。上 embedding 是给未被证明的问题加索引依赖 |
| 调高 `max_total_tokens` | 拒绝 | ADR 0013 已拒：改成能容纳 776,720 等于取消上限 |
| sub-agent 卸载上下文 | 已存在 | `AgentGateway` 已让 child 消耗自身上下文、只回 Artifact ref 与 excerpt |
| 调整 system prompt 拼接顺序以保护 prompt cache | 暂缓 | 它改变模型可见输入，属产品行为变更，需 §1.1 证据；而当前 cache 命中不可观测（见 §7.2）。前置条件：先让 cache 指标进入 trace |

## 9. 影响边界与复杂度预算

P0：`ConversationService` 组装处 + `InteractionTrace` 新增 typed 记录 + 复用
`serialized_length`。不新增模块，不新增 Port，依赖方向不变，Domain 未触及。

P1：复用 ADR 0013 的 `observation_bounds` 与 `_read_action_output`，新增一个投影函数与一处
卸载触发条件。**净新增小于它移除的上下文体积**，且不新增持久化事实。

P2：新增一层 capability 投影与一处 Tier 2 装配。这是三者中唯一新增架构机制的一项，因此必须
单独提交 `Complexity Justification` 与 ADR；本文不代替那份 ADR。

无删除项：P0/P1 的路径此前不存在，如实记录，不虚报净复杂度下降。

## 10. 退出条件

- P0 完成后数据显示 G1、G2 都不构成约束 → 关闭 P1/P2，本文降为一条结论记录；
- P1 或 P2 的 baseline 未失败、或失败根因为环境/测试/Provider 限额 → 停止该项；
- 任一项落地后，当前事实迁入 summary 与 `topics/context-engineering.md`，并从本文删除对应
  章节；本文清空后整体删除。

同时更新 [能力轴](../interview/03-capability-axes.md) 第 3 轴：该节目前只列「全量 schema 注入」
与「无 compaction」两条边界，未包含 ADR 0013 已落地的单次 Observation 界定与 E21 证据，
已落后于代码。修正方向是把边界写成三档——单次体积已有机制与证据、跨轮逐出未证明需要、
capability discovery 无 baseline 故不准入。
