# Knowledge Agent 工程开发规范
> 本文档是知识 Agent 项目的强制工程规范，适用于架构设计、开发、重构、缺陷修复、测试、评审和上线验收。
> “必须/禁止”属于合并门禁；确需例外时，必须通过 ADR 记录原因、风险、验证方案、退出条件和移除日期。

---
## 1. 最高铁律
### 1.1 E2E 可执行验证
**任何落地设计，如果没有配套可执行、可重复、可自动断言用户结果的 E2E 用例，一律视为未经验证。**
因此：
- 编码前必须先定义 E2E 验收场景；
- E2E 可以先失败，但不得缺失；
- 未执行测试时，禁止声称“已验证”“已修复”或“可上线”；
- 单元测试、对象存在、状态为 success、数据库新增记录，均不能替代 E2E；
- E2E 必须同时验证正确结果发生，以及错误结果没有发生。
合格 E2E 必须：
1. 从正式 API、CLI、消息入口或 Application Use Case 进入；
2. 经过生产主路径，而非测试专用旁路；
3. 使用真实领域模型、状态迁移、编排和持久化协议；
4. 自动断言用户可观察结果和关键反事实；
5. 可通过明确命令在本地或 CI 重复执行；
6. 失败时能通过 trace、event、receipt 或 report 定位阶段。
允许 Fake/Stub 的范围仅限不可控第三方、付费模型、危险副作用和故障注入。Fake 必须实现同一 Port，并有 contract test；不得替系统作出本应由模型、Policy 或 Admission 作出的决定。

### 1.2 单一事实与单一写入口
每个业务事实必须只有：
- 一个权威 owner；
- 一个 canonical model；
- 一个合法写入口；
- 一套生命周期、版本和失效规则。
无法说明字段的 owner、来源、写入者、失效条件和重建方式时，禁止直接编码。
禁止：
- 新旧字段双写；
- singular/plural 双轨状态；
- 多个 Model 镜像相同业务字段；
- 用 validator、listener 或 converter 同步副本；
- 为读取方便新增可写镜像字段；
- 将可确定性重建的派生值持久化。

### 1.3 决策所有权
- **模型或外部权威**负责开放世界中的语义判断；
- **确定性代码**负责封闭世界中的权限、唯一推导、状态迁移和不变量；
- **执行系统**负责产生执行事实；
- **Verifier**负责判断 Goal 是否语义满足；
- **Completion Gate**负责判断完成所需证据是否齐全。
任何新增分支必须明确属于：Semantic Decision、Deterministic Derivation、Policy Decision、Environment Fact、Execution Fact、Semantic Verification 或 Completion Decision。

### 1.4 删除优先
重构默认允许修改全部调用方。能替换旧结构时，禁止新增 alias、fallback、双写、永久 deprecated 字段和无期限兼容层。
兼容仅允许用于真实外部契约，并必须包含：适用范围、结束日期、迁移计划、观测指标和删除条件。

---
## 2. 架构目标与依赖方向
系统必须同时满足：
- 高内聚：同一业务不变量集中在同一模块；
- 低耦合：通过稳定契约依赖，不依赖实现细节；
- 可替换：模型、数据库、工具和框架可通过 Adapter 替换；
- 可验证：核心行为能够从正式入口端到端验证；
- 可恢复：长任务支持幂等、重放、暂停和继续；
- 可审计：关键决策、授权、执行和完成均有证据；
- 可演进：删除旧路径，不依靠长期双轨维持演进。

### 2.1 强制分层
1. **Domain**：领域实体、值对象、领域服务、不变量、状态机；
2. **Application / Orchestration**：Use Case、Workflow 编排、事务边界；
3. **Semantic Decision**：Router、Planner、Replanner、模型 Verifier；
4. **Governance / Control Plane**：Policy、Admission、ToolGateway、Approval；
5. **Capability / Execution**：Tool、Service、MCP/A2A Adapter、Executor；
6. **Runtime / Persistence**：Checkpoint、Repository、Event/Receipt、Artifact Store；
7. **Interface**：API、CLI、消息入口、DTO；
8. **Observability / Evaluation**：Trace、Metric、Golden Set、E2E、Eval。

