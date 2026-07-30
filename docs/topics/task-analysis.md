# 历史设计：Task Analysis 与 Goal Graph Compile

> 状态：`TaskAnalyzer` 与统一 `GoalGraphCompiler` 已从正式 Conversation 主链删除。本文只保留
> 旧架构诊断价值，不是当前能力说明；当前短 Interaction 与 durable Project 的语义 owner 分别见
> [personalAgent 当前核心架构](../summary/core-architecture-current-state.md) 和
> [Durable Investigation Project 当前实现](../summary/durable-investigation-project-current-state.md)。

入口不使用关键词 Intent Router。语义理解与正式任务建立分成两个权责边界：

```text
EntryInput + allowed conversation context
  -> TaskAnalyzer
       TaskAnalysis: user_goal / goals / relations / resource hints / criteria
  -> GoalGraphCompiler
       TaskContract / TaskRuntimeProjection / ContextInventory
  -> Coordination + Executive Loop
```

## TaskAnalyzer

`planning/task_analyzer.py` 负责理解用户希望得到的结果。模型输出 Goal、`GoalRelation`、`ResourceHint`、success criteria 和 clarification/rejection。它不读取 Capability Portfolio，不做 provider coverage，不选择 Tool/MCP/A2A/Procedure，也不产生权限。

生产路径没有关键词分类兜底。空输入由结构规则请求澄清；模型不可用时返回 `analyzer_unavailable`，避免把猜测伪装成任务理解。

## Goal Relation

| kind | 语义 | 是否阻塞 |
| --- | --- | --- |
| `consumes_output` | 后继必须消费前驱产物 | 是 |
| `requires_completion` | 前驱完成是后继前提 | 是 |
| `ordering_preference` | 执行或展示偏好 | 否 |

关系记录 origin 和 rationale。Compiler 校验端点、重复、自依赖和阻塞环；运行中若新 Observation 推翻 inferred 假设，Adaptive Planning 只能通过 revision/CAS 产生受约束的新定义或 Plan patch，不能原地改旧 Definition。

## GoalGraphCompiler

`planning/task_compiler.py` 是确定性信任边界：

1. 校验 Goal identity 与 dependency topology；
2. 将 ResourceHint 规范化为嵌套在 Goal 或 Task shared scope 的 `ResourceRequirement`；
3. 通过 canonical Mutation taxonomy 生成 `MutationIntent`；
4. 保留 `user_explicit` criteria，并生成不可降低的 `contract_derived` 底线；
5. 根据 Goal result contracts 得到 Task result contract；
6. 创建定义 revision 与初始 Goal runtime state；
7. 通过 `TaskCompilationCommitter` 以 intake proposal revision 做 CAS 提交。

Compiler 不调用执行能力，不批准 Mutation，不选择 CoordinationMode，也不判断任务完成。

## Definition 与 Runtime

`TaskContract` 独占 Goal description、resource、criterion、constraint 和 dependency；`TaskRuntimeProjection` 只保存 status、attempt、evidence gap、coverage、verification ref 和 event cursor。`materialize_goals` 在 identity/revision/Goal 集一致后生成只读 View，避免每个调用方自行拼接两份 owner。

详见 [当前核心架构](../summary/core-architecture-current-state.md)。
