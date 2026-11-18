# ADR 0004：持久化智能体提交与 Artifact 引用

2026-07-27 决定。AgentGateway 负责执行绑定，ArtifactService 负责产物原字节。[现行 A2A 流程](../workflow/gpt-researcher-a2a-workflow.md)

## 背景与决定

原 Gateway 提交远程作业后才保存子运行，崩溃重试可能重复提交。子记录还保存一份产物正文。现由 `PostgresAgentRunStore` 在派发前保留稳定提交键和不可变定义摘要，回包后在原记录绑定远程任务或结果。

异步提交结果不明时，用提交键查找原作业。找不到或服务方不支持查询时保留未知，不重发。同步调用不明时同样停止重发。产物经 ArtifactService 写入，`AgentArtifact` 只持有带作用域的 `ResourceRef`。读取仍核验权限。保留一套存储与恢复协议，移除生产内存记录和内联产物副本。

## 验证与退出

历史故障注入覆盖提交回包丢失、重建后按键找回以及已提交请求不重复执行。原 Investigation 恢复用例仅说明其历史消费者，该产品循环已退出。真实 A2A 崩溃恢复证据仍按对应部署取得。原复审日期为 2027-07-27；移除绑定时需要受影响服务方均能提供等价幂等与恢复证据。[Project 退出决定](0015-withdraw-investigation-project.md)