### 2.2 依赖规则
依赖方向必须指向更稳定的内层：
`Interface / Infrastructure -> Application -> Domain`
同时遵守：
- Domain 禁止依赖 LangGraph、数据库 ORM、模型 SDK、MCP SDK 或 Web 框架；
- Application 依赖 Port，不直接依赖具体 Adapter；
- Interface 只做协议转换、身份解析和输入校验；
- Adapter 不得补全业务语义或决定业务流程；
- 框架对象不得跨越模块边界成为业务契约；
- 依赖装配集中在 Composition Root；
- 禁止循环依赖和跨层反向调用。

---
## 3. 模块职责与高内聚规则
### 3.1 Domain
Domain 负责：
- canonical facts；
- 核心不变量；
- Entity、Value Object、Aggregate；
- Command 可否作用于 Aggregate；
- 确定性状态迁移。
Domain 禁止：调用模型、访问网络、读写数据库、了解 UI、拼装 Prompt、感知 LangGraph Node。

### 3.2 Application / Orchestration
Application 负责：
- 接收 Use Case 输入；
- 调用 Domain、Port 和 Policy；
- 管理事务、步骤依赖和结果组合；
- 决定何时进入模型、工具、审批、验证和完成阶段。
Orchestrator 只协调，不得：
- 重新解释用户意图；
- 通过 if/else 猜测业务 payload；
- 修复模型 Proposal；
- 复制领域不变量；
- 将工具失败伪装成业务成功。

### 3.3 Semantic Decision
- Router 识别 Goal/Intent，不执行 Workflow；
- Planner 仅用于步骤和依赖无法预定义的任务；
- 固定稳定流程优先使用 Workflow；
- Replanner 只能基于新 Observation 修订尚未冻结的语义计划；
- 模型输出必须是 typed Proposal、Assessment 或 Answer。

### 3.4 Governance / Control Plane
控制面负责：身份、scope、授权、风险、审批、Admission、状态合法性、幂等、预算和强制 route。
控制面不得创造 intent、target、payload、替代计划或业务回答。

### 3.5 Capability / Execution
- Service：Workflow 内固定、低风险、确定性调用；
- Tool：模型可动态选择，或必须经过统一治理和观测的能力；
- Adapter：外部协议与内部 Port 的转换；
- Executor：执行已接受调用并返回 typed result/receipt。
Tool 本身不得决定授权，也不得直接标记 Goal 完成。

### 3.6 Runtime / Persistence
Runtime 负责 checkpoint、恢复、幂等、重放和生命周期控制，不负责开放语义决策。
Repository 只持久化 Domain/Application 认可的事实，不返回 UI View 作为领域事实，不隐式创建业务对象。

### 3.7 Observability / Evaluation
观测层记录事实，不改变业务行为。Eval 评估结果，不成为生产分支规则引擎。

---
## 4. Canonical Model 与状态规范
### 4.1 类型必须分清
禁止在同一 Model 混装：
- Definition：不可变定义；
- Command：请求发生什么；
- Event/Receipt：已发生什么；
- Runtime Projection：当前执行视图；
- View/DTO：展示结构。

### 4.2 派生值默认不持久化
只有满足以下至少一项才考虑持久化：
- 恢复需要；
- 审计需要；
- 重放需要；
- 跨授权或审批边界；
- 长生命周期一致性需要；
- 无法从 canonical facts 确定性重建。
“以后可能有用”不是持久化理由。

### 4.3 Identity 与 Scope
禁止用空字符串、裸字符串、raw dict 表示关键身份和作用域。必须使用 typed ID、Value Object 或明确 DTO。
所有读取、检索、工具调用、Artifact 和 Memory 必须携带并校验 tenant/workspace/user/thread/task 等适用 scope。

### 4.4 Event 使用边界
不要机械地将所有状态事件化。只有需要恢复、审计、重放或长生命周期一致性的核心 Aggregate 才使用完整 Event + Projection。
Event 只能记录已发生事实，禁止记录愿望、建议或未执行 Proposal。

---
## 5. Agentic 决策与确定性管控
### 5.1 Proposal
模型可以提出 Goal、Plan、ToolCall、业务参数、恢复建议或最终回答，但 Proposal 不是权限、Command、执行事实或完成证明。
直接回答不应为形式统一伪造 Task、Command、Receipt 或 CompletionReport。

