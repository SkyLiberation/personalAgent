# 普通对话广泛研究交付优化方案

**首个单变量候选已经进入 `A2`，定向单样本已交付，但成本与扩大回归仍未完成。** 密封产品样本记录了最终交付失败，可重复的 provider action 契约基线又证明 auto/no-plan 首轮会暴露强制 `plan_step_id`，而现有普通动作测试绕过了该 Schema。首个候选只删除这条合成绑定；只有同一阻塞仍然复现，才重新评审收口机会保障。两个变量不得在首个 target 中合并。执行数字与归档坐标只由[当前 E2E 用例盘点](../evals/02-current-case-inventory.md)维护。

本文是[设计优化队列](design-optimization-backlog.md)中 `CONVERSATION-RESEARCH-DELIVERY-001` 的条件详细设计。准入状态和优先级只由该队列维护；当前样本、结果数字和归档坐标只由[当前 E2E 用例盘点](../evals/02-current-case-inventory.md)维护。

## 1. 用户结果与失败边界

**目标结果是让普通 Conversation 在一次交互中交付多来源研究结论，而不是让内部工作项全部变成 `completed`。** `tool-protocol-boundary` 要求模型查阅 OpenAI 与 MCP 官方来源，比较工具选择、权限边界和结果契约，并返回带官方 URL 的中文答案。

当前密封样本支持以下因果判断：

1. 首次 `working_plan_missing` 后已经出现绑定来源步骤的成功搜索，因此该反馈不是最终未交付的充分原因。
2. 两次不适用的 `read_action_output`、重复来源搜索和两次智能体委托增加了模型决策与 Context 成本。
3. 两个 `AgentArtifact` 返回后，运行系统在父级模型再次判断证据前结束交互；最终结果是 `limitation`，工作项仍为待完成。
4. 子级运行的 `completed` 只证明子级已生成结果，不证明父级用户目标已经满足；运行系统不得据此自动完成父级工作项。

本方案只处理普通 Conversation 的决策浪费、预算准入和语义收口。显式外部智能体委托的超时与父级交付由 `AGENT-DELEGATION-DELIVERY-001` 负责；前台委托与响应后继续工作的意图边界由各自队列项负责。方案不得通过增加总预算掩盖重复动作，也不得由确定性代码生成自然语言答案。

## 2. 责任主体保持分离

**优化必须让模型拥有继续、停止和语义完成判断，同时让确定性代码继续拥有资源与状态不变量。** 本方案不把“更 Agentic”解释为模型可以无限消费资源或直接改写权威状态。

| 决策或事实 | 唯一责任主体 | 本方案中的边界 |
| --- | --- | --- |
| 是否需要 `Plan`、下一步调用什么、证据是否足够 | 模型 | 模型可以直接调用工具并回答；没有独立理由时不创建 `Plan` |
| 用户或产品允许的成本、时间和外部动作范围 | Policy | 提供不可突破的资源包络，不决定用户目标是否完成 |
| 已提交 token、工具和智能体调用量 | 运行系统与服务提供方 | 使用真实 usage 记账，不从 Prompt 或工作项状态推断 |
| 工具或智能体是否执行成功 | 执行网关 | 产生 `Observation` 或 `AgentArtifact`，不自动完成工作项 |
| 最终答案是否满足语义标准 | 模型或 Verifier | 根据用户要求和证据进行开放世界判断 |
| required result contract 是否齐全 | Completion Gate | 只检查所需结果与证据，不用预算耗尽冒充完成 |

`WorkingPlanProposal.status` 和 `FinalMessage.resolved_plan_step_ids` 继续由模型提出。Admission 只校验引用、状态迁移和执行证据，并把合法 Proposal 写入 canonical working plan。工具成功不得自动把工作项改成已完成。

## 3. 外部优秀智能体只提供机制约束

**外部实现共同支持“减少无意义回合、按压力治理 Context、把 Plan 限定在必要场景”，但没有任何实现证明本工程需要新的通用预算规划器。** 本方案只采纳直接映射到当前失败的语义。

