# Conversation 动作协议的有界恢复

`CONVERSATION-ACTION-PROTOCOL-RECOVERY-001` 固化两个限定边界：结构合法但目录外的动作由 Application 整批拒绝并反馈；required action 的非法 JSON 由现有 Adapter 进行一次模型重生成，第二次仍错就失败关闭。正式装配已消费修正。**本结论不表示研究交付通过。** 同入口 target 最终因预算耗尽返回 `limitation`，原始 E2E 失败保持。

## 责任与接入状态

正式路径为 `POST /api/conversation/turn` → `ConversationService` → Composition Root 装配的 `JsonObjectStructuredAdapter` → `decode_model_action_invocations` → Admission。Adapter 校验 wire 结构，Application 使用同一份动作声明检查目录与业务参数，决策模型消费拒绝反馈；执行、Verification 与 Completion 不改变。

删除 Adapter 重复的动作目录检查，保留 `ModelActionInvocation` 的名称形状不变量和 typed 失败。零调用和非法参数 JSON 共用已有的一次协议重生成，工具 Schema 与原请求保持；代码不剥除标签、不猜测参数、不执行被拒批次。中文模板 `action.repair.system/v1` 替换旧内联英文模板，由唯一注册表消费并记录版本。错误、原始调用及未执行正文以 JSON 数据传入，保留响应全部用量。没有新增状态、表、工具、重试循环或配置开关。

当前行为由[运行时专题](../../topics/runtime.md)拥有。生产改动相对本轮冻结 baseline 为 49 行新增、19 行删除，净增 30 行；两个已有文件分别继续承担适配和模板职责，无新增类或层。

## 决定性证据与限制

证据位于[本轮归档](../../../.tmp/optimization-integration-20260928/)，全部保留原始失败和独立代码身份：

| 检查点 | 已执行结果 | 适用边界 |
| --- | --- | --- |
| 原入口失败 | baseline 首动作 `provider_action_unknown`，HTTP 503；第一次修正后回跑在真实取证后因非法 JSON 再次 HTTP 503 | baseline 未留存原始未知动作名称，不宣称逐字复现它 |
| 目录归属反事实 | [派生边界回放](../../../.tmp/optimization-integration-20260928/action-recovery/report.json)中旧 Adapter 提前抛出，新路径仍由 Application 拒绝并反馈，零执行 | 固定边界 Offline，不是 E2E |
| 真实目录拒绝后恢复 | [正式 target](../../../.tmp/optimization-integration-20260928/protocol-target/evidence/conversation-research-delivery-001/target/20260928T074210.753965Z-15176-114143be/CONVERSATION-RESEARCH-DELIVERY-001.1.trace.json)自然生成未声明的 `web_search`；整批零执行且用量入账，下一轮收到反馈后产生合法调用并执行 | 局部恢复真实到达；最终预算失败，不能写作用户交付通过 |
| 原始非法 JSON 恢复 | [条件 Offline](../../../.tmp/optimization-integration-20260928/json-recovery-v3/result.json)逐字段复用实际请求和坏响应，一次真实模型纠正通过原 Application 解码；耗时 28.13 秒，新增 47,659 tokens | 固定真实前缀，不是从空状态 E2E；原响应 47,732 tokens 纳入总用量 95,391 |
| 连续坏响应拒绝 | [同一坏响应两次的反事实](../../../.tmp/optimization-integration-20260928/json-recovery-v3/negative.json)在第二次严格解析失败关闭，零动作执行 | 不证明服务方总能纠正，也不放宽协议 |

非法 JSON 反馈请求仅新增一条 1,660 字符消息；该固定调用较原请求增加 606 input tokens。真实返回内容仍由模型决定；格式通过不证明工具选择或答案正确。正式 target 未自然触发非法 JSON 纠正，该分支的成功证据仅来自上述条件 Offline 与正式装配可达性，不能冒充另一条 E2E。

## 尝试汇总与独立阻塞

仅移除重复目录检查恢复了 Application 的责任，但不能处理另一次真实响应中 `<parameter=arguments>` 前缀导致的非法 JSON。保留第一项修正，按 Adapter 已有的协议恢复职责扩展同一次重生成；没有追加跨层参数修补。诊断脚手架两次因重建目录与原请求不同，在发出模型调用前停止；最终直接恢复已留存 wire，全部字段相等后才执行一次真实模型请求。

三个正式样本使用同一中文任务，各运行一次；最终 target 的用户结果仍为失败。原预算下取证与交付未收敛属于既有 `CONVERSATION-RESEARCH-STOP-001`，不改写为格式恢复成功。claim 隔离候选的准入由[研究论断问题](../claim-revision-nonconvergence.md)独立维护。既有 Instructor 与 Pydantic AI 固定实现只支持错误与原响应配对的边界，比较坐标见[协议输入审计](../action-final-protocol.md#输入审计与外部修复边界)，不能替代本工程证据。

## 重新打开条件

出现目录外动作被执行、坏批次部分执行、连续坏响应被放行、修复改变工具声明或权限、用量丢失、既有零动作恢复回归时，重新打开对应责任边界。服务方仍生成坏响应、后置语义失败或预算耗尽不自动否定本限定结论，也不能因此宣布整个研究任务完成。经验入口见[开发复盘](../../interview/10-development-pitfalls.md#9-协议拒绝要能回到正确的恢复责任主体)。
