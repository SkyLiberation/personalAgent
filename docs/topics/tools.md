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

模型原生动作由 [model_actions.py](../../src/personal_agent/application/conversation/model_actions.py)投影和解码。工具参数表达业务动作；工作进度通过独立 `control_working_plan` 提交，执行系统从已准入工作清单关联活动项。主循环同时接受动作和合法 assistant 正文，回答模块将正文或显式提交恢复为同一种 `FinalMessage`。当前协议见 [ADR 0045](../adr/0045-native-intent-loop-and-recorded-model-output.md)，计划控制见 [ADR 0016](../adr/0016-separate-plan-control-from-action-execution.md)。

原生 `function.parameters` 直接表达业务参数。模型可见调用名来自同轮 `ModelActionDefinition.name`，解码器据此构造内部 `Proposal`。检索工具保留 `action`。`tool_edit` 使用 `strict=false` 保留可选的 `replace_all`，本地声明仍校验字段形状。参数类型、权限、接受摘要与恢复由原责任主体校验。[参数协议](../adr/0043-direct-code-agent-tool-parameters.md)

## 注册与曝光

MCP 工具在宿主启动时发现。客户端握手后逐页请求 `tools/list`，把 `nextCursor` 原样传入下一次请求的 `params.cursor`，到末页才把完整目录交给组合根。组合根只注册部署中映射的工具。页格式错误、循环游标、第 64 页仍有续页或请求失败都会中止发现并拒绝启动。发现和注册由 Runtime 完成，模型随后从可见工具中选择调用。 [MCP 分页设计与验收](../mcpDesign/README.md#mcp-01-工具目录分页)

`ToolExecutor` 在 [governance/registry.py](../../src/personal_agent/governance/registry.py)维护已注册工具，按调用入口生成只读定义。`ToolGovernance.exposure` 区分四种声明：

| 声明 | 当前消费边界 |
| --- | --- |
| `public_agent` | 可以进入普通 Conversation 工具投影；调用时仍须通过参数、预算及 Policy 检查 |
| `scoped_agent` | 不进入普通 Conversation；存在明确受限调用入口时由该入口约束工具集合 |
| `workflow_activity` | 由确定性固定流程入口校验和执行，例如运行系统拥有的语义核验 |
| `admin` | 不进入普通 Conversation；由管理入口承担适用权限检查 |

`list_interaction_tools()` 和 `validate_interaction_call()` 都只接受 `public_agent`，`validate_workflow_call()` 和 `invoke_workflow()` 都只接受 `workflow_activity`。工具注册、模型可见与获准执行是三个不同事实。资源可见性与能力投影的现行实现边界见 [Context](context-engineering.md#visibility-的定义与分层)。

HTTP 直接执行通过 `invoke_direct()` 复用 Gateway；它有独立的身份及作用域入口，接口见 [API](../api.md#post-apitoolsnameexecute)。注册工具清单不等于普通模型可选工具清单。

Conversation 在 [`_effective_capabilities()`](../../src/personal_agent/application/conversation/service.py)中加入知识、文件和工作区动作，并按部署与当轮权限筛选注册工具。Runtime 从初始材料、已提交回执及外置结果恢复当前可读范围。主请求还接收适用的控制动作及已配置的 Agent 委托动作。现行调用名及其可见条件见[本地工具列表](../context/tool.md#当前本地工具列表)。

`TurnContextComposition.model_action_definition_chars` 记录每轮动作定义的字符量。模型实际收到的菜单取决于该轮投影，不能从注册总数推导输入体积、误选率或用户结果。

## 输入、结果与错误

内建工具使用 Pydantic `ArgsSchema`，MCP 工具沿用 Server 的 `inputSchema`。Conversation 在执行前校验工具名和参数。原生工具调用的形状合法后，仍须通过 Application 准入。[MCP 输入契约](../mcpDesign/README.md#524-沿用上游输入-schema)

模型用 `tool_create_artifact` 新建草稿，提交 `filename`、`content_type` 和 `content`。用 `tool_edit` 编辑现有文件，提交 `file_path`、`old_string`、`new_string` 和可选 `replace_all`。

当前可编辑草稿返回新 Artifact 快照。任务容器的 `/tmp` 文件须先用 `tool_read_file` 读取，通过版本校验后原地写回。默认要求唯一命中，空替换文本表示删除。字面匹配将 CRLF 和 LF 视作等价。工具结果用原调用 ID 回给模型。[编辑契约](../optimization/to_verify/program-artifact-contract.md#模型编辑工具)

原生动作协议拒绝记录首个拒绝对象、字段诊断和同批原提议。整批均未执行。模型查看配对的原调用，或反馈中保留的未配对提议。未声明动作的反馈以当次可用工具和维护状态为依据，重复未知名共用原修复额度。参见[主循环拒绝反馈约定](../context/agent-loop.md#23-动作拒绝的重试上下文)和[名称反馈保真](../optimization/completed/unknown-action-name-feedback.md)。

工具契约的类型源是 [kernel/contracts/tool.py](../../src/personal_agent/kernel/contracts/tool.py)，包装函数由 [tools/base.py](../../src/personal_agent/tools/base.py)拥有。

| 契约 | 责任 |
| --- | --- |
| `ToolGovernance` | 声明曝光、风险、副作用、权限域、确认、审计、超时、重试、限流和域名约束 |
| `ToolArtifact` | 表达 `ok`、业务 `data`、`error`、`error_kind` 与 `evidence` |
| `ToolErrorKind` | 区分 `transient`、`invalid_param`、`permission` 和 `unrecoverable`；Gateway 依据分类处理失败 |
| `ToolInvocationEvent` | 记录调用归属、输入输出、治理属性、执行耗时和策略结果 |

服务返回领域对象或用例结果，工具将其包装为 `content_and_artifact`。Gateway 使用 typed `ToolArtifact`，跨 HTTP、日志或交互输入边界时序列化。`ok=true` 说明工具执行成功；来源支持与用户结果继续由 [Verification 与 Completion](verification-and-completion.md)验收。

## Gateway、幂等与审计

[governance/gateway.py](../../src/personal_agent/governance/gateway.py)消费 `ToolGatewayContext.execution_scope`、执行模式、调用 ID 和来源平台，统一处理 Policy、直接 URL 域名限制、限流、超时、分类重试及审计。`allowed_domains` 约束直接 URL 的域名后缀，网络重定向和地址安全仍按实际执行边界判断。

Gateway 将 typed `ToolGatewayContext` 经 `RunnableConfig.configurable` 交给需要它的工具工厂；其中的 scope、合法资源及已接受请求摘要不属于模型参数。`write_artifact`、`retrieval_experiment` 和 `execute_python` 在派发前由原 Conversation Journal 保存确切请求，原 owner 保存回执后才形成 Observation。它们声明 `write_local`，不作为规划安全操作，也不由通用超时线程或自动重试启动第二次执行；恢复消费原请求和回执，未知实验先对账。各业务的幂等和恢复沿原 Command 与 Receipt 处理。

Gateway 通过 `PolicyEvaluator` 获取并审计决定。只有 `allow` 才进入执行，`require_confirmation` 与 `require_escalation` 在通用入口均产生权限失败。业务参数 `confirmed` 不构成确认凭据。待确认状态、确认后的恢复与幂等属于具体 Application。已有通用幂等记录仍可通过原审计入口查阅。部署中的 MCP 映射如包含旧字段 `idempotency_key_required`，迁移时删除该字段。[派发边界 ADR](../adr/0052-tool-policy-dispatch-gate.md)

[PolicyEngine](../../src/personal_agent/governance/policy/engine.py)先检查部署拒绝规则，再对 ReAct 工具检查允许名单和自主执行限制。到达调用确认分支时，工具和子 Agent 均按策略请求中的 `requires_confirmation` 判断；高风险配置字段仍可读取，在该分支中不影响现行结果。

内部分支简化以清理前源码为对照：在确认声明、部署配置、风险级别是否为高及是否含禁止副作用的 16 种布尔组合中，确认条件均等价；其余策略方法、ReAct 判断和审计规则值保持。已清理无调用方的旧规划校验，分层、导入及 diff 检查均通过。

固定知识保存、删除和恢复由各自 Application 拥有 Command、确认、Receipt 与事务；工具层不复制这些状态。删除恢复链路见[固定流程](../workflow/delete-knowledge-workflow.md)，保存见 [ADR 0006](../adr/0006-conversation-governed-knowledge-save.md)。

工具审计写入 `tool_audit_events`，查询和脱敏规则由[可观测与治理](observability-governance.md)拥有。[依赖图](../mermaid/tools-model-layer-dependencies.md)只展示现行责任关系。

## 搜索、读取与内部核验

`web_search(query, limit)` 返回发现摘要；`web_read(url)` 返回指定来源正文。长结果保存为会话文件，模型用回执给出的路径调用 `grep_file` 定位正文、用 `read_file` 按行读取。Runtime 检查路径对应本任务的已授权来源。搜索后端固定调用 `rg`；正文和引用契约见 [Context](context-engineering.md#网页来源正文保留与重读)及 [ADR 0024](../adr/0024-plain-source-tools-and-inline-citations.md)。

整稿核验注册为 `workflow_activity`，由运行系统在适用提交后调用，不进入主模型可见工具面。真实核验结果及确切候选交给 Completion，见[核验专题](verification-and-completion.md)。

研究实验用不可变 Artifact 程序和配置快照。模型可创建草稿或从确切快照编辑派生新版本，并通过 `retrieval_experiment` 执行开发实验、冻结结果或评测冻结方案。结果摘要从同一不可变原件投影 publication，组合和冻结消费原业务结果引用。模型按真实指标和原件选择工作，代码负责权限、输入绑定、评分、隔离、状态和交付不变量。[研究设计](../optimization/to_verify/research-experiment-protocol.md#2-受限实验能力)

读取、搜索和编辑 Artifact 使用材料或回执提供的 `file_path`。检查 Artifact 使用 `resource_id`。Runtime 从当前获准集合恢复唯一完整引用和不可变字节，未知、歧义及跨主体引用会被拒绝。续读参数由文件路径和正文坐标组成。[文件路径契约](../context/tool.md#会话文件替换决定)

`execute_python` 与检索实验并列，当前只要求完整 `code`，可选 `input_files` 省略默认空。已有程序绑定为只读输入，由模型用标准 Python 执行，Runtime 按原字节恢复；Command／Receipt 的程序引用仍保留实际执行身份。原 Artifact owner 保存确切源码、输入清单及 stdout／stderr，工具返回有界预览和原件引用；模型可以继续读取、修正程序或成文。它复用一次程序一个受限容器的技术沙箱，通用分析按显式对话许可聚合任务执行额度，检索部署保持原 run 内共享额度；两者沿用原 Journal 的不可变命令和未知终态对账。独立装配及跨轮原件接续见 [ADR 0040](../adr/0040-scoped-python-analysis-authorization.md)，实际验收状态由下述 Spec 拥有。程序输出不变成可信指标或完成事实；分析原件保留内部引用，完成时不生成用户清单／ZIP或触发下载；历史清单和CLI读取保持原离线身份。工具由模型自主选择，不以调用频次验收参数能力；详细契约及验证边界由 [Python 工具 Spec](../optimization/to_verify/python-data-analysis-tool.md)拥有。

## 证据入口

工具选择、参数、曝光、授权和错误恢复分别按 [QLT](../devSpec/quality-security.md#1-测试职责与覆盖)选择真实 E2E 检查点或 Offline Eval；历史单元测试只读保留。当前用例与结果由[评测盘点](../evals/02-current-case-inventory.md)拥有，开放问题及准入状态由 [Future 队列](../future/design-optimization-backlog.md)拥有。
