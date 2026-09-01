# 评测模块规范（EVM）

> 本文件适用于 `evals/**`。它继承根 [`AGENTS.md`](../AGENTS.md)，只定义评测代码、数据集、grader、case catalog 和证据归档的局部不变量。修改前必须阅读[变更证据与设计准入](../docs/devSpec/change-evidence.md)、[测试、评估、观测与安全](../docs/devSpec/quality-security.md)、[当前评测体系](../docs/evals/README.md)及目标评测目录。

## 1. 证据分类不能混用

- Product E2E 从正式入口断言 typed `UserOutcomeContract`，可以证明限定场景的用户结果；Application E2E、Runtime Conformance、Integration、Capability Profile 和 Offline Eval 只能证明各自边界，不能外推为产品交付。
- 产品失败 baseline 是实现前以相同用户、输入、入口、初始事实和结果契约执行并失败的证据。指标 baseline 是固定 workload 与 profile 后的比较值。回归 E2E 锁定已有行为。名称中出现 `baseline` 不会自动改变证据类别。
- 单变量消融必须在可还原独立代码状态中只移除目标机制的生产消费点，并保持比较身份一致。生产 flag、测试旁路或 Fake 不能成为消融的产品路径。
- Unit 通过、对象存在、状态 success、数据库记录、工具调用、Trace 步骤或 grader 自述都不能替代用户结果。

## 2. Canonical owner 与写入口

- `evals/e2e_quality/evidence_catalog.py` 唯一拥有证据类别、`UserOutcomeContract` 和机器 eligibility；禁止在测试文件、报告或文档中维护第二份 release 清单。
- `evals/e2e_quality/validation_catalog.py` 唯一拥有横切验证套件及其关键检查点；它只能引用 `evidence_catalog.py` 已登记的用例，不得复制用户输入、fixture、grader 或执行节点。同一用例可以进入多个横切套件，套件成员关系不得改写该用例唯一的证据类别。
- `evals/e2e_quality/evidence_audit.py` 负责只读语义、重叠和 cohort 审计；`release_gate.py` 负责发布 archive 信任判断；`measurements.py` 负责测量 schema；`metrics_report.py` 负责聚合报表。
- 新增或修改 case 时，必须通过 canonical catalog 注册，并同步修改相应 typed contract、选择器与 [`docs/evals/`](../docs/evals/README.md) 的权威说明。不得靠文件名、pytest marker 或 raw dict 隐式定义证据类别。
- 数据集输入、grader 输出、measurement、principal、scope、模型与 Provider 配置必须 typed。外部 payload 在读取边界校验失败时按事实缺失处理，不得填充默认成功。

## 3. 每条用例必须有唯一验收目的

