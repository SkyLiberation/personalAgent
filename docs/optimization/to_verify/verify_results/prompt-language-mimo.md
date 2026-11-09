# 英文 Prompt 与 MiMo task2 验证

本次按[语言与配置Spec](../prompt-language-selection.md)执行。语言、生成模型与评分模型共同改变，只比较组合配置的观察结果。旧生成原件只读复用，不把 DeepSeek 的历史成绩直接与 MiMo Pro 混比。

## 实现与先行证据

- 默认中文，Runtime显式选择不可变Catalog；英文有45条既有模板镜像及22条提取的指令包装，共67条。Schema／工具说明有61条译文；原用户消息、机器字段、来源和执行事实不改。
- `.tmp/english-mimo-task2-20261027/actual-input-audit-v3/` 封存289个真实SDK请求的4,339次Schema投影，原45条中文模板保持；17个真实工具经当前构造链产生18个动作，14个意图／摘要／研究／核验阶段Schema与字面常量反事实通过。它是零模型物化诊断，不是产品语义通过。
- 20条Application包装与36个实际意图窗口保持；独立评审发现的基础工具说明缺项、嵌套Schema缺项及常量误改均已闭合。重复缺项出现后先停止英文路径，按gettext完整提取／未译清单机制复审，再完整盘点，未采用中文fallback。
- `.tmp/em27/j/qualification/` 的MiMo Pro资格为正例1、负例0，5,183 tokens、未知0。官方Judge Prompt、参考答案、解析与三次协议尝试保持。
- `.tmp/em27/sm/` 从正式Web入口提出中文CSV行数／列名请求，经MiMo Flash和Python执行，正确返回8,807行及12列；3次模型请求、22,761 tokens、39.594秒、未知0，进程停止后封存。它使用原CSV的独立自然请求，不是task2题面翻译；direct/none不构成完整核验后的发布证据。

## 完整运行身份与当前状态

源码冻结在 `.tmp/em27/code/`，3,743个文件由 `.tmp/em27/identity.json` 绑定；新生成在 `.tmp/em27/c/`，复用原官方英文材料 `.tmp/ls25/t01/materials/`。本次完整34轮计划在首轮中断：正式入口返回HTTP502，原始MiMo响应的`finish_reason=content_filter`，Runtime记录为不可重试的`provider_rejected`。没有正式答案，后33轮未执行；这不是新答案0分，无法比较生成正确性。

