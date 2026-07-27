# E2E 与工程可信度

## 1. 为什么 Agent 项目必须从 E2E 讲可信度

Agent 系统最常见的误判是：

- 模型返回了 JSON，所以认为规划成功；
- Tool 返回 `ok=true`，所以认为用户目标完成；
- 数据库新增记录，所以认为保存正确；
- 子 Agent `completed`，所以认为父任务完成；
- 单元测试 mock 通过，所以认为真实 Provider 可用。

这些只证明局部事实。合格 E2E 必须从正式入口经过生产主路径，并断言用户可观察结果和关键反事实。

## 2. 当前 E2E 的运行方式

完整工程矩阵要求：

- 从真实 HTTP 入口进入独立 Web 进程；
- 使用真实模型；
- 使用 PostgreSQL；
- 场景需要时使用真实 GitHub、Notion、Web Search、Delivery 或 GPT Researcher Provider；
- 不注入中间 Goal、Proposal、Observation 或业务对象；
- 自动断言最终用户结果；
- 自动断言错误结果和副作用没有发生；
- 保存 trace envelope、manifest、summary 和 checksum。

完整执行命令：

```powershell
$env:PERSONAL_AGENT_REQUIRE_LIVE_E2E = "true"
$env:PERSONAL_AGENT_E2E_TRACE_DIR = "data/e2e_traces"
uv run pytest evals/e2e_quality --e2e-scope=release `
  --e2e-require-complete-matrix -q -s
```

发布投影：

```powershell
uv run python -m evals.e2e_quality.release_gate --trace-root data/e2e_traces
```

## 3. E2E catalog 为什么是唯一分类 Owner

[evidence_catalog.py](../../evals/e2e_quality/evidence_catalog.py)定义：

- 用例 ID；
- pytest test name；
- evidence kind；
- evidence layers；
- capability profile；
- 是否需要真实 Provider；
- fault mechanism；
- 是否能支持产品发布声明。

测试文件名、Markdown 表格和归档文件不能各自发明分类，否则会产生“同一个 E17 在不同地方代表不同能力”的双轨事实。

## 4. 23 个产品/主循环 E2E

### E01-E13：原生产品能力

| ID | 用户旅程 | 关键正向结果 | 关键反事实 |
| --- | --- | --- | --- |
| E01 | Conversation | 直接回答、澄清、多轮继续 | 不伪造 Task/Command/CompletionReport，不跨会话泄漏 |
| E02 | Grounded Ask | 回答有 citations | Ask 不新增 Claim，不跨 workspace 泄漏 |
| E03 | Upload Ask | 上传形成 application Artifact 并被引用 | 不绕过 Artifact ownership |
| E04 | Governed Delete | confirm 后执行一次，可 replay | prepare/reject 零副作用，错误 digest 拒绝 |
| E05 | ResearchRun | 明确终态和带 source 的 Digest | 不把 running 当成功 |
| E06 | MCP Read Extension | GitHub/Notion 真实读取 | unavailable 时不替换能力 |
| E07 | A2A Delegation | 返回 AgentArtifact，父级综合 | child completed 不自动完成父结果 |
| E08 | Ask then Save | 显式 solidify 后保存用户 Claim | Ask 不写，assistant candidate 不写 |
| E09 | Multi-source Capture | text/conversation/upload/URL 均形成 Artifact | URL 不只保存链接或指令 |
| E10 | Knowledge Lifecycle | correction、delete、restart、restore | replay 不重复副作用，deleted Claim 不残留 |
| E11 | Review | feedback 后 schedule 更新 | 重启后 answered card 不再 due |
| E12 | Knowledge Maintenance | 冲突/孤立分析和 backlink | projection 必须绑定 source Claim |
| E13 | Scheduled Intelligence | Run、Digest、Delivery、Feedback 闭环 | Delivery 恰好一次 |

### C01-C04：组合用户旅程

- C01：Workspace ingest + grounded ask + external research + explicit save；
- C02：Subscription + Research + Digest + Delivery + Feedback；
- C03：ingest + Review Card + forgotten + due + external research；
- C04：GPT Researcher delegation + Artifact + parent synthesis。

组合用例证明多个原生能力可以通过稳定契约形成用户价值，而不是只证明孤立接口。

### L01-L06：复杂 Interaction loop

#### L01 Observation-driven replanning

先调用 `list_recent_notes`，模型收到 Observation 后修改 WorkingPlan，再回答。

证明：主循环不是一次性静态脚本。

#### L02 Safe concurrency

同一 turn 的两个独立只读能力进入长度为 2 的 concurrent batch。

证明：并发有 trace 事实，而且只用于可机械证明安全的 action。

#### L03 Process restart recovery

两步 Tool 调用在第一步事实提交后真实终止进程。恢复后执行顺序前缀不变，旧 action 不重复，新 WorkingPlan 标记 `context_rebuild`。

证明：恢复依据 committed facts，不把旧 Plan 当作 durable authority。

#### L04 Manager + Specialist

父 Agent 委托 GPT Researcher bounded sub-goal，得到一个干净 Artifact 后继续综合。

证明：子 Agent 执行与父级完成分离。

#### L05 Budget fail closed

预算不足以让模型在 Observation 后继续时，返回 limitation 和“未生成替代答案”。

证明：Runtime 不生成确定性业务 fallback。

#### L06 Verifier feedback

首次 draft 被判 `needs_revision`，模型修订后再次验证，最终文本逐字等于 passed receipt 的 `verified_draft`。

证明：Verifier 可以反馈，但 Runtime 不改写模型答案。

## 5. E16-E19 外部 Profile 证据

E16-E19 是 connector/provider profile，不单独产生产品发布声明：

- E16：真实 GitHub MCP；
- E17：真实 GPT Researcher A2A；
- E18：真实 Notion MCP；
- E19：MCP capability unavailable。

产品发布声明由消费这些 profile 的 E06、E07、C04、L04 等旅程拥有。

这样避免“GitHub Tool 能调用”被错误解释为“完整用户产品旅程已经完成”。

## 6. E04 如何定位删除链路问题

E04 的证据链包括：

```text
HTTP request
  -> prepare result
  -> Command state
  -> process restart
  -> recovered Command
  -> decision response
  -> Event/Receipt
  -> replay response