### 5.2 Admission / Validator
Admission 只能接受或拒绝 Proposal，不得：
- 补业务字段；
- 拼接 description/constraints；
- 修改 payload；
- 替换 Goal；
- 生成或重排 Plan；
- 静默降级为另一业务路径。
拒绝必须返回 typed `DecisionFeedback`，至少说明：原因、可修改字段、不可修改字段、required repair、revision scope 和 disposition。

### 5.3 禁止确定性业务 fallback
模型不可用或 Proposal 连续不合法时，只允许：
- fail closed；
- 暂停；
- 请求用户或外部权威输入；
- 请求缺失能力；
- 等待环境变化；
- 执行已冻结 Command；
- 对同一 digest 做幂等技术重试。
禁止生成替代 Goal、Plan、查询、写入内容或业务答复。

### 5.4 Procedure
Procedure 只封装稳定事务不变量，如 prepare、confirm、commit、receipt、compensate、reconcile。
Procedure 不得选择业务目标、决定 payload 或在失败后猜测替代路径。

### 5.5 确定性证明边界
确定性检查只能验证系统可机械证明的关系。禁止使用模型自述、字符串包含、相似度、排名或自然语言断言冒充语义保持、授权或唯一性证明。

### 5.6 Execution、Verification 与 Completion
必须分离：
1. **Execution Fact**：工具或 Command 是否执行；
2. **Semantic Verification**：Goal 是否达到；
3. **Completion**：required result contract 是否全部满足。
Receipt 不能直接代表 Goal 完成；模型 Verifier 也不能推翻确定性执行事实。

---
## 6. Tool、Command 与 Durable Execution
### 6.1 普通 ToolCall
只读、低风险、可安全重试的 ToolCall 在 Admission 后可直接执行，不应为形式统一持久化 Command。

### 6.2 Governed Command
以下调用必须形成 immutable Command：
- 需要审批；
- 有外部副作用；
- 不可安全重试；
- 需要 durable execution；
- 跨越授权、持久化或恢复边界。
Command 必须只缩权、不可覆盖。参数变化必须创建 superseding command。
Confirmation 绑定 AuthorizationDigest；Grant、Journal、Receipt 绑定同一 ExecutionCommandDigest。

### 6.3 Durable Task
Durable Task 至少支持：
- 明确生命周期和合法状态迁移；
- checkpoint 与恢复；
- 相同 digest 的幂等执行；
- Replay 不重新调用模型生成 Command；
- 失败分类、retry policy、补偿或 reconcile；
- required report 缺失时 fail closed。

---
## 7. Context、Memory、RAG 与 Capability
### 7.1 Context 四阶段
Context 必须按以下顺序处理：
1. Visibility：先执行权限和 scope 过滤；
2. Requirement Retrieval：根据当前任务需求召回；
3. Semantic Selection：模型选择语义相关内容；
4. Budget Materialization：压缩并注入 LLM Context。
禁止先召回全部内容再让 Prompt 自行做权限过滤。

### 7.2 存储边界
- Agent State：当前运行所需的结构化状态；
- LLM Context：当前模型调用实际看到的内容；
- Checkpoint：恢复执行所需快照；
- Artifact Store：大文本、文件和中间产物；
- Long-term Memory：跨会话可召回事实或经验；
- Retrieval Index：用于检索，不是事实权威源。
State 中优先保存 `artifact_id`，不要复制大型 Artifact 内容。

### 7.3 RAG
RAG 是检索和证据组织能力，不应成为隐藏 Router 或 Planner。
检索策略应由查询需求、数据特征和评测证据驱动。禁止为单个 benchmark case 硬编码规则；中间检索指标不能替代最终回答质量和证据正确性。

### 7.4 Capability Binding
只有完整满足同一 `CapabilityEquivalenceClass` 的 Provider 才能确定性绑定。存在语义差异时，必须由模型或外部权威选择。

