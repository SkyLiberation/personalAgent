# DynaRev 邮轮用例的执行中补充指令对照

## 用例与验收

固定 DynaRev `f541cf529269d81f1105d767cad55a317d5be3d3` 的公开用例 `dyna_0a0fa834ce41b5297c6474293383759d_110325`。双方从 Carnival 首页和空会话开始，使用上游英文原话。首次只要求找从洛杉矶出发、至少 8 天的邮轮。评测器在上游第一个里程碑送入「选最便宜的」，在第二个里程碑送入「告诉我这艘邮轮有哪些船上活动」。题目、原始网页和浏览工具是 Agent 的输入。尚未送达的指令、里程碑定义和评分数据留在评测器。[公开原题](https://github.com/zsq259/DynaRev/blob/f541cf529269d81f1105d767cad55a317d5be3d3/data/additive.jsonl#L1)

双方各运行一条独立轨迹。双方使用同一模型端点、模型、浏览动作契约和独立浏览器上下文。沿用上游浏览环境、里程碑判断和最终约束评分，从双方各自的正式运行入口接入。personalAgent 使用正式 Conversation Web，运行期间通过同会话提交补充消息并记录实际返回。DeepSeek Harness 使用固定版本的 headless 和正式 `Agent.steer` 接口。评测适配放在 `evals/DynaRev`，复用 Web 启动器和现有 MCP 客户端装配。

整例通过要求两条补充指令在首轮最终答复前按顺序送入，原浏览状态继续使用，最终交付满足原题全部约束。Web 入口拒绝运行中提交、里程碑未到达、外部网页异常和评分故障分别记录。上游 runner 可在尝试提前结束时继续补发指令。下文将严格里程碑与上游补发策略分别计分。适配成绩单列，不计入上游榜单。

浏览步骤上限采用原题的 100 步，单方限时 600 秒，单次输出上限 32,768 tokens。实际运行命令、终态、浏览轨迹、增量消息和评分写入独立归档。网页发生变化时按实际页面评分。公网初态无法对齐时报告环境阻塞。

## 2026-11-21 对照结果

两边使用 `api.minimax.cn` 的 `MiniMax-M3.1-Flash` 和 Chromium 125.0.6422.26。DeepSeek Harness 固定为 `2e39e70496aa02986ca6a820c5d497e816b69d7e`。personalAgent 使用当时工作树，提交和源码摘要随运行保存。

首次双边实跑提供了第一条补充指令的送达证据。personalAgent 在第 6 个浏览步骤后命中里程碑，向运行中的原会话提交补充指令，Web 返回 HTTP 409，明确指出原轮尚未完成。DeepSeek Harness 在第 10 个浏览步骤后命中里程碑，`Agent.steer` 将补充指令送入原轮第 11 步。会话日志事件 71 是该用户消息，之后仍在轮次 1 执行工具。该轮完成了「选最便宜的」后的答复，第二条指令未送达。[personalAgent 的 HTTP 响应](../../../.tmp/dynarev-20261121/r2/personal-agent/i1.http.json) · [DeepSeek Harness 的浏览与注入序列](../../../.tmp/dynarev-20261121/r2/deepseek-harness/events.jsonl)

首轮使用上游默认评审预算。里程碑评审的 250-token 上限截断了部分结构化输出，DeepSeek Harness 的第二处里程碑检查全部未返回可用 JSON，最终评分也因约束拆解无 JSON 而未产生成绩。使用封存浏览快照和同一上游评审 Prompt 复查，设为低推理、至少 2,048 输出 tokens 后取得有效判定。双方新试次使用该配置，原轨迹保留。[首轮记录](../../../.tmp/dynarev-20261121/r2/summary.json)

定向复跑各一例，有效评分 2 例，整例通过 0 例。两边都在「6–9 天」结果内找到了符合原始要求的 8 天游轮。第一处里程碑检查按上游规则审查实际页面，结果仍含 6、7 天游轮，两条补充指令均未送达。最终评分认可三项原始约束，后两项对应的补充指令未送达，得分为 3/5。

| Agent | 复跑结果 | 实跑耗时 |
| --- | --- | --- |
| personalAgent | `milestone_not_reached`，有效终答，3/5。[结果](../../../.tmp/dynarev-20261121/r3/personal-agent/result.json) | 132.45 秒 |
| DeepSeek Harness | `milestone_not_reached`，有效终答，3/5。[结果](../../../.tmp/dynarev-20261121/r3/deepseek-harness/result.json) | 149.03 秒 |

第一条补充指令的入口差异由首轮 HTTP 响应和会话日志直接确认。第二条指令及两次补充后的最终任务交付均未覆盖。此处只记录该题在产品入口适配下的结果。[复跑汇总](../../../.tmp/dynarev-20261121/r3/summary.json) · [源码身份](../../../.tmp/dynarev-20261121/r3/repository.json) · [校验清单](../../../.tmp/dynarev-20261121/r3/checksums.sha256)

## DeepSeek Harness 完整协议验证

单独从空会话运行一例，保持原浏览环境、模型、预算和五项评分约束。按上游规则，正常执行中由网页里程碑触发补充指令。若 Agent 提交终答候选时还有指令待发，使用 Harness 的 `agent/turn-stopping` 在原轮关闭前送入下一条原始用户消息。每次仅送入一条。记录每条指令的触发方式、原轮消费事件和完整终答。此试次单独计分，严格依赖网页里程碑的对照成绩沿用原记录。[上游提前收尾规则](https://github.com/zsq259/DynaRev/blob/f541cf529269d81f1105d767cad55a317d5be3d3/src/agent_lib/runner.py#L277-L293) · [Harness 原轮关闭前钩子](https://github.com/deepseek-ai/deepseek-harness/blob/2e39e70496aa02986ca6a820c5d497e816b69d7e/packages/core/agent-loop/src/agent.ts#L400-L406)

2026-11-21 单方实跑 1 例，有效评分 1 例，**通过 1 例，满足 5/5 项约束**。执行阶段耗时 246.23 秒，共 19 次浏览工具调用。[最终评分](../../../.tmp/dynarev-20261121/dsh-full/deepseek-harness/result.json)

| 用户补充指令 | 触发方式 | 原轮消费证据 |
| --- | --- | --- |
| 选最便宜的 | 第 5 个浏览步骤后命中网页里程碑。 | 轮次 1、第 6 步，用户消息事件 46。 |
| 列出这艘邮轮的船上活动 | 第二处网页里程碑未触发。Agent 尝试收尾时，评测器在原轮关闭前补发。 | 轮次 1、第 13 步，用户消息事件 82。 |

Agent 收到第二条后继续浏览，在 Carnival 官网按船名筛选活动。最终答复选中 2027 年 1 月 16 日出发的 8 天 `Carnival Panorama` 行程，报告每人 423 美元起，并列出该船的活动。会话只记录一次完成终态。第二条的证据覆盖提前收尾后继续同轮执行这一分支。[浏览轨迹](../../../.tmp/dynarev-20261121/dsh-full/deepseek-harness/events.jsonl) · [里程碑判定](../../../.tmp/dynarev-20261121/dsh-full/deepseek-harness/milestones.jsonl) · [执行计划](../../../.tmp/dynarev-20261121/dsh-full/plan.json) · [校验清单](../../../.tmp/dynarev-20261121/dsh-full/checksums.sha256)

## 2026-11-22 personalAgent 同轮补充验证

接入同轮提交后的首跑在第 6 个浏览步骤发出 `i1`，收到了绑定原轮次的 HTTP 202。第一次后续实发模型请求的第 17 条消息以用户角色保留原文 `Now narrow those down to the cheapest one.`，前一条是浏览工具结果。Journal 记录补充指令在原轮第 7 步后接续，第 9 步接受目标修订。本轮在第二处里程碑前用完 200,000-token 评测预算。[回执](../../../.tmp/dynarev-20261121/pa-steer/personal-agent/i1.http.json) · [实发请求](../../../.tmp/dynarev-20261121/pa-steer/personal-agent/sdk/1c8b7da548d84afd8ad9391d4d4d5704.http.request.json) · [轮次轨迹](../../../.tmp/dynarev-20261121/pa-steer/personal-agent/turn-trace.json)

首跑实发请求仍展示已绑定任务的选择区块，随后出现 `task_already_bound`。复跑按任务绑定收起该区块，并将本题 personalAgent 预算调至 1,600,000 tokens，依据是已完成的 DeepSeek Harness 轨迹记录 1,424,261 tokens。复跑找到符合初始要求的 8 天游轮并交付结果。搜索范围仍包含 6、7 天游轮，第一处里程碑未成立，两条补充指令未发出，完整评分为 3/5。首跑和复跑合计执行两例，有效完整评分 1 例，整例通过 0 例。两条指令的自然里程碑路径尚未在同一正式轨迹中到达。[首跑汇总](../../../.tmp/dynarev-20261121/pa-steer/summary.json) · [复跑汇总](../../../.tmp/dynarev-20261121/pa-steer-r2/summary.json)

将首轮对照的 SQLite 复制到隔离目录，回到终态前的真实修订并使用原题的两条补充指令。复核终态提交遇到排队指令时须让出、重开 Journal 保留入队顺序、相同 ID 幂等、异文冲突、跨主体不可见、终态后的新 ID 被拒。此检查覆盖持久化与竞争边界，首跑同一轨迹独立证明用户原文进入真实模型输入。[同轮补充契约](../../adr/0054-session-run-step-journal.md#同轮补充指令)

## 2026-11-24 personalAgent 提前收尾补发验证

启用上游补发策略，沿正式 Web 入口运行一例。模型使用 `api.minimax.cn` 的 `MiniMax-M3.1-Flash`，评审使用同一上游约束。**补发机制通过，整题通过 1/1，满足 5/5 项约束。** 执行阶段耗时 281.44 秒，产品模型用量为 1,159,686 tokens。 [最终评分](../../../.tmp/dynarev-turn-stopping-20261124-target/personal-agent/result.json) · [运行身份](../../../.tmp/dynarev-turn-stopping-20261124-target/plan.json) · [校验清单](../../../.tmp/dynarev-turn-stopping-20261124-target/checksums.sha256)

| 指令 | 触发与消费 | 证据 |
| --- | --- | --- |
| 选最便宜的 | 第 5 个浏览步骤触发里程碑，原轮 HTTP 202。原文在第 6 个模型步骤后被领取。 | [回执](../../../.tmp/dynarev-turn-stopping-20261124-target/personal-agent/i1.http.json) · [首次携带原文的请求](../../../.tmp/dynarev-turn-stopping-20261124-target/personal-agent/sdk/96ed0310b29a4aceb0a8d79a9c4b7cce.http.request.json) |
| 列出这艘邮轮的船上活动 | 第 13 个浏览步骤记录 `premature_done()`，原轮 HTTP 202。原文在第 16 个模型步骤后被领取，Agent 随后继续浏览两步。 | [回执](../../../.tmp/dynarev-turn-stopping-20261124-target/personal-agent/i2.http.json) · [首次携带原文的请求](../../../.tmp/dynarev-turn-stopping-20261124-target/personal-agent/sdk/dc7af33c26914c4e9e215f78d65d4908.http.request.json) |

两条原文都以用户角色进入实发模型请求，单个请求内各出现一次。原轮第二次准备结束时已无待发指令，通知返回后正常提交。SSE 只发出一次 `done`，此前的正文增量拼接后等于最终答复。 [原轮 Journal](../../../.tmp/dynarev-turn-stopping-20261124-target/personal-agent/turn-trace.json) · [浏览轨迹](../../../.tmp/dynarev-turn-stopping-20261124-target/personal-agent/events.jsonl) · [终态事件](../../../.tmp/dynarev-turn-stopping-20261124-target/personal-agent/events.sse)

本次单方目标试次与 11 月 21 日的严格模式和 DeepSeek Harness 补发试次分别记账。

## 复跑入口

使用[DynaRev 同轮补充对照](../../evals/04-running-and-release.md#dynarev-同轮补充对照)的共用入口，选择 `--case cruise-steering`。复跑 11 月 24 日的单方目标试次时，加 `--agent personal-agent --upstream-completion-fallback` 并使用新的输出目录。
