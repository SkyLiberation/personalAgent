# personalAgent 当前核心架构

本文记录截至 2026-08-10 已落地的生产架构事实。尚未落地的设计只进入
[future 索引](../future/README.md)，不能反向定义当前架构；产品能力、E2E 和发布可信度的当前事实由
[`phase0-capability-release-baseline.md`](phase0-capability-release-baseline.md) 拥有。
[`core-architecture-e2e-audit.md`](core-architecture-e2e-audit.md) 是 paired baseline 的历史证据 owner，
不定义当前主链。

归档工程矩阵 E01–E13、C01–C04、L01–L06 共 23/23 passed，archive 为
`data/e2e_traces/20260726T011631.187395Z-20684-4a62da6a`。L01–L06 与 E16–E19 现已改为
不泄漏内部 Tool、Agent、Artifact、verdict 或执行顺序的自然用户场景；当前定向证据见
`phase0-capability-release-baseline.md`。旧完整 archive 不再匹配当前 catalog，当前完整矩阵
和 clean-revision 发布资格都尚未建立。

Conversation governed save 的当前 matching E14 archive 为
`data/e2e_traces/20260810T131706.858565Z-15232-bd519e05`：它证明 exact-span Command、atomic
statement 不被语义抽取改写、跨 scope 拒绝、精确 Claim、恢复和 replay。paired baseline 由
[`core-architecture-e2e-audit.md`](core-architecture-e2e-audit.md) 统一保存。当前 archive 来自 dirty
worktree，只是定向工程证据，不建立发布资格。

目标入口改造使用相同自然输入先后执行 baseline 与 target：读取 baseline
`20260803T142413.474927Z-4864-39fedcf5`、删除 baseline
`20260803T142932.564456Z-23720-19ba8517`、Project baseline
`20260803T143007.354551Z-26256-84d0bf1d` 均证明旧 Conversation 缺少相应能力；改造后 L01
`20260803T152242.957743Z-388-d0850c85`、E22
`20260803T152242.957743Z-388-d0850c85`、E23
`20260803T151935.921382Z-27308-be5eadbf` 通过。Research paired baseline
`20260803T143230.864789Z-6460-dbd005fd` 未证明 ResearchRun 对开放调查优于 Conversation 或
Project，因此 ResearchRun 保持 Scheduled Intelligence 边界。以上仍是 dirty revision 的定向证据。

## 0. 框架命题：可信 Agent Runtime

personalAgent 的顶层目标不是让模型“多调用几个 Tool”，也不是把自然语言机械转换成 JSON，
而是建立一套能够长期承载知识、外部能力和真实副作用的可信 Agent Runtime：

> 模型负责开放世界的语义判断；确定性系统负责准入、权限、状态迁移和执行；执行系统产生事实；
> Verifier 判断语义结果；Completion Gate 依据 required result contract 判断用户目标是否关闭。

主链可以压缩为一个稳定协议：

```text
User Goal + Visible Context + Committed Observation
  -> Semantic Model proposes a typed Decision
  -> Admission / Policy accepts or rejects
  -> Gateway / Executor produces an Execution Fact
  -> Verifier assesses evidence-backed outcome
  -> Completion Gate closes or keeps the obligation open
```

这里的 typed JSON 是模型与 Runtime 之间的 wire representation，不是架构本身。object-root、
Pydantic、OpenAI-compatible transport、手写 loop 或 LangGraph 都可以替换；以下权力边界不能
随实现替换而改变：

1. **Proposal 不是权限**：模型可以选择业务能力和参数，不能给自己授权；
2. **Proposal 不是执行事实**：模型声称“已经完成”不能替代 Tool、Command、Journal 或 Receipt；
3. **Admission 只裁决，不创作语义**：它可以拒绝并返回 typed feedback，不能补业务参数、换目标
   或生成替代答案；
4. **Execution、Verification、Completion 分离**：Tool `ok=true`、Agent `completed`、数据库新增
   记录和 Verifier 通过分别只证明各自事实；
5. **一个业务事实只有一个 owner 和写入口**：索引、Graph、Runtime projection 与 View 不成为
   第二写源；
6. **复杂度由生命周期而不是 Agent 术语准入**：固定事务不交给 Planner，Conversation 不承担独立后台
   Project 成本，没有失败 E2E 的新机制不进入主链。

### 0.1 一套目标责任链，按需选择执行语义

普通用户只面对 Conversation 这一目标入口，不需要先判断 Tool、Workflow 或 Project。模型基于
目标、约束和已提交 Observation 提出粗粒度能力；确定性系统再把已准入的能力交给唯一业务 owner。
下面是框架内部的执行语义，不是三种产品模式或三个并列入口：

| 目标约束 | 下一步 owner | 内部执行语义 | 为什么 |
| --- | --- | --- | --- |
| 多轮动态、无需独立后台生命周期 | 模型按目标与执行事实逐轮提出下一步；用户明示或存在协调收益时维护可验收工作项清单 | 当前对话循环 | 对话日志与上下文支持多轮和恢复；按需前台计划只服务当前对话，不承担后台调度 |
| 拓扑和事务不变量固定 | Application / Domain | 具体 Use Case / 领域 Workflow | 模型不能重排确认、写入、Receipt 或补偿顺序 |
| 路径动态且跨进程、用户轮次或审批边界 | 模型提出 Project 创建参数；Project 内 Planner 提出 Plan | Investigation Project | accepted Plan、ready set、journal 和 Completion obligation 都有生产消费者 |

这些语义共享 Proposal、Admission、Execution Fact 和 Completion 的权力观，但不共享一个 God
Task、God State 或统一 Planner。`Workflow` 只表示具体业务 owner 的稳定事务不变量；它不是
用户可选择的运行模式，也没有全局 Workflow Registry。专用 UI、自动化和管理 API 可以直达同一
Application Use Case，但多个协议入口不能制造第二事实 owner。

### 0.2 现实故障如何支撑框架

| 已观察问题 | 执行证据 | 支撑的框架原则 |
| --- | --- | --- |
| 模糊新请求被旧答案冒充完成 | E01 baseline `20260729T033100.290836Z-35328-02db4988` | 生成文本不等于完成；澄清是显式终态 |
| 整条保存请求把“请保存、先确认”等控制语义写成 Claim | B02 `20260729T031804.415533Z-15972-214cb81c` | 模型语义选择、用户授权和 canonical write 必须分离 |
| exact-span 保存需要确认、原文绑定、scope 拒绝和 replay | E14 `20260810T131706.858565Z-15232-bd519e05` | Proposal、Command、semantic annotation、Receipt 与知识写入口各自拥有事实 |
| terra 在顶层 union structured schema 上 retry 超时 | Phase 0 Provider probe/E17 记录 | Provider transport 是可替换能力边界，不能污染业务 contract |
| 子 Agent 返回 Artifact 后仍被重复委托，或 child terminal 被误当父完成 | E17/C04/L04 定向 archive | child execution fact 与父级综合、完成分离 |
| live Investigation 有搜索结果却因 repair lineage 不闭合而无法交付报告 | B03 到 IP01 的同输入 archive 链 | Evidence Admission、Plan revision 和 Completion obligation 必须由 durable owner 维护 |
| Personal-only 与多源 grounded answer 曾有两个最终 owner | ASK-001A/B paired baseline 与目标 E2E | Knowledge 只拥有 evidence/conflict facts，Conversation 统一拥有 FinalMessage |

