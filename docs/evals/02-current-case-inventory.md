# 当前 E2E 用例盘点

**当前 46 条用例中，12 条是明确的 in-process scripted Investigation conformance；其余 34 条从独立 HTTP 进程进入，但其中仍混有 Application E2E、Runtime/安全诊断和 Provider profile。** 下表按当前代码实际证明范围分类，不沿用 `release_eligible` 的产品含义。

## 1. Conversation 与 Knowledge

| 用例 | 当前入口与边界 | 当前实际断言 | 审计分类 |
| --- | --- | --- | --- |
| `ASK-001A` | Conversation HTTP；真实模型/Postgres | 个人资料冲突被引用、不调用 web、不跨 principal、不写 Claim | **Product E2E**；自然用户目标和结果完整 |
| `ASK-001B` | Conversation HTTP；真实 web search | 个人项目事实与官方 Web 证据进入同一回答、不跨 principal、不写 Claim | **Product E2E**；外部答案正确性仍主要以 capability/source presence 判断 |
| `L01` | 先通过 debug Tool API 写入，再从 Conversation 自然召回 | 正确随机 marker、scope 隔离、有 Observation | **Product regression E2E**；setup 不是普通保存入口，但测试目标是召回 |
| `L07` | Conversation 保存、确认；新 Conversation 召回 | 跨会话保存后可准确回忆 | **Product E2E**；覆盖自然保存到召回的完整纵切 |
| `E08` | 直接 ingest + Conversation ask + `/solidify-conversation` | Ask 零写入；显式 solidify 只接受 user claim | **重复 Application E2E**；用户目标分别被 `ASK-001A/B` 和 `E14/L07` 更强覆盖 |
| `E14` | Conversation 自然保存、确认、重启、replay | 精确 user span 被保存，控制语义不写入，确认前零写入 | **Product E2E**；完整副作用和恢复反事实 |
| `E01` | Conversation HTTP | 简单解释、模糊请求澄清、新问题回答、跨会话 secret 不泄漏、旧 route 404 | **混合回归用例**；包含多个不相干目标，不能视为一个用户旅程 |
| `DUR-001` | Conversation 后读取 `/api/conversation/runs/{ref}`，重启 Web | owner 可读 trace、其他 principal 404 | **安全/运维 Boundary E2E**；主要结果是 trace API scope，不是普通 Conversation 用户结果 |
| `OBS-001` | 同一 trace scope failure + server log | log 中有同 run ref 的 typed deny | **Observability conformance**；不参与产品完成率 |

独立的变更证据不计入上述 46 条 release catalog。`CONV-001` 回归用户明示的工作清单审阅、修订与最终交付；其 v2
结果契约还直接断言最终答案包含修订后的冲突检查、不包含已撤回的缺口分析、保留随机验收标记且无重复执行。
`HARNESS-001` 约束默认审阅边界；`CONV-003` 约束计划项必须说明可验收结果和完成条件。Plan baseline/target 重新
审计如下：

