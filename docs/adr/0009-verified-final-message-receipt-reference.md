# ADR 0009: 以凭据引用替代已验证文本的二次搬运

- 状态：Superseded by [ADR 0010](0010-runtime-owned-interaction-verification.md)（2026-07-31）
- 日期：2026-07-30
- 影响范围：`ConversationService` 交互回合终止路径

> **被取代说明。** 本 ADR 的结论——「发出的字节必须逐字等于通过验证的字节，且这要由
> Runtime 保证而非要求模型复述正确」——仍然成立，且是 0010 的前提。被取代的是**实现手段**：
> 0009 让模型返回 `VerifiedFinalMessage(verified_receipt_id=...)` 由 Runtime 解析；0010 收回
> 验证调用本身，Runtime 直接从它自己持有的凭据取 `verified_draft`，于是模型不再参与产物
> 传输，引用型终止分支、`criteria_anchor()` 与两个 admission 门禁一并删除。本 ADR 末尾
> 记录的「剩余边界：首套判据仍由模型提出」正是 0010 处理的问题。

## Goal / Current Incorrect Behavior / Expected User-visible Result

用户请求「审查并修订这段答复」时，最终发出的文本必须就是通过语义验证的那段文本。

改动前的机制是：模型调 `verify_interaction_draft` 得到 passed 凭据，下一轮把同一段文本
重新写进 `FinalMessage.message`，Runtime 比对 `sha256(message)` 与
`receipt.draft_digest`，不一致则回灌 feedback 要求重述。

错误行为不在门禁判断本身，而在接缝位置：**受管产物被交回模型再搬一趟**。模型没有 copy
原语，第 N+1 轮是对更长 prefix 的一次全新采样（即使 `temperature=0`，prefix 多了一条
observation，条件分布已变），字节漂移是默认结果而非异常。

期望的用户可见结果不变：发给用户的文本逐字等于 passed 凭据的 `verified_draft`。区别是
由 Runtime 保证，而不是要求模型复述正确。

## Business Expansion or Proven Constraint / Out of Scope

已证明约束：LLM 不能被当作字节精确的传输通道。

Out of Scope：判据本身的来源（首套 `success_criteria` 仍由模型提出，见「剩余边界」）、
verifier 的判定严格度、以及为普通问答路径增加验证要求。

## Baseline / Executed Result / Root Cause

改动前的 `verified_draft_mismatch` 真实发生率：**无法测量**。L06 在本部署上根本到不了门禁——
trace 显示 `model_turns=1, tool_calls=0, inputs=[]`，模型直接自撰答案返回。因此本次改动
省下的不是重试成本，而是消掉了一个在该部署上尚未被触发的分支；这一点如实记录，不宣称
性能收益。

诊断 L06 失败时分离出两层原因：

**第一层：指令强度。** 用真实 `deepseek-v4-flash`、只注册 verifier 一个能力做 A/B：
软措辞（"use an available semantic verifier before returning the reviewed text"）→ 3/3
返回 `final_message`；MUST 措辞 → 3/3 返回 `continue_turn:verify_interaction_draft`。
原 prompt 里只有两条 `MUST`，验证规则不在其中，而模型本身具备审查能力，没有理由绕道工具。
已改为 MUST 措辞。

**第二层：判据成形。** 两处修复后跑 9 次真实模型：**5 通过（1/3/4/6/9）、4 失败（2/5/7/8）**。
每次通过时 L06 四条断言全部成立且 `feedback == []`（证明走的是 `verified_final_message`
路径——若自撰答案而本轮已有 passed 凭据，会产生 `verified_reference_required`）。四次失败
形状相同：verifier 持续返回 `needs_revision`，循环到不了 passed 凭据，最终以
`clarification_required`（2/7/8）或 `failed`（5）退出，都是 L06 不接受的 disposition。
近因是模型把**整条用户指令**当作 criterion 字符串传入，verifier 于是拿指令形状的判据去评
判最小化草稿并拒绝。这属于判据成形/verifier 严格度，与本 ADR 处理的漂移是不同问题，
未在本次范围内修。

9 次运行中 `verification_criteria_changed` 出现 **0 次**，漂移类失败已消除。

## Decision Ownership / Fact Owner and Write Path

- 模型拥有**引用**：`VerifiedFinalMessage(verified_receipt_id=...)`，不含 message 字段。
- 工具拥有**凭据**：`receipt_id = f"svr_{draft_digest[:20]}"` 由工具确定性派生，模型无法
  凭空构造一个指向未验证文本的 id。同一 draft 幂等得到同一 id。沿用
  `_prepare_knowledge_save` 里 `command_id = "ksave_" + sha256(...)[:20]` 的既有 idiom。