这些 archive 证明的是对应工作树和输入上的工程事实，不自动建立 clean-revision 发布资格。
框架的可信度来自“问题—owner—最小改动—目标 E2E”链路，而不是来自“对齐优秀 Agent”的类图。

### 0.3 当前实现与框架原则的边界

| 层次 | 当前选择 | 稳定性 |
| --- | --- | --- |
| 框架不变量 | Proposal → Admission → Execution Fact → Verification → Completion | 稳定，改变需 ADR 与产品 E2E |
| 普通用户入口 | Conversation goal entry | 稳定；内部执行语义不暴露为模式选择 |
| 模型协议 | `AgentTurnDecision` / `AgentTurnDecisionWithPlan` object-root lifecycle projection | 两者承载同一 Proposal union，仅调整无 Plan/已有 Plan 阶段的 schema 首选顺序；可由同等 contract 替换 |
| Schema/transport | Pydantic + strict JSON Schema 或 JSON Object Adapter | deployment capability，集中在 Model Adapter |
| 编排技术 | 显式 Python loop、领域状态机、worker queue | 可替换，但不能改变 canonical owner |
| 外部能力 | Tool、MCP、A2A Adapter | 可扩展，必须先通过 visibility、Admission、Gateway 与 E2E |

## 1. 架构边界与依赖方向

当前生产代码按以下稳定方向协作：

```text
Interface / Infrastructure
  -> AgentService / AgentRuntime composition root
  -> Application use cases and orchestration
  -> Domain models, state machines and Ports
```

- Interface 负责协议转换、身份解析和输入校验，不决定业务语义；
- `AgentService` 是 Web、CLI、飞书使用的 facade；
- `AgentRuntime` 集中装配 Store、Model、Tool、Agent 和 Application service，不成为业务事实 owner；
- Application 协调模型、Port、Policy 和领域服务；
- 外部 Provider 通过 Adapter 接入，不能创造 intent、授权或完成事实；
- PostgreSQL、Artifact Store、Graph/Retrieval Index 分别保存其契约允许的事实或投影。

核心模型仍区分：

```text
Definition  不可变定义
Command     请求执行一次有界变更
Event       已经发生的事实
Projection  从事实得到的运行视图
View / DTO  读取时组合，不成为新事实 owner
```

同一事实只能有一个 canonical owner 和一个合法写入口。可确定性重建的值默认不持久化，
禁止用 alias、双写、converter 或 fallback 维护新旧事实副本。

包依赖由 `scripts/check_layers.py` 的显式 DAG 检查。2026-08-10 在当前工作树实际执行结果为：

```text
packages=14 edges=50
unknown_packages=none
missing_packages=none
cycles=none
forbidden_edges=0
OK: explicit package DAG satisfied
```

package discovery 只识别真实 Python package；空迁移目录不再制造未知 package。

## 2. 正式入口与 Composition Root

普通对话的正式入口统一为：

- Web：`POST /api/conversation/turn`；
- CLI：`personal-agent entry`；
- 飞书：消息事件进入 `FeishuService`；
- 三者最终都调用 `AgentService.converse()`。

产品能力也保留各自明确的 Application/API 入口。例如 Personal Knowledge ingest、Knowledge
Lifecycle、Research subscription/run、Review feedback 和 Artifact 操作不必伪装成一次通用
Conversation Task。固定、稳定的产品流程优先直接调用相应 Use Case。

路径动态且需要跨进程、用户轮次或审批边界维持交付契约的任务，可以由普通 Conversation 的
`start_durable_investigation` 粗粒度能力创建，也可以由已明确知道业务动作的 UI/自动化通过
`POST /api/investigation-projects` 直接创建。两者复用 `InvestigationProjectService.create`；创建
先持久化 immutable definition，再异步入队。查询只读取 projection，不调用模型或推进状态。该能力的
当前事实与发布证据边界由
[`durable-investigation-project-current-state.md`](durable-investigation-project-current-state.md)
记录。

装配关系为：

```text
WebAppContext / CLI / Feishu
  -> AgentService
  -> AgentRuntime
     -> ConversationService
     -> KnowledgeService
     -> KnowledgeLifecycleService
     -> InvestigationProjectService
     -> ResearchService
     -> Review / KnowledgeGap use cases
     -> ToolExecutor / ToolGateway
     -> AgentGateway
     -> Model Ports and persistence adapters
```

Investigation Project 使用 PostgreSQL append-only journal 和现有 worker queue；AgentGateway
的生产 run store 为 PostgreSQL。Conversation 只在用户明确需要跨交互持续、进度查询、暂停或
steering 时创建 Project，并且只持久化 `ProjectReference`，不拥有 Project definition、accepted Plan、
状态或 Completion。普通 Conversation 可以拥有独立的轻量 `ConversationWorkingPlan`；它只表示当前
前台目标的可验收工作项，不是后台项目调查规划的副本，也不驱动队列、租约或可持久调度。

`AgentRuntime` 是唯一集中装配点，但 Personal Knowledge、Research、Interaction、Tool audit 等事实仍由
各自 Store/Service 拥有；Composition Root 不通过字段镜像成为第二事实源。

## 3. 普通 Interaction 主循环

普通用户对话由 `application/conversation/ConversationService` 拥有。它不是旧
Task/GoalGraph 的轻量包装，也不为直接回答强制创建 Task、Goal、Command、Receipt 或
CompletionReport。

```text
ConversationMessage[]
  -> materialize EffectiveCapabilities
  -> Model returns AgentTurnDecision
     -> FinalMessage
        -> optional terminal WorkingPlan update
     -> ContinueTurnProposal
        -> optional WorkingPlan proposal / wait_for_user
        -> actions[]
           -> ToolCallProposal | AgentDelegationProposal
  -> deterministic admission and budget checks
  -> execute accepted actions through Ports/Gateways
  -> ActionObservation | DecisionFeedback
  -> next model turn
  -> FinalMessage
```

### 3.1 决策所有权

