# ADR 0035：检索实验复用受治理执行与原始产物

原 E1 确认合法 SciFact 材料与部署说明已进入实际模型请求，但工具面缺少实验提交能力，原用户结果为 0/1。受治理的实验工具获得准入。首版要求的自动发布、打包和下载已由 [ADR 0037](0037-experiment-submission-first-delivery.md)替换。[原失败与准入](../optimization/to_verify/verify_results/research-experiment.md#t0-同轨迹局部准入复审)

## 决定与责任

检索实验 Application 经 typed Port 访问单一工程执行引擎。模型选择开发实验、解释结果和决定冻结；代码校验权限、版本、保持冻结约束并分隔开发与最终评分。测试私有标签只交可信评分器。

Artifact 保留输入、程序及结果原字节、摘要和生产者绑定。Journal 在派发前保存已接受的不可变请求；同身份异内容拒绝，已发生的决策、计划与用量先完整提交。稳定作业身份、原截止和额度在真实派发前冻结，恢复对账原作业。未知终态保持未知，实际停止由 runner 确认。[决策与接受顺序](../optimization/to_verify/verify_results/research-experiment.md#2-决策状态先于持久接受)

复用同一 Artifact、Journal 和执行引擎，避免增加镜像账本。实验 Completion 使用实际执行、冻结和产物事实。现行答复不使用 `prepare_final` 或发布清单，实验执行与完成契约各有入口。[现行完成契约](0037-experiment-submission-first-delivery.md) · [原生答复协议](0045-native-intent-loop-and-recorded-model-output.md)

## 历史验证与退出

旧实例已经在真实检查点暴露决策状态提交顺序问题，特定历史文件的换行归一化曾造成摘要检查假阳性。原始字节与旧运行身份保留，完整实验交付按真实结果验收。越权、混版、重复副作用或未知状态被视为成功时，按最早执行边界定位和撤回。[原验证与反例](../optimization/to_verify/verify_results/research-experiment.md#32-完整落地-implementation-plan)
