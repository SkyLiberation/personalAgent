# 运行预算总结

对话运行按单次用户请求累计主模型决策、工具调用、子智能体委派和 token 用量。单次模型请求另受上下文窗口和输出额度约束。启用 Python 分析、检索实验或独立 Research 时，还会叠加对应的任务预算。本文根据 2026-11-11 工作树的源码与配置整理，运行结果见[评测盘点](../evals/02-current-case-inventory.md)。

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
- **工具和委派先准入再分配。** 批次按动作顺序分配余额，超额动作收到 `budget_exhausted`。正数工具额度耗尽会停止新的主决策。工具额度设为 `0` 时，普通工具派发被拒绝，主模型仍可生成无工具回答。适用的运行时核验活动使用自身的准入分支。[主循环实现](../../src/personal_agent/application/conversation/service.py) · [预算实现](../../src/personal_agent/application/conversation/budget.py)
- **预算耗尽时保留已有结果。** 达到决策、工具或 token 停止条件后，运行可恢复已付费的响应，也可在满足交付条件时交付已有稿件。需要新增模型或执行才能继续时，运行按预算关口停止，预算终态为 `limitation`。开启 `low_budget_warning` 时，至少完成一轮主决策且 token 余量大于零并低于有效额度的 10%，下一次主决策会收到交付提醒。[运行系统](../topics/runtime.md#conversation-loop) · [模型输入与低余额提醒](../context/agent-loop.md)

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
| Python 分析 | 部署授权必填任务总 token 和总执行秒数，跨同一授权对话的多个运行累计。有效 token 余量取单次运行与任务余量的较小值。单次运行截止取开始后 `turn_timeout_seconds`（默认 3,600 秒）和授权到期时间的较早值 | [Python 授权配置](../env.md#通用-python-执行许可) · [预算实现](../../src/personal_agent/application/conversation/budget.py) |
| Python 沙箱 | 单次执行默认 60 秒、512 MB 内存、1 个 CPU 和 64 个进程，另有临时盘、标准输出和标准错误配额。程序限 128 KiB，输入最多 32 项，合计限 64 MiB | [沙箱与授权契约](../../src/personal_agent/application/python_execution/models.py) |
| 检索实验 | 部署声明单次运行时限与累计执行秒数。外层实验进程默认 1,200 秒，候选程序默认 60 秒，两者各有 CPU、内存、进程和输出限制 | [实验额度契约](../../src/personal_agent/application/retrieval_experiment/models.py) · [执行准入](../../src/personal_agent/application/retrieval_experiment/service.py) |
| 独立 Research 与定时简报 | 默认总查询 5 次，其中探索最多 3 次、核证最多 2 次。满意度模型判断最多 1 次，计入预算的工具调用最多 15 次。来源采集配置搜索结果上限为 30 条，单次搜索最多请求 10 条，每次采集最多成功保留 5 篇全文 | [Research 流程](../workflow/research-once-workflow.md#停止与结果状态) · [运行限额](../../src/personal_agent/kernel/contracts/research.py) · [执行实现](../../src/personal_agent/application/research/service.py) |
| 外部 GPT Researcher 委派 | 单次委派时限默认 240 秒，并受子智能体配置的运行时长上限约束。父级等待到子任务终态或委派时限耗尽。远端在途任务默认最多 4 个，可单独配置。父级授权记录还保存 `token_budget` 和 `cost_budget`，默认分别为 4,000 和 1.0。远端提交参数中的额度为可选搜索结果上限 `max_search_results` | [委派提交、预算与恢复](../workflow/gpt-researcher-a2a-workflow.md#提交预算与恢复) · [委派提议](../../src/personal_agent/application/conversation/models.py) · [远端适配](../../src/personal_agent/agents/gpt_researcher_a2a.py) · [委派网关](../../src/personal_agent/agents/gateway.py) |

## 评测中的独立预算

- **评测运行与评分。** Toolathlon、LongDS 的执行配置由各运行规格和归档记录。LongDS 评分器默认单次输出 32,768 token、单次超时 480 秒、累计 2,000,000 token。评分请求发送前按已知用量加上新请求预留判断是否有余额。[评测运行说明](../evals/04-running-and-release.md) · [LongDS 评分预算](../../evals/longDS/longds_judge_config.py) · [评分准入](../../evals/longDS/longds_judge.py)
- **遗留 Ask 离线评测。** 证据进入模型前默认最多 12 项、5,000 字符。配置入口为 `PERSONAL_AGENT_ASK_CONTEXT_MAX_ITEMS` 和 `PERSONAL_AGENT_ASK_CONTEXT_CHAR_BUDGET`。[Ask 组件配置](../env.md#offline-eval-的遗留-ask-组件配置)
