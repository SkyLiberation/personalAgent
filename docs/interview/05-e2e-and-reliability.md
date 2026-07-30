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

## 4. Conversation 与产品 Release E2E

### E01-E14：原生产品能力

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

#### L01 Natural personal-knowledge recall

用户只询问此前记录的随机项目代号，不知道 Tool 名称或执行顺序。Agent 必须自行选择当前
可用的知识读取能力；最终回答必须包含本用户事实、排除另一用户的冲突事实，并且 Trace 中
必须存在包含正确事实的已提交 Observation。

证明：自然用户目标可以驱动真实能力选择，主循环基于 Observation 回答，而不是由测试
Prompt 替 Agent 指定执行方案。

#### L02 Safe concurrency

用户自然询问“最近记录了什么”和“当前有哪些知识缺口或冲突”，不知道对应 Tool。最终回答
必须同时包含随机最近记录和缺口结论；执行后的 trace 才检查两个独立只读 action 进入同一
concurrent batch。

证明：多目标用户结果完整，并发是 Agent 自主选择后的安全执行事实，不是用户提示制造的路径。

#### L03 Process restart recovery

用户只询问此前保存的随机项目验收代号。测试在观察到第一个 committed input、最终回答尚未
产生时真实终止进程；恢复后必须回答本用户随机事实、排除另一用户冲突事实，且执行顺序前缀
不变、旧 action 不重复。

证明：恢复依据 committed facts，不把旧 Plan 当作 durable authority。

#### L04 Manager + Specialist

用户要求面向架构评审的 A2A delegation grant 深度研究，覆盖授权、数据外发、重放、完成
判定和来源，不知道 specialist 的身份。执行后的 trace 必须出现一个干净的深度研究 Artifact，
父 Agent 再交付覆盖上述维度的结构化结论。

证明：子 Agent 执行与父级完成分离。

#### L05 Budget fail closed

用户自然询问随机个人知识。预算足以完成读取、但不足以让模型在 Observation 后继续时，返回
limitation 和“未生成替代答案”；最终消息不得泄漏或猜出随机答案，trace 中必须已有真实读取结果。

证明：Runtime 不生成确定性业务 fallback。

#### L06 Receipt-bound semantic revision

用户要求审查并修订一段缺少执行证据却声称“已完成所有写入”的答复。最终文本不能保留该
无证据声明，必须经过至少一次语义验证，并逐字等于最新 passed receipt 的 `verified_draft`。

证明：用户收到的是经过验证且与 receipt 绑定的安全文本，Runtime 不改写模型答案。真实用户
不关心模型在验证前还是验证后先自行修订，因此 release E2E 不规定 verifier 调用次数；两轮
`needs_revision -> passed` 的反馈状态机由 scripted Runtime Conformance 测试验证。

## 5. E16-E19 外部 Profile 证据

E16-E19 是 connector/provider profile，不单独产生产品发布声明。用户输入仍必须是自然场景：
GitHub/Notion 是用户选择的数据源，深度研究是用户目标；MCP Tool 名、Agent ID、Artifact
类型和内部终态只允许在执行后的 trace 断言中出现。

- E16：真实 GitHub MCP；
- E17：真实 GPT Researcher A2A；
- E18：真实 Notion MCP；
- E19：MCP capability unavailable。

产品发布声明由消费这些 profile 的 E06、E07、C04、L04 等旅程拥有。

这样避免“GitHub Tool 能调用”被错误解释为“完整用户产品旅程已经完成”。

## 6. LT01-LT13 为什么不是 Release E2E

LT01-LT13 验证 Investigation Project 的 durable runtime：

- accepted Plan 驱动 ready set、parallel join 和 coverage；
- approval 绑定 digest；
- steering 不覆盖冻结工作；
- budget/capability missing 进入 typed pause；
- cancel quarantine late Artifact；
- stable submission key 避免重复 child submit；
- worker 重启从 PostgreSQL journal 恢复；
- Completion Gate 不把 Tool/Agent success 当成 Project 完成。

这些用例使用生产 Domain、Application、PostgreSQL Store、Worker Queue、ToolGateway、AgentGateway 和 Artifact owner，但 semantic model 与外部 Provider 是 scripted/frozen Port，而且从 in-process service 进入。因此它们属于 diagnostic/runtime conformance evidence，只能证明状态机和恢复协议，不能证明 live model/provider 的正式用户结果。

要升级为 release evidence，仍需从正式 HTTP 入口进入独立 Web/worker 进程，使用真实模型、真实 PostgreSQL 和场景需要的真实 Provider，以自然用户输入断言最终 Artifact、关键反事实、成本、延迟和恢复结果。

## 7. E04 如何定位删除链路问题

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

## 8. E2E 与低层测试如何分工

