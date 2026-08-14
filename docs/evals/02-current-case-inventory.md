# 当前 E2E 用例盘点

**当前 46 条用例中，12 条是明确的 in-process scripted Investigation conformance；其余 34 条从独立 HTTP 进程进入，但其中仍混有 Application E2E、Runtime/安全诊断和 Provider profile。** 下表按当前代码实际证明范围分类，不沿用 `release_eligible` 的产品含义。

## 1. Conversation 与 Knowledge

| 用例 | 当前入口与边界 | 当前实际断言 | 审计分类 |
| --- | --- | --- | --- |
| `ASK-001A` | Conversation HTTP；真实模型/Postgres | 个人资料冲突被引用、不调用 web、不跨 principal、不写 Claim | **Product E2E**；自然用户目标和结果完整 |
| `ASK-001B` | Conversation HTTP；真实 web search | 个人项目事实与官方 Web 证据进入同一回答、不跨 principal、不写 Claim | **Product E2E**；外部答案正确性仍主要以 capability/source presence 判断 |
| `L01` | 先通过 debug Tool API 写入，再从 Conversation 自然召回 | 正确随机 marker、scope 隔离、有 Observation | **Product regression E2E**；setup 不是普通保存入口，但测试目标是召回 |
| `L07` | Conversation 保存、确认；新 Conversation 召回 | 跨会话保存后可准确回忆 | **Product E2E**；覆盖自然保存到召回的完整纵切 |
| `E08` | 直接 ingest + Conversation ask + `/solidify-conversation` | Ask 零写入；显式 solidify 只接受 user claim | **重复 Application E2E**；用户目标分别被 `ASK-001A/B` 和 `E14/L07` 更强覆盖 |
| `E14` | Conversation 自然保存、确认、重启、replay | 精确 user span 被保存，控制语义不写入，确认前零写入 | **Product E2E**；完整副作用和恢复反事实 |
| `E01` | Conversation HTTP | 简单解释、模糊请求澄清、新问题回答、跨会话 secret 不泄漏、旧 route 404 | **混合回归用例**；包含多个不相干目标，不能视为一个用户旅程 |
| `DUR-001` | Conversation 后读取 `/api/conversation/runs/{ref}`，重启 Web | owner 可读 trace、其他 principal 404 | **安全/运维 Boundary E2E**；主要结果是 trace API scope，不是普通 Conversation 用户结果 |
| `OBS-001` | 同一 trace scope failure + server log | log 中有同 run ref 的 typed deny | **Observability conformance**；不参与产品完成率 |

独立的变更准入证据不计入上述 46 条 release catalog：`CONV-001` 回归用户明示的工作清单审阅、修订与最终交付；
`HARNESS-001` 证明默认交互中正式计划必须先审阅，调用方选择 auto 才可直接执行；`CONV-003` 证明计划项会说明
可验收结果和完成条件，而不是只列执行动作。`CONV-002` 使用同一自然输入保存失败 baseline，并在 target 中证明：
进程重启后恢复同一工作清单，取得三方官方 Observation，最终交付有来源的比较与建议，同时由 Runtime 绑定完成依据。
`HARNESS-003` 使用同一自然输入和冻结 MCP Provider 做单变量消融：移除当前 Plan 绑定的成功 Observation 消费点时，
跨轮继续看不到已提交的随机事实并交付错误口令；恢复消费点后，三个原始档案各执行一次，用户调整后的结果完整交付；同组
简单问答没有创建工作清单。该用例是 **Product E2E + mechanism ablation**，证明的是当前场景中的协调收益，不外推为
所有复杂任务都应创建 Plan。
它们位于
`evals/product_baselines/`。后续执行统一归档到
`data/e2e_traces/product_baselines/<case-id>/<baseline|target>/<run-id>/`；旧的固定
`conv-*.json` 会被后续执行覆盖，已经降为非权威历史调试产物。

