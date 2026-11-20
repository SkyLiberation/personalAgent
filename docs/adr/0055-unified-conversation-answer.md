# ADR 0055 统一 Conversation 答复提交

状态为采用，2026-11-15。2026-11-18 更新主循环的普通答复、状态报告和工具选择契约。

## 问题与依据

`canvas-list-test` 的真实复跑在成功读网页后开放 claim 选证工具，并从普通提交的枚举移除 `answer`。用户要求交付两份 CSV，网页工具的回执把答复变成了需要先选证和建立论断的流程。`find-alita-paper` 已下载评分接受的 PDF，随后两次选证参数被拒，未交付答复。LongDS Netflix Task 2 前两轮直接输出正文，引用列表为空，两次都通过独立的回答核验。用户决定移除 Conversation claim 模块并重跑 Toolathlon。[Canvas 实发请求](../../.tmp/ta-py2-1115/canvas-list-test/personal/product-data/interaction_runs/irun_f8bec9ac90cd44a1/7c10d7a574f2485f9f10a7d0244ef7ef/request.json) · [PDF 轨迹说明](../problems/toolathlon/research-loop-problems.md#goal计划和证据动作) · [LongDS 运行配置](../../.tmp/one-loop-ld/configuration.json)

## 需求和实现规格

| 需求 | 行为 |
| --- | --- |
| ANSWER-1 | Conversation 以完整 Markdown 正文交付普通答复，或单独调用 `control_report_turn_status` 报告明确的限制或失败，两者进入同一 `FinalMessage` 流程。在用户目标和计划允许交付时，读取网页不会移除普通答复入口。已发送的候选稿、模型反馈和最终正文仍由 Journal 记录。 |
| ANSWER-2 | 中英文主请求以当前 Goal 和 Step Context 表达可用阶段。状态工具仅接收 `message` 和 `disposition`，后者仅允许 `limitation`、`failed`。正文使用真实来源链接。阅读工具继续返回原文、来源与续读位置，答复核验从授权回执和工作区事实取得证据。 |
| ANSWER-3 | 删除 Conversation claim 的选证、建稿、修订、核验、恢复、Schema、Prompt 和 writer 配置，包括正式评测入口的消费者。独立的研究实验交付检查、订阅研究和知识库论断继续使用其各自契约。 |
| ANSWER-4 | Journal 为新运行绑定 `answer_protocol_version=markdown-status-v1`。升级后，同一数据目录下仍能开启新会话。Journal 按所有者和会话定位快照，再读取适用的业务 Schema。旧会话按原版本归档，续跑请求得到明确的版本不兼容结果。 |
| EVAL-1 | LongDS、Toolathlon 和后续新增的 Conversation 结果采集评测共用 `evals/conversation_http.py` 启动正式 Web 应用、检查就绪并提交 Conversation HTTP 请求。各数据集只拥有材料准备、运行调度、归档和上游评分适配。 |
| EVAL-2 | 本轮两套评测均使用 `goal_verification=false`、`answer_verification=false`。归档记录两项开关及 `unverified_flow_capture`，独立评分按各数据集的契约记录。生产核验按部署配置装配，默认开启。 |

Conversation 负责接收答复、评估当前 Goal 和接续已有交付链。MiniMax 主循环每个阶段都提交已声明的工具并省略 `tool_choice`。只有目标就绪后才能交付普通答案，业务工具由既有准入约束。目标更新、目标读取、澄清与状态报告各自独占一次模型决策。混批在解码前期拒绝，反馈配对原调用并给出可独立提交的动作。独立核验继续使用各自的输出契约。机制证据与验收见 [Loop Spec §17.7](../optimization/to_verify/conversation-loop-schema.md#177-普通正文与按用途装配的终答)。

### 澄清由独立工具提交

LongDS Task 3 第 16 轮的目标补丁因修改未核验的约束被拒绝。下一次实发请求同时声明了独立澄清工具，在 `submit_goal_patch` 的 Schema 和修复反馈里也提供了 `clarifications`。模型通过补丁发出确认问题，评测以 `clarification_required` 停止。[实发请求](../../.tmp/nyc23-pressure-20261120/t3/capture/sdk/5b776db57fbe491da13349a824511231.http.request.json) · [决策轨迹](../../.tmp/nyc23-pressure-20261120/t3/capture/turn-16.trace.json)

DeepSeek Harness `2e39e704` 的交互配置通过插件注册 `ask_user_question`。SDK 宿主声明能接收问题后，服务按会话和问题 ID 转发，用户答复作为工具结果返回。LongDS 的无人值守配置省略提问插件。采用独立提问与按交互能力装配的分工。本工程使用已有 `control_request_clarification` 及同会话回复入口，足以承载当前单个问题；接续仍以客户端提交下一轮用户原话为准。[工具定义](https://github.com/deepseek-ai/deepseek-harness/blob/2e39e70496aa02986ca6a820c5d497e816b69d7e/packages/interaction/tool-ask-user/src/index.ts#L28-L112) · [SDK 转发](https://github.com/deepseek-ai/deepseek-harness/blob/2e39e70496aa02986ca6a820c5d497e816b69d7e/packages/sdk/server/src/user-questions.ts#L11-L51) · [LongDS 配置](../../.tmp/nyc23-20261119/t3/harness/cordis.json)

- **ANSWER-5**。从模型可见的目标补丁 Schema、双语说明和 Runtime 处理移除提问字段。真实缺口由独立工具提出，Runtime 保存问题，既有 `resolve_clarification` 仍绑定后续用户原话。已接纳补丁的历史序列化保留恒为空的字段，确保 Journal 及历史快照摘要一致。
- **EVAL-3**。LongDS 两个正式入口共用无人值守答复配置。目标待维护与执行阶段都按已有机制撤下提问工具，未声明的调用在解码边界拒绝。目标补丁拒绝反馈保留原调用身份，明确需保留受保护条目并按用户原话修正其余变更。确实无法执行时使用已有状态工具。两类核验策略按既定评测配置工作。
- **定向验收**。用第 16 轮真实请求、实发动作和拒绝反馈回放。校验中英文及互动、无人值守两种声明。原补丁的约束修改仍被拒，旧字段不得解码成提问。独立提问在互动配置可提交，测试配置拒绝；核对旧 Journal 原件、源摘要和新绑定配置。实发验证使用同一轮的真实阶段输入，至多两次主请求、100 万 tokens，接续实际修订结果。整题得分和用时另行验证。

2026-11-20 定向验收通过。四种请求投影均拒绝旧补丁字段，独立提问只在互动模式通过解码。前 15 轮归档的目标操作重新序列化后与原件一致。第 16 轮实发一次英文原始阶段输入，消耗 209,586 输入及 970 输出 tokens。模型提交的补丁新增三条本轮要求，Runtime 接纳并保留原任务约束 `i30`。本次验证止于目标更新，未计算第 16 轮答案或整题得分。[离线判据结果](../../.tmp/nyc-clarification-20261120/offline-report.json) · [实发模型结果](../../.tmp/nyc-clarification-20261120/live-sdk/4ac8e5be96294988beccecc1aa46f0f2.candidate.response.json) · [准入结果](../../.tmp/nyc-clarification-20261120/live-report.json)

## 验收

- **协议与上下文。** 先以已有 Canvas 和 GDP 实发请求固定旧行为。检查新请求继续提供正常答复，网页成功后也不声明旧选证工具与提示。新一轮协议采用 LongDS 第 8 轮原始混批和中英文投影，核对错误回执、合法状态参数、正文原样及来源证据。执行源码导入、依赖和 Prompt 注册检查。
- **持久边界。** 使用封存的旧 Canvas 快照做只读回放，验证同目录可选择新会话，且读取旧会话时给出冲突。两边均不改写旧快照。
- **定向复跑。** 复用 `canvas-list-test` 与 `gdp-cr5-analysis` 的原题、环境与官方评分。分别记录正式答复、用户产物、评分和用量。Canvas 还核对网页读取后允许直接答复。未到达的阶段和失败保留原结果。
- **共享入口。** 核对两个数据集都经共用启动器启动正式 Web 应用，提交 Turn 并归档实际两项核验开关。现行路径为 `/api/conversation/turns`。原定向验证用原题和封存材料，记录实际候选、答复、用量及开关；关闭语义核验的采集标记为 `unverified_flow_capture`。[共用运行说明](../evals/04-running-and-release.md#conversation-评测共用入口)
- **批次复跑。** 按[上次清单](../../.tmp/tac1114/inventory.json)的 96 题重跑 personalAgent，沿用[上次归档身份](../../.tmp/tac1114/runs/identity.json)中的 MiniMax-M3.1-Flash、上游版本、官方评分器、64 轮、128 次工具调用、800 万 token 及 1,200 秒等待。定向实发请求确认新协议后，可并行调度独立环境。共享服务等定向运行结束后再串行调度。只纳入同源码和配置身份的结果。历史官方结果提供参照，Canvas 的官方参照使用已完成的评测材料隔离复跑。Google Cloud 和 Snowflake 的 12 题保持暂缓。分别报告有效评分、答复、用量和环境失败。批次证据只覆盖本次配置。

### Toolathlon 答复引用

以下记录为 Toolathlon 历史实验。通用答复协议已采用正文链接，并移除当时用于单独关闭答复行坐标的开关。

`identify-all-songs` 最新归档已写出并回读通过评分的歌曲清单，但第 26 轮答复把已返回的部分行写成整行引用 `d16:3`。答复校验生成拒绝反馈时查找未注册的提示，接口返回 500。该题评分消费歌曲文件。答复仍可在 Markdown 正文中说明来源。[运行记录](../../.tmp/ta-rerun-1117/window-20261117-014857-963603/identify-all-songs/personal/report.json) · [最后的模型请求](../../.tmp/ta-rerun-1117/window-20261117-014857-963603/identify-all-songs/personal/product-data/interaction_runs/irun_025cf4c70a1f40eb/c26ad5cd2e5b4feb90bfe04585a4ec11/request.json)

DeepSeek Harness 固定版本在网页工具结果中提供来源 URL，提示模型使用 Markdown 链接。主循环提交助手消息后，无工具调用即完成。Toolathlon 采用这一答复边界。补注册错误提示可恢复原来的拒绝反馈，仍要求评测模型维护题目交付不需要的行坐标，因此本次从评测输入和答复契约一同移除行坐标。[网页搜索结果](https://github.com/deepseek-ai/deepseek-harness/blob/b150a551b8d465e31e418e1b2eaf5e79bbb7d28e/packages/web/tool-web/src/search.ts#L73-L94) · [主循环完成条件](https://github.com/deepseek-ai/deepseek-harness/blob/b150a551b8d465e31e418e1b2eaf5e79bbb7d28e/packages/core/agent-loop/src/agent.ts#L391-L418)

Toolathlon 启动配置关闭 `answer_citations`。该配置沿现有 Settings、Runtime 和 Journal 绑定进入 Conversation。答复模块从 `control_submit_final` 声明中移除 `references`，拒绝超出声明的字段，并跳过行坐标绑定。主请求按同一设置接续原工具调用、原文、来源 URL 和续读位置，不生成供答复提交的行坐标。普通 Markdown 答复和带限制状态的提交仍可用。生产和 LongDS 采用原配置，保持可选坐标契约。无新增持久化实体、入口或评测评分条件。撤回时恢复 Toolathlon 启动值。

验收用封存的 `identify-all-songs` 第 26 轮工具回执和答复核对两种配置。Toolathlon 侧应保留原文、URL 和读搜位置，模型请求无行引用指令、坐标及 `references` 声明。完整正文和无引用字段的限制提交可以解码，带旧字段的结构化提议应因字段超出声明被拒绝。默认配置保留真实引用的有效绑定。若运行原题复验，沿用原评测入口、模型和评分器，以歌曲文件通过且返回正式答复为整例判据。局部回放不改写旧评分。

2026-11-18 对封存的 35 条工具回执做中英文回放。关闭时保留原文、URL 和续读路径，答复声明只有 `message`、`disposition`，旧字段无法解码。默认配置仍能绑定有效坐标。同日原题复跑的 64 份主决策请求按新契约发送。该次用完 64 轮后返回受限答复，HTTP 调用未报错，未生成评分所需的 `songs.md`。整例未通过。[新配置复跑报告](../../.tmp/ta-nocite-1118-run/run/identify-all-songs/personal/report.json) · [上游评分](../../.tmp/ta-nocite-1118-run/run/identify-all-songs/personal/grader.log)

## 实施与证据

首版统一提交已删除 claim 路径和写作切换配置。以下为首版及 Toolathlon 当时的验证记录。LongDS 和 Toolathlon 共用正式 HTTP 评测链路；新增会话评测遵守[评测入口规范](../../evals/AGENTS.md#2-canonical-owner-与写入口)。旧 Canvas 快照与新 LongDS 快照的只读回放确认，同目录可打开新会话、旧会话恢复显式冲突，原始文件校验和保持一致。

LongDS 定向验证两轮均返回正式答复，实际发送 7 次模型请求，记录 142,063 token。两类语义核验均关闭，未运行独立评分。共享启动器按记录确认真实 Web 进程已经退出。[LongDS 采集报告](../../.tmp/td1115/ld-pilot/report.json)

Toolathlon 定稿批次已封存 96 题。`find-alita-paper` 验证网页读取后仍能直接交付。最新的评分、正式答复和阻塞项见[运行结果](../problems/toolathlon/agent-comparison.md#运行结果)。定向调试报告保留原运行版本，可作为启动和路由检查，批次分子只取定稿源码指纹的运行。
