# 执行反馈边界

**执行反馈是 canonical 运行事实的只读界面投影，不是第二套任务状态或通用事件事实源。** Web、CLI 和飞书入口复用相同的 Conversation 结果契约；固定业务能力由各自 Application 或 Domain 拥有状态与恢复语义。

## 当前反馈链

```text
Application / Aggregate canonical facts
  -> typed result、Observation 或 DecisionFeedback
  -> Interface Adapter
  -> HTTP/SSE、CLI text 或 message reply
```

入口只转换协议、解析身份并校验输入。入口不得从事件名称补业务语义，也不得把工具成功、Agent Artifact 或单个步骤完成升级为用户目标完成。

Web SSE 在 Turn 登记后发送轮次身份，在交付完成后发送答案分块。断连后通过原 Turn 查询或恢复。[SSE 响应](../api.md#sse-响应)

## 权威文档

- 入口、SSE、CLI 与飞书契约见 [入口层说明](entry.md)；
- Conversation loop、durable execution 和运行事实见 [当前 Runtime](runtime.md)；
- `Observation`、Verification 与 Completion 的边界见 [Verification 与 Completion](verification-and-completion.md)；
- 后台持续运行的当前边界见 [当前 Runtime](runtime.md#durable-execution)。
