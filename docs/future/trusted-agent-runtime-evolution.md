# 可信 Agent Runtime 演进与收敛计划

- 状态：文档与工程门禁优化已由本次审计准入；产品能力扩展仍需各自 baseline
- 审计日期：2026-07-30
- 当前事实 owner：[当前核心架构](../summary/core-architecture-current-state.md)
- 产品/E2E owner：[Phase 0 能力与发布基线](../summary/phase0-capability-release-baseline.md)

本文不设计第二套 Agent 框架。它记录对当前仓库的架构、代码、文档和证据审计结果，并定义如何
让既有可信 Agent Runtime 的理念、生产实现和发布证据重新对齐。已经落地的产品能力不在本文
重复定义；尚未取得 baseline 失败证据的候选只登记进入条件，不得据此编码。

## 1. Goal / Current Incorrect Behavior / Expected Result

项目已经形成一套稳定框架：

```text
Semantic Proposal
  -> Admission / Policy
  -> Governed Execution
  -> Execution Fact
  -> Semantic Verification
  -> Completion Gate
```

但当前读者从 README、topics、workflow、summary 和 future 会得到互相冲突的系统：

- current-state 声明旧 `TaskAnalyzer -> GoalGraph -> Executive -> LangGraph` 总主链已删除；
- README、Workflow 索引、Task Analysis、Runtime、Context 和 Tools 文档仍把旧链描述为当前；
- current-state 和 Phase 0 曾声明 package DAG gate passed，但当前实际命令返回失败；
- Phase 0 同一文档同时声称当前 structured model 是 `deepseek-v4-flash` 和 `gpt-5.4-mini`；
- future 文档混装已交付能力、历史调试流水和尚未准入候选，违反自身退出规则；
- 面试材料容易把 object-root JSON 讲成顶层理念，掩盖真正稳定的决策与事实所有权。

期望结果是：

1. 任何入口先看到同一框架命题、目标责任链和 owner；
2. current、historical、future、diagnostic、release evidence 明确分开；
3. 文档不能声称当前 gate 通过，除非相同工作树实际命令为零退出；
4. 技术实现可以替换，但 Proposal、Authority、Execution Fact、Verification、Completion 的边界
   在所有文档中一致；
5. 新机制必须由正式入口 baseline 证明产品缺口，不能用“优秀 Agent 都这么做”准入。

## 2. Business Expansion or Proven Constraint / Out of Scope

本轮准入的是工程可信度约束，不是新产品能力。读者无法从文档判断真实生产主链、门禁状态与
证据边界，会直接导致错误开发、错误面试陈述和错误发布判断。

Out of Scope：

- 不重写 Conversation、Investigation、Workspace 或 Research 生产代码；
- 不创建新的通用 Agent、Planner、Task、Context Engine、Memory 层或 Registry；
- 不因为原生 Tool Calling 更流行就替换当前 `AgentTurnDecision`；
- 不因为 `FileInteractionJournal` 不是分布式存储就提前增加数据库 session 模型；
- 不把文档审计冒充用户产品 E2E。

## 3. Executed Baseline / Result / Root Cause

### 3.1 旧主链残留

执行：

```powershell
rg -n "TaskAnalyzer|GoalGraph|AdaptivePlanner|ExecutiveController|orchestration_graph|_react_parse_response" `
  docs README.md src/personal_agent.egg-info
```

结果：README、API、环境、Workflow、Topics、Mermaid 和生成的 package metadata 中仍有大量命中；
其中多个文件使用“当前”“唯一入口”“权威文档”等措辞。生产源目录已不存在
`orchestration_graph.py` 和旧 orchestration nodes，当前正式 Conversation 入口实际装配
`ConversationService`。

根因不是单个链接过期，而是 current-state 重构后没有关闭旧文档写入口，也没有文档术语门禁。

### 3.2 Package DAG gate 与文档声明冲突

执行：

```powershell
uv run python scripts/check_layers.py
```

结果：

曾得到：

```text
packages=17 edges=53
unknown_packages=['context', 'skills', 'verification']
missing_packages=none
cycles=none
forbidden_edges=0
FAIL: 3 architecture violation(s)
```

生产 Python 文件已在当前改动中删除，但目录仍被 `discover_packages()` 当成 package。根因是 gate
以“目录存在”定义 package，而当前迁移状态包含只剩缓存/残留内容的目录。

**已于 2026-07-30 关闭**：同时采用两种修法——删除三个只剩 `__pycache__` 的残骸目录，并让
`discover_packages()` 要求目录内至少有一个 `.py`，使未来的 stale pycache 不再制造幻影 FAIL。
当前结果 `packages=14 edges=53`、`unknown_packages=none`、`OK`。没有把未知目录加入
allow-list。

### 3.3 当前模型事实冲突

只读取非敏感配置：

```powershell
Get-Content .env |
  Where-Object { $_ -match '^(STRUCTURED_MODEL|STRUCTURED_OUTPUT_TRANSPORT)=' }