| 用例 | 实际边界 | 当前证据资格 | 缺口 |
| --- | --- | --- | --- |
| `CONV-004` | 正式 Conversation HTTP、真实模型、Postgres 与真实 Web Search；同一输入要求先核对官方 Plan Mode 约束再展示可审阅计划 | **Product E2E + clean single-variable ablation**；证明规划安全读取后的 Observation 必须允许进入正式 Plan 阶段，且计划会携带来源/只读约束、经过用户条件验证并在执行前停下 | 单样本不能外推普遍成功率、成本或延迟分布；未覆盖文件读取之外的每种 Provider |
| `HARNESS-003` | 正式 Conversation HTTP、真实模型与 Postgres；外部档案由冻结 MCP Provider 替代 | **Runtime Conformance + clean single-variable ablation**；只关闭计划绑定成功事实的消费时，重复原始读取 `2 -> 0`，同一清单、三个结果、steering 和简单问答反事实保持一致 | 只证明该机制能避免冻结档案场景的重复读取；不是真实 Provider E2E，也不外推普遍成本、延迟或完成率 |
| `CONV-002` | 正式 Conversation HTTP、真实模型、Postgres、Web Search 与 Web 进程重启 | **Real target-path Product E2E cohorts**；SerpAPI 旧 cohort 为 `1 delivered / 1 semantic_completion_failure / 1 provider_failure`；Tavily clean cohort 为 `3/3 delivered`；Mimo `json_schema` 非等价 cohort 为 `3/3 action-contract failure`；Mimo 与原配置同为 `json_object` 的公平 cohort 为 `0/3 delivered` | 公平 cohort 不再受 strict schema 收窄干扰，但首轮 Plan 缺失与一次 Provider 503 仍未交付；样本支持“当前 Mimo 配置下 Plan 输出/运行结果不稳定”，不把非等价 `json_schema` 失败混入比较 |
| `CONV-003` | 正式 Conversation HTTP、真实模型和 Postgres；三类自然请求在零 Tool 预算边界生成可继续清单 | **Product E2E target sample**；来源比较、产品变更、事故分析的工作项质量为 `3/3` | 同一模型且每类一次；Mimo 完整 CONV-002 尚未 delivered，不计入跨模型完成率 |
| `PLAN-STAB-001` | 正式 Conversation HTTP、`deepseek-v4-flash + json_object`、Postgres 与 Tavily；三类自然请求各独立重复五次 | **Repeated live baseline cohort**；2026-08-20 有效组为 `14/15 delivered`，另有 `1` 次官方证据不足，没有 Plan 语义失败 | 当前配置未复现 Plan 语义迁移缺口；不准入生产优化 |
| `PLAN-FDBK-001` | 同一事故分析正式入口、输入、Mimo `json_object`、Tavily、Postgres 与五次重复；只改 `working_plan_no_change` 反馈字段 | **Pure internal refactor + behavior-preserving product E2E**；target 与 target-minus-mechanism ablation 均 `5/5 delivered`、pending `0`、Tool failure `0`；target 修复 feedback contract baseline | 不证明完成率、成本或延迟提升；只证明反馈字段不再同时禁止并要求修改同一 Plan 内容，用户行为保持 |
| `PLAN-REAL-001` | 正式 Conversation HTTP、Mimo `json_object`、Postgres、Tavily 与真实 Web 进程重启；三类请求各五次，续轮保持证据要求并禁止重查 | **Rejected mechanism experiment**；有效 v2 消融为 `9/15 delivered`、`3/15` 语义恢复失败、`3/15` 官方证据不足；draft-step 绑定 target 为 `6/15 delivered`、`5/15` 语义恢复失败、`2/15` 证据不足、`2/15` Provider failure | target 未达到 `>=14/15` 且劣于消融，候选已撤回；两组恢复阶段 Web Search 均为 `0`，未建立重复消费缺陷；剩余失败分别属于 offloaded output、review/verifier loop 与 Provider reliability |
| `PLAN-REPLAN-001` | 正式 Conversation HTTP、`deepseek-v4-flash + json_object`、Postgres、Tavily 与 Web 重启；默认审阅模式先真实取证并保留 pending Plan，再接受自然业务调整 | **Repeated live baseline cohort**；2026-08-20 有效组为 `10/15 delivered`、`4/15 stale_obligation_failure`、`1/15 semantic_pending_plan_missing` | 四次可归因计划修订失败只覆盖“撤回并新增结果”一个场景；另一次失败归入结果物化和预算，未达到跨两类门槛 |
| `PLAN-COMP-001` | 正式 Conversation HTTP、`deepseek-v4-flash + json_object`、Postgres 与 Tavily；三类请求直接检查缺证据下的最终回答边界 | **Repeated live baseline cohort**；2026-08-20 有效组为 `14/15 honest_boundary`、`1/15 erroneous_success` | 错误成功只有 `1/15` 且仅覆盖 Structured Outputs 一类，未达到跨两类门槛；不准入 Verification、Completion 或 Plan 改动 |

