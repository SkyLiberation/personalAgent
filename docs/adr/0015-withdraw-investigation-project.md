# ADR 0015：撤回无需求 baseline 的 Investigation Project

- 状态：Accepted，已实施
- 日期：2026-08-26
- 影响范围：Conversation、AgentGateway、Web API、worker、PostgreSQL、E2E 与项目文档

## 1. 决策

删除 `InvestigationProject` Application Capability、Product Aggregate 和第二套研究循环。普通研究只从 `Conversation -> Tool/Agent Gateway -> Observation/Artifact -> Verification -> Completion` 进入；明确要求响应结束后继续运行、稍后查询或 steering 时，返回 typed `capability_missing`，不创建后台事实，也不伪造同步成功。

GPT Researcher 继续作为 Conversation 可委托的 A2A 执行资源。`AgentGateway` 拥有 submit、poll、cancel、timeout 和 `AgentArtifact` 执行事实；父 Conversation 继续拥有用户 Goal、工作清单、Verification 与 Completion。

## 2. 为什么删除

旧设计先让测试指定“后台调查、稍后领取或 steering”，再断言 Project 被创建。它证明机制可被选择，没有证明普通 Conversation 因缺少独立生命周期而无法满足真实需求。

删除前的后台组为 `20/20 project_selected`、`0/20 delivered`，四 worker 候选也为 `0/20 delivered`。同期普通 Conversation 对照为 `0/20 delivered`，两条路径的研究质量问题仍独立存在。

旧机制横跨 Application、Domain、PostgreSQL Adapter、Web API、worker、Conversation 分支以及专用测试和消融资产。不同表、ID 和写入口只能证明事实没有双写，不能证明两套目标分解、执行、修复和完成循环在产品上都必要。

## 3. 同身份 baseline、target 与配对

`BACKGROUND-CONTINUATION-LIMITATION-001` 使用四类自然后台请求，每类重复五次。baseline 与 target 的 case、用户输入、principal、正式入口、初始状态和 grader 完全相同，只改变代码状态。

| 对照 | 结果 | 模型调用 | tokens | P95 |
| --- | --- | ---: | ---: | ---: |
| 机制开启 baseline | `0/20 limitation`、`0/20 capability_missing`、`20/20` 进入非边界执行 | 41 | 27,038 | 22.83 秒 |
| 删除后 target | `20/20 limitation`、`20/20 capability_missing`、非边界执行为 0 | 20 | 14,132 | 11.65 秒 |

归档：

- baseline：`data/e2e_traces/product_baselines/background-continuation-limitation-001/baseline/20260826T113052.621892Z-30036-eb7f45c0`；
- target：`data/e2e_traces/product_baselines/background-continuation-limitation-001/target/20260826T111202.670374Z-2720-e3611907`。

`python -m evals.product_baselines.evidence <baseline> <target>` 已通过 checksum 和 comparison identity 校验。延迟与 tokens 只描述这组样本，不能外推为一般性能收益。

## 4. 保留链路的回归边界

删除前后各执行一次真实 `E17`。两次均从正式入口经 `AgentGateway` 调用 GPT Researcher，得到 `timed_out` Artifact，后续未收敛并返回 `limitation`。原结果均为未交付，委托链路仍能到达原执行边界。

诊断归档分别为 `data/e2e_traces/20260826T113135.980866Z-19016-9b5c82ba` 和 `data/e2e_traces/withdrawal-e17-mechanism-on/20260826T113656.397743Z-3096-331f683e`。它们不是产品结果配对，只用于检查删除前后是否经过相同 AgentGateway 失败阶段。

同期显式委托历史组为 `10/20 delivered`。A2A 预算、服务方结果和父级来源验收各自保留原归因。

## 5. 实施与验证

- 删除 Project 的 Application、Domain、Adapter、Store、路由、facade、worker handler、Conversation intent/引用/投影，以及只服务该机制的测试、conformance 和 ablation；
- `src/`、`tests/`、`evals/` 对旧生产名称的删除审计为 0；
- 当时本地 `personal_agent_test` 的两张残留表均为 0 行，已按精确表名删除。`postgres` 数据库没有同名表；
- 历史 ADR、评测盘点和 checksum 归档保留，并明确标注为历史证据。

## 6. 重新准入条件

只有真实用户在无 Project 的正式入口稳定遭遇请求断开导致结果丢失、必须稍后查询或取消、完成后必须主动通知，或 Provider Task 过期导致结果无法保存时，后台能力才能重新进入 A0。

重新设计时优先保存有身份作用域的 Provider/A2A Task 引用与最终 Artifact。只有该最小方案无法满足已执行 baseline，才评估新的 Product Aggregate；不得恢复第二套研究 Plan 作为默认起点。