- 模型负责开放语义：是否直接回答、是否需要计划、选择哪个语义能力、委托什么 bounded
  sub-goal、如何根据 Observation 修订下一步；
- Runtime 负责 schema、重复 action、预算、scope 和能力存在性等机械判断；
- Admission 只能接受或返回 typed `DecisionFeedback`，不得补业务参数、改写 working plan 或替换目标；
- Tool/Agent 执行产生 execution fact；模型或领域 Verifier 判断语义结果；领域状态机判断完成。

模型输出使用同一 object-root 形状和同一 Proposal union；只按 Conversation Working Plan 生命周期选择 schema 投影：

```text
无 admitted Plan: AgentTurnDecision
└─ decision: ContinueTurnProposal | FinalMessage

已有 admitted Plan: AgentTurnDecisionWithPlan
└─ decision: FinalMessage | ContinueTurnProposal

两者共享:
├─ optional WorkingPlanProposal
└─ actions: ToolCallProposal | AgentDelegationProposal []
```

**两个 envelope 不是两个业务事实或决策 owner。** `kind`、Admission、journal 和 Completion Gate 完全共享；
第二个 envelope 只调整已有计划生命周期中的 union 顺序，帮助结构化模型优先选择交付结果。`HARNESS-002` 的
消融进一步证明，单改 union 顺序或接受相同 Proposal 为 no-op 都不能解决停滞；真正的问题是模型被要求先写一次
计划完成状态、再写一次同义 FinalMessage，并被进度门禁阻止在同一步继续补充证据。

不存在 `.root` 兼容入口、`action/actions` 双轨、working-plan step 直接执行或确定性业务 fallback。

### 3.2 按需前台工作清单

**`ConversationWorkingPlan` 是当前对话拥有的可验收工作项清单，不是通用规划器、固定流程或后台项目规划。**
每项可以描述分析、实现或用户可见交付，但必须同时写明预期结果和完成条件；“搜索资料”“调用工具”这类只有活动、
没有产出的描述不合格。用户明确要求查看或调整时，模型必须先提出结构化计划并等待审阅；即使用户没有说出“计划”，
模型也可在漏项、重复、跨预算、上下文、进程或用户轮次恢复，以及调整方向的收益显著时主动提出短期计划。default
模式必须先展示计划并停下，不能夹带动作；只有调用方明确选择 auto 模式，计划才可与已授权动作同轮提交。模型不能根据
用户文本猜测或自行切换 auto。普通多步请求仍走轻量循环，不能只因动作数量创建计划。

- Interaction journal 是唯一 canonical 写入口，HTTP response 只投影同一对象；新 Web 进程可从 journal
  恢复当前清单；
- 模型只提出 `goal + steps`，看不到也不回传 `plan_id/revision`。Runtime 直接对照当前 canonical
  清单检查 step ID 唯一和 completed step 不可删除或改写；
- `revision` 仅由 Runtime 单调生成，用于 journal 恢复排序和响应展示，不是乐观并发令牌，也不声称提供
  CAS。旧清单全部完成后，内容不同的新清单获得新的 `plan_id`；
- Tool/Agent action 必须绑定当前 pending step，成功 Observation 仍只是 Execution Fact；模型可在继续工作时
  修订状态，也可在最终答案的 `resolved_plan_step_ids` 中声明由本答案完成的 pending 结果。Runtime 只机械绑定
  已成功 action ID，不根据 Tool success 自动判断语义完成；
- `FinalMessage` 没有覆盖全部 pending step ID 时拒绝完成；它覆盖全部 pending 时，FinalMessage 是唯一语义
  完成声明，不再要求模型先提交一次同义 plan-status-only 更新。若模型先
  单独提交 all-completed plan，Runtime 进入只允许 `FinalMessage` 的受限 completion call；该调用不再暴露
  Tool、Agent 或 Plan，不计入开放 Interaction turn，但仍计入 aggregate model usage 和 total-token cap；
- working plan 不创建 Project、Repository、表、Planner Interface 或 durable dispatch，也不替代原有
  Verification / Completion contract。

跨用户轮次恢复时，Runtime 还会从同一 Interaction journal **确定性派生当前清单可继续消费的成功执行事实**：
只选择同一 `conversation + principal + plan_id`、且绑定当前 step 的成功 `ActionObservation`，再交给已有的有界
上下文物化；失败动作、DecisionFeedback、无计划 Observation 和其他权限范围的事实不会恢复。Journal 只筛选已经
发生的事实，不决定下一步或语义完成。该实现没有新增 Plan/Todo、持久字段、表、Prompt 或配置。

`HARNESS-003` 给出了这条消费链的同输入因果证据。无该消费点的 baseline 在首轮真实非零预算边界后，第二轮
看不到已经提交的随机口令和本地副本，最终返回了三个错误口令；恢复该消费点后，第二轮只读取本地副本中尚未展开的
内容，ALPHA、BETA、GAMMA 原始档案各执行一次，最终交付三个随机口令和用户 steering 后的新阈值。配对中还包含简单问答反事实，正式
响应和 trace 均没有工作清单。checksum 封存与 identity 配对校验通过：

- baseline：`data/e2e_traces/product_baselines/harness-003/baseline/20260814T091431.462087Z-3328-bd35a339`；
- target：`data/e2e_traces/product_baselines/harness-003/target/20260814T091531.397728Z-17136-7b8c3257`。