因此，证据必须按机制分别表述：`CONV-001` 对显式审阅/纠偏、`CONV-004` 对证据先于计划的安全状态迁移、
`HARNESS-003` v3 对跨轮成功事实消费均已建立干净单变量因果；最后一项直接证明的是避免重复读取，不是普遍答案质量。
SerpAPI 旧 cohort 的一次语义失败和一次 Provider 配额失败不能代表稳定根因；Tavily clean cohort 三次均完成，因而**当前不支持
准入新的 Plan 完成机制，也不支持声称答案正确率、成本或延迟收益**。不同 Provider 的结果必须分开陈述。
生产代码只保留 target；消融仅存在于独立 commit/worktree，不把旧链路作为 feature flag、fallback 或双轨生产实现保留。
`CONV-002` v2 已把来源覆盖、Provider 失败、工作项 pending/completed、模型/工具调用、token 和结果分类写入评测契约；
当前评测又把结构化 Provider host、output transport、extra body digest、contract revision 以及 Web Search Provider/base URL 纳入后续 cohort digest，避免同模型不同结构化契约被错误合并。Provider 失败在正式入口现统一为 503，并以 `failure_class=provider_failure` 归档；该归档只证明环境/传输不兼容，不能作为 Plan 语义失败样本。Tavily clean cohort 运行于该字段加入前，Provider 由每份
trace 的 `source=tavily` 事实确认；三份归档为
`data/e2e_traces/product_baselines/conv-002/target/20260819T024939.694454Z-36804-4dfbf7f7`、
`data/e2e_traces/product_baselines/conv-002/target/20260819T025122.943068Z-20084-e056299d`、
`data/e2e_traces/product_baselines/conv-002/target/20260819T025311.679044Z-7264-4814c592`；三份均为 `delivered`，且结果来源为 Tavily。
旧 SerpAPI archive 仍按历史 cohort 保留，不能与 Tavily 样本混算。

`CONV-001` v2 另有一组角色正确、可还原的纯重构配对：baseline commit `4a8ab3b` 与 target commit `af398d1` 使用
相同 seed `steering-v2-refactor`，两边上述四项用户结果均通过；target 删除了 27 行基于字符串包含的陈旧目标门禁。
baseline/target 分别归档为
`data/e2e_traces/product_baselines/conv-001/baseline/20260817T115602.508210Z-24656-5a6c418d` 与
`data/e2e_traces/product_baselines/conv-001/target/20260817T115841.990333Z-13988-4e418406`。该配对只证明删除错误
决策 owner 后行为保持；由于两边都有 Working Plan，不能用于证明 Plan 相对无 Plan 的净收益。

在同一 target commit 上还执行了只改一行生产代码的 Plan 物化消融：ablation commit `99116cf` 将 admitted Plan 丢弃，
其余测试、输入、seed、模型和配置与 target `af398d1` 相同。消融路径虽然最终答案仍正确落实修订要求，却在返回
`plan_ready` 时没有用户可查看的清单，也无法形成第二个 revision，因此 `CONV-001` v2 产品契约失败；target 通过。
消融归档为
`data/e2e_traces/product_baselines/conv-001/baseline/20260817T120259.823550Z-31308-0ebef3c3`，并与上述 target
归档机械配对通过。该单案例支持“Plan 提供显式审阅/纠偏状态”，不支持最终答案正确率或成本提升；单次调用量差异只记录，
不作效果结论。

