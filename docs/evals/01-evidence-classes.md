# 证据分类

**一条测试是否端到端，由入口、生产路径、语义决策、真实边界和用户结果共同决定；文件名、HTTP 请求或真实数据库都不能单独使它成为 Product E2E。**

## 当前采用的分类

类别名称解释 canonical catalog；新验证方式与停用范围由 [QLT](../devSpec/quality-security.md#1-测试职责与覆盖)拥有。以下局部分类不自动成为需要新增或运行的套件。

| 分类 | 必须具备 | 可以使用的替代 | 能证明 | 不能证明 |
| --- | --- | --- | --- | --- |
| Product E2E | 正式用户入口、完整生产链、真实模型、用户可观察结果和关键反事实 | 不替换结果依赖的真实决策或执行边界 | 该用户目标在该配置下成立 | 设计最初有必要、所有场景、框架优越性 |
| Application Integration | 正式 API/CLI/Application Use Case、生产 Domain/Store/Runtime、结果契约 | 外部 Provider 可冻结 | 某个正式 Application contract 从入口到结果成立 | Agent 能从自然语言自主选择该能力；完整用户目标已经满足 |
| Runtime Conformance | 真实 Application/Domain/Store，可精确构造 Command、Plan、故障或 Provider outcome | scripted model、frozen provider、故障注入 | 幂等、恢复、状态迁移、Admission、Completion 等机械协议 | 用户会提出该目标、模型能做出正确语义决策 |
| Integration | 两个或多个生产组件的协议与装配 | 边界 Fake/Stub | 组件间契约可执行 | 完整用户目标 |
| Capability Profile | 真实 MCP/A2A/外部 Provider 和生产 Gateway | 通常不使用 Provider Fake | 特定连接器/profile 可用 | 本产品需要该 Provider、完整产品完成率 |
| Offline semantic eval | 冻结数据集、runner、scorer、统计阈值 | 模型或检索器可按 profile 替换 | 指定数据分布上的语义质量 | 正式入口、持久化、恢复和副作用正确性 |
| Unit/Contract（历史分类） | 单一责任主体、不变量或 Port contract | 按原证据解释；后续不新增或运行等价单元套件 | 历史局部确定性规则 | 当前验收或端到端用户结果 |

## 证据分类与横切验证不能混用

每条 catalog 用例在 `evidence_catalog.py` 中只能拥有一个证据分类。Tool Calling、MCP dispatch、A2A Artifact 返回等横切套件不是新的证据类别，而是对同一份密封 Trace 的机制检查；同一用例可以进入多个套件。报告必须并列保留整例 `pytest_outcome` 和关键检查点结果，不能用机制通过覆盖 Product、Provider 或用户结果失败。

只有现有用例无法承载新的用户目标、入口、初始事实、故障边界或关键反事实时才新增 E2E。共享 Observation、Receipt、Artifact、policy fact 或局部不变量时，优先在 `validation_catalog.py` 中增加 typed 检查点，不复制 live workload。

## Product E2E 判定

资格由[根规范](../../AGENTS.md#21-证据先于设计)和 [EVD](../devSpec/change-evidence.md#2-产品-e2e-的最低资格)拥有。用户本来要求具体外部服务或可见计划时保留该需求；禁止的是为命中内部实现而伪造输入。预期成功用例的 `limitation` 仍是失败，合法终态不自动表示用户目标满足。发布另受 [EVM](../../evals/AGENTS.md#6-运行与声明)的目标版本与完整矩阵约束。

## Test Double 边界

冻结外部只读资料可以用于重复性测试，但证据范围随之缩小：

- `CTX-001` 的 frozen MCP 可以证明 Conversation/MCP/Gateway/Context materialization 对固定大文档的行为；不能证明真实 GitHub、Notion 或 Web Provider 的可用性。
- `GOV-001` 的恶意文档和隐藏 Tool 是安全协议测试；它不是自然产品旅程。
- `RUN-001` 的固定 A/B/C records 用于验证 budget admission；它不是外部资料读取质量 E2E。
- 历史 12 个 `LT` 用例（`LT01–LT08、LT10–LT13`）曾使用 scripted semantic decisions 和 frozen providers，只能作为 Runtime Conformance；当前可执行节点均已删除，归档保持只读。

## 用户结果与内部事实

以下断言不能单独作为 Product E2E 的 Then：

- `state == success/completed`；
- Plan、Project、Command、Receipt 或数据库记录存在；
- Tool/Agent 被调用；
- trace 命中特定 capability 或并发 batch；
- digest、projection、coverage 字段非空；
- Verifier 返回 passed；
- Worker 正常退出。

这些事实可以作为 path evidence 或反事实，Product E2E 仍需断言用户实际取得的结果。
