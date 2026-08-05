# 证据、E2E 与发布资格

本文是证据口径的权威参考：用例编号、archive、分级和 release gate 状态。任何其他文档引用证据时
必须与本文一致。写法遵守 [面试文档规范](00-writing-spec.md)，方法论层面见
[能力轴 11](03-capability-axes.md#11-评估与发布证据)。

证据分级（规范第 5 条）在本文的具体落位：

```text
A 正式入口 E2E + clean matching revision   -> 当前无（完整矩阵未在 clean revision 重跑）
B 正式入口 E2E，dirty revision 或覆盖窄     -> E01-E05、E08-E14、E20、E22-E23、L01-L06、IP01
C Profile、诊断运行、单测、对象存在         -> E16-E19、E21、E24、LT01-LT08、LT10-LT13
D 仅设计或推理                             -> 第 11 节的候选 baseline
```

因此本文中所有「passed」都最多是 B 级。**当前没有任何 A 级证据**——package DAG gate 已转
PASS（第 9 节），但 archive 与工作树 dirty，clean matching revision 仍未闭合。

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
- fault mechanism；
- 是否能支持产品发布声明。

测试文件名、Markdown 表格和归档文件不能各自发明分类，否则会产生“同一个 E17 在不同地方代表不同能力”的双轨事实。

## 4. Conversation 与产品 Release E2E

### E01-E05、E08-E14、E20、E22-E23、IP01：应用能力

| ID | 用户旅程 | 关键正向结果 | 关键反事实 |
| --- | --- | --- | --- |
| E01 | Conversation | 直接回答、澄清、多轮继续 | 不伪造 Task/Command/CompletionReport，不跨会话泄漏 |
| E02 | Grounded Ask | 回答有 citations | Ask 不新增 Claim，不跨 workspace 泄漏 |
| E03 | Upload Ask | 上传形成 application Artifact 并被引用 | 不绕过 Artifact ownership |
| E04 | Governed Delete | confirm 后执行一次，可 replay | prepare/reject 零副作用，错误 digest 拒绝 |
| E05 | ResearchRun | 明确终态和带 source 的 Digest | 不把 running 当成功 |
| E08 | Ask then Save | 显式 solidify 后保存用户 Claim | Ask 不写，assistant candidate 不写 |
| E09 | Multi-source Capture | text/conversation/upload/URL 均形成 Artifact | URL 不只保存链接或指令 |
| E10 | Knowledge Lifecycle | correction、delete、restart、restore | replay 不重复副作用，deleted Claim 不残留 |
| E11 | Review | feedback 后 schedule 更新 | 重启后 answered card 不再 due |
| E12 | Knowledge Maintenance | 冲突/孤立分析和 backlink | projection 必须绑定 source Claim |
| E13 | Scheduled Intelligence | Run、Digest、Delivery、Feedback 闭环 | Delivery 恰好一次 |
| E14 | Conversation Governed Save | exact user-authored span 确认后保存 | 控制语义、assistant candidate 不写入 |
| E20 | Workspace Answer Verification | 冲突 assessment 绑定本次 EvidenceSpan | 回答组装器不把互斥结论标成 supported |
| E22 | Goal-entry Governed Delete | 自然语言定位 canonical item，确认后删除一次 | 确认前零副作用、跨 scope 不泄漏、replay 不重复 |
| E23 | Goal-entry Durable Investigation | 自然目标创建可查询 ProjectReference | 不要求内部名称、不复制 Project 状态、不把创建算完成 |
| IP01 | Durable Investigation Report | live worker 交付可读、可追溯报告 | 缺 coverage/evidence 时不完成 |

E24 用同一个开放架构调查自然目标对照 ResearchRun、Conversation 和 Project，属于 diagnostic
boundary evaluation，不参与 release 记功。`20260803T143230.864789Z-6460-dbd005fd` 中
ResearchRun 只抓到二手来源，Project 因无法满足官方规范来源要求而诚实暂停；该对照没有证明
ResearchRun 适合作为通用研究入口，因此它继续只服务 Scheduled Intelligence。

### 为什么当前没有组合能力 E2E

原 C01–C04 把 ingest、ask、research、save 等独立 Use Case 串起来，却没有断言一个不可拆分的
用户结果；C02 直接复跑 E13，C04 直接复跑 E17。因此它们已退出 catalog。组合能力不是把多个
接口各调用一次，而是先有单一用户目标、同输入 baseline 失败，再由一条正式入口 E2E 证明结果。

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

#### L06 Runtime-owned semantic revision

用户要求审查并修订一段缺少执行证据却声称“已完成所有写入”的答复。最终文本不能保留该
无证据声明，必须经过至少一次语义验证，并等于 passed receipt 的 `verified_draft`。判据、触发与
产物三者都由 Runtime 拥有：判据从用户表述派生并逐字校验，verifier 不在模型能力清单里，
发出的字节直接取自 Runtime 已持有的凭据（[ADR 0010](../adr/0010-runtime-owned-interaction-verification.md)）。

**当前真实状态：9 次真实模型运行 9 次通过**（所有权收归 Runtime 前为 5/9），因此升为 **B 级**。
改动过程中一条值得记录的实测：仅收回控制权与判据权时是 0/3，确定性地以
`clarification_required` 终止——模型向用户索取判据提到的那份证据，而非删掉无证据的断言。
只有 `answer` 会被验证，非 answer 的 disposition 因此是一条绕过验证的出口；Runtime 拒绝该
disposition 后 9/9。

设计意图：用户收到的是经过验证的安全文本，Runtime 不改写模型答案。真实用户
不关心模型在验证前还是验证后先自行修订，因此 release E2E 不规定 verifier 调用次数；两轮
`needs_revision -> passed` 的反馈状态机由 scripted Runtime Conformance 测试验证。

## 5. E16-E19、E21 外部 Profile 证据

E16-E19、E21 是 connector/provider/runtime profile，不单独产生产品发布声明。用户输入仍必须是自然场景：
GitHub/Notion 是用户选择的数据源，深度研究是用户目标；MCP Tool 名、Agent ID、Artifact
类型和内部终态只允许在执行后的 trace 断言中出现。

- E16：真实 GitHub MCP；
- E17：真实 GPT Researcher A2A；
- E18：真实 Notion MCP；
- E19：MCP capability unavailable。
- E21：超大 GitHub 文件返回在 observation/token budget 内分页取证。

E17 的产品级父子协作结果由 L04 证明；E16/E18/E19/E21 当前只提供专项诊断证据。删除 E06/E07
wrapper 避免同一条实际旅程被多个编号重复记功。

这样避免“GitHub Tool 能调用”被错误解释为“完整用户产品旅程已经完成”。

## 6. LT01-LT08、LT10-LT13 为什么不是 Release E2E

这 12 个用例验证 Investigation Project 的 durable runtime：

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

旧 LT09 没有执行 Conversation baseline；`input_digest_equal`、`capability_digest_equal` 和
`conversation_coverage=2` 是 harness 常量，不是 paired execution 结果，因此已删除。

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
LT01-LT13 historical diagnostic matrix = 13/13 passed（历史 catalog，LT09 结论已撤销）
current Investigation lifecycle + diagnostic regression = 15 passed
Investigation B03 live baseline = passed（仅证明当时 revision 的历史不足）
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

架构依赖检查（`uv run python scripts/check_layers.py`，2026-07-30）：

```text
packages=14 edges=53
unknown_packages=none
missing_packages=none
cycles=none
forbidden_edges=0
OK: explicit package DAG satisfied
```

这条的**历史**要主动说，因为它本身是一个诊断教训：此前门禁长期 FAIL，
`unknown_packages = context, skills, verification`。追下去发现三个目录只剩
`__pycache__/*.pyc`、`git ls-files` 为空——是已删除包的编译残骸，而
`discover_packages()` 只判断 `isdir` 就把它们数成了包。**门禁报的是真实失败，但根因不是
架构违规，而是门禁自己的探测规则。** 修法两步：删残骸目录，并要求目录内至少有一个 `.py`，
使未来的 stale pycache 不再制造幻影 FAIL。教训是 fail-closed 门禁也需要区分「被守护的
不变量破了」与「探测器坏了」，否则会长期误报并稀释门禁可信度。

门禁转 PASS 移除了 clean release 资格的一个障碍，但 A 级证据仍不成立——原因是 archive 与
工作树 dirty，见下一节。

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
- 如要重新提出 Project 优于 Conversation 的恢复声明，先实现真实同输入 paired baseline，并比较完成率、错误副作用、模型轮次、token、延迟和恢复结果；
- clean matching revision 的 release archive。
