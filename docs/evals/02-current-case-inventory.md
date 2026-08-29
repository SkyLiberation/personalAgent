# 当前 E2E 用例盘点

> 2026-08-26 更新：`InvestigationProject` 已因缺少需求 baseline 且正式结果为 `0/20 delivered` 被撤回。下文仍出现的 `E23`、`PLAN-001`、`IP01`、`LT*` 与 `INVESTIGATION-*` 行只用于解释历史归档，不属于当前可执行矩阵或产品能力。

**当前目录有 28 条用例：9 条 Product E2E、8 条 Application E2E、7 条 Runtime Conformance 和 4 条 Capability Profile。** 其中 9 条进入 release selection，19 条进入 diagnostic selection；横切验证套件只复用既有节点和密封 Trace，不增加 case 数量。

## 1. Conversation 与 Knowledge

| 用例 | 当前入口与边界 | 当前实际断言 | 审计分类 |
| --- | --- | --- | --- |
| `ASK-001A` | Conversation HTTP；真实模型/Postgres | 个人资料冲突被引用、不调用 web、不跨 principal、不写 Claim | **Product E2E**；自然用户目标和结果完整 |
| `ASK-001B` | Conversation HTTP；真实 Web search | 个人项目事实与 OpenAI 官方 URL 进入同一回答、不跨 principal、不写 Claim | **Product E2E**；不再把固定工具名当作用户结果，窄范围路由由横切套件独立判断 |
| `L01` | 先通过 canonical Knowledge ingest 写入并核对 EvidenceSpan，再从 Conversation 自然召回 | 正确随机 marker、scope 隔离、有 Observation | **Product regression E2E**；准备步骤直接验证 canonical 事实就绪，测试目标是召回 |
| `L07` | Conversation 保存、确认；新 Conversation 召回 | 跨会话保存后可准确回忆 | **Product E2E**；覆盖自然保存到召回的完整纵切 |
| `E14` | Conversation 自然保存、确认、重启、replay | 精确 user span 被保存，控制语义不写入，确认前零写入 | **Product E2E**；完整副作用和恢复反事实 |
| `E01` | Conversation HTTP | 简单解释、模糊请求澄清、新问题回答、跨会话 secret 不泄漏、旧 route 404 | **混合回归用例**；包含多个不相干目标，不能视为一个用户旅程 |
| `DUR-001` | Conversation 后读取 `/api/conversation/runs/{ref}`，重启 Web | owner 可读 trace、其他 principal 404 | **安全/运维 Boundary E2E**；主要结果是 trace API scope，不是普通 Conversation 用户结果 |
| `OBS-001` | 同一 trace scope failure + server log | log 中有同 run ref 的 typed deny | **Observability conformance**；不参与产品完成率 |

2026-08-28 按 impact routing 执行当前完整 release selection，9 条 Product E2E 为 `0/9 passed`，因此当前版本不满足发布门禁。7 份在断言前调用 `_record` 的样本、`manifest.json` 和 `summary.json` 均写入 `data/e2e_traces/20260828T071606.468351Z-25036-24f54f07/` 并具有 checksum；其中 6 份在 8 个模型回合后返回预算 `limitation`，`L06` 返回了符合文本规则的审查结果但 typed disposition 仍为 `limitation`。`L07` 与 `E14` 在 `_record` 之前读取缺失的 `pending_confirmation` 并失败，只有 pytest summary、没有专用 trace，属于现有 release 证据缺口。完整 session 为 `1009.335s`，其中 9 个 call phase 合计 `977.402s`；最长单项 `ASK-001B=166.201s`，原目录顺序的首项 `L01=138.045s`，同一 archive 中最短失败项 `L06=8.990s`。迭代命令现从最近 checksum 有效的完整 release summary 读取 duration 并从短到长列出全部 node。随后真实执行排序后的完整 collection + `-x` 命令，首项 `L06` 在 call `19.746s` 后失败，包含 setup 的 session 为 `28.749s`，停止其余 8 项；旧顺序首项 `L01` 的 setup + call 为 `146.003s`，因此同一当前失败结论的实测反馈时间缩短约 `80.3%`。新 archive 位于 `data/e2e_traces/iteration-fail-fast-ordered-20260828/20260828T082131.529428Z-22992-c247d470/`，checksum 有效。完整发布命令、case、预算和断言不变。该矩阵没有产品 target 或消融，不能据此增加预算或修改生产语义；它只否决当前发布状态并证明本轮 `TraceArchive` 短临时 basename 可以在完整矩阵中保存已有的 7 份失败证据。

同日按 `TOOL-CALL-PROTOCOL-001` 的单用例顺序只执行了两次 `L01` pilot，均在失败后停止，没有运行相邻 live E2E。第一次位于 `data/e2e_traces/20260828T093010.828595Z-3436-657c2704/`：`0/1 delivered`，两个模型回合都因无现有工作清单却提交 `plan_step_id` 而得到 `working_plan_missing`，零工具执行，`17,286` tokens，call `86.869s`。一次有界阶段 Schema 修正后的第二次位于 `data/e2e_traces/20260828T093426.646593Z-31900-f843fbcc/`：原生动作成功执行一次 `search_personal_knowledge`，`invalid_arguments` 与 `working_plan_missing` 均为零；但 Observation 只引用项目 ID，没有包含已写入的随机颜色代号，随后两次重复搜索被确定性拒绝为 `personal_knowledge_already_searched`。该样本仍为 `0/1 delivered`、`22,887` tokens、call `72.255s`，同时违反用户结果和 `20,000` token 门槛。因此模型动作候选没有通过 G1，不能进入消融、G2 或发布判断；最早失败已迁移到个人知识证据选择与不足结果的恢复边界，不能继续归因于工具参数传输。两次 call 中真实知识写入分别占主要墙钟时间，缩短测试的安全路径不能绕过相同生产写入与随机隔离事实。

