# ADR 0018：将语义验证绑定到可见执行证据

- 状态：Accepted
- 日期：2026-09-01
- 影响范围：Conversation Context Materialization、Runtime Verifier 输入契约、Verification 相位迁移
- 当前事实：[Verification 与 Completion](../topics/verification-and-completion.md)

## 1. 背景与决定

clean `HARNESS-003` 证明答案模型与 Runtime Verifier 的事实视图不一致：前者看到当前 interaction 的 typed execution inputs，后者只看到草稿、criteria 和 URL refs。Verifier 因此把缺少精确来源事实的草稿错误分类为 `needs_revision`，Runtime 按 ADR 0017 合法地关闭动作能力并继续文字修订，最终耗尽预算。

本 ADR 决定：Runtime 调用 Verifier 时，增加由当前已提交 `ActionObservation` 确定性重建的有界 `execution_evidence`。Verifier 仍拥有开放世界语义判断；Application 只决定 Visibility、物化投影和既有 verdict 相位迁移，不按关键词判断 Goal，也不把 Receipt 或 Tool success 改写为完成。

## 2. 机制依据与本地证据

[OpenAI Graders API](https://developers.openai.com/api/reference/resources/graders)允许 model grader 同时消费待判输出和数据项 reference；[Claude Code Hooks](https://code.claude.com/docs/en/hooks)让 stop/agent verifier 读取 transcript、最终消息以及必要的文件或测试结果。共同模式是把判定所需事实提供给独立判断者，而不是只发送标准文本。

本地失败归档为 `C:/pae/harness003-adr16-clean-target-e8ab48f-20260901/harness-003/target/20260901T080629.144958Z-33432-31cdf9b1/`，绑定 clean `e8ab48f` 且 checksum 全部匹配。Plan 恢复、无重复原始读取和 Action/Final 分相均成立；Verifier 两次返回 `needs_revision`，最终 `limitation`。这证明当前最早失败位于 Verification evidence boundary，不证明候选已经修复。

## 3. 事实 owner、写入口与依赖方向

| 责任 | owner | 约束 |
| --- | --- | --- |
| 执行事实 | `ActionObservation` / Journal | 仍是唯一 canonical 记录，不增加镜像写入口 |
| Verifier 可见投影 | Conversation Application | 请求时从当前 inputs 重建，只含成功、非 Verifier Observation，并复用既有有界物化 |
| criterion 语义状态与整体 verdict | Verifier 模型与 Verifier adapter | 模型逐条判断；adapter 按 `insufficient_evidence`、`not_satisfied`、全满足的顺序确定性聚合，并在汇总缺省时只复用逐判据 feedback，不得生成执行事实或 Completion |
| 相位迁移 | Conversation Application | 沿用 ADR 0017；不增加启发式路由 |

依赖方向保持 `Application -> Capability Port`。`personal_agent.tools` 的 workflow adapter 消费字符串化的 typed Observation 投影，不反向拥有 Application 状态。投影不持久化，无迁移数据和兼容窗口；内部 Schema 直接破坏式替换全部 Runtime 调用者与测试。

## 4. Complexity Justification 与未采用方案

新增一个纯物化函数和一个 verifier 参数；不新增表、Repository、状态、重试、Planner、Workflow 或模型决策回合。生产消费者只有 Runtime Verifier，但该职责不能并入 URL refs：URL identity 与执行返回内容是两类不同证据，混装会让字段名和安全边界失真。

未采用：

- 用确定性关键词或正则直接通过草稿，因为任意用户标准属于开放世界语义；
- 无证据时一律 `needs_revision`，因为文字修订无法创造缺失事实；
- 把全部 Journal 或未裁剪 Tool payload交给 Verifier，因为会绕过 Context Budget Materialization；
- 增加固定 token、回合或 Verifier 重试，因为当前 baseline 已定位为输入缺失而非预算太小；
- 为 `HARNESS-003` 写专用口令比较器，因为它不能成为生产语义 owner。

## 5. 验证、回滚与退出条件

Contract 必须证明投影的 scope、成功状态过滤、Verifier Receipt 排除、bounded materialization、Runtime 到 workflow capability 的参数传递，以及混合 criterion 中 `insufficient_evidence` 的聚合优先级。本项恢复 Verifier 已有 verdict 契约，不要求正式消融；普通 Conversation Product E2E 仍须验收用户结果。

`HARNESS-003` 只保护跨轮 Plan 绑定事实的恢复与消费，使用正常生产预算，不规定特定 Verifier、Final-only 或 Completion 轨迹。曾追加的一回合动作预算和内部相位断言混合了概率性取证与确定性边界，现已撤回；其两份失败归档保持历史诊断证据，不冒充通过的 Conformance。

最终实现的定向 Conversation、Structured Model、Trace Archive 与 Evidence Catalog 回归为 `194 passed`；Ruff 通过。Contract 覆盖成功 Observation 投影、失败与 Verifier Observation 排除、Runtime 到 workflow capability 的真实参数传递、混合 criterion 中证据不足优先于文字修订，以及汇总反馈缺省时从逐判据反馈确定性派生。这些是工程边界证据，不替代 Product target。

正常预算 Product target 已在最终代码通过；同输入的前一份正式路径归档还证明 Final 提交后 Runtime Verifier 实际消费了执行证据投影，并暴露出汇总反馈缺省问题。最终通过样本不要求复现特定 Verifier verdict 或内部相位；详细归档、指标和证据职责见[当前评测用例盘点](../evals/02-current-case-inventory.md)。

如果 target 仍最早失败于同一 Verifier 分类，或实现需要新持久状态、专用语义解析、无界证据、额外重试或预算扩张，则撤回本 ADR，删除字段和投影函数。回滚依赖版本控制，不保留 flag、alias、fallback 或双轨工具契约。