- Runtime 拥有**解析与写入**：`resolve_verified_final()` 命中 passed 凭据后返回已解析的
  `FinalMessage(disposition="answer", message=receipt.verified_draft)`，`respond()` 用它替换
  原 decision 再提交。所以 `InteractionTrace.final_message` 存的是执行事实而非引用，replay
  路径与既有 E2E 断言无需改动。

删除 `report_id`（无消费者，且因为在 `output_type` 里而**可被模型自填**——引用命名空间可伪造）。

## Canonical Models

新建 `capabilities/contracts/verification.py` 承载
`VerificationCriterionResult` / `SemanticVerificationReport` / `SemanticVerificationReceipt`。
原先契约住在 `tools/`，而 package DAG 不允许 `application -> tools`，这正是消费侧退化成
`payload.get("data")` + `receipt.get("draft_digest")` 的根因：字段改名不报错，`.get()` 返回
`None` → 永久 mismatch → 重试到预算耗尽，静默且昂贵。搬到 `capabilities/` 后两侧都合法，
消费侧改为 `SemanticVerificationReceipt.model_validate(...)`，字段改名当场 ValidationError。

`SemanticVerificationReceipt` 携带 `success_criteria` 作为 `criteria_digest` 的原像。这不是
冗余字段：判据漂移的拒绝必须能指名该用哪套判据重验，否则就是在要求模型复述它已看不到的
字节——与本 ADR 移除的漂移是同一个缺陷。见下节。

## Affected Modules and Dependency Direction

`emits_verified_artifact: bool` 沿既有链 `ToolGovernance -> InteractionToolDefinition ->
EffectiveToolCapability` 增加一个声明位（`kernel/contracts/tool.py`、`tools/base.py`、
`capabilities/contracts/interaction.py`、`governance/registry.py`、
`application/conversation/models.py`）。Admission 按属性筛出凭据类能力，Application Service
里不再出现 `"verify_interaction_draft"` 字面量；下一个需要产物绑定的工具只声明属性。

`application/conversation/verification_admission.py` 全部为纯函数，无 service 依赖，
每条拒绝分支都能在不构造 service 的前提下单测到。

`AgentTurnDecision.decision` 从 2 分支 union 变 3 分支，仍在 `properties.decision.anyOf`
同一层，没有引入新嵌套。ADR 0007 记录的 Provider 坑是 root union，不是本层；
`test_agent_turn_decision_uses_supported_object_root_schema` 继续守这条。

## Complexity Added, Removed and Rejected Alternatives

removed：`_admit_final_verification`、`_verification_completion_feedback`、
`verified_draft_mismatch` reason code、feedback 里回灌整段 draft 的上下文放大、
Application 层的工具名字面量、无消费者的 `report_id`。

added：一个 union 分支、一个声明位、一个纯函数模块。

reject 掉的替代方案：
- **收回自撰权，所有 answer 都必须引用凭据**：会把普通问答路径也拖进验证，
  E01/E02/E08/L01 全部受影响。已确认只在本轮出现过 passed 凭据时才强制引用。
- **放宽 digest 比对（容忍空白/标点差异）**：把「哪些漂移可接受」变成一条需要持续维护的
  规范化规则，而漂移这个类别本身没有消失。
- **不做锚定，只绑文本**：则同一段文本可以被换成更易满足的判据重验后再引用，
  只绑了文本而判据自由移动。

一次自我修正值得记录：锚定的第一版拒绝语只说「用原来的 success_criteria 重验」而不写出
判据本身。9 次测量中的前一轮探针因此在 `turns=8` 撞上预算上限，feedback 是
`verification_criteria_changed × 5`。它复现的正是本 ADR 刚刚为 draft 移除的缺陷——要求模型
凭记忆复述字节。结构性修法（而非放宽检查）是把 `success_criteria` 放进凭据，让
`_reverify_repair()` 直接写出 `list(anchor.success_criteria)`。修后 9 次运行该 reason code 为 0。

## Verification and Remaining Risk

- 架构门禁 `scripts/check_layers.py`：PASS（packages=14, edges=53）。顺带修了三个只含
  `__pycache__` 残骸的目录造成的假阳性，并让 `discover_packages()` 要求目录内至少有一个
  `.py`，使未来的 stale pycache 不再制造幻影 FAIL。
- `tests/` 全量：709 passed。
- 证据分级：三条拒绝分支（引用不存在 / 未通过 / 判据变更）与「按声明而非工具名选能力」为
  **C 级**（单测）。正向绑定为 **C 级而非 B 级**——L06 正式 HTTP 入口在 9 次真实模型运行中
  5 次通过，未达到可作为 B 级证据的稳定通过，原因是上文第二层（判据成形）。

**剩余边界：首套判据仍由模型提出。** 锚定只阻止中途削弱，不保证判据本身足够严，也不保证
判据形状适合 verifier 评判——这正是 L06 剩余 4/9 失败的来源。让判据源自用户表述是另一个
更大的改动，本次不做。