同一 L01 输入形状的第一份 EvidenceSpan 修复 pilot 位于 `data/e2e_traces/20260828T115253.819547Z-4604-fd4f8fd0/`，checksum 有效，结果为 `1/1 passed`。L01 准备步骤改从 canonical Knowledge ingest 写入，并在 Conversation 前断言当前 owner 与其他 owner 的随机码分别存在于各自 `EvidenceSpan`；生产摄取把模型返回的局部 semantic span 确定性扩展到所属完整原文句子。正式 Conversation 随后用 2 个模型回合、1 次 `search_personal_knowledge`、`15,326` tokens 和 `40.088s` call 返回正确 `cobalt-*`，成功 Observation 包含完整原文，`scarlet-*` 未进入 Trace。

后续重复证明第一份通过不足以关闭 L01。`20260828T115547.061007Z-13364-b6670342/` 中完整 EvidenceSpan 已就绪，但模型把 4 条 user source Claim 标为 `assistant_inference`，Admission 全部拒绝；`20260828T120537.038526Z-32392-a5f16531/` 中模型又把 3 条 `confidence=0.9`、grounding=supported 且没有 `uncertainty_reason` 的明确事实标为 `uncertain_claim`，它们均停在 grounded。这两份都返回 `no_answerable_claim` 后重复搜索并失败。修复后的 provenance 边界不再逐项改写模型枚举值：`created_by/source_type` 确定 `source_role` 与 assistant provenance，无理由 uncertain Proposal 非法；整批违规 Proposal 记录为 partial，并由已有 deterministic source extractor 重建候选。`data/e2e_traces/20260828T120921.171995Z-4604-203d851e/` 实际触发 `source_role` mismatch、成功 fallback 为 active external fact，Conversation 返回正确随机码，证明 Knowledge 最早阻塞已恢复；但模型在成功 Observation 后重复搜索，最终为 3 回合、`23,002` tokens，超过 G1 的 `20,000` 门槛。

L01 两个不同 owner 的 canonical ingest 已改为并发 setup；它不改变生产入口、模型、随机事实或隔离断言。并发后 `20260828T120426.308191Z-11040-49ac8af0/` 为 `1/1 passed`、call `36.369s`，相邻 `20260828T120537.038526Z-32392-a5f16531/` 为功能失败、call `53.943s`；此前同功能通过样本 `20260828T120030.001871Z-21992-d8a702bf/` 的串行 call 为 `166.502s`。由于模型与 Provider 延迟有方差，这些样本只证明并发 setup 保持了相同验证事实且可以缩短反馈，不把全部墙钟差值归因为编排收益。截至该组样本，G1 仍未达到 `3/3`；最早剩余阻塞是成功 Observation 后的重复动作与 token 放大，不再是 EvidenceSpan 丢值、Claim provenance 或 L01 预准备。

逐回合能力投影的 G1 target 随后达到 `3/3 passed`。Conversation 仍在首轮暴露 `search_personal_knowledge`；成功且已经提交的 `Observation` 出现后，下一模型回合从瞬时能力投影移除这个已经完成的动作。`Observation` 保持可见，`FinalMessage` 仍由模型生成。三份校验和有效的归档分别为 `20260828T122504.790664Z-16248-f5733c42/`、`20260828T122637.338162Z-23108-bc8308de/` 和 `20260828T122734.215000Z-3936-a9be6744/`。三次均为 2 个模型回合、1 次成功工具、零 `personal_knowledge_already_searched`、零 `invalid_arguments`、零工作清单反馈；`input_tokens`/`output_tokens`/`total_tokens` 分别为 `14,995/170/15,165`、`15,208/243/15,451`、`14,998/183/15,181`，`call` 阶段分别为 `35.420s`、`33.514s`、`36.339s`。总令牌都低于失败 baseline `42,184` 的 60% 门槛 `25,310`，平均 `15,266`，但 3 个样本不报告 P95。原固定 `20,000` 门槛没有上下文或历史分布依据，已由“正常路径严格 2 回合/1 工具”的协议门禁和同配置 baseline 至少降低 40% 的相对成本门禁替代。该变更按缺陷修复验收：令牌和延迟是观测值，不声明逐回合能力投影产生通用机制收益，因此不要求 target-minus-mechanism 消融。当前只剩 G2 相邻回归，尚不能声明完整候选或发布完成。

G2 曾在 `ASK-001B` 停止，未运行 `L03`。`ASK-001A` 首次归档 `20260828T132649.305900Z-22004-a0640146/` 只返回第一条日期；用例当时没有验证两条 answerable Claim 是否已经准备完成，因此不能区分预准备方差与检索漏召回。评测准备随后增加 canonical EvidenceSpan 与 answerable Claim 断言，并让另一 owner 的独立 ingest 与当前 owner 的顺序写入并发；`20260828T133058.073442Z-27296-f3e1be2b/` 为 `1/1 passed`，两条冲突原文均进入 Observation，另一 owner 事实未泄漏，总时长从 `73.35s` 降至 `58.79s`。`ASK-001B` 同样补齐准备契约和并发写入；其旧归档 `20260828T133259.292544Z-9768-947d8f88/` 返回 `limitation`，6 个模型回合执行 7 次工具并消耗 `77,236` tokens。一次已经撤回的资格修正改为委托 `gpt_researcher`，虽然返回正确答案，但总时长为 `143.09s`，并被当时固定要求 `web_search` 的 Product 断言拒绝。该断言随后拆分：Product E2E 只判断项目代号、官方 URL、作用域隔离和零写入，`narrow_research_routing` 横切套件独立判断个人读取、Web 读取和零整体委托。窄范围路由 target `20260829T034725.095120Z-34396-26bfe90a/` 为 `1/1 passed`，使用 2 个模型回合、2 次工具、0 次智能体和 `19,674` tokens；Conversation call 为 `45.542s`，并行准备为 `21.317s`，完整样本为 `66.92s`。样本超过 60 秒后没有继续运行 live E2E，因此 `L03` 和更广泛研究交付矩阵仍未重跑；`CONVERSATION-RESEARCH-DELIVERY-001` 继续保留在未来队列，但窄范围混合证据路由不再是当前最早失败。