```

当前工作树配置为：

```text
STRUCTURED_MODEL='deepseek-v4-flash'
STRUCTURED_OUTPUT_TRANSPORT='json_object'
```

Phase 0 正文已经记录这一事实，但后续 owner 表仍写“当前为 gpt-5.4-mini”。根因是同一事实被
同一文档的历史验证段和当前状态段重复维护。

### 3.4 发布证据未闭合

现有 archive 证明过历史 23/23、自然 Conversation/MCP/A2A 定向场景、E14 exact-span 保存和
IP01 live Investigation target；但当前 catalog 已变化，工作树与 archive 不是 clean matching
revision。`release_gate.py` 按设计 fail closed。

这是已知交付门禁，不是框架设计失败。优化目标是建立同 revision 证据，不是降低 gate。

## 4. Decision Ownership / Fact Owner and Write Path

| 事实或决策 | Canonical owner | 合法写入口 |
| --- | --- | --- |
| 当前生产拓扑和框架不变量 | `summary/core-architecture-current-state.md` | 架构变更随代码、ADR 和证据整体更新 |
| 产品能力与发布资格 | `evidence_catalog.py` + `release_gate.py` + archive | 测试执行和 gate 派生，Markdown 不手写覆盖 |
| structured deployment 配置 | `Settings.structured` / `STRUCTURED_*` | 环境配置；文档只描述已观察 profile |
| package DAG | `scripts/check_layers.py` + 实际 Python package | gate 输出；文档不得复制过期 passed 状态 |
| 领域事实 | 对应 Application/Domain owner | 现有 canonical Use Case/Store |
| 面试表达 | `docs/interview` | 只引用 current-state 和证据 owner，不创造架构事实 |
| 未来候选 | `docs/future` | baseline 失败后进入；落地后迁出或删除 |

## 5. Target Checks and Counterfactuals

### 文档目标

- README、docs 索引和 interview 开头都先表达可信 Agent Runtime，而不是 JSON/框架名；
- current-state 只记录当前实现和同日期执行状态；
- 历史旧主链文档有醒目标记，且不再被索引为当前权威；
- future 索引只列未闭合目标，已交付 stage 不继续冒充 future；
- `rg` 搜到旧术语时，每处必须属于明确的“历史/已删除/禁止恢复”语境；
- 本地 Markdown 链接不存在指向已删除源文件的当前架构声明。

### 工程目标

- `scripts/check_layers.py` 零退出，并且不是通过忽略所有未知 package 实现；
- clean revision 上执行当前完整 release matrix；
- release gate 只在 catalog、revision、clean、summary、trace envelope 和 checksum 全部匹配时通过。

### 反事实

- 不删除 fail-closed release 条件；
- 不把 historical archive 改写成 current release；
- 不为消除旧术语而恢复旧 Task/GoalGraph 代码；
- 不把 `AgentTurnDecision` wire format 提升为不可替换的领域事实；
- 不为“文档统一”复制 owner 表、状态表和 archive 清单到更多文件。

## 6. Delivery Plan

### Stage D0：文档事实源重置（本次文档变更）

1. 在 current-state 增加框架命题、不变量、三条运行形态、实现/理念边界和现实证据；
2. README、docs/README、workflow 索引和 interview 使用同一入口叙事；
3. 修正 Phase 0 当前模型与 IP01 状态矛盾；
4. 给旧 Task/GoalGraph/LangGraph 总主链文档增加历史状态标记；
5. 将本文加入 future 索引，作为剩余收敛项的唯一计划 owner。

删除或降级：

- “对齐优秀 Agent”作为需求来源；
- object-root JSON 作为顶层架构卖点；
- 已删除源路径对应的“当前”流程；
- 同一配置和发布状态的重复手写 owner。

### Stage G0：恢复架构门禁（已完成，2026-07-30）

已执行 baseline：gate 曾因三个 unknown package 失败。

最小实现候选只能二选一：

1. 若目录没有生产 Python/资源消费者，删除残留目录；
2. 若目录是合法 package，补回明确 owner、依赖边和生产消费者，再更新 DAG。

三个目录都属于第 1 类（只剩 `__pycache__/*.pyc`，`git ls-files` 为空）。除删除外还收窄了
discovery：`discover_packages()` 现在要求目录内至少有一个 `.py`，否则同类残骸会再次制造
幻影 FAIL。没有把未知目录加入 allow-list。当前结果 `unknown_packages=none`、`OK`。

不得简单把未知目录加入 allow-list 来让测试变绿。完成命令：

```powershell
uv run python scripts/check_layers.py
```

目标结果必须为 `unknown_packages=none`、`missing_packages=none`、`cycles=none`、
`forbidden_edges=0` 和零退出。

### Stage R0：建立 clean matching release evidence

前提：目标代码和文档提交到 clean revision，Provider 环境可用。

```powershell
$env:PERSONAL_AGENT_REQUIRE_LIVE_E2E = "true"
$env:PERSONAL_AGENT_E2E_TRACE_DIR = "data/e2e_traces"
uv run pytest evals/e2e_quality --e2e-scope=release `
  --e2e-require-complete-matrix -q -s
uv run python -m evals.e2e_quality.release_gate --trace-root data/e2e_traces
```

失败时按 semantic decision、Admission、Execution、Verification、Completion、Evidence Gate
分层定位；禁止先改 Prompt 或降低断言。

### Stage M0：清理生成 metadata 与旧文档（部分完成）

- 已重新生成源码树中的 `personal_agent.egg-info`，不再宣称旧总主链；
- 已按当前消费者重写 `topics/memory.md`、`topics/context-engineering.md` 和
  `topics/retrieval-reasoning.md`；
- 已删除无 source binding 的 Microsoft GraphRAG 生产 Adapter/配置及失效 Provider 文档；
- 已重写 Memory 与 Ask Mermaid，只保留当前 owner 和生产数据流；
- 已核对 API/env/deploy 的 Conversation、Provider 和历史 checkpoint 表述；
- 添加只检查 current 文档的旧术语和本地链接 CI 门禁。

该 Stage 只收敛文档与生成物，不改变产品语义，不需要创建新的架构层。

## 7. Conditional Candidates Not Yet Admitted

以下都是合理研究方向，但当前没有同一用户目标的 baseline 失败证据，因此不是实施计划：

| 候选 | 必须先执行的 baseline | 准入条件 |
| --- | --- | --- |
| Provider 原生 Tool Calling 替换 Interaction envelope | 相同自然 Conversation 场景记录完成率、错误副作用、parse failure、token、延迟 | 当前 envelope 导致可重复用户失败，且替换不破坏 Admission/Observation contract |
| Conversation distributed journal | 多实例切换或 commit/Receipt crash injection | File journal 导致丢失恢复事实或重复副作用 |
| 两阶段 capability discovery | Tool 数量扩大的自然选择场景 | 全量 schema 注入造成可量化误选、延迟或 context budget failure |
| Context compaction | 长对话/长 Project 同输入对照 | 当前 materialization 因 context overflow 丢失 required result |
| Identity Value Object 全面迁移 | scope/identity 混淆的正式入口失败 | 字符串 identity 导致越权、错误恢复或不可定位错误 |
| Online Eval 控制面 | 真实线上质量运营目标 | 离线 E2E 无法回答已定义的线上成功率、成本或失败分布问题 |

这些候选共享同一退出规则：baseline 未失败、失败来自环境/测试、或当前路径已满足用户目标时，
停止优化。不得先创建 Interface、Registry、Projection、Fake 或第二状态模型。

「两阶段 capability discovery」与「Context compaction」两行的机制细节、业界坐标和缺失的
baseline 测量能力见 [Context 物化度量与逐出](context-materialization-measurement-and-eviction.md)；
准入判定仍由本节所有，那份文档不构成第二个 owner。

## 8. Complexity Budget and Rejected Alternatives

本计划允许的无条件新增仅是一份 future owner 和文档状态标记；同步删除重复叙事和失效权威
引用。Stage G0/R0/M0 优先删除残留与恢复现有门禁，不新增产品状态。

拒绝：

- 创建“统一 Agent Kernel”复制 Conversation、Workflow、Project 三套生命周期；
- 用一个通用 `Decision`/`Receipt` 表镜像所有领域事实；
- 为框架显得先进而恢复 TaskAnalyzer、GoalGraph 或全局 Planner；
- 把所有 Provider 差异塞进 Prompt；
- 用更多免责声明替代明确 owner、状态和验证命令。

## 9. Exit Conditions

本文可以删除或缩减为 ADR 索引，当且仅当：

1. current 文档中旧主链只出现在历史/禁止恢复语境；
2. ~~package DAG gate 在目标 revision 通过~~ 已满足（2026-07-30，Stage G0）；
3. current catalog 的 complete matrix 与 release gate 在 clean matching revision 上执行；
4. landed future stages 已迁出，future 只保留真正未落地候选；
5. 文档链接和术语门禁进入 CI，后续重构不能再次产生同类漂移。