| A 级实现 | 可复核机制 | 本方案采纳 | 本方案拒绝 |
| --- | --- | --- | --- |
| OpenAI | [GPT-5.6 Model guidance](https://developers.openai.com/api/docs/guides/latest-model)要求精简重复指令、只暴露任务相关工具，并把不需要每一步重新判断的有界工具链合并执行；最终答案质量必须与 token、延迟和调用量一起评估 | 减少重复决策与无关工具 Schema；把语义判断留给来源结果返回后的父级模型 | 不引入 Programmatic Tool Calling 运行环境，不把调用更少单独写成用户收益 |
| Gemini CLI | [Planning tools](https://github.com/google-gemini/gemini-cli/blob/main/docs/tools/planning.md)只把 `Plan Mode` 用于复杂规划或明确进入该模式的请求；[Configuration](https://github.com/google-gemini/gemini-cli/blob/main/docs/reference/configuration.md)分别提供工具输出摘要、Context 压力阈值和循环检测 | 普通有界研究不强制创建 `Plan`；资源压力与语义完成分开处理 | 不复制任务跟踪器、模式状态机或固定复杂度档位 |
| DeepSeek Harness | [`Compaction` 固定提交](https://github.com/deepseek-ai/deepseek-harness/blob/b150a551b8d465e31e418e1b2eaf5e79bbb7d28e/docs/subsystems/compaction.md)把压缩保留为可选能力；出现压力时先裁剪工具结果并重新计量，再按需摘要 | 先收缩已测的大型输入来源；只有正式入口复现 Context 压力后才讨论压缩 | 当前不引入 Compaction 服务、持久摘要事件或第二套 token 计量框架 |

外部坐标只证明候选机制已经存在，不能替代本工程 target。设计不得复制外部对象数量、插件拓扑、默认阈值或状态生命周期。

## 4. 第一候选先删除强制 `Plan` 绑定

**第一个单变量候选是让没有现存 working plan 的普通动作保持无绑定，而不是先建设动态预算机制。** 当前代码在 `interaction_mode="auto"` 且没有 working plan 时，仍向每个工具 Schema 加入必填 `plan_step_id`。这个字段迫使模型同轮创建 `WorkingPlanProposal`，并使简单研究承担额外的创建、绑定和完成协议。

候选只改变以下行为：

1. 没有现存 working plan 时，工具和智能体动作 Schema 不出现 `plan_step_id`。
2. 模型可以直接并发取得两个独立官方来源，并在下一次语义判断中回答。
3. 模型主动创建 working plan 后，后续动作仍必须绑定一个待完成步骤；已完成步骤继续不可变。
4. 用户明确要求计划评审，或者跨用户轮次恢复现有 working plan 时，既有 Plan 契约保持不变。

该候选不得新增 Model、状态、配置、Planner、Workflow 或兼容分支。实现应删除 `allow_new_plan_binding` 对无现存 Plan 动作 Schema 的强制影响，并删除只为合成 Plan 绑定服务的提示词与测试预期。Admission 不新增猜测或降级逻辑。

第一候选只在同输入 target 同时满足用户结果和成本门禁时保留。如果模型仍在成功来源结果后重复搜索，或者仍在最终综合前被预算截断，则撤回第一候选，不与下一候选组合后解释收益。

## 5. 第二候选保障一次有界收口机会

**只有第一候选的 target 仍复现“最新有效证据返回后没有父级判断回合”，才准入收口机会保障。** 该候选不按简单、中等、复杂给任务打分，也不让模型自行扩大预算；它只防止资源门禁在动作结果和语义判断之间切断闭环。

### 5.1 预算分成资源包络和运行分配

**固定值只能表达 Policy 的最大资源包络，不能表达任务完成条件。** `LoopBudgetPolicy` 可以继续保存最大模型回合、工具调用、智能体调用和累计 token，但运行系统不得在最新 `Observation` 到达后直接用固定文本结束交互。

运行系统在准入下一批工具或智能体动作前必须证明：

```text
已提交 usage
+ 待执行动作的有界结果成本
+ 一次 final-only 请求的输入投影
+ final-only 输出上限
+ 必需的 Verifier 成本
<= Policy 资源包络
```

输入投影必须针对将要发送的 canonical request envelope，并沿用目标服务提供方与模型的计量规则。Application 不得使用固定“每字符多少 token”或任务复杂度等级猜测。现有 Structured Model Adapter 如果不能提供同口径预检，该候选保持 `A1`；实现前只能在现有 Adapter 边界补最小请求计量能力，不得新增通用 Budget Service、数据库状态或第二份 usage 事实。

### 5.2 收口阶段仍由模型决策

**进入收口阶段后，运行系统只收缩动作面，不替模型判断完成。** 该阶段复用现有 final-only 生成路径，只允许模型返回 `FinalMessage`；模型根据已有证据选择：

- 证据充分时返回 `answer`，并按需声明 `resolved_plan_step_ids`；
- 用户目标存在关键歧义时返回 `clarification_required`；
- 权威来源、权限或能力确实不足时返回有事实依据的 `limitation`；
- required result contract 无法满足时返回 `failed`。

收口阶段不暴露工具、智能体或新的 working plan，因此最多消费一次父级语义判断，不会形成新的动作循环。运行系统不得把累计 usage、子级 `completed` 或工具 `succeeded` 自动转换成 `answer`。

### 5.3 复杂任务通过继续契约扩展，不创建预算状态机

**真正复杂的任务需要更多资源时，优先复用现有未决 working plan 和下一次用户交互，不新增 `BudgetRequest` Aggregate。** 模型必须说明已完成结果、未决义务和继续工作的必要性；用户或产品 Policy 决定是否提供新的交互资源包络。只有独立复杂任务 baseline 证明这种边界仍无法交付，才能重新评审自动续算机制。

## 6. 其他效率机制保持条件化

**工具投影和 Context 压缩不得与前两个候选同时实现。** 当前追踪记录已经能测量动作 Schema 和 typed inputs 的字符组成，但这些指标只能确定后续检查顺序，不能自动准入新层。

后续条件按以下顺序判断：

1. 第一候选交付用户结果但动作 Schema 仍占主要输入时，只收缩当前已确定不可用或与任务阶段无关的动作定义；不得通过用户关键词硬编码工具选择。
2. 有界 `Observation` 或 `AgentArtifact` 被每轮完整重复注入时，优先复用现有 `ArtifactRef` 和按需读取路径；不得新增可写摘要副本。
3. 只有目标服务提供方的真实 Context 窗口出现可重复压力、错误截断或无法发送请求时，才重新评审 Compaction。
4. 查询重复但仍有足够收口资源时，由模型根据 typed 的重复反馈修订策略；确定性代码只拒绝机械重复，不判断来源是否语义充分。

本方案明确拒绝任务复杂度分类器、三档 token 表、通用 Budget Planner、自动无限扩展预算和完整外部 Harness 移植。

## 7. baseline、target 与单变量门禁

**每个候选必须在同一正式入口、自然输入和服务提供方身份下独立证明用户结果，不能把两个失败 target 合并成一次成功。** 首个验证继续使用 `tool-protocol-boundary-run-1`，并保留当前评测器、隔离主体与 required source group。

第一候选的 Contract 与 Runtime Conformance 必须证明：

- 没有 working plan 时，工具动作 Schema 不包含 `plan_step_id`，动作可以通过 Admission；
- 已存在 working plan 时，动作仍必须绑定待完成步骤；
- 工具成功不会自动完成步骤；
- 用户要求计划评审时仍保留原 Plan 边界。

第二候选的 Contract 与 Runtime Conformance 必须证明：

- 运行系统在准入新动作前包含 final-only 与必要 Verifier 的资源投影；
- 最新成功 `Observation` 返回后至少存在一次受限父级判断机会；
- 收口阶段不能调用工具、智能体或创建新 Plan；
- usage 缺失、预检不可用或资源不足时 fail closed，且不能生成未经证据支持的答案。

每个定向 target 都必须交付覆盖三个比较维度和两组官方 URL 的 `answer`，并保持零参数拒绝、零跨主体泄漏、零知识写入、零重复副作用和完整 usage。效率只按同输入归档比较模型调用、决策回合、工具与智能体调用、总 token、延迟和 Context 组成；单样本只能判断候选是否值得继续，不能声明统计收益。

定向 target 通过后才运行既有正式样本组。机制收益候选必须在独立可还原代码身份执行 target-minus-mechanism 消融；消融只移除当前候选，不得同时恢复强制 Plan、扩大预算或改变 Prompt。target、消融或正式门禁失败时删除候选代码，不保留生产开关、降级路径或双轨入口。

## 8. 复杂度预算与退出条件

**本方案的净复杂度目标是删除一次合成 Plan 协议，并最多复用一条现有 final-only 路径。** 第一候选不得新增生产类型；第二候选最多扩展现有模型请求预检边界和 Conversation Loop 的准入判断。任何新增持久状态、Repository、Router、Workflow、Agent、通用 Planner、Compaction 层或兼容开关都超出本方案，必须重新提交 Complexity Justification；改变 Completion 语义时还必须单独创建 ADR。

若第一候选已经满足用户结果和成本门禁，第二候选直接删除，不进入实现。若第一候选失败而第二候选独立通过，则只保留第二候选。若两个候选都失败，设计回到 `A1` 并重新定位最早未恢复阶段，不得把二者叠加成第三个补丁分支。

候选通过定向 target、适用消融和正式门禁后，当前事实迁入 Conversation 固定流程与 Verification/Completion 专题；随后从设计优化队列移除对应问题，并删除本文。没有这些执行证据前，本文只能表述为条件设计，不能声称已经修复或可发布。