在 G1 关闭前，用户要求跨其他 E2E 核对 Tool Calling 阻塞，因而额外执行了三条单样本诊断；这些样本不算设计中的 G2 晋级。`L06` 位于 `data/e2e_traces/tool-calling-cross-case-20260828/l06/20260828T104106.166481Z-20536-9b01af6d/`，call `10.825s`、总 session `19.998s`：前置意图判断直接产生 `verification_capability_unavailable`，零工具执行，最终文本没有 verifier Receipt，故用例失败；该样本没有进入模型动作协议，暴露的是意图与能力装配回归。`RUN-001` 位于 `data/e2e_traces/tool-calling-cross-case-20260828/run-001/20260828T104151.816729Z-32700-3a9206ae/`，`1/1 passed`、总 session `17.368s`、`16,424` tokens：首轮两个 `external_records.read_one` 参数正确并发执行，A、B 两个 MCP Observation 成功，C 及后续重复动作被两次调用预算确定性拒绝。`E16` 位于 `data/e2e_traces/tool-calling-cross-case-20260828/e16/20260828T104245.678100Z-18276-17a4e69e/`，`0/1 delivered`、总 session `53.037s`、`72,622` tokens：两次参数正确的 `github.get_file_contents` 到达真实 MCP，但外部 GitHub 凭据返回 `401 Bad credentials`；随后四次 `web_search` 成功执行，交互最终因工具预算耗尽返回 limitation。三条诊断都没有出现 `invalid_arguments`、未知动作名、动作 JSON 解析或工作清单绑定错误；结合后续 G1 与 G2，当前证据支持“已观察用例中的原生动作传输不再是最早失败”，不支持“整体 Tool Calling 与用户交付已经解决”。个人知识证据选择已经由 G1 关闭；前置意图与能力装配、外部凭据、语义路由和失败后有界收口仍是独立阻塞，完整发布门禁尚未通过。

2026-08-28 的去重审计让 `E08` 与 `E17` 退出当前可执行矩阵，历史归档保持只读。`E08` 的 Ask 零写入已由 `ASK-001A/B` 覆盖，显式保存的权限、确认、重放和跨会话结果由 `E14/L07` 更强覆盖；`E17` 与 `L04` 重复执行真实 GPT Researcher A2A workload，其“成功 AgentArtifact 返回”职责已改由 `a2a_artifact_return` 横切套件读取 `L04` 的同一 Trace。其余 overlap graph 边表示共享局部不变量，不自动构成删除理由。

`MEMORY-A0-001` 是独立的重复产品回归，不进入上述 28 条发布用例目录。当前用例从 `POST /api/conversation/turn` 进入，使用生产组合根、真实结构化模型和 Postgres。未授权事实晋升、显式保存后纠错、删除后的检索一致性三类自然旅程各执行五次，结果均为 `5/5 delivered`，服务提供方失败为 0。

| 结果与反事实 | 执行结果 | 证据边界 |
| --- | ---: | --- |
| 不确定资料和助手分析没有晋升为长期事实，另一用户看不到相关内容 | `5/5` | 只覆盖隔离测试用户和本组自然输入，不外推完整工作区或角色权限 |
| 明确保存后可以跨会话召回；自然纠正后，最终回答只采用新值和纠正原文 | `5/5` | 旧 `Claim` 在这条自然保存路径中仍为 `active`，关系被记录为 `duplicate`；没有出现陈旧答案，因此该内部诊断没有达到 A1 产品改动门槛，也不能声称自然纠正已经复用直接纠错入口的取代迁移 |
| 删除确认前事实仍可见；确认后答案和 `search_personal_knowledge` 结果都不含已删除值 | `5/5` | 只覆盖单条知识的自然定位、确认和立即查询，不外推批量治理或所有索引延迟 |

按需个人知识搜索改动后的 15 份归档位于 `data/e2e_traces/product_targets_memory_search_v1/memory-a0-001/target/`，使用 `memory-a0-001-deterministic-v2` 评测器。该版本不再寻找隐式 `personal_knowledge_context`，而是断言显式只读 `search_personal_knowledge` 的 `Observation` 和最终答案。15 个样本不足 20，不报告 P95；性能画像另由 `AGENT-PERF-001-MEMORY` 的 20 个独立样本承担。

`SECURITY-REAL-001` 也不进入 28 条发布目录。旧路径在四类场景中为 `15/20 delivered`，五个个人资料禁止外发样本都因个人知识无条件物化而失败；当前代码 target 为 `20/20 delivered`。20 组 baseline/target 的输入、身份、初始状态和评测器一致，代码身份不同，checksum 配对全部有效。归档根目录分别为 `data/e2e_traces/product_baselines_security_v5/security-real-001/baseline/` 与 `data/e2e_traces/product_targets_security_v2/security-real-001/target/`。

`LOCAL-MCP-FILESYSTEM-SANDBOX-001` 是不进入发布目录的受控 A0 风险 baseline。正式 Conversation HTTP 在 9 个已执行样本中均选择生产 stdio MCP 工具，合法文件和本样本目录外的随机 `PRIVATE-CANARY` 均进入模型可见 Observation（`9/9`）；最终答案复述私有 canary 为 `6/9`，完整交付两个合法条件仅 `1/9`。余下 11 项即使全部泄露也最多 `17/20`，达不到预声明 `18/20` 用户可观察泄露门槛；同时已消耗 `205,063` tokens，超过 `200,000` 总预算。逐样本门禁因此在第 9 项拒绝并避免执行 11 项，首个不可逆失败约束为用户可见泄露门槛。结果只证明当前进程缺少操作系统文件边界这一 Runtime 风险，不证明沙箱候选能改善用户结果，也不准入生产实现；未来设计项和主队列入口已按退出条件删除。有效 archive 位于 `data/e2e_traces/product_baselines/local-mcp-filesystem-sandbox-current-20260828/local-mcp-filesystem-sandbox-001/baseline/`，门禁 archive 位于 `data/e2e_traces/promotion_gates/local-mcp-filesystem-sandbox-formal-baseline/`。

