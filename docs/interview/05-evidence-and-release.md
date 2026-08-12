# 证据、指标与发布资格

> **当前 catalog 有 46 个 case：24 个 release-eligible、22 个 diagnostic；这些证据覆盖多条产品旅程和运行机制，但当前工作树没有 clean matching revision 的完整发布矩阵。** 定向通过与版本可发布是两个独立判断。

## 1. 三种证据回答三种问题

| 问题 | owner | 合格结论 |
| --- | --- | --- |
| 用户目标是否在生产主路径达成 | 正式入口 Product E2E | 该 archive 下结果与反事实成立 |
| 机制是否遵守不变量 | Unit/Contract/Integration/Runtime Conformance | 指定机械边界成立 |
| 目标 revision 是否具备发布证据 | release gate | eligible matrix、archive、commit、clean tree、checksum 匹配 |

Tool `ok`、模型 JSON、数据库新增、子 Agent completed 和 Trace 命中都只是局部事实，不能替代用户结果。

## 2. 机器 catalog 是唯一分类 owner

**编号、类型、入口、provider profile 和 release eligibility 只在 [evidence_catalog.py](../../evals/e2e_quality/evidence_catalog.py) 定义。** 当前机械统计：

| 分类 | 数量 | release 角色 |
| --- | ---: | --- |
| Product Capability | 17 | release-eligible |
| Complex Loop | 9 | 7 eligible，2 diagnostic |
| Capability Profile | 5 | diagnostic |
| Durable Investigation | 12 | diagnostic conformance |
| Boundary Evaluation | 3 | diagnostic |
| **合计** | **46** | **24 eligible，22 diagnostic** |

Markdown 不复制完整 case 清单。用例移动、分类变化和 required set 由 catalog/release gate 测试机械约束。

## 3. 代表性产品 E2E

| 用户旅程 | case | 证明结果 | 关键反事实 |
| --- | --- | --- | --- |
| Conversation | E01 | 直接回答、澄清和多轮继续 | 不伪造执行对象、不跨会话泄漏 |
| Grounded answer | ASK-001A、ASK-001B | personal-only 与 personal + official web 统一由 Conversation 回答 | 不跨 principal、不写 Claim、不产生第二答案链 |
| Conversation → Project | PLAN-001 | 读取、steer、Web 重启后恢复同一 Project | 不创建第二 Project、不复制 Plan |
| 显式保存 | E08/E14 | Ask 后显式保存 exact user span | assistant/control 语义和确认前均零写入 |
| 删除与恢复 | E04/E10/E22 | 删除一次、可恢复、可 replay | 跨 scope 拒绝、replay 无新副作用 |
| Research/Scheduled Intelligence | E05/E13 | Run、Digest、Delivery、Feedback 闭环 | running 不算完成、Delivery 不重复 |
| Durable 调查 | E23/IP01 | 自然目标创建 Project 并交付可追溯报告 | 创建不算完成、缺 coverage/evidence 不完成 |
| 重启 scope | DUR-001 | owner 恢复读取，另一 principal 不可读取 | 私密内容零泄漏、拒绝可诊断 |

准确 test node 与环境要求以 catalog 为准。

## 4. Complex loop 与 diagnostic 的边界

**Complex loop 的用户输入不能指定 Tool、顺序、并发或终止；这些只在执行后通过 Trace/Receipt 断言。**

- `L01/L07`：自然知识召回与跨会话保存后召回；
- `L02/L03/L04`：安全并发、进程恢复、父子 Agent 综合；
- `L05/L06`：预算 fail closed 与 Runtime-owned verified revision；
- `CTX-001/RUN-001`：冻结外部边界后诊断 Context 增长和 batch budget，因此不参与产品完成率。

