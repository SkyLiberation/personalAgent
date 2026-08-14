# Baseline-first 审计

**当前 E2E catalog 把“目标回归用例”“机制诊断”“指标 baseline”和“产品失败 baseline”放在同一命名空间；只有少数能力可以定位到实现前、同输入、正式入口的失败 archive。**

## 1. 有明确失败链的用例

| 当前目标用例 | 可定位的失败证据 | 可以支持的结论 | 不能支持的结论 |
| --- | --- | --- | --- |
| `L01` | `20260803T142413.474927Z-4864-39fedcf5`：自然召回没有 Observation，误报未找到 | Conversation 缺少 canonical personal knowledge read 接线 | 完整个人知识产品已验证 |
| `E22` | `20260803T142932.564456Z-23720-19ba8517`：只能文字确认，无法形成 canonical delete action | 自然语言删除需要复用 lifecycle 写入口 | 所有 delete/restore 控制都需当前复杂度 |
| `E23` | `20260803T143007.354551Z-26256-84d0bf1d`：幻觉不存在的 specialist，Admission capability missing | 在 Project 已存在前提下，Conversation 缺 handoff capability | InvestigationProject 本身有真实产品必要性 |
| `E14` | B01/B02 与 E14 同输入链：旧 Conversation 无可恢复保存操作或控制文本污染 | 自然保存需要 exact-span、确认、canonical write path | 所有知识写入都必须经 Conversation |
| `L06` | 同一 workload 曾 5/9，Runtime-owned verification 后 9/9 | draft verification owner 和发送产物绑定解决该场景错误 | 所有回答都需要独立 verifier loop |
| `CTX-001/E21` | 大结果曾以 1,940,197 chars、776,720 tokens 进入上下文，或 hash/重复 refetch 导致失败 | 大 Observation 需要 artifact-backed bounded reread | 所有 Tool 输出都应采用同一分页策略 |
| `IP01` | B03/IP01 历史链暴露 verification repair lineage 死锁和无法交付报告 | 已存在 Project 的 repair lineage/completion 缺口 | Project 产品需求真实性 |

## 2. 当前是回归，不是需求 baseline

以下用例锁定已有产品或接口行为，但仓库没有为其当前完整设计找到实现前同输入失败证据：

- `PLAN-001`：已有 Project 的查询、steering 和 Web restart recovery；
- `ASK-001A/B`：当前统一 Conversation answer owner 的结果；
- `E05/E09/E10/E11/E12/E13`：现有 Application API 的纵向行为；
- `DUR-001/OBS-001`：当前 trace scope 与诊断行为；
- `L02/L03/L04/L05`：当前 loop 的并发、恢复、delegation 和 budget 行为；
- `E16/E17/E18/E19/E21`：当前 Provider profile；
- `LT01–LT08、LT10–LT13`：当前 Investigation runtime protocol；`LT09` 因未执行 Conversation 对照已删除。

这些测试通过只能说明当前行为受到回归保护，不能作为新增 Aggregate、Queue、Planner、Projection 或治理机制的需求来源。

## 3. 为设计而构造的风险

当前用例存在以下模式：

| 模式 | 当前实例 | 风险 |
| --- | --- | --- |
| 用户输入主动要求设计独有能力 | `E23/PLAN-001` 明确要求后台、进度、暂停、调整 | 场景恰好命中 Project 全套能力，但没有真实需求来源 |
| 直接构造内部 contract | `IP01` 直接传 requirements、budget；LT 直接构造 Plan/Command/approval | 证明机制可运行，不能证明 Agent 会自主选择或用户需要它 |
| 断言机制存在代替用户结果 | `L02` 要求两个 capability 和 concurrent batch；`E12` 断言 projection/backlink | 容易为了维护架构对象而保留测试 |
| 多条路径并排即称 paired baseline | `E24` 只记录 Research/Conversation/Project 状态 | 没有统一 scorer、同等条件和用户结果，无法比较优劣 |
| 多条独立用例拼成完整能力 | `E23 + PLAN-001 + IP01` | 没有一条测试证明自然入口到最终报告的完整用户旅程 |
| `baseline` 仅作为名称 | `CTX-001.baseline`、`RUN-001.baseline`、`DUR-001.baseline` | 名称可能被误读为实现前失败证据 |

## 4. 当前证据状态

当前工作树的机器门禁事实：

```text
target revision: 61ffadb041e7424892f5b9948fcd0e484f3b4ad6
target dirty: true
same-revision trusted product evidence: 0
same-revision trusted loop evidence: 0
release capabilities: all unverified
```

历史 archive 可以解释缺陷和设计决策，但不匹配当前 dirty revision，不能成为当前发布证据。
