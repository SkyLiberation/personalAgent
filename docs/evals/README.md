# 当前评测体系

**canonical catalog 当前登记 29 条证据：9 条有 typed `UserOutcomeContract` 的 Product E2E，以及 20 条 supporting evidence。** 后者包括 8 条 Application Integration、7 条 Runtime Conformance、4 条 Capability Profile 和 1 条用于校准研究答案评测器的 Boundary Evaluation。产品发布完成率仍只消费前 9 条；横切验证套件不改变发布分母。

## 文档入口

| 文档 | 回答的问题 |
| --- | --- |
| [证据分类](01-evidence-classes.md) | Product E2E、Application Integration、Runtime Conformance、Capability Profile 和离线 Eval 分别证明什么 |
| [当前用例盘点](02-current-case-inventory.md) | 当前用例、横切套件及历史撤回证据的入口、Test Double、用户结果强度和可用证据等级 |
| [baseline-first 审计](03-baseline-first-audit.md) | 哪些用例有实现前失败证据，哪些只是已有设计的回归或机制演示 |
| [运行与发布](04-running-and-release.md) | 如何收集、执行、归档和判断当前 revision 的发布证据 |
| [观测指标](05-observability-metrics.md) | 当前 archive 能输出哪些性能指标，哪些指标尚不可用 |

## 当前机器事实

截至 2026-09-04，canonical catalog 的机器分类如下；参数化样本数与用例数分开统计：

```text
catalog cases: 29
qualified Product E2E: 9
supporting evidence in e2e_quality: 20
retired Investigation conformance: 0
HTTP process entry: 28
real model required: 29
contains test doubles: 3
process-termination cases: 7
```

当前工作树为 dirty，尚未执行与目标 clean revision 绑定的完整 release gate；因此没有可陈述的 release-ready 能力集合。定向 target archive 只能证明对应变更边界，不能替代发布矩阵。

按用户最新要求，当前优先处理 Final 的来源支持范围，独立评测器候选暂停。生成组件先依据封存原文和明确人工标签核对；自动评测与产品发布证据仍保留原门槛，不能由人工组件结果代替。推进顺序由[来源支持设计](../future/conversation-source-support.md)拥有。

研究回答的错误生成、Verifier 放行、旧稿传播与后续评测错误已按责任边界分开定位，
完整因果链、原始响应复核及历史请求缺失的限制见[根因定位结论](C:/pae/root-cause-synthesis-20260908/conclusion.md)。
定位结论不代表生产修复、稳定性证明或原用户 E2E 通过。

