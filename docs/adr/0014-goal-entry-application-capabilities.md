# ADR 0014：单一目标入口复用领域 Application Owner

- 状态：Accepted
- 日期：2026-08-03
- 影响范围：Conversation、Knowledge Lifecycle、Investigation Project、SSE/前端、E2E catalog

> 2026-08-26：复用领域 Application Owner 的原则仍有效；`Investigation Project` 作为 Application Capability 的部分已撤回并删除。当前决策见 [ADR 0015](0015-withdraw-investigation-project.md)。

## Goal / Current Incorrect Behavior / Expected User-visible Result

普通用户只描述“读取我的知识”“删除这条错误知识并先确认”或“在后台持续调查并允许后续暂停、
调整”等结果，不应理解 Tool、Workflow、Project 或执行顺序。旧 Conversation 分别出现：未读取就
声称未找到、只能文字确认但无法准备 canonical delete command、幻觉不存在的 research agent。

目标结果是 Conversation 自主选择粗粒度业务能力，同时让 Personal Knowledge、Knowledge Lifecycle 和
Investigation Project 继续拥有各自事实、权限、状态与恢复语义。

Out of scope：通用 Router、Workflow Registry、UnifiedTask、第二 Project state、restore/订阅的
Conversation 入口、把 ResearchRun 扩为通用研究 Agent。

## Simplest Baseline E2E / Executed Result / Root Cause

| 用户目标 | baseline archive | 已执行结果与根因 |
| --- | --- | --- |
| 读取本用户随机知识并排除另一用户冲突事实 | `20260803T142413.474927Z-4864-39fedcf5` | clarification，无 Tool Observation；Semantic Decision 缺 canonical personal knowledge read capability |
| 自然语言定位错误知识并先确认删除 | `20260803T142932.564456Z-23720-19ba8517` | 文字确认、零 action；Capability 缺口，无法取得 canonical KnowledgeItem id 或调用 lifecycle owner |
| 后台持续调查、可查询/暂停/调整 | `20260803T143007.354551Z-26256-84d0bf1d` | 提议不存在的 `deep_research_agent`，Admission `capability_missing`；缺 Project handoff capability |
| 同目标研究边界对照 | `20260803T143230.864789Z-6460-dbd005fd` | ResearchRun 只得二手来源，Project 因官方规范证据缺失诚实暂停；未证明 ResearchRun 适合开放调查 |

前三项失败来自产品行为，准入最小改动；第四项只决定边界，不准入 ResearchRun 扩张。

## Decision Ownership / Fact Owner and Write Path

- 模型：判断是否读取个人知识、是否执行而非解释删除、是否确实需要 durable continuity，并提出
  现有 `ToolCallProposal`。
- Conversation Admission：校验 typed schema、单 action、scope 内已观察 target 和能力存在性；只
  接受或拒绝，不补 target、goal 或 requirement。
- Personal Knowledge：拥有 KnowledgeItem；`list_personal_knowledge` 只投影当前 principal 拥有的
  `owner_id` 分区的项。它不证明 Personal Knowledge membership；该产品边界仍需独立 baseline/E2E。
- Knowledge Lifecycle：`prepare_delete/decide_delete` 是 delete Command/status/Receipt 唯一写入口。
- Investigation Project：`InvestigationProjectService.create` 与 Project store 是 definition、Plan、
  state、journal 和 Completion 唯一写入口。
- Interaction journal：只增加 delete command ref 和 ProjectReference，不复制 operation、Plan 或状态。
- 前端：只读 Project projection，并调用原 pause/resume API；不运行 Planner 或推进 Project。

## Referenced Industry Mechanism

