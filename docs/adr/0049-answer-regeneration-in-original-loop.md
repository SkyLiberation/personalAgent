# ADR 0049：普通回答拒稿后沿原循环重新生成

状态：最小实现及正常完整提交已验证，独立审查通过；前三轮3/3交付、原分[1,1,0]。回答拒稿后重生成未自然触发，第三轮用户结果失败，见[记录§36](../optimization/to_verify/verify_results/analysis-correctness.md#36-普通回答改为原循环完整重提的连续前三轮)。日期：2026-11-03。

## 背景与决定

task2全量尝试第三轮的真实回答核验反馈已经进入原Loop；主模型继续计算后，两次调用答案按段修订工具均输出错误段号类型，Runtime按原有界修复规则停止，用户未收到答案。完整正文重提本来就可达，保留另一套编辑参数不是本次任务完成的必要前提。原失败见[记录§35](../optimization/to_verify/verify_results/analysis-correctness.md#35-当前实现的task2全量连续运行)。

用户要求参考smolagents的反馈后循环重新生成方式。本决定取消普通回答的revise_final操作及其段落编辑模型，由原Loop消费核验反馈、继续取证或提交完整新回答；普通正文和submit_final共用原FinalMessage、SubmittedFinal、核验及Completion出口。目标、引用、执行、核验与历史事实不新建owner。

## 参考、差异与防护

固定smolagents `96f33fa` 的配置式final_answer_checks失败写入真实记忆并进入下一步，模型重新提交完整结果；固定PydanticAI `922ee561` 的校验失败按原调用交回循环。源码装配与边界见[现有参考](../agentRef/model-interaction-protocols.md)，不将第三方可选检查或最大步数兜底当作本工程Completion契约。

本决定替代[ADR0031](0031-complete-final-revisions.md)的普通回答局部合并路径。其引用丢失背景保留历史身份：完整原稿与引用仍进入当前历史，新稿的必要引用须重新选择并由原binder／Verifier检查，不保证模型自动保留，也不允许Runtime擅自添加。claims的业务局部修订与逐项证据关系保持，不因删除普通段落编辑而删除。旧封存run使用原冻结源码解释，不保留兼容别名、旧Schema或自动转换。

## 责任、复杂度与验证

2026-11-03 的全量运行复现了主循环反馈投影缺口：只留最新判决且置于旧回答之前。现按[目标维护 Spec §9.18](../optimization/to_verify/analysis-goal-maintenance.md#918-核验反馈与实际修复按原交互进入主循环)修正，原生交换通过 `runtime_feedback` 携带该次决定后真实产生的回执，Adapter 按原时间顺序发出 Runtime 消息。Journal 仍为唯一 owner；原始 assistant 和工具配对不变，提交动作的接纳不能覆盖后续核验失败。完整判决及修复在合法压缩前持续保留，确定性历史回放与语义收敛分别验收。

随后[新真实全量运行](../optimization/to_verify/verify_results/analysis-correctness.md#38-完整反馈历史候选的-task2-全量连续运行)复现跨 run 同号回执被误删及压缩后仍超容量，反馈保留范围已重新打开，当前不作整体历史契约通过声明。保留完整重提入口和已成立配对，不恢复旧编辑工具或无界重跑；下一修正先重审身份及压缩边界。

Conversation内DirectAnswerResult负责解释完整模型输出；Service拥有原循环与门禁，Journal保存唯一真实交互。删除一个操作、四个专用类型和一个合并模块及双语资源，无新增工具、字段、模型阶段或存储。代价是普通修正需重新提交完整正文及必要引用；实际输出量、成本与语义另计。

唯一设计及先行验收由[目标维护Spec §9.16](../optimization/to_verify/analysis-goal-maintenance.md#916-回答拒稿后沿原循环重新生成)拥有：新空会话连续前三轮，实际依赖产物滚动，原用户结果和协议检查分别计分，无隔离模型回放或重采。若真实新输入复现必要引用丢失或新循环无法完成，保留失败并按最早责任重审；不能据结构简化声称目标理解已解决，也不静默恢复旧协议。