外部实现只用于约束机制边界：Gemini CLI commit `c0d192452b4e2df7efb6d62a60385f475bfd6779` 的
[`plan-mode.md`](https://github.com/google-gemini/gemini-cli/blob/c0d192452b4e2df7efb6d62a60385f475bfd6779/docs/cli/plan-mode.md)
和 [`tools.md`](https://github.com/google-gemini/gemini-cli/blob/c0d192452b4e2df7efb6d62a60385f475bfd6779/docs/reference/tools.md)
区分执行前审阅与轻量 Todo；Hermes Agent commit `3c5fd918e3e2537cd74f4f88c990c5de5cbd9f63` 的
[`todo_tool.py`](https://github.com/NousResearch/hermes-agent/blob/3c5fd918e3e2537cd74f4f88c990c5de5cbd9f63/tools/todo_tool.py)
只在上下文压缩后重新注入 active items，避免完成项诱发重做；OpenAI 官方的
[`Follow a goal`](https://learn.chatgpt.com/use-cases/follow-goals) 把持久目标限定为跨轮、具有可验证停止条件的工作。
本工程采纳“按需、跨边界继续消费、结果验证”，不复制 Plan 文件、第二套 Todo、Task Tracker 或通用 Planner。

默认审阅边界由两条正式入口证据共同约束。CONV-001 锁定用户明确要求计划时先返回 `plan_ready`，HARNESS-001
使用没有“计划、步骤、确认、auto”等指令的自然研究请求，锁定两种合法结果：不创建正式计划并直接完成，或创建计划
后在执行任何动作前停下。变更前同一 HARNESS-001 输入创建计划后先执行了 3 个网页动作；变更后返回完整答案且没有
创建形式计划。baseline/target archive 分别为
`data/e2e_traces/product_baselines/harness-001/baseline/20260813T155736.029773Z-2924-b3c89423` 和
`data/e2e_traces/product_baselines/harness-001/target/20260813T162211.319231Z-25124-d865fd5b`，checksum 与配对校验均通过。

CONV-002 已关闭 `HARNESS-002`。失败 baseline 证明旧协议会在 Observation 已齐后重复相同计划直到预算耗尽；
落地时删除了模型可写的 revision/evidence 字段、`working_plan_progress_required` 和 FinalMessage 前的重复完成写入，
保留一个 canonical Working Plan。最新正式 target 在进程重启后恢复 revision 1，以 3 个 ToolCall 取得 OpenAI、Gemini、
Hermes 官方来源，在 4 个 continuation model-turn 内返回 answer；Runtime 生成 revision 3，三项来源步骤绑定各自
action ID，最终交付步骤由 FinalMessage 明确完成。归档为
`data/e2e_traces/product_baselines/conv-002/target/20260814T045035.499203Z-31672-582c9346`。
这证明当前同一用例已交付，不代表任意模型调用都无方差；HARNESS-001 曾出现一次模型错误声称没有可用搜索能力，
同输入复跑通过，尚不足以准入新的字符串门禁或 Prompt 规则。

CONV-003 锁定计划项本身的质量。同一正式 Conversation HTTP 输入仍限制为一次模型决策和零次工具调用；
变更前虽能创建计划，但各项只是“检索、比较、给建议”等活动，独立结构化语义评估将全部工作项判为不可验收。
最小修复没有增加字段、表或第二套计划对象，只要求现有描述用用户语言写明“结果”和“完成条件”。目标路径中每项都
说明要形成的资料提取或建议，以及何时可以接受为完成；执行成功仍只作为证据，不会由运行系统自动把工作项标成完成。
用例为 `evals/product_baselines/test_conv_003_work_item_quality.py`；同输入失败基线与目标报告分别为
`data/e2e_traces/conv-003-baseline.json` 和 `data/e2e_traces/conv-003-work-item-quality.json`。

### 3.2.1 Interaction Prompt 的工程边界

**Prompt materialization 已从 `ConversationService` 抽到纯函数模块 `interaction_prompt.py`；Service 只传入
canonical projection、预算与当前 Working Plan，不再拥有 159 行 prompt literal。** 这是用户行为不变的内部
重构：工程基线为 `service.py=3209` 行、内嵌 system prompt 159 行/10240 literal chars；重构后
`service.py=3028` 行、prompt 模块 183 行。抽取前后代表性输入的 materialized prompt 均为 9940 chars 且
byte-for-byte 相同；重构后的 targeted suite 为 65 passed，正式入口 CONV-001 为 1 passed（40.36s），
CONV-002 为 1 passed（53.33s）。这些数字记录的是抽取阶段的行为保持基线；之后 CONV-003 依据失败的产品基线
调整了计划项表述，因此不再声称当前提示词与抽取前逐字相同。该模块没有 Interface、Factory、Repository、状态或第二写入口。

CONV-001 当前只能作为目标行为回归证据：旧测试把每次通过结果写回
`data/e2e_traces/conv-001-baseline.json`，原失败 baseline 已被覆盖，不能继续声称存在可复核的 paired
baseline。当前用例 `evals/product_baselines/test_conv_001_working_plan.py` 仍经过真实模型、PostgreSQL、
Web 进程重启和运行时随机知识事实，并验证用户审阅、修订、恢复和最终结果；新执行写入
`data/e2e_traces/product_baselines/conv-001/<baseline|target>/<run-id>/`，记录输入/初始事实/身份/入口/
配置与 grader digest，并由 checksum 封印。只有在旧实现与目标实现使用相同 evidence seed 且机械配对
校验通过后，才能重新建立“该产品变更有失败 baseline”的结论。机制参考为 A 级 OpenAI 官方文档（复核日期
2026-08-13）：`https://developers.openai.com/api/docs/guides/function-calling` 的 five-step tool-calling
conversation 与 strict schema，以及 `https://developers.openai.com/tracks/building-agents` 的 structured
outputs / orchestration 边界。采纳 typed proposal、应用侧执行和 observation 回注；没有引入多 Agent、
通用 Planner、Workflow、Aggregate、Repository 或新表。

### 3.3 预算、并发与恢复

`LoopBudgetPolicy` 限制 model turns、Tool calls、Agent calls、token 和并发数。预算耗尽返回
明确 limitation/failure，不拼接替代业务答案。组建同一批 action 时按 proposal 顺序逐项预占剩余
Tool/Agent call slot；因此并发批次也不能基于同一个旧 usage 快照越过 cap。

同一 turn 只有全部 action 都可机械证明为安全并发时才使用 bounded thread pool；具有共享
写状态、审批或结果依赖的动作保持串行，并把 Observation 返回下一模型轮。

`InteractionTrace` 由 `ConversationService` 写入，直接保存 owner `AuthenticatedPrincipal`、输入消息、
已提交 Observation/Feedback、usage、真实执行顺序、并发批次、逐轮上下文构成
（`context_composition`）、当前 `ConversationWorkingPlan` 和最终消息。被 Admission 拒绝的 proposal
只形成 typed Feedback，不进入 execution order。读取或用同一 `interaction_run_ref` 恢复前必须匹配已提交
principal；不匹配时返回资源不存在，并以同一 run ref 记录 `conversation_run_scope_mismatch`。
无法可信推导 owner 的旧 snapshot 被隔离，不能默认归给当前用户。恢复后模型直接读取 committed
typed inputs；恢复不会重复已提交 action，也不把前台工作清单升级为生产调度源。

`context_composition` 属于 Observability：记录发生在模型调用之后，不参与可见输入组装，不进入任何
终止判据或预算判定，可由 committed inputs 确定性重算。语义见
[Context 工程](../topics/context-engineering.md#上下文构成度量)。

Conversation 当前按运行上下文暴露粗粒度 Application-owned action，而不是领域内部步骤：

- `list_personal_knowledge`：只读当前 authenticated principal 拥有的 active/conflicted canonical
  KnowledgeItem 引用；Conversation 和 execution 只关联本次运行，不改变 owner；
- `prepare_conversation_knowledge_save`：冻结 user-authored exact span，等待确认；
- `prepare_knowledge_delete`：只能引用上一 Observation 中同 scope 的 KnowledgeItem，调用
  `KnowledgeLifecycleService.prepare_delete`，确认前不删除；
- `start_durable_investigation`：仅用于用户明确要求跨交互持续、查询进度、暂停或 steering 的目标，
  调用 `InvestigationProjectService.create` 并返回 `ProjectReference`。
- 已关联 Project 时不再暴露第二次 start；Application 从 Project owner 预取有界
  `investigation_project_context`，并只暴露 `steer_investigation_project` 写动作。模型不提供 project id、owner 或
  plan version。
- 当前问题有个人证据时，Application 先按 scope 调用 `select_evidence()`，物化
  `personal_knowledge_context`；模型仍决定是否回答或调用其他只读 Tool。

显式保存时，参数只能引用现有 user
message 索引并逐字复制其中的知识 `text_span`；Admission 机械证明 span 确实存在且来源角色为
user。Runtime 只冻结 exact span 与 source index 并产生一个服务端 `command_digest`，Interaction journal 保存
`awaiting_confirmation/rejected/executed` 和 Receipt。确认入口重新校验 principal、
digest，执行时仍复用 `KnowledgeService.solidify_conversation`，不开放 `capture_text`。客户端通过
`interaction_run_ref` 与 authenticated principal 定位 operation，不能回传或覆盖 digest；确认后
模型可以补充 Claim 的语义结构，但 atomic one-span/one-claim 的 `statement` 与 canonical key 只能来自
已冻结 EvidenceSpan，不能被语义抽取改写。E14 已覆盖 exact span、确认前零写入、prepare 后重启、跨 principal
拒绝、精确结论 Claim、控制语义零写入、Receipt 和成功 replay。提交知识与 journal Receipt
之间的进程终止故障注入仍未覆盖。删除 operation 和 Project 的 canonical 状态不复制到
Interaction journal；journal 分别只保存 delete command ref 和 `ProjectReference`，恢复时回查
原 Application owner。E22 覆盖确认前零删除、scope 隔离、确认与 replay；E23 覆盖从自然目标
创建一个可查询 Project、trace 引用一致且不把创建冒充 Completion。

### 3.3 单次 Observation 的体积边界

回合 token 上限按回合起点判定，**不约束单次工具返回**，因此单次体积由独立生产机制执行
（[ADR 0013](../adr/0013-bounded-observation-and-offloaded-read.md)）：一次 Observation 进入
Context 的上限是 20,000 字符，超限部分卸载为 `ResourceRef` 并回带 `retrieval.omitted_chars`；
模型用 `read_action_output` 按关键词或行号取窗口；存在未读完的卸载物时，`clarification_required`
/ `limitation` / `failed` 被拒绝，防止模型在自己的 Observation 里已有答案时反问用户。

被卸载的正文以 Artifact 持久化，身份是 `ResourceRef`，`producer_key` 保证幂等；「这个远端输出读过
没有」是对 committed inputs 的纯函数判定，不另存已读集合。

## 4. Application Capability、执行资源、MCP 与 A2A

### 4.1 Application owner 与 EffectiveCapabilities

Application Capability 由对应 Use Case 拥有语义、准入、写入口和结果契约，不存在全局可写的
Application Capability Registry。Conversation 每次运行从 Application-owned action contract、实际 Tool
registry 和 Agent profiles 构造临时 `EffectiveCapabilities`；该对象只说明模型当前可以提出什么，不拥有
capability definition，不证明远端健康，也不产生发布可信度。

当前模型 wire format 把 Application-owned action 与 registered Tool 都投影为
`EffectiveToolCapability -> ToolCallProposal`。这是模型可见形状的复用，不改变事实 owner：保存、删除和
Project 创建仍进入各自 Application，registered Tool 才进入 ToolExecutor/ToolGateway。

管理/API 使用的 `RuntimeCapabilityInventory` 从本地 registry、accepted MCP config 和 A2A
assembly 投影。它明确区分 configuration、discovery 和 availability observation，不把
“配置存在”推断为“Provider 当前健康”。

### 4.2 Application action 与 Tool 执行

```text
ToolCallProposal
  ├─ Application-owned action
  │    -> action-specific typed Admission
  │    -> canonical Application Use Case
  │    -> pending operation / Command ref / ProjectReference / Observation
  └─ registered Tool
       -> ToolExecutor registry/schema validation
       -> deterministic admission
       -> ToolExecutor.invoke_interaction
       -> ToolGateway policy / idempotency / audit
       -> typed Tool result
       -> ActionObservation
```

普通低风险、只读、可安全重试的 ToolCall 不为形式统一持久化 Command。需要审批、外部副
作用、不可安全重试或跨恢复边界的调用，必须使用领域 Command、digest、Journal 和 Receipt。

`ToolExecutor` 拥有本地 Tool registry；`ToolGateway` 拥有 registered Tool 的最终 policy enforcement、
调用和审计事实。Application 只依赖 `InteractionToolPort`，不直接依赖具体 Tool 或 MCP SDK；Gateway
不改写 Application Command、Aggregate 或完成状态。

### 4.3 MCP

MCP Server 拥有远端 tool name/schema 和协议响应；Host config 拥有本地映射、风险、权限、
data egress、timeout 和 exposure。只有实际 discovery 与 Host mapping 都满足时，MCP Tool 才
进入 registry。

GitHub/Notion MCP 是当前真实 Connector profile。capability missing 时系统返回 typed
unavailable/feedback，不选择“最像”的 Tool，也不生成替代业务结果。

### 4.4 A2A

```text
AgentDelegationProposal
  -> local profile and scope admission
  -> DelegationGrant
  -> AgentGateway submit / poll / cancel / stream
  -> ChildAgentRunRecord + AgentArtifact
  -> ActionObservation
  -> parent model synthesis
```

`AgentGateway` 拥有 child lifecycle 和 Artifact index；Adapter 只转换远端协议。远端
`completed` 不能自动完成父 Interaction，Artifact 也不能直接冒充父级 FinalMessage。当前
GPT Researcher A2A profile 与主工程使用相同 tokeness Provider 配置。

## 5. 原生产品领域与事实 owner

| 产品能力 | Application owner | Canonical fact / 唯一写入口 |
| --- | --- | --- |
| Conversation | `ConversationService` | `InteractionTrace` / Interaction journal；按需 `ConversationWorkingPlan` 与 final message 共用此唯一写入口 |
| Conversation governed save | `ConversationService` + `KnowledgeService` | journal 拥有 save Command/operation/Receipt；Personal Knowledge 固化方法仍是唯一知识写入口 |
| Goal-entry knowledge delete | `ConversationService` 调用 `KnowledgeLifecycleService` | lifecycle service/store 拥有 delete Command/status/Receipt；Interaction 只存 command ref |
| Goal-entry durable investigation | `ConversationService` 调用 `InvestigationProjectService` | `InvestigationProject` aggregate 拥有 definition/accepted Plan/state/Completion，Service 是唯一 Application 写入口，store 持久化 definition/event；Interaction 只存 ProjectReference |
| Artifact | `ArtifactService` | application-owned ArtifactRef 和 Artifact Store |
| Capture | `CaptureService` + Personal Knowledge ingestion | 原始资源、Artifact、Evidence、Claim ingestion transaction |
| Grounded answer | `ConversationService` + `KnowledgeService.select_evidence` | Conversation 拥有唯一 FinalMessage；Knowledge 拥有 Personal Evidence/Claim/conflict；回答不隐式写 Claim |
| Knowledge Lifecycle | `KnowledgeLifecycleService` | immutable delete/restore Command、operation status、Receipt |
| Personal Knowledge Knowledge | `KnowledgeService` | Artifact、EvidenceBlock/Span、Claim、Relation、KnowledgeItem |
| Review | `ReviewDigestUseCase` / feedback use case | review content、feedback fact、schedule projection 分离 |
| Knowledge Gap | `KnowledgeGapUseCase` | gap analysis result；不成为知识事实写入口 |
| Research | `ResearchService` | ResearchRun、Event、Digest、Delivery/limitation |
| Scheduled Intelligence | Research/Review scheduler | Subscription definition、Run、Delivery、feedback 分离 |

Personal Knowledge 的 PostgreSQL Store 是结构化知识事实 owner。Graphiti 和 embedding index 是检索/图
投影，不是事实权威源；投影失败不能覆盖或删除 Personal Knowledge canonical facts。生产 Graph Provider
只接受 `graphiti`、`structural` 和 `hybrid`；缺少 source/citation binding 的 Provider 不在生产
allowlist，CLI synthesized answer 不能作为检索事实。
大型正文和上传文件由 Artifact Store 持有，运行状态优先保存 ref 而不是复制内容。

Knowledge delete/restore 不使用通用 Planner 猜测目标。Application 根据明确的
user/scope/note identity 创建 immutable Command；客户端通过 path command id 与 authenticated principal
选择 operation，一个服务端 `command_digest` 绑定 Command、Operation 和 Receipt。错误 command id、
跨 scope 或 replay 不产生重复副作用。只有 Personal Knowledge
Item/Claim 的真实迁移产生状态事件，生命周期本身不复制 Event。

## 6. Model Port 与 Provider 边界

Application 只依赖 `StructuredModelClient` / `StreamingModelClient`，不直接依赖 OpenAI SDK。
`infra/structured_model.py` 是唯一 OpenAI-compatible 生成式边界，共享 SDK 调用与响应归一化，
并按 Provider/model capability profile 在 Composition Root 确定性选择：

- `StrictJsonSchemaAdapter`：Provider 原生 strict `json_schema`；
- `JsonObjectStructuredAdapter`：`json_object` + canonical Pydantic schema instruction；
- tool calling/text：Chat Completions 的统一请求和响应提取；
- streaming：typed `StreamChunk`；
- observation：usage、latency、trace 由 decorator 记录；
- retry：SDK 隐式 retry 关闭，`RetryingStructuredModelClient` 是唯一 retry owner；
- repair：typed validation 失败最多请求同一模型完整重写一次，累计全部调用的 latency/token，
  第二次仍无效则 fail closed；
- timeout：connect/read/write/pool timeout 外，再执行完整 Provider 调用的 wall-clock
  deadline；structured SSE 消费也受该 deadline 约束。

所有生成式 Adapter 从 canonical `STRUCTURED_*` 配置解析；`STRUCTURED_OUTPUT_TRANSPORT`
声明 deployment 的结构化输出能力，禁止根据一次异常在运行中切换协议。当前配置为
`deepseek-v4-flash` + `json_object`；embedding 和 transcription 保持独立契约。Provider
transport compatibility 可以改变传输格式，但不得修改 Prompt 语义、Proposal payload 或
typed output contract。

`StructuredModelRequest.context_projection_ref` 必填。边界明确、完整输入即 messages 的调用
使用 content-addressed `sealed-context`；上下文内容变化会改变 digest。模型调用仍经过
governed model client，配置或凭据本身不构成调用授权与成功事实。

## 7. Execution、Verification 与 Completion

系统明确分离：

```text
Execution Fact
  = Tool、Command 或 Agent 实际执行了什么

Semantic Verification
  = Answer/Artifact 是否被可见证据支持

Domain Completion
  = 对应领域 Aggregate 是否满足其 definition 并进入合法终态
```

审查类 Interaction 的语义验证由 `ConversationService` 拥有，模型只保留「这是不是一次审查请求」
的路由判断。判据由 Runtime 经一次独立结构化调用派生，每条 `criterion` 必须携带逐字出现在用户
消息里的 `source_span`（否则丢弃，并留下 `review_criteria_not_grounded`），派生结果冻结进
`InteractionTrace.review_criteria`。`verify_interaction_draft` 的 `exposure` 是
`workflow_activity`，不出现在模型能力清单里；`ToolExecutor.list_interaction_tools()` 按 exposure
过滤而 `invoke_interaction()` 不过滤，所以 Runtime 仍经同一 ToolGateway 调用，`permission_scope`、
超时、限流、审计与预算记账全部保留。Runtime 在终止前无条件验证，并拒绝审查请求上任何非
`answer` 的 disposition；通过后发出的文本直接取自凭据的 `verified_draft`，模型不参与产物传输
（[ADR 0010](../adr/0010-runtime-owned-interaction-verification.md)）。非审查请求完全跳过验证，
普通问答路径不变，也不为形式统一伪造 VerificationReport 或 CompletionReport。

Research、Knowledge Lifecycle、Review 和 Delivery 使用各自的 typed result/receipt/terminal
state。Tool success、Agent completed、数据库新增记录或模型自述均不能单独证明用户目标完成。

## 8. 持久化、恢复与后台执行

当前不存在覆盖所有请求的通用 Task/GoalGraph/RunCheckpoint 主链。持久化边界按事实类型分开：

| 边界 | 当前实现 | 恢复语义 |
| --- | --- | --- |
| 普通 Interaction | `FileInteractionJournal` | 从 committed inputs/usage 重建 transient context |
| Personal Knowledge/Knowledge | `PostgresKnowledgeStore` | 从 canonical Artifact/Evidence/Claim/Event 恢复 |
| Delete/Restore | `PostgresKnowledgeLifecycleStore` | immutable Command/Event/Receipt，digest replay |
| Research | `PostgresResearchStore` + worker queue | ResearchRun/Subscription/Delivery 生命周期 |
| Tool governance | `PostgresToolGovernanceStore` | policy decision、idempotency 和 audit |
| Child Agent | `AgentGateway` run store + trace | child status/event/Artifact 与父结果分离 |
| Background work | `PostgresWorkerQueueStore` | retry/dead/reconcile，不重新创造业务参数 |

`ProcedureRuntime` 只服务具有稳定事务不变量的流程；它不是普通 Interaction 的 Planner，也不
是所有业务 lifecycle 的父 Aggregate。仓库中的部分 Task/Control contract 仅供明确的 Procedure
消费者使用；它们不是正式 Conversation 入口，也不能成为通用任务主链。

## 9. Observability 与发布证据

观测层记录 trace、usage、latency、provider、action order、receipt、verification 和错误分类，
不改变业务行为。凭据和不必要的完整敏感内容不得进入 trace。

E2E 分类的唯一 owner 是 `evals/e2e_quality/evidence_catalog.py`：

- E01–E05、E08–E14、E20、IP01：应用能力；
- L01–L06：自然复杂主循环、恢复、fail-closed 和 receipt-reference semantic revision；
- E16–E19、E21：真实外部 Provider/runtime profile，属于 diagnostic。

E06/E07 重复 profile、C01–C04 拼接独立 Use Case、LT09 使用常量代替 paired baseline，均已退出
当前 catalog；B03 保留为历史 archive，不再与 IP01 一起对当前实现断言相反结果。

完整矩阵必须从真实 HTTP 入口进入独立 Web 进程，使用真实模型、PostgreSQL 和场景需要的
真实 Provider，并同时断言用户结果和关键反事实。`release_gate.py` 只接受 catalog、clean
matching revision、passed summary、trace envelope 和 checksum 的交集。

上一完整矩阵与当前定向证据：

```text
previous full matrix = 23 passed, 0 failed, 0 skipped
previous archive = 20260726T011631.187395Z-20684-4a62da6a
natural L01-L05 batch = passed
corrected natural L06 = passed
natural E17/E19 plus L04 = passed
answer-free-prompt E16/E18 = passed
targeted archives = 20260727T163802.147366Z-12512-71873e6b,
                    20260727T164815.081968Z-14456-e1196ad4,
                    20260727T162913.553817Z-9428-c723ad92,
                    20260727T165211.554901Z-17344-3e4bc060
current complete matrix = not rerun
release eligibility = not established (dirty revision)
```

## 10. 当前入口与 owner 调用路径

### 10.1 普通对话

```text
Web / CLI / Feishu
  -> AgentService.converse
  -> AgentRuntime.converse
  -> ConversationService.respond
  -> AgentTurnDecision
  -> ToolExecutor or AgentGateway
  -> Observation / Feedback
  -> FinalMessage
```

### 10.2 固定产品流程

```text
Conversation Application-owned action / Product API / CLI
  -> capability-specific Admission（Conversation 入口适用）
  -> explicit Application use case
  -> Domain state transition / Port
  -> persistence adapter
  -> typed user result
```

固定 Capture、Knowledge Lifecycle、Review、Research 和 Scheduled Intelligence 不为
“更 Agentic”而强制进入 Planner。只有语义下一步无法预定义时才回到模型 Interaction loop。

Conversation 只是其中一个调用入口；保存、删除等业务状态继续由对应 Application/Domain 拥有。专用 UI/API
直接调用时也必须复用同一个 Use Case，不能形成第二写路径。

### 10.3 Conversation 内确认后保存

```text
POST /api/conversation/turn
  -> ToolCallProposal(prepare_conversation_knowledge_save)
  -> immutable Command + awaiting_confirmation
  -> Interaction journal
POST /api/conversation/runs/{run}/knowledge-save-decision
  -> principal/personal knowledge/digest validation
  -> KnowledgeService.solidify_conversation
     -> frozen atomic EvidenceSpan owns statement/canonical key
     -> semantic extraction only annotates claim structure
  -> Receipt / replay same Receipt
```

## 11. 当前架构不变量

- 普通请求不强制创建 Task、GoalGraph、Command、Receipt 或 CompletionReport；
- 模型拥有开放语义和下一步 Proposal，Runtime 不从字符串或相似度猜业务下一步；
- Proposal 不是权限、执行事实或完成证明；
- Admission 只接受/拒绝，不静默修复 Proposal；
- 普通 Conversation 不强制创建计划；用户明示是强触发条件，存在可证明协调收益时模型也可主动创建由当前对话拥有的可验收工作项清单；可持久恢复的调查规划只属于显式后台项目；
- 普通只读 ToolCall 与 governed side effect 使用不同执行边界；
- Tool 和 Agent 必须经过对应 Gateway，Adapter 不决定授权；
- Agent Artifact、Tool Receipt、Semantic Verification 和 Domain Completion 互不冒充；
- Conversation grounded answer 不隐式保存模型回答，长期知识只有明确 ingestion/write path；
- Conversation 保存只冻结已选 user message；确认前、reject 和 scope denied 均不写知识；确认后的语义
  抽取不得覆盖 atomic confirmed statement；
- 远程能力没有实际 discovery/availability 时 fail closed；
- replay 不重新生成或覆盖冻结 Command，不重复副作用；
- retrieval index 和 graph projection 不是知识事实 owner；
- Interface、Application、Domain 与 Adapter 的依赖不得反向或循环；
- release 可信度只能由 clean matching E2E archive 派生。

## 12. 主要代码入口

| 关注点 | 当前路径 |
| --- | --- |
| Composition Root | `orchestration/runtime.py`、`orchestration/service.py` |
| Conversation models / loop | `application/conversation/models.py`、`application/conversation/service.py` |
| Conversation execution facts / working-plan admission / explicit knowledge save | `application/conversation/journal.py`、`application/conversation/working_plan.py`、`application/conversation/knowledge_save.py` |
| Conversation Ports | `application/conversation/ports.py`、`capabilities/contracts/interaction.py` |
| Web conversation entry | `adapters/web/routes/conversation.py` |
| Personal Knowledge / grounded read | `application/knowledge/`；确定性文本与关系规则位于 `application/knowledge/text_rules.py` |
| Knowledge delete/restore | `application/knowledge_lifecycle/`、`adapters/web/routes/notes.py` |
| Research / Scheduled Intelligence | `application/research/`；请求理解与查询规划位于 `application/research/planning.py`；Web 入口位于 `adapters/web/routes/research.py` |
| Review / Knowledge Gap | `application/review/`、`application/insight/` |
| Tool registry / execution | `governance/registry.py`、`governance/gateway.py` |
| Agent lifecycle / A2A | `agents/gateway.py`、`agents/gpt_researcher_a2a.py` |
| Capability inventory / resolution | `orchestration/capability_inventory.py`、`capabilities/` |
| Model Port / Adapter | `capabilities/contracts/model.py`、`infra/structured_model.py` |
| Persistence adapters | `infra/storage/` |
| E2E catalog / gate | `evals/e2e_quality/evidence_catalog.py`、`evals/e2e_quality/release_gate.py` |
| Architecture DAG gate | `scripts/check_layers.py`、`.github/workflows/architecture.yml` |

## 13. 巨大生产文件审计与职责收敛

**结论：大文件是评审触发器，不是拆分目标。本轮只处理已测得职责混装的三个主文件；千行以上生产文件仍有 8 个，但其余文件没有足够证据支持机械拆分。**

这是**纯内部重构**，用户行为保持不变。重构前，Conversation、Research 与 Knowledge 的主服务分别为
3,028、2,589、1,981 行，并分别混入了可独立命名、可独立验证的职责。正式入口行为基线为：

- `uv run pytest -q tests/test_conversation_interaction.py tests/test_research.py tests/test_research_digest_verification.py tests/test_knowledge_p0.py`：112 passed；
- `uv run pytest -q tests/test_api.py`：29 passed。

| 文件 | 已证明的职责混装 | 本轮处理 | 处理后行数 |
| --- | --- | --- | ---: |
| `application/conversation/service.py` | 主循环同时拥有 journal 实现、working-plan 机械准入与显式知识保存的确认事务 | 把执行事实存取、计划机械准入、知识保存 prepare/confirm/commit 分别交给命名 owner；保留原公共入口 | 2,450 |
| `application/research/service.py` | 研究运行编排同时拥有请求理解、策略解析和查询规划 | 抽出无运行状态的 planning 规则，Research 主服务继续拥有研究生命周期 | 2,375 |
| `application/knowledge/service.py` | 知识用例同时实现文本切分、规范化、实体与关系判定 | 抽出确定性文本/关系规则，Knowledge 主服务继续拥有写入和生命周期 | 1,736 |

三个主文件共移出 **1,037 行**。新增模块不是新的架构层：没有新增 Interface、Factory、Registry、状态、表、写入口或兼容路径；生产主服务直接调用这些 owner，旧实现已删除。由于没有引入新的运行机制，本轮不以外部 Agent 框架作为需求或拓扑来源，继续复用本工程现有的 Application owner 与 Port 边界。

其余千行文件的本轮判断如下：

- `investigation_project/service.py` 仍围绕同一个 durable aggregate 的生命周期与恢复，不因 1,981 行直接拆分；
- `investigation_project/model_ports.py`、`infra/structured_model.py` 位于模型边界，尚无已执行的变更耦合基线证明需要再分层；
- `orchestration/runtime.py` 是 Composition Root，体积来自显式装配；只有装配职责发生混装或变更耦合可复现时才拆；
- `kernel/evidence.py` 仍拥有同一 evidence contract，没有第二个事实 owner。

重构后的同输入回归为 141 passed；`uv run ruff check .` 与 `uv run python scripts/check_layers.py` 均通过。当前最大剩余热点是 Conversation 的 `respond()`（748 行）和 `_admit()`（256 行）。它们不能只被搬进通用 Helper；后续只有在某个独立 Application Capability 的 owner 与失败工程基线成立时，才继续从主循环删除对应分支。

## 14. 工作清单版本协议收缩

**结论：模型只负责工作清单语义，服务端只负责计划身份、排序和恢复；当前实现不再让模型参与版本控制，也不声称具备并发 CAS。**

这是**纯内部重构**，用户行为保持不变。工程基线显示，原 `WorkingPlanProposal.base_revision` 同时进入结构化输出 schema、Prompt 和 Admission；但 Journal 的“读取当前计划、接纳、写入”不是原子条件写，因此 `working_plan_revision_conflict` 只能拒绝顺序执行中的旧 Proposal，不能提供并发一致性。对应的正式入口行为基线仍使用 `POST /api/conversation/turn`，锁定计划展示、用户调整、Web 重启恢复和最终完成：

- 重构前行为 archive：`data/e2e_traces/product_baselines/conv-001/target/20260814T030814.909041Z-2708-3c4881f7`；
- 重构后行为 archive：`data/e2e_traces/product_baselines/conv-001/target/20260814T031938.266803Z-9344-31006f3d`。

本轮删除模型 Proposal 的 `base_revision`、版本冲突反馈和相关 Prompt 协议；主决策调用与受限 completion call 都只向模型提供 `goal + steps`。Runtime 继续从当前 canonical plan 机械保护 completed step，并为已接纳快照生成内部 `revision`。该序号仍由 journal 恢复和 HTTP 展示消费，因此本轮不删除字段；若未来确有同会话并发写入，必须先取得正式入口失败 baseline，再在 canonical Repository 实现原子 `expected_revision`，不能把版本重新交给模型。

复杂度变化为：模型字段 -1、Admission reason code -1、版本相关准入分支 -2；新增状态、表、Interface、Factory、Repository 和兼容路径均为 0。保留的内容比较由同一准入模块拥有，用于区分“已完成清单的重复提交”和“新目标的新清单”。验证结果：

- `python -m pytest -q tests/test_conversation_interaction.py tests/test_api.py tests/test_e2e_evidence_catalog.py tests/test_e2e_trace_archive.py`：117 passed；
- `ruff check .`：passed；
- `python scripts/check_layers.py`：passed，14 packages、48 edges、0 cycle、0 forbidden edge；
- `python -m pytest -q -s evals/product_baselines/test_conv_001_working_plan.py::test_conv_001_frontstage_working_plan_is_visible_and_revisable`：passed。

## 15. 未闭合风险

1. 旧 23/23 archive 不匹配新版自然 E2E；提交后必须在 clean revision 重跑当前完整矩阵，才能
   建立发布资格；
2. Supporting workflow/topic 与评测归档不拥有当前主链或发布状态；引用它们时必须回到 canonical
   current-state 与 catalog 复核；
3. `conversation_id`、`interaction_run_ref` 等部分 Interface/Application identity 仍以受格式
   约束的字符串传递，尚未全部收敛为 Value Object；
4. GPT Researcher PDF 中文字体视觉质量尚未形成自动化 E2E；
5. 部分 Task/Control contract 只服务受限 Procedure 消费者，需要持续按实际调用方收缩并标明边界，
   避免被误认为通用生产主链；
6. Conversation 的 Tool listing 按 exposure 过滤，但 registered-tool Admission 尚未机械绑定“proposal 必须
   来自本轮可见投影”；当前只有 conformance 诊断，没有正式入口失败 E2E，不能声称该边界已经产品化闭合。