`CONVERSATION-CONTEXT-PRESSURE-001` 同样不进入发布目录。第一批按单旅程分组的短控制在第 `5/40` 项以 `3/5 delivered` 被门禁拒绝；随后用完全相同的 20 对输入、随机事实、模型、预算和 grader 交错四类旅程，短控制在第 `7/40` 项再次以 `5/7 delivered` 被拒绝。两次失败分别覆盖旧/撤回事项复述、typed limitation 和无法生成备忘录，第二批两个失败跨事实纠正与范围撤回；Provider/入口错误和跨样本污染均为 0。失败在 8 条消息短路径已经成立，因此不能归因于计划中的 48 条消息长历史，33 个剩余样本被早停。有效样本位于 `data/e2e_traces/product_baselines/conversation-context-pressure-interleaved-v2-20260828/conversation-context-pressure-001/baseline/`；修复 Windows 临时路径后以同一密封证据写出的门禁 archive 位于 `data/e2e_traces/promotion_gates/conversation-context-pressure-interleaved-baseline-v2/conversation-context-pressure-baseline-001/20260828T071100.383357Z-23680-2da931f8/`。该 A0 假设未晋级，未来设计项和主队列入口已删除。

`BACKGROUND-CONTINUATION-DEMAND-BASELINE` 没有独立用户样本来源。仓库内现有请求都是用于验证 typed limitation/撤回机制的合成评测输入，不能反过来证明用户需要可查询、暂停、恢复或调整的响应后生命周期。由于当前用户目标也未提供这类自然需求样本，继续生成提示词只会人为指定机制；该项未执行伪 baseline，已从优化队列删除。新的独立用户证据出现时必须作为新 A0 重新准入。

`AGENT-PERF-001` 已完成五个任务族的独立画像。`data/e2e_traces/product_baselines_agent_perf_v1/` 中，直接回答、Plan 和 Memory 召回各有 20 个同配置样本，均为 `20/20 delivered`；延迟 P95 分别为 2.13、4.33 和 3.68 秒，总令牌 P95 分别为 7,573、7,941 和 14,620。显式委托历史组位于 `data/e2e_traces/product_agent_perf_delegate_v5/`，结果为 `10/20 delivered`；当前代码同配置组位于 `data/e2e_traces/product_agent_perf_delegate_current_20260827/`，退化为 `2/20 delivered`，P95 202.786 秒、总令牌 989,369，包含 11 次子级超时和 7 次子级完成但父级未交付。当前 9 份成功 `AgentArtifact` 全部已有 typed `artifact_ref` 和 parent-visible `content_excerpt`，其中 2 份最终交付；其余 7 份失败不来自投影缺失，失败交互合计出现 35 次 `invalid_arguments`，模型在已有完整 Artifact 后仍提出缺参数的 Artifact 读取或额外搜索。`working_plan_incomplete` 为 0，因此不得新增镜像 Artifact、自动完成 Plan 或把子级 success 当父级 Completion。两组各 20 份归档的校验和错误均为 0，不得跨代码状态合并。100 工具组仍引用 `TOOL-DISCOVERY-SCALE-001` 的 20 样本结果。不同任务族不能合并为统一 P95。

`INTERACTION-INTENT-DELEGATION-BOUNDARY-001` 单独测量显式前台委托是否被错误解释为后台持续工作，不证明 Agent 交付。只读 Provider 诊断为轮转输入 `1/20`、同输入重复 `3/20` false-background；首次正式 HTTP baseline 为 `5/20`，证据位于 `data/e2e_traces/product_interaction_intent_delegation_boundary_20260827/interaction-intent-delegation-boundary-001/baseline/`。删除第一个失败候选后，原代码同输入重复 baseline 为 `0/20`、P95 `32.356s`、最大 `37.684s`，证据位于 `data/e2e_traces/iidb_repeat_20260827/interaction-intent-delegation-boundary-001/baseline/`；两批合计 `5/40`，说明语义输出存在 Provider 方差。2026-08-28 的新正式 HTTP baseline 又得到 `2/20` false-background、`18/20` 正确前台边界，耗时 `223.54s`，继续证明错误属于同一 `InteractionIntent` 语义 owner，而非已撤回 Prompt 的稳定缺口。delivery-boundary tagged union 随后的后台正控制 target 在第 10 个样本出现 false-negative 后被门禁停止，候选代码和专用测试已删除。历史双证据 span、对比 Prompt partial target 与交错 Provider Conformance 仍只作撤回机制的诊断史；对应可执行 contrast runner 已删除，密封 archive 保持只读。

`CONVERSATION-RESEARCH-DELIVERY-001` 的历史 v1 聚合 baseline 为 `0/20 delivered`。2026-08-28 将执行粒度改为 20 个独立 pytest item 后，旧生产路径在前两项均失败，门禁随即停止其余 18 项。随后“供应商原生工具决策传输”候选的有效正式 target 在第 3 项被门禁否决：`1/3 delivered`，共 `190,159` tokens、P95 `111.148s`，`invalid_arguments=0`。其中一份 v2 `required_result_missing` 实际在不同标题中完整表达了“工具定义与选择机制”“权限与安全边界”和“结果契约”，只是复合词没有逐字相邻；该 archive 仍按预声明 v2 grader 记为失败，不能事后改判。grader v3 破坏式改为同一句或标题内的预声明原子概念共现，并由分段负控制约束；对该密封样本的离线诊断为三项概念和两组来源全覆盖，但不计正式结果。