- 新增或修改用例前，必须先写清楚该用例回答的唯一问题：验证一个用户可观察结果、一个正式业务入口的事实链、一个运行不变量，或者一个外部能力配置结果。设计项编号、证据类别、目标结果或不变量、关键反事实、范围外事项和断言责任主体必须能从 canonical catalog、typed contract 或 `docs/evals/` 权威说明中反查；没有这些内容时不得先写测试。
- 每条断言必须直接对应上述目标结果、该结果成立所必需的关键反事实，或者全局权限、隔离、幂等和副作用不变量。删除一条断言后如果用例的设计目的与必要反事实仍然完整，该断言就是冗余要求，必须删除或移入真正拥有它的 Contract、Runtime Conformance 或横切套件。
- 优化项用例只能验收该优化项声明的变量和用户结果。优化项没有改变 Plan、工具选择、智能体委托、查询、调用次数、执行顺序、固定措辞、产物数量或内部状态时，禁止把这些实现细节追加为通过条件；不得为了让既有过度断言通过而修改生产行为。
- 产品 E2E 只要求用户结果和关键反事实，不指定模型必须采取的最小执行路径。工具、智能体、Plan 或 Trace 事实只有本身属于公开产品契约时才能进入产品结果；否则只能作为执行后路径证据或独立机制检查。
- 同一用例可以被多个横切大类复用，各套件只判断自己预先声明的关键能力。整例用户结果、原始 pytest outcome 和局部能力 verdict 必须保持分离；不得因为整例存在与目标能力无关的失败，就把局部能力判为失败，也不得用局部能力通过覆盖整例失败。
- 用例失败时必须执行[按目标、阶段和单变量处理](../docs/devSpec/quality-security.md#2-e2e-阻塞按目标阶段和单变量处理)。先审查用例目的与每条断言；确认属于附加要求时先修正 canonical contract、评测器或用例分类，禁止通过增加 Prompt、预算、状态、降级路径或生产分支迎合。用例合理时才选择用户结果必经链上最早的一个失败责任主体，完成一次有界修正后先只回跑该原子 case；它通过前不得运行相邻昂贵 E2E。
- 阻塞分析必须在 checksum 有效的归档、report 或 `docs/evals/` 权威说明中记录 case id、唯一验收目的、必要断言、合理性结论、最早失败阶段、选中的唯一阻塞、责任主体、因果说明、排除项、下一条定向命令和停止条件。该记录不得建立第二份用例状态或发布清单。

## 4. 产品 E2E 与 grader 边界

- Given/When 使用目标用户自然表达，不得泄漏预期 Tool、Agent、Workflow、内部 ID、步骤或执行顺序。内部路径只在执行后通过 Trace、Event、Receipt 或 Report 断言。
- grader 必须在实现前固定版本、输入与结果契约，直接断言用户可观察结果和关键反事实。禁止让 grader 用字符串包含、对象存在、工具调用或模型自述代替语义结果。
- Fake 只允许隔离不可控第三方、注入危险副作用失败或验证低层 Contract/Conformance。Fake 必须实现生产 Port 并有 contract test，不得替模型、Policy、Admission 或 Verifier 决策。
- 真实 target 使用生产 Composition Root、真实持久化，以及用户结果依赖的真实模型、Provider 与隔离沙箱。冻结 Provider 只能支持可重复消融、故障注入或 Conformance。

## 5. 比较身份与归档

- baseline、消融和 target 必须保存用户输入、principal、正式入口、交互模式、初始事实、config cohort、grader 版本、代码与配置身份、trace 或 report 和 checksum。
- baseline 与 target 必须使用相同 seed、用户输入、principal、正式入口、初始事实和 grader。比较器必须拒绝 checksum 失效、role 错误、比较身份不一致，以及代码与配置身份完全相同的伪配对。
- 每次执行生成独立且 checksum 封印的 archive；禁止覆盖历史结果。历史 archive 只读，不能与不同 grader、Provider、transport、Prompt、预算、fixture 或 cohort 的结果合并。
- 结果报告缺失、pytest 失败、internal error、usage error 或调用阶段异常都必须保持 typed 失败。晋级器不得覆盖测试失败，也不得把执行失败解释成用户结果类型。
- 横切验证报告必须同时保留原始 `pytest_outcome` 与独立的关键检查点结果。整例失败时允许 Tool Calling、MCP dispatch、Agent Artifact 返回等 Runtime Mechanism 检查通过，但局部通过不得覆盖整例结果、进入 Product E2E 分子或被 `release_gate.py` 消费。
- 横切检查只能读取 checksum 有效且代码、配置与评测身份一致的密封 Trace；缺少用例、重复选择同一节点或跨身份拼接必须失败。Provider 成功、用户结果和机制检查是不同 verdict，只有 catalog 预先声明为关键的事实才能忽略整例终态。
- 性能比较只有在用户目标、输入、Provider、模型、Prompt、预算、fixture 和 repetition 一致时成立。不同 case 或 cohort 的完成率、耗时、token 或成本不得直接比较。

## 6. 运行与声明

- 运行前预声明指标门槛、样本量、重复次数、最大成本和停止条件。高成本或真实外部 Provider 评测只在任务需要该证据时执行，不属于普通回归套件。
- 定向 target archive 只能证明对应变更边界，不能替代完整 release matrix。dirty revision 的结果必须记录 dirty digest；没有与目标 clean revision 绑定的完整 release gate 时，禁止声明 release-ready 能力集合。
- 失败时保留 trace、event、receipt、report 和 archive，不得为使门禁通过而修改 grader、删除失败样本、重跑后只挑成功结果，或把不可用指标写成零。
- 评测结果必须报告分子、分母、样本量、方差或适用置信边界，并区分完成率、正确性、错误副作用、成本、延迟和恢复。禁止只报告百分比或挑选单个成功例。

## 7. E2E 执行效率是评测设计门禁

- 高成本 E2E 在执行前必须先完成 collect-only、impact routing 和成本估算。估算优先读取最近一份 checksum 有效、比较身份相符的 archive，并预声明单样本/完整 cohort 的 wall time、token、外部调用成本与早停条件；没有历史数据时先执行最小独立 pilot，不得直接启动大样本循环。
- 出现以下任一信号时，必须在当前原子样本安全结束后暂停新增样本并立即重审 E2E 设计：单样本超过 `60s`；cohort 预计超过 `10min` 或 `200,000` tokens；同 profile 耗时超过最近有效基线两倍；结论已数学上不可逆；或者连续等待不能再增加机制归因信息。除非 runner 有安全取消与 typed failure 归档，禁止在样本中途强杀而制造不完整证据。
- 重审必须先区分产品/Provider 延迟与评测脚手架开销，再按最小改动依次采用：把聚合循环拆成独立 pytest item 和独立 archive；使用预声明约束做数学早停；按最近有效 duration 调整 fail-fast 迭代顺序；只运行 impact map 选中的最小 live selection；复用经过隔离证明的进程或 fixture。不得先增加并发、缓存、mock 或全局状态复用。
- fail-fast、历史耗时排序和定向 selection 只服务开发迭代。它们必须保持完整 catalog collection、正式 case 输入、生产预算和 grader 不变，并清楚标注不能替代完整 release evidence。完整发布命令不得因提速而加入 `-x`、样本裁剪、低预算 profile 或测试旁路。
- promotion cohort 不得用 pytest `--maxfail` 绕过其 typed 门禁；早停只能由预声明约束根据已封存的独立样本判定。局部良好结果不能提前通过，执行失败、缺 report 或成本超限必须进入分母并保持失败。
- 禁止为缩短运行时间而降低用户结果门槛、模型/Agent/Tool 预算、重复次数或反事实覆盖，禁止更换 Provider、Prompt、transport、grader 或 fixture 后仍沿用原比较身份，也禁止用 Fake 替代目标用户结果依赖的真实边界。此类变化必须作为新的评测设计和 cohort 重新准入。
- 每项 E2E 提速改动都必须保存重构前工程基线与重构后证据，至少报告完整收集数量、首个决策反馈时间、完整运行时间、实际执行/避免的样本数、token/外部调用变化、回退行为和未改变的发布契约。若速度没有改善、证据覆盖下降或引入第二套命令 owner，删除候选而不是继续叠加脚手架。
- evaluator、grader、文档或无生产影响的脚手架变更不得重复运行昂贵完整矩阵来制造产品证据；使用受影响的 Contract/Conformance、历史 archive 只读回放和默认工程回归。只有生产候选通过定向 target 与消融、目标 clean revision 需要发布判断，或 Provider/Prompt 漂移需要周期复核时，才执行完整 release matrix。
- 新能力域优先把既有正式 E2E 加入横切套件并读取同一 Trace，禁止仅为重新断言已有 Observation、Receipt、Artifact 或 policy fact 复制一条 live E2E。只有新的用户目标、入口、初始事实、故障边界或关键反事实不能由现有用例承载时才新增 case；局部不变量重合不等于重复旅程。

具体收集、配对、promotion 和 release gate 命令只由[运行、归档与发布](../docs/evals/04-running-and-release.md)维护，本文件不复制易漂移的命令。