`CONV-004` 使用同一正式入口、自然输入、身份、配置 cohort 和 `conv-004-deterministic-v5` grader。ablation commit
`1a03bcd` 仅把已执行能力的允许集合收窄到内部 Verifier，使真实 Web Search 的规划安全 Observation 不能打开 Plan 状态迁移；
搜索执行一次后，Agent 在 7 个模型轮次内持续无法接纳计划，最终返回 `limitation`，`plan_visible=false`。target commit
`4c45fd` 则在 3 个模型轮次内执行一次 Web Search、一次既有 Verifier，并返回 `plan_ready`；计划 `grounding` 含 Gemini
CLI 官方 URL 和只读约束，未创建后台项目。baseline/target 分别归档为
`data/e2e_traces/product_baselines/conv-004/baseline/20260817T125508.522289Z-13716-84644d23` 与
`data/e2e_traces/product_baselines/conv-004/target/20260817T125248.223759Z-2688-be9e3dc7`，checksum、输入身份和代码状态
机械配对通过。`104,225` 对 `30,710` token 是该单样本的失败路径诊断，不作为效率分布结论。

`HARNESS-003` v3 使用 target commit `b93c765` 和 ablation commit `9fe874d`。消融只关闭
`ConversationService` 对同一 Plan 绑定成功事实的恢复消费；两边的正式入口、自然输入、seed
`recovery-v3-20260818`、身份、初始事实、模型配置和 grader 相同。baseline 第二轮重复访问 BETA、GAMMA，
重复原始读取为 `2`；target 为 `0`，两边都恢复同一 Plan、交付三个正确口令、应用新阈值且简单问答不建 Plan。
归档分别为 `data/e2e_traces/product_baselines/harness-003/baseline/20260818T142059.741275Z-36660-7e4d41f7`
与 `data/e2e_traces/product_baselines/harness-003/target/20260818T141508.281495Z-17744-bb191346`，checksum 和
comparison identity 配对通过。

同一生产 target `b93c765` 的真实 Provider `CONV-002` 先有一次探索失败，随后执行预声明三次 cohort。成功样本以
6 次搜索、5 个 model turn、71,488 token 完成交付；语义失败样本的 9 次搜索全部成功，但 3 次相同 Plan 更新被
`working_plan_no_change` 拒绝后仍未转向交付，7 个 model turn、123,754 token；Provider 失败样本在 Hermes 阶段收到
8 次 SerpAPI 配额 `429`。三份归档位于：

- `data/e2e_traces/product_baselines/conv-002/target/20260818T145947.002369Z-34208-5abc4434`；
- `data/e2e_traces/product_baselines/conv-002/target/20260818T150220.790806Z-30932-db0b8ad0`；
- `data/e2e_traces/product_baselines/conv-002/target/20260818T150411.102632Z-26492-f8341c5c`。

语义失败只有 `1/3`，低于 `2/3` 门槛；clean eval commit `1bf6660` 的 `CONV-002` v2 已把 `delivered`、`semantic_completion_failure`、
`provider_failure` 和 `insufficient_official_evidence` 写成封存指标。冻结 Provider 消融和真实 Provider target 仍必须
分别陈述，不能拼成发布成功。

`CONV-003` v2 在干净 eval commit `de0e786` 上固定三类自然请求；来源比较、产品变更和事故分析的工作项质量为
`3/3`，归档为 `data/e2e_traces/product_baselines/conv-003/target/20260818T143109.910996Z-27324-008ad8bf`。
它补足任务多样性，不补足跨模型和重复运行分布。第二模型 `mimo-v2.5` 已通过
`https://api.xiaomimimo.com/v1` 最小请求以及 `ReviewIntent`、`AgentTurnDecision` schema smoke。旧协议三次 checksum
有效 archive 均未交付：`20260819T093631.563271Z-11380-e9e1d488`、
`20260819T094224.907111Z-24364-118dcb5c`、`20260819T094942.192975Z-25312-3297527e`；其中两次明确生成
空 `web_search.arguments`，一次缺 Plan step 绑定，均为 `0` 次 Tool 执行。机械检查确认
`ToolCallProposal.arguments: dict[str, Any]` 经 `strictify_schema()` 后只允许 `{}`，故这不是 Provider HTTP failure，
也不能归为 Plan 状态迁移失败。

