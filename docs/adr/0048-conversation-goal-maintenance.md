# ADR 0048：Conversation 每轮维护任务目标

2026-11-12 采用版本化目标条目，2026-11-13 将目标链从会话转为任务，并接入统一主循环。[现行任务切换](../context/agent-loop.md#同一对话中的任务切换)

## 背景与决定

真实 LongDS Task 2 在收到原用户消息和原生历史后，仍更换名单范围和必要条件。引入可校验、可恢复的当前任务目标，让后续动作与回答共享同一有效任务解释。[原六轮诊断](../optimization/to_verify/verify_results/analysis-correctness.md#17-用户原话与持续约束候选的完整六轮)

每轮先维护任务。模型以 `submit_goal_patch` 提议任务归属与版本化条目变更，用户原话继续拥有约束。启用目标核验时，Runtime 先取得对应回执；Journal 在同一次提交绑定轮次任务与已接纳变更。执行、计划、核验和恢复只消费对应任务及可见分支。执行限制由原治理入口负责。按需读取 `read_current_goal` 返回生效快照，读操作不会提交修改。[增量目标规格](../optimization/to_verify/analysis-goal-maintenance.md#当前改造版本化目标条目和增量提交) · [核验责任与开关](0050-verification-feature-flags.md)

复用现有 Journal 和原生反馈闭环，不复制目标存储。旧独立意图分类、单正文和文稿替换协议已退出。早期强制在作答前读目标的规则已移除，正式输入继续包含生效目标。[统一主循环规格](../optimization/to_verify/analysis-goal-maintenance.md#统一-conversation-主循环)

## 验证与退出

旧 `.tmp/gm631/` 六轮独立评分 2/6，保留原接入身份。单正文四项契约和职责分离的三轮结果分别留在原记录。现行任务切换的实际验收按统一规格报告；若目标归属、原要求、反馈或恢复出错，使用对应的真实轨迹定位与复验。[早期目标结果](../optimization/to_verify/verify_results/analysis-correctness.md#32-单正文四项内容契约的空会话连续前三轮) · [核验分离结果](0047-user-goal-verification-context.md)