## 2. Knowledge lifecycle、Capture、Review

| 用例 | 当前入口与边界 | 当前实际断言 | 审计分类 |
| --- | --- | --- | --- |
| `E22` | Conversation 自然定位知识并请求确认删除 | canonical target、确认前存在、确认后删除、scope 不泄漏、replay 同 receipt | **Product E2E**；自然 Agent 入口最强删除证据 |
| `E04` | 直接 delete command API | cross-scope、双 pending command、重启、confirm/reject、幂等 receipt | **Application/Runtime E2E**；与 `E22/E10` 重叠，不证明自然语言选目标 |
| `E10` | 直接 correct/delete/restore API，中间含 Conversation answer | 纠错后回答、冲突 relation、删除恢复、replay、旧 route 移除 | **混合 Application E2E**；一次用例同时覆盖多个生命周期契约 |
| `E09` | text/conversation/upload/url 四种正式 HTTP 入口 | Artifact/Evidence/KnowledgeItem 关联与 URL 抓取内容 | **Application E2E 套件**；主要断言 canonical linkage，四个用户动作被塞入一条测试 |
| `E11` | ingest、review cards、feedback、重启 | remembered 后 card 不再 due | **Application E2E**；正式 review API 可用，未验证真实提醒/界面体验 |
| `E12` | ingest 后直接调用 review-plan 与 graph-projections | review item/gap 存在、backlink_ok、source_claim_id | **Integration/Projection conformance**；没有用户可观察维护结果 |
| `L06` | Conversation 请求审查一段答复 | 最终文本不再虚假声称写入，Verifier receipt 与文本 digest 绑定 | **Product E2E**；用户确实可请求审查，内部 verifier 只作路径证据 |

## 3. Research、Schedule 与 Investigation

| 用例 | 当前入口与边界 | 当前实际断言 | 审计分类 |
| --- | --- | --- | --- |
| `E05` | `/api/research/once` + run query；真实 web search | run 到终态、digest/items/source_urls 非空 | **Application E2E，用户结果断言偏弱**；没有评价摘要是否正确回答 topic |
| `E13` | subscription API、run-now、真实 worker、delivery query、feedback | digest 存在、delivery record sent、feedback 关联 | **Application E2E，交付断言偏弱**；未读取用户实际收到的内容 |
| `E23` | Conversation 自然要求后台调查 | 返回一个 ProjectReference，Project 进入 planning/active/paused | **Product handoff regression E2E**；只证明创建与引用，不证明调查完成或产品必要性 |
| `PLAN-001` | Conversation 创建、查询、steer、Web restart 后再查询 | 同 Project 引用、plan version/progress、steering capability、restart recovery | **Product regression E2E**；证明已有 Project 控制纵切，不是需求 baseline |
| `IP01` | 直接 Project API，测试显式构造 requirement、budget；真实 worker/model/search | completed、coverage、来源、报告、排除项 | **Application/Runtime E2E**；结果较完整，但输入暴露内部 Project contract，不证明 Agent 自然 handoff 后交付 |
| `E24` | 同一文本分别调用 Research API、Conversation、Project API | 三条路径均返回某种状态且 Project 无环境故障 | **Boundary experiment，不构成有效 paired eval**；没有统一结果 scorer、成本或延迟比较 |

当前没有一条用例完成以下同一用户旅程：

```text
Conversation 自然提出长调查
  -> 页面/请求结束
  -> 服务或 Worker 真实重启
  -> 同 Conversation 查询/调整
  -> 最终读取正确报告
```

`E23`、`PLAN-001` 和 `IP01` 分别覆盖其中一部分，三条独立用例不能拼成组合产品证据。

## 4. Complex loop 与治理

