# Context 物化的度量、逐出与两阶段能力加载

本文是 [可信 Agent Runtime 演进与收敛](trusted-agent-runtime-evolution.md) 第 7 节中
「两阶段 capability discovery」与「Context compaction」两行候选的详细设计，不是第二个 owner：
准入与退出仍由那份路线图判定，本文只补齐这两条候选各自的机制、边界和缺失的准入前提。

Context 四阶段协议、持久化规则和腐化防护的 canonical 文档是
[Context 工程](../topics/context-engineering.md)；单次 Observation 的界定与卸载重读已落地，
见 [ADR 0013](../adr/0013-bounded-observation-and-offloaded-read.md)。本文不复制这两处事实。

## 1. 结论先行

**两条候选都不做，但理由不同：一条被数据关闭，另一条只是被门禁挡住——能判定它的那次运行至今
没跑过。**

P0 度量已落地（`TurnContextComposition`），22 条真实 turn 记录显示：capability 投影占该轮可见
输入 39.5%–78.4%，绝对量 2,917–4,970 tokens；回合峰值 `input_tokens` 11,339，是本工程回合上限
`max_total_tokens=32,000` 的 35.4%；最大 `turn_index` 为 1，即全部 2 轮收敛，上限是 8 轮。

| 阶段 | 内容 | 当前状态 |
| --- | --- | --- |
| P0 | 上下文构成度量 | **已落地**，数据见 §5.6 |
| P1 | Observation 逐出与重读 | **未准入：§1.1 门禁生效，决定性测量未执行**（§6.3）。22 条全部 2 轮收敛，没有一条在测跨轮累积 |
| P2 | 两阶段 capability materialization | **已测量 → 不准入**：命中官方反向判据，且缺 baseline 失败证据（§7.4） |

**两项的证据资格必须分开读。**P2 的数据有代表性——全量 schema 每轮无条件注入，任何一次运行都在
测它。P1 的数据没有代表性：只有多轮且每轮带大 observation 的运行才在测它，而 22 条全是 2 轮收敛，
**等于这把尺子从未量到它要量的东西**。所以 P1 当前靠的是 §1.1 的硬门（没有已执行的 baseline 失败
就不准入），不是一组显示它不必要的数据。复核路径见 §6.3：重跑 E21，不设计新用例。

**P2 一节另外如实记录了一处对本文不利的读数**：若拿 `max_total_tokens` 当官方 10% 阈值的分母，
20/22 条会越线；那条比值之所以不能用，是因为分母该是 Provider context window，而本工程的 trace
里没有这个字段——所以判定改由不依赖该分母的两条判据作出。

P0 当初不需要 baseline 失败证据，因为它不新增产品行为、不进入任何模型可见输入，属于 §2.2 的
Observability 层；它唯一的职责就是让这两条候选可被判定——**现在它给出的判定是「不要做」，这正是
它的正确用法，而不是失败**。

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

**三个缺口的当前读数**（数值见 §5.6）。G1、G3 的数据有代表性；**G2 的没有**——只有多轮且每轮带
较大 observation 的运行才在测它，22 条全是 2 轮收敛：

| 编号 | 缺口 | 结构事实 | 测得结论 |
| --- | --- | --- | --- |
| G1 | 全量 public tool schema 每轮注入 | `_effective_capabilities` 无条件遍历全部 `public_agent` tool 与 agent profile，由 `_system_prompt` 直接序列化 | **占比高、绝对量小**：39.5%–78.4% 的可见输入，但只有 2,917–4,970 tokens |
| G2 | `inputs` 跨轮单调增长，无逐出 | 主循环对 `inputs` 只 append/extend，从不裁剪 | **未被证明构成约束**：最大 `turn_index`=1，`typed_inputs_chars` 峰值 18,939；但 22 条全是 2 轮收敛，**没有一条在测跨轮累积**（§6.3） |
| G3 | token 上限按回合起点判定 | 已知语义如此，ADR 0013 明确不改 | 回合内峰值 `input_tokens`=11,339，为上限的 35.4%，**未逼近** |

G3 不是缺陷而是已接受的语义边界，本文不改它，只把回合内峰值记录下来，使「上限按起点判定」
这件事有数据可讨论，而不是每次都靠重读 ADR 0013 回忆。