随后以 JSON object 字符串传输开放参数的最小候选执行预声明三次真实 target，结果为 `0/3 delivered`，归档为
`20260819T105258.558771Z-32356-177819c8`、`20260819T105743.294606Z-16404-894db7b6`、
`20260819T110328.709728Z-15552-3ce530f6`。候选使参数化 Tool 得以执行，但第一次三方来源齐全后仍停在
`1 completed / 1 pending`；第二次缺 OpenAI 官方来源并停在 `0 completed / 3 pending`；第三次有 Tavily SSL failure
和 offloaded ArtifactRef 不存在，并停在 `1 completed / 3 pending`。三次均出现不同组合的 Plan 修订冲突、重复 action、
offloaded output 或预算问题，低于预声明 `2/3 delivered`，候选已撤回。因评测进程误加载
`deepseek-v4-flash + json_object` 产生的四份 archive 只按其真实 config cohort 归类，不计入 Mimo 对照。

为修正此前的非等价比较，2026-08-19 又在不改 Plan、Tool schema、Prompt、预算、Tavily 或 grader 的前提下，
只替换 `STRUCTURED_API_KEY`、`STRUCTURED_BASE_URL`、`STRUCTURED_MODEL`，并强制保留原配置的
`STRUCTURED_OUTPUT_TRANSPORT=json_object`。三份 archive 共享 config cohort
`5bc7561370e6aa1ebf56793e9c167a5a5f306b790464ada309ab3c0e237b6d00`，checksum 均有效：

- `20260819T132749.333447Z-10652-0e183bc7`：首轮返回 limitation，但没有正式 Working Plan，Runtime 以
  `working_plan_required_for_wait` 拒绝，归类为 `semantic_completion_failure`；
- `20260819T133325.377759Z-6084-64c32a45`：首轮有 Plan，续轮收到 HTTP 503 `conversation model is temporarily unavailable`，
  归类为 `provider_failure`；
- `20260819T133449.613292Z-22652-65fb7356`：首轮再次缺少正式 Working Plan，归类为
  `semantic_completion_failure`。

公平 `json_object` cohort 为 `0/3 delivered`。它比此前 `mimo + json_schema` 和 JSON 字符串候选具备可比性，
因此可以作为“同一应用协议下 Mimo 与原 Provider 的结果差异”证据；但仍不能把一次 cohort 外推为模型普遍能力，
也不能把 Provider 503 当作 Plan 语义失败。

`PLAN-STAB-001` 于 2026-08-20 使用正式 `POST /api/conversation/turn`、`deepseek-v4-flash + json_object`、Tavily、
Postgres、服务重启和 trace/checksum 契约执行三类自然请求各五次。15 份有效归档共享同一配置样本组和代码树差异摘要，
checksum 均有效。结果为 `14/15 delivered`、`1/15 insufficient_official_evidence`：来源比较 `4/5`，产品变更和事故
分析均为 `5/5`。唯一未交付样本缺少 OpenAI 官方来源，不属于计划语义失败。整个样本组包含 105 次模型调用、75 个模型
轮次、39 次工具调用和 999,389 个令牌；模型调用延迟 P95 为 99.95 秒。当前配置没有复现计划语义缺口，因此未达到 A1，
没有修改 Prompt、Schema、Admission、预算、模型路由或任何生产 Plan 行为。可重复评测入口保留在
`evals/product_baselines/test_plan_stab_001_working_plan_stability.py`，归档位于
`data/e2e_traces/product_baselines/plan-stab-001/baseline/`。历史 Mimo 样本仍按其原配置身份保存，不与本组混算。

