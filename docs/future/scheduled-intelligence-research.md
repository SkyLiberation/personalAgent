# 持续研究 P1/P2 目标设计

> 状态：目标设计，尚未实现。本文只定义来源验证和事件触发增量；当前实现见
> [当前核心架构](../summary/core-architecture-current-state.md)、
> [research_once workflow](../workflow/research-once-workflow.md) 和
> [Research 环境配置](../env.md#research--定时情报简报)。

## 1. Goal and Baseline

用户希望持续追踪主题、实体或事件，并收到可区分“原始来源、转载、待证实声明、修订”的更新。
重要变化即时提醒，普通变化进入定时简报，没有变化时不制造消息。

当前最简单 baseline 是周期性 `ResearchSubscription -> ResearchRun -> Delivery`。它适合定时查询和
投递，但在实现 P1/P2 前必须用 E2E 冻结以下缺口，而不能凭设计假设：

- 多个域名转载同一内容是否被误认为多个独立来源；
- 后续官方修订是否覆盖了旧事件或旧简报；
- poll/webhook 重复到达是否重复研究和投递；
- 安静时段、暂停和恢复是否保持事件时间与副作用幂等；
- credential/capability 缺失时是否 fail closed。

若扩展现有固定 Workflow 就能满足这些结果，不引入通用长任务、动态 Planner 或新的知识事实模型。

## 2. Expected User-visible Result

用户看到的每条重要更新必须明确：

- 官方一手来源、相互独立的二手来源和转载链；
- 尚未独立证实的单一声明；
- 新信息是补充、修订还是反转；
- 为什么即时提醒、延后投递或进入下一次简报；
- 当前追踪是否 paused、缺少凭据或等待外部环境。

反事实同时成立：不重复研究/投递，不把搜索摘要当 verified evidence，不把不同域名数量当来源独立性，
不因通知优先级改变事件可信度，不在 subscription 暂停后创建新 ResearchRun。

## 3. Decision and Fact Ownership

| 决策/事实 | Owner | 唯一写入口/边界 |
| --- | --- | --- |
| 原始抓取正文、locator、内容指纹 | Artifact/Evidence store | connector ingestion；正文不复制进 run state |
| URL 归一、canonical URL、转载候选 | Source canonicalization projection | admitted source observation 重建 |
| 来源是否语义独立 | typed model proposal + admission | 代码只验证结构，不按域名数直接判定 |
| source event identity、revision/supersedes | Research event lifecycle | event admission transaction |
| Subscription、cursor、ResearchRun、Delivery | 各自领域 owner | 不双写为通用 DurableTask |
| Claim、EvidenceBlock/Span | Personal Knowledge knowledge lifecycle | Research 只引用，不另建 Claim 写入口 |
| 重要性与个人相关性 | Digest decision/output | 不成为事实真实性判断 |
| 即时/定时/安静时段投递 | deterministic delivery policy | 不修改事件发生时间或可信度 |

Connector 只产生外部 Observation；模型负责来源独立性和事件关系的开放语义；Policy 负责通知预算、
安静时段和权限；Gateway/worker 产生获取与投递事实；Verifier 判断 claim-level evidence 是否充分。

## 4. P1: Source and Verification

### 4.1 Minimum Scope

1. 面向新闻、release 和原始页面的 typed read tool，继续经 Gateway 执行；
2. URL、canonical URL、转载链和内容指纹的 source canonicalization；
3. 来源独立性由结构化特征和模型 typed assessment 共同形成；
4. 官方来源优先级只作为 ranking policy，不等于内容自动为真；
5. claim-level verification 只消费 admitted EvidenceRef，不直接消费搜索摘要；
6. 新信息形成 event revision/supersedes，不覆盖旧事件和旧简报；
7. 趋势判断引用多个时间窗口，单次尖峰不能直接成为长期趋势。

### 4.2 E2E First

```text
E2E SI-P1-01: 三个域名转载同一新闻，只形成一个原始来源链；最终简报显示转载关系
And not: 不显示“三个独立来源已证实”

E2E SI-P1-02: 官方 changelog 与媒体摘要冲突，同时保留双方 Evidence 和冲突状态
And not: 不静默合并为单一确定结论

E2E SI-P1-03: 只有单一匿名来源，简报标记“尚未独立证实”
And not: 不因模型置信度或搜索排名升级为 verified

E2E SI-P1-04: 后续官方修订形成新 event revision，旧简报仍可按原 digest 回放
And not: 不覆盖旧 Event、Evidence 或 Delivery

E2E SI-P1-05: 页面含 prompt injection，正文可作为 untrusted Artifact 保存但不进入 verification evidence
And not: 页面指令不改变查询、Policy 或回答

E2E SI-P1-06: Claim 抽取失败，已提交 Artifact/Evidence 保留并返回 typed partial failure
And not: 不回滚已发生的获取事实，也不伪造 Claim
```

每个用例从正式 research API/application entry 进入，经过生产 ResearchRun、Artifact/Evidence、
source admission、digest 和 delivery 路径；断言 canonical source、Evidence admission、event revision 和
最终用户结果。冻结外部页面可以 Fake，但模型语义判断、Admission 和 Delivery policy 必须真实。

目标命令：

```powershell
pytest -q evals/e2e_quality/test_scheduled_intelligence_source_verification.py
```

## 5. P2: Event-triggered Tracking

### 5.1 Minimum Scope

- RSS、官方 changelog、GitHub release 和论文源等结构化 connector；
- tracked entity/event/topic subscription；
- 即时提醒与定时摘要的确定性投递策略；
- 安静时段、通知优先级和每日打扰预算；
- follow-up subscription 引用原 topic/entity，不复制旧 ResearchRun；
- connector cursor、ResearchRun 和 Delivery attempt 分别管理生命周期；
- 重启、断连和重复事件到达时不重复研究或投递。

只有第一个真实 connector 的 E2E 通过后才抽取第二个 connector 的公共 Port；禁止先建设 connector
marketplace、通用 Event Bus 或动态 Planner。

### 5.2 Durable Invariants

1. 同一 source event 的重复到达由 canonical event identity 去重；
2. 即时提醒只改变投递时机，不改变 Evidence 或可信度；
3. subscription paused 后不得创建新 ResearchRun；
4. 已 dispatch 的调用按既有 Journal reconcile，不重新生成业务查询；
5. Delivery 失败只重试同一 digest 的投递，不重新搜索或生成 digest；
6. 安静时段推迟发送，不修改 event occurrence time；
7. connector credential 获得批准不等于远端已经 available。

### 5.3 E2E First

```text
E2E SI-P2-01: 同一 GitHub release 经 poll 和 webhook 重复到达，只形成一个 event/ResearchRun/Delivery
And not: 不重复搜索、生成或发送

E2E SI-P2-02: event admitted 后、delivery 前进程终止；重启复用同一 digest 并投递一次
And not: 不重新调用模型生成简报

E2E SI-P2-03: 安静时段的重要事件进入 pending delivery，窗口开放后发送一次
And not: event occurrence time 不被改成发送时间

E2E SI-P2-04: 普通事件进入下一次 digest，不触发即时通知
And not: 不因内容新颖度越过用户通知 policy

E2E SI-P2-05: subscription paused 后 connector 回调，不创建新的 ResearchRun
And not: 不依赖 Prompt 忽略回调

E2E SI-P2-06: connector 缺 credential，进入 typed authorization/capability missing
And not: 不选择相似 Provider、不生成替代结果

E2E SI-P2-07: follow-up 引用原 entity/event ID，旧 run 内容不复制为新事实 owner
And not: tenant/personal knowledge scope 不得变化
```

目标命令：

```powershell
pytest -q evals/e2e_quality/test_event_triggered_research.py
```

## 6. Affected Modules and Dependency Direction

目标变更限于现有 Research 领域及其 Port：

```text
Connector Adapter -> Research Application -> Research/Event domain
                                      -> Artifact/Evidence Port
                                      -> Delivery policy/Port
                                      -> existing worker journal
```

不把固定持续研究迁入
[Durable Investigation Project](../summary/durable-investigation-project-current-state.md)，不复制 Artifact、Evidence、Claim、Gateway、
Journal 或 Delivery 状态。Connector Adapter 只转换协议和产生 typed observation，不补研究语义。

## 7. Removed Legacy Path

实施时必须删除或拒绝以下路径：

- 以域名数量直接计算独立来源；
- 将搜索摘要直接传给 claim verifier；
- 覆盖旧 event/digest 的“最新状态”写入口；
- connector、scheduler 和 callback 各自创建 ResearchRun 的多写入口；
- delivery retry 重新运行 research；
- 缺 credential 时选择相似 provider 的 fallback；
- 为新 connector 保留新旧 cursor 或 event identity 双轨。

如果这些路径当前不存在，不为“迁移完整性”而创建兼容层或 converter。

## 8. Non-goals and Delivery Order

明确不做：通用网页爬虫、绕过登录/付费墙、默认写入全部外部文本、无限 subscription、通用动态
Planner、通知 Agent 团队，以及没有 E2E 的 connector 抽象。

实施顺序：

1. 先提交 baseline 与 P1/P2 E2E，冻结同一外部输入；
2. 先落地 P1 source identity/revision 的单一纵切，删除旧判定路径；
3. 再落地一个 GitHub release connector 的 P2 纵切和 durable dedupe；
4. 只有第二个真实 connector 证明同一契约后才抽取共享 Adapter Port；
5. 运行 unit、contract、integration、E2E、lint/type/layer checks；
6. 更新 current-state/workflow/env 并删除本文。

## 9. Definition of Done

P1/P2 只有同时满足以下条件才算完成：

1. 上述正式入口 E2E 与外部 Port contract tests 实际通过；
2. source、event、subscription、run、delivery 各有唯一 owner 和写入口；
3. crash/retry 不重复获取、研究、模型生成或投递；
4. Evidence admission 与 Claim lifecycle 仍使用既有权威模块；
5. 新 connector 不引入 raw dict identity、Provider fallback 或 cursor 双写；
6. 用户结果同时证明“正确更新发生”和“重复/伪证实未发生”；
7. 当前事实文档和运维文档更新，本文删除而不是追加已落地记录。
