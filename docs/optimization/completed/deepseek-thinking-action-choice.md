# DeepSeek 思考模式的工具选择编码

2026-10-21，既有工具协议的确定性兼容缺陷已在真实研究轨迹中验证关闭。修正只改变 Provider 的工具选择编码；完整研究报告仍有独立的错例分析错误，结果由[研究 Spec](../to_verify/knowledge-decision-delivery.md)及[评测盘点](../../evals/02-current-case-inventory.md#2026-10-20-检索实验研究能力准入)拥有。

## 问题与采用方案

前一正式 DeepSeek E1 的意图阶段完整返回，随后动作请求携带 `thinking=enabled` 和 `tool_choice=required`，Provider 明确返回 HTTP 400。坏请求及响应由[原失败封存](../../../.tmp/research-deepseek-flash-20261021/preparation-2-failure-seal.json)绑定。[官方 Chat 契约](https://api-docs.deepseek.com/api/create-chat-completion/)允许思考模式使用 `auto`，不接受强制工具选择。

[OpenAIModelClient._chat_kwargs](../../../src/personal_agent/infra/structured_model.py)在实际 host 为 `api.deepseek.com`、工具请求内部要求 `required`、思考未显式关闭时，将 wire 的工具选择编码为 `auto`。内部 frozen request 仍为 `required`，无动作或非法 JSON 继续接受原单次协议修复和严格解码，普通正文不直接交付。其他 Provider 及显式关闭思考的原协议保持。

该决定由 Provider Adapter 拥有，不增加模型路由、配置开关、状态或权限。修正共增加 9 行，复用原请求、解码及反馈，未改变业务动作与 Completion。

## 决定性证据与范围

- [完整真实请求反事实及预检](../../../.tmp/context-compression-research-20261021/preflight.json)：失败 DeepSeek SDK body 只改变 `tool_choice`；7 份 MiMo 实际 body 逐值保持；零模型／业务执行。
- [独立审查](../../../.tmp/research-deepseek-flash-20261021/protocol-independent-review.md)：核对内部 required、单次修复及正式消费者，无阻断发现。
- [新正式 E1 机械审计](../../../.tmp/context-compression-research-20261021/after-run-1/capture-audit.json)：真实 API 接受，模型动作通过解码和准入并实际执行至冻结、test 与报告发布；25 物理请求全部完整，2,576,142 已知 tokens、零新增未知。一次非法参数 JSON 使用原有单次修复后继续，首响应与费用保留。

原 400 的未知用量保持。该结果证明本服务身份下的协议接入和原门禁继续成立；研究报告正确性、历史压缩、完整恢复矩阵及 Harness 收益分别验收。

## 失败尝试与重新打开

初次配置额外携带未被现行容量 profile 接纳的 `reasoning_effort`，在发送前拒绝；启动器删除冗余参数后另建准备身份。随后出现上述真实 400，按协议边界修正，没有关闭思考或放宽动作校验。原失败与新证据分别保留。

后续真实 E2E 在相同协议边界复现拒绝、无动作被错误交付，或其他 Provider 请求出现本分支引入的差异时，重新打开本问题。完整用户结果中的独立报告错误继续由研究 Spec 推进。