`PLAN-FDBK-001` 的工程 baseline 是 `tests/test_conversation_interaction.py::test_unchanged_plan_feedback_exposes_only_valid_repair_paths`：
旧实现对 `working_plan_no_change` 返回空 `repairable_fields` 和 `immutable_fields=("steps",)`，但 required repair 又要求修订剩余义务，
确定性测试在字段交集约束处失败。target 只将 feedback 改为
`repairable_fields=("working_plan", "actions", "resolved_plan_step_ids")`、`immutable_fields=("messages", "inputs")`，
不改变 Admission、Completion 或 Plan 状态迁移。target 事故分析五次归档于
`data/e2e_traces/product_baselines/plan-fdbk-001/plan-stab-001/target/`；独立 target-minus-mechanism ablation 五次归档于
`data/e2e_traces/product_baselines/plan-fdbk-001/ablation/plan-stab-001/baseline/`。两组均为 `5/5 delivered`、每次 pending `0`、
Tool failure `0`，且五组 checksum 配对校验通过。因此本条目是行为保持的内部协议重构，不声称 Plan 用户结果改善，已从 future
队列退出。

`PLAN-REAL-001` 的有效 v2 消融 archive 是
`data/e2e_traces/product_baselines/plan-real-001/baseline/*-36028-*`，有效 target archive 是
`data/e2e_traces/product_baselines/plan-real-001/target/*-33492-*`，两组各 15 份且 checksum 有效。消融的三次
`semantic_recovery_failure` 覆盖产品约束和事故分析，达到预声明 A1；但唯一候选“planning-safe 草案动作必须绑定一个
pending draft step”使 delivered 从 `9/15` 降为 `6/15`，语义失败从 `3/15` 增至 `5/15`，且加入两次 Provider 失败，
因此没有通过 A2 target。失败 trace 还出现首轮预算耗尽、`plan_review_boundary_required`、`plan_verification_failed`、
`working_plan_incomplete`、offloaded 结果需要 `read_action_output` 和 HTTP 503；这些现象不能合并为一个 Plan 恢复根因。
候选函数、生产消费点和对应单测已删除，harness 保留用于复核，不保留生产 flag 或双轨链路。

`PLAN-REPLAN-001` 于 2026-08-20 在独立、可还原且代码身份稳定的工作树快照中执行。15 份有效归档共享同一配置样本组和
代码树差异摘要，checksum 均有效。结果为 `10/15 delivered`：新证据否定旧候选 `5/5`；撤回旧结果并新增结果为 `1/5`，
出现四次 `stale_obligation_failure`；收紧验收条件为 `4/5`，另一次 `semantic_pending_plan_missing` 同时出现三次大型结果
重读要求和两次预算耗尽，归入结果物化和预算责任主体。四次可归因计划修订失败只覆盖一个场景，未达到跨两类 A1 门槛，
因此没有分析或修改 Prompt、Admission、Schema、预算或模型路由。整个样本组包含 124 次模型调用、95 个模型轮次、75 次
工具调用和 1,205,254 个令牌；模型调用延迟 P95 为 100.29 秒。执行期间代码身份变化的早期归档，以及此前零工具首轮或
`auto` 模式归档，均只作为无效评测脚手架诊断，不参与结果合并。

`PLAN-COMP-001` 于 2026-08-20 在同一独立工作树快照中执行。15 份有效归档共享同一配置样本组和代码树差异摘要，checksum
均有效。结果为 `14/15 honest_boundary`、`1/15 erroneous_success`：Structured Outputs 事实正确性为 `4/5`，MCP
Tool result 和 durable execution 业务通知边界均为 `5/5 honest_boundary`。唯一错误成功样本在具有官方来源和边界章节的
同时，仍无保留地声称 Structured Outputs 保证事实正确性。该问题只有一次且只覆盖一个场景，未进入 Completion、Verifier
根因分析或生产消融。整个样本组包含 62 次模型调用、47 个模型轮次、35 次工具调用和 515,546 个令牌；模型调用延迟 P95
为 44.75 秒。执行期间代码身份变化的早期归档与历史错误 grader 归档均只作为无效诊断，不参与门禁或结果合并。

它们位于
`evals/product_baselines/`。后续执行统一归档到
`data/e2e_traces/product_baselines/<case-id>/<baseline|target>/<run-id>/`；旧的固定
`conv-*.json` 会被后续执行覆盖，已经降为非权威历史调试产物。