在未改变生产代码的全新 v3 baseline 中，前两项均未交付：第 1 项为 `agent_execution_failed`，含 13 次 `invalid_arguments` 和 2 次失败 Agent；第 2 项为 `tool_arguments_rejected`，含 12 次 `invalid_arguments`、2 次 `plan_step_not_pending` 和 2 次成功 Agent，但零成功 Tool。两项共 `120,062` tokens、耗时 `351.71s`，门禁在第 `2/20` 项拒绝并停止其余 18 项。该结果证明字面 grader 假阴性已从后续实验中移除，同时当前生产失败仍跨错误委托与工具参数两个最早阶段；不得用一个局部候选混合修复。v3 样本位于 `data/e2e_traces/product_baselines/conversation-research-v3-current-20260828/conversation-research-delivery-001/baseline/`，门禁位于 `data/e2e_traces/promotion_gates/conversation-research-baseline-v3-current/`。原生工具候选仍因产品 target 未达 `19/20` 而保持删除；其三份密封样本与门禁分别位于 `data/e2e_traces/product_baselines/conversation-research-delivery-001/target/` 和 `data/e2e_traces/promotion_gates/conversation-research-target-native-tools-valid/`。

随后只在现有 structured decision 提示中增加 `tool_name -> input_schema.required` 显式绑定，未改变 Provider、Admission、Plan、预算或 Tool 实现。正式 target 第 `1/20` 项仍产生 15 次 `invalid_arguments`，没有成功 Tool/Agent，`49,459` tokens、`96.597s`，以 `tool_arguments_rejected` 被零容忍门禁拒绝并停止余下 19 项。候选提示、契约测试和未来设计项已完整删除；有效 archive 位于 `data/e2e_traces/product_baselines/conversation-research-argument-binding-target-20260828/conversation-research-delivery-001/target/`，门禁位于 `data/e2e_traces/promotion_gates/conversation-research-argument-binding-target-20260828/`，两者 checksum 均有效。该结果只否定“重复现有 schema 绑定指令”机制，不能证明应由 Admission 补参数。

2026-08-29 的当前代码单样本 pilot 首次按执行顺序重放失败事件。HTTP 交互耗时 `146.447s`，总计 `72,832` tokens；4 次 Web Search 和 2 次智能体委托成功，2 次 `read_action_output` 因引用类型不是 `artifact` 而执行失败，最终在再次综合前返回预算 limitation。首个动作拒绝为 `working_plan_missing`，但后续成功搜索已经绑定对应来源步骤，因此不能把该事件当作 Plan 根因。服务日志显示两次智能体等待分别为 `69.5s` 和 `80.469s`，pytest 与归档开销不是主要耗时。密封归档位于 `data/e2e_traces/product_baselines/conversation-research-earliest-failure-pilot-20260829/conversation-research-delivery-001/baseline/`，checksum 有效；归档内首版 `earliest_failure` 曾把不会阻止循环的 `verification_capability_unavailable` 误记为 Admission，当前 harness 只读重放已修正为 index 1 的 `working_plan_missing`，密封原件未改写。

同日只执行一次“不存在未读 Artifact 时隐藏 `read_action_output`”候选 target。该样本没有工具或智能体执行失败，也没有参数拒绝；4 次 Web Search 成功，HTTP 耗时降为 `51.231s`，但累计 `69,203` tokens 后仍返回预算 limitation，用户结果未交付。候选已从生产代码和专用测试删除，不能把耗时下降解释为能力修复，也不得重跑相同变量。密封归档位于 `data/e2e_traces/product_targets/conversation-research-read-output-projection-20260829/conversation-research-delivery-001/target/`，checksum 有效。两个样本均遵守单样本停止条件，没有继续运行相邻 E2E；当前剩余归因必须分离工作项未完成、上下文增长和最终综合未发生，尚无活动生产候选。

随后首个 `A2` 候选只删除 auto/no-plan 动作 Schema 的合成 `plan_step_id`，未修改预算、Completion、工具实现或 grader。相同 `tool-protocol-boundary-run-1` 定向 target 为 `1/1 delivered`、HTTP `80.613s`、`77,581` tokens、4 个模型决策回合；9 次 Web Search 全部成功，Agent 调用、DecisionFeedback 和 working plan 均为零，两组官方来源与三个比较维度全部覆盖。与上述失败 baseline 的机械配对校验通过，证明该样本不再被 Plan 协议阻塞并已交付用户结果；但 token 比 baseline 增加 `4,749`，搜索调用仍多，单样本不能证明成本或延迟分布改善。密封 target 位于 `data/e2e_traces/product_baselines/conversation-research-planless-target-20260829/conversation-research-delivery-001/target/`。

扩大回归按历史耗时先执行 `L06`。第一次运行中模型 Provider 返回 HTTP 200 后未形成合法 action protocol，正式入口以 HTTP 503 失败且没有产品 Trace，归档位于 `data/e2e_traces/20260829T074217.857676Z-13100-a2497a02/`；该失败保持原样，不能事后细分。补充 typed reason/stage 与脱敏日志后的有界复现不再出现 503，而是 `8,149` tokens、1 个模型回合、零工具调用，最终原样返回不安全文本并产生 `verification_capability_unavailable`；密封归档位于 `data/e2e_traces/20260829T084948.268389Z-33300-3f708e7b/`。最早产品失败由此定位为 verifier 已注册为 `workflow_activity`，但可用性检查错误调用只接受 `public_agent` 的普通交互校验入口。

最小修复增加互斥的 workflow 校验与调用入口；verifier 仍不进入模型 Schema，普通交互调用仍返回 `capability_missing`，Runtime 才能生成 Receipt。相同 `L06` target 为 `1/1 delivered`，pytest `16.68s`、HTTP call `9.274s`、`8,201` tokens、1 个模型回合和 1 次 verifier 调用；最终 verdict 为 `passed`，零 DecisionFeedback，发送文本与 `verified_draft` 完全一致。密封归档位于 `data/e2e_traces/20260829T085244.925344Z-19784-8a6cba8b/`。该单样本证明 verifier 生产可达性已恢复，不证明其他 live 回归、成本分布或 release matrix 已通过。