旧对照为最近一次完整的MiniMax／中文Prompt轨迹：`.tmp/cf27/c/` 的1—20轮、`.tmp/cf27r/c/` 的21—23轮与 `.tmp/cf27q/c/` 的24—34轮。它们已在本次零模型审计中校验封存；MiMo Pro重评已完成，分数与费用见[评测盘点](../../../evals/02-current-case-inventory.md#2026-10-27-英文prompt与mimo-task2)。历史DeepSeek2/34及更早的布局前3/34都保持原身份，不重生成或重标。

生成上限60M、授权34小时，每run10M／40次决策／3,600秒；评分由 `.tmp/em27/j/` 同一1M账本累计资格、旧34轮及新34轮。新答案评分阶段未到达，空报告保留`not_reached`，没有新增评分调用。`.tmp/em27/comparison.json`记录完整比较为false、有效配对0，改善／回退为null，不把未执行填0分。

## 中断、输入与成本核对

- 新生成14次实际HTTP，632,653个已知tokens、1次未知用量，运行2,263.453秒后进程停止并封存。未知用量来自一次480秒墙钟超时，既有有界重试随后恢复；最后的content_filter响应本身具有完整usage并已计入已知消费。
- `.tmp/em27/audit/`确认冻结源码未变、首轮原官方英文请求未改、14次请求均为MiMo Flash／thinking.enabled，247个实际工具Schema和说明均为选中语言，全部初始system的中文字符计数为0。用户、工具及外部内容不参与语言改写。
- 同轨迹显示模型成功执行Python并反复核对统计口径，随后检索题面特征短语、读取现有程序；工作计划完成仍继续执行。具体输入污染、拒绝位置与归因边界见下节，不能据此认定英文改善或恶化了目标遵从。
- 本次生成含中文smoke共655,414个已知tokens；评分含资格与旧重评共226,630，未知0。新活动合计882,044个已知tokens，另有1次未知；旧34轮生成没有重跑或重复计入新活动。

本次真实请求没有显示新增SDK参数、Schema或语言装配错误；阻断来自服务方拒绝。保留原拒绝与停止事实，未重发改写后的受拒请求、忽略过滤状态或另换模型继续本次轨迹。完整英文34轮及同评分器质量比较仍未完成，RUN-1未通过；语言资源和局部构造证据保持其实际边界。

执行脚本与进程状态在 `.tmp/english-mimo-task2-20261027/`。静态检查、分层检查及开发规范检查通过；未运行停用的单元测试。当前成绩与未到达范围由[评测盘点](../../../evals/02-current-case-inventory.md#2026-10-27-英文prompt与mimo-task2)登记，未取得完整新生成分数或发布证据。

## 首轮 content_filter 的实际输入与返回审计

2026-10-27 的补充只读审计绑定第 14 次物理请求，新增模型调用为 0。报告、消息索引、14 次调用对照及已核对的封存校验和位于 `.tmp/task2-content-filter-analysis-20261027/`。原封存未修改。

**已确认的拒绝阶段。** 实发文件为 `.tmp/em27/c/sdk/f70d012cc5ec48239ab4d512f2111482.http.request.json`，与候选 `7e65ad9fed064f0e95084ffc2f9f9798` 的消息和工具定义逐项相同。上游先返回 HTTP 200 及 SSE，约 270 秒后完成响应；原返回第 11 行是 `finish_reason=content_filter`，第 15 行正文是 `The request was rejected because it was considered high risk`。该请求输入为 100,622 tokens，生成 20,923 tokens，其中 20,922 为推理，低于 32,768 输出上限。生成过程已发生，不能解释为零 token 入口拒绝；实际被审核的对象究竟是输入、输出或组合，响应没有标明。Adapter 按终止标记映射为不可重试的 `provider_rejected`，Web 入口再返回 502；不是评分器的业务判分。

**已确认的输入污染。** 原题是 CSV 分析，模型为确认统计口径，额外检索 `"mature exposure" "genre focus" Netflix launch score guarded CAGR`。AnySearch 返回 10 条结果，其中第 1、2、3、4、6、8 条含明确成人色情站点内容。标题、摘要和 URL 经引用行物化进入工具消息 14 的文档 `d6`，不需要调用 `web_read` 就已经进入模型输入。后续第四次搜索又引入 IMDb 裸体列表标题，位于消息 22 的 `d10`。这些内容不来自用户原题或工具说明。本次请求共有 28 条消息和 19 个工具定义，历史推理另有 176,803 字符；工程侧可确认的问题是额外搜索把低相关内容带进了当前分析。

**本次不能把色情片段定为唯一触发原因。** 第 7、8、9、11、12、13 次已完成的成功调用都含同一批成人片段，第 10 次是超时，不能当作成功或拒绝。最后一次相对前一次，用户题面、工具定义、已有原生历史前缀均未变，新增的是上一模型消息和两次文件读取。因此“出现这些片段就必定拦截”的解释不成立；这些内容是明确污染与候选风险，尚无本次审核规则的因果证明。

**最靠近截断的新增内容。** 最后返回的 85,192 字符推理仍在讨论计算范围和数据清洗，末段转为检查国家名称中的逗号，并自行举出 `Taiwan, Province of China`、`Korea, North` 等例子。这些例子在完整实发请求中为 0，在此前成功模型输出中也为 0；最后段落还出现 `Hong Kong`，该名称在较早输入中已有。这把输出端的候选位置缩到国家／地区名称讨论，但不能据截断位置把政治类审核、某个词或某条规则写成已确认根因。

**证据边界与确认入口。** 当前捕获保存了实发 HTTP 请求、传输摘要和 SDK 聚合响应，没有逐帧 SSE 原文。已保存对象没有审核类别、命中片段或规则 ID，无法恢复可能未留存的服务方扩展字段。[MiMo 接口定义](https://mimo.mi.com/docs/en-US/api/chat/openai-api)只把 content_filter 解释为过滤器导致内容被省略；[官方错误说明](https://mimo.mi.com/docs/en-US/api/guidance/error-codes)将内容审核与额度不足、限流分别列项。MiMo 仓库[用户报告#76](https://github.com/XiaomiMiMo/MiMo/issues/76)有相同提示及国家／地区合规指令误拦的复现，但其模型为 2.5 Pro、生成量为 0 且无维护者确认，仅为外部线索，不能代替本次证据。

要确认本次具体审核类别，应由服务方按响应 ID `c5cd22a1-e95e-424f-99f0-efc178ee960d_6f095dc0700d4c33a782dd8c95c42045` 查询审核记录。本次已定位调用、输入污染来源、截断前内容和异常映射，具体触发规则仍未唯一证实。没有改写受拒请求、重跑整轮或把可疑词直接当作删除方案。

## 禁用搜索的独立配置验证

全部 34 轮原题已核对，只需原 CSV、题面规则和前序实际结果，没有外部搜索依赖。按[Spec 第 8 节](../prompt-language-selection.md#8-task2-禁用搜索的独立配置验证)，仅在本次进程清空搜索凭据，通过现有条件注册移除 `web_search`；全局 `.env` 不改，`web_read` 保留。这是新的工具配置和空对话，从第 1 轮开始，原受拒轨迹保持封存。

准备检查冻结 3,743 个文件；相对 `.tmp/em27/code/`，仅评测配置快照增加 `web_search_available`，生产源码没有变化。生成仍为英文 Prompt／MiMo Flash，原题、CSV、镜像、每 run 预算和 direct/none 保持。实际首个主决策请求 `013f543626a049e68a6dcf87728d63f4.http.request.json` 有 18 个工具，无 `tool_web_search`，保留 `tool_web_read`；全部动作也未搜索或读取网页。轨迹在首轮连续两次提交同类无效 `write_artifact` 参数后停止，正式交付 0、后 33 轮未执行；5 次模型请求、88,154 tokens、未知 0、471.797 秒。未出现 content_filter，但不能据这一独立轨迹确定此前过滤原因。

运行在 `.tmp/ns27/c/`，身份为 `.tmp/ns27/identity.json`；携入前次 632,653 已知生成 tokens、1 次未知及 1,032,768 管理预留后，本次上限 58,334,579，预留不是实际消费。评分继续使用 `.tmp/em27/j/` 的同资格 Pro／1M 账本，旧 34 轮 4/34 直接复用。进程停止和封存后自动评分，组名 `no-search-01-34`；无可评分答案、无新增评分调用，账本仍为 226,630。终态汇总 `.tmp/ns27/final.json`；未把没有答案写成新 0/34。

本次执行准备检查、针对新增评测元数据及执行脚本的 Ruff 检查、开发规范检查通过；没有运行单元测试，也没有为配置切换新增生产开关或模型调用步骤。脚本在 `.tmp/longds-task2-no-search-20261027/`，旧生成与评分归档保持原身份。

## 英文动态提示与反馈补齐

全请求审计纠正了原有覆盖边界：`.tmp/task2-language-audit-20261027/` 校验 38 个原始 SDK 文件，上一英文轨迹 14 个请求中 10 个含硬编码中文读取说明，最新轨迹 5 个请求和两组原模型返回均没有中文。中文停止提示由 Runtime 终止后生成。原先只核对模板、初始 system 和 Schema，不足以覆盖工具实际返回。

按[固化方案](../../completed/english-owned-feedback.md)，将 326 条漏出的指令和说明注册到原 Catalog，当前中英各 393 条。覆盖读取／搜索／截断、回答与研究、工作计划、工具／治理、执行与恢复说明、实验 Completion gap、直接内联生成、参数与模型输出校验，以及 Capture413 等实际返回模型的说明。中文原有 67 条资源保持；业务数据、源文、模型历史、代码与 stdout/stderr 原件保持。Schema／错误分类／权限／恢复次数不变，无新增模型步骤或运行时翻译器。

零模型回放覆盖了被拒轨迹中的全部 5 次真实读取：使用原快照、原参数、原消费者前的完整输出，并绑定其实际 wire 投影，中文逐字相同、英文说明生效，正文／坐标／引用／续读事实保持。全输入物化审计为 308 个真实 SDK 请求、4,658 次 Schema 投影，17 个真实工具／18 个当前动作及14个当前阶段 Schema；原用户和历史消息、字面量约束保持。这些是语言和结构边界证据，不代表 task2 正确性。

独立审查定位并修正了10处新增模板变量 `name` 与 Catalog 参数同名的错误，以及 get_note 无命中、Capture413、研究输出校验和核验拒绝默认说明的遗漏。中文符号化构造和10个机器 Schema 对照保持；静态实参绑定检查覆盖当前具名资源调用，无未关闭的 Critical／Important。源码冻结在 `.tmp/ec27/code/`，3,753个文件由 `.tmp/ec27/identity.json` 绑定。

`LANG-ENTRY-1` 已通过：正式入口原请求“Read the first two lines of the attached CSV as text, then report its column names.”，上传原 CSV，答案包含正确的前两行原文和12列名。实际调用 `read_artifact` 后提交终答，3次 MiMo Flash／thinking enabled 请求共19,368 tokens、未知0、41.609秒；未注册搜索，进程停止封存。`.tmp/ec27/actual-input-audit.json` 校验全部冻结文件及实际408个源码身份、配置和原请求；3个完整实发请求的汉字计数均为0。全局 `.env` 未修改，无新增评分调用。

本次预声明的语言覆盖用例均通过，对应局部缺口关闭，机制正文归固化方案。该语言smoke不包含完整task2，也不冒充参数修复、Graphiti兼容或完整发布。新增生产复杂度为原Catalog中的具名资源及显式实例参数／校验context，未新增依赖、业务状态或模型输出字段。费用只增加上述英文smoke；截至该smoke封存，连同前两次英文task2生成、中文smoke及共享Pro账本，活动累计989,566个已知tokens，另1次未知保持原身份。

用户随后明确要求继续原题以观察写文件与后续执行。按[Spec §10](../prompt-language-selection.md#10-英文反馈补齐后的-task2-原题验证)运行的`.tmp/ew27/c/`已停止封存：34轮计划中请求2轮、交付1轮，第2轮Provider超时，后32轮未执行。9次物理请求共203,868已知tokens、未知3次，耗时2,376.063秒。第1轮通过3次Python执行提交答案，没有提议或接纳`tool_write_artifact`；Pro判0分，主要是质量、成熟曝光、类型平衡和类型集中度数值错误，起止规模及CAGR正确。评分新增4,364tokens，共享账本累计230,994、未知0。原件和评分分别在`.tmp/ew27/final.json`及`.tmp/em27/j/english-complete-01-34/`，不能写成完整任务0/34。

2026-10-28用户要求恢复。第2轮旧run已超过单轮截止时间，但任务授权有效；按Spec使用同一对话新run重提原第2轮，并保留旧失败、全部事实、费用及原许可。恢复捕获根`.tmp/er28/c/`，不重跑第1轮或重评其答案。09:07正式入口已接收第2轮，实际Flash请求开启thinking，服务方返回200并接收流式响应；此时尚无第2轮终答。启动前142个复制文件逐字校验；运行中141个事实文件保持，另1个对话锁由正式进程持有。`.tmp/er28/live-continuity-audit.json`确认原请求除run身份外一致、许可一致、累计已知203,868及usage不完整标记保留、无未决执行。脚本静态检查和规范检查通过；未改生产源码或运行单元测试。最终状态以该根报告为准。已有英文语言局部验收保持成立，本次超时作为独立Provider阻塞处理。

2026-10-28恢复捕获`.tmp/er28/c/`已终态封存：新增交付第2、3轮，第4轮两次同类无效动作后按原门禁返回limitation，后30轮未执行。旧第1轮直接复用，当前累计交付及Pro评分3轮，0/3正确；完整task2未通过。恢复生成15次物理请求、508,801已知tokens、未知0、1,413.250秒；新评分2轮增加6,267tokens，共享账本237,261、未知0。英文生成活动累计1,452,844已知tokens、历史未知4次保持，不把管理预留计为实际费用。汇总`.tmp/er28/final.json`及评分组`english-recovery-02-34`保留，未自动再建恢复尝试。该轨迹使用`.tmp/ec27/code/`，不包含随后已通过独立smoke的[Markdown表达迁移](../../completed/prompt-markdown-presentation.md)。

## 英文表述与结构化兼容的判断

两次无效动作均在 `$.request` 把应为对象的值输出成 JSON 字符串。实际修复请求收到错误位置、原提议与 Schema；第二次同轨迹记录已识别对象要求，最终 API 返回却仍为字符串。未截断，不能归因为“没有看到反馈”或“完全不懂英文”。详细只读依据在 `.tmp/english-completion-20261027/wording-analysis.md`。

公开 [vLLM MiMo parser](https://github.com/vllm-project/vllm/blob/4e7af3b0de4cae4f70056da590f2f3d676223978/vllm/tool_parsers/utils.py#L1014) 的类型提取不解析本地 `$ref`，在本次 `oneOf + $ref` 结构上会得到 string；增加冗余 object 类型或内联分支后可识别 object。已做确定性 helper 对照，不能指认 hosted Token Plan 使用同一实现，也不能当作本工程兼容候选已通过。下一项有区分力的验证应针对出站等价 Schema 投影，保留本地 canonical 校验；本轮未改 Provider 或自动解析内层字符串。

优秀框架允许自然语言正文，同时保留工具参数结构。LongDS 的 Codex／Claude Code runner 使用 Schema，Kimi／Qoder 用 Prompt 约定最终 JSON；没有服务端 Schema flag 不等于没有结构要求。当前 task2 的19个实发请求均未发送 `response_format`，因此不是 `response_format=json_schema` 与 JSON mode 的冲突。[MiMo JSON mode](https://mimo.mi.com/docs/en-US/quick-start/usage-guide/text-generation/structured-output)与[工具 Schema](https://mimo.mi.com/docs/en-US/api/chat/openai-api)属于不同接口。

另有真实生产适配缺口：Graphiti 在 `response_model` 非空时固定用 `json_schema`，绕过当前 `structured.output_transport=json_object`，Policy 也未检查格式；未取得这条路径实际 HTTP 拒绝的证据。其结构信息当前由 response_format 携带，不能只改为 json_object 而丢掉 Schema；后续应由已有 Policy／Adapter 显式适配并保留本地 typed 校验。本轮仅分析，不宣称所有 MiMo 调用已兼容。

## 工程检查与剩余范围

实际执行`python scripts/check_layers.py`（14包、43依赖边、无违规）、`python -m ruff check --select F401,F811,F821 src scripts`及变更的Judge／输入诊断文件、`python scripts/check_dev_spec.py`、本次范围的`git diff --check`，均退出0。规范检查为72/72主路由、9/9目录覆盖、881链接及340锚点；检查没有证明模型理解全部规范。完整命令与输出在`final-checks.json`。

结构变化是一个typed语言设置、不可变Catalog／译文结构、独立Judge设置及已有指令的资源化，未增加业务事实、状态机、LLM输出字段、模型调用步骤或依赖。实际新增的模型调用均为已声明的资格、中文smoke及验证。英文研究／核验只有Schema物化证据，完整英语任务用户结果仍缺失；保持`to_verify`，不登记为完整产品验收或发布通过。
