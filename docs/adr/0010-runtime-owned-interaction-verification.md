# ADR 0010: 交互语义验证的所有权收归 Runtime

- 状态：Accepted
- 日期：2026-07-31
- 影响范围：`ConversationService` 交互回合的判据派生、验证调用与终止路径
- 取代：[ADR 0009](0009-verified-final-message-receipt-reference.md)（其产物传输结论仍成立，见该文顶部说明）

> 2026-08-26：Conversation 的 Runtime-owned verification 结论仍有效；本文涉及 `InvestigationProject` 的实现坐标只作历史记录，该产品循环已经删除。当前决策见 [ADR 0015](0015-withdraw-investigation-project.md)。

## Goal / Current Incorrect Behavior / Expected User-visible Result

用户请求「审查并修订这段答复」时，发出的文本必须真的经过语义验证，且验证所用的判据必须
源自用户自己的表述。

改动前四条不变量里只有两条是确定的：

| 不变量 | 改动前的执行方式 | 改动前状态 |
| --- | --- | --- |
| 发出的字节 = 验过的字节 | Runtime 解析凭据引用（ADR 0009） | 确定 |
| 判据不被中途削弱 | `criteria_anchor` digest 比对 | 确定 |
| **验证会发生** | prompt 里的 MUST 措辞 | **概率** |
| **判据可被评判** | 无任何机制 | **无** |

错误行为是把两个不变量交给 prompt 措辞去执行。L06 实测 **5/9**，四次失败对应两条降级：
触发权在模型（`tool_calls=0`，模型直接自撰答案），判据来源在模型（把整条用户指令当作
criterion 传入，verifier 拿指令形状的判据评判最小化草稿，一路 `needs_revision`）。

期望的用户可见结果不变。区别是「验证发生过」成为这段代码的性质，而不是模型配合的结果。

## Business Expansion or Proven Constraint / Out of Scope

已证明约束：**不能用 prompt 措辞执行结构性不变量。** 与 ADR 0009 的「不能把 LLM 当字节精确
传输通道」同类——那次是产物传输，这次是控制流与判据来源。

决定性证据在本仓库内部，不在外部框架。**Project 路径**已经把这条原则写成强制规则：
`investigation_project/model_ports.py:80-95`
  的 `_exclude_project_verification_work` 与 `investigation_project/admission.py:212-222` 双重
  拒绝任何 `semantic_domain in {verification, semantic_verification}` 的 SubGoal，理由原文是
  「Project semantic verification is owned by the automatic Verifier and cannot be a Plan
  SubGoal」。判据同样不由模型自拟：`project.user_requirements` 是独立 durable 对象，模型
  derive 的 requirement 不得与其 id 冲突，且每条 active 的都必须被 mapped。

所以本次改动不是「向主流框架看齐」，而是让 Conversation 遵守本项目 Project 路径已经强制的
同一条规则。

Out of Scope：verifier 的判定严格度本身；为普通问答路径增加验证要求（非审查请求完全跳过
验证，E01/E02/E08/L01 路径零变化）。

## Baseline / Executed Result / Root Cause

同一段 L06 用户文本、同一组四条断言、同样的进程内探针方法：

| | 改动前 | 改动后 |
| --- | --- | --- |
| 通过率 | **5/9** | **9/9** |
| 判据形状 | 整条用户指令 | `不能声称写入已经发生，除非有可核验的执行证据。`（9 次稳定，1 次仅末尾句号差异） |
| `ungrounded_spans` | 不适用 | 9 次均为空 |

**收回控制权与判据权不足以让 L06 通过，这一点如实记录。** 第一次跑探针是 **0/3**，且是确定性
失败而非抖动：判据派生正确（一条 grounded 判据，跨运行稳定），但模型以
`clarification_required` 终止——「请提供可核验的执行证据，例如写入操作的日志或确认信息」。

根因是第三条未被识别的降级路径：**只有 `answer` 会被验证，于是非 answer 的 disposition 是
一条绕过验证的出口。** 而通用 prompt 里的「Ask for clarification whenever required user input
is missing」正好在邀请模型走它。模型的行为在自己的框架内是自洽的：判据提到「可核验的执行
证据」，它便去索取证据，而不是删掉那个无证据的断言。

