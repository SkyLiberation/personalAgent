# 面试收尾口径

可以用这段话收尾：

> 我这个项目真正想解决的不是“让 Agent 看起来什么都会”，而是让 Agent 在记忆、工具、workflow 编排和评测几个关键位置都有系统边界。短期现场用 checkpoint，长期事实用 note/chunk，语义关系用 Graphiti，回答依据统一成 evidence；固定流程由 WorkflowSpec/WorkflowRegistry 管理，删除和固化这类 workflow 会被确定性投影成可展示、可恢复、可确认的步骤；工具和记忆访问必须经过 PolicyEngine 与 Gateway，并经过 StepProjectionValidator、HITL 和 checkpoint。这样模型可以参与理解和局部决策，但不能绕过可恢复、可校验、可审计的工程边界。

---

[← 返回索引 INDEX.md](INDEX.md)
