# 工具声明与受治理执行

本文拥有当前工具声明、曝光、执行和结果契约。Conversation 的决策相位与最终交付由[Runtime](runtime.md)拥有；工具返回执行事实，业务状态由对应 Application 或领域服务维护。

## 当前生产链路

```text
Application Service
  -> 工具工厂声明 BaseTool、ArgsSchema 和 ToolGovernance
  -> ToolExecutor 注册
  -> Conversation 物化模型可见动作
  -> 模型提出工具调用
  -> Application 校验曝光、参数与预算
  -> ToolGateway 校验 Policy 并执行
  -> ToolArtifact -> bounded ActionObservation
  -> Conversation 继续决策或提交最终结果
```

工具工厂负责参数和协议适配，服务负责业务语义、写入及领域不变量。组合根在 [orchestration/runtime.py](../../src/personal_agent/orchestration/runtime.py)装配真实服务、注册表、Policy 和持久化适配器。

模型原生动作由 [model_actions.py](../../src/personal_agent/application/conversation/model_actions.py)投影和解码。工具参数表达业务动作；工作进度通过独立 `control_working_plan` 提交，执行系统从已准入工作清单关联活动项。动作相位与 typed 最终提交分别调用模型，具体契约见 [ADR 0016](../adr/0016-separate-plan-control-from-action-execution.md)和 [ADR 0017](../adr/0017-separate-action-selection-from-final-delivery.md)。

## 注册与曝光

`ToolExecutor` 在 [governance/registry.py](../../src/personal_agent/governance/registry.py)维护已注册工具，按调用入口生成只读定义。`ToolGovernance.exposure` 区分四种声明：

| 声明 | 当前消费边界 |
| --- | --- |
| `public_agent` | 可以进入普通 Conversation 工具投影；调用时仍须通过参数、预算及 Policy 检查 |
| `scoped_agent` | 不进入普通 Conversation；存在明确受限调用入口时由该入口约束工具集合 |
| `workflow_activity` | 由确定性固定流程入口校验和执行，例如运行系统拥有的语义核验 |
| `admin` | 不进入普通 Conversation；由管理入口承担适用权限检查 |

`list_interaction_tools()` 和 `validate_interaction_call()` 都只接受 `public_agent`，`validate_workflow_call()` 和 `invoke_workflow()` 都只接受 `workflow_activity`。工具注册、模型可见与获准执行是三个不同事实。资源可见性与能力投影的现行实现边界见 [Context](context-engineering.md#visibility-的定义与分层)。

HTTP 直接执行通过 `invoke_direct()` 复用 Gateway；它有独立的身份及作用域入口，接口见 [API](../api.md#post-apitoolsnameexecute)。注册工具清单不等于普通模型可选工具清单。

## 输入、结果与错误

工具使用显式 Pydantic `ArgsSchema` 表达必填项、范围及字段说明。Conversation 在执行前校验工具名和参数；原生工具调用的形状合法后，仍须通过 Application 准入。

工具契约的类型源是 [kernel/contracts/tool.py](../../src/personal_agent/kernel/contracts/tool.py)，包装函数由 [tools/base.py](../../src/personal_agent/tools/base.py)拥有。

| 契约 | 责任 |
| --- | --- |
| `ToolGovernance` | 声明曝光、风险、副作用、权限域、确认、幂等、审计、超时、重试、限流和域名约束 |
| `ToolArtifact` | 表达 `ok`、业务 `data`、`error`、`error_kind` 与 `evidence` |
| `ToolErrorKind` | 区分 `transient`、`invalid_param`、`permission` 和 `unrecoverable`；Gateway 依据分类处理失败 |
| `ToolInvocationEvent` | 记录调用归属、输入输出、治理属性、执行耗时和策略结果 |

服务返回领域对象或用例结果，工具将其包装为 `content_and_artifact`。Gateway 使用 typed `ToolArtifact`，跨 HTTP、日志或交互输入边界时序列化。`ok=true` 说明工具执行成功；来源支持与用户结果继续由 [Verification 与 Completion](verification-and-completion.md)验收。

## Gateway、幂等与审计

[governance/gateway.py](../../src/personal_agent/governance/gateway.py)消费 `ToolGatewayContext.execution_scope`、执行模式、调用 ID 和来源平台，统一处理 Policy、直接 URL 域名限制、限流、超时、分类重试及审计。`allowed_domains` 约束直接 URL 的域名后缀，网络重定向和地址安全仍按实际执行边界判断。

确认且要求幂等的通用工具通过 `IdempotencyStore` 预占 key，成功后提交结果供重放；生产适配器是 [PostgresToolGovernanceStore](../../src/personal_agent/infra/storage/postgres_tool_governance_store.py)。账本只证明所覆盖调用的执行事实，跨系统副作用仍由相应业务契约约束。

固定知识保存、删除和恢复由各自 Application 拥有 Command、确认、Receipt 与事务；工具层不复制这些状态。删除恢复链路见[固定流程](../workflow/delete-knowledge-workflow.md)，保存见 [ADR 0006](../adr/0006-conversation-governed-knowledge-save.md)。

工具审计写入 `tool_audit_events`，查询和脱敏规则由[可观测与治理](observability-governance.md)拥有。[依赖图](../mermaid/tools-model-layer-dependencies.md)只展示现行责任关系。

## 搜索、读取与内部核验

`web_search(query, limit)` 返回发现摘要；`web_read(url)` 返回指定来源正文。长结果卸载到 Artifact，模型以 `search_action_output` 定位、`read_artifact` 读取同一正文坐标。后端固定调用 `rg`，模型只指定授权资源及读取参数。原 `read_action_output` 保留实现但不投影，准入拒绝；正文和引用契约见 [Context](context-engineering.md#网页来源正文保留与重读)及 [ADR 0024](../adr/0024-plain-source-tools-and-inline-citations.md)。

语义核验注册为 `workflow_activity`，由运行系统在适用提交后调用，不进入普通模型可见工具面。研究 claims、来源核验、覆盖、独立汇总与最终核验继续由 Conversation 的既有责任链消费，见[核验专题](verification-and-completion.md)。

## 证据入口

工具选择、参数、曝光、授权和错误恢复分别按 [QLT](../devSpec/quality-security.md#1-测试职责与覆盖)选择真实 E2E 检查点或 Offline Eval；历史单元测试只读保留。当前用例与结果由[评测盘点](../evals/02-current-case-inventory.md)拥有，开放问题及准入状态由 [Future 队列](../future/design-optimization-backlog.md)拥有。
