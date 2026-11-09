# 受限检索实验执行协议 Spec

问题编号：`KNOWLEDGE-DECISION-DELIVERY-001`。本文拥有受限检索实验的模型决策边界、可编程候选、执行／持久接受和当前完成协议。用户请求与验收见[实验验收](research-experiment-acceptance.md)，共享源码写入见[程序产物契约](program-artifact-contract.md)，总体职责见[总 Spec](knowledge-decision-delivery.md)。已执行轨迹见[验证记录](verify_results/research-experiment.md)。

## 1. 当前先完成的闭环

2026-10-21 用户明确要求：当前 claim 和 verifier 暂不接入，先初步闭环任务，运行稳定后再接入。该决定改变本任务的实施范围，不把既有 claim 链的完成状态当作原用户需要，也不改变用户要求的实际实验、报告、配置和可复现产物。

当前路径为：**自然委托 → 模型选择实验／读取实际结果 → 分析并决定继续或收敛 → 提交报告 → 核对必要执行事实 → 返回确切回答。** 模型保留决定下一项实验、读取哪些错例、修订候选及何时提交的权力；代码负责权限、执行事实、配置冻结、原件引用、预算和Completion。完成、已完成恢复及缓存返回均不生成报告副本、导出清单、ZIP或下载资源列表。

| 首轮保留 | 首轮后置 |
| --- | --- |
| 实验工具、源码／配置产物、实际执行与反馈、模型证据消费及报告生成 | 将分析拆成 ResearchClaims、claim 编辑／逐条引用绑定及其专门选证循环 |
| 模型提交完整 `FinalMessage`／确切 segments，返回同一回答并保留内部原件 | 独立语义 verifier、ResearchReview、同稿 approved 要求及拒稿修订循环 |
| 执行覆盖、冻结／test 隔离、同run身份、必要原件可读和实际回答 | 新评分器资格准备与语义 target 评分；当前已有工具和历史材料保留，不作为初步闭环的前置步骤 |
| 全部实际模型调用的容量、用量及原 deadline；真实压力下的必要压缩 | 以摘要 Judge、额外研究子 Agent 或新任务平台补回被后置的阶段 |

报告生成仍由模型承担，可复用现有 writer 的成文职责，但其输入输出须独立于 claim 创建和语义核验；不把现有 claim writer 原样调用称为“已经解耦”。当前没有 claim／verifier 时，压缩只覆盖实际存在的动作、读取、报告等历史；通用设计列出的 verifier 容量保护不构成首轮接入要求。

本范围仅适用于已由正式部署绑定实验能力的研究任务，其他普通对话及既有研究契约不自动关闭核验。实验路径使用一套当前交付契约，迁移其全部生产者、消费者和恢复出口，不增加可任意切换的 `skip_verifier` 开关，也不伪造 passed／approved 来适配旧链。已有封存 run 按原身份解释，不拿原 claim 检查点冒充新路径的提交。

初步闭环检查实际实验、结果消费、必要选择、当前提交和回答是否连续；独立指标复算可由工程读取原执行产物完成，不能强制用户下载、导出打包或CLI重跑。报告语义按用户决定暂放，结果记“Agent流程检查点／语义未验收”；运行时长、工具次数或一条成功轨迹不自动构成稳定或长任务能力。过去按文件交付口径封存的结果保持原身份，后续评价按本轮明确范围单列，不覆盖原报告。

T3／T5 提交和采集迁移已在新 DeepSeek E1 中到达报告、下载、复算和干净复现；独立审读确认错例分析错误，初步闭环仍未通过。新轨迹的正确资料完整送达，没有历史压缩；不能把错误归因为资料丢失或凭此准入摘要。此前 E1、P1、F3、评分资格及源码封存保留原判据和成绩，不追溯重评。

## 2. 受限实验能力

这里的“受限”指实验执行器有明确的可执行范围：只接受已支持的方法及参数、获准数据与模型、实验专用资源，并遵守执行额度及开发／test 隔离。参数、资源范围和额度由准入及 runner 落实，不能只靠 Prompt 约定；这些是待实施和验证的要求，不代表当前已经具备物理沙箱隔离。

