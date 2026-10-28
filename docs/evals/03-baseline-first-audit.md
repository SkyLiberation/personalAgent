# Baseline-first 审计

> 历史审计，更新于 2026-08-26。本审计已促成 `InvestigationProject` 撤回；下文保留审计时的用例、风险与证据，不作为现行矩阵。当前用例和结果见[用例盘点](02-current-case-inventory.md)。`E23`、`IP01`、`PLAN-001`、`LT*` 与 Investigation Consolidation 仅保留历史反例和归档坐标。

审计时的 E2E catalog 在同一命名空间登记了目标回归、机制诊断、指标 baseline 与产品失败 baseline。下表区分它们各自可支持的结论；现行准入规则见 [EVD](../devSpec/change-evidence.md#1-用户结果与工程约束的可执行基线)。

## 1. 有明确失败链的用例

| 审计目标用例 | 可定位的失败证据 | 可以支持的结论 | 不能支持的结论 |
| --- | --- | --- | --- |
| `L01` | `20260803T142413.474927Z-4864-39fedcf5`：自然召回没有 Observation，误报未找到 | Conversation 缺少 canonical personal knowledge read 接线 | 完整个人知识产品已验证 |
| `E22` | `20260803T142932.564456Z-23720-19ba8517`：只能文字确认，无法形成 canonical delete action | 自然语言删除需要复用 lifecycle 写入口 | 所有 delete/restore 控制都需当前复杂度 |
| `E23` | `20260803T143007.354551Z-26256-84d0bf1d`：幻觉不存在的 specialist，Admission capability missing | 旧实现中的 handoff 缺陷 | `InvestigationProject` 本身有真实产品必要性；该越界推论已被撤回 |
| `E14` | B01/B02 与 E14 同输入链：旧 Conversation 无可恢复保存操作或控制文本污染 | 自然保存需要 exact-span、确认、canonical write path | 所有知识写入都必须经 Conversation |
| `L06` | 同一 workload 曾 5/9，Runtime-owned verification 后 9/9 | draft verification owner 和发送产物绑定解决该场景错误 | 所有回答都需要独立 verifier loop |
| `CTX-001/E21` | 大结果曾以 1,940,197 chars、776,720 tokens 进入上下文，或 hash/重复 refetch 导致失败 | 大 Observation 需要 artifact-backed bounded reread | 所有 Tool 输出都应采用同一分页策略 |
| `IP01` | B03/IP01 历史链暴露 verification repair lineage 死锁和无法交付报告 | 已存在 Project 的 repair lineage/completion 缺口 | Project 产品需求真实性 |
| `INVESTIGATION-CONSOLIDATION-001-BACKGROUND` | `20260824T161211.968242Z-9412-a35dc537`：20 个自然请求均创建 Project，9 个因整批委托预算暂停，11 个因产物内容摘要不一致失败，`0/20 delivered` | 只证明旧路由会选择第二循环且不能交付 | 不能证明独立生命周期有需求；正确决策是先删除无证据机制，再单独修复普通 Conversation 研究质量 |

## 2. 当前是回归，不是需求 baseline

以下用例在审计时锁定已有产品或接口行为，但未找到其完整设计实现前的同输入失败证据：

- `PLAN-001`：已删除 Project 的查询、steering 和 Web restart recovery；仅作历史说明；
- `ASK-001A/B`：统一 Conversation answer owner 的结果；
- `E05/E09/E10/E11/E12/E13`：现有 Application API 的纵向行为；
- `DUR-001/OBS-001`：trace scope 与诊断行为；
- `L02/L03/L04/L05`：loop 的并发、恢复、delegation 和 budget 行为；
- `E16/E18/E19/E21`：Provider profile；审计后的 A2A profile 去重由 `L04` 的 Product E2E 与 `a2a_artifact_return` 横切检查共同覆盖；
- `LT01–LT08、LT10–LT13`：已删除 Investigation runtime protocol 的历史 conformance，可执行节点已移除。

这些测试的通过结果只证明原身份下的回归行为，不能作为新增 Aggregate、Queue、Planner、Projection 或治理机制的需求来源。

## 3. 为设计而构造的风险

审计发现以下模式：

| 模式 | 历史实例 | 风险 |
| --- | --- | --- |
| 用户输入主动要求设计独有能力 | `E23/PLAN-001` 明确要求后台、进度、暂停、调整 | 场景恰好命中 Project 全套能力，但没有真实需求来源 |
| 直接构造内部 contract | `IP01` 直接传 requirements、budget；LT 直接构造 Plan/Command/approval | 证明机制可运行，不能证明 Agent 会自主选择或用户需要它 |
| 断言机制存在代替用户结果 | `L02` 要求两个 capability 和 concurrent batch；`E12` 断言 projection/backlink | 容易为了维护架构对象而保留测试 |
| 多条路径并排即称 paired baseline | `E24` 只记录 Research/Conversation/Project 状态 | 没有统一 scorer、同等条件和用户结果，无法比较优劣 |
| 多条独立用例拼成完整能力 | `E23 + PLAN-001 + IP01` | 没有一条测试证明自然入口到最终报告的完整用户旅程 |
| `baseline` 仅作为名称 | `CTX-001.baseline`、`RUN-001.baseline`、`DUR-001.baseline` | 名称可能被误读为实现前失败证据 |

## 4. 当前证据状态

以下是审计保存的机器门禁快照，按其中 revision 与 dirty 身份解释：

```text
target revision: 61ffadb041e7424892f5b9948fcd0e484f3b4ad6
target dirty: true
same-revision trusted product evidence: 0
same-revision trusted loop evidence: 0
release capabilities: all unverified
```

该快照及历史 archive 可以解释缺陷和设计决策；它们不证明后续版本的发布资格。目标版本须按 [Release gate](04-running-and-release.md#release-gate)核对完整证据。
