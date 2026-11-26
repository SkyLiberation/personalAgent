# ADR 0004：持久化智能体提交与 Artifact 引用

2026-07-27 决定。AgentGateway 负责执行绑定，ArtifactService 负责产物原字节。[现行 A2A 流程](../workflow/gpt-researcher-a2a-workflow.md)

## 背景与决定

原 Gateway 提交远程作业后才保存子运行，崩溃重试可能重复提交。子记录还保存一份产物正文。现由 `PostgresAgentRunStore` 在派发前保留稳定提交键和不可变定义摘要，回包后在原记录绑定远程任务或结果。

异步提交结果不明时，用提交键查找原作业。找不到或服务方不支持查询时保留未知，不重发。同步调用不明时同样停止重发。产物经 ArtifactService 写入，`AgentArtifact` 只持有带作用域的 `ResourceRef`。读取仍核验权限。保留一套存储与恢复协议，移除生产内存记录和内联产物副本。

Runtime 将 `ArtifactService` 注入 A2A 适配器。适配器从 `write_generated` 取得 `ResourceRef`，PostgreSQL 运行记录保存并恢复该引用。Agent 契约模块原先还定义并导出无人调用的 `new_agent_artifact_id`，容易与产物引用的生成入口混淆。本次清理移除了这两处。[A2A 适配器](../../src/personal_agent/agents/gpt_researcher_a2a.py) · [PostgreSQL 运行记录](../../src/personal_agent/infra/storage/postgres_agent_run_store.py) · [Agent 契约](../../src/personal_agent/kernel/contracts/agent.py)

## 验证与退出

产物标识清理以改动前的 Agent 契约模块为基线。验收要求生产源码中 `new_agent_artifact_id` 和 `aart_` 的匹配从三处降至零。对照时从基线语法树剔除函数定义和导出，然后比较整个模块并导入现有消费者。若其余定义出现差异或消费者导入失败，应撤回清理并核对调用关系。源码对照及 7 个直接消费者的导入均通过。

历史故障注入覆盖提交回包丢失、重建后按键找回以及已提交请求不重复执行。原 Investigation 恢复用例仅说明其历史消费者，该产品循环已退出。真实 A2A 崩溃恢复证据仍按对应部署取得。原复审日期为 2027-07-27；移除绑定时需要受影响服务方均能提供等价幂等与恢复证据。[Project 退出决定](0015-withdraw-investigation-project.md)