研究答案独立评测器现使用 v3：补齐有限参考摘要遗漏的控制选项和强制要求，不改变生产 Agent 或用户结果门槛。
既有校准 20/20，但真实长答案重评分仍错误拒绝已被依据支持的 MCP 论断，修复未闭环。
后续固定输入诊断确认：授权原文已进入 Final 和生产 Verifier，却未进入独立评分器；
评分器还会将答案完整性混入论断支持判断，显式低温和字段顺序调整均不足以消除错误。
分组结果、责任边界与限制见[独立评分器定位报告](C:/pae/grader-order-diagnosis-20260908/conclusion.md)。
后续隔离候选先试验论断抽取，出现改写义务强度、遗漏总结和超时；没有接入当前评测器或生产。
直接读取原答案的窄职责评测仍漏报；段落对照进一步发现跨规范和义务范围的误用。
隔离参考后的单个否定判断改善，但原文绑定协议失败。补齐原始引用的正控制在混合参考和仅 Tools 参考下均通过，尚不足以准入通用来源过滤。
候选、实际运行与机械测试的限制见
[候选边界记录](C:/pae/source-support-candidate-20260908/conclusion.md)。
完整原文块、全答问题集合、模型、普通文本与思考对照均未取得资格；完整响应仍有答案与参考身份混用。参考审计随后发现实际引用的旧版 Tools 来源未投影，补齐后首次判别因非法正向状态触发结构修复，重新生成的报告又误判。消费者核对确认无需穷举完整问题清单；后续整体二态试验无结构修复，但仍把原句的 SHOULD 当成强制要求而错误拒绝。各次原始结果、实际用量与下一诊断边界均由候选边界记录拥有；不能把整体拒绝当成正确判别，也不能把窄阅读控制外推为完整答案通过。生产配置及 canonical 评测器未采纳这些候选。
后续相邻句反事实与输入顺序对照仍未取得完整答案资格。Pro 对照得到预期正负布尔，但负例解释错误；删除解释输出的候选又漏放原错误答案，见[仅分类资格记录](02-current-case-inventory.md#仅分类支持评测的资格失败)。随后独立诊断中，局部能够识别的同一缺陷在完整答案中仍被漏放；最新输入审计与单样本限制由[局部与完整答案诊断](02-current-case-inventory.md#局部与完整答案的支持边界诊断)拥有。旧模型与不同协议的样本不混算，局部改善不能替代完整校准。
只替换 Final 阶段前缀的单次真实输入试验仍缺少 URL 并作出无据论断，原始响应完整；没有修改生产 Prompt。
该候选已退出。选材职责诊断也出现引文改写、来源身份错配和结构修复超线，尚未准入分阶段生成；
坐标选择试验虽返回完整响应，仍配错读取身份与 offset，并存在选中片段不能支持结论的问题。
无损解码输入后的坐标均可恢复，但仍用附近主题支持没有对应条款的结论；首次原始响应另有主体和否定条件翻转。
纯选择仍选中无正文抓取记录且输出截断；候选目录随后返回合法引用，但完整任务仍遗漏已读结果契约。保持正文不变、只收窄问题后能找到该条款，不能以此证明完整任务通过或必须增加模型调用。
补回原正式请求已有的独立成功标准后，选材包含先前遗漏条款，但接近全量且有重复，未证明新增选择调用的必要性。生产本已传入标准，不能把诊断删去该消息解释为生产漏传。
Final 无损正文视图通过往返检查，但完整原始响应仍有无据来源归因。跨领域相邻示例首次违反 FinalMessage 输出协议，结构修复再次生成正文后仍有语义问题，且总用量超线；两项都未进入生产。
仅将原生产首次 Final 的末尾执行资料从系统消息改为用户消息后，完整响应仍扩大否定范围。原 Plan 只说需要补齐资料，没有直接提供该否定论断；角色候选未准入，后续先校准完整答案的支持评测。
实际请求数、逐项原文审计与请求权威边界核对见[Final 来源边界记录](C:/pae/final-authority-boundary-20260908/conclusion.md)。
执行与历史评分隔离规则见[研究答案评测器的前置校准](04-running-and-release.md#研究答案评测器的前置校准)。

首次 Final 完整请求的后续反事实另复现非空截断：服务方输出重复并以 `length` 结束，
通用解析器补齐 JSON 外壳后仍接纳为 `FinalMessage`。这是独立于事实判别的错误处理缺口，
尚未修复；两次试验与确定性解析核对见[首次生成边界报告](C:/pae/first-final-body-counterfactual-20260908/conclusion.md)。

历史 `current-runtime` 标签仍包含 3 个不兼容 cohort；新运行默认使用完整 cohort digest 生成 profile id，`--list-cohorts` 可枚举旧数据。2026-08-12 的独立验证 profile 已成功生成 completion/limitation、端到端 latency、provider input/output/total tokens 和 model/tool/agent turn/call 报告；非恢复场景的 recovery facts 保持 unavailable。

## 三个词不能混用

- **产品失败 baseline**：变更前用相同用户、输入、入口和结果契约执行并失败，用于证明“为什么需要改变产品行为”。
- **指标 baseline**：固定 workload/profile 后保存的质量、成本或延迟参考值，用于比较回归。
- **回归 E2E**：锁定已经存在的产品行为；它可以有价值，但不能反向证明该设计最初有必要。

测试函数、trace 文件和 profile 中大量使用 `baseline` 字样；这些名称本身不构成产品失败 baseline 证据。

## 权威来源

- 证据类别、产品结果契约和机器 eligibility：`evals/e2e_quality/evidence_catalog.py`；
- 可重叠的横切验证套件与关键检查点：`evals/e2e_quality/validation_catalog.py`；
- 密封 Trace 的横切检查报告：`evals/e2e_quality/cross_cutting_validation.py`；
- 只读语义、重叠和 cohort 审计：`evals/e2e_quality/evidence_audit.py`；
- 发布 archive 信任判断：`evals/e2e_quality/release_gate.py`；
- 测量 schema：`evals/e2e_quality/measurements.py`；
- 聚合报表：`evals/e2e_quality/metrics_report.py`；
- 本文档集合：解释机器 contract 与结果，不再维护第二份 release 清单。