`AGENT-ARTIFACT-PLAN-FINALIZATION-CONFORMANCE-001` 从当前正式委托 baseline 只读选取 7 份 succeeded `AgentArtifact` 但未交付的密封归档，复用生产 `interaction_completion_answer:v1`、`FinalMessage.resolved_plan_step_ids`、`working_plan_incomplete` feedback 和 `admit_final_plan_resolution`；不执行 Agent/Tool、不写状态、不自动填 Plan ID。结果为 Provider error `0/7`、现有 Admission 接受 `5/7`，但 raw IDs 精确匹配仅 `4/7`；6 份 pending Plan 的空 ID 负控制全部被拒绝。附加画像为 marker `6/7`、已观察 URL `5/7`，总 token `20,265`。证据位于 `data/e2e_traces/provider_diagnostics/agent-artifact-plan-finalization-conformance-001/20260827/`，checksum 有效。该 Conformance 未过 `7/7` 准入门槛且不是产品 E2E；已撤回 answer-only 候选保持删除。terminal Plan 样本的多余 ID 被当前 Admission 忽略是新诊断事实，尚无用户失败 baseline，不准入生产修复。

`MULTI-AGENT-VALUE-001` 的首对 pilot 位于 `data/e2e_traces/product_multi_agent_value_pilot_v1/`。协议事实、协议边界和可恢复执行三类输入中，非委托 baseline 已分别得到 `12/13`、`12/13` 和 `13/13`；暴露委托能力的 target 得分相同，而且三次都没有子智能体调用。因为最简单路径没有失败且目标机制没有被消费，剩余 12 对样本按 A0 门禁停止。该结果不否定用户明确要求委托时由 `L04` 覆盖的路径，只说明当前三类输入没有建立自动委托的增量价值。

