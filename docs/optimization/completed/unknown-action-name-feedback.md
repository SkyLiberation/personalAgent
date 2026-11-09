# 未声明动作名称的反馈保真

**未知动作拒绝现在准确回送首个未声明名称，原整批拒绝和有界停止保持。** 本结论只关闭确定性事实投影缺项；模型纠正和研究完整交付仍由原验收负责。

## 问题、方案与接入

研究 E1 v9 的真实 e5／fae 响应都提交未声明的 `tool_control_working_plan`。decoder 已取得具体名称，但没有填入已有 `StructuredOutputFailure.action_name`，Conversation 只收到泛称。原 `rejected_action_invocations` 已完整回显，不能据此声称模型没有收到反馈，或将后续失败归因为此。

正式路径继续为 HTTP → Conversation → Native Adapter → `decode_model_action_invocations` → 原反馈入口。decoder 在唯一未知名预检查填写具体 `action_name`，删除后续遍历中重复且不可达的未知名分支。反馈保留 reason、全部原 call_id／名称／参数和空 diagnostics；未声明动作没有可据以判断参数的合法 Schema。

`_repeated_action_feedback` 对 `provider_action_unknown` 显式保持原协议错误族分组，具体名不产生新重试额度。其他错误的分组、Plan revision、成功进展重置及两个决策轮停止保持。模型继续决定下一步；Runtime 不改名、解包、生成计划或执行合法 sibling。两处既有 owner 完成修改，无新增模型、字段、状态、Prompt、配置或权限。生产代码相对 v9 为 6 行增加、8 行删除，净减 2 行。

## 决定性证据与范围

设计先在主循环 Spec 固定 `APF-UNKNOWN-1`（具体对象保真）和 `APF-UNKNOWN-2`（原停止边界），再实现。来源为[原 v9 封存](../../../.tmp/research-capability-20261020/t5/e1-v9-final-seal.json)，方案经[同轨 critic](../../../.tmp/research-capability-20261020/t5/e1-v9-protocol-boundary-critic.md)核对；固定的 OpenHands／Gemini 实际错误回送机制只支持事实绑定，不证明本地模型收益。

| 检查 | 已执行结果 | 边界 |
| --- | --- | --- |
| 原实现问题恢复 | [首次 baseline](../../../.tmp/research-capability-20261020/t5/unknown-action-feedback-baseline-1/report.json)恢复 e5 完整请求／响应及原泛称反馈 | 零模型，不是新 E2E |
| 同轨原实现反事实 | [完整 baseline](../../../.tmp/research-capability-20261020/t5/unknown-action-projection-baseline-2/report.json)实际加载原 ZIP decoder 和原停止函数；两份反馈及完整 7f／fae SDK kwargs 与原件相同 | report 的 sources 是准备时工作树身份；实际执行的两份原源码另由该目录 checksums 绑定 |
| 当前实现 | [完整 candidate](../../../.tmp/research-capability-20261020/t5/unknown-action-projection-candidate-2/report.json)对两份真实坏响应严格整批拒绝；19 项原声明、生产物化、原生修复和完整下一轮 kwargs 只改变对应反馈动作名 | 首次未知名不提前停止、第 7 轮仍停止；不同未知名的族分组为静态核对，未伪造额外运行样本 |
| 状态及原件保真 | typed Trace 往返成立，原 v9 全文件及首次 baseline 保持，零模型／业务准入／执行 | 不生成执行或完成事实 |
| 独立实现审查 | [限定审查](../../../.tmp/research-capability-20261020/t5/unknown-action-projection-implementation-review.md)只读重核原件、全部回放 checksum、唯一字段差异及停止消费者，未见阻断 | reviewer 未重跑回放或模型，不作为第二组运行 |

实际命令为 `.venv\Scripts\python.exe -B -X utf8 .tmp/research-capability-20261020/t5/unknown_action_projection_replay.py baseline` 和同脚本 `candidate`，均 exit 0。临时脚手架首次因原源码相对导入缺 package identity 而在模型／业务前失败，保留原目录；只修正隔离模块身份后形成独立第二版回放，没有生产试补或挑模型成功样本。旧 E1 的 limitation、9 次物理调用、费用和缺交付结果不改判。

## 重新打开条件

后续真实 E2E 或其实际阶段产物再次证明已知拒绝对象没有进入反馈、原调用被改写、坏批次部分执行，或该投影扩大停止额度时，重新打开对应需求。模型仍生成非法提议或整体研究失败不单独推翻本事实保真结论。生产可见契约见[工具专题](../../topics/tools.md)，未完成的模型验收及研究结果见[研究 Spec](../to_verify/knowledge-decision-delivery.md)。