---
## 8. 设计模式与可维护性
设计模式只用于隔离真实变化，不用于展示“架构完整性”。新增模式必须说明：变化来源、稳定边界、替换对象和测试方式。
推荐模式：
- **Ports and Adapters**：隔离模型、数据库、工具、MCP 和外部服务；
- **Strategy**：存在可独立替换且契约一致的策略；
- **State Machine**：状态集合有限、迁移可枚举；
- **Command**：需要审批、审计、幂等或重放；
- **Specification**：组合可机械验证的规则；
- **Repository**：隔离领域事实与存储实现；
- **Saga/Process Manager**：跨资源长事务与补偿；
- **Decorator/Middleware**：统一 trace、retry、timeout、policy；
- **Anti-Corruption Layer**：隔离外部语义和内部模型；
- **Factory/Registry**：对象创建复杂或 Provider 需要注册发现。
禁止：
- 每个类都创建 Interface、Factory、Manager；
- 只有一个实现且无变化来源时提前抽象；
- 用设计模式掩盖职责不清；
- 让 Strategy 承担本应由模型作出的开放语义决策；
- 用 converter 长期维护镜像模型；
- 创建 God Service、God State、God Workflow。

---
## 9. 代码组织规范
### 9.1 LangGraph
- Graph 表达编排和状态迁移，不承载领域事实权威；
- Node 必须薄，只做输入提取、Use Case 调用和结果写回；
- 禁止在多个 Node 复制业务规则；
- GraphState 只存运行必需状态，字段必须 typed；
- 大对象使用 artifact reference；
- checkpoint 恢复不得导致模型或副作用重复执行。

### 9.2 Router、Planner 与 Workflow
- Router 输出 Goal 列表和必要语义参数，不输出执行完成事实；
- Goal 间固定依赖由契约或 Workflow 定义；动态依赖才交给 Planner；
- 固定流程不得为“更 Agentic”而调用 Planner；
- Planner 不负责授权、执行和完成判定；
- Workflow 内稳定低风险步骤优先 Service 化；动态或受控能力 Tool 化。

### 9.3 Error Taxonomy
错误至少区分：Validation、Semantic Rejection、Authorization Denied、Capability Missing、Execution Failure、Transient Failure、Verification Failure、Completion Failure、Invariant Violation。
禁止捕获异常后返回空结果、默认成功或模糊 fallback。

### 9.4 依赖注入与测试性
模型、时钟、ID、Repository、Tool、Policy 和外部 Provider 必须可通过 Port 注入。测试不得 monkey patch 生产规则来构造通过结果。

### 9.5 命名
命名必须表达业务角色和生命周期。禁止使用 `data`、`info`、`manager`、`processor`、`handler` 等无法表达职责的泛化名称，除非其边界确实清晰。

---
## 10. 强制开发流程
任何功能、修复或重构必须按以下顺序进行：
1. 定义用户目标、当前错误行为和验收标准；
2. 完成 Decision Ownership Analysis；
3. 完成 Fact Ownership Analysis；
4. 标明受影响模块、依赖方向和删除路径；
5. 先定义 E2E Given/When/Then 与反事实断言；
6. 实现最小改动；
7. 补充必要的 Unit、Contract、Integration Test；
8. 删除旧字段、旧入口、旧 converter 和临时 fallback；
9. 执行 E2E、相关低层测试和 lint/type check；
10. 记录执行命令、结果和剩余风险。

### 10.1 变更分析最小模板
```markdown
## Goal
## Current Incorrect Behavior
## Expected User-visible Result
## Out of Scope
## Decision Ownership
## Fact Owner and Write Path
## Affected Modules and Dependency Direction
## Removed Legacy Path
## Risks
```

### 10.2 E2E 最小模板
```markdown
## E2E: <name>
Given: <输入、身份、初始事实>
When: <从正式入口执行的行为>
Then: <用户可观察结果>
And not: <禁止发生的副作用或错误结果>
Path: <必须经过的生产组件>
Allowed fakes: <仅外部边界>
Evidence: <trace/event/receipt/report>
Command: <本地或 CI 执行命令>
```

### 10.3 AI Coding Agent 行为
开始编码前必须先输出：目标、所有权、影响边界、E2E 和计划删除内容。
编码过程中禁止：
- 因不确定而新增 fallback；
- 为兼容保留新旧双轨；
- 未搜索调用方就修改公共模型；
- 用 raw dict 绕过类型边界；
- 新增抽象却不说明变化来源；
- 未运行测试就声称完成。
信息不足以确认事实 owner、授权边界或外部契约时，应停止该部分实现并明确阻塞原因，不得猜测。

---
## 11. 测试与评估门禁
### 11.1 测试职责
- Unit：领域不变量和纯函数；
- Contract：Port 与 Adapter 契约；
- Integration：数据库、Checkpoint、ToolGateway 等组合；
- E2E：正式入口到用户结果；
- Offline Eval：模型、检索和语义质量；
- Online Evaluation：线上质量、成本、延迟和失败分布。