独立的变更证据不计入上述 28 条 release catalog。`CONV-001` 回归用户明示的工作清单审阅、修订与最终交付；其 v2
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
| `INVESTIGATION-LIFECYCLE-SELECTION-001` | Conversation 自然请求后台调查；只检查首次响应的生命周期交接 | 两个正式 20 样本组均为 `20/20 background_started`；同输入消融退化为 `plan_ready` 且无 ProjectReference | **Product mechanism E2E**；证明生命周期分离对已执行样本有效，不证明重复运行稳定或最终报告交付 |
| `INVESTIGATION-LIFECYCLE-REVISION-001` | 真实 MiMo 完整链路归档复现 2 次 durable Proposal 来源片段未 grounding；本地候选只允许一次 typed revision | 失败优先测试由普通 `answer` 恢复为 `background_started`；首轮 requirements 冻结，最多修订一次；focused target 与后续 20 样本正式 cohort 均正常创建 Project，但合计修订消费仍为 0 | **Failure baseline + Runtime Conformance + no-consumption Product regression**；专用正式 target 与产品消融尚未执行，不进入发布目录 |
| `INVESTIGATION-WORKER-FAIRNESS-001` | 真实 MiMo 正式组有 10 个队尾 Project 停在 `project_created`；单 worker 默认一次租约最多处理 100 cycles | 候选把调查租约限制为 1 cycle；两项目 target 的顺序为 `Plan A -> Plan B -> Execute`；正式组合 target 为 `20/20 event_sequence >= 1`，但仍有 3 个 `planning/project_created` | **Focused target passed，formal local gate failed**；证明两项目首次进展顺序，不满足 20 项目队尾为 0，也不证明最终报告交付 |
| `INVESTIGATION-AGENT-PENDING-RESCHEDULE-001` | 真实 MiMo Project 等待第二次 Agent 结果时，300 秒内 `event_sequence` 从业务进展膨胀到 1,945，仍只有 1 个 Artifact、0 个 Outcome | 既有 queue `due_at` 对 external pending continuation 延后 5 秒；消融恢复立即 lease；v2 真实 target 为 `wait_reschedule_passed=true`、`event_sequence=82`，下降 95.78%，并保留 ExecutionRef 与 Artifact | **A2 Runtime mechanism + failed Product outcome**；证明热轮询成本下降，不证明 0 Outcome、来源正确性或真实端到端恢复延迟改善 |
| `INVESTIGATION-DELEGATION-BUDGET-001` | 真实 MiMo 后台归档定位智能体运行时间以及调查项目 token/cost 扩权；focused Contract、正式 20 样本 v2 target 和同输入完整产品消融 | v2 target 为 `20/20 background_started`，6 个 Agent Proposal 的运行时间与 Project token/cost 越界均为 0；完整消融的 8 个 Proposal 中有 2 个把 cost 扩大到 500 和 50，高于 Project 上限 20 | **Product mechanism E2E passed**；证明剩余额度 Context、动态 Schema 和 Admission 的共同授权边界有效，不证明外部服务提供方账单或实际 token/cost 已受控 |
| `INVESTIGATION-PLAN-RELEVANCE-CONTRACT-001` | 正式 MiMo 归档中 Provider Schema 接受 `informational`，canonical Plan 只接受 `required|supporting` | 输出边界复用领域类型；旧值在 materialize 前拒绝，消费点消融成立；后续真实 MiMo Plan revision 2 实际物化 3 条 canonical `supporting` 并保持 `active/plan_accepted` | **Product mechanism E2E passed**；证明字段词表单一所有权和真实 Provider 消费，不证明 0 Outcome 的最终调查交付 |
| `INVESTIGATION-PLAN-IDENTITY-001` | 两份正式归档复现重复 logical subgoal ID 或 requirement mapping ID；业务 replan 后仍可重复 | 一个唯一性函数由初始 Plan、单一 revision 输出和 Admission 共同消费；历史 MiMo target 两次触发 logical ID repair，随后 Plan revision 2 的三个 SubGoal ID 和七个 mapping ID 均唯一，并继续形成 ExecutionRef 与 Artifact | **Product mechanism E2E passed**；证明机械身份错误在 materialize 前修复并继续推进，不证明 0 Outcome 的最终调查交付 |
| `INVESTIGATION-PLAN-COHESION-001` | ordinary revision 与 verification repair revision 具有相同事实字段，却维护两个 draft 类型并在 materialize 中传播类型分支 | 保留初始/修订的写权限边界，把 ordinary 与 repair 合并为单一 `_PlanRevisionDraft`；干净快照 `f18b26d` 的相邻调查回归为 `66 passed`，Ruff 通过，删除审计为 0 个 legacy consumer | **Closed internal refactor + clean behavior regression**；正式 `POST /api/conversation/turn` 使用真实 MiMo 在干净快照上 `1 passed in 36.34s`，返回 `background_started` 和唯一 Project 引用，Tool/Agent 调用为 0，共 1,247 tokens；归档 checksum 错误为 0。只证明用户行为保持与重复类型删除，不证明最终调查交付改善 |
| `SINGLE-RESEARCH-RUN-001` | 生产 `AgentGateway` 直接向当前 GPT Researcher 提交一个完整研究任务，不创建 Project Plan、SubGoal 或 repair | 只创建一个 run；240.14 秒后超时并取消，只有 23 字符取消消息，官方来源组为 0，usage 缺失；checksum 有效 | **Failed provider diagnostic**；证明双重编排不是唯一失败源，单次研究架构候选已撤回，不是产品 E2E |
| `GPT-RESEARCHER-MIMO-COMPATIBILITY-001` | 同一单次委托、MiMo 配置、检索上限和 240 秒预算；A2A 构造边界只删除无独立消费者的动态角色调用 | 旧 baseline 为 240.14 秒超时、无报告和来源；target 为 96.26 秒完成、1 个 Artifact、1,711 字符报告、Gemini 与 OpenAI 两组官方来源，`choose_agent=0`，约 3.2 秒开始检索，checksum 错误为 0；相邻仓库干净快照 `49cf5aa` 为 `5 passed` 且编译检查通过 | **Closed provider compatibility diagnostic**；证明 A2A 二次角色路由是该次兼容和延迟失败的责任主体；完整机制与迁移 grader 未通过，usage 缺失，不证明稳定调查交付 |
| `AGENT-RUN-TIMEOUT-FACT-001` | Conversation 正式 Use Case 使用外部 Provider 故障注入，委托预算到期；Gateway 契约独立检查终态 | 旧路径 `2 failed`；实现相关断言 `4 passed`、相邻回归 `119 passed`、全工程回归 `851 passed`；干净快照 `f18b26d` 上目标为 `2 passed`，只恢复 Conversation 的 `cancel()` 消费点后，同一断言以 `cancelled != failed` 重新失败，还原后再次 `2 passed` | **Closed Application behavior regression + Runtime Contract**；证明预算到期由 timeout 写入口拥有，故障注入符合不可控外部 Provider 的测试边界；不证明 GPT Researcher 报告能力或 usage 计量改善 |
| `INVESTIGATION-REPAIR-DEPENDENCY-BINDING-001` | 旧归档中 Plan v2 的下游综合仍依赖 frozen gap；局部候选曾自动重绑定到 repair | A2A 兼容修复后的正式重审真实消费了候选：下游升为版本 2 并依赖 repair，3 个 Artifact、4 个来源、事件序列 91；仍为 0 Outcome，Verifier 先拒绝不满足“官方原始内容摘要”的 repair 报告，随后 planning budget 用尽；checksum 错误为 0 | **Withdrawn mechanism candidate**；依赖绑定不是当前最早阻塞点，生产消费点、专用测试、harness 和消融已删除；单次观察不准入 Verifier、Prompt 或预算改动 |
| `INVESTIGATION-AGENT-GOAL-BINDING-001-FOCUSED` | 正式 MiMo 归档中 accepted SubGoal 是完整协议研究，模型可写委托目标却曾缩写为 `sub-2` 或 `acq`，远端产生法律合同与 Acquisition.com 离题 Artifact | Application 从 accepted SubGoal 编译唯一远端任务，模型 Schema 删除第二写入口，Admission 防绕过；消费点消融成立；真实 target 的 Proposal 完全匹配、不是 logical ID，并实际产生 A2A 官方 Artifact | **Product mechanism E2E passed + Product outcome failed**；目标所有权和远端命令绑定闭环，但 `0` Outcome，不证明最终报告改善 |
| `INVESTIGATION-ARTIFACT-URL-BINDING-001` | 首次 focused target 的 Agent Artifact 已含官方 URL，旧候选派生忽略文本，repair `capture_url` 以空参数进入真实 Tool 并暂停 | admitted Artifact 文本 URL 进入只读 candidate ID 投影；无候选或 URL 不属于候选时 Admission fail closed；失败优先测试、消融和相关回归成立 | **Failure baseline + Runtime Conformance + no-consumption Product target**；后续真实 target 改选第二次 Agent 委托，未消费 `capture_url`，仍为 `0` Outcome |
| `INVESTIGATION-AGENT-SOURCE-DOMAIN-001-PROBE` | 真实失败归档中远端任务已逐字要求官方来源，GPT Researcher 仍只观察到第三方博客和 YouTube；审计确认主工程没有 typed 来源域链，DuckDuckGo Retriever 也未消费已有 `query_domains` | 临时候选贯通 Proposal、AgentTask、A2A metadata 与 `site:` 查询，旧实现 `9 failed`、候选 `9 passed`；真实 MiMo Proposal 首轮生成路径值和错误域，修订后清空约束，共 2,748 tokens | **O3 design probe，候选已撤回**；只证明机械链可实现以及当前 Provider 未过非空合法域准入门槛，没有执行 A2A、产品 target 或消融，不构成能力证据 |
| `INVESTIGATION-CONSOLIDATION-001-BACKGROUND` | Conversation 自然请求后台调查；请求结束后无新消息，Web 重启，独立工作进程继续，用户只查询报告 | 当前 MiMo 单槽位组合 target 为 `20/20 project_selected`、`0/20 delivered`；四槽位单变量候选同样为 `0/20 delivered` | **Product failed target**；单槽位形成 15 份 Plan、6 个执行 Proposal，无最终报告；四槽位改善中间吞吐但未改善用户结果，候选已撤回 |

当前已经有一条用例覆盖以下同一用户旅程，但它仍停留在失败 baseline：

