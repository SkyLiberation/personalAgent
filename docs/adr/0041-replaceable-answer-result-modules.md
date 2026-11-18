# ADR 0041：回答 writer 与核验装配的历史决定

2026-10-23 接入。核验配置于 2026-11-05 迁到 [ADR 0050](0050-verification-feature-flags.md)，可替换 writer 于 2026-11-15 随 [ADR 0055](0055-unified-conversation-answer.md)退役。

## 原决定与责任

LongDS 相位与结果实验需要在同一正式入口比较直接回答和研究论断写作。原决定用装配配置选择 writer，独立决定是否执行核验。复用同一模型 Port、Journal、执行事实和完成入口；运行身份绑定装配，原记录恢复可检测配置变更。历史 `AnswerResultConfig` 及其 `required`、`none` 值属于当时的协议。

## 历史验证

实际阶段回放覆盖正文、引用拒绝、修复和原稿恢复。正式两轮交付与独立评分均通过，更换配置的原 run 恢复和同对话新 run 被拒。完整 36 轮、其他部署、自然压力以及 writer 的独立收益另列。[原阶段与运行结果](../optimization/to_verify/verify_results/longds-analysis.md)
