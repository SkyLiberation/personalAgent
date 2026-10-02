# 局部研究修订继承已有引用

**已解决 `CLAIM-REVISION-INHERITED-REFERENCES-001`：正文片段修改继承已绑定引用，引用替换只对新增坐标要求本轮选择；正式 writer 接收已选与当前已绑定证据的原文。** 本问题属于[研究修订未收敛](../claim-revision-nonconvergence.md)中的确定性准入与输入交接边界。

## 问题与责任

2026-10-01 原正式入口的第 29、30 回合使用正确版本和 `c5.f11`，却被“已有引用须在本轮全部重选”的检查拒绝；末次只漏 `d4:1074`，两次零写入后停止。[原责任审计](../../../.tmp/research-convergence-integration-20261001/target/terminal-boundary-audit.json)保存实际动作、选证与反馈。

`ResearchClaims.references` 拥有已绑定引用，Runtime 在正文修改时保持该字段。模型选证拥有本轮新增依据的适合性；canonical citation binder 从可见执行输入恢复原文，Verifier 判断修改后的完整正文与依据关系。

## 采用方案与生产消费者

`admit_claim_change` 校验完整 `base_ref`、claim 和片段范围后，正文修订原样保留引用，并从实际输入重新绑定。引用替换按当前目标 claim 的已绑定坐标计算新增部分，只对新增坐标检查本轮选择；创建和增补的全部引用继续经过选择。其他 claim 的已绑定引用须经本轮选择才可新增给目标 claim。

`service._decide` 的研究 writer 原文目录取本轮选择与当前集合已绑定引用的并集，来自同一可见执行输入。`evidence_selection` 保持原模型选择；当前 claim 的引用字段标识继承关系。Schema 和 `conversation.research.writer:v11-retained-references` 统一说明继承与新增边界。目录只在请求中派生，合法修改后仍复验完整新版。

正式路径为 `POST /api/conversation/turn` → 生产 Composition Root → 真实选证及 writer → Conversation 准入 → 来源核验。新增持久字段、Port、模型调用和生产开关均为 0。

## 决定性证据

| 证据 | 成立判据 |
| --- | --- |
| [原失败输入反事实](../../../.tmp/research-retained-reference-repair-20261001/retained-replay.json) | 两份实际失败动作保持原选择和 replacement：旧检查均拒绝，现行准入均接受。引用替换继承旧引用并新增已选引用；未选新增引用、其他 claim 引用、缺行范围和不可见来源均拒绝且零写入。 |
| [实际 writer 输入](../../../.tmp/research-retained-reference-repair-20261001/target/writer-view-audit.json) | 可见原文逐坐标等于已选与当前绑定坐标的并集，实发 Schema 范围与目录一致。首个修订请求含 43 个未重选的已绑定坐标。 |
| [实际模型动作与新版消费](../../../.tmp/research-retained-reference-repair-20261001/target/admitted-fragment-audit.json) | 第 4 版 c1 的片段修订保留 2 个本轮未重选的目标引用，实际准入且完整新稿进入来源核验；旧全量重选检查会拒绝。范围外正文、引用与其他项保持。 |

原始预声明和冻结身份见[修复归档](../../../.tmp/research-retained-reference-repair-20261001/plan.json)。完整用户结果、调用和耗时由[评测登记](../../evals/02-current-case-inventory.md)拥有；Verifier 的判决边界由[独立审查](../claim-verifier-consistency.md#2026-10-01-修订修复后的判决边界审查)拥有。

## 失败尝试与重新打开条件

| 尝试 | 已证实原因与结果 |
| --- | --- |
| 对正文修订的全部继承引用执行本轮选择检查 | Runtime 保留整条引用，局部修订却被不相关旧引用未重选拒绝。 |
| 返回缺失坐标后要求模型重新选齐 | 第二次只遗漏一个坐标，合法 ID 动作仍零写入；反馈精确没有解除不必要的重复选择责任。 |

若合法正文修订仍因已有引用未重选被拒、已绑定原文没有进入实际 writer、未选新增引用被接受，或继承引用无法从可见执行输入绑定却发生写入，则重新打开本问题。复用经验见[面试复盘](../../interview/10-development-pitfalls.md#10-局部修订应继承已有绑定关系)。