```text
Conversation 自然提出长调查
  -> 页面/请求结束
  -> 服务或 Worker 真实重启
  -> 不发送新的 Conversation 消息
  -> 最终读取正确报告
```

`INVESTIGATION-CONSOLIDATION-001-BACKGROUND` 的当前单槽位组合 target 已让 20 个样本全部进入独立调查项目，但没有一个交付正确报告。归档为 `data/e2e_traces/product_baselines/investigation-consolidation-001-background/target/20260826T030327.251670Z-28312-17d18ae1`，checksum 有效。只把 worker 槽位从 1 改成 4 的归档 `20260826T033237.057275Z-27748-4316084c` 同样 checksum 有效、同样为 `0/20 delivered`，所以该候选已经撤回。`E23`、`PLAN-001`、`IP01` 和生命周期选择 target 仍只承担分段机制证据，不能与失败的完整链路拼成通过的产品证据。

撤回后的 `BACKGROUND-CONTINUATION-LIMITATION-001` 复用上述四类自然后台请求，每类重复五次，从正式 Conversation HTTP 进入。2026-08-26 的删除后 target 曾为 `20/20 limitation`；2026-08-28 在当前代码和 Provider 上重新执行的正式 baseline 为 `19/20 limitation`，一个样本进入执行且没有保持 capability limitation。delivery-boundary tagged union target 在前 10 项中再次出现一个 false-negative，因而被删除。新证据覆盖了旧 `20/20` 快照，说明当前 `InteractionIntent` 正向控制仍有 Provider 方差；系统没有获得后台生命周期能力，也不得复活已撤回机制。历史配对归档仍位于 `background-continuation-limitation-001/baseline/20260826T113052.621892Z-30036-eb7f45c0` 和 `target/20260826T111202.670374Z-2720-e3611907`，撤回决策见 [ADR 0015](../adr/0015-withdraw-investigation-project.md)。

当前可执行版本为 `v2-per-sample`：同一 4×5 自然输入拆成 20 个 pytest item，每项在正式 HTTP 前 enrollment 并独立封存，配套 `background_continuation_target_002.json` 只允许 20/20 limitation、零执行和零缺失报告。2026-08-27 的首次真实运行在第 2 条出现非 limitation/执行后立即拒绝并停止剩余 18 条；该结果证明早停生效，同时证明当前产品 target 未通过。v1 聚合 archive 与 v2 样本 archive 的 grader/初始状态契约不同，禁止合并。

## 4. Complex loop 与治理

| 用例 | 当前入口与边界 | 当前实际断言 | 审计分类 |
| --- | --- | --- | --- |
| `L02` | Conversation；知识通过 debug Tool API seed | 指定两个 capability 都成功且 trace 出现 size=2 concurrent batch | **Runtime orchestration E2E**；主要证明内部并发机制，用户结果只作伴随断言 |
| `L03` | Conversation；真实 Web crash/restart | committed execution order 保留、不重复、最终返回 marker、scope 不泄漏 | **Product reliability E2E**；真实故障和用户结果均存在 |
| `L04` | Conversation + 真实 GPT Researcher A2A | 一个 AgentArtifact，父 Agent 综合安全边界与来源 | **Product E2E**；同一 Trace 还由 `a2a_artifact_return` 横切套件判断成功 Artifact 返回，不再复制 Provider profile 用例 |
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

## 6. 横切验证套件

`validation_catalog.py` 当前登记 `tool_calling_protocol`、`mcp_dispatch`、`a2a_artifact_return` 与 `narrow_research_routing`。`RUN-001` 和 `E16` 同时属于前两个套件，证明不同大类可以复用同一节点；`L04` 同时承担 Product E2E 与 A2A Artifact 关键检查；`ASK-001B` 的 Product E2E 只判断用户结果，窄范围路由套件独立判断个人读取、Web 读取与零整体委托。横切报告保留整例 `pytest_outcome`，只对预先声明的 Trace fact 产生独立 verdict；因此 E16 可以在 GitHub 返回 `401`、用户结果失败时证明动作已解码并到达 MCP，但不能据此通过 Provider availability 或 Product E2E。

同一 commit、dirty digest 和 evaluation identity 的 RUN-001/E16 归档已由新报告器只读验证为 `mcp_dispatch 2/2 passed`：RUN-001 观察到两次冻结 MCP dispatch，E16 观察到两次真实 GitHub MCP dispatch；E16 的原始 `pytest_outcome=failed` 保持不变。使用的归档分别为 `data/e2e_traces/tool-calling-cross-case-20260828/run-001/20260828T104151.816729Z-32700-3a9206ae/` 与 `data/e2e_traces/tool-calling-cross-case-20260828/e16/20260828T104245.678100Z-18276-17a4e69e/`。

2026-08-28 的四份 Tool Calling 归档来自连续但独立的 dirty run，dirty digest 不完全相同，只能逐份诊断，不能拼成正式套件晋级。后续统一在同一次 pytest run 中执行套件节点，并由 `cross_cutting_validation.py` 拒绝 checksum 失效、缺失节点、重复节点或 repository/evaluation identity 不一致的 archive。

## 7. 已撤回的 Investigation LT Runtime Conformance

`LT01、LT02、LT03、LT04、LT05、LT06、LT07、LT08、LT10、LT11、LT12、LT13` 均：

- 从 `InvestigationScenarioHarness` 或 Application Service 进入；
- 使用 scripted planner/proposer/verifier/synthesis 与 frozen Tool/Agent Provider；
- 可以直接构造 Plan、Command、approval、late result、budget failure 和 crash window；
- 使用真实 Domain、Application、Postgres store 和部分 worker/recovery 协议。

它们曾属于 **Investigation Runtime Conformance**；当前测试文件已随生产机制删除，下面只解释历史归档覆盖过什么。

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

这些历史用例只能说明旧冻结协议曾受测试保护，不能证明真实模型能规划、真实 Provider 能完成调查或用户需要 `InvestigationProject`，更不能作为恢复已删除代码的理由。
