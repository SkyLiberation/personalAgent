# 评测模块规范（EVM）

> 本文件适用于 `evals/**`，继承根 [AGENTS.md](../AGENTS.md)。修改前必须完整阅读[变更证据与设计准入](../docs/devSpec/change-evidence.md)、[测试、评估、观测与安全](../docs/devSpec/quality-security.md)、[当前评测体系](../docs/evals/README.md)及目标评测目录。本文拥有评测代码登记、比较身份、归档和执行效率规则。

## 1. 证据分类不能混用

测试分类与 Test Double 边界由[QLT](../docs/devSpec/quality-security.md#1-测试职责与覆盖)定义；Product E2E 必须满足根规范的完整智能体生产链和用户结果要求。绕过智能体的正式 Application 旅程归类为 Integration，不能因入口正式而称为 E2E。

- 产品失败 baseline 是变更前以相同用户、输入、入口、初始事实和结果契约执行并失败的证据。
- 指标 baseline 是固定 workload 与 profile 后的比较值。
- 回归 E2E 锁定已有行为，不能反向证明设计最初有必要。

文件名、pytest marker 或报告中的 `baseline` 字样不决定证据类别；机器分类必须由下一节的唯一目录登记。

## 2. Canonical owner 与写入口

评测事实按下表分别拥有；报告和文档只能解释机器契约，不能维护第二份发布清单。

| 文件 | 唯一职责 |
| --- | --- |
| `evals/e2e_quality/evidence_catalog.py` | 证据类别、`UserOutcomeContract` 与机器 eligibility |
| `evals/e2e_quality/validation_catalog.py` | 横切验证套件及关键检查点；只引用已登记用例，不复制输入、fixture、grader 或执行节点，也不改写用例类别 |
| `evals/e2e_quality/evidence_audit.py` | 只读语义、重叠和 cohort 审计 |
| `evals/e2e_quality/release_gate.py` | 发布 archive 信任判断 |
| `evals/e2e_quality/measurements.py` | 测量 schema |
| `evals/e2e_quality/metrics_report.py` | 聚合报表 |

新增或修改用例必须同步 canonical catalog、相应 typed contract、选择器与[评测权威文档](../docs/evals/README.md)。数据集输入、grader 输出、measurement、principal、scope、模型与服务提供方配置必须 typed；外部 payload 在读取处校验失败时按事实缺失处理，不得填充默认成功。

## 3. 每条用例必须有唯一验收目的

编写用例前必须明确它验证的是用户结果、正式业务入口的事实链、运行不变量，还是外部能力配置。设计项编号、证据类别、目标、关键反事实、范围外事项及断言责任主体，必须能从 catalog、typed contract 或评测权威文档反查。

- 每条断言必须对应目标结果、必要反事实或全局权限、隔离、幂等与副作用不变量。删除后不影响验收目的的断言属于冗余，须删除，或按真实失败边界纳入 Offline Eval 或 E2E 横切检查点，禁止另建单元套件。
- 优化用例只验收声明的变量与结果，不得追加未改变的 Plan、工具、委托、查询、调用次数、顺序、措辞、产物数量或内部状态要求。内部路径只能作为执行后证据或独立机制检查，除非它本身属于公开产品契约。
- 同一用例可以供多个横切套件复用。各套件只检查预声明的局部能力，整例用户结果、原始 `pytest_outcome` 和局部 verdict 必须分开。
- E2E 失败必须执行[QLT 阻塞处理](../docs/devSpec/quality-security.md#2-e2e-阻塞按目标阶段和单变量处理)。在 checksum 有效的 archive、report 或评测权威文档中保存 case id 和完整审查记录，不另建用例状态或发布清单。

合法 typed 终态与局部验收按[EVD 归因规则](../docs/devSpec/change-evidence.md#1-用户结果与工程约束的可执行基线)判断。预期成功交付的用例仍须按原始用户结果计分；后续独立失败不否定已成立检查点，但局部通过不能进入 Product E2E 成功分子或发布门禁。

## 4. 产品 E2E 与 grader 边界

Product E2E 的中文表达、自然输入、真实边界与 Test Double 限制继承根规范和 QLT；本节只规定 grader 的责任。

grader 必须在实现前固定版本、输入和结果契约，直接判断用户可观察结果与关键反事实。禁止用字符串包含、对象存在、工具调用或模型自述替代语义结果，也不得指定模型的内部执行策略来制造通过。

## 5. 比较身份与归档

每次执行生成独立、带 checksum 封印的 archive。历史 archive 只读，不得覆盖；baseline、适用消融或责任边界反事实、target 必须分别可还原。

本项目后续临时诊断脚本、隔离测试源码、来源快照、日志与证据归档统一保存到项目根目录的 `.tmp/<专题>-<日期>/`，不得继续向 `C:/pae` 新写文件。正式 E2E 和 Offline Eval 源码保存在 `evals/`；`tests/` 按根规范停用，禁止新增、维护、修复、收集和运行，也不得整体迁移后改名。运行前显式将适用的 `PERSONAL_AGENT_E2E_TRACE_DIR`、`PERSONAL_AGENT_PRODUCT_EVIDENCE_DIR` 或脚本输出根目录设为该目录下的独立子目录，不依赖旧默认路径；子进程同样遵守。历史归档只读保留，未迁移前不得仅改文档路径而伪装已经迁移。过程与经验持续写入 `docs/optimization/` 并与 Future 联动；`.tmp/` 已被 Git 忽略，不能作为唯一的经验记录。

- 保存用户输入、principal、正式入口、交互模式、初始事实、seed、环境与配置 cohort、代码身份、Prompt、模型与服务提供方版本、transport、schema、预算、fixture、grader 版本、重复次数、追踪记录、报告、最终结果和 checksum。
- 比较必须固定用户目标、输入、身份、入口、初始事实、评测契约及除声明变量外的条件。baseline 与 target 使用相同 seed；新设计消融只改变目标机制，不能同时更换 Prompt、Provider 或其他变量。
- 比较器必须拒绝 checksum 失效、role 错误、比较身份不一致，以及代码与配置身份完全相同的伪配对。不同 grader、Provider、transport、Prompt、预算、fixture 或 cohort 的历史结果不得合并。
- 性能比较必须固定用户目标、输入、Provider、模型、Prompt、预算、fixture 和 repetition。不同 case 或 cohort 的完成率、耗时、token、成本不得直接比较；声明变量改变这些条件时，必须新建比较设计，不能沿用旧性能身份。
- pytest 失败、internal error、usage error、调用异常和缺失报告都必须保留为 typed 失败。晋级器不得覆盖测试失败或将执行失败解释为用户结果类型。
- 横切报告同时保留 `pytest_outcome` 与独立检查点结果。检查只读取 checksum 有效且代码、配置、评测身份一致的密封 Trace；缺少用例、重复选择同一节点或跨身份拼接必须失败。
- 整例失败时，Tool Calling、MCP dispatch、Agent Artifact 返回等局部机制可以通过，但只有 catalog 预声明的关键事实可以独立于整例终态验收；局部通过不得由 `release_gate.py` 作为产品成功消费。

## 6. 运行与声明

运行前预声明指标门槛、样本量、重复次数、最大成本和停止条件；高成本或真实外部服务评测只在任务需要该证据时执行，不属于普通回归套件。

- 定向 target archive 只证明对应变更边界，不能替代完整 release matrix。dirty revision 必须记录 dirty digest；没有绑定目标 clean revision 的完整发布门禁时，不得声明 release-ready 能力集合。
- 保留失败的 trace、event、receipt、report 与 archive。禁止改写 grader 迎合失败、删除失败样本、只挑成功重跑或把不可用指标写成零。
- 报告分子、分母、样本量、方差或适用置信边界，并区分完成率、正确性、错误副作用、成本、延迟和恢复；不得只报百分比或单个成功例。

## 7. E2E 执行效率是评测设计门禁

提速只能减少评测开销，不能缩减证据契约。高成本 E2E 执行前必须完成 collect-only、impact routing 和成本估算；优先读取最近一份 checksum 有效且比较身份相符的 archive，预声明单样本与完整 cohort 的 wall time、token、外部调用成本和早停条件。没有历史数据时先执行最小独立 pilot，不得直接启动大样本循环。

出现以下任一信号，在当前原子样本安全结束后暂停新增样本并重审：

- 单样本超过 `60s`；cohort 预计超过 `10min` 或 `200,000` tokens；
- 同 profile 耗时超过最近有效基线两倍；
- 结论已数学上不可逆，或继续等待不能增加机制归因信息。

除非 runner 支持安全取消与 typed failure 归档，禁止中途强杀。重审先区分产品或服务方延迟与脚手架开销，再依次考虑：独立 pytest item 和 archive、预声明约束下的数学早停、历史耗时驱动的 fail-fast 顺序、impact map 最小 live selection、经过隔离证明的进程或 fixture 复用。不得先增加并发、缓存、mock 或全局状态复用。

- 开发迭代的 fail-fast、排序和定向 selection 必须保持完整 catalog collection、正式输入、生产预算和 grader，且明确不能替代发布证据。完整发布命令不得加入 `-x`、样本裁剪、低预算 profile 或测试旁路。
- promotion cohort 不得用 pytest `--maxfail` 绕过 typed 门禁。早停只能由预声明约束和已封存独立样本判定；局部良好结果不能提前通过，执行失败、缺 report 或成本超限必须进入分母并保持失败。
- 不得为提速降低用户结果门槛、模型或工具预算、重复次数与反事实覆盖，或替换结果依赖的真实边界。更换 Provider、Prompt、transport、grader 或 fixture 必须作为新评测设计与 cohort 重新准入。
- 每项提速改动保存重构前工程基线和重构后证据，报告完整收集数量、首个决策反馈时间、完整运行时间、实际执行与避免的样本数、token 与外部调用变化、回退行为，以及发布契约保持情况。未提速、覆盖下降或引入第二命令责任主体时，删除候选。
- evaluator、grader、文档及无生产影响的脚手架变更，使用相关 Offline Eval、历史 archive 只读回放和静态工程检查。仅在生产候选取得适用消融或责任边界反事实与定向 target、目标 clean revision 需要发布判断，或 Provider/Prompt 漂移需周期复核时，执行完整 release matrix。
- 新能力域优先复用既有正式 E2E 并读取同一 Trace。只有现有用例不能承载新的用户目标、入口、初始事实、故障边界或关键反事实时才新增 case；局部不变量重合不等于重复旅程。

收集、配对、promotion 与 release gate 命令由[运行、归档与发布](../docs/evals/04-running-and-release.md)唯一维护。
