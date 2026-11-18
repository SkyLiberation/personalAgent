# ADR 0042：保留原生模型工具会话

状态：接受；生产候选已接入，协议及真实阶段局部验证完成，完整流程未验收。

## 问题与依据

MiniMax 真实首轮在反馈后重复非法参数，当前消息仅为状态快照。官方工具循环要求完整 assistant 消息、思考字段和按 ID 配对的工具结果。此前 Python 参数变更没有保存该协议，不能把旧局部通过外推为本模型可靠。具体事实及唯一方案见[原生续接规格](../optimization/model-provider-transport.md#2026-10-23-原生工具会话续接规格)。

## 决定与责任

既有 Model Port 传递 host/model 绑定的 typed 原生响应 envelope；外部 payload 由 Adapter 验证并保真，Application 不识别具体 reasoning 字段。Conversation Journal 与用量一并提交当前 run 的决策响应和必要的控制接纳／延期事实。工具执行、拒绝、计划及业务操作仍归原 owner，发送时从 canonical 事实派生 tool 消息，不建立第二执行账本。

完整消息按原调用顺序续接，错误调用保留原参数并交回真实拒绝；准备提交、计划接纳及业务待确认各自表达其真实边界。恢复不调用模型或重执行来填补历史，host/model、scope、配对或原件不匹配时明确拒绝。压缩按完整已结算交换移出，来源摘要覆盖 assistant 原文；不经原生历史重新引入已压缩资料。

## 取舍、复杂度与验证

2026-10-30 在独立 Python 分析路径引入跨用户轮次续接。原用户前缀和实际终答均匹配时，原生交换投影到对应历史答复前。`before_message_index` 仅决定当次请求位置，由 Adapter 按 host／model 核对后组装。Journal 继续保留原件。历史六轮验证了特定跨轮边界，用户结果为 4/6。现行历史按选中任务恢复。[跨轮证据](../optimization/completed/conversation-tool-history.md) · [任务历史决定](0048-conversation-goal-maintenance.md)

2026-11-05 扩展决定。等待目标维护时，整批动作因未声明名称在执行前被拒，模型输入以单条有位置的 Runtime 反馈替换整对原生消息。该消息说明本轮唯一可推进任务的目标维护路径。原始响应和拒绝仍保存在 Journal。其他执行和参数修复继续保留原生配对。新增输入变体只参与请求物化与封存，不拥有执行事实。依据和验收见[动作拒绝反馈设计](../optimization/to_verify/conversation-loop-boundaries.md#312-动作协议拒绝的事实反馈)。

保留现状和提高思考深度都不能补齐服务方协议；不同时修改工具 Schema、提高权限或增加通用 Provider 平台。新增必要的 Port envelope／exchange、run 内决策与控制记录及一个会话物化模块；删除受影响入口仅用全量状态快照替代工具会话的路径。新模型输出无新增字段。

初版同 run 验证中，真实阶段回放 5/5，SDK 对照 4/4，原件压缩及恢复边界通过。一次固定配置的实际续接返回合法参数，36,568 tokens，未执行工具。旧 `prepare_final` 的通过记录属于当时的协议，现行答复见 [ADR 0045](0045-native-intent-loop-and-recorded-model-output.md)。各阶段的原件、失败及费用按原规格追溯。