- A：[OpenAI Agents SDK `Agent orchestration`](https://openai.github.io/openai-agents-python/multi_agent/)，
  2026-08-03 复核 `Orchestrating via LLM` 与 `Orchestrating via code`：开放语义可由 LLM 决定，稳定
  编排可由代码约束，manager 可保持用户会话 owner。采纳混合所有权；不复制 triage Agent 数量、SDK
  对象或 handoff 拓扑。
- A：[ChatGPT Deep research](https://help.openai.com/en/articles/10500283-deep-research-in-chatgpt)，
  2026-07-31 更新版 `How deep research works`、`When to use deep research`、controls：耗时、多步、来源
  范围、进度和中断形成可见业务契约。采纳 durable 项目的可见引用与控制；不把快速查询升级为 Project。
- B：[Anthropic `Building effective agents`](https://www.anthropic.com/engineering/building-effective-agents)，
  2024-12-19：workflow 是预定义代码路径，agent 动态决定过程，并建议从最简单方案开始。仅与上述 A
  级机制交叉用于解释；不把 pattern 列表当作需求。

外部参考只回答机制如何实现；需求仍由本仓库已执行 baseline 产生。

## Decision

在现有 `ConversationService` 和 Proposal union 中增加三个最小能力切片：

1. `list_personal_knowledge`：安全只读 Observation；
2. `prepare_knowledge_delete`：独立 turn，引用已观察 canonical id，调用现有 lifecycle service；
3. `start_durable_investigation`：独立 turn，调用现有 Project service，返回 ProjectReference。

同时强化模型契约：没有 personal knowledge read Observation 时不得声称个人知识不存在。专用 API 保留给
UI/自动化，但与 Agent 入口复用同一 Application owner。ResearchRun 固定为 Scheduled Intelligence。

## Target E2E and Counterfactuals

- L01：`20260803T152242.957743Z-388-d0850c85`，读取本用户事实、排除跨 scope 冲突，并有已提交 Observation；
- E22：`20260803T152242.957743Z-388-d0850c85`，只选择当前 active/conflicted 目标，确认前零删除、跨 scope 不泄漏、确认后执行一次、replay 同 Receipt；
- E23：`20260803T151935.921382Z-27308-be5eadbf`，自然目标创建一个可查询 Project，trace 只持有同一引用，创建不冒充 Completion；
- Contract：解释删除不触发 delete/Project；Project replay 不重复 create；delete target 必须先在同 scope 被观察。

这些 archive 来自 dirty revision，只是定向 B 级工程证据，不建立 clean release 资格。

## Complexity Added, Removed and Rejected Alternatives

增加：三个 capability schema、三个 Application Port、两个 composition adapters、两个引用字段、
E22/E23 release E2E、E24 boundary diagnostic 和前端 Project progress card。

未增加：Router、Workflow definition/registry、通用 Outcome、统一 Task、第二 digest、第二 Project
journal。删除已迁移的 future 设计稿和“用户选择三条主链”的文档表述。新增对象各自有生产消费者，
并直接替代 baseline 中缺失的能力。

拒绝方案：关键词路由会误触发“只解释删除”；把 lifecycle/project 注册成大量低层 Tool 会让模型
重排事务；把状态复制进 Interaction 会形成第二 owner；扩张 ResearchRun 没有 paired 收益证据。

## Risks / Exit Conditions

- 语义误选仍由 Golden Set、Admission 与确认反事实控制；不得加入关键词 fallback。
- Project 创建使用当前默认预算；若真实成本策略要求显式确认，必须先新增同输入 baseline、ADR 和 E2E。
- UI 当前提供进度、暂停和恢复；steering/approval 继续使用 canonical Project API。
- 若重复运行表明 handoff 降低完成率或错误创建 Project，撤回该 capability，而不是保留双轨。
- clean matching revision 的 22 个 release E2E 未完整执行前，release gate 继续 fail closed。

## Executed Verification

- `uv run pytest tests -q`：760 passed，4 个既有 dependency deprecation warning；测试结束后的
  LangSmith 后台上传出现网络 SSL warning，不影响 pytest exit code；
- `uv run ruff check .`：passed；
- `uv run python scripts/check_layers.py`：14 packages、53 edges、0 cycle、0 forbidden edge；
- `npm run build`（`frontend/`）：TypeScript 与 Vite production build passed；仅有既有 bundle-size warning；
- E2E collect：40 total，22 release、18 diagnostic；catalog/gate contract 28 passed；
- live target：L01、E22、E23 passed；E24 paired boundary diagnostic passed as measurement。

没有执行当前 22 个 release 旅程的完整 clean-revision 矩阵，因此未声明 release ready。
