# 可观测与治理边界

**可观测数据解释系统发生了什么，不能反向成为业务事实、授权或 Completion 结论。** 当前工程按用途分别保存运行追踪记录、工具审计、调查项目 journal 和评测归档，不再使用一份通用事件流镜像全部状态。

## 1. 事实归属

| 记录 | 责任主体 | 可以证明 | 不能证明 |
| --- | --- | --- | --- |
| `InteractionTrace` | Conversation | 本轮输入、上下文组成、执行顺序、用量和最终消息 | 长期知识或调查项目状态 |
| 工具审计与幂等记录 | 工具执行网关及持久化 Adapter | 调用是否获准、是否执行、是否重复和副作用引用 | 用户目标已经完成 |
| Investigation journal | `InvestigationProject` | Project 定义、Plan、执行、证据、Verification 和 Completion 事实 | 普通 Conversation 的当前回答 |
| E2E archive | 评测系统 | 冻结代码与配置下的用户结果、指标和校验和 | 其他版本或未覆盖场景的质量 |
| LangSmith trace | 观测 Adapter | 模型和运行阶段的诊断投影 | canonical 审计、权限或发布资格 |

日志、追踪记录和归档可以通过稳定身份互相定位，但禁止用 listener 或 converter 在它们之间同步第二份业务状态。

## 2. LLM Trace 脱敏策略

**LangSmith 默认关闭；启用后也只接收观测投影。** `PERSONAL_AGENT_TRACE_UPLOAD_INPUTS=false` 时，模型调用只上传用途、模型参数、消息数量、字符数、延迟和 token 等摘要，不上传用户消息、模型正文、工具参数或工具结果正文。

显式设置 `PERSONAL_AGENT_TRACE_UPLOAD_INPUTS=true` 才允许上传完整输入输出。这个开关不替代采样、外部项目权限和数据保留策略，也不能保证第三方库自动生成的全部 trace 都经过同一个脱敏策略。敏感生产数据仍需在进入外部观测系统前执行最小化和权限审查。

配置字段和启用方式见 [环境变量说明](../env.md#langsmith-可观测性)。代码存在或配置加载成功只证明观测机制可构造；只有实际 trace 才能证明某条生产路径已经被观测。

## 3. 治理与执行

模型只能提出动作 `Proposal`。策略与 Admission 判断权限、风险、预算和确认要求，执行网关产生执行事实，Verifier 与 Completion Gate 分别判断语义满足和结果契约。观测组件只记录这些阶段的输入、输出和错误，不修改决策。

工具的曝光、授权、结果结构、审计和幂等边界见 [工具设计](tools.md)。运行装配与 `InteractionTrace` 见 [当前 Runtime](runtime.md)。全局权力边界见 [当前核心架构](../summary/core-architecture-current-state.md)。

## 4. 评测与发布

评测归档必须绑定代码身份、配置、样本、评测器和 checksum。中间事件、工具调用、Artifact 或状态为 success 只能用于定位失败阶段，不能替代用户可观察结果。

证据分类、当前用例和发布资格分别由以下文档维护：

- [当前评测体系](../evals/README.md)；
- [当前端到端用例盘点](../evals/02-current-case-inventory.md)；
- [评测执行与发布](../evals/04-running-and-release.md)。

旧 `AgentGraphState`、LangGraph 总图、通用 `AgentEvent` 收敛计划和已经迁移的 `web/agent/storage` 路径不再属于当前设计，因此已从本页删除。
