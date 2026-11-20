# 纽约餐饮配送 Task 2 与 Task 3 对照评测

使用 LongDS v1.1 Full 的官方英文原件。Task 2 有 33 轮，Task 3 有 34 轮。两题使用同一份订单 CSV，双方为每题建立独立会话和容器。[Task 2 原件](https://huggingface.co/datasets/zjunlp/LongDS/blob/6b448459c333ecc050a2e89fcc65c0e044d763ac/task/longds_v1.1/business/nyc_restaurants_data_food_ordering_and_delivery/task2/task.json) · [Task 3 原件](https://huggingface.co/datasets/zjunlp/LongDS/blob/6b448459c333ecc050a2e89fcc65c0e044d763ac/task/longds_v1.1/business/nyc_restaurants_data_food_ordering_and_delivery/task3/task.json) · [原件核对](../../../.tmp/nyc23-20261119/inventory.json)

## 结果

2026-11-20，本 Agent 从第 31 轮续跑完成 Task 2，累计交付 33 轮，答对 21 轮。续跑使用扩大后的整题预算。Task 3 无人值守复跑交付 21 轮，答对 12 轮，第 22 轮触发整题额度。下表记录 2026-11-19 的双方对照。[Task 2 续跑结果](#task-2-从第-31-轮续跑) · [Task 3 复跑结果](#task-3-无人值守复跑)

| 用例 | Agent | 提交 / 交付 / 有效评分 | 答对 / 有效评分 | 生成耗时 | 已知模型总用量（tokens） |
| --- | --- | ---: | ---: | ---: | ---: |
| Task 2 | 本 Agent | 33 / 33 / 33 | 20 / 33 | 107 分 6 秒 | 23,651,066 |
| Task 2 | DeepSeek Harness | 33 / 33 / 33 | 10 / 33 | 23 分 9 秒 | 12,539,860 |
| Task 3 | 本 Agent | 5 / 4 / 4 | 4 / 4 | 3 分 45 秒 | 848,910 |
| Task 3 | DeepSeek Harness | 34 / 34 / 34 | 14 / 34 | 29 分 41 秒 | 17,698,579 |

## Task 2 逐轮对照

双方共同提交的 33 轮题面逐字一致。在双方均有有效评分的 33 轮中，本 Agent 答对 20 轮，DeepSeek Harness 答对 10 轮。本 Agent 单独答对的轮次为 8、9、10、11、12、13、16、17、21、24。DeepSeek Harness 答对的配对轮次，本 Agent 也全部答对。[逐轮评分](../../../.tmp/nyc23-20261119/t2/comparison.json) · [本 Agent 采集](../../../.tmp/nyc23-20261119/t2/capture/report.json) · [DeepSeek 采集](../../../.tmp/nyc23-20261119/t2/harness-retry/report.json) · [本 Agent 评分](../../../.tmp/nyc23-20261119/t2/judge/personal-score/report.json) · [DeepSeek 评分](../../../.tmp/nyc23-20261119/t2/judge/harness-score/report.json)

本 Agent 共执行 Bash 110 次，模型发起专用读取 0 次、专用编辑 0 次。DeepSeek Harness 的该次配置提供 Bash，发起 81 次。[本 Agent 工具证据](../../../.tmp/nyc23-20261119/t2/comparison.json) · [DeepSeek 工具装配](../../../.tmp/nyc23-20261119/t2/harness-retry/cordis.json)

## Task 3 逐轮对照

双方共同提交的 5 轮题面逐字一致。在双方均有有效评分的 4 轮中，本 Agent 答对 4 轮，DeepSeek Harness 答对 3 轮。本 Agent 单独答对的轮次为 3。DeepSeek Harness 答对的配对轮次，本 Agent 也全部答对。[逐轮评分](../../../.tmp/nyc23-20261119/t3/comparison.json) · [本 Agent 采集](../../../.tmp/nyc23-20261119/t3/capture/report.json) · [DeepSeek 采集](../../../.tmp/nyc23-20261119/t3/harness/report.json) · [本 Agent 评分](../../../.tmp/nyc23-20261119/t3/judge/personal-score/report.json) · [DeepSeek 评分](../../../.tmp/nyc23-20261119/t3/judge/harness-score/report.json)

本 Agent 共执行 Bash 20 次，模型发起专用读取 0 次、专用编辑 0 次。DeepSeek Harness 的该次配置提供 Bash，发起 104 次。[本 Agent 工具证据](../../../.tmp/nyc23-20261119/t3/comparison.json) · [DeepSeek 工具装配](../../../.tmp/nyc23-20261119/t3/harness/cordis.json)

## Task 2 首次中断

DeepSeek Harness 首次执行在第 15 轮第 6 步收到模型流错误 `PI_AI_ERROR`，交付了前 14 轮。表中采用相同配置的新会话重试。[首次中断轨迹](../../../.tmp/nyc23-20261119/t2/harness/turn-15.json) · [首次采集](../../../.tmp/nyc23-20261119/t2/harness/report.json)

## Task 3 本 Agent 停止原因

第 5 轮提出 `submit_goal_patch` 时，模型引用了最新用户消息中不存在的句段。准入先后拒绝了 `$.changes[0].evidence`、`$.task.evidence` 和 `$.changes[0].evidence`。其中第三次仍提交非原文的 `already in the current pressure state`。本轮未执行 Bash，正式入口返回 `limitation`，第 6–34 轮未提交。[本轮输入](../../../.tmp/nyc23-20261119/t3/capture/turn-05.request.json) · [模型决策与修复反馈](../../../.tmp/nyc23-20261119/t3/capture/turn-05.trace.json) · [正式响应](../../../.tmp/nyc23-20261119/t3/capture/turn-05.response.json)

DeepSeek Harness 在同一轮用两次 Bash 调用完成交付，继续执行至第 34 轮。[同轮 DeepSeek 轨迹](../../../.tmp/nyc23-20261119/t3/harness/turn-05.json)

DeepSeek Harness 在第 5 轮得 1 分。本 Agent 在该轮的记录是交付中断，评分为空。后续对原补丁做了[跨轮引文定向验证](../../optimization/to_verify/analysis-goal-maintenance.md#跨轮原话引用)，三个补丁均通过新准入，原整题成绩保留。[逐轮评分](../../../.tmp/nyc23-20261119/t3/comparison.json)

## Task 2 长会话优化回放

使用实际归档的六个模型调用状态，固定工具声明和预算时钟，对比优化前后构造的拟发请求。六份正文哈希及上下文摘要一致。范围包含首轮、历史未压缩、已压缩及 Bash 失败回执。表中的时间覆盖工作计划读取和请求构造。[基线回放](../../../.tmp/nyc23-20261119/t2/projection-baseline.json) · [优化后回放](../../../.tmp/nyc23-20261119/t2/projection-candidate.json)

| 归档位置 | 优化前 | 优化后 |
| --- | ---: | ---: |
| 第 1 轮第 1 步 | 0.033 秒 | 0.030 秒 |
| 第 8 轮第 6 步 | 0.966 秒 | 0.258 秒 |
| 第 16 轮第 10 步 | 5.043 秒 | 1.142 秒 |
| 第 27 轮第 6 步 | 14.242 秒 | 1.552 秒 |
| 第 31 轮第 13 步 | 23.669 秒 | 3.382 秒 |
| 第 33 轮第 5 步 | 27.370 秒 | 2.304 秒 |

第 33 轮第 5 步的 Journal 记录解码从 430 次降到 46 次。隔离回放核对了最新修订与冻结前驱分别读取、跨主体和会话隔离，以及重新取得锁或重开库时从 SQLite 重建。整题耗时和评分记录来自上方实跑。[修订与隔离回放](../../../.tmp/nyc23-20261119/t2/projection-scope-check.json) · [机制规格](../../optimization/to_verify/conversation-loop-boundaries.md#长会话历史读取与回执匹配)

## Task 2 历史读取优化后的本 Agent 复跑

从空会话重新提交官方英文 Task 2。预检固定了材料、模型、镜像、核验开关、预算和评分器。与原 Task 2 采集相比，源码只变更了历史回执匹配和 SQLite 会话历史读取两个文件。
[复跑计划](../../../.tmp/nyc2-hist-20261119/t2/plan.json) · [生成归档](../../../.tmp/nyc2-hist-20261119/t2/capture/report.json) · [用量与耗时](../../../.tmp/nyc2-hist-20261119/t2/run-metrics.json)

| 指标 | 优化前 | 优化后 |
| --- | ---: | ---: |
| 提交 / 交付 / 计划 | 33 / 33 / 33 | 1 / 0 / 33 |
| 答对 / 有效评分 | 20 / 33 | 无可评分答复 |
| 生成耗时 | 107 分 06 秒 | 10 分 19 秒 |
| 模型 HTTP 请求 | 219 | 40 |
| 已知模型总用量（tokens） | 23,651,066 | 1,625,084 |

复跑以 `terminal_limitation` 结束，已交付 0 轮，未提交 32 轮。

原运行首轮用 17 次主决策交付答复。本次首轮达到 40 次主决策上限，执行 Bash 38 次。模型在第 40 步继续读取清洗后的样本行，正式入口返回 `limitation`。`unzip` 缺失后已通过 Python `zipfile` 解包。

预算边界的定向回放复用本次停在第 40 步的快照和原运行第 17 步的交付材料。离线及实发模型结果见[预算执行](../../budge/README.md#主决策与工具额度独立)；整题成绩沿用原运行。
[首轮轨迹](../../../.tmp/nyc2-hist-20261119/t2/capture/turn-01.trace.json) · [正式响应](../../../.tmp/nyc2-hist-20261119/t2/capture/turn-01.response.json)

本次用时只覆盖首轮及启停。首轮没有前驱记录，长会话提速仍以此前的归档回放为依据。

逐轮评分保存在独立归档。两次从不同空会话生成，模型调用次数和答题路径会变化。[本次逐轮评分](../../../.tmp/nyc2-hist-20261119/t2/judge/personal-score/report.json)

运行中核对了只读输入、独立 `/tmp` 和禁网配置。[沙箱挂载](../../../.tmp/nyc2-hist-20261119/t2/sandbox-runtime.json)

## 目标引文与预算调整后的本 Agent 复跑

从空会话依次运行 Task 3 和 Task 2，各一次。测试当前跨轮引文、预算和上下文实现。沿用原官方英文题面、附件、MiniMax-M3.1-Flash、固定 Bash 镜像、两类核验关闭配置和隔离评分器。每轮上限为 40 次主决策、48 次工具、1000 万 tokens 和 3600 秒。每题已知生成额度 6000 万 tokens，独立评分额度 100 万 tokens。按正式入口的失败、限制、预算或计划终态停止并保留结果。

Task 3 核对第 5 轮是否通过目标维护并交付，并记录此后的整题覆盖。Task 2 核对首轮、整题交付和评分。两题保留结束原因及全部未执行轮次。与已封存的本 Agent 及 DeepSeek Harness 结果分开记录。

<!-- 复跑结果 -->

| 任务与运行 | 提交 / 交付 / 计划 | 答对 / 有效评分 | 生成耗时 | 已知模型总用量（tokens） |
| --- | ---: | ---: | ---: | ---: |
| Task 2 本次复跑 | 33 / 33 / 33 | 12 / 33 | 42 分 09 秒 | 20,348,432 |
| Task 2 本 Agent 历史 | 33 / 33 / 33 | 20 / 33 | 107 分 06 秒 | 23,651,066 |
| Task 2 DeepSeek Harness 历史 | 33 / 33 / 33 | 10 / 33 | 23 分 09 秒 | 12,539,860 |
| Task 3 本次复跑 | 34 / 34 / 34 | 13 / 34 | 36 分 46 秒 | 19,144,936 |
| Task 3 本 Agent 历史 | 5 / 4 / 34 | 4 / 4 | 3 分 45 秒 | 848,910 |
| Task 3 DeepSeek Harness 历史 | 34 / 34 / 34 | 14 / 34 | 29 分 41 秒 | 17,698,579 |

- Task 2 本次以 `planned_turns_finished` 结束。0 轮未提交，生成 HTTP 请求 182 次，未知用量 0 次。[计划](../../../.tmp/nyc23-rerun-20261119/t2/plan.json) · [生成归档](../../../.tmp/nyc23-rerun-20261119/t2/capture/report.json) · [逐轮评分](../../../.tmp/nyc23-rerun-20261119/t2/judge/personal-score/report.json) · [沙箱运行检查](../../../.tmp/nyc23-rerun-20261119/t2/sandbox-runtime.json)
- Task 2 评分消耗 148,550 tokens，有效评分 33 轮。
- Task 2 第 1 轮返回 `answer`，得 1 分，记录 1 次已接纳目标操作和 10 个 Bash 回执。[正式响应](../../../.tmp/nyc23-rerun-20261119/t2/capture/turn-01.response.json) · [轨迹](../../../.tmp/nyc23-rerun-20261119/t2/capture/turn-01.trace.json)
- Task 2 首轮用了 12 次主决策。前一次历史读取优化复跑在首轮第 40 步达到上限。两次属于独立会话。
- Task 2 逐轮分数与历史运行并列，缺分保持为空。[逐轮对照](../../../.tmp/nyc23-rerun-20261119/t2/historical-comparison.json)
- Task 3 本次以 `planned_turns_finished` 结束。0 轮未提交，生成 HTTP 请求 176 次，未知用量 0 次。[计划](../../../.tmp/nyc23-rerun-20261119/t3/plan.json) · [生成归档](../../../.tmp/nyc23-rerun-20261119/t3/capture/report.json) · [逐轮评分](../../../.tmp/nyc23-rerun-20261119/t3/judge/personal-score/report.json) · [沙箱运行检查](../../../.tmp/nyc23-rerun-20261119/t3/sandbox-runtime.json)
- Task 3 评分消耗 137,535 tokens，有效评分 34 轮。
- Task 3 第 5 轮返回 `answer`，得 1 分，记录 1 次已接纳目标操作和 1 个 Bash 回执。[正式响应](../../../.tmp/nyc23-rerun-20261119/t3/capture/turn-05.response.json) · [轨迹](../../../.tmp/nyc23-rerun-20261119/t3/capture/turn-05.trace.json)
- Task 3 第 16、17、18、26 轮的目标增量共接纳 9 段来自前序轮次的引文。第 5 轮的引文来自本轮。[跨轮来源核对](../../../.tmp/nyc23-rerun-20261119/t3/cross-turn-evidence.json)
- Task 3 逐轮分数与历史运行并列，缺分保持为空。[逐轮对照](../../../.tmp/nyc23-rerun-20261119/t3/historical-comparison.json)

### Task 2 首次通过、复跑未通过的轮次

首次完整运行得 20/33，复跑得 12/33。两次的 33 轮英文输入、数据附件和评分配置一致，均完成交付并获得有效评分。第 8、10、11、12、13、16、17、24 轮由 1 分变为 0 分，复跑没有新增通过轮。以下核对参考答案、终答和实际执行轨迹。[首次评分](../../../.tmp/nyc23-20261119/t2/judge/personal-score/report.json) · [复跑评分](../../../.tmp/nyc23-rerun-20261119/t2/judge/personal-score/report.json) · [参考答案](../../../.tmp/nyc23-rerun-20261119/t2/materials/evaluator-private/task.json)

| 轮次 | 首次通过的结果 | 复跑差异 |
| --- | --- | --- |
| 8 | 沿用第 6 轮的 17 个单位及客户覆盖判断，风险跨界数为 0，按慢单率差值列出 8 项。 | 实发上下文保留了 17 个单位的范围。脚本仍对全部 70 个合格单位重算客户覆盖，以此报告 2 项跨界（Cafe Habana、Momoya）。即使收回到 17 个单位，新覆盖判断仍会令 Cafe Habana 跨界。[实发上下文](../../../.tmp/nyc23-rerun-20261119/t2/capture/sdk/aec6e8591d7b40a0adf22fb80d05b043.http.request.json) · [执行轨迹](../../../.tmp/nyc23-rerun-20261119/t2/capture/turn-08.trace.json) |
| 10 | 报告 59 个问题单位及 8 个主要佣金敞口。 | 沿用第 9 轮的 29 个品牌候选，只计其 40 个合格成员中的 34 个问题单位。答复也给出了全体合格单位中的 59/70，8 个敞口的名称和佣金也一致。评分按主答的 34 判错。[复跑答复](../../../.tmp/nyc23-rerun-20261119/t2/capture/turn-10.response.json) |
| 11 | 在 84 个候选中排序，The Loop、Asuka Sushi、Song Thai Restaurant & Bar 均提升 7 位。 | 脚本读取第 9 轮文件中的 29 个候选，只得到 4 个正向提升，Sarabeth 以提升 2 位居首。扩大到复跑的全部 62 个品牌也仍缺席部分参考候选。[执行轨迹](../../../.tmp/nyc23-rerun-20261119/t2/capture/turn-11.trace.json) |
| 12 | 在 84 个候选中排序，Burger Joint 居首，补贴压力为 1.6667。 | 脚本继续使用第 9 轮留下的 29 个候选，Yama Japanese Restaurant 以 1.4218 居首，8 个入选品牌均与参考名单不同。[执行轨迹](../../../.tmp/nyc23-rerun-20261119/t2/capture/turn-12.trace.json) |
| 13 | 频次、消费额及共有目标数分别为 71、81、71，并列出 8 个变化。 | 继续在 29 个品牌中计算，三个计数变为 27、29、27，只剩 The Kati Roll Company 和 Vanessa's Dumplings 两个新增，均与参考变化一致。[复跑答复](../../../.tmp/nyc23-rerun-20261119/t2/capture/turn-13.response.json) |
| 16 | Tamarind TriBeCa、The Smile 均有残差慢单，慢单率为 7.4074%、5.5556%，均低于 9.2202% 的风险阈值。 | 第 14 轮从 29 个候选取出的有效评分数中位数为 17，The Smile 的 12 条有效评分未过门槛，因而出局。对剩下的 Tamarind TriBeCa，脚本只把超过风险阈值的行列入压力清单，漏报其 2 笔残差慢单。[第 14 轮轨迹](../../../.tmp/nyc23-rerun-20261119/t2/capture/turn-14.trace.json) · [第 16 轮轨迹](../../../.tmp/nyc23-rerun-20261119/t2/capture/turn-16.trace.json) |
| 17 | 保留两家。Tamarind TriBeCa 的两种慢单率相差 7.4074 个百分点，The Smile 的差值为 0，两家均无残差独有风险。 | 沿用第 14 轮的质量判定，正式表只有 Tamarind TriBeCa。附表算对了 The Smile 的两项 5.5556%，但因质量未过门槛，把它在两种视图下都判为有风险。[复跑答复](../../../.tmp/nyc23-rerun-20261119/t2/capture/turn-17.response.json) |
| 24 | 两种范围均有分析，且完整列出第 20 轮正式复核的四个单位。四项优先级差值均为 0。 | Bash 输出了四项的调整佣金、净佣金、评分、客户份额和零差值。终答主要展示 64 个单位中的 7 个非零案例，对正式四项仅保留零差值和扣减额。评分器以范围和字段缺失判错。[实发工具回执](../../../.tmp/nyc23-rerun-20261119/t2/capture/sdk/0333bb28082c463885004a140c06b9fc.http.request.json) · [复跑答复](../../../.tmp/nyc23-rerun-20261119/t2/capture/turn-24.response.json) |

第 9 轮的复跑脚本在汇总品牌前，先筛掉未达到 5 单的餐厅单位。品牌全集由 167 个缩为 62 个，讨论候选由 84 个缩为 29 个。第 9 轮的 8 个品牌、风险变化方向和顺序仍与参考一致，评分器给了 1 分。第 10–13 轮直接消费了缩小的候选池。两次第 14 轮均未通过，两次都以有效评分数衡量覆盖，复跑的候选池把该门槛从 4.5 抬到 17，又改变了第 16–17 轮的安全推广名单。[首次第 9 轮](../../../.tmp/nyc23-20261119/t2/capture/turn-09.response.json) · [复跑第 9 轮](../../../.tmp/nyc23-rerun-20261119/t2/capture/turn-09.trace.json) · [首次第 14 轮](../../../.tmp/nyc23-20261119/t2/capture/turn-14.response.json)

本次样本表明，一次范围决策可以改变多轮结果。两次都完整交付，八个失分轮在交付前均有成功 Bash 回执。两次使用不同代码与独立模型采样，这组记录无法单独量化跨轮引文、预算、历史读取优化或采样对分差的影响。

### 本 Agent 复跑耗时分解

用 SDK 候选响应的 `wall_seconds` 统计完整模型调用，包含流式摘要的响应体读取。Bash 网关按 `tool.audit.latency_ms` 统计，包含输入准备、执行和结果发布。其余时间为整次生成采集减去上述两类计时，仍包含会话运行、请求构造及采集启动、归档等开销。[首次 Task 2](../../../.tmp/nyc23-20261119/t2/capture/report.json) · [复跑 Task 2](../../../.tmp/nyc23-rerun-20261119/t2/capture/report.json) · [复跑 Task 3](../../../.tmp/nyc23-rerun-20261119/t3/capture/report.json)

| 运行 | 生成总耗时 | 主模型 SDK | 历史摘要 SDK | 工具网关 | 其余 |
| --- | ---: | ---: | ---: | ---: | ---: |
| Task 2 首次 | 107 分 06 秒 | 37 分 34 秒（217 次） | 1 分 46 秒（2 次） | 11 分 25 秒 | 56 分 21 秒 |
| Task 2 复跑 | 42 分 09 秒 | 23 分 43 秒（175 次） | 6 分 34 秒（7 次） | 4 分 59 秒 | 6 分 53 秒 |
| Task 3 复跑 | 36 分 46 秒 | 23 分 01 秒（174 次） | 1 分 45 秒（2 次） | 4 分 46 秒 | 7 分 14 秒 |

Task 2 总耗时下降 60.6%，总 tokens 下降 14.0%。两次的主模型与摘要调用合计省下约 9 分钟，工具网关省下约 6 分钟，其余差值集中在未单独计时的阶段。前文六份请求构造回放证明了历史读取与回执匹配优化的局部收益。整题差值还受代码差异和独立决策轨迹影响。[首次日志](../../../.tmp/nyc23-20261119/t2/capture/server.log) · [复跑 Task 2 日志](../../../.tmp/nyc23-rerun-20261119/t2/capture/server.log) · [复跑 Task 3 日志](../../../.tmp/nyc23-rerun-20261119/t3/capture/server.log)

- **Bash 输入复用有直接证据。** 两题各用一个容器。Task 2、Task 3 的 Bash 网关分别花 299.0、285.9 秒，执行回执分别记载 78.6、67.1 秒。两者之间各有约 220 秒用于命令准备、容器调度、产物和回执处理。两题最后一条命令分别带入 440、415 个输入。当时的实现逐个读取绑定输入，复用容器时仍清空并重建只读输入暂存。后续改动及定向回放单独记录。[只读输入复用](../../optimization/to_verify/python-data-analysis-tool.md#只读输入复用) · [Task 2 末轮轨迹](../../../.tmp/nyc23-rerun-20261119/t2/capture/turn-33.trace.json) · [Task 3 末轮轨迹](../../../.tmp/nyc23-rerun-20261119/t3/capture/turn-34.trace.json)
- **Task 2 摘要有明显长尾，也确实缩短了后续请求。** 第 17 轮单次摘要用了 225.5 秒。服务方在 101.9 秒时返回响应头，流式响应体又耗时约 123.6 秒。第 11 轮首次摘要前后的相邻主模型请求由 719,301 降至 232,142 字节，输入 tokens 由 180,497 降至 60,501，缓存命中 tokens 同时由 150,272 降至 9,472。摘要收益应按段累计，计入摘要调用和前缀重新预热的成本。主模型输入缓存命中比例在两题分别为 78.6% 和 89.7%。[第 17 轮摘要 HTTP 回执](../../../.tmp/nyc23-rerun-20261119/t2/capture/sdk/62a582393a8e4680a486e1f87d9af495.http.response.json) · [第 11 轮摘要前请求](../../../.tmp/nyc23-rerun-20261119/t2/capture/sdk/8ba6bb18196f4471a22e74acbc8f36e4.http.request.json) · [第 11 轮摘要后请求](../../../.tmp/nyc23-rerun-20261119/t2/capture/sdk/76cacc2ea26340e7a7e351e5da13a988.http.request.json)
- **Task 3 的第 34 轮适合定位决策链开销。** 单轮约 7 分 17 秒，包含 16 次主模型请求和 14 次 Bash。模型 SDK 约 3 分 33 秒，Bash 网关约 1 分 18 秒。轨迹包含读取旧脚本、一次失败后的状态检查、修补和重新计算。逐条保留有信息增益的检查，先确定哪些步骤可以共用已产出的结果。[第 34 轮轨迹](../../../.tmp/nyc23-rerun-20261119/t3/capture/turn-34.trace.json)

复跑两题仍分别有 6 分 53 秒和 7 分 14 秒缺少细粒度归因。按采集文件时间戳估算，其中约 6 分 03 秒和 6 分 25 秒发生在等待正式 Turn 响应期间。可在这一范围内按请求组装、Journal 版本读写和响应处理分段测量。本节为封存记录的只读分析，保留原成绩和运行身份。

## 压缩与 Bash 输入复用后的本 Agent 复跑

使用上一次复跑的封存英文题面与数据，从空会话依次运行 Task 3 和 Task 2，各一次。沿用相同模型、评分资格、固定 Bash 镜像、禁网与两类核验关闭配置。每轮仍为 40 次主决策、48 次工具、1000 万 tokens 和 3600 秒，每题生成、评分额度分别为 6000 万和 100 万 tokens。每题到正式入口的计划终态、限制、错误或预算耗尽时封存，独立评分实际交付的轮次。

记录答对数、交付数、生成耗时、用量、摘要调用及检查点激活次数。与上一次封存运行分列，变化覆盖当前代码和独立模型决策轨迹。[Task 2 计划](../../../.tmp/nyc23-pressure-20261120/t2/plan.json) · [Task 3 计划](../../../.tmp/nyc23-pressure-20261120/t3/plan.json) · [上下文策略](../../context/context-management.md#1-历史压缩) · [Bash 输入复用](../../optimization/to_verify/python-data-analysis-tool.md#只读输入复用)

<!-- 压缩优化复跑结果 -->

| 任务与运行 | 提交 / 交付 / 计划 | 答对 / 有效评分 | 生成耗时 | 已知模型总用量（tokens） | 摘要调用 / 激活 |
| --- | ---: | ---: | ---: | ---: | ---: |
| Task 2 含续跑 | 33 / 33 / 33 | 21 / 33 | 41 分 21 秒 | 67,177,680 | 0 / 0 |
| Task 2 续跑前 | 31 / 31 / 33 | 21 / 31 | 37 分 46 秒 | 60,053,780 | 0 / 0 |
| Task 2 上次 | 33 / 33 / 33 | 12 / 33 | 42 分 09 秒 | 20,348,432 | 7 / 7 |
| Task 3 无人值守复跑 | 22 / 21 / 34 | 12 / 21 | 63 分 18 秒 | 60,107,747 | 0 / 0 |
| Task 3 澄清停跑 | 16 / 15 / 34 | 12 / 15 | 13 分 14 秒 | 10,005,618 | 0 / 0 |
| Task 3 上次 | 34 / 34 / 34 | 13 / 34 | 36 分 46 秒 | 19,144,936 | 2 / 2 |

- Task 2 在 6,000 万 tokens 额度下以 `case_budget_exhausted` 停在第 31 轮。该段有 250 次生成 HTTP 请求，主模型最高输入 492,040 tokens。比较两次运行的前 31 轮，生成用量由 18,410,745 增至 60,053,780 tokens，主决策请求由 163 次增至 250 次。[生成归档](../../../.tmp/nyc23-pressure-20261120/t2/capture/report.json) · [逐轮评分](../../../.tmp/nyc23-pressure-20261120/t2/judge/personal-score/report.json) · [逐轮对照与压缩统计](../../../.tmp/nyc23-pressure-20261120/t2/comparison.json)
- Task 2 含续跑一行合计两个采集进程的用时，共 264 次生成 HTTP 请求。用时范围为两段采集，沙箱重建和评分分别归档。DeepSeek Harness 在 2026-11-19 的 Task 2 对照档案中交付 33 轮，答对 10 轮，生成用量 12,539,860 tokens。最新续跑采用独立副本及更高的整题额度，两份记录各反映其运行条件。[本 Agent 续跑汇总](../../../.tmp/nyc2r-1120/summary.json) · [DeepSeek Harness 采集](../../../.tmp/nyc23-20261119/t2/harness-retry/report.json) · [DeepSeek Harness 评分](../../../.tmp/nyc23-20261119/t2/judge/harness-score/report.json)
- Task 3 上次在第 16 轮以 `terminal_clarification_required` 结束，18 轮未提交。生成 HTTP 请求 104 次，主模型最高输入 209,795 tokens。[生成归档](../../../.tmp/nyc23-pressure-20261120/t3/capture/report.json) · [逐轮评分](../../../.tmp/nyc23-pressure-20261120/t3/judge/personal-score/report.json) · [逐轮对照与压缩统计](../../../.tmp/nyc23-pressure-20261120/t3/comparison.json)
- Task 3 第 16 轮请求澄清。该轮目标更新先收到 constraint_change_requires_verification。共同有分的 15 轮由 11 分变为 12 分。本次耗时仅覆盖实际提交的轮次。[终止轨迹](../../../.tmp/nyc23-pressure-20261120/t3/capture/turn-16.trace.json)
- 后续使用该轮真实阶段输入定向回放。新的无人值守配置撤下提问入口，模型一次提交了可接纳的目标补丁，保留原任务约束并记录本轮新要求。此次回放未生成答复，原评分沿用上表。[澄清协议与验收](../../adr/0055-unified-conversation-answer.md#澄清由独立工具提交)

### 生成用量对齐回放

2026-11-20 使用两方已封存记录回放生成用量。Task 2 在第 30 轮后累计 55,707,328 tokens，预算仍可开启第 31 轮。在第 31 轮后累计 60,053,780 tokens，整题预算拦住第 32 轮。其中总输入 59,824,922，缓存读取 58,106,650，缓存未命中输入 1,718,272，输出 228,858。250 次 HTTP 请求均有输入和输出记录，缓存写入未报告。DeepSeek Harness 的 15 轮事件可独立重算为 7,184,610 已知 tokens 和 1 个未知步骤。Task 1 本 Agent 的 162 次物理请求仍有 1 次用量未知。以上为原件回放，未新增生成调用。[用量回放](../../../.tmp/longds-token-parity-20261120/report.json) · [预算及归档契约](../../budge/README.md#评测中的独立预算)

### Task 2 从第 31 轮续跑

按用户授权把整题生成上限从 60M 调至 85M，保留前 31 轮的 60,053,780 已知 tokens、用户原文、答案、模型原件和执行回执。正式检查点入口绑定原许可与第 17 轮；本次使用第 31 轮封存状态的独立评测副本，重新绑定同一主体与会话的扩大额度。原封存与生产恢复契约沿用。原容器已回收，使用相同镜像和字节摘要匹配的历史命令，在断网沙箱重建 `/tmp`，单列重放及其差异。只通过正式 HTTP 入口发送第 32、33 轮英文原题，沿用原每轮预算、模型与评分资格。停在正式交付、限制、错误或预算边界；只对新增答案独立评分。

续跑完成，累计交付 33/33 轮，终态为 `planned_turns_finished`。新增 14 次模型请求，合计使用 7,123,900 tokens，续跑采集耗时 3 分 35 秒，整题已知模型用量累计 67,177,680 tokens。第 32、33 轮分别消耗 2,497,925 和 4,625,975 tokens，独立评分均为 0。前 31 轮的 21 分与续跑成绩合计为 21/33。77 条历史 Bash 命令的退出状态全部一致，75 条输出逐字节一致，其余两条仅目录列表的时间戳不同。[续跑汇总](../../../.tmp/nyc2r-1120/summary.json) · [生成归档](../../../.tmp/nyc2r-1120/c/report.json) · [新增评分](../../../.tmp/nyc2r-1120/judge/tail-score/report.json) · [沙箱重放](../../../.tmp/nyc2r-1120/workspace-replay.json)

### Task 3 无人值守复跑

2026-11-20 从空会话重跑官方英文 Task 3。沿用 6,000 万的整题生成额度、1,000 万的单轮额度、原模型、镜像与独立评分器。实发请求的 289 份目标补丁声明均已去掉旧的提问字段，澄清工具声明数为 0。第 16 轮提交一次合法目标补丁，随后交付答案，独立评分为 1。与上次共同有分的前 15 轮中，本次答对 10 轮，上次答对 12 轮。[运行计划](../../../.tmp/nyc3-1120/plan.json) · [第 16 轮轨迹](../../../.tmp/nyc3-1120/c/turn-16.trace.json) · [逐轮评分](../../../.tmp/nyc3-1120/judge/personal-score/report.json)

第 21 轮结束时累计 55,430,929 tokens。第 22 轮使用 4,676,818 tokens 后达到整题额度，Runtime 返回 `limitation`，第 23–34 轮未提交。289 次 HTTP 请求有 1 次用量未知。评分耗费 98,857 tokens，独立记账。运行期间工作树新增了未调用的 SSE 辅助函数，记录按启动时封存的源码快照核对。[复跑汇总](../../../.tmp/nyc3-1120/summary.json) · [生成归档](../../../.tmp/nyc3-1120/c/report.json) · [第 22 轮轨迹](../../../.tmp/nyc3-1120/c/turn-22.trace.json) · [沙箱装配](../../../.tmp/nyc3-1120/sandbox-runtime.json)

### Task 3 从第 22 轮续跑

整题生成额度从 6,000 万提高到 1.5 亿 tokens，已知消费 60,107,747 和单轮上限 1,000 万继续参与预算判断。独立评测副本使用原运行封存的源码、会话和镜像。第 22 轮恢复到生成额度终止前的最近修订，保留 11 个已付费的模型响应与已提交工具结果，重新授予该轮运行时限。原 `/tmp` 通过原命令和输入重放重建。通过正式恢复入口接续第 22 轮，再顺序提交第 23–34 轮英文原题。前 21 轮沿用封存评分，新增答复独立评分。

首次续跑交付第 22–25 轮。第 26 轮使用 10,061,402 tokens 时触发单轮上限，其 20 次主模型决策均已记录。这一段续跑将单轮额度提高到 2,000 万，从第 26 轮终止前修订接续。整题额度为 1.5 亿 tokens，各段用量累计计入。这一段每轮上限为 40 次主决策、48 次工具调用。

第 26 轮两次出现 Bash 超时后回收容器。两条命令分别等待 60 秒和 55 秒，实际执行在 59.203 秒和 54 秒时被终止。后续 `workspace_unavailable` 回执确认命令未派发。DeepSeek Harness 的该对照插件在 `docker exec` 内用 `timeout` 限制命令进程，容器生命周期独立。本次隔离恢复沿用本 Agent 的容器回收规则，将 Bash 命令授权从 60 秒增至 180 秒。第 26 轮已累计 40 次主决策和 20,482,951 tokens，续跑配置提供 56 次和 3,000 万的单轮额度。整题仍按 1.5 亿计量。恢复保留失败回执，重放实际已完成的命令，再从未消费的主决策接续。[对照 Bash 插件](../../../.tmp/nyc23-20261119/bash-container-aligned.mjs) · [第 26 轮第二次停止轨迹](../../../.tmp/nyc3rf-1120/c/turn-26.trace.json)

用户停止最后一段续跑时，已交付 25/34 轮，答对 12/25 轮。第 26 轮已记录 41 次主模型响应，尚无正式答复。已知生成用量累计 93,709,361 tokens，第 26 轮各段合计 21,014,980 tokens。运行器和 Web 进程已退出，容器暂停保留工作目录。180 秒配置只观察到有限接续，整轮结果未到达。[首次续跑评分](../../../.tmp/nyc3r-1120/judge/tail-score/report.json) · [最后一段沙箱登记](../../../.tmp/nyc3rt-1120/sandbox-runtime.json) · [停跑用量审计](../../../.tmp/nyc3-cost-20261120/report.json)

### Task 3 Bash 失败与用量对照

Bash 的 60 秒自命令授权时开始计量。命令登记、容器检查和只读输入暂存在 Docker Exec 启动前占用同一绝对时限。第二次超时从授权到 Exec 登记约用 6.14 秒，命令实际获得约 54 秒，55 秒的等待尚未结束。容器回收后，后续调用仍绑定原工作区登记。两次超时后的 26 条 `workspace_unavailable` 命令均未派发。请求这些动作的 26 次模型决策合计使用 13,322,573 tokens，占第 26 轮已知用量约 63%。[授权截止时间](../../../src/personal_agent/application/bash_execution/service.py#L200) · [执行与回收](../../../src/personal_agent/infra/bash_execution/backend.py#L142) · [容器工作区准入](../../../src/personal_agent/infra/bash_execution/run_container.py#L308) · [原件审计](../../../.tmp/nyc3-cost-20261120/report.json)

对齐两边实际提交且逐字相同的前 25 轮英文题面。模型、端点和镜像相同。用量从原响应累计，模型次数统计有用量的步骤。该对照来自独立归档，包含运行器和模型决策轨迹的差异。[前 25 轮对照](../../../.tmp/nyc3-cost-20261120/report.json) · [DeepSeek Harness 原始记录](../../../.tmp/nyc23-20261119/t3/harness/report.json)

| 指标 | 本 Agent | DeepSeek Harness |
| --- | ---: | ---: |
| 有用量的模型请求 | 315 | 105 |
| 已知模型总用量（输入加输出，tokens） | 72,694,381 | 9,477,060 |
| 总输入（含缓存，tokens） | 72,455,436 | 9,345,048 |
| 输出（tokens） | 238,945 | 132,012 |
| 缓存读取（tokens） | 69,700,266 | 9,142,110 |
| 缓存写入（tokens） | 未报告 | 0（SDK 折算） |
| 折算未缓存输入（tokens） | 2,755,170 | 202,938 |
| 输入缓存命中率 | 96.20% | 97.83% |
| 单请求平均输入（tokens） | 230,017 | 89,000 |

本 Agent 的原始回包在缓存分项中只提供读取量。为与 DeepSeek Harness 对齐，未缓存输入按总输入减读取量和已报告的写入量折算。命中率为缓存读取量占总输入的比例。只读回放用新口径复算了这 25 轮，也核对了首次采集的 289 次物理请求、1 次未知用量和 60,107,747 tokens 的预算合计。[用量回放](../../../.tmp/longds-usage-display-20261120/report.json) · [LongDS 用量与预算](../../budge/README.md#评测中的独立预算)

总用量相差 7.67 倍，由约 3 倍的调用次数和 2.56 倍的每次总用量相乘得到。本 Agent 发起 78 次 `tool_bash`、162 次 `tool_read_file`、27 次目标更新和 25 次 Artifact 创建。DeepSeek Harness 提交 81 次 Bash 工具动作。第 25 轮最后一次模型实发正文约 176 万字节，其中助手消息和配对工具回执合计约 168 万字节。该请求输入为 491,357 tokens，仍低于 800,000 的自动压缩触发线。两个归档在这段对照均无已激活的历史摘要。缓存命中输入继续计入整题预算，未命中的输入也相差约 13.6 倍。[本 Agent 第 25 轮实发请求](../../../.tmp/nyc3r-1120/c/sdk/c48e056f459a486dbeffadbaabf124bb.http.request.json) · [用量与事件审计](../../../.tmp/nyc3-cost-20261120/report.json)

## 运行口径

- 本 Agent 通过正式 Conversation HTTP 入口提交，沿用 Task 1 的两类语义核验关闭配置。DeepSeek Harness 固定为 `2e39e70496aa02986ca6a820c5d497e816b69d7e`，通过原生 SDK 执行。两边使用同一个 MiniMax-M3.1-Flash、同一固定 Docker 镜像、同一 MiMo-V2.6-Pro 评分配置。
- 两边均可在 `/tmp` 编写、修改和执行脚本。生成接收允许的数据 ZIP 和原始英文题面，评分材料留在独立目录。每个 Agent 串行运行两个用例，两条执行队列可并行。工具声明、模型请求的超时和预算由各自运行器配置。耗时和用量覆盖本次实测样本。
- 本记录使用当前工作树做定向对照，结论覆盖这两个用例的实测样本。
- [Task 2 计划](../../../.tmp/nyc23-20261119/t2/plan.json) · [Task 3 计划](../../../.tmp/nyc23-20261119/t3/plan.json) · [Task 2 运行挂载](../../../.tmp/nyc23-20261119/t2/sandbox-runtime.json) · [Task 1 历史对照](2026-11-18-nyc-restaurants-task1.md)
