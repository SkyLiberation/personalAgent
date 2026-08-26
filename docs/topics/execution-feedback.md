# 执行反馈边界

**执行反馈是 canonical 运行事实的只读界面投影，不是第二套任务状态或通用事件事实源。** Web、CLI 和飞书入口复用相同的 Conversation 结果契约；固定业务能力和 durable Project 继续由各自 Application 或 Aggregate 拥有状态与恢复语义。

## 当前反馈链

```text
Application / Aggregate canonical facts
  -> typed result、Observation、DecisionFeedback 或 Project projection
  -> Interface Adapter
  -> HTTP/SSE、CLI text 或 message reply
```

入口只转换协议、解析身份并校验输入。入口不得从事件名称补业务语义，也不得把工具成功、Agent Artifact 或单个步骤完成升级为用户目标完成。

当前 Web SSE 会在一次 Conversation turn 完成后对最终文本进行协议分块。它不是模型 token 的原生流，也没有独立的可恢复执行状态。若真实端到端测试证明首 token 延迟或中途取消不满足用户需求，才能准入新的流式协议与恢复边界。

## 权威文档

- 入口、SSE、CLI 与飞书契约见 [入口层说明](entry.md)；
- Conversation loop、durable execution 和运行事实见 [当前 Runtime](runtime.md)；
- `Observation`、Verification 与 Completion 的边界见 [Verification 与 Completion](verification-and-completion.md)；
- 后台调查项目的 canonical 状态见 [Durable Investigation Project 当前状态](../summary/durable-investigation-project-current-state.md)。

旧 step panel、GoalGraph 事件、LangGraph 总图和通用 `AgentEvent` 实施计划已经失去生产责任主体，因此不再保留在当前设计文档中。
