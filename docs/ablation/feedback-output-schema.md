# 分类错误处理与反馈输出结构审查

初始审查：2026-10-19。第 1 至 6 节为跨任务检索与只读代码审计，项目模型调用、生产改动均为 0，没有执行外部框架。2026-10-20 的字段顺序诊断和未绑定片段加入诊断分别见第 7、8 节，各两次调用，生产保持。本文保存依据与分析，[唯一 Spec](../optimization/to_verify/research-goal-coverage.md#分类方法与反馈结构复审)拥有设计取舍。

**当前八类、四字段作为“待修问题报告”基本合理，尚无证据支持扩充 Schema 来修复海岸漏检。它的确定限制是：能约束已输出问题的结构与引用，不能证明模型检查了每个事实关系。**这里的合理指能够表达并被实际消费，未证明八类最优或各类能力达标。同一 Schema 一次漏报、一次准确报告，说明它能表达该问题；这不证明 Schema 对判断行为完全没有影响。

## 1. 先区分哪一步出了错

“分类错误”容易把不同失败合在一起。当前任务需要分清以下边界；这些是审计维度，不是新增生产分类或模型阶段。

| 边界 | 可观察的失败 | 应检查什么 |
| --- | --- | --- |
| 检查与支持判断 | 正文包含无据限定，却没有对应 finding | 原文、实际断言及同轨记录；区分未形成独立判断、支持关系误判、发现后漏输出。仅靠空报告不能分清内部原因 |
| 分类 | 已有 finding 指出该缺口，但选成另一个类别 | 同一待修关系的类别边界与反证条件 |
| 反馈质量 | 类别正确，解释、定位或证据错误 | 四项是否都指向同一实际差异，不能只算标签正确 |
| 修订 | 反馈准确，但新版仍错误或损伤其他内容 | 同轨实际反馈消费及完整新版，而非模型承诺会修好 |

海岸 G1 没有生成该项，repeat-C 则用 `citation_not_supported`、`a3`、`d3:59` 正确说明附加限定缺证。前次不能归为“已有 finding 选错枚举”。原生输出与 typed 报告一致，也没有结构层丢项。依据见[逐组加回](claim-verifier.md#211-最简输入逐组加回)及[定向追问](claim-verifier.md#213-直接追问未分类原因)。后者仍未确认原漏报原因。

## 2. 其他任务怎样处理分类错误

以下固定源码为 EVD A 级机制证据，论文和 issue 为 C 级线索。论文实验可以支持其自身任务结论，不能替代本工程真实失败与收益验证。详细调用链、缓存、版本和限制分别见[工程对照](../../.tmp/feedback-schema-review-20261019/engineering/engineering-review.md)及[分类调研](../../.tmp/feedback-schema-review-20261019/classification/analysis.md)。

| 场景与来源 | 实际做法与解决边界 | 对本项目的参考 |
| --- | --- | --- |
| 实体关系抽取：[Yan 等，AACL 2022](https://aclanthology.org/2022.aacl-short.55/)，§2、§3、表 2/3 | 分别评价对象／关系的识别与分类；比较八种联合或流水线结构，拆得更多并不普遍更好 | 分开看漏项和错类；不能直接推出增加模型阶段会改善 |
| 零样本信息抽取：[GoLLIE v5](https://arxiv.org/html/2310.03668v5)，§3、§6 | 使用类别定义、例外和示例，并专门训练模型服从准则；仍存在细类别被归到宽类别的错误 | 类名不能替代边界定义；训练与多种机制的联合收益不能算成“多写几句 Prompt”的收益 |
| 工具路由：[LangChain 1.4.0](https://github.com/langchain-ai/langchain/blob/79cab2dc7f58be720cac43db3677b4c1fd971f91/libs/langchain_v1/langchain/agents/middleware/tool_selection.py) | 按真实工具构造名称枚举及描述，结果实际进入 `bind_tools`。缺少 `tools` 等结构错误有界重试；合法名称中的误选、漏选不触发它 | 真实候选、可见说明、消费者要接通；结构重试无法识别合法标签中的语义错误 |
| 结构抽取／分类：[Instructor v1.14.5](https://github.com/instructor-ai/instructor/blob/63b729d3a01dc1605ab2636853a6cfef76c1d0a3/instructor/core/retry.py) | `from_openai → patch → Schema → SDK → Pydantic → 字段错误 reask`。只有校验器识别出的错才有针对性重试 | 已有合法类型中的错类、漏项不会自动触发校验；再加一层解析不等于加了语义检查 |
| 意图分类：[Rasa 3.6.21](https://github.com/RasaHQ/rasa/blob/d6829b6acc10fd9548798176bb0f9713107c1555/rasa/nlu/classifiers/fallback_classifier.py) | 前置分类排名的首项低于阈值，或前两项分差过小，改为 `nlu_fallback`，保留原排名 | 拒识须有恢复动作和适用数据；模型自己写一个置信度不能替代经验证的阈值，也不会补回未输出对象 |
| 少样本分类：[Calibrate Before Use，ICML 2021](https://proceedings.mlr.press/v139/zhao21c.html)，§3/4 | 用内容无关输入估计标签先验，再校正候选概率 | 适用于已有分类对象和候选分数；当前自由生成 findings 不具备同等前提 |
| 情感、问句匹配和阅读理解：[CheckList，ACL 2020](https://aclanthology.org/2020.acl-main.442/)，§2、表 2/3 | 按修饰、主客体、否定等语言能力检查具体行为，避免总体准确率掩盖局部失败 | 从真实轨迹审查“主体一致但修饰扩大”等关系；只借鉴能力维度，不引入本仓库已停用的单元测试或合成替代验收 |

两套工程实现的装配与消费者已固定核对：LangChain 提交 `79cab2dc7f58be720cac43db3677b4c1fd971f91`，Instructor 提交 `63b729d3a01dc1605ab2636853a6cfef76c1d0a3`。这里只做静态调查，没有在外部框架中动态运行。它们共同证明结构恢复的边界，不能证明本项目需要这些依赖。

公开问题也要区分解决对象。[LangChain #34358](https://github.com/langchain-ai/langchain/issues/34358)报告偶发缺 `tools`；[PR #39245](https://github.com/langchain-ai/langchain/pull/39245)已合并，固定版本核实了有界重试与默认显式失败。它解决结构错误。[LangGraph #8818](https://github.com/langchain-ai/langgraph/issues/8818)报告相似名称和描述影响工具选择，读取时仍开放，不能作为已解决的语义错类方法。

Instructor 的[动态标签示例](https://github.com/instructor-ai/instructor/blob/63b729d3a01dc1605ab2636853a6cfef76c1d0a3/docs/examples/bulk_classification.md)还有一项具体限制：ID 和名称只分别检查属于候选集合，没有校验成对对应；`instructions` 字段也未进入该次分类模型消息。因此应检查实际可见输入和真实 validator，而非看到字段就认定规则已执行。本项目类别没有这组 ID／名称配对字段，不据此外推本地存在同一缺陷。

### 解释与格式能否改善分类

[Turpin 等，NeurIPS 2023](https://papers.nips.cc/paper/2023/hash/ed3fea9033a80fea1376299fa7863f4a-Abstract-Conference.html)在受选项布局或暗示影响的推理任务中发现，解释会支持偏置答案且不提干扰。说明与标签自洽，不能证明判断正确，也不能还原原判断的原因。[ERASER，ACL 2020](https://aclanthology.org/2020.acl-main.408/)分别评价分类、理由定位和理由对预测的作用，提供了把这些质量分开审查的思路。当前 `error_description` 应承载可核查的差异，不能被当作内部判断过程的转录。

[格式限制研究，EMNLP Industry 2024](https://aclanthology.org/2024.emnlp-industry.91.pdf)比较约束 JSON、格式指令及先自由回答再转换。部分推理任务在严格格式下退化，分类任务却有不同趋势，JSON 并非普遍更差。其字段顺序观察也不能证明本项目 `category` 在前造成漏检：模型、任务和传输不同，当前 MiMo 另有 thinking 通道。自由文本后转结构还会引入转换边界，不能直接当修复方案。

## 3. 当前四字段是否合理

生产定义见[契约](../../src/personal_agent/capabilities/contracts/research.py)，现行语义见[研究 Prompt](../../src/personal_agent/kernel/prompt_templates/research.py)，引用检查和反馈恢复见[研究应用层](../../src/personal_agent/application/conversation/research.py)。本轮核对的坐标为：契约第 37–87 行；应用层第 675–708、737–761、830–903 行；实际消费在[会话服务](../../src/personal_agent/application/conversation/service.py)第 1599–1624、1692–1749 行。代码后续变化时按命名入口反查。

| 字段 | 当前用途与合理处 | 现有约束的边界 |
| --- | --- | --- |
| `category` | 八类表达原目标缺项、回答与 claim 差异、缺证和明确反证。消费者按类别理解修订；代码还据此限制目标类型和引用范围 | 枚举保证合法名称，不能判断语义选对。没有八套确定性修复流程 |
| `target` | 绑定当前原验收项、claim 连续片段或回答段。Runtime 校验真实身份，避免模型重抄已有正文定位 | 正确段落内仍有多个关系。身份准确不等于具体错误已定位清楚 |
| `error_description` | 说明同一个待修差异，供选证与 writer 回到原文修订；能表达“国家名有支持，海岸限定缺证” | 结构只要求非空；无法计算它是否完整、忠实及有助修订 |
| `evidence_ids` | 指回实际允许原文，Runtime 恢复证据供修订，避免把反馈解释当作来源事实 | 坐标存在和归属正确，不等于该原文支持判断；没有相应原文时允许空集合是必要的 |

当前八类为 `citation_not_supported`、`factual_conflict`、`source_attribution_conflict`、`normative_status_conflict`、`obligation_strength_conflict`、`evidence_presence_conflict`、`requirement_not_satisfied`、`answer_claim_mismatch`。四种明确反证类型并非 Prompt 中不存在：四类共用一段，分别描述事实、出处、规范性质和强度冲突，展开程度低于几个单独定义的类别。定义压缩是当前输入事实，是否因此造成误判尚未证实。

代码确定性执行两类区别：`requirement_not_satisfied` 必须定位原验收项，其他类型定位正文；`citation_not_supported` 只能使用本单元绑定原文，其他类型可使用其绑定与实际返回原文。反馈恢复主要按 `evidence_ids`，之后选证和 writer 结合原目标、原稿与原文决定取证、删去无据部分、收窄或改写。类别既有用途，也不是完整修复指令。

当前实发 MiMo 使用 `json_object`，完整 Schema 作为 System 文本发送，返回后再做 typed 与动态引用校验。它不等于供应商在生成时按完整 Schema 严格约束解码。即使采用严格解码，[JSON Schema 官方说明](https://json-schema.org/understanding-json-schema/reference/annotations)也将 `description` 等列为说明性关键词；结构校验不会自动执行其中开放的事实语义。

`evidence_ids` 不应一律要求非空。尚未取得所需资料、无绑定来源或目标缺项时，强制填一个坐标会诱导无关引用。当前拒绝重复与越界坐标，但不将缺少原文转换成虚构依据。

G1 与 repeat-C 的 Schema System 文本相同，均为 2,434 字符，SHA-256 为 `e1ce887e39d9b13494fc888194281c50219de7804ce62d1d598b5782dfa66897`；八类、四个必填字段和三种 target 一致。没有 `maxItems`，也没有同一 target 只允许一条 finding 的限制。不能将漏报解释为“a3 已经报过别的错，所以结构容不下海岸”。原始 SDK 坐标见[本地审计](../../.tmp/feedback-schema-review-20261019/local-audit.md)。

## 4. 现有设计的限制与待证问题

**已证明的限制是：空 findings 没有逐关系覆盖证据。**它的协议含义仍是完整版本未发现待修问题，模型仍须完成全部检查。完成链要求当前完整版本具有适用空报告，再交付同一确切回答。版本绑定能防止复用旧通过，不能证明每个限定都接受过正确判断。代码也没有“轻微错误可忽略”的 severity 过滤；G1 的模型原生报告中已无此项。

这与 `error_description` 质量仍由模型负责共同构成语义边界。Schema 可以接收正确报告，也可以接收结构合法的错误报告；该能力不足不等于再加一个字段便有了独立校验能力。

以下结构选择值得审查，但本轮不将它们写成已证根因：

| 选择 | 具体疑问 | 缺少的决定性证据 |
| --- | --- | --- |
| 一个平面类别枚举 | 原目标、稿件一致性、支持状态和冲突子类属于不同判断维度，存在分类负担。Prompt 已规定若干优先级与去重，不要求这些职责彼此互斥 | 已报或未报关系中，类别判据持续影响输出或修订的同轨证据 |
| `category` 排在前面 | 生成标签时会不会过早采用一个整体解释 | 固定其他输入的因果对照；不能从 JSON 字段顺序推断真实判断先后 |
| 自由文本解释 | 是否把实际断言、已有支持、剩余缺口压成一句后丢失关系 | 准确发现却因解释结构无法表达或被消费者误解的真实链；新增字段也可能重复或产生新误述 |
| 回答按段定位 | 段中多关系能否稳定精确修订 | 正确反馈因定位粒度而修错内容的同轨结果；海岸成功 finding 已能定位，不足以证明必须改定位结构 |

## 5. 当前取舍与后续判断标准

本轮结论是保留八类与四字段。首先把评价对象从“枚举选对了吗”恢复到“实际错误关系被报告了吗、报告是否准确、真实修订是否成功”。这复用[冻结指标](claim-verifier.md#21-具体评估指标)：A1 检查漏项，A2 检查合法关系误拒，A3 分别审查类别、解释、位置、证据，A4 检查实际消费及完整新版；不改变 `v1` 定义、原标签或历史分母。只在已输出 finding 上算分类正确率，会把海岸这样的未报项排除在外。

定义或结构的调整必须对应已定位的缺口：有证据指向类别判断或映射，再优先审查类别边界；准确差异无法表达或不能被消费者使用，再调整字段或定位。类别混淆也能在输出前发生，因此未报项仍要审查发现、支持判断和报告边界，不能直接认定与分类无关，也不能靠新增“修饰错误”类别代替定位。上一轮扩写主体、范围等支持判据仍失败的[既有证据](claim-verifier.md#29-来源支持判据候选验证)保留，不把同义扩写重新包装成方案。

置信度用于决策需要校准数据和消费者；拒识需要明确恢复语义，不能变成空报告放行；多个独立问题已可分别输出 finding，单个错误关系是否需要多个类别则没有本地必要性证据；severity 若用于放行，会引入新的错误豁免决策，仅作诊断也需证明用途；逐项 `checked` 或 `support_status` 仍是模型自报，不能单独证明完整覆盖。上述字段及额外模型阶段均没有本地收益证据，本轮不准入。

本轮没有生产实现与删除项。外部资料证明方法与边界，不能证明当前缺陷已修复；现有反馈能表达海岸缺证，也不代表发现稳定或后续 A4 已通过。

## 6. 证据与检查

本地构造链与 Schema 对照保存在[本地审计](../../.tmp/feedback-schema-review-20261019/local-audit.md)。外部固定代码、issue 快照及论文缓存的 URL、版本和 SHA 分别保存在[工程清单](../../.tmp/feedback-schema-review-20261019/engineering/artifact-manifest.json)、[分类来源](../../.tmp/feedback-schema-review-20261019/classification/sources.json)及[补充来源](../../.tmp/feedback-schema-review-20261019/primary/sources.json)。部分 arXiv 网页经 web 阅读成功、本机下载证书失败，按来源清单保留差异，不冒称全部本地可重放。

本次范围的正文、索引、Spec 与 Future 同步结果，以及文档链接／锚点／空白／围栏、根规范检查和归档哈希检查，统一记录在[只读检查记录](../../.tmp/feedback-schema-review-20261019/validation.json)；新材料身份见[封存清单](../../.tmp/feedback-schema-review-20261019/artifact-manifest.json)。本轮无产品行为变化，不执行 Product E2E、模型回放、单元测试或生产 lint／类型／层次检查，不据文档检查宣称语义收益。

## 7. 字段顺序敏感性诊断

2026-10-20，已执行 A1 原序和 B1 候选，**海岸主目标两次均未报告，字段顺序候选没有解决本次漏检。**B1 返回空报告，按预声明 `candidate_target_not_reported` 停止，B2／A2 未执行。本轮不改生产，也不继续更换顺序求命中。

完整输入、唯一变量、条件配对、判据和成本由[唯一 Spec](../optimization/to_verify/research-goal-coverage.md#反馈字段呈现顺序的有界诊断)在派发前固定；计划与原始身份见[封存计划](../../.tmp/feedback-schema-next-20261020/run-1/plan.json)。只将 Schema 的 finding `properties`、`required` 和实际支持 Prompt 一处四字段列举，从 `category,target,error_description,evidence_ids` 改为 `target,error_description,evidence_ids,category`。八类四字段及校验器、分类定义、完整六条 claim／七段回答／原会话要求／实际资料均保持。

两组实发请求均为 173,213 UTF-8 字节，用户消息逐字相同；A1 与旧原序完整 SDK 相等，B1 只含上述顺序差异。不是删 claim、缩短材料、删除分类或先生成解释再调用分类器。沿 `mimo-v2.6-flash`、thinking、`json_object`、131,072 输出和 2,400 秒物理时限；本诊断只看首次响应，双方结构恢复及服务重试均为 0，不评价生产恢复。具体准入与八维 critic 见[设计审查](../../.tmp/feedback-schema-next-20261020/local-design-review.md)、[方法审查](../../.tmp/feedback-schema-next-20261020/method-review.md)和[运行器审查](../../.tmp/feedback-schema-next-20261020/runner-review.md)。

| 观察 | A1 原序 | B1 候选 |
| --- | --- | --- |
| 海岸主关系 | 未报告，0/1 | 未报告，0/1 |
| 目标 A3 | 未形成，不能给各字段虚填成绩 | 未形成，不能给各字段虚填成绩 |
| 三个合法控制误拒 | 0/3 | 0/3 |
| 实际 finding | 一项声景／测试独立性支持缺口 | 空报告 |
| 其他反馈审读 | 核心缺口成立，但解释额外引入正文未断言的 Zenodo 来源条件；整项完整解释记未决，确认误报 0 | 无其他 finding；空报告不等于整稿有据 |
| 原生 finding 键序 | 原序，实际可观察 | 空报告，无可观察键序 |
| 输入／输出／总 tokens | 61,295／2,377／63,672 | 61,295／1,788／63,083 |
| 调用秒数 | 96.131 | 56.511 |

两次原生均正常 stop，typed 与 content 相等，SDK 等于预期；没有解析丢项、结构恢复、服务重试、未知用量或成本复审。两逻辑／物理共 **126,755 tokens、152.642 秒**，低于原上限。模型采样温度、seed、权重版本和缓存未控制；单次耗时差不作性能收益，两个调用也不估计稳定率。独立语义审读见 [A1](../../.tmp/feedback-schema-next-20261020/A1-semantic-review.md)、[B1](../../.tmp/feedback-schema-next-20261020/B1-semantic-review.md)，由代理审读并经执行者核对，没有新增独立人工盲审。历史分母、标签和冻结 v1 保持。

### 同轨记录增加了什么信息

[A1 同轨审读](../../.tmp/feedback-schema-next-20261020/A1-decision-audit.md)显示模型整体接受地点和生态概括，没有形成海岸限定的可见独立支持判断。不能据此说它已发现海岸缺证后忽略，或已判错却漏输出。

[B1 同轨审读](../../.tmp/feedback-schema-next-20261020/B1-decision-audit.md)给出了更具体的范围问题：模型接受声景表述时借用了返回目录的 `d3:129`，该行确在输入中，却不在 c3／a3 的 49 条绑定原文内；对训练独立性还采用了从来源、测试用途和匹配子集作出的推断。**目录里可见资料被用作本单元引用支持，突破了当前来源支持的范围。**这是本次记录与实际材料可交叉核对的依据使用问题，不证明海岸漏检的唯一原因，也不证明它由顺序变化造成。

当前 validator 只校验实际 finding 的目标和 `evidence_ids`。B1 返回空数组，没有引用供该规则拒绝，因此结构合法没有阻止上述正向接受。这补充了第 4 节的语义边界：不仅缺少逐关系覆盖证明，也无法从空报告核对模型放行时实际采信了哪些资料。增加一个自报字段仍不能自行提供独立校验。

### 结论与退出

候选呈现已实际发送，但 B1 无 finding，不能证明模型按新序生成了单项报告；thinking 的内部判断先后也没有被控制。本轮只能确认这份完整输入下候选没有修复目标，不能得出字段顺序普遍无影响、原序必然致错或改序必然使报告变差。

已观察到的主问题仍是具体限定没有形成可见独立判断；B1 借用未绑定材料则是[既有输入归属问题](claim-verifier.md#24-持续漏检的输入归属审计)的再次复现，早期记录已出现 d3:129，不能称为新根因。A1 解释包含正文未断言的 Zenodo 来源条件，它是否增加了修订要求仍未决。两项分别按现有来源支持与 A3 反馈忠实性审查，不新增生产错误类型。下一核实边界是正向接受所用材料是否属于本单元，以及是否覆盖实际限定；累计尝试与旧停止决定保持，不预设新字段、裁剪方案或拆分模型阶段，不把 B1 的声景范围问题当作海岸唯一根因。

实际执行 `run_order.py prepare`、两次 `run-next` 和各自 `review-one`、`finish`，脚本路径为 `.tmp/feedback-schema-next-20261020/`；限定 Ruff 通过，没有单元测试或 Product E2E。本轮没有 writer 消费，A4／A5 未测，不关闭完整漏检问题。结果见[只读投影](feedback-field-order-results.json)、[运行封存](../../.tmp/feedback-schema-next-20261020/run-1/artifact-manifest.json)；生产 262 个 Python 文件、配置及冻结指标身份通过复核。本文及关联文档的检查、最终文档快照与补充封存见[交付检查](../../.tmp/feedback-schema-next-20261020/validation.json)及[完整清单](../../.tmp/feedback-schema-next-20261020/documentation-manifest.json)。

## 8. 未绑定原文片段的加入诊断

2026-10-20，完成 P1／U1 两次调用，按 `reported_scope_invalid` 停止。**P1 报告声景缺证，U1 未报告该项，并把加入的未绑定资料称为绑定原文；两组都准确报告海岸缺证。**本轮没有复现海岸漏检，也没有完成反向配对，不能证明该片段是海岸漏检的根因或估计影响概率。

### 同一个旧问题，本轮只增加一个对照

[早期归属审计](claim-verifier.md#24-持续漏检的输入归属审计)已记录稿件混入证据概述，以及借用未绑定 d3:113、d3:129。B1 连同一条 d3:129 都再次使用，属于旧问题复现。归属标签、去重、原文阅读隔离均已有尝试，未证明稳定修复；本轮不重试这些改法，不重置累计尝试或旧停止决定。

d3:129 同时是 c4／a4 的合法引用，直接从完整输入删除会损伤其他单元。因此两臂采用相同的单稿来源任务，保留原 a3 全文及其全部 49 条绑定，原序八类四字段、校验器和模型参数不变。文档 Observation、URL、身份、元数据也相同：P 臂的额外资料正文为空，U 臂只加入真实连续 d3:120–131，包括数据字典、Train 与 Test_5s 的上下文。这 12 行始终未绑定 a3，未加入其他 claim 或回答。唯一数据变量是该片段是否可见，长度随之变化，未单独分离内容和长度影响。

主终点是“八个评测集均按声景形式组织”缺少本单元支持，海岸限定独立计分；评测规模和国家名称为两项合法保护关系。完整判据、预算和条件配对由派发前的[唯一 Spec](../optimization/to_verify/research-goal-coverage.md#未绑定原文片段的加入诊断)拥有，冻结身份见[计划](../../.tmp/citation-boundary-probe-20261020/run-1/plan.json)。这是实际单元裁剪诊断，未覆盖完整阶段、claim 作用、A4 修订或 A5 交付；原整稿三个合法控制不在输入中，标未覆盖，不能填 0/3。

### 实际结果与反馈质量

| 观察 | P1：无额外原文 | U1：加入未绑定片段 |
| --- | --- | --- |
| 声景主关系 | 准确报告，1/1，目标 A3 四项成立 | 未报告，0/1，目标 A3 未形成 |
| 海岸次关系 | 准确报告，1/1，A3 四项成立 | 准确报告，1/1，A3 四项成立 |
| 两项合法关系误拒 | 0/2 | 0/2 |
| 训练独立性反馈 | 正确指出本单元缺证，没有推成反向事实 | 错判为有明确反证，并将额外资料称为绑定原文 |
| 其他反馈审读 | 三项均有依据，无未决 | 两项中海岸准确；一项明确冲突反馈不成立，无未决 |
| 诊断要求的绑定范围 | 无违规 | finding 0 使用未绑定 d3:120、d3:122，违规 |
| 输入／输出／总 tokens | 8,345／2,018／10,363 | 8,863／2,325／11,188 |
| 调用秒数 | 57.842 | 73.313 |

U1 的具体错误是：d3:120 说整个数据字典包含 Train、Test_5s 和 Test；d3:122 介绍 Train 来源。**一个数据字典有训练部分，不能证明其中测试部分与训练数据不独立。**它把数据容器与被评测试部分混用，不能满足 `factual_conflict` 所需的同一关系明确反证。训练独立性仍然缺少 a3 的绑定支持，正确做法应保留缺证边界，不能据此推出反向事实。

沿用审读类型将这项记为 `confirmed_false_positive`，仅指“明确反证”反馈不成立；不表示训练独立性已被证实，也不算作受保护合法关系的 A2 误拒。其类别、解释及反证支持错误，a3 定位存在。实际报告与全部 finding 的执行者审读见 [P1](../../.tmp/citation-boundary-probe-20261020/P1-semantic-review.md)、[U1](../../.tmp/citation-boundary-probe-20261020/U1-semantic-review.md)；本轮没有独立复核、盲审或额外模型 grader。

### 引用门禁究竟检查了什么

U1 违反的是本次最简任务“evidence_ids 只用本单元绑定”的要求。原生产动态 validator 实际接受该报告：[应用层](../../src/personal_agent/application/conversation/research.py)的 `validate_research_support` 对 `citation_not_supported` 限于绑定集合，对 `factual_conflict` 等类别允许实际返回原文作为反证。**这个权限本身有用途，错误在于本次资料并不构成反证。**不能把诊断的范围违规写成生产确定性门禁失效，或据此禁止使用所有未绑定反证。

这说明结构合法的错类可以携带错误的证据解释通过形状与引用检查；当前已观察到一项错误分类反馈，但不能把其他轮的全部漏报统称为分类错误。U1 未报告声景并不证明它具体如何接受声景；本轮无需依赖未观察到的内部判断来成立归属及反证误读结论。

### 停止、成本与边界

按预声明范围违规停止，U2／P2 未执行，没有为凑反向配对忽略错误反馈。两次 SDK 均与封存载荷精确相等，原生 content 与 typed 报告一致，正常 stop，无结构恢复、服务重试、未知用量或成本复审；共 **21,551 tokens、131.156 秒**。温度、seed、权重快照未控制，当前只是一对观察，不估计稳定率或唯一因果。

执行 `run_probe.py prepare`、两次 `run-next`、各自 `review-one` 与 `finish`，代码在 `.tmp/citation-boundary-probe-20261020/`；完整结果见[只读数据](citation-boundary-probe-results.json)，原始请求、响应、审读及停止身份见[运行清单](../../.tmp/citation-boundary-probe-20261020/run-1/artifact-manifest.json)。生产变化为 0，262 个生产 Python 文件、配置和原冻结 v1 保持。文档及归档检查见[检查记录](../../.tmp/citation-boundary-probe-20261020/validation.json)与[收尾清单](../../.tmp/citation-boundary-probe-20261020/documentation-manifest.json)；没有运行单元测试或 Product E2E。当前对照结束，不继续同义 Prompt 修补或重采，完整漏检问题仍未关闭。