两处修复：Runtime 拒绝审查请求上的任何非 answer disposition（`review_requires_sendable_answer`
feedback，要求返回可发送文本），并在审查指令里写明请求已自带文本与要求、不得索取证据。
修后 3/3，再跑 9/9。

## Decision Ownership / Fact Owner and Write Path

| 事实 | 所有者 | 写入路径 |
| --- | --- | --- |
| 「这是不是审查请求」+ 判据候选 | 模型（一次独立结构化调用） | `derive_review_criteria()`，`operation="interaction_review_criteria"` |
| 判据是否成立 | **Runtime**（确定性函数） | `admit_review_intent()`：每条 `source_span` 必须逐字出现在某条 **user** message 里，否则丢弃 |
| 判据的冻结值 | **Runtime** | `InteractionTrace.review_criteria`，每回合派生一次并提交 |
| 验证何时发生 | **Runtime** | `respond()` 终止分支无条件调用，模型看不见该能力 |
| 判据字节 | **Runtime** | 由冻结值构造 `success_criteria`，模型无任何路径改它 |
| 判定结果 | 工具 | `SemanticVerificationReceipt` |
| 发出的字节 | **Runtime** | `FinalMessage(message=passed.verified_draft)`，直接取自 Runtime 已持有的凭据 |

路由判断仍留给模型，这是刻意的：**路由错了会被兜住（多验或少验一次，trace 里可检测），
判据错了没人兜住**——那正是改动前的 4/9。所以收回判据权是必须的，收回路由权是不必要的。

## Canonical Models

- `ReviewCriteria`（`application/conversation/models.py`，frozen）：`criteria` + `ungrounded_spans`
  + `requires_review` property。**放在 `models.py` 而非 `review_admission.py`**，因为它是提交进
  `InteractionTrace` 的执行事实，必须能跨重启恢复；否则 `models.py -> review_admission.py`
  的依赖方向就反了。`ungrounded_spans` 让「一条判据都追溯不到用户」与「本来就不是审查请求」
  两种状态可区分。
- `ReviewRequirement(criterion, source_span)` / `ReviewIntent(requires_review, requirements)`
  （`review_admission.py`）：**没有承载被审查原文的字段。** 计划里原有 `draft_span`，实现时删掉
  ——它没有消费者（Runtime 验证的是模型自己的最终文本，不是被引用的原文），而它的 grounding
  校验会新增一条能让整次审查降级的失败路径。单独搬运一份「原始草稿」只会制造第二个未经验证
  的候选产物。
- `AgentTurnDecision.decision` 从 3 分支 union 回到 **2 分支**（`FinalMessage | ContinueTurnProposal`）。

## Affected Modules and Dependency Direction

**`workflow_activity` 是干净的接缝，不需要 bespoke stage。** 已核实
`governance/registry.py:64` 的 `list_interaction_tools()` 按 `exposures={"public_agent"}` 过滤，
而 `invoke_interaction()`（:133）与 `validate_interaction_call()`（:79）**不按 exposure 过滤**。
于是 verifier 从模型能力清单里消失、Runtime 仍可经同一 ToolGateway 调用，整条治理链
（`permission_scope="interaction:verify"`、`timeout_seconds=60`、`rate_limit_per_minute=20`、
PolicyEngine、审计、预算记账）全部保留。这正是当初选 tool 形态唯一站得住的理由，不必为了
收回控制权而丢掉它。

改 exposure 不影响 Project 路径：那里的排除按 `semantic_domain` 判，不按 exposure。

## Complexity Added, Removed and Rejected Alternatives

removed：`VerifiedFinalMessage` 模型、`resolve_verified_final()`、`criteria_anchor()` 与
`verification_criteria_changed`、`admit_self_authored_final()`、`admit_redundant_verification()`、
`verified_receipts()`、`receipt_capability_names()`、以及 prompt 里全部 verifier 相关措辞
（MUST 调用要求、`success_criteria` 字节一致要求、`verified_final_message` 形状说明）。
`verification_admission.py` 从 289 行 / 6 函数缩到 **53 行 / 1 函数**。