### 11.2 E2E 最低覆盖矩阵
核心变更按适用性至少覆盖：
- Direct Message；
- 普通只读 ToolCall；
- Governed Action；
- Durable Task；
- Admission Denied；
- Authorization Denied；
- Capability Missing；
- Execution Failure；
- Verification Failure；
- Replay 不重算 Command、不重复副作用；
- Context/tenant 隔离；
- 新路径生效且旧路径不可达。
每项变更至少包含一个成功场景，以及一个失败、拒绝、恢复或重放场景。

### 11.3 Golden Set
新增或改变语义决策、检索、回答、规划和验证行为时，必须先补 Golden Set。
Golden Set 应覆盖真实用户目标、边界输入、失败路径、反事实和历史回归；禁止只增加能够证明当前实现正确的样例。

---
## 12. Observability、安全与审计
### 12.1 Trace 最低字段
按适用性记录：trace_id、tenant/workspace/user、thread/task、goal、proposal/version、policy/version、authorization digest、command digest、tool/provider、attempt、latency、token/cost、receipt、verification、completion 和 error taxonomy。
Trace 不得记录不必要的密钥、完整敏感内容或跨 scope 数据。

### 12.2 权限与风险
- Identity 和 scope 必须在入口解析并贯穿调用链；
- Policy Engine 决定是否允许以及是否需要审批；
- ToolGateway 统一执行授权、风险、预算和审计；
- Prompt 不能代替权限控制；
- 高风险操作必须绑定明确 target、payload、授权和确认；
- 批量、删除、外发、不可逆和高成本操作默认提高风险等级。

### 12.3 审计事实
审批、授权、Command、Journal、Receipt、补偿和 Completion 必须可关联到同一任务和 digest 链路。审计记录不可被普通业务更新覆盖。

---
## 13. 迁移、兼容与 ADR
Schema 或 Model 迁移必须说明：canonical 新模型、数据迁移方式、调用方迁移、旧写入口关闭、回滚策略、E2E 验证和最终删除日期。
以下情况必须创建 ADR：
- 跨模块边界调整；
- 引入新框架或基础设施；
- 新增持久化事实；
- 引入 Event Sourcing、Saga 或兼容窗口；
- 改变 Command、Replay、Approval 或 Completion 语义；
- 偏离本文档中的“必须/禁止”。
ADR 不能代替 E2E。

---
## 14. Review 合并门禁
PR 合并前必须确认：
- [ ] 用户目标和验收标准明确；
- [ ] Decision Owner 明确；
- [ ] Fact Owner、canonical model 和唯一写入口明确；
- [ ] 依赖方向正确，无框架侵入 Domain；
- [ ] Orchestrator、Validator、Adapter 未创造业务语义；
- [ ] 无重复事实、镜像 Model、双写或隐藏 fallback；
- [ ] Proposal、Command、Execution Fact、Verification、Completion 已分离；
- [ ] 旧字段、旧路径和临时兼容已删除或有期限 ADR；
- [ ] 正式入口 E2E 已执行并通过；
- [ ] E2E 包含用户结果和关键反事实；
- [ ] 至少一个失败、拒绝、恢复或重放场景通过；
- [ ] Unit/Contract/Integration Test 按风险补齐；
- [ ] Trace、审计和错误分类足以定位问题；
- [ ] 验证命令、结果和剩余风险已记录。

---
## 15. Definition of Done
一项变更只有同时满足以下条件才算完成：
1. 行为和架构边界符合本规范；
2. 所有事实和决策均有唯一 owner；
3. 没有新增冗余状态、静默 Proposal 改写或确定性业务 fallback；
4. 全部调用方已迁移，旧路径已删除或有明确移除期限；
5. E2E 从正式入口经过生产主路径并通过；
6. 用户结果、失败结果和关键反事实得到自动断言；
7. 关键执行、授权、Receipt、Verification 和 Completion 可观测；
8. 文档、Golden Set、迁移说明和测试同步更新；
9. 实际执行过验证命令，并如实记录结果；
10. 未验证风险被明确列出，不以“应该没问题”代替证据。
**没有可执行 E2E，就没有可信的落地设计。**
