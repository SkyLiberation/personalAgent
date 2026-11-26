# 运行预算总结

对话运行按单次用户请求累计主模型决策、工具调用、子智能体委派和 token 用量。单次模型请求另受上下文窗口和输出额度约束。启用 Python 分析、检索实验或独立 Research 时，还会叠加对应的任务预算。本文根据当前运行实现与配置整理，运行结果见[评测盘点](../evals/02-current-case-inventory.md)。

## 对话主循环

一次用户请求建立一个对话运行（`interaction_run_ref`），内部可以做多轮模型决策。`AgentRuntime` 装配预算组件 `ConversationBudget`。对话运行日志（`Journal`）记录实际用量，预算组件据此计算余额和判断准入。[运行系统](../topics/runtime.md#conversation-loop) · [预算实现](../../src/personal_agent/application/conversation/budget.py) · [运行装配](../../src/personal_agent/orchestration/runtime.py)

| 预算 | 代码默认 | `.env.example` | 环境变量 | 计量口径 |
| --- | ---: | ---: | --- | --- |
| 累计 token | 32,000 | 2,000,000 | `PERSONAL_AGENT_INTERACTION_MAX_TOTAL_TOKENS` | 已提交的模型输入和输出用量，包括同一运行内计入日志的意图识别、摘要、核验和修复调用 |
| 模型决策轮次 | 8 | 32 | `PERSONAL_AGENT_INTERACTION_MAX_MODEL_TURNS` | 每次主模型决策占一轮。该轮的内部结构化调用按实际 token 记账 |
| 工具调用 | 12 | 48 | `PERSONAL_AGENT_INTERACTION_MAX_TOOL_CALLS` | 每个进入执行的工具动作占一次，包括执行失败的动作。运行时另对工作区执行、目标维护和适用的核验活动计数 |
| 子智能体委派 | 4 | 沿用默认值 | `PERSONAL_AGENT_INTERACTION_MAX_AGENT_CALLS` | 每个进入执行的委派动作占一次，使用独立额度 |
| 批内并发 | 4 | 沿用默认值 | `PERSONAL_AGENT_INTERACTION_MAX_CONCURRENCY` | 安全批次中同时执行的动作数。每个动作仍分别占用调用额度 |

本地 `.env` 的累计 token、模型轮次和工具次数与示例值一致。已启动进程在重启后重新读取配置。[环境变量读取](../../src/personal_agent/kernel/config_env.py) · [示例配置](../../.env.example) · [对话运行预算](../env.md#对话运行预算)

- **累计 token 按已知消费准入。** 每次新增模型实发前检查余额和适用的截止时间。响应原件提交时优先采用服务提供方报告的总量，否则累加已知输入和输出。用量缺失时，累计值只表示已知下界。在途请求可以把累计用量推过阈值。已付费原件按原调用身份恢复解码并去重记账。[运行日志](../../src/personal_agent/application/conversation/journal.py) · [模型重试与记账](../topics/runtime.md#model-retry)
- **工具和委派先准入再分配。** 配置整数工具上限时，批次按动作顺序分配余额，超额动作收到 `budget_exhausted`。普通工具额度耗尽时，下一次主决策撤下用完额度的工具。设为 `0` 时，从首步起撤下普通工具。显式选择 `unlimited` 时，工具执行仍逐项记账，工具次数不参与派发和下一次请求的工具可见性判断。主决策、累计 token、截止时间、委派、核验与权限按各自契约判定。[主循环实现](../../src/personal_agent/application/conversation/service.py) · [预算实现](../../src/personal_agent/application/conversation/budget.py)
- **预算耗尽时保留已有结果。** 新主决策在步数、累计 token 或截止时间达到上限时停止。运行可恢复已付费的响应，也可在满足交付条件时交付已有稿件。受阻且无法完成交付时返回 `limitation`。[运行系统](../topics/runtime.md#conversation-loop) · [主请求构造](../context/agent-loop.md)

### 主决策与工具额度独立

LongDS NYC Task 2 的复跑在第 40 步完成已获准的动作，下一步因主决策额度耗尽而返回 `limitation`。同题早先的成功运行在累计 15 次工具调用后，于第 17 步直接交付 Markdown。把该成功阶段的工具上限设为 15 时，旧主循环会在准备第 17 步前终止，尽管生成已有结果的正文并不占用工具额度。[原两次运行](../problems/longds/nyc-restaurants.md#task-2-与-task-3-对照评测)

DeepSeek Harness 核心在 `agent/pre-step` 返回拒绝时停止开下一步。LongDS 对照用外部扩展拒绝第 41 步。核心单次输出由 `maxTokens` 限制，工具批次另管并发，正常无工具正文可结束。采用其按生命周期边界执行限制的做法，沿用本工程的 Journal、模型次数、累计 token 和工具额度。[主循环固定源码](https://github.com/deepseek-ai/deepseek-harness/blob/2e39e70496aa02986ca6a820c5d497e816b69d7e/packages/core/agent-loop/src/agent.ts#L344-L395) · [对照扩展](../../.tmp/nyc23-20261119/step-limit.mjs)

已接入。

`ConversationBudget` 判断能否发起新主决策，`ConversationService` 先检查已付费原件和待交付旧稿，再在能力物化前检查主决策、累计 token 和截止时间。普通工具额度用尽后，下一主决策只声明仍可执行的动作，工具批次仍在派发边界逐项分配额度。已计入正数额度的目标更新、目标读取及新增核验也不能越过该边界。保留不占用普通工具额度的状态报告、澄清、计划控制和独立委派。配置为零时沿用既有内置目标与核验规则。未就绪的目标及必须新增核验的答案仍经过原交付检查。余额在 Step Context，存在余额的最后一次主决策仍按原 Auto 协议执行。无新增宽限、持久化计数或循环入口。

预定验收为两个原始 Task 2 首轮阶段。对早先成功运行重放第 17 步之前已提交状态，分别使用原 48 次工具额度及与已提交用量相同的 15 次额度。检查正常声明保留、耗尽后无新增计费工具声明、保留正常正文出口和已提交工具结果。用原第 17 步实际回复核对 Markdown 可走原交付路径。对复跑第 40 步之后的状态核对完成的工具回执不丢失，第 41 步没有模型调用。核验或目标未就绪的终态仍受原门禁约束。本次是固定真实阶段的 Offline Eval，完整任务分数独立。

离线回放通过四项。48 次配置下沿原路径交付；15 次配置下保留原来的 15 次工具调用用量和 15 组历史交互，复用第 17 步实际正文完成交付；40 步耗尽时未再物化能力或调用模型，保留已执行动作。已记账的第 17 步回复在决策与工具额度均耗尽时可恢复并交付，本次恢复无新增模型请求。另以第 17 步的完整请求回放 MiniMax，将工具列表缩减为当步仍可用的三个控制工具，并以当前 System Prompt 和末尾预算发出。一次实发用量 23,435 tokens，返回正常 Markdown 正文，无工具调用。两次 Task 2 的整题结果保持原归档。[离线回放](../../.tmp/dsh-budget-20261119/replay-result.json) · [模型回放](../../.tmp/dsh-budget-20261119/model-replay.json)

### BrowseComp-Plus 工具次数对齐

**BCP-BUDGET-1** 允许对话配置显式取消独立的工具总次数限制。BrowseComp-Plus 原配置把 40 步与 40 次工具调用绑定，`773` 在第 23 个模型请求后以 `limitation` 结束，已发生 40 次工具调用。对照方在同一题的 38 步内完成 69 次工具调用，其核心在每步完成后派发本步的工具批次，评测插件在下一步超过 40 时拒绝进入。固定数值如 80 仍会额外截断合法批次。[原始结果](../problems/BrowseComp-Plus/2026-11-26-five-questions.md) · [DeepSeek Harness 固定源码](https://github.com/deepseek-ai/deepseek-harness/blob/4b399c39a6d1479cd84ca591b4d7c88e24d38a96/packages/core/agent-loop/src/agent.ts)

配置加载将 `unlimited` 映射为可空的 `max_tool_calls`，运行装配沿用现有 `LoopBudgetPolicy` 和 `ConversationBudget`。Journal 持续持有已提交用量，预算组件负责决定工具是否因次数耗尽而不可见或拒绝派发。正整数与零保留各自原语义。BrowseComp-Plus 运行配置采用该值，主决策、token 及运行权限沿用该评测的既定设置。无需新增策略、状态、计数或执行入口。

先用原 `773` 的封存用量回放 40 次边界，核对有限额度、零额度和取消计数限制的决策。再从独立新会话复跑一次 `773` 双方，保持原题、索引、模型、Goal 配置与评分。检查实际配置、请求工具声明及超出旧边界的调用，分别记录正式答复和上游评分。达到既定预算或正式终态结束，不追加语义重跑。[复跑入口](../../evals/BrowseComp-Plus/README.md)

## 单次请求与上下文容量

| 约束 | 当前口径 | 依据 |
| --- | --- | --- |
| 模型上下文窗口 | 对声明了容量的服务提供方与模型，发送前估算完整文本请求。估算输入、输出预留与协议预留之和超过窗口时拒绝。输入估算使用规范化后的 ASCII JSON 字节数 | [容量检查](../../src/personal_agent/infra/model_capacity.py) |
| 单次模型输出 | 普通主决策和常规语义核验请求各声明 32,768 token。结构化研究主决策声明 131,072 token，历史摘要声明 8,192 token。最终请求还要通过该模型的输出容量检查。省略输出参数的请求按配置的模型最大输出量预留容量 | [主决策](../../src/personal_agent/application/conversation/service.py) · [语义核验](../../src/personal_agent/tools/interaction_verifier.py) · [历史摘要](../../src/personal_agent/application/conversation/history_compaction.py) |
| 历史压缩 | 主请求的估算输入与两项预留合计达到窗口的 80%，且存在可安全压缩的历史前缀时，尝试生成摘要。主请求构造最多尝试两次压缩，候选须使请求估算输入变小。目标核验另有从结构化模型窗口扣除输出、协议与包装预留后派生的输入额度 | [上下文窗口与历史增长](../topics/context-engineering.md#整体窗口与历史增长的当前边界) · [核验输入额度装配](../../src/personal_agent/orchestration/runtime.py) |
| 工具回执与读搜 | 普通工具回执按序列化后的 UTF-8 体积限为 50 KiB。超限时外置原件并返回有界预览和可用定位。原件续读和搜索窗口另受 20,000 字符限制。网页抓取响应与提取正文分别限 4 MiB 和 16 MiB | [工具回执](../context/tool.md) · [网页正文限额](../../src/personal_agent/application/capture/web_source.py) |

## 时间、重试与服务限流

| 预算 | 作用域与生效方式 | 依据 |
| --- | --- | --- |
| 运行截止与执行秒数 | 绑定 Python 授权或检索实验时，运行记录绝对截止时间。执行命令还要预留执行秒数，已结算命令按实际耗时扣减，未结算命令占用原预留。恢复沿用原截止时间和既有消费 | [对话运行创建](../../src/personal_agent/application/conversation/service.py) · [执行预留与结算](../../src/personal_agent/application/conversation/journal.py) |
| 单次模型请求超时与重试 | 通用 OpenAI 兼容配置默认 30 秒，结构化模型默认 60 秒，示例配置将结构化超时设为 480 秒。两者默认最多 2 次传输重试。主决策的适配器内输出修复额度为 0，非法动作回到主循环修复。内部结构化请求按各自声明使用有限的输出修复 | [环境变量读取](../../src/personal_agent/kernel/config_env.py) · [模型重试](../topics/runtime.md#model-retry) |
| 重复动作修复 | 无成功工具结果或新研究稿件推进时，同一动作、拒绝原因和计划修订下跨两轮出现同类拒绝，运行停止继续修复 | [主循环实现](../../src/personal_agent/application/conversation/service.py) |
| 工具网关 | 工具可独立配置超时、重试及每分钟限流。重试由网关按失败类型和工具策略执行，主循环按进入执行的动作计数 | [工具配置](../../src/personal_agent/kernel/config_models.py) · [执行网关](../../src/personal_agent/governance/gateway.py) |
| Web 请求限流 | 默认每个 API Key 每 60 秒 60 次请求，超限返回 HTTP `429` | [鉴权与限流](../env.md#鉴权限流与-cors) · [限流实现](../../src/personal_agent/adapters/web/auth.py) |

## 专项任务预算

| 任务 | 独立额度与适用范围 | 依据 |
| --- | --- | --- |
| Bash 分析 | 部署授权必填任务总 token 和总执行秒数，跨同一授权对话的多个运行累计。有效 token 余量取单次运行与任务余量的较小值。单次运行截止为该轮开始时间加 `turn_timeout_seconds`（默认 3,600 秒），恢复沿用原截止。单条命令另受自身时限和执行余额约束 | [Bash 授权配置](../env.md#通用-bash-执行许可) · [预算实现](../../src/personal_agent/application/conversation/budget.py) |
| Bash 沙箱 | 单次默认 60 秒、512 MB 内存、1 个 CPU 和 64 个进程，另有临时盘及输出配额。命令限 128 KiB，工作区输入合计限 64 MiB | [沙箱与授权契约](../../src/personal_agent/application/bash_execution/models.py) |
| 检索实验 | 部署声明单次运行时限与累计执行秒数。外层实验进程默认 1,200 秒，候选程序默认 60 秒，两者各有 CPU、内存、进程和输出限制 | [实验额度契约](../../src/personal_agent/application/retrieval_experiment/models.py) · [执行准入](../../src/personal_agent/application/retrieval_experiment/service.py) |
| 独立 Research 与定时简报 | 默认总查询 5 次，其中探索最多 3 次、核证最多 2 次。满意度模型判断最多 1 次，计入预算的工具调用最多 15 次。来源采集配置搜索结果上限为 30 条，单次搜索最多请求 10 条，每次采集最多成功保留 5 篇全文 | [Research 流程](../workflow/research-once-workflow.md#停止与结果状态) · [运行限额](../../src/personal_agent/kernel/contracts/research.py) · [执行实现](../../src/personal_agent/application/research/service.py) |
| 外部 GPT Researcher 委派 | 单次委派时限默认 240 秒，并受子智能体配置的运行时长上限约束。父级等待到子任务终态或委派时限耗尽。远端在途任务默认最多 4 个，可单独配置。父级授权记录还保存 `token_budget` 和 `cost_budget`，默认分别为 4,000 和 1.0。远端提交参数中的额度为可选搜索结果上限 `max_search_results` | [委派提交、预算与恢复](../workflow/gpt-researcher-a2a-workflow.md#提交预算与恢复) · [委派提议](../../src/personal_agent/application/conversation/models.py) · [远端适配](../../src/personal_agent/agents/gpt_researcher_a2a.py) · [委派网关](../../src/personal_agent/agents/gateway.py) |

## 评测中的独立预算

LongDS 的累计 token 额度以整题为单位。正式采集把同一额度用于 Web 的运行设置和 Bash 授权，绑定授权的主循环使用已知跨轮消费计算有效余额，因此单轮没有额外的累计 token 上限。DeepSeek 对照运行器在用户轮次之间检查整题用量。双方各自的 40 次主决策上限以及单次请求窗口、输出和时间规则独立生效。[LongDS 运行说明](../evals/04-running-and-release.md#公开数据集运行) · [预算对照与验收](../optimization/to_verify/longds-analysis.md#对照运行的累计-token-上限)

- **LongDS 生成用量与停止点。** Task 2 的第 31 轮交付后累计 60,053,780 tokens，外层在第 32 轮前停止。DeepSeek Harness 对照也用 60M 的整题额度，在用户轮之间检查。其 SDK 的 `maxTokens` 单独限制每次主请求的输出，token-meter 从已结算的助手事件累计未缓存输入、缓存读写和输出，同一次尝试的更新替换旧样本，后续重试独立计入。LongDS 主模型请求现有 32,768 输出上限，Run 与 Bash 授权继续执行各自的额度。采用对照的整题停止边界与用量分项。[Task 2 轨迹](../../.tmp/nyc23-pressure-20261120/t2/capture/report.json) · [对照运行器](../../.tmp/nyc23-20261119/harness.py#L157) · [token-meter 固定源码](https://github.com/deepseek-ai/deepseek-harness/blob/2e39e70496aa02986ca6a820c5d497e816b69d7e/packages/llm/token-meter/src/usage-projection.ts#L108-L143)
- **记录与归档。** LongDS 以实际 HTTP 发送及配对的 SDK 响应为来源。`known_tokens` 是已知模型总用量，包含总输入和输出。单次优先用服务方总量，缺失时累计已知输入与输出。汇总供停跑、检查点和最终报告使用，缺失的尝试单列。DeepSeek Harness 的适配器将总输入拆为缓存读取、缓存写入和未缓存输入，界面将三项相加得到总输入，缓存命中率按读取量除以总输入计算。LongDS 同步记录总输入、输出和三项输入分量。读取量有效时，按同一公式折算未缓存输入，未报告的写入量在折算中按零处理，原始缓存写入统计仍保留未知和观测次数。已有的未命中输入是总输入减缓存读取，可能包含写入。命中率按同时有有效总输入与缓存读取的请求做 token 加权，覆盖数由未命中输入的 `observed_attempts` 给出。旧报告可继续读取，新增分项以原始回包重算。[用量映射](https://github.com/deepseek-ai/deepseek-harness/blob/2e39e70496aa02986ca6a820c5d497e816b69d7e/packages/llm/llm-pi-ai/src/stream.ts#L17-L31) · [统计展示](https://github.com/deepseek-ai/deepseek-harness/blob/2e39e70496aa02986ca6a820c5d497e816b69d7e/packages/experimental/client-ui-stats/src/client/stats-totals.ts#L14-L29) · [运行与归档](../evals/04-running-and-release.md#公开数据集运行)
- **定向验收。** 只读回放 Task 2 最近一次的 31 轮物理请求和 DeepSeek Harness Task 2 原生用量，按同一口径对齐输入、输出和缓存。校验 Task 2 第 30 轮后余额为正、第 31 轮之后拒绝第 32 轮。用 Task 1 含用量缺口的已封存 HTTP 轨迹核对未知尝试仍保留。对服务方缺总量的字段投影使用同一次实际回包的独立副本验证回退及完整性。定向回放零新模型费用，无需改变题面、评分或生产 Prompt。
- **用量展示验收。** 只读复核 Task 3 双方题面逐字相同的前 25 轮，按原始用量重算总输入、输出、缓存分量和命中率。复用本 Agent 的首次采集段检查报告可读、289 次请求中的 1 次未知仍保留，以及 60,107,747 的已知总量和停止判据仍成立。用同一真实响应的独立副本检查已报告写入的分量守恒。每项执行一次，零新模型调用。[Task 3 原件审计](../../.tmp/nyc3-cost-20261120/report.json) · [首次采集报告](../../.tmp/nyc3-1120/c/report.json)
- **评测运行与评分。** Toolathlon、LongDS 的执行配置由各运行规格和归档记录。LongDS 评分器默认单次输出 32,768 token、单次超时 480 秒、累计 2,000,000 token。评分请求发送前按已知用量加上新请求预留判断是否有余额。[评测运行说明](../evals/04-running-and-release.md) · [LongDS 评分预算](../../evals/longDS/longds_judge_config.py) · [评分准入](../../evals/longDS/longds_judge.py)
- **遗留 Ask 离线评测。** 证据进入模型前默认最多 12 项、5,000 字符。配置入口为 `PERSONAL_AGENT_ASK_CONTEXT_MAX_ITEMS` 和 `PERSONAL_AGENT_ASK_CONTEXT_CHAR_BUDGET`。[Ask 组件配置](../env.md#offline-eval-的遗留-ask-组件配置)