Capability Profile、LT Project conformance 和 Boundary Evaluation 可以精确指定 Provider、checkpoint 或故障注入；正因为它们是白盒机制证据，不能单独冒充产品能力。`GOV-001` 证明外部内容不获得控制权，`OBS-001` 证明 scope 拒绝不泄漏且可定位，`E24` 保留 Research 边界的 paired diagnosis。

## 5. paired evidence 只支持对应设计

| 机制 | baseline | target | 可支持的结论 |
| --- | --- | --- | --- |
| Observation 驱动知识读取 | 无知识 Observation、返回 clarification | 命中本用户随机事实并排除冲突 principal | committed Observation 是回答依据；不证明所有 Tool 选择 |
| span、确认和写入口分离 | 控制语义被写入 Claim | exact Claim +1；确认前/控制语义/replay 新写入均 0 | 保存边界有效；不覆盖 assistant candidate 保存 |
| 有界 Observation 与重读 | 1,940,197 chars、776,720 tokens | 12,138 chars、26,424 tokens，精确地址/行号 | 卸载显著降低该 workload 输入；CTX-001 仍是 diagnostic |
| Runtime-owned verification | 同输入 5/9 | 9/9 | 用户明确要求审查的路径更稳定；不外推所有回答 |
| principal 与 execution ref 分离 | 重启后跨 principal 返回私密内容 | owner 恢复；cross-principal 404；泄漏 0 | DUR-001 范围内 scope 恢复成立；不证明完整 RBAC |

Archive 坐标和更完整数字保留在对应 ADR/trace，不在多篇 interview 文档重复。没有执行本框架与外部框架的同输入 A/B，因此不能声称整体完成率、成本、延迟或维护性优于其他 Agent。

## 6. EVAL-001：能测当前 runtime，不制造比较结论

**`MeasurementProfile`、`CaseMeasurement` 和 `metrics_report` 只聚合同 profile、checksum-sealed archive。** 输出包括：

- goal completion 与 recovery success；
- input/output/total tokens；
- model turns/calls、Tool/Agent calls；
- case/recovery latency、replay new side effects；
- measurement completeness。

缺失 usage 标记 unavailable，不记为 0；不同 model/provider/prompt/budget/catalog/fixture profile 拒绝混合；diagnostic case 不进入产品完成率。**这解决了同 profile 可比测量，没有凭空产生第二 runtime 的 A/B。** 只有真实替换决策出现后，才在相同 workload、模型、Provider、Prompt、预算、fixture 和重复次数下增加对照 profile。

## 7. 为什么当前不能说“可发布”

**Release gate 只有在证据、代码 revision 和工作树一致时才允许通过。** 至少核对：

1. catalog eligible set；
2. required cases 全部通过且未 skip；
3. trace envelope、summary 和 checksum 完整；
4. archive commit 与目标 revision 相同；
5. archive 和目标工作树 clean；
6. summary exit status 为 0。

当前准确说法是：

> 已有多条正式入口定向 E2E 与机制诊断；当前工作树尚未形成 clean matching revision 的完整 eligible matrix，因此不能把这些定向结果升级为版本发布资格。

## 8. 可复现入口

```powershell
$env:PERSONAL_AGENT_REQUIRE_LIVE_E2E = "true"
$env:PERSONAL_AGENT_E2E_TRACE_DIR = "data/e2e_traces"
uv run pytest evals/e2e_quality --e2e-scope=release `
  --e2e-require-complete-matrix -q -s
uv run python -m evals.e2e_quality.release_gate --trace-root data/e2e_traces
```

指标报告示例与 profile 约束见 [evals/e2e_quality/README.md](../../evals/e2e_quality/README.md)。

## 9. 证据边界不是默认 backlog

**证据边界不能自动升级成开发任务。** 当前不能声称 principal ownership 等于完整 workspace/RBAC、assistant candidate 可安全自动写入、所有 Project provider 组合已通过 live E2E、或 checkpoint 天然保证外部 exactly-once；只有真实业务扩展、失败产品 baseline 或可量化工程约束成立后，才进入 future。