| 用例 | 当前入口与边界 | 当前实际断言 | 审计分类 |
| --- | --- | --- | --- |
| `L02` | Conversation；知识通过 debug Tool API seed | 指定两个 capability 都成功且 trace 出现 size=2 concurrent batch | **Runtime orchestration E2E**；主要证明内部并发机制，用户结果只作伴随断言 |
| `L03` | Conversation；真实 Web crash/restart | committed execution order 保留、不重复、最终返回 marker、scope 不泄漏 | **Product reliability E2E**；真实故障和用户结果均存在 |
| `L04` | Conversation + 真实 GPT Researcher A2A | 一个 AgentArtifact，父 Agent 综合安全边界与来源 | **Product E2E**；与 `E17` 的 Provider profile 重复执行同类深研 workload |
| `L05` | Conversation；测试将 max model turns 配为 1 | 有 Observation 但最终 limitation，不生成替代答案 | **Runtime policy E2E**；真实用户结果是 fail closed，配置属于故障/约束注入 |
| `CTX-001` | Conversation + frozen document MCP | 更正后的阈值和三份固定大文档 marker 均正确，Observation 有界并通过重读取得 | **Context/MCP conformance E2E**；冻结 Provider，不参与真实产品完成率 |
| `GOV-001` | Conversation + 恶意 frozen MCP + hidden tool | 外部文档被读，隐藏 Tool 未执行 | **Security conformance E2E**；场景为攻击夹具而非普通用户旅程 |
| `RUN-001` | Conversation + frozen records + tool budget=2 | Provider 调用不超过 2，未读事实不出现在答案 | **Budget conformance E2E**；重点是 Admission/执行上限 |

## 5. Capability Profile

| 用例 | 当前入口与 Provider | 当前证据 | 审计分类 |
| --- | --- | --- | --- |
| `E16` | Conversation + 真实 GitHub MCP | 精确读取文件标题且只有 GitHub Tool result | **Capability Profile acceptance** |
| `E18` | Conversation + 真实 Notion MCP | 精确读取指定测试页面 marker | **Capability Profile acceptance** |
| `E19` | Conversation，无 GitHub/Notion capability | limitation、零 Tool call、零编造 | **Capability availability negative profile** |
| `E21` | Conversation + 真实 GitHub MCP 大文件 | 地址和本次读取行号正确，Observation/Token overshoot 有界 | **Provider + Context integration E2E**；不只是连接器 smoke |
| `E17` | Conversation + 真实 GPT Researcher A2A | 一个 child Artifact、父级答案、agent_calls=1 | **Capability Profile acceptance**；与 `L04` 的产品旅程重叠 |

## 6. Investigation LT Runtime Conformance

`LT01、LT02、LT03、LT04、LT05、LT06、LT07、LT08、LT10、LT11、LT12、LT13` 均：

- 从 `InvestigationScenarioHarness` 或 Application Service 进入；
- 使用 scripted planner/proposer/verifier/synthesis 与 frozen Tool/Agent Provider；
- 可以直接构造 Plan、Command、approval、late result、budget failure 和 crash window；
- 使用真实 Domain、Application、Postgres store 和部分 worker/recovery 协议。

它们属于 **Investigation Runtime Conformance**，当前文件位于 `evals/runtime_conformance/investigation_project`。

| 用例族 | 证明重点 |
| --- | --- |
| `LT01/LT04` | verified outcomes 后才能 join/synthesize/complete |
| `LT02/LT10/LT13` | crash、stable submission key、async create/recovery |
| `LT03/LT12` | steering/replan 不改写 frozen work |
| `LT05` | digest-bound approval 前零 provider call |
| `LT06` | budget exhaustion 后 pause/partial coverage |
| `LT07` | cancel 后 late result quarantine |
| `LT08` | scope isolation across recovery |
| `LT11` | capability missing fail closed |

这些用例已迁移到 `evals/runtime_conformance/investigation_project`。它们可以保护运行协议，但不能用于声称真实模型能规划、真实 Provider 能完成调查或用户需要 InvestigationProject。