| 测试层 | 负责证明 |
| --- | --- |
| Unit | 领域状态迁移、digest、纯函数和不变量 |
| Contract | Model/Tool/MCP/A2A/Repository Port 与 Adapter 契约 |
| Integration | PostgreSQL、ToolGateway、Journal、Worker queue 组合 |
| E2E | 正式入口到用户结果及反事实 |
| Offline Eval | 模型路由、检索、回答、规划和 Verifier 质量分布 |
| Online Eval | 线上成功率、延迟、token/cost 和失败分布 |

Unit 和 Contract 可以快速定位，E2E 负责防止“每个零件都对，但整体用户结果不对”。

## 9. 当前执行证据

截至 2026-07-30：

```text
previous full matrix = 23/23 passed (historical catalog)
natural L01-L05 batch = passed
corrected natural L06 = passed
natural E17/E19 plus L04 = passed
answer-free-prompt E16/E18 = 2/2 passed
current complete matrix = not rerun
LT01-LT13 historical diagnostic matrix = 13/13 passed
current Investigation lifecycle + diagnostic regression = 15 passed
Investigation B03 live baseline = passed, product insufficiency proven
Investigation IP01 live target = passed (3/3 outcome, 5 admitted evidence)
current package dependency gate = failed (3 unknown packages)
```

Evidence archives：

```text
previous full: data/e2e_traces/20260726T011631.187395Z-20684-4a62da6a
natural L01-L05 plus obsolete L06 assertion:
  data/e2e_traces/20260727T163802.147366Z-12512-71873e6b
corrected L06:
  data/e2e_traces/20260727T164815.081968Z-14456-e1196ad4
natural E17/E19 plus L04:
  data/e2e_traces/20260727T162913.553817Z-9428-c723ad92
answer-free-prompt E16/E18:
  data/e2e_traces/20260727T165211.554901Z-17344-3e4bc060
B03 live Investigation baseline:
  data/e2e_traces/20260728T123013.176272Z-42316-76b47a9c
IP01 live target:
  data/e2e_traces/20260729T101501.732689Z-53628-6c5f02f2
```

架构依赖检查：

```text
unknown_packages = context, skills, verification
missing_packages = none
cycles = none
forbidden_edges = 0
result = FAIL (3 architecture violations)
```

## 10. 为什么还不能说“可发布”

Release gate 要求：

1. catalog 分类正确；
2. 用例通过且未 skip；
3. trace envelope 和 checksum 完整；
4. archive commit 与目标 revision 一致；
5. archive 和目标工作树都是 clean；
6. summary exit status 为 0。

旧完整 archive 已不匹配新版自然 E2E；当前定向 archive 和工作树也是 dirty。因此它们只能
作为对应工程现场的定向证据，不能建立当前完整矩阵或 clean matching revision 发布资格。

面试时应说：

> 我把“测试通过”和“具备发布证据”分开。测试结果属于一个具体 archive，只有 archive、
> catalog、commit、工作树和 checksum 都匹配时，release gate 才派生发布资格。新版自然
> 复杂场景和外部场景已定向通过，但当前完整矩阵尚未重跑，门禁按设计 fail closed。

## 11. 当前 E2E 覆盖缺口

E14 已定向证明首条自然语言受治理保存链路：

```text
Conversation message
  -> 模型选择 prepare_conversation_knowledge_save
  -> exact user-authored span + source index
  -> Admission 逐字来源校验
  -> 冻结 exact span 与单一 digest
  -> Pending Confirmation
  -> 用户确认
  -> Workspace canonical write
  -> typed Receipt
```

该证据覆盖 exact span 与 Claim/Receipt 可追溯、控制语义零写入、确认前零写入、prepare 后
重启、跨 scope 拒绝和成功 replay，但不覆盖保存 assistant candidate、多实例并发协调、
Workspace commit 与 journal Receipt 之间的 crash window。B02 已在 archive
`20260729T031804.415533Z-15972-214cb81c` 证明旧错误，修复后 E14 archive
`20260729T033339.065714Z-22692-16415241` 通过。后续候选场景仍必须分别执行 baseline，只有
当前路径确实失败才定义目标 E2E 和实现：

- “只分析，不要保存”等非显式保存表达的零写入 Golden Set；
- 冲突核对后保存 assistant candidate，并保留 Evidence 和候选版本；
- 对话删除：含糊目标必须澄清，确认前零副作用；
- 对话创建订阅：确认后 Worker、Digest、Delivery 闭环；
- scope denied 时零副作用；
- capability unavailable 时不走替代写路径。

Investigation Project 已证明 IP01 的单次 live 目标闭环；仍缺少：

- live structured model + live GitHub/Notion/Web/A2A 的正式 HTTP/worker E2E；
- LT09 同输入 paired baseline，对比 Conversation 的完成率、错误副作用、模型轮次、token、延迟和恢复结果；
- clean matching revision 的 release archive。
