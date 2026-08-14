# 证据分类

**一条测试是否端到端，由入口、生产路径、语义决策、真实边界和用户结果共同决定；文件名、HTTP 请求或真实数据库都不能单独使它成为 Product E2E。**

## 当前采用的分类

| 分类 | 必须具备 | 可以使用的替代 | 能证明 | 不能证明 |
| --- | --- | --- | --- | --- |
| Product E2E | 真实目标用户、自然输入、正式用户入口、生产主路径、真实模型、用户可观察结果和关键反事实 | 只允许替代不可控第三方、付费边界或危险副作用，且 Fake 实现生产 Port | 该用户目标在该 profile 下成立 | 设计最初有必要、所有用户场景、框架优越性 |
| Application E2E | 正式 API/CLI/Application Use Case、生产 Domain/Store/Runtime、结果契约 | 外部 Provider 可冻结 | 某个正式 Application contract 从入口到结果成立 | Agent 能从自然语言自主选择该能力 |
| Runtime Conformance | 真实 Application/Domain/Store，可精确构造 Command、Plan、故障或 Provider outcome | scripted model、frozen provider、故障注入 | 幂等、恢复、状态迁移、Admission、Completion 等机械协议 | 用户会提出该目标、模型能做出正确语义决策 |
| Integration | 两个或多个生产组件的协议与装配 | 边界 Fake/Stub | 组件间契约可执行 | 完整用户目标 |
| Capability Profile | 真实 MCP/A2A/外部 Provider 和生产 Gateway | 通常不使用 Provider Fake | 特定连接器/profile 可用 | 本产品需要该 Provider、完整产品完成率 |
| Offline semantic eval | 冻结数据集、runner、scorer、统计阈值 | 模型或检索器可按 profile 替换 | 指定数据分布上的语义质量 | 正式入口、持久化、恢复和副作用正确性 |
| Unit/Contract | 单一 owner、不变量或 Port contract | Fake/Stub 普遍允许 | 局部确定性规则 | 端到端用户结果 |

## Product E2E 判定

一条 Product E2E 同时满足：

1. Persona 和需求来源可以说明，不是为了命中某个内部机制而创造；
2. 用户输入不指定 Tool、Agent、Plan、Project、内部 ID、并发方式或完成状态；
3. 从用户实际可接触的 HTTP、CLI、消息或 UI 入口进入；
4. 模型、Application、Domain、治理、持久化和实际 Provider 走生产装配；
5. 断言最终答案、可读报告、实际知识变更、实际投递或明确 limitation；
6. 同时断言关键错误结果没有发生；
7. 如果用于准入产品变更，存在同输入、实现前失败 archive；
8. 如果用于发布，archive 与 clean 目标 revision、profile 和 checksum 一致。

## Test Double 边界

冻结外部只读资料可以用于重复性测试，但证据范围随之缩小：

- `CTX-001` 的 frozen MCP 可以证明 Conversation/MCP/Gateway/Context materialization 对固定大文档的行为；不能证明真实 GitHub、Notion 或 Web Provider 的可用性。
- `GOV-001` 的恶意文档和隐藏 Tool 是安全协议测试；它不是自然产品旅程。
- `RUN-001` 的固定 A/B/C records 用于验证 budget admission；它不是外部资料读取质量 E2E。
- 当前 12 个 `LT` 用例（`LT01–LT08、LT10–LT13`）使用 scripted semantic decisions 和 frozen providers，属于 Runtime Conformance，不属于 E2E；伪造 Conversation 对照的 `LT09` 已删除。

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