研究模型负责实验策略、错例解释、候选程序、需要语义取舍的方案建议及完整交付；已确定规则下的数值比较交给确定性业务代码。工程维护固定基线、执行驱动和评分器，模型可以在获准范围编写分析及排名变换程序，不能修改受信组件。首个可编程切片只处理已有排名的组合／重排及相关诊断，不开放任意模型下载、训练或宿主 Shell。以下契约已沿正式入口装配，完整交付仍待验收；独立工具证据见 [先行交付：独立实验工具 Implementation Plan](verify_results/research-experiment.md#31-先行交付独立实验工具-implementation-plan)。

本例要求比较已有检索方法，不要求 Agent 实现新算法，因此先以“输入数据、方法和配置均已明确的一次实验”为执行单元。解析、索引、检索及指标计算按相应方法的既定程序完成，同一作业的配置、状态、结果和耗用保持关联。把这些稳定步骤逐个交给模型调度，并不会增加研究自主性；模型的工作是消费实际结果，决定下一项必要实验或交付。

工具只运行本次基线配置或确切程序，不自动遍历全部候选、选择最优方案、追加融合、决定研究停止或代写结论。SciFact 名称、809／300 条查询及本例验收要求属于用例和获准材料，不写成执行器中的案例分支或参考答案；实际覆盖从输入数据和执行事实取得。固定的是受信执行、基线及评分协议，候选实现可以由模型编写；不为兼容未来方法预建插件平台。

**固定基线的可配置范围很小，不能仅靠这些参数展示研究决策。** BM25 首个候选没有暴露 `k1`／`b` 等调参项；向量首例只准备一个固定 MiniLM 候选，许可打分方式为 `cos_sim`；独立工具的参考融合固定为 RRF、常数 60。`retrieve_k` 主要控制返回深度及资源，满足指标深度后增加它，不能当然解释为改善 nDCG@10 或 Recall@100。P1 增加候选程序的构造与修订空间，仍不以找到全局最佳配置验收。

若原委托已确定可机械执行的目标指标、约束及并列规则，原实验 Application 的比较职责从已提交结果计算排序、合格集合及规则选定项；小规模合法候选在预算内也可用固定流程搜索。该职责消费真实结果，不要求 LLM 代算最大值，不借 Admission 改写提议，也不把选优塞入单次执行器。若成本、效果或特定错例存在需解释的取舍，模型依据当前目标及实际材料说明并提出选中引用，再沿原业务入口绑定和冻结。已有指标排序的复述不计为独立研究判断；本例重点验收实际执行、证据解释、必要取舍、成果接续及可运行交付，不为制造自主性增设参数或强制追加实验。

这里的“最优”须限定候选范围、目标和实际证据。固定规则下已运行候选的最高分项由代码计算；研究模型通过取证、提出判断、实现候选、决定实验及何时停止，影响实际验证的方案和耗用，并据真实结果提交建议。模型不能改写原目标或临时添加成本权重以制造取舍。原 E1 的固定方法空间有限，因此新增 P1 验收程序构造及反馈消费，保留 E1 原身份；若模型仅消费固定流程的最终排名写报告，仍按固定实验流程加报告生成评价。[推进、结束与恢复](#4-推进结束与恢复) 说明决策怎样进入执行，[评估标准及评分资格](research-experiment-acceptance.md#4-评估标准及评分资格) 分别验收交付与研究决策。

### 2.1 模型的决策权与候选修改范围

研究模型拥有研究过程和候选实现的决定权，须由实际工具动作兑现。目标、指标、权限和资源上限来自原委托及执行契约，不能由模型在实验中改写。旧 E1 已有模型自主实验轨迹，Python 局部组也已自主生成分析程序；两者尚不证明 P1 的完整候选实现、实验反馈与修订链。

| 决定对象 | 研究模型可以决定 | 确定性边界 |
| --- | --- | --- |
| 取证与假设 | 选择要分析的开发查询、排名差异及获准原文，提出或放弃可验证判断 | 不预选有利错例；开发资料可分析，test 标注不交给研究模型调参 |
| 候选实现 | 编写和修订候选 Python 源码及 JSON 配置，改变排名变换逻辑 | 不修改固定基线、评分器、执行器、隔离策略或历史结果；程序输出仍是待评分候选 |
| 实验与耗用 | 根据新反馈决定下一份程序、合法配置、是否追加实验及何时停止 | 每次运行受剩余额度和支持范围约束；不能扩权、隐去失败或无限重跑 |
| 方案建议 | 解释效果及原目标内的取舍，提出选中结果引用并提交冻结 | 已确定规则下的数值排序和选优由业务代码完成；冻结后不能换代码或利用 test 反馈改选 |

候选 `program` 入口提供至少两份已有排名及分数、查询文本、全库文档 ID 和可选配置；不提供文档标题／正文、qrels、embedding 或模型权重，默认镜像只有 Python 标准库。研究模型已可读取获准开发标注，并在独立 `execute_python` 分析中使用 train.tsv；这不扩大候选容器权限，test 标注仍只归受信评分端。源码沿 T2a 迁至唯一 [候选执行入口](../../../src/personal_agent/infra/retrieval_experiment/controller.py)与 [配置契约](../../../src/personal_agent/infra/retrieval_experiment/contracts.py)；工程迁移已有限定证据，P1 模型消费仍单独验收。

在这些输入下，无需改变受信执行器即可实现以下候选；它们都是待验证方向，不是预定提升或必跑清单：

| 可修改方向 | 候选程序能改变什么 | 需要实际验证的判断 |
| --- | --- | --- |
| 排名融合 | 各路权重、排名衰减公式及参与窗口；自写加权 RRF 等 | 是否减少一种方法的优势被另一种稀释；内置参考 RRF 仍固定常数 60 |
| 分数融合 | 各路分数归一化、加权组合及权重配置 | 分数差距是否提供了被纯排名融合丢弃的有效信息；原始 BM25 与向量分数不能直接视为同尺度 |
| 按查询调整 | 根据查询文本特征、排名重叠和分数分布选择已有排名或调整组合 | 是否能从可见信号预测各路优劣；不能将查询 ID 到 gold 文档的查表当作可迁移策略 |
| 候选保留与重排 | 共同命中文档加权、保留某路前列、再补入另一路结果 | 能否改善前 10 排序或减少前 100 遗漏；文档 ID 本身不提供正文语义 |

`retrieve_k` 允许 100—1000；加深输入须重新运行对应基线并形成新实验身份，候选不能从未提供的分数恢复更深排名。它属于有成本的取证选择，不能预先算作质量提升。当前输出校验允许合法文档 ID，并未将输出硬限制为输入排名并集；但没有额外语义输入时，程序对并集外文档没有新的相关性依据。正文语义重排、查询改写后重新检索、BM25 `k1`／`b`、向量模型切换或训练均不在本切片暴露范围；若真实错例证明需要，须另行完成证据、设计和执行边界准入，不能由模型自行修改受信脚本开放。

分数归一化和加权融合的机制参考 [Elasticsearch 官方线性融合说明](https://www.elastic.co/docs/reference/elasticsearch/rest-apis/retrievers/linear-retriever)及 [混合检索融合函数研究](https://arxiv.org/abs/2210.11934)。这里只参考公式和比较思路，在现有候选程序中实现，不引入 Elasticsearch 新版 API、升级现有引擎或据外部结论宣称本例提升。

2026-10-20 对既有 809 条 train 产物的[描述性分析](../../../.tmp/retrieval-experiment-tool-20261020/decision-potential-audit.json)显示：BM25 的逐查询 nDCG@10 在 215 条上高于向量，向量在 150 条上更高，其余相等；现有 RRF 相对 BM25 改善 162 条、退化 101 条、相等 546 条。两份 top100 并集内正标的宏平均可达 Recall 上界为 0.97054，现有 RRF Recall@100 为 0.95035，18 条查询存在输入已有正标却被 RRF 排出前 100 的情况；另有 22 条查询全部正标均不在这两份输入中。该上界使用 gold，只定位输入可达性和遗漏，既不是新算法得分，也不证明模型能识别这些正标、提升约 2 个百分点或改善 nDCG；本轮未读取 test 或运行新候选。

下一步应验证“实际开发差异 → 模型判断 → 确切程序修订 → 真实执行反馈 → 继续或停止”的连续链。固定流程跑完再让模型写报告、机械遍历预设权重后复述最大值，均不能替代 P1 的研究决策证据。效果只由事先确定的开发验收及冻结独立评测确认，不能以改过代码、迭代更多或上述可达上界宣称提升。

**加权 RRF 的隔离验证（2026-10-20，执行前固定）。** 为回答当前数据是否支持调整权重，复用上述两份 train top100，固定衰减常数 60、输入窗口与输出深度 100，仅运行 BM25 权重比例 `α∈{0,0.1,…,1}` 的 11 个候选，向量比例为 `1−α`。公式为 `α/(60+rank_bm25)+(1−α)/(60+rank_dense)`，未命中一路时该项为零；实际源码整体乘 2，使 `α=0.5` 与现有等权参考逐分数一致。只在独立候选源码及配置中实现，不改变受信组件、生产工具或现有结果；方法依据为 [官方加权 RRF 公式](https://www.elastic.co/docs/reference/elasticsearch/rest-apis/retrievers/rrf-retriever)。

按 `sha256("weighted-rrf-v1:"+query_id)` 排序，前 647 条为调参区、后 162 条为留出区，划分不读取标注。只按调参区 nDCG@10、Recall@100、接近等权、较小 α 的顺序确定唯一候选，再查看其留出区效果；保留全部 11 次实际执行和外部可信评分。报告完整 train 与两区指标、相对等权的差值和逐查询胜／负／平；预定以留出区 nDCG 上升且 Recall 不降作为同时改善，以 2000 次成对 bootstrap（固定种子 20261020）的 nDCG 差值 95% 区间辅助说明不确定性。没有改善也结束本轮，不追加细网格或改变判据。证据归档为 `.tmp/retrieval-experiment-tool-20261020/weighted-rrf/`。

本轮属于已有工程检索产物上的候选算法实验，不是 Product E2E、研究模型自主调整或生产优化验收；这些 train 查询此前已用于整体诊断，本轮留出只隔离参数选择，不能冒充此前完全未见的独立测试。未读取或重跑 test，原 test 已有历史身份也不作为新候选的独立提升依据。

实际运行命令为 `.\.venv\Scripts\python.exe .tmp/retrieval-experiment-tool-20261020/weighted-rrf/run_experiment.py`。11 份候选均经现有隔离 runner 执行及独立 worker 评分，控制端累计耗时 24.406 秒；`α=0.5` 的完整排名及逐查询指标与原参考精确一致，两个端点的逐查询指标分别与原向量、BM25 一致。[执行前计划](../../../.tmp/retrieval-experiment-tool-20261020/weighted-rrf/plan.json)、[候选源码](../../../.tmp/retrieval-experiment-tool-20261020/weighted-rrf/weighted_rrf.py)、[调参选择](../../../.tmp/retrieval-experiment-tool-20261020/weighted-rrf/selection.json)及[完整结果](../../../.tmp/retrieval-experiment-tool-20261020/weighted-rrf/summary.json)保留确切身份。

仅由 647 条调参区选出 `α=0.6`。以下列出其与等权的对照，指标取五位小数；完整 11 组及未舍入值见结果原件：

| 查询范围 | 等权 nDCG@10 | 60% BM25／40% 向量 nDCG@10 | 等权 Recall@100 | 60% BM25／40% 向量 Recall@100 |
| --- | --- | --- | --- | --- |
| 调参区 647 条 | 0.71308 | 0.72010 | 0.95621 | 0.95827 |
| 留出区 162 条 | 0.70880 | 0.71989 | 0.92695 | 0.93313 |
| 完整 train 809 条 | 0.71222 | 0.72006 | 0.95035 | 0.95323 |

本轮同时改善的点估计判据成立：留出区 nDCG 差值为 `+0.01109`，逐查询 13 胜／10 负／139 平；Recall 差值为 `+0.00617`，仅 1 胜／0 负／161 平。完整 train 的 nDCG 为 75 胜／44 负／690 平。留出区成对 bootstrap 的 nDCG 差值 95% 区间约为 `[-0.00038, 0.02300]`，包含零；Recall 区间为 `[0, 0.01852]`。因此只确认当前固定输入和本轮划分下观察到小幅改善，不能宣称稳定或独立 test 提升；更多 BM25 权重也非单调收益，`α=0.7` 的完整 train 指标为 `0.71877／0.94124`，Recall 低于等权。按原计划结束本轮，不追加搜索或生产改动。

### 2.2 模型怎样构造并验证候选

**现有共享产物读写、检索候选执行及独立 `execute_python` 分别承接源码、实验和分析；固定基线与受信评分继续复用。** 候选程序通过检索实验协议执行并由外部评分，通用分析程序只产生分析产物，二者不以 stdout 互相改写正式事实。完整交互 Shell／Notebook 会增加本例不需要的进程会话和任意依赖管理，首版不采用。

1. 模型从开发指标、逐查询排名和必要原文提出具体判断，自行实现诊断或候选。例如分数归一化、融合、按查询特征选用已有排名，均属于允许的实现方向，不是必跑清单或预定改进结论。
2. 候选程序经 `write_artifact` 创建／修订为确切版本，以 `program_ref` 交给 `retrieval_experiment`；读取复用 `read_artifact`，已有源码通过引用和范围修改，不靠模型重抄恢复。分析程序沿当前 `execute_python(code,input_files)` 提交，契约由 [Python Spec](python-data-analysis-tool.md)拥有；工具链已接入，P1 连续消费尚待验收。
3. 两个 Application 复用同一受控沙箱技术，分别物化其合法只读输入和受限输出；固定启动协议，不接受任意命令、宿主路径或动态安装。分析 stdout 是普通产物；候选排名交给检索 Application 的 typed 结果契约及受信评分。不为每种诊断或算法注册工具。
4. 模型程序作为非受信工作负载，只产生候选输出。评分在它不能修改或读写的独立受信进程／环境进行：核对查询集合、文档 ID、重复、有限分数、排序和完整性，再由固定评测计算指标。程序自报分数、覆盖或“通过”不成为执行／评分事实；输出齐全也不代替方法语义和效果评价。
5. 模型消费实际指标、错误和产物，决定修订程序、验证其他合法候选或停止。每次修订产生新版本和新实验身份，失败及无提升结果保留并计费，不能以新源码解释旧成绩。
6. 冻结绑定确切源码、依赖镜像、配置、基线输入的生成规则及数据身份。test 使用对应 test 排名及冻结代码，在无 test 标注的程序环境执行，由外部评分端验收，不接受临时换代码。最终交付包含实际执行的源码及复现入口。

首个切片使用固定依赖、离线数据和已有基线排名，不开放任意网络或私人知识库权限。开发标注按原协议供研究模型分析，test 标注仅归评分端；候选环境不挂载评分目录、生产凭据或容器管理 socket。导入名单或静态源码检查不能代替操作系统边界。程序、回执、结果、额度及交付沿原 Artifact／Journal／Gateway owner，不另建可写实验总账或持久解释器状态。

正式接入为“研究模型 → 程序产物写入口 → 程序引用 → 工具治理 → Application／执行 Port → 隔离 runner → 候选输出 → 受信评分 → 原结果产物 → 下一轮模型”。开源装配及取舍见[可编程执行源码比较](../../agentRef/tool-execution-and-safety.md#7-模型生成程序的实际执行链)。候选读写契约及正式 typed Schema、输入角色和输出约束见下文；实现和验证状态由 [完整落地 Implementation Plan](verify_results/research-experiment.md#32-完整落地-implementation-plan) 拥有。

执行授权同时绑定数据快照、split、用途及冻结事实。可读引用不等于可用于任意计算：通用 Python 输入同样拒绝把 test 资料改名为开发输入，冻结前不得启动 test 候选／评分，冻结后不得将新源码或配置代入。候选环境只能取得当前授权的实际文件，业务校验和文件／网络隔离共同落实此约束。

Context 常驻当前目标、有效程序／结果引用、最新必要反馈及剩余额度；源码和历次排名保存在原产物 owner，按需读确切版本与必要片段，不将完整历史源码和日志反复塞入每轮。依赖当前源码的语义评分仍需完整最小充分输入，不能摘要掉必要实现；每次构造计入 R-07。恢复只从已提交源码、结果及额度接续，不依赖 Python 解释器内存；原 E2 成绩不自动外推 P1 程序恢复。

### 2.3 生产实验与持久接受的实施契约（T2，已实现、待整体验收）

**本轮只增加检索实验 Application、一个业务工具和一个执行 Port，复用原 Artifact 与 Conversation Journal。**
现独立实验引擎迁为生产适配器唯一实现，CLI 随之成为调用者；不复制评分、冻结和沙箱规则。
部署绑定固定本次材料、实现、模型、镜像、许可主体和额度，不建立动态环境或 Provider 注册中心。

#### 初始资源与部署

Web、Conversation 和 InteractionTrace 的初始资源字段统一为 `input_artifact_refs`。
该字段只表达用户本次提供的确切引用，不接受模型自报 role、owner、audience 或执行权限。
同 run 恢复要求 principal、会话、messages 和初始引用与已接受记录一致。
实验内部的角色输入由当前合法引用与受信部署绑定产生；它不是第二套用户输入协议。

一个 run 只绑定本次许可部署，首次接受时保存其内容摘要，恢复时要求原部署身份仍有效。
部署复用现有 DatasetManifest／DatasetBinding、ModelIdentity 和 ImplementationIdentity，不另造同义身份。
材料角色只覆盖本次 corpus、queries、开发 qrels 和私有 test qrels；train、frozen、test 的用途按固定业务规则检查。
研究模型可按权限读取开发材料；候选只取得声明的查询文字、文档 ID 和实际输入排名。
test qrels 由组合根提供的受信 scorer 身份读取，不进入模型 Context 或候选容器。
Engine endpoint、模型本地路径和暂存根归外层运行环境，必须对应已绑定身份，不投影给模型。
数据集、模型、镜像及额度由部署提供，工具不再要求模型重复填写；原内部配置仍完整绑定这些事实。
没有真实多部署消费者时，只保留内容摘要和本次绑定，不增加独立 profile id／revision 注册生命周期。

#### 唯一实验工具

`retrieval_experiment` 的 `action` 使用按 operation 区分的严格 union，未知字段拒绝。

| 操作 | 模型选择 | Application 恢复与执行 |
| --- | --- | --- |
| `run_development` | BM25／dense／参考 RRF／candidate 之一、许可 retrieve_k；组合分支提交实际输入结果引用，candidate 另提交 program_ref 和可选 config_ref | 从本 run 部署恢复开发材料、固定模型及额度，核对确切版本／用途后执行；结果只能来自真实执行和受信评分 |
| `freeze` | 本任务已完成的 selected_result_ref | 从结果恢复完整配置、依赖、程序和环境，提交不可变冻结事实；机械比较规则已确定时核对选中项，否则由模型在原目标内选择并说明依据。首轮不等待 claim／语义核验，选型解释留待独立审读，不增加冻结批准条件 |
| `evaluate_final` | 本任务 frozen_ref | 恢复冻结方案和对应 test 输入，实际执行基线与选中方案，复用确切相同且有效的重复结果；不接收临时源码、参数或 test 标签 |

retrieve_k 沿现有 100—1000 范围，参考 RRF 固定常数60；不让工具自动搜索或替模型决定是否组合。
freeze 重复同一选择返回原事实；发生 final dispatch 后不得换配置或源码。
返回真实状态、正式产物引用、有界摘要、已知耗用和明确缺口；unknown 不缩成空结果或成功。
不设置模型 `bind_delivery` 操作；文件集合和复现入口由 [成果、Context 与共享产物](verify_results/research-evaluation-and-delivery.md#1-成果context-与共享产物) 的交付用例导出。

#### 变更调用的持久接受

**原 Journal 已保存这些调用的持久接受与执行绑定，不另建 Command 平台。**
原 InteractionTrace 保存 `write_artifact`、实验变更和 Python 执行的已接受请求；Python 的具体 Command／进程事实／Receipt 由 Python Spec 定义，其他只读工具保持原路径。
记录绑定实际 ExecutionScope、原 action_id、工具名、完整严格请求、请求摘要及适用部署／输入身份。
它是不可变执行请求，不代表运行成功；不得把模型 Proposal 直接记为 Receipt。
按工具区分两种具名 payload：Artifact create／patch 请求与实验 action；不建立面向所有业务的通用任务总账。
原文请求只用于同身份重放；Artifact owner 仍拥有实际快照、元数据和提交回执，不产生第二份可编辑内容。

Conversation 完成原 Admission 后，经原 Journal 先持久接受该确切请求，再进入 Gateway 和业务 Service。
Artifact 和实验 Service 均要求受信 Gateway context，并核对当前作用域、action_id 与已接受请求摘要相符。
Gateway 只传播已绑定身份，不补参数、改变 payload 或自行产生执行成功。
同作用域、同 action_id、同完整请求复用原记录；不同请求拒绝，不以新的模型采样覆盖旧动作。
write_artifact 的 producer 继续绑定该身份，Artifact owner 负责跨进程排他和确切快照提交。
接受后尚未调用 Artifact 时，可重放同一请求；快照已提交但响应丢失时，恢复同一回执，不另建快照。
T1 的内容摘要／partial commit 恢复与此处的调用接受分别拥有职责，不能以其中一个替代另一个。
freeze 等本地事实操作也在原记录提交其结果，但不为它们建立 Docker 作业。

#### Journal 更新与原样恢复

Journal 的变更方法显式带 run_ref／ExecutionScope，不能只收无法定位 run 的 command hash 或依赖全局 current_run。
同一 Trace 的所有写入口经同一提交函数：读取 latest、校验 scope／expected revision、只更新职责字段、原子落盘后更新缓存。
Conversation 外层 `_commit` 保留 latest 中的已接受请求和执行结果；实验 Service 不覆盖 Conversation 的 inputs／usage／Final。
ActionObservation 恢复使用记录中的原 action_id；执行结果已有而 Observation 缺失时只补一次，tool_calls 不重复累计。
累计用量由已提交事实派生，不另存可独立改写的 remaining budget。
单宿主首版对同 run respond 和确认写入口采用共享进程内／OS排他锁，进入后刷新磁盘快照，冲突明确返回。
锁的重入和线程边界须与实际 Gateway 调用一致，不能持锁后在另一个工具线程重复获取同一非可重入锁。
不扩大为分布式 lease；多宿主共享 Journal 不属于本次许可环境。

#### 实验派发、终态与额度

执行 Command 复用上述已接受请求，另绑定实际输入、稳定 job identity、首次 deadline 和适用作业额度。
Command 必须保存 action_id 和 scope，不能只保存不可逆 hash 后再猜恢复身份。
先持久接受和 dispatch 状态，再调用 Docker；容器／索引名由 command 与当前实际子作业角色确定性派生。
同名后端对象还须核对标签、镜像和输入身份；create/start 响应丢失时先对账，不能盲目另起同一工作。
已提交终态复用；运行中仅在原 deadline 内等待或停止；无法确认终态则记录 unknown 并保留未结占用。
Gateway 不额外对实验线程做假取消或自动重试；runner 负责真实停止／查询，持久结果后才清理可恢复输出。
实验次数、实际耗时和 unknown 占用在同一 Journal 记账；父工具耗时和子作业分解不重复相加。
E2 仍只承诺已提交成果边界恢复，F2 检查真实停止或如实 unknown，不承诺任意运行中宕机必然续成成功。

#### T1b／T2 的具体装配与 Schema

以下接口在实施前固定；均为 strict／frozen typed 模型，正文内容只按各字段所属 owner 恢复，不从模型文字扫描身份。

| 入口或类型 | 字段、调用及责任 |
| --- | --- |
| 初始引用 | Web、外观、Runtime 与 `respond` 统一 `input_artifact_refs: tuple[ResourceRef,...]=()`；拒绝重复、非 Artifact、越 owner 或不可读引用。首次模型调用前验证并提交到 Trace，同 run 恢复要求主体／会话／messages／引用原顺序全部一致 |
| 具名来源 | `ArtifactSourceInput(kind="artifact_source", resource:ArtifactResourceItem)` 加入 InteractionInput，只表示可读文件元数据，不表示已读。初始来源、成功写回执、实验 typed 结果由生产者追加该投影；原成功 retrieval 保留。元数据未知 URL／行数不能覆盖既有已知来源类别，只有已知身份／摘要／长度冲突才拒绝 |
| 模型输入说明 | 版本化 read_artifact／search_action_output 的 description 及主循环 system 对应取证条款，说明当前初始引用与成功 typed 回执投影均可读，元数据不等于正文已经读取；返回行才构成已读证据。只同步本次来源契约，不增加任务特化策略、自动选证或绕过权限 |
| 读搜及引用 | Artifact Port 增 `read_snapshot`／`resource_item`，read／search 同用 owner 的 TextCoordinates，返回 digest／EOF。`SourceMetadata(resource_ref, source_url, document_kind, total_lines)` 替代隐含 URL tuple；本地文件默认 source_text，原 retrieval 显式类别优先，只有实际返回行可引用／计已读，报告不加入来源 |
| Gateway context | `ToolGatewayContext.allowed_resource_refs=()`、`accepted_request_digest=None`；ToolPort／Executor 透传，Gateway 以先前固定 RunnableConfig key 注入实际 typed 对象。`require_gateway_context` 拒绝 dict 冒充。普通工具默认字段保持，写／实验必须同步 `timeout=None,max_retries=0` |
| 写／inspect | `WriteArtifactArgs(request:ArtifactWriteRequest)`，只提交 create／patch；先校验已接受摘要再调 T1a write_draft，成功解析具名 ArtifactWriteReceipt。inspect 只有 resource_ref／question，删除 user_id，按实际 context principal 和当前集合检查，提取文本不冒充原文坐标 |
| 工具副作用 | 在唯一 `SideEffectType` 中增加 `write_local`，用于草稿写入及实验本地产物提交。它仍受实际 scope、许可引用及工具 allowlist 约束，风险为 low、不新增确认；Registry 将其判为非只读、非 planning_safe、不可通用重试。它不代表长期知识写入或对外发送，跨持久边界仍使用上述接受／Command 协议 |
| 接受记录 | Trace 的 `accepted_tool_requests` 是 `AcceptedArtifactToolRequest`／`AcceptedExperimentToolRequest` 按 tool_name 区分的 union；公共字段 action_id、execution_scope、request_digest、plan_step_id，分别保存完整 WriteArtifactArgs／ExperimentToolArgs。Artifact 保存实际 receipt／失败 observation，实验结果仅在 experiment_records，一份事实不双写 |
| 唯一请求摘要 | `kernel.contracts.tool_runtime.accepted_tool_request_digest(*, execution_scope,action_id,tool_name,arguments:BaseModel)`；envelope 键为 execution_scope／action_id／tool_name／arguments，arguments 用 mode=json，ensure_ascii=False、sort_keys=True、紧凑 separators、allow_nan=False 后 UTF-8 SHA256。普通工具原 execution_request_digest 职责保持，不混用 |
| Journal 一致性 | `exclusive_run(run_ref)` 共享进程内／OS锁、同线程重入；整个 respond、知识确认及实验窄写入口同锁。get 刷新磁盘最高 revision；put 校验 expected revision、同版同内容可幂等、异内容冲突，先落盘再缓存。outer commit 只更新职责字段并保留 latest 的新接受／实验／交付事实 |
| 原样恢复 | 模型采样前恢复未物化的 accepted request；有回执只补原 action_id 的 observation／source／usage 一次，没有回执按原命令对账／重放。已有 observation 不重复 tool_calls，不能因丢失局部变量重新采样替换动作 |
| 截止后的草稿对账 | 已接受 write_artifact 丢回执时，先调用 Artifact owner 的只读 `recover_draft`（同 write_draft 的 scope／action／request／allowed refs 参数），返回完整 producer 绑定、确切已提交 metadata 及原字节均通过的原 ArtifactWriteReceipt；该查询不补写任何文件。即使 deadline 已过也可恢复原事实；不存在完整提交时返回 None，截止后禁止以重放新建／补齐草稿，不能未查询就固定为失败。权限、异 payload 或完整性冲突明确报错 |
| 用户内容入口 | `POST /api/artifacts/upload` 只上传不入库；`GET /api/artifacts/{resource_id}/revisions/{revision}` 按认证主体构造确切引用，`read_upload` 一次取得已核验原字节后 Response 返回，避免另开路径竞争。非 owner／缺文件404、非法输入422、run写冲突409。View 的 resources 复用 ArtifactResourceItem，Web 派生下载 URL，不暴露存储路径 |

正式 HTTP 响应与资源 DTO 由[API 契约](../../api.md)及相应类型拥有；实验完成仍只返回本次确切回答和必要引用，不以用户下载验收。旧资源投影的实现／取证记录见[历史验证](verify_results/research-evaluation-and-delivery.md#8-旧资源投影的实现与取证)。

唯一模型工具参数为 `ExperimentToolArgs(action)`：RunDevelopment 的 request 按 method 区分 BM25／dense（retrieve_k）、RRF（retrieve_k、至少两份 input_result_refs）、candidate（同前并加 program_ref／可空 config_ref）；FreezeExperiment 只有 selected_result_ref，EvaluateFinal 只有 frozen_ref。retrieve_k 为 strict 100—1000，参考 RRF=60；首版冻结组合的父输入仍限实际 BM25／dense，与既有冻结规则相同，不自动补选最优结果。

`RetrievalDeployment` 由受信 JSON 配置提供 authorized_principal、独立 scorer_principal、四种 MaterialBinding(role,resource_ref,content_digest)、开发／最终 DatasetManifest、worker／candidate 内容镜像 ID、ModelIdentity 和必填 ExperimentLimits；不另建 profile id／revision。limits 固定 worker 1200秒／4096MiB／4CPU／128PIDs，candidate 60秒／512MiB／1CPU／64PIDs／32MiB临时空间，stdout 16MiB／stderr 64KiB。run_timeout_seconds 与 max_execution_seconds 必须由部署者分别显式提供，不以900秒作为所有长任务的默认值；前者在绑定部署的研究Trace初次创建时用实际UTC固定deadline，后者只累计实验 backend 父调用耗时与未结预留，不给全部普通工具新增计时平台。恢复不重置，子作业不重复相加；下一模型决策与新派发前检查墙钟。

配置入口为 `Settings.retrieval_experiment_config_path`（默认 None），环境变量 `PERSONAL_AGENT_RETRIEVAL_EXPERIMENT_CONFIG`。配置禁向模型原样输出；仅已绑定授权 principal、当前初始引用包含许可开发三原件的 run 启用该部署及其显式配置的 deadline。既有未绑定对话保持原策略。本地 endpoint／network／es_endpoint／model_path／workspace_root 由 infra 的 LocalExperimentEnvironment 提供，不成为模型参数。scorer 固定受信主体 `personal-agent/retrieval-experiment-scorer`，研究主体沿原正式用户；不从引用 owner 临时构造授权。

业务 Service 入口为 `execute(action, *, execution_scope,action_id,request_digest)->ExperimentToolResult`。构造注入 artifacts／journal／execution／deployment／clock，不反查全局 Runtime。以下事实由实验 Application typed 模型拥有、原 Trace 承载：

| 类型 | 必须保存或返回的字段 |
| --- | --- |
| PublishedExperimentResult | 原 result.json 确切字节的 raw_result_ref，以及 rankings_ref／coverage_ref／metrics_ref／per_query_ref、input_result_refs、可空 program_ref／config_ref；另含 corpus／queries 两个 BoundInputIdentity（确切文本 Ref／digest）。从原字节恢复唯一 ExperimentResult，不由 wrapper 重序列化猜原 input_results SHA，也不复制可写指标 |
| PublishedFrozenExperiment | 唯一 FrozenExperiment、selected_result_ref、input_result_refs、program_ref／config_ref；冻结文件及引用不可变，选择在 final dispatch 后锁定 |
| ExperimentCommand | execution_scope、action_id、request_digest、deployment_digest、按 operation 区分的 DevelopmentWorkload／FinalWorkload、BoundInputIdentity 列表、accepted_at、deadline_at、reserved_seconds、command_digest；bound input 是 Ref／digest，私有 test 标签仅由部署摘要与数据哈希绑定，不把其 Ref 写入模型可见或用户 run Trace |
| ExperimentExecutionFact | status=dispatching／succeeded／failed／timed_out／output_limit／unknown，实际 BackendJobFact 列表、可空 elapsed_seconds、受限 error_code。job 保存 key／role／name／可空container_id／可空image_id／真实status／耗时；镜像解析前失败时 actual image_id 为 None，所请求镜像仍由原 Command／部署绑定，不能用空串或请求值伪造实际解析／容器事实 |
| ExperimentActionReceipt | operation、status、result_refs、可空 frozen_ref、diagnostic_refs、受限 error_code；成功仅为动作事实，不能表示研究完成 |
| ExperimentRecord | action_id、request_digest、可空 command／execution／receipt。freeze 无 Docker Command；confirmed terminal 不可改，unknown 只能经同身份权威对账转终态 |
| ExperimentJournalView | scope／action_id／typed action／request_digest／deployment_digest／allowed_artifact_refs／run_deadline_at／同账派生 remaining_execution_seconds／records；不持久第二份 remaining |
| ExperimentToolResult | receipt、从正式 result 恢复的有限 summaries（result_ref／必填 publication:PublishedExperimentResult／method／split／query_count／retrieve_k／Metrics）、具名 corpus／queries 可空 BoundInputIdentity、已知 elapsed_seconds、未结 unsettled_seconds、有限 limitations；publication 只读复用同一不可变业务结果 owner，与该 summary.result_ref 绑定，不返回完整排名或私有标签 |

ExperimentJournalPort 只提供显式 scope／action_id 的 `load(...,request_digest)->ExperimentJournalView`、`bind_command(...,command)`、`record_execution(...,fact)`、`record_result(...,receipt)`。原 Conversation 已先接受顶层请求，Service 不再 accept 第二份。load 核对 scope／action／digest／部署一致性；同命令幂等，异命令拒绝。已回执恢复重建同一摘要和原耗时，零模型／execute；outer commit 保留这些字段。

ExperimentExecutionPort 为 `execute(command,inputs:tuple[BoundArtifact,...])->BackendOutcome`、`reconcile(command)->BackendOutcome`、`cleanup(command)`；BoundArtifact 是进程内 Ref／digest／bytes，不写入 Journal，Outcome 返回真实 execution、ResultBundle 原字节及有界诊断。首次 bind 和 dispatching 持久成功才 execute；恢复 dispatching／unknown 仅 reconcile。container/job 名由 command_digest＋实际子角色＋recipe／输入确定性派生，完整标签核对；先记录 create／start 意图再调用，丢响应先查询同名同绑定对象，未知不重建。候选完整 stdout 不可恢复时不能从有限日志造排名。receipt 落盘后才清理已核验终态与工作根内暂存，未知永不清理。

原公开 corpus／queries 为 Parquet，不能把二进制附件的存在计为模型已读。backend 的 ResultBundle 另交回本次受信 prepare 实际生成的 corpus_bytes／queries_bytes；Application 核对原 DatasetManifest.artifact_sha256 后，以原公开 Parquet Ref 为来源发布确切 UTF-8 JSON 只读投影，digest 由 owner 计算。开发 qrels 已是可读原 TSV；不创建或授权任何 test 标签投影。上述具名引用经原 ArtifactSourceInput 加入读搜集合，模型自行定位查询与文献原文；投影只恢复原字面材料，不预选错例或解释结果。它属于有原件摘要和重建规则的只读派生，不形成独立可写事实。

模型候选编程还需取得执行协议，不能靠猜测文件名或 stdout 形状。实验工具的版本化说明须给出固定入口 `python -I /inputs/program.py /inputs`：argv[1] 是只读目录，按 input_result_refs 顺序提供 rankings_0.json 等（query_id→doc_id→有限数值分数）、queries.json（query_id→原查询文本）、corpus_ids.json（文档 ID 数组），传 config_ref 时另有 config.json。仅 Python 标准库、禁网、不可安装依赖；stdout 只能是包含全部当前查询的同型排名 JSON，每查询不超过本次 retrieve_k，可为空排名，不附指标或日志；诊断写 stderr。说明不提供候选算法、权重、源码或胜出配置。

候选失败时，backend 除原 typed 执行事实外，发布实际候选 stderr（最多64KiB）及 stdout 原件（最多本轮16MiB）为具名诊断引用；模型按需读取而非整段塞入 Observation。stderr 的 UTF-8 解码替换按原 sandbox 诊断口径标明，stdout 保留原字节；不把日志当成功、排名完整性或评分事实。私有评分输入及任意 worker／宿主日志不借该入口公开。Artifact owner 新增窄只读契约 `read_limitations(ref, *, principal, owner) -> tuple[str, ...]`，复用 `_read_verified` 授权、版本和原字节完整性检查，返回现有 canonical limitations；ExperimentArtifactPort 的同名方法供 `_response` 从原 diagnostic_refs 恢复限制，保留未知状态原有限制，不另存日志或限制镜像，不向模型返回宿主存储记录。捕获缺失时不伪造诊断；启动早期 job/result 身份一致但尚无容器／镜像，且两路实际捕获均空时，只保留原执行事实。原 unknown 捕获尚无容器 ID、两路为空，而原 job 按同一 job_key／名称／镜像／输入对账后才确认容器 ID 时，该合法历史快照只保留当前执行事实，不发布空旧捕获，也不因旧 ID 未知截断原恢复。其他绑定仍逐项核对；旧捕获非空、两个已知 ID 不同或其他记录冲突均明确失败，不把 unknown 默认转成 failed 或成功。冻结 v1 未含这两项模型协议补齐；其终态和原身份保留，v2 实施后才启动依赖该协议的 P1。

工程契约的纯模型及无 IO 冻结规则移入 `application/retrieval_experiment/contracts.py`／`rules.py`，其余业务模型／Port／Service 同模块；infra 保留文件 Job 协议和 file_io、controller／sandbox／worker 唯一实现，backend／deployment 负责外层适配。Application 不导入 infra／scripts／Conversation；CLI 复用同一纯规则和引擎。worker 的固定相对生产路径源码清单与host一致，迁移后重建新镜像、新结果／冻结，历史身份不改。新原件／private refs 必须由新 owner 实际准备，worker新ID须实际构建取得，不预填旧ID。

按[主循环工具设计](conversation-loop-boundaries.md#工具粒度和模型可见面的收敛)控制可见操作及输出成本。当前工程没有现成通用计算入口，受控 Python 执行属于新增能力；只有当前研究一个消费者时，不预建通用作业或 Skill 平台。原 E1 可以使用固定方法完成，不强制编程；P1 通过明确的程序实现委托验收扩展，不能把工具次数或新增参数当成自主性。

实验用例位于 Application，经 typed Port 调用外层 runner，在 Composition Root 作为受治理工具装配。局部实现沿[代码地图](../../architecture/code-map.md)定位现有 ToolExecutor、Gateway 和 Artifact 协作者。工具是模块的调用边界；独立 use case、适配器和责任形成模块区分，只有拥有自主内循环才属于 Sub-agent。

| 一次明确实验 | 输入、输出与职责 |
| --- | --- |
| 输入 | 模型按上述 ADT 提交方法配置、适用输入结果／源码引用，test 只提交 frozen_ref；获准数据引用由本 run 许可部署恢复。Runtime 绑定程序、环境及实验资源，不由模型重复指定数据集、任意入口或路径 |
| 执行 | 固定程序解析、建索引、检索及计算；研究选择下一次做什么，工具不包办整套选型策略或代写报告 |
| 输出 | 实际状态、配置身份、已完成查询事实、原始排名／指标、错误、产物引用及已知耗用 |
| 复用与失效 | 绑定数据、实现、模型和配置；输入不变的有效结果可复用，选中基线时可使用同一份有效 test 结果；变更产生新结果，旧结果保留原身份 |
| 超时与恢复 | 保留实际作业身份，确认终态／停止或查询未知结果后再决定重试；HTTP 结束或线程 cancel 不等于作业停止 |

BEIR BM25 示例会删除并重建指定索引，适配器须绑定实验专用命名空间，不接受任意已有知识索引名。E1 允许“必要时验证组合”，首版能力范围须包括消费已有排名的受限融合验证，继续使用同一程序和 typed 入口；唯一引擎已实现 RRF(60)，生产接入已有正式引用、许可参数和消费链；真实模型是否选择及怎样消费由 E1 验收。缺少合法生产分支时不准入完整 E1，不能让模型判断需要后静默省略。是否调用仍由真实结果决定，不强制融合或预定提升。独立操作按现有并发安全契约执行，不因支持多工具就并行修改同一资源。

只读且可安全重试的调用沿准入后执行；建索引等跨副作用、授权或恢复边界的操作按 [EXE](../../devSpec/agentic-execution.md)形成适用 Command。执行失败如实返回；结果未知时先对账，不盲目重跑。runner 的实际进程／服务能力须落实 R-08，再用 F2 验收，不先建设通用后台目标平台。

### 2.4 执行哪份程序及输入输出

**独立工程入口已实现为 `python -m scripts.retrieval_experiment`，受信 worker 运行固定检索和评分，独立最小容器运行候选程序。** [工具说明](../../../scripts/retrieval_experiment/README.md)提供真实命令；生产调用已沿前述 Application／Port 及治理消费链装配，完整真实验收尚未完成。适配程序复用固定 BEIR 库、获准模型和预置环境，产生基线并在候选环境之外评分；候选程序处理获准排名，不能修改适配器、标注或评测口径。生产调用必须实际经过这些边界，不能只在 `evals/` 中提供替代调用。参考材料限制由[BEIR 源码核查](../../agentRef/task-benchmarks.md#8-beirscifact-检索实验材料)拥有。

```text
模型：选择一次实验及有类型的配置
  → Application：校验引用、许可方法、冻结配置及适用执行绑定
  → runner：在预置实验环境启动固定 Python 入口，管理作业身份和终态
  → 基线分支：retrieval_eval 调用固定检索实现
    候选分支：隔离执行确切模型程序，生成排名及诊断输出
  → 候选环境外：校验输出 → 受信评分 → 记录实际结果
  → runner 交回实际结果；Application 经共享 Artifact 入口提交配置和产物
  → 下一轮模型读取结果，分析错例，选择继续实验或组织交付
```

运行资源由已认证作用域、Policy 及部署配置绑定。现行调用只有前述 `run_development`、`freeze`、`evaluate_final` 三种 typed 操作；候选消费 `program_ref`、有序 `input_result_refs` 和可选 `config_ref`，最终评测只消费 `frozen_ref`。数据、split、固定模型、容器路径和额度由已接受操作及部署绑定，模型不提交 Shell、宿主路径或自由参数字典。正式 Schema 以本节 T2 契约和生产模型为准，不保留另一套通用执行参数。

冻结方案固定方法、模型、预处理、检索深度、依赖配置及数据快照；采用模型程序时同时绑定确切源码和依赖镜像。开发到 test 的查询集合切换由原协议允许，test 作业记录自身实际 split 和执行身份，不覆盖开发结果。融合使用对应 test 排名，不把开发排名或代码中固化的开发答案冒充新查询结果。原业务入口沿 Journal 及适用 Command 先记录冻结身份，再执行基线及选中方案；`frozen=true` 自报不能代替此事实，同任务不能换配置／源码反复 test 选型，重试仍绑定原方案。test 标注只交给获准评分端，不进入候选程序或生成侧 Context。

所有输入分支及嵌套方法对象严格拒绝未知字段。实际程序、依赖、固定模型的本地物化位置、工作目录、实验服务／索引、凭据、网络及硬额度由 Runtime／执行配置绑定，不作为模型参数；准入接受或拒绝原提议，不修正业务配置或提升权限。具体类型、许可方法及数值范围已在前述 T2 契约固定并装配；实际消费及 P1 未覆盖边界按[验证记录](verify_results/research-experiment.md)单列。

以下是构造的越界或协议违规输入，用于明确拒绝边界，不是当前模型已发生的行为，也不据字段推断恶意。缺少沙箱不会使这些字段自动成为合法参数：

| 假设输入 | 要改变什么 | 正确处理及责任 |
| --- | --- | --- |
| 追加 `command`、`script_path`、`python_code` 或 `extra_args` | 将固定实验换成任意程序或透传选项 | typed 协议拒绝未知字段；runner 从部署绑定固定入口，不将参数拼接为 Shell 或透传未知选项 |
| 追加 `dataset_path`、`output_dir: "../../knowledge"`、`es_url`、`index_name` 或 `upload_to` | 读取范围外文件、覆盖业务数据、改用生产索引或外发产物 | 严格参数协议拒绝未知字段；这些输入在调用前即不合法，不用它们证明沙箱的必要性 |
| 给 `program_ref`／`input_result_refs`／`config_ref`／`frozen_ref` 填其他用户或未许可用途的引用 | 借合法字段形状扩大读取或执行范围 | Application 在实际读取前核对当前身份、资源可见性、版本及获准用途；引用存在或可读本身不等于可用于实验／执行模型代码 |
| `retrieve_k: 10000000`，或追加更大 `timeout`／`memory_limit` | 扩大计算量或提高执行额度 | 前者按实际许可上限拒绝，后者按未知字段拒绝；实际耗用与声明配置的区别见下节 |
| 在 `evaluate_final` 中追加新模型／方法、`query_ids`、`qrels_ref` 或 `frozen: true` | 绕过冻结选型、缩小评分集合或接触 test 标注 | 拒绝不合法分支和覆盖字段，恢复原冻结事实及完整查询集合；实验协议与评分端权限负责此边界，沙箱不判断研究协议正确性 |

上述输入由参数、引用和 Policy 校验处理。固定入口、封闭参数及可信实现已经限制模型通过参数表达的动作；未知字段能被拒绝，不能据此再证明需要沙箱。运行时的资源耗用、停止及访问约束另按下节判断，不把两类机制混算为相同收益。

| 程序内工作 | 首例具体执行内容及边界 |
| --- | --- |
| 加载与格式适配 | 将当前获准的 corpus／queries Parquet 和 qrels TSV 校验并映射为 BEIR 所需数据结构，保留文档／查询 ID 及原件身份。现有 `GenericDataLoader` 的 JSONL 路径不能直接读取这份 Parquet；不得默默改用示例下载的另一份数据 |
| BM25 | 调用固定版本 `BM25Search`，连接 Runtime 绑定的实验 Elasticsearch 服务及专用索引；索引副作用沿前述执行契约治理，适配器核对实际写入和响应完整性，不能仅以调用未抛异常认定成功。只开放已验证的配置，不把上游构造函数尚未暴露的参数写成已支持 |
| 向量检索 | 调用 `SentenceBERT` 加载获准的固定模型快照，再由 `DenseRetrievalExactSearch` 编码查询／文档并排序；本例候选为已固定版本的 MiniLM。批大小等资源设置按实际环境约束固定，不默认开启示例的 remote code |
| 固定参考融合 | 消费两份已提交、同数据快照／split 的完整排名及明确融合配置，形成可复算的新排名；该参考分支的方法及参数在阶段 0 固定，不限制 P1 已授权的模型程序实现。程序不选择是否融合或扫参选优；test 使用冻结方案对应的实际 test 排名，不能复用开发排名冒充 |
| 覆盖与评分 | 先根据实际执行／响应事实区分已完成、零命中和失败／缺失，再按固定完整查询集合调用 `EvaluateRetrieval`／`pytrec_eval`，生成 nDCG@10、Recall@100 等获准指标。BM25 零命中可能不生成结果键，不能仅据排名字典补造已执行事实；真正完成但无命中计零，缺执行不缩小分母或补零掩盖 |
| 结果交接 | 交回实际程序／环境／数据／模型身份、有效配置及摘要、作业状态、逐查询完成事实、排名／指标／日志和已知耗用；Application 经正式 Artifact 写入口保存并返回合法引用，未知状态和失败保留原事实 |

### 2.5 单次数据规模、产物量与模型可见输出

**一次调用执行一个配置在一个 split 上的完整实验，不是一条查询，也不是整套研究。** 首例 BM25／dense 使用同一份 5,183 篇文档的获准 corpus；train 完整处理 809 条查询，test 完整处理 300 条查询。程序内部可按执行资源分批索引／编码／检索，批大小不改变本次覆盖范围，不要求模型逐批调度。融合分支消费同 split 已提交排名，不重新编码 corpus。

以下保留设计初期 `retrieve_k=100` 候选的静态规模估算，不是当前生产统一上限或本轮实测。现行typed Depth允许100—1000，实际深度由模型在范围内选择并绑定配置；本轮新E1实际选择1000，不能套用本表记录数或旧深度的融合指标。计算及源码身份见[规模核查](../../../.tmp/experiment-volume-context-20261020/volume-analysis.json)和[源码清单](../../../.tmp/experiment-volume-context-20261020/source-manifest.json)：

| 单个配置／split | 查询数 | 最多排名记录数 | 逐查询状态／指标记录数 |
| --- | ---: | ---: | ---: |
| train | 809 | 80,900 | 809 |
| test | 300 | 30,000 | 300 |

排名记录是 `(query_id, document_id, score/rank)` 对应的结果，不含重复复制的文档正文或全部向量；零命中或候选不足可少于上界，不能据实际排名数推断执行覆盖。此处“完整排名”指声明检索深度内的完整结果，不要求保存整个 corpus 的全部打分。两个方法各执行一次 train 和 test 时，排名记录合计最多 221,800 条，不含额外验证或重试；有效结果仍按原身份复用，不要求重复执行。文件字节、模型 tokens 及峰值内存均尚未实测，不能从压缩数据文件大小或记录条数直接换算。

固定 BEIR 的 `EvaluateRetrieval` 默认按 `max(k_values)` 取 top-1000，BM25 实现还会多取一个候选用于排除相同 query／doc ID，来源由[BEIR 核查](../../agentRef/task-benchmarks.md#8-beirscifact-检索实验材料)拥有。适配器须把合法 `retrieve_k` 绑定实际检索调用，明确排序、并列处理、排除及交付 top-K 的规则，并记录实际请求深度；评分 cutoff 单独声明。不能仅在报告里写 100、仍按默认取 1000，再裁剪以掩盖实际配置及耗用差异。阶段 0 同时固定检索深度、融合输入深度与指标所需深度。

输出分两种消费者组织：

- **完整机器产物**至少涵盖有效配置、声明深度内的原始排名、逐查询状态／指标、执行清单和有界日志，由 runner 交给 Application／Artifact 保存，供复算、复现及授权读取。执行端不将 corpus、全部排名、向量或完整日志打印到模型 Observation；具体文件格式、完整性和用户读取沿 [成果、Context 与共享产物](verify_results/research-evaluation-and-delivery.md#1-成果context-与共享产物) 及 R-04 验收。
- **模型下一轮收到的有界摘要**保留实际状态、有效配置及身份、预期／已完成／失败查询数、聚合指标、必要限制、已知耗用和合法产物引用。模型再按需读取开发集的逐查询指标及排名，选择错例并读取相应查询和文档原文；不要求穷举所有结果，也不能只凭聚合指标声称已分析实际错例。机器复算消费完整结果，语义核验消费报告断言所需的实际依据，二者不等于把全部排名送入一个模型请求。

摘要不能与全部排名混入超大 payload 后依赖通用裁剪。当前通用卸载观察的请求物化主要保留状态和 `retrieval` 引用，不能保证配置及指标仍留在当前输入；本例须在正式输出边界产生可独立消费的有界摘要和合法引用。具体字节／token 预算及按需读取窗口由阶段 0 的真实序列化、模型窗口和所需原文共同固定，不把现有 20,000 字符兜底直接当作本工具输出目标。单次实验成功只证明本配置的实际结果，不代表比较、报告或整体目标完成。

受控执行与领域适配分别承担可复用职责，但当前只有一个消费者，不预建程序注册平台。BM25 与向量方法由同一实验输入区分，不按算法各加一个工具；新增程序或方法先确认真实需求及验收。独立评测复算交付，不能以程序自产的汇总分数替代用户结果检查。

### 2.6 执行隔离与沙箱的最小边界

**参数准入约束调用提议，运行隔离约束已启动程序实际能访问和消耗的资源；作业控制管理执行及终态。** 此处把“执行隔离”限定为运行环境强制的进程、文件、网络、凭据和资源约束，避免把所有参数拒绝、超时配置和状态管理都称为沙箱。

| 机制 | 检查或控制对象 | 合法参数下仍需区分的行为 |
| --- | --- | --- |
| 参数／权限准入 | 提议的字段、范围、资源引用及授权 | `retrieve_k=100`、数据和模型引用均合法，可以接受；不会由此证明实际内存占用或程序已停止 |
| 作业控制 | 已启动作业的身份、运行、停止与终态 | 等待时限到达后，runner 确认实际停止或明确未知；调用方停止等待不等于程序终止 |
| 运行隔离 | 进程实际访问和消耗的资源 | 合法实验在编码时可能使用超预期内存，实际上限由执行后端落实；若实现发生路径或连接错误，最小文件／服务权限限制它触达业务资源 |

本例允许读取获准实验数据和模型、写本作业输出及实验索引，不赋予私人知识库或生产存储权限。固定基线落实参数／权限校验、作业控制和专用资源；P1 增加非受信模型程序，须在开放前落实文件、网络、凭据、资源和评分端的物理执行边界。不能仅由非法参数推导完整平台，也不能用固定入口或导入名单代替代码隔离。独立工程后端的真实隔离与故障检查由 [先行交付：独立实验工具 Implementation Plan](verify_results/research-experiment.md#31-先行交付独立实验工具-implementation-plan) 记录，生产调用的适用边界按[验证记录](verify_results/research-experiment.md)解释；动态安装和任意宿主 Shell 仍不在本切片。

2026-10-19 静态核对现有 [ToolGateway](../../../src/personal_agent/governance/gateway.py)、[ProcedureRuntime](../../../src/personal_agent/runtime/procedure_runtime.py)、[run_manager](../../../src/personal_agent/runtime/run_manager.py)及 [Compose](../../../docker-compose.yml)，身份见[本轮源码清单](../../../.tmp/experiment-execution-boundary-20261019/source-manifest.json)：Gateway 的线程等待超时及 `future.cancel()` 不证明执行停止；Procedure 的编排、run 的状态／lease 不提供操作系统资源隔离。现有 research worker 挂载应用数据并继承应用环境，不能原样作为本例最小权限环境。下述部署契约已在生产适配器装配；工程实测范围见 [完整落地 Implementation Plan](verify_results/research-experiment.md#32-完整落地-implementation-plan)，完整产品和故障验收尚未完成。

| 边界 | 首版最小设计及责任 |
| --- | --- |
| 可执行内容 | runner 启动固定镜像及驱动；基线执行固定实现，P1 将确切模型源码作为只读输入在候选容器运行。模型不能替换驱动／评分器、拼接宿主 Shell 或安装依赖，依赖及模型在准备阶段取得并校验 |
| 进程与额度 | 实验离开 Web／Agent 的业务执行线程，运行于独立受控进程／容器；runner 管理真实作业身份、时限、停止及终态确认。CPU、内存等硬限制由所选后端实际强制，输出／磁盘额度有可执行限制和失败行为；不能只把预算写进 Prompt |
| 文件与凭据 | 只把当前获准数据、固定模型及配置作为输入提供，输入只读；每次作业有受限输出／临时空间，执行环境不挂载应用数据、私人知识库、生产凭据或容器管理 socket。仅设置工作目录或 Python venv 不提供这样的访问隔离 |
| 网络及索引 | 常规执行只允许访问所需实验服务，数据和模型预置，不开放任意外网。BM25 使用与知识库分开的实验 Elasticsearch 实例／资源及专用索引；索引前缀本身不等于服务端访问控制。服务端作业的停止、写入与未知结果仍须单独对账 |
| 结果导入 | runner 只从声明的输出恢复结果，校验路径、格式、身份和额度，由原 Application／Artifact owner 导入；模型输出不作可信指标，评分在候选环境之外执行。子程序无共享存储发布凭据，沙箱成功不代表结果正确或研究完成 |

**首版推荐 Docker SDK for Python（pip 包 `docker`）配合已有 Docker Engine，实现固定基线及隔离候选程序的 runner，保持 A0 部署候选。** 仓库已有 Docker／Compose 部署，但尚未验证目标 Engine、权限或相应库；当前 `pyproject.toml` 未直接声明 `docker` 或 `psutil`。这一推荐基于本例确需的固定环境、挂载／网络、资源限制和终态查询，不能仅由非法参数推导。已有专用执行服务满足同一契约时直接复用，不为安装 SDK 再建沙箱平台；阶段 0 根据实际环境及成本选定唯一实现，不同时接入多个后端。

已核对 Docker SDK `7.2.0` 与 psutil `v7.2.2` 的实际调用链，外部事实及固定坐标由[执行库比较](../../agentRef/tool-execution-and-safety.md#5-固定程序执行可复用的库)拥有。本例选择 Docker SDK 作为首选适配候选：它把创建、inspect、停止及限制配置交给 Engine，工程只保留业务必需生命周期。`subprocess`／`psutil` 可用于仅需本地可信进程管理的更轻方案，但文件／网络隔离及跨平台硬限制仍需其他执行环境，不能作为静默降级或同等沙箱。

进一步走读 OpenHands SDK、Gemini CLI 和 OpenSandbox 的固定源码，实际装配与限制由[开源 Agent 运行隔离比较](../../agentRef/tool-execution-and-safety.md#6-开源-agent-的运行隔离装配)拥有。**本例以一次获准程序执行为隔离单位：容器运行固定基线或一份确切模型程序，约束覆盖子进程；评分在模型程序不可写的环境执行。** 数据／模型缓存按授权只读复用，不将整个研究 Agent 或多次实验共用的交互 Shell 放入同一环境。沿原执行身份关联容器 ID，复用现有事实及事件出口，不另设独立可写作业总账。

这样可直接按实验停止、归属耗用及导入产物，但增加容器启动与环境准备成本，须在阶段 0 按实际环境确认。尚无多用户远端 workspace、池化或统一交互执行的真实消费者，不引入 OpenHands agent-server 或完整 OpenSandbox 平台。源码比较只支持机制选择，不证明本工程已有隔离效果或 Harness 收益。

```text
Agent 提交一次实验
  → 现有工具治理 → 实验 Application 校验并绑定配置及资源
  → 实验执行 Port → 外层 runner → Docker SDK → 受控 Docker Engine
  → 固定镜像／驱动中的基线或确切候选源码 → 实际状态和输出
  → 候选环境外的受信输出校验及评分
  → 原 Application／Artifact owner 导入 → 下一轮 Agent 消费
```

以下步骤是同一业务 runner 的职责，不新增模型可见沙箱工具或通用 Job 平台：

1. **准备并绑定。** 从当前身份和获准引用恢复输入，固定程序／镜像 digest、实际参数、工作资源及截止条件；数据、模型和镜像在准备阶段取得。Engine 端点显式来自部署配置，不跟随模型输入或操作者临时 CLI context。SDK 管理连接只交给受信执行端；不向实验容器暴露管理 socket，也不默认扩大现有 Web 服务的宿主权限。控制端部署及输入暂存目录的 daemon 可见性在阶段 0 固定。
2. **创建后再启动。** 用 SDK `containers.create()` 创建已预备镜像，显式配置只读输入、受限输出、最小身份、内存／CPU／进程数及网络；记录容器 ID 与原执行身份后再 `start()`。创建前记录可对账的预期名称及配置绑定，响应丢失时按同一身份查询并核对，不盲目再建。镜像缺失如实失败，不使用会自动 pull 的便捷调用改变准备范围。
3. **观察并处理截止。** SDK 的 `wait(timeout)` 只限定一次 API 等待，runner 使用本次实验的截止时间，并服从 Agent 总预算；不能把请求超时或关闭客户端写成执行终止。到期请求 `stop`，必要时强制终止，再用 wait／inspect 确认真实终态；停止请求被接受也不能代替该确认。Engine 失联、响应不确定或缺少既有终态事实时保留未知，先对账后决定重试；停止实验进程也不能代替实验 Elasticsearch 的结果及写入对账。新实验调用须接好原 Gateway 的超时／重试边界，不能把默认瞬态重试直接变成重新启动；按同一冻结执行身份查询并协调继续，避免并发恢复重复启动、停止或发布。
4. **提交真实结果。** 取得退出／OOM 等实际终态、有界日志、源码／配置及声明产物；确认候选及子进程停止后，将输出导入受信端不可变快照，再从该快照校验和评分，防止评分期间候选继续改文件。结果沿原 Application／Artifact 提交，退出码 0 不等于查询完整或研究完成。输出／磁盘及日志上限按实际后端落实，挂载参数本身不提供通用目录配额。
5. **提交后清理。** 终态及必要产物保存后再删除临时容器和不再需要的资源；首版关闭自动重启及自动删除，防止后台重复执行或丢失恢复依据。恢复时用 Journal 中的原执行绑定和后端 ID inspect，保持事实 owner，不新建第二份可写作业总账。

纯本地向量／融合实验可关闭网络；BM25 所需实验 Elasticsearch 走预配置受限网络，不能同时禁网又声称可以访问外部服务。实验 Elasticsearch 自身的资源及在途操作按服务侧约束管理，检索容器的硬限额不代表整次实验总耗用。SDK 可配置相关限制，实际强制由 Engine 和宿主完成；CPU／内存、挂载／网络、输出限制均须按所选环境验证，不把安装库当作隔离生效。独立工具已调用真实 Engine 并单独准备依赖，未改变产品依赖或生产实现，检查范围见 [先行交付：独立实验工具 Implementation Plan](verify_results/research-experiment.md#31-先行交付独立实验工具-implementation-plan)。

SDK 不提供控制端宕机后的自动任务 TTL 或本工程 durable execution。环境 TTL 表示何时回收环境，与请求等待、单次实验截止及 Agent 总预算分别约束不同对象；当前不因外部平台有 TTL 接口就新增一套计时服务。阶段 0 明确控制端存活时的截止处理和失联后的对账；需要控制端失联期间也强制截止时，落实独立监督或后端期限能力，并核对其实际执行者及恢复事实后再作该主张。现有 E2 只验证无在途写入的已提交边界，不能转计运行中故障的自动停止成绩。

部署后端及具体限制在阶段 0 固定；未具备时保留环境缺口，不静默退回宿主无限权执行。固定可信程序可在具备等价权限和资源限制的专用进程环境中执行，须说明等价依据；普通子进程不能自动取得安全沙箱资格。P1 在本轮首个可编程切片内，须另取得其正式失败 baseline，并验证代码／依赖、数据出域及用户间隔离；不可信执行端与 test 标注、评分器物理分离。固定基线的限制证明不能转计模型代码隔离成绩。

验收复用 F1 的授权拒绝、F2 的实际停止／未知结果及 E1 的零越权修改和完整产物检查；这些用例未触达的挂载、网络及硬额度边界，在所选真实后端上单独记录适用工程检查及反事实，不把配置存在或作业状态当隔离已生效。不因本节要求模型再调用沙箱管理工具，也不自动增加产品 Judge。

### 2.7 本例可调用的工具与需要扩展的边界

当前入口沿[代码地图](../../architecture/code-map.md)装配，以下按 2026-10-22 的实现及实际轨迹解释；2026-10-19 的[工具边界审计](../../../.tmp/experiment-tool-surface-20261019/read-only-audit.json)只保留为初始缺口证据。正式工具面仍按配置、身份、曝光和 Policy 生成，注册本身不证明当前调用方可用。

| 本例工作 | 当前入口 | 责任及验证边界 |
| --- | --- | --- |
| 查实验方法、数据说明及原始资料 | `web_search`、`web_read`，分别依赖搜索和捕获配置 | 按研究需要调用，不把联网设为所有实验的必经步骤；获准数据和实现已提供时直接消费 |
| 检查用户提供的材料 | `inspect_artifact` | 支持已有合法引用的上传内容检查；文本等解释有预览限制，不能据此声称完整读取数据集。初始实验材料仍须经获准只读入口提供，不借会入库的上传路由改写知识 |
| 运行检索实验、冻结及正式评测 | `retrieval_experiment` | 实验 Application 绑定数据、候选、评分与冻结，唯一引擎执行；旧 E1 已实际消费，P1 模型候选链尚未验收 |
| 创建和修订程序／配置 | `write_artifact` 的 strict create／patch 分支 | 复用 Artifact owner、不可变引用和正式工具治理；读写参数及派生版本见[程序产物契约](program-artifact-contract.md) |
| 定位和读取结果、配置及错例材料 | `search_action_output`、`read_artifact` | 当前获准初始资料、实验产物和 Python 输出可经确切引用读搜；保留 owner、scope、版本及原件绑定，不开放任意文件路径 |
| 自主统计、连接数据及分析排名 | `execute_python` | 模型选择代码及合法输入，共享沙箱和额度；输出进入下一轮普通观察，不替代受信评分或强制研究步骤。实际自主调用成立，成文收益尚未通过 |
| 确认实际终态或处理停止 | Journal 的接受／Command／执行事实及执行适配器对账 | 沿同一作业身份等待、取消或恢复，unknown 不盲目重启；不是模型必须额外轮询的一组新工具。已有边界证据不代表全部故障窗口通过 |

一次实验返回聚合指标、逐查询指标及原始排名／查询／文档的合法引用，开发集错例分析可按需读原件；test 标注保持原授权隔离。大量排名可交由模型编写的程序计算，程序及其输出仍需分别审读。共享读取已接入，不增加结果、配置、查询和文档各自的读取工具；只有新的真实失败表明现有入口不足时，再考虑结构化查询。

建索引、调用向量模型和计算指标是一次实验内部的稳定执行步骤，不逐项变成模型工具。比较解释及错例语义分析由研究模型消费实际结果完成，不再包装一个内部调用 LLM 的 `analyze_errors` 来重复研究职责。工作清单、研究编辑、澄清、最终提交及适用核验沿原控制／能力协议，不能都计为新增业务工具。

实验结果由 Application 通过共享 Artifact 写入口提交，程序、输入清单及实际输出保留合法读取引用；报告沿当前提交及完成入口返回确切正文。内部原件按当前授权可读，文件发布、用户下载及打包不再作为 Agent 完成条件；旧文件交付口径仅见[历史记录](verify_results/research-evaluation-and-delivery.md#1-成果context-与共享产物)。

## 3. 机器交付与直接复现的实施契约（T3）

本节说明范围收回后的当前完成协议，依据[Agent能力范围收回与删除计划](verify_results/research-evaluation-and-delivery.md#7-agent能力范围收回与删除计划)收回，用户下载与结果打包不再执行；原封存清单及CLI复现证据只按旧身份读取，不作为Agent完成门槛。

### 3.1 T3 的具体持久及复现协议

当前SubmittedFinal及实际用量仍先存入Journal。Conversation恢复当前提交并校验引用；实验Completion服务核对同run接受身份、实际终态、完整开发结果、先冻结后test及确切选中配置，Python输入／回执与未结执行继续核对。缺口回到现有模型反馈链，不代写配置或伪造成功。

校验通过后直接将同一SubmittedFinal提交为FinalMessage并返回正文。完成、提交后恢复与已完成返回均不创建报告Artifact、ReproductionManifest、ZIP或下载资源列表，不新增持久完成副本。当前程序、排名、输入及双流继续保留在原Artifact，模型按既有引用读搜；这些内部事实不因删除打包而删除。

历史manifest类型和CLI reader只供现有离线封存消费者读取，不再装配bundle builder或自动发布。可用回答、实际执行、语义质量和安全审计分别报告；文件数量、下载和包内闭包不计Agent能力。Context常驻目标、有效成果引用、必要反馈和原预算，原件按需读取；历史压缩仍由主循环§3.11独立验收。

## 4. 推进、结束与恢复

一次完整委托按下列依赖关系推进；其中是否追加验证、选择哪份方案及何时收敛，由真实结果决定。每行表示应产生的成果，不固定模型轮数或工具调用路径：

| 工作 | 模型承担的选择与分析 | Harness 承担的执行与防护 | 可观察成果 |
| --- | --- | --- | --- |
| 建立实测依据 | 在获准配置范围选择并发起 BM25、向量开发实验 | 校验授权、配置及资源，运行程序，保存状态、完整排名和查询完成事实 | 两种方法同口径的实际开发结果；完整覆盖由执行事实核对 |
| 分析差异并选择下一步 | 从实际逐查询差异选择要读的查询、标注文献及排名原文，提出关于互补性的待验证判断，据此决定验证组合、继续取证或停止追加 | 提供有界指标摘要和可读原件引用，保留原目标、有效结果及预算，不预选有利错例或替模型决定后续实验 | 绑定实际材料的判断，以及实际改变下一项工作或收敛的选择 |
| 验证与收敛 | 有必要时验证获准组合；P1 自行实现候选、消费真实错误及指标后修订或停止，解释目标取舍 | 按确切配置／源码隔离执行，结果绑定输入；独立评分并计算规则排序，复用有效成果 | 被验证或否定的判断、实际运行的程序版本、明确方案及依据 |
| 冻结并最终评测 | 消费业务规则选定结果；存在开放取舍时提出有据的选中引用，继续最终评测 | 原业务入口绑定确切配置并先记录冻结身份，再执行实际 300 条 test 查询；绑定配置及覆盖事实，隔离标注 | 冻结方案的独立评测结果；已有同配置有效结果可复用 |
| 完成当前回答 | 解释比较、错例、取舍、最终评测和限制，提交完整报告 | 核对必要实际执行、引用、冻结与权限后返回同一Final；当前不接claim／语义verifier，不导出或打包 | 用户取得确切回答；内部结果可追溯，语义未验收单列 |

假设开发结果中 BM25 总体得分较高，但向量检索在部分查询上找回 BM25 未取回的已标注相关文献。程序提供逐查询指标和真实排名，模型自行选择并读取这些查询及文献原文，提出“融合能否保留 BM25 的优势并补回遗漏”的待验证判断，再决定是否调用获准融合。E1 可运行固定参考融合，P1 可以自行实现候选再隔离执行形成新排名；结果不支持时，模型应放弃该判断或在合法范围继续取证，不能为原建议编造提升。最终固定规则下的选优由代码计算，存在原目标内的开放取舍时由模型解释并建议，再绑定冻结；test 只评测该冻结方案，不回流改选。这是假设性决策示例，不是已观察的 SciFact 结果；未标注文献不直接当作负例。没有证据支持追加时，模型有据停止并完成交付；已有成果、原目标和额度在整条链中连续消费。

完整候选提交后，确定性检查执行覆盖、配置、数值、文件及权限。首轮按 [当前先完成的闭环](#1-当前先完成的闭环) 不进入 claim／语义 verifier；代码不能判断报告解释的全部语义，也不能把 `evals/` 的 UserOutcomeContract 当作生产完成合同。当前 `_complete_experiment_answer()`、提交后恢复及已完成返回均消费本次真实SubmittedFinal；没有文件发布步骤。原两份真实完整状态的完成边界回放不计新模型E2E或语义通过。

| 交接 | 生产者、内容及真实消费者 |
| --- | --- |
| 实验结果 | 实验 Application 产生绑定确切配置、数据、程序及完成查询事实的结果；沿合法 Observation／Journal 交回 typed 引用，供模型读取和决策 |
| 当前提交 | 按[统一 Loop 契约](conversation-loop-schema.md)通过原生提交／修订操作形成完整候选；SubmittedFinal 与原用量归 Journal，不另建包或产物集合 |
| 实验及产物检查 | 本业务确定性 validator 从原 owner 恢复上述事实，检查覆盖、冻结配置、口径、已有实验文件和授权；将明确缺口交回模型或将实际检查结果交最终出口，不生成语义 passed |
| 回答与Completion | 从原Journal及Artifact核对必要成果后，直接提交并返回同一FinalMessage；恢复重新校验，不补文件发布 |

硬事实失败交回明确缺口；限制或预算耗尽不计完整交付。阶段 1 的改动限定为实验绑定路径：prepare 后进入不依赖 claims 的报告提交，普通 answer 分支不回退到 `_verify_before_send()`；提前恢复待发布项、缓存返回及 `_complete_experiment_answer()` 均消费同一提交绑定。同步请求构造、中文 Prompt／Schema、binding 字段、Manifest 生产／读取和评测采集消费者，删除该路径被替代的 claim／review 前置条件，不保留双轨 fallback。原工具及权限准入、usage 提交、其他对话核验保持；不依赖全局关闭 Verifier 实现本例。

实施前定点源码核对明确两处迁移责任：原 SubmittedFinal 只在普通 verifier 分支创建，原可修复交付缺口反馈位于 claim 分支。当前切片已将本实验最终提议移到独立提交边界，额度内缺口交回动作模型；最终 `_complete_experiment_answer()` 只处理发布阶段事实，不替代额度内向模型交回缺口并重新检查的前置补齐机会。容量／预算已停止、结果 unknown 或授权失效时沿原限制返回，不由反馈循环扩大额度或重做未知副作用；发布错误只按原绑定恢复。不能只删核验调用而保留这两处隐式依赖。

本次是模型可见提交协议、跨模块绑定和恢复前提的实质变更，实施前按 REL 记录 ADR、固定受影响调用方及实际阶段输入。既有旧 run／Manifest 只作为封存证据，不在新生产路径推断或补写 submission；新准备身份从正式入口产生。不能为保留旧内部字段而造一个空 claim，也不能修改旧归档 Schema 或费用记录。

实施前从既有真实 Journal／完整 SDK 输入固定当前 prepare、报告提交与发布消费者，以及缺配置、文件缺失、混版和发布失败的反事实；尚无真实报告阶段时不能注入理想报告冒充模型消费。新初步闭环使用原自然 E1 请求和正式 Composition Root，真实模型连续决策、执行、成文及交付，按 [评估标准及评分资格](research-experiment-acceptance.md#4-评估标准及评分资格) 的初步结果记录。原来自动进入选证的实际 v1 说明存在额外阶段及其失败，不能据此声称 verifier 是整例未完成的根因或移除后必然提速。

E2 使用原样同 run 恢复：首次正式 POST 预填合法 `interaction_run_ref`，进程中断后仍使用相同身份、会话、run 引用及完全相同的 messages。新 Runtime 保留原 Journal、Artifact 和有效实验资源，恢复已提交输入及用量。当前局部 finalization 变量不是完整持久程序位置，因此必须以恢复后完成原交付验收，不能从对象存在推断成功；追加“继续”及跨 run 总预算不在该契约内。

E2 实施前发现的检查点缺口已完成[只读恢复链审计](../../../.tmp/research-capability-20261020/t5/e2-model-cost-checkpoint-audit.md)：实际 v10 的[revision 13](../../../.tmp/research-capability-20261020/t5/e1-v10-cost-checkpoint-observation-1/report.json)已接受本批两个实验请求，BM25 已成功、dense 在途；五份完整 SDK 已知 61,802 tokens，但 Trace 保存 44,634，缺本次已完成响应的 17,168。同批新 Plan 与 Context 也尚未提交，已接受请求却已关联新活动项。正式恢复只从旧 usage／Plan／Context 接续，工具恢复没有模型费用补源；telemetry、LangSmith 与评测 SDK 不是 canonical 恢复账本。若止于该版本且没有后续完整提交，已知费用和工作状态会缺失；正常进程仍可后续提交补齐。v10 已截止封存，其最终 revision 39 仍缺最后完整响应 74,391 tokens；没有执行恢复，不能记 E2 失败。两个在途窗口均不符合原 E2 无在途条件，独立缺口不抹去实验成功。


## 5. 当前范围与历史文件交付的关系

当前完成协议返回同一已提交回答，检查实际执行、冻结／test、权限和必要原件；不再生成下载包、ZIP、导出清单或报告副本。[范围收回及两次恢复记录](verify_results/research-evaluation-and-delivery.md)只保存该变更依据与验证，不恢复旧文件交付合同。