```

如果失败，可以判断问题发生在：

- scope resolution；
- Command persistence；
- digest validation；
- confirmation；
- side-effect execution；
- Receipt persistence；
- replay idempotency。

这比只断言“note 最后不存在”更可诊断。

## 7. E2E 与低层测试如何分工

| 测试层 | 负责证明 |
| --- | --- |
| Unit | 领域状态迁移、digest、纯函数和不变量 |
| Contract | Model/Tool/MCP/A2A/Repository Port 与 Adapter 契约 |
| Integration | PostgreSQL、ToolGateway、Journal、Worker queue 组合 |
| E2E | 正式入口到用户结果及反事实 |
| Offline Eval | 模型路由、检索、回答、规划和 Verifier 质量分布 |
| Online Eval | 线上成功率、延迟、token/cost 和失败分布 |

Unit 和 Contract 可以快速定位，E2E 负责防止“每个零件都对，但整体用户结果不对”。

## 8. 当前执行证据

截至 2026-07-26：

```text
E01-E13 = 13/13 passed
C01-C04 = 4/4 passed
L01-L06 = 6/6 passed
total = 23 passed, 0 failed, 0 skipped
duration = 1777.44 seconds
archive exit_status = 0
```

Archive：

```text
data/e2e_traces/20260726T011631.187395Z-20684-4a62da6a
```

架构依赖检查：

```text
unknown_packages = none
missing_packages = none
cycles = none
forbidden_edges = 0
```

## 9. 为什么还不能说“可发布”

Release gate 要求：

1. catalog 分类正确；
2. 用例通过且未 skip；
3. trace envelope 和 checksum 完整；
4. archive commit 与目标 revision 一致；
5. archive 和目标工作树都是 clean；
6. summary exit status 为 0。

当前 archive 和工作树是 dirty，所以 23/23 只能证明该工程现场主路径可执行。它不能建立 clean matching revision 的发布资格。

面试时应说：

> 我把“测试通过”和“具备发布证据”分开。测试结果属于一个具体 archive，只有 archive、commit、工作树和 checksum 都匹配时，release gate 才派生发布资格。当前完整矩阵通过，但由于 revision dirty，门禁按设计 fail closed。

## 10. 当前 E2E 覆盖缺口

现有 E2E 分别证明了 Conversation 和固定产品 Workflow，但还缺少统一自然语言写操作链路：

```text
Conversation message
  -> 模型选择 scoped Application Capability
  -> Prepare Command
  -> Pending Confirmation
  -> 用户确认
  -> 固定 Workflow
  -> Receipt Observation
  -> parent FinalMessage
```

未来至少应增加：

- 对话显式保存成功，以及非显式保存零写入；
- 对话删除：含糊目标必须澄清，确认前零副作用；
- 对话创建订阅：确认后 Worker、Digest、Delivery 闭环；
- scope denied 时零副作用；
- capability unavailable 时不走替代写路径。