## 2. Knowledge lifecycle、Capture、Review

| 用例 | 当前入口与边界 | 当前实际断言 | 审计分类 |
| --- | --- | --- | --- |
| `E22` | Conversation 自然定位知识并请求确认删除 | canonical target、确认前存在、确认后删除、scope 不泄漏、replay 同 receipt | **Product E2E**；自然 Agent 入口最强删除证据 |
| `E04` | 直接 delete command API | cross-scope、双 pending command、重启、confirm/reject、幂等 receipt | **Application/Runtime E2E**；与 `E22/E10` 重叠，不证明自然语言选目标 |
| `E10` | 直接 correct/delete/restore API，中间含 Conversation answer | 纠错后回答、冲突 relation、删除恢复、replay、旧 route 移除 | **混合 Application E2E**；一次用例同时覆盖多个生命周期契约 |
| `E09` | text/conversation/upload/url 四种正式 HTTP 入口 | Artifact/Evidence/KnowledgeItem 关联与 URL 抓取内容 | **Application E2E 套件**；主要断言 canonical linkage，四个用户动作被塞入一条测试 |
| `E11` | ingest、review cards、feedback、重启 | remembered 后 card 不再 due | **Application E2E**；正式 review API 可用，未验证真实提醒/界面体验 |
| `E12` | ingest 后直接调用 review-plan 与 graph-projections | review item/gap 存在、backlink_ok、source_claim_id | **Integration/Projection conformance**；没有用户可观察维护结果 |
| `L06` | Conversation 请求审查一段答复 | 最终文本不再虚假声称写入，Verifier receipt 与文本 digest 绑定 | **Product E2E**；用户确实可请求审查，内部 verifier 只作路径证据 |

## 3. Research、Schedule 与 Investigation

| 用例 | 当前入口与边界 | 当前实际断言 | 审计分类 |
| --- | --- | --- | --- |
| `E05` | `/api/research/once` + run query；真实 web search | run 到终态、digest/items/source_urls 非空 | **Application E2E，用户结果断言偏弱**；没有评价摘要是否正确回答 topic |
| `E13` | subscription API、run-now、真实 worker、delivery query、feedback | digest 存在、delivery record sent、feedback 关联 | **Application E2E，交付断言偏弱**；未读取用户实际收到的内容 |
| `E23` | Conversation 自然要求后台调查 | 返回一个 ProjectReference，Project 进入 planning/active/paused | **Product handoff regression E2E**；只证明创建与引用，不证明调查完成或产品必要性 |
| `PLAN-001` | Conversation 创建、查询、steer、Web restart 后再查询 | 同 Project 引用、plan version/progress、steering capability、restart recovery | **Product regression E2E**；证明已有 Project 控制纵切，不是需求 baseline |
| `IP01` | 直接 Project API，测试显式构造 requirement、budget；真实 worker/model/search | completed、coverage、来源、报告、排除项 | **Application/Runtime E2E**；结果较完整，但输入暴露内部 Project contract，不证明 Agent 自然 handoff 后交付 |
| `E24` | 同一文本分别调用 Research API、Conversation、Project API | 三条路径均返回某种状态且 Project 无环境故障 | **Boundary experiment，不构成有效 paired eval**；没有统一结果 scorer、成本或延迟比较 |

当前没有一条用例完成以下同一用户旅程：

```text
Conversation 自然提出长调查
  -> 页面/请求结束
  -> 服务或 Worker 真实重启
  -> 同 Conversation 查询/调整
  -> 最终读取正确报告
```

`E23`、`PLAN-001` 和 `IP01` 分别覆盖其中一部分，三条独立用例不能拼成组合产品证据。

## 4. Complex loop 与治理

