# ADR 0003：认证主体与执行关联

2026-08-08 决定。私有资源属于认证主体，执行范围传播关联身份。[身份契约](../../src/personal_agent/kernel/contracts/scope.py)

## 背景与决定

L07 保存个人知识后，在新 Conversation 中无法回读；当时会话 ID 被用于资源分区。DUR-001 在 Web 重启后，用另一主体读取私有运行引用也收到 200，并取得原用户消息。缺口分别在知识归属和对话读取权限。

入口解析 `AuthenticatedPrincipal`，应用构造 `ExecutionScope` 关联主体、执行及会话。资源引用和 Journal 以真实主体为准，公开运行 ID 不授予权限。错主体的读取或恢复返回不可见结果，拒绝事件关联同一 run 以便审计。旧无可信 owner 的快照隔离。复用 canonical 字段和已有审计路径，删除旧 workspace 分区及重叠入口；原 Investigation 关联的产品消费者随 [ADR 0015](0015-withdraw-investigation-project.md)退出。

采用 LangGraph 的运行标识与主体分离、现有记录重放和 OpenTelemetry 的执行关联思路，避免新权限索引和观测基础设施。[原机制与迁移记录](https://github.com/SkyLiberation/personalAgent/blob/345c62679a6c1f6a4c70980c868f55b5dee95fef/docs/adr/0003-principal-ownership-and-execution-association.md)

## 历史验证

L07 失败与通过归档分别为 `20260808T075713.239052Z-30360-52c7f40a`、`20260808T084332.564715Z-7092-0f815eeb`。DUR-001 失败归档为 `20260811T123526.301024Z-18200-577304a8`。DUR-001／OBS-001 修正后归档 `20260811T131846.157075Z-14556-f95a2089` 中，原主体得到 200，另一主体为 404，拒绝日志可关联原 run。新增共享需求需以真实成员关系与用户结果重新确定权限边界。