`receipt_capability_names()` 的删除是对计划的第二处偏离（计划说保留 2 个函数）：它按
`emits_verified_artifact` 从**模型可见**的工具清单里筛能力，而 exposure 改动后该清单按构造
不含 verifier，函数已不可达。`emits_verified_artifact` 声明位本身沿
`ToolGovernance -> InteractionToolDefinition -> EffectiveToolCapability` 链保留。

added：`review_admission.py`（177 行）、一次判据派生调用、一次 Runtime 直接验证调用、
一条 `review_requires_sendable_answer` feedback。

**净复杂度下降**：消掉的是三个「约束模型行为」的门禁，换成一个「Runtime 直接做」的调用。
**prompt 变短是这次改动正确性的一个信号**——不再需要用文字执行不变量。

三处 fail-closed 降级，各留一条可区分的 typed feedback 在日志里：

1. `review_criteria_not_grounded`——一条判据都追溯不到用户表述时降级为非审查请求，
   **不静默替换成通用判据**（那会把判据来源从模型换成 Runtime 自拟，等于没收回）。
2. `verification_capability_unavailable`——部署未注册 verifier 时不派生它无力执行的标准。
   一次自我修正：第一版复用 `ungrounded_spans` 承载这个原因，会把两种不同成因报成同一个，
   已改为独立 reason code。
3. 派生调用抛异常 → `ReviewCriteria()` + 0 tokens，降级为「不是审查请求」而非 Runtime 编判据。

reject 掉的替代方案：
- **判据由 Runtime 用固定模板生成**：判据来源从模型换成 Runtime 自拟，仍然不源自用户。
- **保留模型可见的 verifier，仅加强 MUST 措辞**：已实测过，这就是 5/9 的那一版。
- **对非 answer disposition 也跑验证**：verifier 判的是「可发送文本是否满足判据」，
  拿它评判一句澄清提问是范畴错误；拒绝 disposition 本身才是对的接缝。

## Verification and Remaining Risk

- `tests/test_conversation_interaction.py`：**28 passed**（新增 11 组，锁判据必须 verbatim
  grounded、判据不取自 assistant 消息、无 grounded 判据不静默降级、非审查请求不验证、
  审查请求终止前必验、非 answer disposition 不能绕过验证、判据冻结只派生一次、能力不可用时
  fail-closed、派生失败不声称审查过、凭据按契约而非位置读取）。
- `test_the_real_verifier_is_not_a_capability_the_model_can_see` 用生产
  `build_verify_interaction_draft_tool` 断言它不在 `_effective_capabilities().tools` 里、但
  `executor.get(...)` 能取到且 `validate_interaction_call` 接受。已做变异验证：把 exposure 改回
  `public_agent` 该测试失败。（此前一版用测试内的 `_tool` 助手，默认 `public_agent`，
  断言方向与测试名相反。）
- `tests/` 全量：**707 passed**，9 个 `MCPError: MCP server notion timed out waiting for
  initialize` fixture 错误。判为环境抖动而非本次改动：`test_api.py`（27 passed）与
  `test_audit.py`（19 passed）单独跑全绿，且基线那次的 5 个错误落在不同测试名上。
  计数吻合：707 + 9 = 716 = 基线 715 + 本次新增 1。
- 架构门禁 `scripts/check_layers.py`：**PASS**（packages=14, edges=53, cycles=none,
  forbidden_edges=0）。Ruff 覆盖改动范围：clean。
- 证据分级：「判据源自用户表述」「验证不可跳过」「非 answer 不能绕过」为 **C 级**（单测，
  三者都是结构性不变量，单测足够）。L06 正向绑定 **9/9**，为 **B 级**。

**剩余风险：路由判断错（漏判审查请求）会走普通路径不验证。** 可在 trace 里检测（无 verifier
observation），代价是一次未经验证的回答。这是收回判据权时刻意保留的那条可兜住的失败路径。
