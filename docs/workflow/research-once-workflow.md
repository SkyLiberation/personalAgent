# 一次性与周期 Research 的业务链路

本文拥有 `ResearchService` 的运行、来源、事件和 digest 信息流。一次性及订阅研究维护独立业务事实；普通 Conversation 的研究 claims、修订和最终回答由 [Runtime](../topics/runtime.md)及[核验专题](../topics/verification-and-completion.md)拥有。

## 入口与责任主体

| 边界 | 当前消费者与职责 |
| --- | --- |
| 一次性入口 | HTTP 或 CLI 调用 `AgentService.run_research_once()`，由 `AgentRuntime` 准备运行并调用 `ResearchService.execute_run()` |
| 订阅调度 | `ResearchScheduler` 扫描到期订阅，创建幂等运行并入队；worker 消费现有运行 |
| 业务事实 | Research store 保存订阅、`ResearchRunRecord`、来源、事件、digest、反馈及投递事实 |
| 外部读取 | 服务通过 `ToolExecutor.invoke_direct()` 与 Gateway 执行搜索、正文读取和图谱查询 |
| 投递 | `deliver_run()` 使用 DeliveryRouter 和投递账本，生成 digest 与投递是不同事实 |

入口装配见 [orchestration/runtime.py](../../src/personal_agent/orchestration/runtime.py)，阶段实现见 [application/research/service.py](../../src/personal_agent/application/research/service.py)，数据契约见 [kernel/contracts/research.py](../../src/personal_agent/kernel/contracts/research.py)，调度见 [scheduler.py](../../src/personal_agent/application/research/scheduler.py)。生产启动与 cron 命令由[部署文档](../deploy.md#research-生产调度)拥有。

## 运行阶段

```text
prepare_run
  -> initialize_state
  -> run_research_loop
       选择查询 -> 读取来源 -> 聚类事件 -> 个人相关性排序
       -> 更新证据缺口、用量和停止原因
  -> synthesize_digest
  -> verify_digest
  -> 按业务入口呈现或投递
```

`prepare_run()` 保存用户、主题、指令、时间窗口和 `ResearchLimits`。`execute_run()` 顺序执行初始化、研究循环、合成及核验，已初始化运行跳过初始化；异常写入 `failed` 与原因并向调用方传播。订阅变化只影响后续运行，历史执行仍保留原身份。

`ResearchRunDefinition` 拥有冻结定义，`ResearchRunProjection` 保存运行阶段、用量和追踪。`ResearchDecision.id` 关联实际来源的 `decision_id`，事件保存 `source_ids`，digest claim 保存来源、决策及证据片段，支持从最终判断反查实际读取。

## 搜索、事件与个人相关性

初始化理解原始主题并构造查询计划。后续循环根据已执行查询和证据缺口选择 `search_web` 或停止；服务检查重复查询、动作范围及预算。来源清理包含 URL 归一、去重、排除域和来源分类，按优先级抓取正文。当前该业务链最多保留每个全文来源 12,000 字符，这与 Conversation 的 Artifact 读取契约分别记录。

`StructuredResearchEventExtractor` 生成事件 frame，服务据此聚类、保存事件与来源关系。事件抽取缓存绑定主题、来源及内容指纹；`personal_relevance_cache` 在当前运行中复用事件的个人图谱相关性结果。缓存与排名服务读取，业务事实仍由 Research store 拥有。

当前实现包含启发式 frame、查询和 satisfaction 降级路径：模型未配置或输出非法时，按现有确定性策略继续。它们是代码事实，不能据此宣称模型完成了语义判断或用户结果合格。具体实现可从 [planning.py](../../src/personal_agent/application/research/planning.py)与 [extraction.py](../../src/personal_agent/application/research/extraction.py)反查。

## 停止与结果状态

`_evaluate_research_satisfaction()` 产生 `ResearchSatisfaction`，`_should_stop_loop()` 消费其继续判断并记录原因。模型判断仍受硬预算约束；默认策略检查入选事件、来源策略和关键缺口。

| 停止原因 | 含义 |
| --- | --- |
| 目标事件及关键来源条件满足 | 进入 digest 合成与核验，尚不代表最终质量通过 |
| 查询、全文、工具或模型调用预算耗尽 | 保留实际结果与限制，不记为完整交付 |
| 连续低收益 | 按当前策略停止扩大检索 |
| 没有新的合法动作 | 记录无法继续的事实，保留尚未解除的缺口 |

预算配置由 [env.md](../env.md#research--定时情报简报)拥有。各次工具延迟、失败与结果数进入 `tool_call_traces`；阶段耗时进入 `stage_timings`。这些测量说明发生了什么，不直接证明机制改善成本或延迟。

## digest 核验与投递

`synthesize_digest()` 从当前排序事件生成 `IntelligenceDigest` 及 `DigestClaim`；合成后的阶段性状态由 `verify_digest()` 校准。Research digest 的核验复用 [Evidence Engine](evidence-engine.md)，恢复实际来源片段，记录 `supported`、`partially_supported`、`unsupported` 或 `contradicted`，并收窄支持来源与决策。

缺少来源 URL、找不到对应事件、核心论断不受支持或存在矛盾的条目退出 digest。无据的 supporting/context 论断移除并降低可信标签。事件状态与 claim 支持共同决定 `confidence_label`；最终运行可为 `completed_verified`、`completed_with_limitations` 或具体 partial 状态。无条目时输出本次窗口没有已支持重大更新的说明，不能从空结果推出全局不存在。

订阅投递消费已核验 digest，账本约束重复发送，反馈绑定产生结果的运行。投递成功和内容正确分别验收；当前结果、归档及尚未覆盖的质量边界由[评测盘点](../evals/02-current-case-inventory.md)拥有。自 2026-09-18 起，历史单元测试只读保留，后续按 [QLT](../devSpec/quality-security.md#1-测试职责与覆盖)选择真实 E2E、Offline Eval 和适用静态检查。
