# ADR 0025：可修订的 Plan 进度与执行、交付事实分离

2026-09-16 决定。2026-11-11 更新工作清单的读写和审阅协议。现行入口见[Runtime](../topics/runtime.md#conversation-loop)，原缺陷与正式证据见[推进记录 §108](../optimization/revision-feedback-loop.md#108-plan-生命周期整体修正)。

## 背景与决定

模型把三项进度标记为完成后，三个合法读取或搜索被 `working_plan_terminal` 拒绝，原任务未交付。进度既被用作执行门禁，又被用作不可修订证明，阻断了后续补证。

模型通过 `control_working_plan` 提议进度，Admission 校验步骤身份、最多一个活动项和审阅状态。已完成步骤可重开。无活动项时原业务动作可按合法权限执行，执行网关记录空关联；有活动项时绑定该步骤。Journal 恢复已接纳清单及版本，原执行事实保持。最终稿通过原交付契约后才结算工作项。对答复的独立提交及核验见 [ADR 0055](0055-unified-conversation-answer.md)。

空参数读取；提交 `steps` 默认替换，`merge: true` 按 ID 更新和追加。常规更新继续执行，用户需要审阅时走明示 `wait_for_user` 的路径。成功回执绑定调用时的清单与版本，压缩后投影进度而非制造新写入口。[读写及上下文决定](../optimization/completed/working-plan-context.md)

## 取舍与验证

复用原 Plan、Journal 和执行网关，删除已完成状态导致的工具禁用、不可修订规则和按进度切换交付的推导。Gemini CLI、OpenHands 的职责分离，以及 Hermes 的读写与压缩规则，分别用于验证设计取舍。[早期源码对照](../optimization/revision-feedback-loop.md#106-plan-完成状态与继续执行的源码对照) · [Hermes 固定实现](https://github.com/NousResearch/hermes-agent/blob/f19432adb7ac4aa2920797a7d092d3987012d4b2/tools/todo_tool.py#L26)

原正式运行三次在清单已完成后成功补证，后因重复无据缺项句主动停止。11 月的中英文离线回放覆盖读取、替换、合并、审阅和恢复，一次真实工具决策提交 6 项并请求审阅，计 3,965 tokens。该轮未执行完整 Product E2E。若进度修订破坏身份、审阅、执行事实或最终验收，按触发该失败的用例回退并复审。