## 4. 缺失的测量能力已补齐

按 §6 流程第 2 步，优化前必须执行同输入 baseline。G1/G2 的 baseline 曾**无法执行**，缺的不是
场景而是观测——`InteractionTrace` 中与体积相关的只有 `usage.total_tokens` 这一个标量，无法区分
system prompt 内部构成；trace 虽存了 messages 与 inputs 全文可事后算字符，但那是离线重算，不是
可断言的生产事实。

缺失能力必须在同一设计中给出落地方案（§1.5），这就是 P0 的全部内容，现已落地。

**仍未补齐的一项**：`StructuredModelResponse` 提供 input_tokens / output_tokens / total_tokens，
**没有**任何 cache 命中字段。所以「prompt cache 是否被破坏」至今不可测，相关候选仍卡在这里
（见 §7.2 与 §8）。

## 5. P0：上下文构成度量（已落地）

### 5.1 事实与 owner

| 事实 | Owner | 写入口 | 生命周期 |
| --- | --- | --- | --- |
| 一轮模型调用的可见输入构成 | `TurnContextComposition`（[models.py:292](../../src/personal_agent/application/conversation/models.py#L292)） | `ConversationService._decide`，`generate` 返回处（[service.py:1056](../../src/personal_agent/application/conversation/service.py#L1056)） | 随 `InteractionTrace.context_composition` |
| 各段字符长度 | 发出的字符串本身 | 由 `len()` 直接派生，其中 `system_prompt_other_chars` 用减法保证两段互不重叠 | 同上 |

度量在**已组装完成、且已经发出的那批消息上**进行，不另起一套估算：估算与真实输入不一致时，
数据会指向不存在的问题。这也是不引入 tokenizer 的原因——字符数由生产输入直接派生，tokenizer
会引入 Provider 相关的第二套口径。

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

两条均在 [test_conversation_interaction.py:236](../../tests/test_conversation_interaction.py#L236)
与 [:276](../../tests/test_conversation_interaction.py#L276)。

不新增 E2E：P0 没有用户可观察结果，为它写 E2E 属于用测试证明对象存在。

### 5.6 测得数据

**数据集**：2026-08-03 的 16 个 archive 中有 12 个带 `context_composition`，共 **22 条 turn 记录**，
全部来自 commit `0f692ad`、dirty worktree。用例为 E22（governed delete）、E23（durable handoff）、
E24（research boundary paired）、L01（natural recall）。按 [00-writing-spec](../interview/00-writing-spec.md)
是 **C 级观测数据，不构成发布资格**。

| 测得量 | 数值 |
| --- | --- |
| capability 投影占该轮可见输入 | **39.5%–78.4%**；turn 0 的 14 条集中在 69.7%–78.4% |
| capability 投影绝对体积 | baseline profile 9,442–11,779 字符；`+web_search` 15,111–17,448 字符 |
| 实测字符/token 比 | 3.23–3.51（均值 3.39），逐条换算后投影 **2,917–4,970 tokens** |
| 回合峰值 `input_tokens` | **11,339**，为 `max_total_tokens=32,000` 的 **35.4%** |
| 最大 `turn_index` | **1**（即全部 2 轮收敛），上限是 `max_model_turns=8` |
| 最大 `typed_inputs_chars` | **18,939**（单条，E24 turn 1） |

分用例看，占比的分母差异比分子大得多：

| 用例 | profile | n | capability 字符 | 占比 | 峰值 `input_tokens` | 峰值 `typed_inputs_chars` |
| --- | --- | --- | --- | --- | --- | --- |
| E22 | baseline | 7 | 9,442–11,779 | 68.3%–70.2% | 5,107 | 480 |
| E23 | +web_search | 6 | 15,111–17,448 | 76.7%–78.4% | 6,414 | 409 |
| E24 | +web_search | 2 | 15,111 | 39.5%–78.4% | 11,339 | 18,939 |
| L01 | baseline | 7 | 9,442–11,779 | 64.5%–70.2% | 5,522 | 1,491 |

投影绝对量按 profile 分成两档：baseline **2,917–3,561 tokens**，`+web_search`
**4,444–4,970 tokens**。

**唯一一条占比降到 39.5% 的记录（E24 turn 1）正是唯一一条 observation 体量可观的记录。**
这说明 70%+ 的正确读法是「其他段太小」，不是「投影太大」——判据必须用绝对量对齐 context
window，而不是用段间比值。这也是官方阈值写成「超过 context window 10%」而不是「超过 prompt
的百分之多少」的原因。

**必须主动说的一条边界：这 22 条不含多次重读形态，而那正是 G2 唯一会显形的形态。**
`TurnContextComposition` 于 2026-08-03 前后落地；E21 的 archive 是 20260731，早于该字段，
那几次 3–4 轮、35,947 tokens 的运行因此没有分段记录。**缺失不是随机的**——它与用例年龄相关，
用例年龄又与场景形态相关，于是数据集系统性地排除了唯一相关形态。所以 §6.3 只能得出「未被证明
需要」，不能得出「不需要」，更不能外推成「任何形态都不会挤占」。复核动作是重跑 E21，见 §6.3。

## 6. P1：Observation 逐出与重读（未准入，决定性测量待执行）

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

### 6.3 准入条件与判定结果

**判定：未准入，依据是 §1.1 的门禁而不是一组显示它不必要的数据。** 准入条件本应是：P0 数据显示
`typed_inputs_chars` 随轮次增长并挤占后续轮次，**且**存在一条从正式入口执行的 baseline，用户目标
需要多次读取而实际因早期 observation 占据上下文失败或降质。第二条是硬门，当前不成立。

本节原文另写了一条关闭条件：「若 P0 显示多数回合在 2–3 轮内结束、`typed_inputs_chars` 从未接近
上限，则 G2 是想象中的问题，逐出机制不得实施」。22 条记录字面上全部命中，但**第三行必须把两件事
分开读**：

| 关闭条件 | 测得 | 命中 | 证明力 |
| --- | --- | --- | --- |
| 多数回合在 2–3 轮内结束 | 最大 `turn_index`=1，即 **全部** 2 轮收敛（上限 8） | 是 | 仅覆盖这 22 次运行的形态 |
| `typed_inputs_chars` 从未接近上限 | 峰值 18,939 字符 ≈ 5.6k tokens；回合峰值 11,339 tokens 为上限的 35.4% | 是 | 同上 |
| 存在一条正式入口 baseline，失败根因是早期 observation 挤占 | 无 | 是 | **「没有一条失败」不等于「有一条在测它」——22 条里两者都不成立** |

**这组数据不足以支撑「不需要」，只足以支撑「未被证明需要」。**只有多轮、且每轮带较大 observation
的运行才会触发跨轮累积；22 条全是 2 轮收敛，且来自 E22/E23/E24/L01——这四个用例要证明的事情都与
跨轮累积无关，它们是顺手攒下的遥测，不是针对 G2 执行的 baseline。按 §5.6 的边界，唯一相关的形态
（多次重读）恰好被排除在数据集之外。

**复核的最便宜动作是重跑 E21，不是设计新用例。**
[test_release_user_outcomes.py](../../evals/e2e_quality/test_release_user_outcomes.py) 的
`test_e21_http_process_answers_from_oversized_read_within_budget` 已经是这个形态——真实用户目标、
自然表达、目标事实位于 ~916 KB 文件的 96% 处，单窗口取不到，实测 3–4 轮。它落在数据集外的原因
只有时间差：archive 为 20260731，早于 `TurnContextComposition` 落地；而当前代码无条件记录分段，
所以今天重跑即可得到一条多次重读形态的分段记录。**禁止为让跨轮累积显形而构造新场景**（例如「一次
问 8 个大文件」）：那是反向设计 baseline，判据是用户目标是否真实，不是数据量是否够大。

重跑的三种结果都推进判定，其中两种加固当前结论：

| 分段记录显示 | 对本项的影响 |
| --- | --- |
| 后轮被早期 observation 挤占，**且运行失败或降质** | G2 准入，§6.4 骨架即起点 |
| 累积可观但运行成功 | 仍不准入，但理由从「未测到」升级为「已测到且不失败」——**更强的关闭** |
| 累积其实不大 | 说明 ADR 0013 的卸载已顺手解决 G2，关闭理由最硬 |

E21 在 catalog 中属 `CAPABILITY_PROFILE`，是 diagnostic，不单独产生发布声明；重跑给出的是判定
P1 开关的观测数据，不是发布资格。

下面 §6.4 的 E2E 骨架保留，作为准入条件成立时的现成起点，不作为待办。

### 6.4 目标 E2E 骨架（未准入状态下的备用起点）

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

最后一行与前几行同等重要：官方同时给出了**反向判据**。本工程 baseline profile 是 5 个 Service
内能力（[service.py:91](../../src/personal_agent/application/conversation/service.py#L91)）加注册
的 `public_agent` tool；接入 GitHub（~30）与 Notion（~15）后才越过 30–50 区间。所以 P2 的准入门
若存在，只会落在「MCP 全开的 capability profile」，而非 baseline profile——**P0 数据现已确认这一
判断，结论是当前不做，见 §7.4**。

### 7.2 采纳与不采纳

**采纳**：两层加载这一机制本身，以及「少数高频能力恒在、其余按需」这一参数选择。

**不采纳**：Anthropic API 的具体形状（`defer_loading` 字段、`tool_reference` block、
服务端 `tool_search_tool_*`）。本工程走自建 object-root envelope 且面向 OpenAI-compatible
endpoint，没有服务端展开机制；照搬字段名只会产生一个不存在的协议依赖。

**有条件借用**：该文档记录的一条实现细节值得对照——deferred tool 被排除在 system-prompt
**prefix** 之外，发现后内联展开在对话体中，因此 prompt cache 前缀不失效。本工程当前把
capabilities JSON 拼在 system prompt 尾部，其后紧跟每轮变化的 remaining budget
（[service.py:1732](../../src/personal_agent/application/conversation/service.py#L1732)）。

但**这条不作为 P2 的收益，而且不能顺势断言前缀复用性很差**：变动部分只是尾部约百余字符的
budget JSON，前缀本身逐轮稳定；真正的事实是 **cache 命中当前不可观测**——
`StructuredModelResponse` 只有 input/output/total tokens，没有任何 cache 字段，当前部署是否启用
上下文缓存也无证据。所以「调整拼接顺序能省钱」是 **D 级推断**，不是事实。它列为 §8 的一条独立
候选，准入前提是先让 cache 指标进入 trace。

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

### 7.4 准入条件与判定结果

**判定：不准入，判据是官方反向判据而不是占比。**

先说清一件容易被自己糊弄过去的事：**官方 10% 阈值的分母是 Provider context window，而本工程的
trace 里没有这个字段。** `STRUCTURED_MODEL` 当前是 `deepseek-v4-flash`，其窗口大小不在本仓任何
可复核坐标内，因此这条比值**当前无法权威计算**，不能拿它当结论。

若换成手头唯一的硬上限 `max_total_tokens=32,000` 作分母，结果反而对本节不利——逐条换算后投影是
**2,917–4,970 tokens**，其中 20/22 条超过 3,200（baseline profile 14 条中 12 条，`+web_search`
8 条全部）。**如实记录：用这个分母，第一条准入条件反而成立。** 它不成立只是因为分母用错了：
32,000 是本工程的回合预算，不是模型的 context window，官方阈值问的是「definition 是否吃掉了窗口
的一成」，不是「是否吃掉了自设预算的一成」。

所以判定只能落在另外两条上，它们都不依赖那个缺失的分母：

| 判据 | 测得 | 结论 |
| --- | --- | --- |
| 官方反向判据：tool < 10 个，或 definition 总量很小 | baseline profile 为 5 个 Service 内能力加注册 `public_agent` tool，definition 约 2.9k–3.6k tokens | **命中反向判据，不值得做** |
| 存在正式入口 baseline，证明当前规模下误选能力或延迟造成用户结果失败 | 无。22 条记录中没有一条误选或因规模超时 | **不成立** |

第二条是硬门：按 §1.1，没有已执行的 baseline 失败，P2 无论占比多少都不得准入。

**这个判断由数据和缺失的 baseline 关闭，不是由本文的偏好关闭。** 重新开启有两条独立路径：让
context window 进入 trace 从而使 10% 阈值可权威计算；或按 §7.1 的形态在 MCP 全开 profile 下取得
一条可重复的误选/延迟越界 baseline（失败根因不得是 Provider 限额，那属环境失败）。

### 7.5 目标 E2E 骨架（不准入状态下的备用起点）

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
| 通用 memory tool / note-taking | 拒绝 | 单回合上限 8 轮；跨会话记忆已由 Personal Knowledge Claim 拥有。新增等于造第二个记忆 owner |
| embedding 语义能力检索 | 拒绝 | 官方在 ~50 tool 规模用 regex/BM25 即可。上 embedding 是给未被证明的问题加索引依赖 |
| 调高 `max_total_tokens` | 拒绝 | ADR 0013 已拒：改成能容纳 776,720 等于取消上限 |
| sub-agent 卸载上下文 | 已存在 | `AgentGateway` 已让 child 消耗自身上下文、只回 Artifact ref 与 excerpt |
| 调整 system prompt 拼接顺序以保护 prompt cache | 暂缓 | 它改变模型可见输入，属产品行为变更，需 §1.1 证据；而当前 cache 命中不可观测（见 §7.2）。前置条件：先让 cache 指标进入 trace |

## 9. 影响边界与复杂度预算

P0（**已落地**）：`ConversationService._decide` 记录处 + `InteractionTrace` 新增一条 typed 记录。
不新增模块、不新增 Port，依赖方向不变，Domain 未触及；无删除项，如实记录，不虚报净复杂度下降。

P1、P2 均未准入，下列预算仅在准入条件成立时有效：

- P1：复用 ADR 0013 的 `observation_bounds` 与 `_read_action_output`，新增一个投影函数与一处卸载
  触发条件，不新增持久化事实；
- P2：新增一层 capability 投影与一处 Tier 2 装配。这是三者中唯一新增架构机制的一项，必须单独提交
  `Complexity Justification` 与 ADR；本文不代替那份 ADR。

## 10. 当前状态与本文去向

**本文已从「待实施设计」降为一条结论记录，但留着一件未做完的事**：P0 的职责是让 P1/P2 可判定，
P2 已判定完毕；P1 的决定性测量（多次重读形态的分段记录）**从未执行**，当前挡住它的是 §1.1 门禁而
非数据。这是 P0 → P1 交接漏掉的一步，不是已完成项。

| 事项 | 状态 |
| --- | --- |
| P0 落地事实迁入 canonical 文档 | 已完成：`topics/context-engineering.md`「上下文构成度量」持有机制与边界，本文持有测得数据 |
| 能力轴第 3 轴按四档重写 | 已完成：单次体积有机制与证据、跨轮逐出未被证明需要、两阶段发现不准入、资源 visibility 部分成立 |
| P2 准入判定 | 已完成，见 §7.4（数据有代表性） |
| P1 准入判定 | **未完成**：§6.3 记录了当前不准入的依据，但决定性测量待重跑 E21 取得 |
| 准入与退出的最终 owner | 仍是 [可信 Agent Runtime 演进](trusted-agent-runtime-evolution.md) §7；本文不重复裁决表 |

**引用观测数据时必须同时记录该字段的落地日期与数据集缺失的形态。**G2 这次的教训不是用例设计不足
——覆盖该形态的 E21 一直存在——而是新增观测字段会产生一条静默分界线：字段落地前的 archive 看似
随机缺数据，实际缺失与用例年龄相关，用例年龄又与场景形态相关，于是数据集**系统性地**排除了唯一
相关形态，且偏向对结论有利的一侧。§5.6 已按此要求写明落地时间差与缺失形态。

仍然有效的退出条件：

- P1 或 P2 准入条件成立后执行 baseline，若未失败、或失败根因为环境/测试/Provider 限额 → 再次停止该项；
- 两条候选都长期无重开信号时，把 §6/§7 压缩为 `trusted-agent-runtime-evolution.md` §7 里的一行
  否决理由，本文整体删除。

**保留 §6/§7 的理由只有一条**：关闭条件、可复核的官方坐标和已判定的数据都在这里，删掉就只剩一句
「当时觉得不必要」。等它们不再被追问时再删。