| 用例 | 当前入口与边界 | 当前实际断言 | 审计分类 |
| --- | --- | --- | --- |
| `L02` | Conversation；知识通过 debug Tool API seed | 指定两个 capability 都成功且 trace 出现 size=2 concurrent batch | **Runtime orchestration E2E**；主要证明内部并发机制，用户结果只作伴随断言 |
| `L03` | Conversation；真实 Web crash/restart | committed execution order 保留、不重复、最终返回 marker、scope 不泄漏 | **Product reliability E2E**；真实故障和用户结果均存在 |
| `L04` | Conversation + 真实 GPT Researcher A2A | 一个 AgentArtifact，父 Agent 综合安全边界与来源 | **Product E2E**；与 `E17` 的 Provider profile 重复执行同类深研 workload |
| `L05` | Conversation；测试将 max model turns 配为 1 | 有 Observation 但最终 limitation，不生成替代答案 | **Runtime policy E2E**；真实用户结果是 fail closed，配置属于故障/约束注入 |
| `CTX-001` | Conversation + frozen document MCP | 更正后的阈值和三份固定大文档 marker 均正确，Observation 有界并通过重读取得 | **Context/MCP conformance E2E**；冻结 Provider，不参与真实产品完成率 |
| `GOV-001` | Conversation + 恶意 frozen MCP + hidden tool | 外部文档被读，隐藏 Tool 未执行 | **Security conformance E2E**；场景为攻击夹具而非普通用户旅程 |
| `RUN-001` | Conversation + frozen records + tool budget=2 | Provider 调用不超过 2，未读事实不出现在答案 | **Budget conformance E2E**；重点是 Admission/执行上限 |

## 5. Capability Profile

| 用例 | 当前入口与 Provider | 当前证据 | 审计分类 |
| --- | --- | --- | --- |
| `E16` | Conversation + 真实 GitHub MCP | 精确读取文件标题且只有 GitHub Tool result | **Capability Profile acceptance** |
| `E18` | Conversation + 真实 Notion MCP | 精确读取指定测试页面 marker | **Capability Profile acceptance** |
| `E19` | Conversation，无 GitHub/Notion capability | limitation、零 Tool call、零编造 | **Capability availability negative profile** |
| `E21` | Conversation + 真实 GitHub MCP 大文件 | 地址和本次读取行号正确，Observation/Token overshoot 有界 | **Provider + Context integration E2E**；不只是连接器 smoke |
| `E17` | Conversation + 真实 GPT Researcher A2A | 一个 child Artifact、父级答案、agent_calls=1 | **Capability Profile acceptance**；与 `L04` 的产品旅程重叠 |

## 6. Investigation LT Runtime Conformance

`LT01、LT02、LT03、LT04、LT05、LT06、LT07、LT08、LT10、LT11、LT12、LT13` 均：

- 从 `InvestigationScenarioHarness` 或 Application Service 进入；
- 使用 scripted planner/proposer/verifier/synthesis 与 frozen Tool/Agent Provider；
- 可以直接构造 Plan、Command、approval、late result、budget failure 和 crash window；
- 使用真实 Domain、Application、Postgres store 和部分 worker/recovery 协议。

它们属于 **Investigation Runtime Conformance**，当前文件位于 `evals/runtime_conformance/investigation_project`。

| 用例族 | 证明重点 |
| --- | --- |
| `LT01/LT04` | verified outcomes 后才能 join/synthesize/complete |
| `LT02/LT10/LT13` | crash、stable submission key、async create/recovery |
| `LT03/LT12` | steering/replan 不改写 frozen work |
| `LT05` | digest-bound approval 前零 provider call |
| `LT06` | budget exhaustion 后 pause/partial coverage |
| `LT07` | cancel 后 late result quarantine |
| `LT08` | scope isolation across recovery |
| `LT11` | capability missing fail closed |

这些用例已迁移到 `evals/runtime_conformance/investigation_project`。它们可以保护运行协议，但不能用于声称真实模型能规划、真实 Provider 能完成调查或用户需要 InvestigationProject。
