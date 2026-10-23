# 任务与用例数据参考

**公开任务用于寻找有代表性的用户目标、输入材料和可检查结果，不能替代 personalAgent 的正式入口验证。** 本文拥有外部任务与数据的核查记录；本工程候选由各自 Spec 拥有，证据类别及验收由 [QLT](../devSpec/quality-security.md)和 [EVD](../devSpec/change-evidence.md)拥有。

2026-10-17 首批检索并下载以下 5 个项目的 20 个文件，核对了 4 个具体题目及 WorkArena 的任务生成、验证代码。固定版本、文件、字节数及校验和见[来源清单](../../.tmp/new-task-directions-20261017/source-manifest.json)，题目审计见[只读样本](../../.tmp/new-task-directions-20261017/task-audit.json)。新增长任务参考见第 2 节，具体 GitHub 事项材料见第 3 节，非代码业务任务见第 4 节。未运行第三方 Agent、用户模拟器或本工程 E2E；下载材料不计产品样本。

## 1. 已取得的任务和数据

| 来源与固定版本 | 具体任务与已取得材料 | 可借鉴的边界及限制 |
| --- | --- | --- |
| WorkArena `e885130962f61fb64ac305497996a46cfc7d18f0`，仓库 Apache-2.0 | [`EditKnowledgeBaseTask`](https://github.com/ServiceNow/WorkArena/blob/e885130962f61fb64ac305497996a46cfc7d18f0/src/browsergym/workarena/tasks/compositional/edit_knowledge_base.py#L129)生成正确与错误文章并要求处理；已取得含 100 项的知识素材、公司协议、重复工单任务及验证代码 | 适合参考有约束的维护任务。其“编辑”任务实际通过两篇文章的评论与交叉引用验收，未检查正文替换或本工程 Claim 生命周期；错误文章还使用 Faker 构造，不能称为真实维护事故。完整环境需 ServiceNow 实例及访问批准，本轮未取得或启动 |
| LongMemEval cleaned `98d7416c24c778c2fee6e6f3006e7a073259d48f`，数据卡 MIT | 已取得 [`longmemeval_oracle.json`](https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned/blob/98d7416c24c778c2fee6e6f3006e7a073259d48f/longmemeval_oracle.json)，解析 500 项，其中 `knowledge-update` 78 项；审计 `6a1eabeb` 的跨会话个人跑步纪录更新 | 提供时间、会话、问题、参考答案和证据会话身份。原任务是记忆问答，不能证明显式保存、纠错、删除和授权。当前只下载 oracle 版，它已选出证据会话，不能据此声称通过完整历史检索；正式候选应另取同版本完整历史，不把答案或证据会话标签交给 Agent |
| τ-bench `96a3ef92329baf908ffe9dfe188cea34e8701d2a`，仓库 MIT | 已取得 retail 的 114 项 [`tasks.json`](https://github.com/sierra-research/tau2-bench/blob/96a3ef92329baf908ffe9dfe188cea34e8701d2a/data/tau2/domains/retail/tasks.json)、政策及评测源码；任务 `0` 要求同一订单两件商品换货，并指定键盘偏好及替代条件 | 适合参考多对象执行、澄清和业务终态。领域初始数据库本轮未下载；参考动作仅用于评分端产生目标状态。[环境评测器](https://github.com/sierra-research/tau2-bench/blob/96a3ef92329baf908ffe9dfe188cea34e8701d2a/src/tau2/evaluator/evaluator_env.py#L85)分别恢复预测环境与参考环境后比较状态。评分开关须逐题核实，任务 `0` 为 `DB` 与 `NL_ASSERTION`，不能仅依据概述套用统一评分。客服领域和模拟环境不等于个人知识场景 |
| MathDial `acc3878459e0bd8c04ab840056572f0b8b1abe1f`，数据卡 CC-BY-4.0 | 已取得 [`test.jsonl`](https://huggingface.co/datasets/eth-nlped/mathdial/blob/acc3878459e0bd8c04ab840056572f0b8b1abe1f/test.jsonl)及字段说明；审计 `qid=6000025`：学生在勺子数量题中把已使用数量的加减关系弄反，数据包含错解、误区标注、正确解及师生对话 | [原论文 v2](https://arxiv.org/abs/2305.14536v2)说明由真人教师与模拟学生对话构建。可参考错误诊断和有效提示，不能只按最后数字正确评分。正确解及后续对话留在评分端；单题对话不能直接证明跨任务训练、技术面试辅导或真实学习收益 |
| DABstep `523e6627415c6ebafa0954ce0df9cd93b6c0914d`，数据卡 CC-BY-4.0 | 已取得 [`dev.jsonl`](https://huggingface.co/datasets/adyen/DABstep/blob/523e6627415c6ebafa0954ce0df9cd93b6c0914d/data/tasks/dev.jsonl)的 10 项开发题、支付列说明及业务手册；任务 `5` 比较发卡国家的交易笔数 | 可补研究内的文件分析用例。`payments.csv` 本轮未下载或计算；[字段说明](https://huggingface.co/datasets/adyen/DABstep/blob/523e6627415c6ebafa0954ce0df9cd93b6c0914d/data/context/payments-readme.md)明确称其为合成支付数据，不能因介绍强调实际工作负载就将材料记为真实交易。题目答案只覆盖原问题，不自动验收报告、产物和后续保存 |

仓库许可证和数据卡许可分别记录，未据此推断外部平台账户、所有上游素材或衍生发布具有同一许可。其他仅检索到概述、未核对具体任务和输入的数据集不进入已取得清单。

## 2. 新增长任务方向的任务与源码

2026-10-17 继续核查 AppWorld 与 TheAgentCompany，下载 17 个公开文件，固定提交和校验和见[本轮来源清单](../../.tmp/task-capability-fit-20261017/source-manifest.json)。范围包括任务装载与评分源码，以及 3 个具体任务的说明、检查点和评测器；未安装运行环境或下载完整任务数据库。

| 来源与固定版本 | 核实内容 | 适用方向与取舍 |
| --- | --- | --- |
| AppWorld `42b5bcf3cd334fee33f0c37c02070a9f5807add5` | [`Task.load()`](https://github.com/StonyBrookNLP/appworld/blob/42b5bcf3cd334fee33f0c37c02070a9f5807add5/src/appworld/task.py#L94)读取题目、时间、用户和任务数据库；[`evaluate_task()`](https://github.com/StonyBrookNLP/appworld/blob/42b5bcf3cd334fee33f0c37c02070a9f5807add5/src/appworld/evaluator.py#L452)装载初始与执行后数据库，再交给本题评分逻辑 | 可参考跨应用事务与结果状态检查。完整材料通过单独的数据 bundle 分发，本轮未取得单题的完整世界，不能称为已准备可运行用例。仓库公开代码 Apache-2.0，README 对加密 bundle 的再分发另有条款；不能把仓库许可直接外推全部数据。`Task.load()` 默认加载评分真值，Agent 接入时须隔离真值及私有测试材料，不能把整个任务对象无差别交给模型 |
| TheAgentCompany `98b68ef82a47690c316f42fddb05baafaab56851`，仓库 MIT：[`pm-ask-issue-assignee-for-issue-status-and-update-in-plane`](https://github.com/TheAgentCompany/TheAgentCompany/blob/98b68ef82a47690c316f42fddb05baafaab56851/workspaces/tasks/pm-ask-issue-assignee-for-issue-status-and-update-in-plane/task.md) | 从 Plane 查负责人，在 RocketChat 核实事项状态，完成时才更新看板；已读取同目录评测器 | 可参考“取证影响写入”的跨应用依赖。评分器只检查存在私聊记录及事项完成态，不能独自证明问对问题、消费了回复或有依据关单。本工程改编需检查依据与终态的因果关系；该小任务本身也不证明长任务接续 |
| 同一 TheAgentCompany 提交：[`sde-debug-crashed-server`](https://github.com/TheAgentCompany/TheAgentCompany/blob/98b68ef82a47690c316f42fddb05baafaab56851/workspaces/tasks/sde-debug-crashed-server/task.md)、[`sde-copilot-arena-server-new-endpoint`](https://github.com/TheAgentCompany/TheAgentCompany/blob/98b68ef82a47690c316f42fddb05baafaab56851/workspaces/tasks/sde-copilot-arena-server-new-endpoint/task.md) | 分别要求诊断并修复崩溃服务，及增加可实际调用的新接口；取得题面、检查点和 HTTP 评测器 | 可参考工程交付的环境准备、修改、运行与服务级检查。评分器仍有覆盖限制：崩溃任务只探测特定 `/events` 内容；新接口任务只检查部分输出，没有完整断言所有返回项及零外部 API 调用。不能以其局部通过宣称完整故障修复或符合全部需求 |

上述项目提供可审计的模拟应用或公司任务，不等于本工程已经连接真实业务系统。多应用数、多动作数及局部检查点不单独证明长任务；本工程仍需选定完整目标、真实依赖、成果交接和结束判据。只运行第三方 Agent 不证明 personalAgent；通过本工程正式链访问模拟服务时，也只报告相应模拟域证据，真实目标服务接入另行验收。

## 3. DeepAgents 上游事项的具体材料

2026-10-17 为跨应用项目执行核查 [`langchain-ai/deepagents`](https://github.com/langchain-ai/deepagents)。它的公开记录同时包含局部修复、方案未采用和产品层修复，适合检查 Agent 是否分清处理结论及适用组件。这里不是引用一个既有 benchmark，也不是本工程真实用户的迭代记录；隔离工作台与外部事务候选按[当前范围取舍](../optimization/to_verify/non-research-task-directions.md#5-已比较但不推进的方向)不再推进，来源事实仍保留。

| 材料 | 本轮直接核实的事实 | 用于区分的问题 |
| --- | --- | --- |
| [issue #927](https://github.com/langchain-ai/deepagents/issues/927)与 [PR #994](https://github.com/langchain-ai/deepagents/pull/994) | #927 报告非法文件路径导致运行中止，已关闭为 `completed`；#994 于 2026-02-02 合并，修改文件系统工具的路径异常处理。PR 直接写 `Closes #728`，#927 与 #994 的关系另外由后续讨论及 #5356 说明支持，不能伪称 #994 的自动关单目标就是 #927 | 文件系统路径错误被处理，不等于所有工具异常都被统一处理 |
| [issue #5356](https://github.com/langchain-ai/deepagents/issues/5356)、[维护者回复](https://github.com/langchain-ai/deepagents/issues/5356#issuecomment-5257811491)与 [PR #5417](https://github.com/langchain-ai/deepagents/pull/5417) | #5356 于 2026-08-11 关闭为 `not_planned`；维护者建议按需加入错误或重试中间件；#5417 已关闭，`merged_at=null`。其 `merge_commit_sha` 非空也不能证明已合并 | issue 关闭、PR 关闭、作者声称测试通过，都不能替代“方案已合入”的事实 |
| [issue #5952](https://github.com/langchain-ai/deepagents/issues/5952)与 [PR #5954](https://github.com/langchain-ai/deepagents/pull/5954) | #5952 在 #5954 中作为 `completed` 关闭；PR 于 2026-08-28 合并到 `e0a474fed575992abc991f6a8049cc8e18e328c0`。实际补丁在 `libs/code/deepagents_code/agent.py` 的 dcode 装配中添加仅处理 `task` 的 `ToolErrorMiddleware` | dcode 的并行子任务隔离不能外推 SDK 默认行为，也不等于接入项目已经完成验证 |

固定到 `e0a474fed575992abc991f6a8049cc8e18e328c0` 核对了 [SDK 装配](https://github.com/langchain-ai/deepagents/blob/e0a474fed575992abc991f6a8049cc8e18e328c0/libs/deepagents/deepagents/graph.py#L816)、[文件路径处理](https://github.com/langchain-ai/deepagents/blob/e0a474fed575992abc991f6a8049cc8e18e328c0/libs/deepagents/deepagents/middleware/filesystem.py#L1780)与 [dcode 装配](https://github.com/langchain-ai/deepagents/blob/e0a474fed575992abc991f6a8049cc8e18e328c0/libs/code/deepagents_code/agent.py#L3255)。结论限于该提交及所列事件，不称为最新版本行为。未运行上游代码或测试。

本轮取得 7 份 REST 响应、5 份网页或补丁及 3 份固定版本生产源码，共 15 个文件，URL、取得时间、字节数和 SHA-256 见[原始来源清单](../../.tmp/concrete-github-task-20261017/source-manifest.json)。后续 REST 请求返回 403，#5952／#5954 改用公开网页与实际补丁核实；未取得完整 CI API 结果和 required-check 配置。#5954 页面显示 80 checks passed，仅记录为页面摘要；不能把 #994 的合并或作者的测试清单写成必要 CI 已通过，也不据此设置缺乏证据的 CI 门槛。

材料在工作台中只使用中文摘要、来源链接和必要身份，不批量复制上游评论、个人信息或测试内容；仓库代码许可不被外推为全部 issue 文本的许可。原始下载留在本地证据目录。工作台初始状态、错误知识与新增接入验证要求均明确标为本工程构造，不声称来自上游真实会议或真实用户。

## 4. 非代码业务场景的具体任务

2026-10-17 继续按“用户得到什么结果、哪些判断依赖新信息、能否独立验收”筛选非代码任务。本轮新增取得 43 个文件，复用同版本缓存 6 个，共 49 个有效文件；含 TheAgentCompany 的 11 项任务说明及评测器、3 份 NPC 场景，以及 τ-bench 的任务、初始数据库、政策和实际工具源码。固定版本沿用本页所列 TheAgentCompany 与 τ-bench 提交，逐文件 URL、时间、字节数与 SHA-256 见[来源清单](../../.tmp/noncoding-scenarios-20261017/source-manifest.json)，具体任务及评分审计见[只读审计](../../.tmp/noncoding-scenarios-20261017/candidate-audit.json)。两条猜测的 telecom 路径返回 404，已按 `utils.py` 取得实际 TOML 数据与政策；不计为有效文件。未安装或运行应用环境。

| 具体来源 | 取得及核实内容 | 能支撑的场景与证据限制 |
| --- | --- | --- |
| TheAgentCompany [`admin-check-employees-budget-and-reply-and-record`](https://github.com/TheAgentCompany/TheAgentCompany/blob/98b68ef82a47690c316f42fddb05baafaab56851/workspaces/tasks/admin-check-employees-budget-and-reply-and-record/task.md) | 收集两个部门共 4 人的设备需求，读取价格，按部门 10,000／5,000 的预算反馈，超支时联系该部门人员削减并记录变化；已读同目录 `scenarios.json` 与 `evaluator.py` | 能参考“获取需求→计算→协商→消费新回复→重新收敛”的业务依赖。NPC 的后续策略只给模拟器／评分端，不能直接给 Agent。原评分器检查私聊存在、初始金额和固定削减组合，金额注释还混淆鼠标与键盘；它不完整验收实际同意、最终预算及其他合法方案。`products.pdf` 与完整 OwnCloud／RocketChat 数据本轮未取得，不能称为已准备可运行世界或已完成采购 |
| τ-bench retail [`tasks.json`](https://github.com/sierra-research/tau2-bench/blob/96a3ef92329baf908ffe9dfe188cea34e8701d2a/data/tau2/domains/retail/tasks.json)，任务 `30` | 已解析全部 114 题，取得完整 `db.json`、政策与工具源码；题目要求先给平板运单号，同款可换则换、不可换则退；只有退平板时才取消配套充电器，另退运动鞋。已核对该平板原规格库存为 false | 能参考有条件依赖的多订单售后。原任务 `communicate_info` 写了运单号，`reward_basis` 却为 `DB, NL_ASSERTION` 且语义判据为空，不能以原总分证明运单号已交付。[退货工具](https://github.com/sierra-research/tau2-bench/blob/96a3ef92329baf908ffe9dfe188cea34e8701d2a/src/tau2/domains/retail/tools.py#L709)只设为 `return requested`，不证明实物已寄回或退款已结算。[换货政策](https://github.com/sierra-research/tau2-bench/blob/96a3ef92329baf908ffe9dfe188cea34e8701d2a/data/tau2/domains/retail/policy.md#L128)只支持同产品不同规格，不能仅改原 SKU 库存就构造“同 SKU 换同 SKU”成功变体 |
| τ-bench airline [`tasks.json`](https://github.com/sierra-research/tau2-bench/blob/96a3ef92329baf908ffe9dfe188cea34e8701d2a/data/tau2/domains/airline/tasks.json)，任务 `42` | 已解析全部 50 题，取得完整 `db.json`、政策与工具源码；用户只确定 5 月 17 日由 Dallas 到 New York、5 月 22 日由 Boston 离开，要求识别误订并保留给其他乘客订的行程。参考取消对象为 `FDZ0T5`、`HSR97W`，原库均存在 | 能参考地点、时间、乘客与取消权限的联合约束。参考对象只由评分端持有；Agent 从真实订单读取判断。原评分使用 `DB, COMMUNICATE`，但该题沟通判据为空；本工程仍需独立检查取消依据、保留对象和最终交付。原世界的日期与政策保持固定，不当作当前真实航班信息 |
| τ-bench telecom [`tasks.json`](https://github.com/sierra-research/tau2-bench/blob/96a3ef92329baf908ffe9dfe188cea34e8701d2a/data/tau2/domains/telecom/tasks.json)，选定 `[mobile_data_issue]data_mode_off\|data_usage_exceeded\|user_abroad_roaming_disabled_off[PERSONA:Hard]` | 已完整解析 2,285 题，取得服务侧及设备侧初始 TOML、政策、排障手册及两侧工具。该题要求恢复移动数据与模拟器的 excellent 速度，可补充 2 GB，不换套餐；评分使用服务状态、速度及补充量的 `ENV_ASSERTION` | 能参考多原因诊断、人机协作、修改后复测。故障 ID、初始化动作和参考修复留在准备／评分端。客服 Agent 有服务提供方权限，用户只操作设备；个人助理不能冒充运营商改套餐或开服务。速度是模拟器状态，不是实测网络指标；原断言也未完整覆盖套餐不变等限制 |

另核对了几类容易高估的任务：`finance-expense-validation` 与 `finance-invoice-matching` 主要交付表格和分析；`finance-qualified-bill-ask-for-reimburse` 只要求计算可报金额并告知一人；`admin-arrange-meeting-rooms` 计算最少会议室并发送答案，并未订房；`pm-schedule-meeting-1` 只收集可用时间并写结论，评测真值是本周无法排期，没有日历落地。这些原题不能被描述为完成报销申报或活动组织。`admin-get-best-vendor-quote` 有需求澄清、报价筛选与共享文件，可参考采购前段，但没有实际下单。

以上均为公开模拟域任务，不是本工程真实用户的采购、售后或差旅记录。数据可取得与业务价值是两项判断；当前只能说明任务有具体目标和可审计材料，不能据此声称节省了多少时间或费用。这些外部事务按[当前范围取舍](../optimization/to_verify/non-research-task-directions.md#5-已比较但不推进的方向)不再推进，不将其旧准备规格当作活动产品路线。

## 5. 知识材料修订的具体来源

2026-10-17 按尽量不过度扩展的要求，转向个人知识附近的方案共创、材料审校与定向修订。取得 23 个源码、元数据及数据文件，固定提交、下载时间、ETag、字节数和 SHA-256 见[来源清单](../../.tmp/adjacent-knowledge-scenarios-20261017/source-manifest.json)。本轮没有运行第三方模型、编辑应用或本工程产品 E2E。

| 来源 | 实际取得与核查 | 可参考范围与限制 |
| --- | --- | --- |
| [ARIES](https://github.com/allenai/aries/tree/5691bae71a101225ed345d0ffc42e47609f03bbb)，代码提交 `5691bae71a101225ed345d0ffc42e47609f03bbb` | 已下载评论、论文编辑映射、196 条测试对齐记录、197 条人工评估记录、全文解析归档及许可；解析 4,088 条评论，从归档取出 3 组论文前后版本。真实个案审计见[主样本](../../.tmp/adjacent-knowledge-scenarios-20261017/aries-case-audit.json)与[补充核查](../../.tmp/adjacent-knowledge-scenarios-20261017/text-cases-audit.json) | 数据为 ODC-BY 1.0，代码为 Apache-2.0；训练／开发中的合成对齐不能冒充全人工标注。评论与 edit 对齐不是完整修订成功判据，作者新版不是唯一合法答案，新增实验不能由仅有原稿的模型补造 |
| ARIES `doc_id=o2UwRc8fbXI, comment_id=7` | 原稿 `jLPxR50Zq3` 第 48 段声称改进可解释性，评审要求说明或删除；对应标签为 edit `41`，作者新版 `Vc2tetE2ZF` 第 42 段补入实验与附表。已核对原文、评论、标签和实际新版 | 可作为缺证断言与反馈消费的真实素材。受限改稿须明确改编要求，例如用户本次只允许删除／限定，不做新实验；不可将作者新增实验写成 Agent 已完成，原新版和标签留在评分端 |
| ARIES `nLb60uXd6Np/7`、`2234Pp-9ikZ/3` | 分别询问术语和函数定义，已取得其原稿及新版；原测试对齐的 `positive_edits` 均为空 | 不能只因评论看似适合文字澄清，就声称数据中有已完成的对应修订；可作需进一步判断的材料，不作正向成功金标 |
| [Open Canvas](https://github.com/langchain-ai/open-canvas/tree/0310cecd51f31b3d37a52d6d1060137da3405280)，提交 `0310cecd51f31b3d37a52d6d1060137da3405280` | 已读[实际图装配](https://github.com/langchain-ai/open-canvas/blob/0310cecd51f31b3d37a52d6d1060137da3405280/apps/agents/src/open-canvas/index.ts)、[局部修订](https://github.com/langchain-ai/open-canvas/blob/0310cecd51f31b3d37a52d6d1060137da3405280/apps/agents/src/open-canvas/nodes/updateHighlightedText.ts)及整稿重写。局部节点把当前稿、选中块及用户输入送模型，再拼接并追加一版 artifact | 是实际可定位的改稿实现，仓库已归档；借鉴任务与产物持续交互，不照搬整套图或前端。`includes`／字符串替换不能证明定位唯一、版本有效或未选原文保真，也不证明来源正确和长任务收益 |

官方数据文件没有 Git 提交身份，以本次完整文件摘要及发布对象的 ETag／时间固定。OpenReview 页面访问遇到浏览器验证，本轮未通过页面取证；前后版本来自作者公开的 ARIES 数据归档，来源渠道分别记录。CoAuthor 另检索到真实协作写作会话介绍，但未下载其会话文件，不列为本轮已取得完整输入。

相邻场景的正式范围与验收由[场景 Spec](../optimization/to_verify/non-research-task-directions.md)拥有。本文只支持“存在具体反馈、原稿和改稿实现”，不能证明 personalAgent 已完成这项工作；本仓库中的 Codex 编辑也不替代正式入口的产品验证。

## 6. 转为本工程用例的方式

先按数据可取得性、结果可判断性和本工程目标选择少量代表任务，再确定是否扩展能力；不能先包一个新 Agent，再找题证明它必须存在。

1. 固定原任务 ID、版本、许可、原始文件和校验和，记录哪些输入完整取得、哪些只读了样例。保留原任务结果与本工程扩展要求的边界，公开或合成数据不冒称真实用户记录。
2. 中文化时核对事实、时间、条件及成功标准。新增“先预览再确认”“生成文件”等要求时，登记为本工程改编场景；原 benchmark 分数与本工程结果分开，不能沿用其原样本身份。
3. 材料、身份和初始状态可以作为用例前置事实，经正式入口准备。答案、参考动作、证据标签、后续标准对话及预期工具参数只由评测持有；不能替模型选择对象、补全计划或注入中间结果。
4. 用户自然表达经生产入口、真实模型及实际执行链推进；后续交互消费同一轨迹的真实提议、回执和产物。完整历史检索不能用 oracle 证据选择代替，用户的自然反馈也不能由脚本代替 Agent 决策。
5. 用户结果、必要副作用及禁止变更分别断言；维护任务检查实际有效知识和后续使用，事务任务检查业务终态，辅导任务检查反馈是否忠实于实际作答。默认允许满足相同契约的合法执行路径，不把参考工具顺序变成唯一正确答案。

首批只形成候选与数据准备，实际样本数、预算、正式入口、评分校准及停止条件在对应 Spec 中固定。可公开复现的任务提高可审计性；贴近目标用户的真实材料仍需单独确认，二者不能相互冒充。

## 7. 个人上下文事项执行与时间变化任务

2026-10-18 根据部署痛点继续检索，核查个人历史是否影响后续动作、事项是否实际完成，以及环境独立变化时如何等待。产品取舍由[唯一场景 Spec](../optimization/to_verify/non-research-task-directions.md)拥有；本节只记录已取得资料及证明边界，未运行模型、用户模拟器或应用环境。

| 来源与固定身份 | 实际取得与核实 | 适用范围与限制 |
| --- | --- | --- |
| π-Bench `4f545be5d289b28ff022d2904d455007358ed3b7`，已取得 Apache-2.0 LICENSE | 取得 researcher 的 20 项 `task.yaml` 及 `profile.yaml`、`episode.yaml`，共 22 个数据文件；已核对 [任务 009](https://github.com/Simplified-Reasoning/Pi-Bench/blob/4f545be5d289b28ff022d2904d455007358ed3b7/data/researcher/tasks/researcher_task_009/task.yaml)的履历匹配请求及地点、通勤、研究方向等七项隐藏约束 | 能参考个人约束恢复与针对性消歧。题面要求 `cv.txt`，本轮未下载该文件，也未确认每项隐藏约束在前序历史中的可恢复性；不能把标签直接交给模型、声称已备齐用例或证明招聘申请已执行。题目标记 `long_term` 也不能代替本工程的实际依赖判定 |
| MyPCBench `937ec49882508223c7ea3f79ead3330c6810feb1`，已取得 MIT LICENSE | 解析 [`all_tasks_with_grading.json`](https://github.com/ljang0/MyPCBench/blob/937ec49882508223c7ea3f79ead3330c6810feb1/tasks/final/all_tasks_with_grading.json)的 184 项题目；重点审计 `hard_app-f033`、`long_horizon-f025`、`long_horizon-f055` 的题面及实际 rubric；另取变量、分类与 persona 元数据 | 上游将匿名请求改写到合成人物及应用，能参考需求类型，不能声称是真实用户完整记录。仓库为 runner、任务和元数据，应用构建源与初始数据库不在仓库；VM 本轮未取得或启动，无法直接复现世界。网页、论文与固定提交的总 rubric 数不同，不混用统计 |
| MyPCBench `hard_app-f033` | 用户要求先检查下一周四的实际冲突，有冲突才移动带指定参会人的工作会议，保护前后 15 分钟缓冲，并更新邀请及沟通；原题含无冲突分支 | 能参考有条件变更和实际状态核对。原 rubric 主要按截图与轨迹判断，明确以 UI 显示为准；它不能替代真实提供方的状态、邀请语义和本工程完整结果检查 |
| MyPCBench `long_horizon-f055`、`long_horizon-f025` | 前者跨项目记录、沟通、邮件等七应用准备自评并安排一对一；后者根据群聊和联系人筹备活动、拟邀约、安排日程并记计划 | 能参考“资料决定内容与对象，内容进入实际安排”的依赖。裁减应用、替换项目材料或增加确认要求属于本工程改编；不能把更小场景按原题得分，也不能把多应用数量当长任务证明 |
| SentinelBench `0faca33cc58ea62e97a928b67cd3beec7176b408`，已取得 MIT LICENSE | 取得 [notifications 题](https://github.com/microsoft/sentinel_environments/blob/0faca33cc58ea62e97a928b67cd3beec7176b408/scenarios/microlendar/description-notifications-absolute-active.json)、Hawaii 题、两个 no-op 题及 [`microlendar` 服务处理源码](https://github.com/microsoft/sentinel_environments/blob/0faca33cc58ea62e97a928b67cd3beec7176b408/server/handlers/microlendar.py)。notifications 题在 `68.09` 秒新增目标事件，Agent 需打开说明识别 | 支持独立时间轴、条件未出现和非目标事件的参考。该题 `eval_sql` 只检查目标事件 `isViewed`，不证明完整通知或日程修改；不能据此声称已验证事项看护。原应用与事件时间为合成，未证明当前后台需求或生产恢复机制 |

固定来源、字节数与 SHA-256 见 [π-Bench 清单](../../.tmp/agent-pain-scenarios-20261018/pi-source-manifest.json)、[Git 读取清单](../../.tmp/agent-pain-scenarios-20261018/extracted-source-manifest.json)，题目及评分审计见[核查记录](../../.tmp/agent-pain-scenarios-20261018/task-audit.json)。许可证只按已取得范围说明，不外推虚拟机、应用素材或匿名原始请求的全部再分发权。

GitHub REST 在取得 π-Bench tree 后返回 403 rate limit，后续两个仓库改用只读 Git 获取固定身份；未绕过访问控制。MyPCBench 网页 `tasks.json` 路径返回非 JSON，未作为有效题库，实际解析来自上述固定 Git 文件。两项访问限制不记作产品失败，也不因此推断环境不可运行。

## 8. BEIR/SciFact 检索实验材料

2026-10-18 为[公开检索方案复现实验候选](../optimization/to_verify/knowledge-decision-delivery.md#21-首个用例公开检索方案复现实验)取得 8 个 BEIR 源文件、4 个数据文件、2 份数据卡，以及向量模型元数据和模型卡。固定 URL、提交及 SHA-256 见[来源清单](../../.tmp/retrieval-experiment-scenario-20261018/source-manifest.json)，完整数据的结构与引用检查见[数据审计](../../.tmp/retrieval-experiment-scenario-20261018/dataset-audit.json)。只进行下载、读取和结构审计，未执行检索、下载模型权重、调用模型或运行产品 E2E。

**数据来源有正式学术依据，Agent 任务规格由本工程设计。** SciFact 由华盛顿大学与 Allen Institute for Artificial Intelligence 团队发布，对应 [EMNLP 2020 论文](https://aclanthology.org/2020.emnlp-main.609/)及[原始仓库](https://github.com/allenai/scifact/tree/68b98a56d93e0f9da0d2aab4e6c3294699a0f72e)。原任务包含 1,409 条专家编写的科学声明及摘要证据、关系和理由标注。BEIR 将其纳入统一检索格式，对应 [NeurIPS 2021 Datasets and Benchmarks 论文](https://datasets-benchmarks-proceedings.neurips.cc/paper/2021/hash/65b9eea6e1cc6bb9f0cd2a47751a186f-Abstract-round2.html)。本工程实际使用 BeIR 发布的下述固定 Hugging Face 数据文件；相关性标注服务于检索评分，不能直接作为科学声明真实性或完整回答正确性的标签。

原始划分与 BEIR 命名须分开。[BEIR 论文 v4 附录 D.9](https://arxiv.org/pdf/2104.08663v4)明确：SciFact 的 300 条原始公开 dev 查询被用作 BEIR test；它不是 SciFact 隐藏测试集。本工程可在本次运行中隔离这些标注，但不能宣称模型从未见过它们。当前固定文件的查询／相关性记录数按本地审计解释，不混用原始声明总数、证据条目数或论文其他版本统计。

中文研究请求、实验推进、报告交付、进程中断和 Harness 对照均为本工程自建规格，未取得外部基准对这些 Agent 行为的参考答案或终态评分。应描述为“基于 BEIR/SciFact 材料构建的研究交付 E2E”，不能称“官方 Agent 长任务 benchmark”。原始材料与标注有可追溯出处，不替代本工程的真实整链验收，也不等于已逐条复核标注正确性。本轮重新校验原清单 16 个文件的 SHA-256，均一致；核查记录见[来源复核](../../.tmp/retrieval-data-provenance-20261018/authority-review.json)。

| 来源与固定身份 | 实际核实内容 | 适用限制 |
| --- | --- | --- |
| [BEIR](https://github.com/beir-cellar/beir/tree/ef83d29307061c65d04b035b4f4e7c18bd8374af)，`ef83d29307061c65d04b035b4f4e7c18bd8374af`，取得 Apache-2.0 LICENSE | [GenericDataLoader](https://github.com/beir-cellar/beir/blob/ef83d29307061c65d04b035b4f4e7c18bd8374af/beir/datasets/data_loader.py)按 qrels split 筛选查询；[EvaluateRetrieval](https://github.com/beir-cellar/beir/blob/ef83d29307061c65d04b035b4f4e7c18bd8374af/beir/retrieval/evaluation.py#L14)调用检索器并使用 `pytrec_eval` 计算 NDCG、MAP、Recall 与 Precision。2026-10-20 补核：默认 `k_values=[1,3,5,10,100,1000]`，`top_k=max(k_values)` 实际传给 `retriever.search()`，不能把默认行为描述成 top-100 | 它是检索基准及执行代码，不是 Agent 长任务 benchmark；只运行它不能证明 personalAgent。指标实现以实际返回的评分集合求平均，本工程候选须另检查所需查询集合完整，不能静默漏查后缩小分母；本轮未修改或运行该实现 |
| 同一 BEIR 提交的 BM25 及 dense 示例 | [BM25 示例](https://github.com/beir-cellar/beir/blob/ef83d29307061c65d04b035b4f4e7c18bd8374af/examples/retrieval/evaluation/lexical/evaluate_bm25.py)直接使用 test；[BM25Search](https://github.com/beir-cellar/beir/blob/ef83d29307061c65d04b035b4f4e7c18bd8374af/beir/retrieval/search/lexical/bm25_search.py)在 `initialize=True` 时删除并重建指定 Elasticsearch 索引，零命中查询可能没有结果键；其搜索传 `top_hits=top_k+1` 排除相同 query／doc ID，但本方法没有将剩余结果再截到 `top_k`。2026-10-20 补核的 dense exact 路径则用有界 heap 保留至多 `top_k`；[dense 示例](https://github.com/beir-cellar/beir/blob/ef83d29307061c65d04b035b4f4e7c18bd8374af/examples/retrieval/evaluation/dense/evaluate_sbert.py)使用 TREC-COVID、Stella 模型及 `trust_remote_code=True` | 示例不能原样执行本例：数据、模型、开发／test 协议及资源范围均须按获准配置绑定；排名字典不能独自证明完整执行。当前 Parquet 不是 `GenericDataLoader` 的直接 JSONL 输入，基础依赖和环境尚未准备 |
| 同一提交的向量实现，2026-10-19 补读 3 个文件 | [SentenceBERT](https://github.com/beir-cellar/beir/blob/ef83d29307061c65d04b035b4f4e7c18bd8374af/beir/retrieval/models/sentence_bert.py)委托 `SentenceTransformer` 编码查询及文档；[DenseRetrievalExactSearch](https://github.com/beir-cellar/beir/blob/ef83d29307061c65d04b035b4f4e7c18bd8374af/beir/retrieval/search/dense/exact_search.py)分块编码并用 cosine／dot 排序；另补读 Elasticsearch 适配实现，身份见[本轮来源清单](../../.tmp/experiment-program-design-20261019/source-manifest.json) | 只核实代码调用链，未运行或证明与本工程环境兼容；本工程候选程序及输入输出由[研究 Spec](../optimization/to_verify/knowledge-decision-delivery.md#执行哪份程序及输入输出)拥有，不能把外部库已有算法归功于 Agent 决策 |
| [BeIR/scifact](https://huggingface.co/datasets/BeIR/scifact/tree/b3b5335604bf5ee3c4447671af975ea25143d4f5)，`b3b5335604bf5ee3c4447671af975ea25143d4f5` | 实际解析 corpus 与 queries Parquet：5,183 个唯一文档、1,109 个唯一查询，保留 `_id`、`title`、`text` | 英文科学检索材料，不代表中文个人知识库或完整 RAG 回答效果。镜像数据卡声明 CC-BY-SA-4.0，BEIR 论文附录 E 的 SciFact 声明为 CC-BY-NC-2.0；声明差异尚未解决，不用镜像元数据替代上游许可核对 |
| [BeIR/scifact-qrels](https://huggingface.co/datasets/BeIR/scifact-qrels/tree/2938d17dc3b09882fdb8c12bbbe2e2dc0e75a029)，`2938d17dc3b09882fdb8c12bbbe2e2dc0e75a029` | 实际解析 train 的 919 条相关性记录／809 条查询，test 的 339 条／300 条；分数均为 1，split 查询无交集，引用均存在且无重复 query/doc 对 | train 可用于开发诊断，test 标注只交给受控评分端；公开数据的运行隔离不等于未见数据或排除训练污染，不能用测试集反复选配置 |
| [all-MiniLM-L6-v2](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2/tree/1110a243fdf4706b3f48f1d95db1a4f5529b4d41)，`1110a243fdf4706b3f48f1d95db1a4f5529b4d41` | 取得官方模型卡与元数据，模型卡说明英文 Sentence Transformers 模型及 Apache-2.0 声明 | 只作为已命名的向量候选；权重未下载，质量、资源占用和与 BM25 的胜负均未测得 |

BEIR README 指向的原始 `scifact.zip` 下载遇到 TLS 证书链校验失败，本轮保留[访问限制](../../.tmp/retrieval-experiment-scenario-20261018/download-limitations.json)，未关闭证书验证；实际完整材料来自上述官方 BeIR Hugging Face 固定镜像，不声称取得原始 ZIP 或证明两种封装字节相同。主场景推荐及验收由对应 Spec 拥有，本节不新增实验或产品成绩。

### 8.1 评估标准与有效性证据

**原始 SciFact 评科学证据识别，BEIR/SciFact 评相关文献排序，两者的标准答案含义不同。** SciFact 在摘要层及句子层报告 Precision、Recall 和 micro-F1；包含标签的指标要求支持／反驳关系正确，要求 rationale 的摘要指标还须包含一个完整的 gold 证据句集合。作者的[公开评分实现](https://github.com/allenai/scifact-evaluator/blob/66feffc5b2cc9e28e3ce3b8c9e824c3c642981eb/evaluator/eval.py#L139)直接比对原始标签与证据句，不依赖 LLM Judge。

[原论文 §3.3](https://aclanthology.org/2020.emnlp-main.609.pdf)对 232 个声明—摘要对进行独立复标，关系标签 Cohen's κ 为 0.75，证据句归属 κ 为 0.71。这是原始证据标注的一致性依据，不证明所有标注无误，也不是 BEIR 检索 qrels 的独立复标统计。

2026-10-18 取得原作者下载脚本指向的公开 `data.tar.gz`，与已固定的 BEIR qrels 逐对核对。原包为 3,115,079 bytes，SHA-256 为 `11c621288d41ac144d29b13b0f8503b3820b7d6e8b1f6ff24dff335c196d76be`；[审计结果](../../.tmp/retrieval-evaluation-criteria-20261018/qrels-audit.json)及[复算脚本](../../.tmp/retrieval-evaluation-criteria-20261018/audit_qrels.py)保留来源与集合比较。

| 原始划分 → BEIR 划分 | qrels 文献对 | 原始 `cited_doc_ids` 文献对 | 原始 `evidence` 文献对 | 逐对核对 |
| --- | ---: | ---: | ---: | --- |
| train → train | 919 | 919 | 564 | qrels 等于被引文献集合，额外包含 355 个未列入 evidence 的文献对 |
| dev → test | 339 | 339 | 209 | qrels 等于被引文献集合，额外包含 130 个未列入 evidence 的文献对 |

原始 dev 的 112 条 NOINFO 查询也包含在 BEIR test 中，对应 113 个相关文献对。作者[字段说明](https://github.com/allenai/scifact/blob/68b98a56d93e0f9da0d2aab4e6c3294699a0f72e/doc/data.md#L59)区分“来源引用句所引文献”与“摘要实际含有证据的文献”。本版本 qrels 应解释为指定的相关被引文献，不把额外文献对认定为上游标错，也不将找回它们等同于正确核验科学声明。

[BEIR 论文 §3.3](https://arxiv.org/pdf/2104.08663v4)以 nDCG@10 为主要指标，并在附录报告 Recall@100。nDCG@10 衡量前十条检索结果的相关性与排序质量，Recall@100 衡量前百条找回多少已标注相关文献。仅有一篇相关文献时，排第一的 nDCG@10 为 1，排第十约为 0.289，未进前十为 0；前两种的 Recall@100 都为 1。实际结果按查询求均值，计算由[固定实现](https://github.com/beir-cellar/beir/blob/ef83d29307061c65d04b035b4f4e7c18bd8374af/beir/retrieval/evaluation.py#L101)调用 `pytrec_eval` 完成。

BEIR 在统一协议下比较 18 个数据集与 10 种检索方法，支持可重复的检索比较；没有统一的“达到 0.8 即有效”通过线。论文还讨论标注不穷尽和选择偏差，其 TREC-COVID 补标实验不能外推为对 SciFact 的重标注。此处指标只按该版本相关性定义解释，不能替代报告正确性、私人知识效果或 Agent 长任务验收；本工程评分资格由[研究 Spec](../optimization/to_verify/knowledge-decision-delivery.md#6-评估标准及评分资格)拥有。

## 9. 用户输入的具体程度与来源身份

2026-10-19 实际检索并读取以下三个一手来源，记录见[来源核查](../../.tmp/research-input-clarification-design-20261019/source-review.json)。公开问题、功能提议与专家题面分别解释；没有采集本项目真实用户输入分布，不能据这些样本认定所有用户都写得简短或详细。

| 来源 | 实际观察 | 能支持及不能支持什么 |
| --- | --- | --- |
| [Qdrant issue #8014](https://github.com/qdrant/qdrant/issues/8014)，2026-01-30 的公开提问 | 作者询问 BM25 在 miracl-zh 上召回和精确率较低的原因，同时提供 collection 配置及长测试脚本 | 是“问题目标加详细材料”的技术请求，说明任务表达与材料长度应分开判断；不是本工程直接委托，也不据此采纳其性能或根因结论 |
| [Memvid issue #93](https://github.com/memvid/memvid/issues/93)，2026-01-06 的功能提议 | 作者明确要求 RRF 与可选 reranking，并给出实现及 API 建议 | 专业用户确实可以指定方法；不把提议中的性能数字、算法评价或功能缺失声明视为已核实事实 |
| [DeepResearch Bench 作者项目页](https://deepresearch-bench.github.io/)，本次按页面声明核对 | 原始用户查询用于主题分布分析，公开研究任务由领域专家另行设计 | 专家任务可以贴近真实需求，但不等于未经改写的用户记录，也不能用其详细题面推断用户实际输入程度 |

这些资料只提供输入形态的实例与来源限制。自然输入、必要澄清及评测义务怎样设计，由[研究 Spec](../optimization/to_verify/knowledge-decision-delivery.md#23-输入不明确时怎样澄清)拥有，不在参考页复制生产规则或新增任务准入。

## 10. LongDS 长程数据分析评测

2026-10-23 核对 LongDS 固定源码和已发布任务，保存 10 份来源共 206,885 字节，清单含 URL、提交及 SHA-256，见[来源清单](../../.tmp/longds-design-20261023/source-manifest.json)。这是外部源码／数据结构审计，零模型、零业务执行；没有下载输入 CSV 或运行第三方 runner。取舍及本工程候选只由[整体研究 Spec §9](../optimization/to_verify/knowledge-decision-delivery.md#9-longds-长程数据分析设计)拥有。

### 10.1 固定版本、原题与适用差异

数据固定为 `zjunlp/LongDS@6b448459c333ecc050a2e89fcc65c0e044d763ac`，代码为 `zjunlp/DataMind@a814927159470ad1624602d233f57b7c0be5882e`。作者推荐 v1.1 Lite，含 24 个完整任务、777 轮；Full 含 68 个任务、2,225 轮。Lite 只选择完整任务，未裁短其中对话；v1 与 v1.1 分开报告。[数据卡](https://huggingface.co/datasets/zjunlp/LongDS)、[固定 README](https://github.com/zjunlp/DataMind/blob/a814927159470ad1624602d233f57b7c0be5882e/longds/README.md)

| 候选 | 原始任务特点 | 本次选择依据 |
| --- | --- | --- |
| [LongDS](https://arxiv.org/abs/2605.30434) | 多轮请求依赖既有定义、计算结果、临时假设及历史版本 | 选作长期分析状态用例；固定问题序列不代表自主选题，交互轮数不等于模型工作轮数 |
| [DABstep](https://huggingface.co/blog/dabstep) | 结构化数据与业务文档的多步计算，有参考答案 | 适合计算正确性；大量独立题目不能拼成同一长期状态任务 |
| [DiscoveryBench](https://github.com/allenai/discoverybench) | 由数据和目标出发发现、验证假设 | 可覆盖开放研究，但不单独保证跨轮状态和自然窗口压力 |
| [DSBench](https://github.com/LiqiangJing/DSBench) | 现实数据分析和建模，包含多表及多模态背景 | 范围较广，所需执行环境须逐题核对；本轮不将其建模能力并入目标 |

选定 `business/netflix_movies_and_tv_shows/task3`，v1.1 Lite 的完整 36 轮。直接读取任务、metadata 和输入目录 API，核实 16 个 CSV、3,454,619 字节、最大标注依赖跨度 30 轮，见[任务审计](../../.tmp/longds-design-20261023/task-audit.json)。目录包含 Netflix 主目录和各国每周搜索热度；仅核实可见文件尺寸，不宣称已适配执行环境。

原题逐轮要求清洗、国家归属、搜索动量、成熟度、类别、供应延续、片长等分析，后期回滚或组合历史口径并形成市场推荐。第 32 轮标注依赖第 2 轮等历史，第 36 轮依赖第 25、26、27、34、35 轮；这些标签仅供评测分析，不能提供给解题 Agent。来源是从真实 Kaggle 分析工作流构造并审查的公开题目，不称为本工程原始用户记录。[原题](https://huggingface.co/datasets/zjunlp/LongDS/resolve/6b448459c333ecc050a2e89fcc65c0e044d763ac/task/longds_v1.1/business/netflix_movies_and_tv_shows/task3/task.json)、[依赖](https://huggingface.co/datasets/zjunlp/LongDS/resolve/6b448459c333ecc050a2e89fcc65c0e044d763ac/task/longds_v1.1/business/netflix_movies_and_tv_shows/task3/metadata.json)

### 10.2 实际调用、隔离与评分

固定源码核对为 A 级实现证据：`run_custom_longds.py` 加载任务并逐轮发送，`worker.py` 每任务创建一个 Agent 实例，调用 `respond(message)`，只组合当前 `context`／`question`；Agent 自己拥有历史及工具。参考答案写在评测结果中交 Judge，不传给 respond。作者允许自定义 Agent，不要求用其示例 ReAct 替换已有生产循环。[runner](https://github.com/zjunlp/DataMind/blob/a814927159470ad1624602d233f57b7c0be5882e/longds/runners/custom/run_custom_longds.py)、[worker](https://github.com/zjunlp/DataMind/blob/a814927159470ad1624602d233f57b7c0be5882e/longds/runners/custom/worker.py)

逐轮原题含 `turn_id`、`context`、`question`、`code`、`answer`；只有当前题面可交被测 Agent。正式环境还须隔离参考脚本、notebook、metadata 和未来题面，不能因为 runner 接口不传答案就推定文件系统也无泄漏。

官方 Judge 输入为当前题面、参考答案、实际回答，输出 0／1 和理由。必需内容全部正确计 1，任意缺失或错误计 0；数字仅忽略无意义尾零，明确容差除外；排序按所问内容核对，数值完全并列时接受不同顺序。标签归一化规则较宽，实际错判须保留原始判分并审查，不能把模型 Judge 称为确定性事实检查。[Judge](https://github.com/zjunlp/DataMind/blob/a814927159470ad1624602d233f57b7c0be5882e/longds/runners/src/judge.py)、[评分 Prompt](https://github.com/zjunlp/DataMind/blob/a814927159470ad1624602d233f57b7c0be5882e/longds/runners/src/judge_prompt.py)

单任务分数是正确轮数除以该任务总轮数，task3 分母为 36；原论文和官网整套分数采用任务准确率的宏平均。固定 runner 的原始聚合字段仍须按实际代码解释，不凭 `overall_accuracy` 名称推断口径；单任务评分不受不同任务轮数加权差异影响。每轮默认超时为 3,600 秒；原论文使用每用户轮最多 40 个推理／动作步骤，二者都不是整任务预算。[论文评测协议](https://arxiv.org/html/2605.30434v1#S3.SS4)、[自定义 runner](https://github.com/zjunlp/DataMind/blob/a814927159470ad1624602d233f57b7c0be5882e/longds/runners/custom/run_custom_longds.py)

### 10.3 公开比较的范围

固定 README 给出 v1.1 Lite 的组合系统成绩：GPT-6 Astra／Codex 78.17%，Claude Fable 5.1／Claude Code 76.53%，GPT-5.6-sol／Codex 70.71%。这是整套 24 任务的宏平均，未查到所选 task3 的单独公开结果；不作本工程通过阈值，也不能单独归功于模型或 Harness。[官方结果说明](https://github.com/zjunlp/DataMind/blob/a814927159470ad1624602d233f57b7c0be5882e/longds/README.md#longds-v11-lite-leaderboard)

英文原题的公开成绩与中文改编分别报告。跨模型、任务版本、预算或工具环境的差异必须注明；本工程若只跑 task3，就报告单任务及逐轮结果，不填 Lite 榜单成绩。外部代码存在不证明 personalAgent 的跨轮引用、授权、预算或压缩已经通过。
