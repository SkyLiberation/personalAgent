# 当前评测用例盘点

> 2026-08-26 更新：`InvestigationProject` 已因缺少需求 baseline 且正式结果为 `0/20 delivered` 被撤回。下文仍出现的 `E23`、`PLAN-001`、`IP01`、`LT*` 与 `INVESTIGATION-*` 行只用于解释历史归档，不属于当前可执行矩阵或产品能力。

**当前目录有 29 条用例：9 条 Product E2E、8 条 Application Integration、7 条 Runtime Conformance、4 条 Capability Profile 和 1 条 Boundary Evaluation。** 其中 9 条进入 release selection，20 条进入 diagnostic selection；新增离线评测不增加产品发布分母。只有 Product E2E 经目标 Agent 完整生产链；直接调用 Application 入口的旅程不再命名为 E2E。

`RESEARCH-ANSWER-OUTCOME-001` 是 `WEB-RESEARCH-EVIDENCE-CONTEXT-001` 的前置评测校准，历史目的为判断旧比较任务正文、官方论断支持和保证范围；当前评分器已按协作任务修正，旧样本只作历史诊断。canonical catalog 将其登记为 Boundary Evaluation（Offline Eval）；它只向真实模型提交最终答案、中文用户目标与版本化官方依据，不提供生产 Observation 或 Verifier 判断，不启动数据库，不证明 Agent 已修复。历史旧任务采用十类控制各两次、`mimo-v2.5 + json_object + thinking=disabled`；当前协作任务使用 v8、thinking 开启及清理后的十三项控制，不规定生产 Agent 的工具、查询、调用顺序或回答措辞。具体执行和成本停止条件见[运行与发布](04-running-and-release.md)。

首个 v1 pilot 对历史错误答案的最终拒绝符合预期（`1/1`，2,325 tokens，15.21 秒 pytest），但人工检查理由发现它错误排斥“工具注解辅助风险评估”的合理表述，故不能据此准入。密封归档为 `C:/pae/research-answer-grader-20260904/pilot/20260904T045358.788333Z-39256-fd93df0e/`。v2 只补齐 MCP `ToolAnnotations` 与 `CallToolResult` 的官方依据，并将相邻正确控制明确为“辅助风险判断、不保证安全”；原历史答案和通过门槛不变，新旧评测版本不混算。

v2 的同代码、同输入协议校准达到 `20/20`，使用 35,019 tokens，模型调用墙钟合计 148.859 秒，最长单样本 12.531 秒，Provider 失败为 0。两次历史回放均拒绝错误保证；四类正确中文表达均通过，标题式回答、无关 URL、扩大保证及被评答案注入评分指令均被拒绝。归档为 `C:/pae/research-answer-grader-20260904/v2-pilot/20260904T045623.403148Z-15600-2fc861d9/` 与 `C:/pae/research-answer-grader-20260904/v2-controls/20260904T045701.763776Z-28640-5f8e11c1/`，checksum 有效，dirty digest 同为 `45414d360c745c1c73bbfb1cb250c6d3b0634a28b60aa6fc8f4cd9e84ba7c905`。这只准入限定场景的结果检查，不估计通用语义正确率。下述 Product E2E target 已接入该 grader；旧运行 outcome 不追溯改写。

随后沿本地 HTTP 响应、生产抓取 Provider、真实 `CaptureService` 与工具装配、生产 Observation 界定和真实 Artifact 读写执行确定性 Contract。有效 baseline 为 `6 failed`：纯文本、HTML、Firecrawl Markdown 的三个 12,000 字符截断反例，一个 `web_search` 的 2,000 字符截断反例，一个最长叶子丢掉第二来源的反例，以及一个完整存储后仍无法重读 90,012 字符单行中段的反例。最后一项没有替代模型作决定：它仅直接测试 Runtime 的关键词与行号读取，不能命名为 E2E。有效密封归档 `C:/pae/web-evidence-contract-baseline-20260904/20260904T050216.865977Z-25960-85516826/` 含失败测试源码、相关生产源码和原始 pytest 输出；首轮 `20260904T050129.474661Z-21652-1207462a/` 的最后一项因诊断脚本读取错误属性而无效，不作为读取缺陷证据。临时失败测试从默认回归目录移除，源码可由有效归档恢复。

当时的官方页面响应另存于 `C:/pae/web-evidence-source-snapshot-20260904/20260904T045916.814832Z-39344-29ea6342/`：OpenAI HTML 为 1,394,582 bytes、旧提取文本 64,763 字符；MCP HTML 为 862,843 bytes、旧提取文本 15,732 字符，最长提取行分别为 369 和 374 字符。该快照不是失败 E2E 的原始 HTTP 响应，只用于同字节提取与体积测量；不能把页面漂移后的 target 当作与历史 HTTP 字节完全相同的配对。

有界来源片段的准入 Contract 为 `6/6 passed`，归档 `C:/pae/web-representation-qualification-20260904/20260904T060044.995700Z-1556-4d9d1277/`。首轮 `20260904T055939.007045Z-35780-7df18acd/` 因 pytest 自动参数名超过 Windows 环境变量长度而出现 8 个 setup error，不作为机制反例；修正的只是测试 ID。双份约 4 MiB 文本容量检查得到 9,040,797 bytes 编码载荷、44,306,184 bytes 峰值追踪内存与 0.306 秒处理时间，归档 `C:/pae/web-source-capacity-20260904/20260904T060140.948648Z-15300-f2fe9800/`；该本地单进程样本不证明并发或磁盘容量。

生产修复后，`tests/test_web_source_representation_contract.py` 与 `tests/test_web_evidence_delivery_contract.py` 合计 `17/17 passed`，覆盖长单行、多来源重组、完整窗口续读、转义与来源伪造、作用域拒绝、Provider 失败、容量超限和卸载失败。密封归档为 `C:/pae/web-source-production-contract-20260904/20260904T061402.153824Z-38924-2941532c/`，含该次源码与原始 pytest 输出。原有两级正文静默截断、摘要拼接正文和旧字符串抓取接口已删除；当前实现由[Context 工程](../topics/context-engineering.md#网页来源正文保留与重读)拥有。

正式 HTTP target `CONVERSATION-RESEARCH-DELIVERY-001/tool-protocol-boundary` 为 `1/1 passed`，归档 `C:/pae/web-source-context-target-20260904/conversation-research-delivery-001/target/20260904T061819.322981Z-11240-e6e37647/`。仍使用 `mimo-v2.5 + json_object + thinking=disabled`，未修改 Final、Verifier 或预算策略；只同步了工具返回契约说明。Agent 用量为 89,038 tokens、5 个模型回合，正式调用耗时 209.350 秒，整个 pytest 为 228.17 秒。独立 grader 使用 2,210 tokens、6.556 秒，比较正文、官方依据和保证范围均通过；答案未再把 `strict: true` 扩大为工具返回值保证。

该次实际封存两份正文 Artifact，归一换行后为 25,584 与 18,339 字符；前者包含 Anthropic 和 MCP 两个来源，后者包含 MCP 来源。真实模型读取后者的第 1—15 行，包含 `outputSchema` 原文，返回 `next_start_line=16`；逐行核对与 Artifact 完全一致，没有第二次截断。封存与审计归档 `C:/pae/web-context-closure-audit-20260904/20260904T063032.078666Z-19136-69115d47/` 记录了可重组来源、Windows CRLF 原文件校验和重建和退役 Future 设计。它不是新增 E2E，也不代表模型读完所有来源。OpenAI 官方页面在 target 中发生 SSL EOF 抓取失败，失败事实和答案中的取证限制均可见；MCP 官方正文已成功取得并读取。

上述历史反例、确定性修复反事实和真实用户结果支持 `WEB-RESEARCH-EVIDENCE-CONTEXT-001` 的限定缺陷闭环，不证明整个 Context 架构、Verifier 或通用事实合成已无问题。样本超过 60 秒，按预声明规则停止新增 live 样本；未执行完整 release matrix，不声明当前 dirty revision 可发布，也不声明成本降低或概率稳定性。预算与 Provider 网络问题不在本次修复范围。

最终本地回归为 `223 passed`、14.04 秒，覆盖上述 Contract、Capture、工具、Conversation、Prompt、评测契约和 URL 摄取 API；3 条警告均来自第三方弃用提示。`ruff`、`check_layers.py`、`check_dev_spec.py` 与 `git diff --check` 通过；本次文档另检查 20 个本地链接、3 个标题锚点和 17 张表，代码块配对正常。归档 `C:/pae/web-context-final-regression-20260904/20260904T063551.639810Z-21320-19ad0b87/` 保存逐条命令、原始输出和源码。相对实施前密封快照，本片生产代码新增 245 行、删除 60 行，净增 185 行；没有新增数据库表、读取工具、模型调用或旧新双轨。该本地回归不增加 live Product E2E 的样本数。

## DeepSeek 固定输入的 Final 模型对照

**2026-09-08 按用户要求切回 DeepSeek v4-flash，单次关闭 thinking 的 Final 对照仍出现超出来源支持范围的否定断言。** 当前生成模型配置由[模型配置](../env.md#llm-配置)拥有；此次不更改生产 Prompt 或 canonical 评测器。

输入复用历史正式首次 Final 的全部消息、角色、原文、Plan 与 Schema，不重跑检索或加入修订稿。`json_object`、关闭 thinking 和 1,600 输出上限保持；服务提供方从 MiMo 切到 DeepSeek，既有 Adapter 将 `max_completion_tokens` 改为 `max_tokens` 并增加 `temperature=0`。因此这是模型服务配置对照，不能声称只改变模型权重。执行命令为 `./.venv/Scripts/python.exe -X utf8 C:/pae/deepseek-final-comparison-20260908/compare.py`。

实际一次 HTTP 请求，返回模型为 `deepseek-v4-flash`，正常 `stop`，无重试、结构修复或截断；共 34,608 tokens，其中输入 33,565、输出 1,043，调用墙钟 11.471 秒。完整中文比较和官方 URL 已交付；参数 strict、MCP `outputSchema` 的适用条件及服务器 MUST / 客户端 SHOULD 本次保留正确。人工来源审计仍发现“文档没有声明 OpenAI 会代表应用执行权限检查，也未说明由谁负责权限检查”和“文档没有规定工具返回结果必须符合某个输出 schema，也没有声明 OpenAI 会校验工具返回结果”。输入只含部分窗口，参数 Schema 的正向保证不能支持这些整篇文档的否定结论；此判断不把缺少支持等同于已被官方反证。

[生成归档](C:/pae/deepseek-final-comparison-20260908/comparison/20260908T132901.523676Z-21308-303251bf/result.1.trace.json)与[人工审计](C:/pae/deepseek-final-comparison-20260908/audit/20260908T133037.270794Z-16112-59147814/audit.1.trace.json)封存原始请求、原始响应、来源坐标、脚本、配置差异和可还原生产代码身份，checksum 有效。此样本不支持“换回原模型即可消除越界”；它不能排除模型能力影响、比较整体模型质量或替代 Product E2E，独立评测器继续暂停。

### Thinking 与输出额度的隔离诊断

**开启 thinking 并取得完整正文后，仍观察到从执行事实推导权限归属、从局部未见承诺推导指南未声明的越界。** 按用户要求先扩大诊断预算以完成定位，成本优化后置。以下请求沿用同一首次 Final 的完整消息，生产 Prompt、评测器与默认运行预算均未修改；thinking 只在隔离请求开启，服务默认推理强度为 `high`。官方说明 thinking 模式忽略 `temperature`，因此相同参数字面量不等于相同采样语义，见[思考模式契约](https://api-docs.deepseek.com/guides/thinking_mode/)。

| 诊断条件 | 实际响应与用户正文 | 已知用量与墙钟 |
| --- | --- | --- |
| thinking 开启，1,600 输出上限，生产 Adapter 恢复链 | 3 次初次请求均 `length`；连同结构修复共 6 次 HTTP 请求，正文全部为空；其中 2 次修复为 `stop`，JSON 只在 `reasoning_content`，未被接纳为正文 | 210,152 tokens；90.578 秒，超过最初预估的 75k / 60 秒，保留原始失败 |
| 原始请求输出上限 8,192，等待 60 秒 | `APITimeoutError`；没有取得响应和用量 | 用量未知；60.548 秒 |
| 相同 8,192 请求，等待 240 秒 | `length`；8,192 个输出 token 全部用于推理，正文为空 | 41,836 tokens；74.497 秒 |
| 输出上限 32,768，等待 480 秒 | 正常 `stop`，完整 `FinalMessage`；实际推理 2,711 tokens、正文 1,001 tokens，无结构修复 | 37,356 tokens；31.566 秒 |

扩大额度后的三次诊断都只发一次原始服务请求，不执行 Adapter 的修复或重试。前一条超时请求的成本不能计零；连同关闭 thinking 的对照，本轮共 10 次 HTTP 尝试，9 份响应已知合计 323,952 tokens，另 1 次用量未知。32,768 样本实际使用较少 token，不证明预算扩大必然降低成本，也不支持一次成功即可估计稳定性。

完整推理中，模型先承认没有直接权限依据，再用应用执行代码推导权限责任；最终正文写为“因此，按已查阅到的官方页面，工具调用的授权与访问控制取决于构建和执行该工具的应用侧实现”。执行代码的主体与授权、访问控制的归属不是同一命题，输入不足以完成该推导。答案也仍写“该指南未声明 OpenAI 会对函数返回值做类似 outputSchema 的强制校验”，没有把否定范围限定为本次实际读取的片段。这些是可定位的支持关系问题，不声称对应现实命题已被官方反证。

历史调用另确认：在 Plan 仍记录取证缺口时，原模型将 `control_prepare_final` 与两项读取同批提交；进入 Final 时仍剩 7 个模型回合、11 次工具调用和 229,138 tokens。运行系统等该批执行结束后进入独立 Final，因而此次不是预算触发的工具隐藏。Final 原契约允许 `limitation`，不能把阶段分离描述为必然强迫模型编造。可见推理只帮助提出“取证充分性判断过早、合成时错误跨越证据边界”的假设，不能代替责任边界反事实或证明模型内部因果。

完整结果见[32,768 额度响应](C:/pae/deepseek-final-comparison-20260908/thinking32768/20260908T133811.747293Z-23952-e7c264f6/response.1.trace.json)；[汇总审计](C:/pae/deepseek-final-comparison-20260908/thinking-audit/20260908T134110.021497Z-26380-a9978953/audit.1.trace.json)封存全部运行入口、原始失败、精确推理与答案坐标、历史动作响应及来源代码身份，checksum 有效。执行脚本为隔离目录下的 `thinking.py`、`thinking_budget.py`、`thinking_long.py` 和 `thinking_large.py`；未运行新的 Product E2E，也没有迁入生产修复。

## MiMo thinking 成文与对话反问诊断

**2026-09-08 切回 `mimo-v2.5` 并开启 thinking 后，同一首次 Final 仍有来源越界；定向追问可以纠正部分错误，不能作为生成修复通过。** 当前配置由[模型配置](../env.md#llm-配置)拥有。本轮保持生产与 canonical 评测源码身份，固定封存的首次 Final 原始消息；诊断输出上限 32,768、等待 480 秒，`json_object`，每项仅一次真实请求，无重试或结构修复。MiMo 的思考模式与输出额度含义按[官方契约](https://mimo.mi.com/docs/en-US/api/chat/openai-api)核对；与历史关闭 thinking 的请求不是相同采样条件。

| 诊断 | 实际观察 | 用量与模型墙钟 |
| --- | --- | --- |
| 原始完整输入 | 推理把应用执行与文档缺失作为权限归属依据；正文仍有无据权限责任、全页否定和工具选择对立 | 35,596 tokens；69.135 秒 |
| 基于该答案追问依据 | 仍将文本缺失称为部分支持，辩护应用执行到权限归属的推断 | 38,356 tokens；76.928 秒 |
| 独立请求只将 Plan.goal 的“差异”改为“规定” | 保留完整任务与来源；权限归属和结果无契约的越界仍存在，候选淘汰 | 36,382 tokens；86.505 秒 |
| 对话提出同片段、不同未读部分的反事实 | 承认无法区分，却仍把缺失称为部分支持，以减弱语气保留推断 | 40,752 tokens；65.299 秒 |
| 独立请求只替换 Final 前缀为蕴含反事实判据 | 仍从局部窗口推到全文未规定，且将 strict 的调用参数约束写成返回结果约束；候选淘汰 | 35,381 tokens；49.664 秒 |
| 追问该候选的对象和全文范围 | 正确撤回两处结论；却将离散窗口描述为 offset 0—69000、约 120 行摘要，读取覆盖自述不可靠 | 36,908 tokens；46.171 秒 |

六次请求均 `stop` 且取得正文与 `reasoning_content`，合计 223,375 tokens、393.701 秒。三次独立生成均保留来源支持失败，另三次为带具体问题提示的对话诊断，不能混成独立正确率；候选失败后的充分与不足控制未执行。后两次追问返回 `clarification_required`，但没有实际需要补充的用户输入，另记协议语义问题，不在本轮修复。

逐字复核确认，strict 的依据在输入索引 4 与 11 的 line 67—70（offset 66000—69000），对象是函数调用参数；不能迁移为应用返回结果保证。全部来源输入共 85 个可解码原文片段，其中 OpenAI 只有 33 个不同 offset，存在未覆盖区间。对话纠正对 strict 的指向成立，读取范围的自述则不成立；不能因为模型承认错误就停止核对原始数据。

这轮证据将问题缩小到完整合成中的对象错配、否定范围扩大及把合理猜测当成来源支持。它不证明模型绝对不懂这些区别，也不证明唯一内部原因；推理与事后解释只用于提出可检验假设。仅换模型、开启 thinking、改写 Plan 目标或加入同类自检规则均未取得生成准入，两个候选不迁入生产，独立评测器继续暂停。

执行入口为 `./.venv/Scripts/python.exe -X utf8 C:/pae/mimo-thinking-focus-20260908/probe.py <case>`，六个 case 及实际请求、原始推理、完整正文、人工标签和原文坐标见[密封审计](C:/pae/mimo-thinking-focus-20260908/audit/20260908T140629.399162Z-27284-97fc35f3/audit.1.trace.json)。请求保持、单变量差异、源码身份与 checksum 均核对通过。诊断脚本在仓库外，生产代码净增 0 行；未运行新 Product E2E、全部 Adapter 集成或发布矩阵。正式 Conversation 的单次输出上限仍为 1,600，本轮扩大额度不代表正式链路的 thinking 预算已验收。下一责任边界由[生成责任诊断](../optimization/permission-inference.md#33-正式正文与实验引用协议的责任核对)拥有。

## Action 取证充分性与来源范围诊断

**2026-09-08 的新诊断确认，来源越界可以先出现在 Action 的可见推理中，不能仅归因于 Final 阶段。** 历史 Action 在取证与 `prepare_final` 同批提交后进入 Final；但本次同输入 thinking 回放选择继续取证。因此，“阶段切换必然导致越界”没有成立，尚无阶段协议修改准入。

本轮固定历史首次 Final 前的 Action 请求、用户任务、全部工具和来源，开启 MiMo thinking，输出上限 32,768，等待 480 秒。另从同次正式运行封存的 OpenAI Artifact 中取出 line 56—57（offset 55000—56000）的结果格式原文，分别形成 Action 与 Final 输入反事实。仅补充这两个真实片段，不修改其他资料或指令；这是人工构造的组件输入，不是新执行的 Observation，也不是 E2E。

| 条件 | 人工核对结果 | 用量与模型墙钟 |
| --- | --- | --- |
| 原 Action，`mimo-v2.5` thinking | 选择继续取证，但搜索 `arguments` 为字符串，不符合对象 Schema；推理已经从应用执行推导开发者权限责任 | 34,110 tokens；27.329 秒 |
| Action 仅补结果格式原文 | 正确区分 strict 与返回结果；未经依据将用户范围限于 Function Calling，认定未读权限页面仅讲平台权限、与任务无关，提交 `prepare_final` | 35,402 tokens；44.446 秒 |
| Final 仅补相同原文 | 正确引用格式由开发者决定的条款，但仍扩大权限责任及文档否定范围；完整来源支持失败 | 35,823 tokens；48.151 秒 |
| 对话追问取证范围依据 | 承认用户未限定唯一页面、未读页面不相关没有依据，执行函数也不能证明权限责任；仅为带提示诊断 | 39,445 tokens；55.444 秒 |
| 独立替换 Action 的取证范围规则 | 只重复提交原 Plan，没有可执行取证动作，候选检查点失败；其余控制未运行，候选不迁入生产 | 35,033 tokens；32.083 秒 |
| 原 Action 仅改为 `mimo-v2.5-pro` thinking | 提前提交 `prepare_final`，在尚无正文时自述全部验收通过 | 33,866 tokens；20.038 秒 |
| 原 Final 仅改为 `mimo-v2.5-pro` thinking | 将 MCP 的工具安全及注解条款归到 OpenAI，并再次把 strict 参数约束用于工具结果；来源支持失败 | 35,351 tokens；40.198 秒 |

七次真实请求共 249,030 tokens、267.688 秒，均完整返回，未重试或结构修复。第一项脚本错误地只允许 `stop`，因此原归档保留退出码 1；只读审计依据 MiMo 契约确认 `tool_calls` 是正常结束类型，没有据此重跑。搜索参数的真实 Schema 错误仍保留，不与脚本断言错误混淆。Pro 两项只改变模型字段，未改变正式配置；单样本不能比较整体模型优劣，也不能排除能力影响。

独立 Conformance 将候选的真实 Plan 响应交给现有解码和 Admission：计划按对象身份保持不变，`admit_continue_turn_progress` 返回 `continue_turn_no_progress`。因此，无进展分支已有反馈，不能新增同义机制；此次没有执行其后恢复，也不把首次候选失败改判为通过。

本轮证据支持两个更具体的失败位置：模型会用对未读资料的假设缩小取证范围，并在合成时错配来源和条款对象。补充结果格式原文只解决该局部依据缺口，不证明完整回答合格；也不能由两次独立采样推断补充片段必然造成停止。当前没有合格的生产修正，独立评测器继续暂停。

执行入口为 `./.venv/Scripts/python.exe -X utf8 C:/pae/action-readiness-20260908/probe.py <case>`；[密封审计](C:/pae/action-readiness-20260908/audit/20260908T142615.212118Z-28212-eecdc051/audit.1.trace.json)保存七次输入、完整推理和响应、参数错误、单变量核验、外部依据与源码身份。[无进展反馈 Conformance](C:/pae/action-readiness-20260908/progress-check/20260908T142317.808484Z-27968-61df510d/progress.1.trace.json)通过。生产及 canonical 评测源码、`.env` 身份未变，生产代码净增 0 行；未执行真实工具动作、新 Product E2E 或完整发布门禁。后续工作转向[生成责任诊断](../optimization/permission-inference.md#33-正式正文与实验引用协议的责任核对)。

## MiMo thinking 连续链路与意图输出预算

**2026-09-08 的正式基线同时复现意图截断后验收条件丢失，以及最终回答的来源越界。** 使用原 `tool-protocol-explicit-review` 中文请求和 `POST /api/conversation/turn`，真实 Composition Root、模型、取证、Admission 与完成链路；不注入历史动作或来源。沿用当前 MiMo thinking，诊断累计额度临时为 384,000 tokens、16 回合、24 工具，模型等待 480 秒、HTTP 等待 1,800 秒；`.env` 保持不变。

原 Product E2E 为 `0/1`，pytest `689.89s`，用户 HTTP `491.657s`。意图请求与既有修复/重试共六次，800 输出 tokens 全部用于思考，均 `length` 且正文为空；`ConversationService._derive_interaction_intent` 的既有异常处理返回空意图，正式 trace 的验收条件随之为空。原始自动最早失败标签仍记录后续动作参数拒绝；只读 wire 审计揭示更早的意图输出失败，不追溯改写原标签。

本轮 OpenAI 页面读取五次 SSL EOF 失败，模型取得一份研究 Agent 报告后继续成文。Final 正常 `stop`，实际输出 1,598 tokens，但仍把开发者负责执行扩大为所有必要权限检查、用户确认和安全验证，也将 MCP 应用的 SHOULD 建议写成具体实现需要。报告及真实官方 URL 不能替代该扩展所需的原文依据。独立 grader 经 1,200 额度下多次截断重试后返回 `false`；其拒绝理由没有定位 OpenAI 权限扩展，还将 MCP 正确的人类确认建议描述为冲突，原判与人工审计分开保留。

服务进程捕获 21 次真实响应，共 257,306 tokens，其中意图失败 11,109、Conversation 15 次调用 246,197；另有一次 Agent 委托。grader 最终报告 7,485 tokens，不能代表全部重试成本，外部 Agent 用量也未完整取得。执行入口 `./.venv/Scripts/python.exe -X utf8 C:/pae/continuous-thinking-20260908/run.py`；[基线审计](C:/pae/continuous-thinking-20260908/audit/20260908T144513.176331Z-5644-3b5c75b9/audit.1.trace.json)关联完整源码、原始响应、来源 Artifact 和产品归档，checksum 有效。

固定首个真实意图请求，只把输出上限从 800 改为 32,768 的一次 Offline Eval 正常 `stop`：输出 3,450（推理 3,242）、合计 4,468 tokens、77.197 秒，五条条件通过现有原文 Admission。[反事实归档](C:/pae/continuous-thinking-20260908/intent-probe/20260908T143717.530067Z-24728-72889d48/response.1.trace.json)证明完整响应所需额度，不能证明全部条件的语义质量；该次仍未展开部分“两者”指代。随后生产只将意图推导及其既有修订的两处 800 上限替换为同一 32,768 常量，未改 Prompt、异常策略、Action/Final、Verifier 或独立 grader。当前额度事实由[模型配置](../env.md#llm-配置)拥有。

意图额度修正后的同入口 target 为 `0/1`，pytest `804.07s`、HTTP `790.754s`；首个意图正常完成，输出 3,187（推理 2,924）、合计 4,205 tokens，五条展开主体的条件进入正式 trace。局部检查点通过后，Action 又出现 1,600 输出全用于思考的 `length`，后续修复恢复动作；最终 16 回合耗尽，返回 `limitation`，无最终答案且未调用 grader。18 个 Action HTTP 尝试有 17 份响应、1 次没有响应，用量未知；加意图的已知用量为 206,845，外部 Agent 费用也未完整取得。[两轮分段审计](C:/pae/continuous-thinking-20260908/audit/20260908T145742.600463Z-28364-1874323a/audit.1.trace.json)保留原失败和已成立的意图检查点，不宣称用户交付通过。

按用户再次明确的“预算不足先扩大预算”，随后仅将 Conversation 统一 Action/Final 调用方上限改为 32,768，并同步两个既有测试中的旧额度断言；不增加生产开关或改变生成策略。新隔离 profile 为 64 回合、96 工具、2,000,000 累计 tokens、模型等待 480 秒、HTTP 等待 3,600 秒，`.env` 保持原配置。这是诊断预算扩充，不把不同随机轨迹作为单变量消融；运行入口为 `./.venv/Scripts/python.exe -X utf8 C:/pae/conversation-budget-expanded-20260908/run.py`。

扩充后的 Product E2E 仍为 `0/1`，pytest `597.67s`、HTTP `380.817s`。意图、13 次 Action/Final 和一次生产 Verifier 均完整响应；实际读到了两份官方正文，未耗尽执行预算。Final 仍写“OpenAI 文档未明确指定统一的权限检查方，责任通常由应用开发者承担”，现有 Verifier 又以 URL 正确及答案自称未扩大保证为理由放行。独立 grader 的六次响应全部在 1,200 上限 `length` 且正文为空，最终为 `StructuredOutputFailure`，原 E2E 保持失败；来源问题不由评分失败来证明，而由实际入参和正文独立核对。该轮完整 wire 用量为 367,601 tokens，其中 Conversation trace 记 307,605、生产 Verifier 41,366、grader 六次合计 18,630；Verifier 漏入 Conversation 汇总属于既有独立计量问题。本轮完整源码身份与各检查点见[三轮分段审计](C:/pae/continuous-thinking-20260908/audit/20260908T151214.505400Z-22876-1403c838/audit.1.trace.json)。独立评分算法仍后置；后续恢复评分前须先扩大已证实不足的请求额度，不用这次评分截断迫使生成候选迎合。

逐段核对第三轮实际 Final 请求，只含 OpenAI offset 0—59000 的 60,000 字符和 MCP offset 0—14000 的 15,000 字符。MCP `Security Considerations` 仅出现在目录，服务器访问控制正文尚未进入模型输入；不能误报为模型已读该条文仍故意忽略。Action 的可见推理已经承认 OpenAI 权限未明确，却认为可推断归应用，随后 `prepare_final`；进入 Final 时还剩 52 回合和 1,734,056 tokens。这将预算不足与来源充分性判断区分开来。

另一次固定该 Final 请求、仅删除重复工作计划投影的 Offline Eval 正常 `stop`，用量 42,875 tokens、64.719 秒。候选仍把权限责任推断写成来源结论，并新增“没有严格的输出模式验证”，来源支持检查失败；不迁入生产、不继续叠加提示词。全部用户原文、验收条件和来源逐字保持，核验及原文片段见[Final 范围审计](C:/pae/continuous-thinking-20260908/scope-audit/20260908T151803.894802Z-27328-7bfc7f1a/audit.1.trace.json)。这只否定单独去掉计划投影是充分修复，不能否定计划与外部事实需要区分权威边界。

生产预算修改后的 Conversation/Adapter 回归为 `180 passed`、4.78 秒，相关三个文件 Ruff 通过；意图修改后的编译、package DAG 与 devSpec 检查也通过。相对本轮基线，生产只增加一个供两处调用使用的额度常量并替换三个旧上限，净增 2 行；测试仅迁移两个旧额度断言。`service.py` 的影响路由要求完整 live matrix，但按原样本失败时先定位的规范尚未扩跑；因此不声明完整发布门禁、来源生成修复或产品完成。

读取失败另做了不修改生产的网络对照：同 URL 首先在当前 Windows 代理和直接 urllib 连接下均 SSL EOF；稍后固定 GET、请求头和 TLS 验证，curl、urllib、httpx 均取得相同的 1,395,623 bytes 正文，SHA-256 一致。见[客户端对照](C:/pae/continuous-thinking-20260908/http-clients/20260908T145500.998426Z-17292-34854474/plan.1.trace.json)。此结果支持间歇性读取失败，不能准入 HTTP 客户端替换，也不能抹去 E2E 已发生的来源缺口。

## 仅分类支持评测的资格失败

**2026-09-08 的仅分类隔离候选漏放原始错误长答案，未取得正式评测准入。** 本轮只删除输出中的解释字段及配套说明，固定 Pro、`json_object`、关闭思考、1,200 输出上限、五份参考和完整原文。此前 Pro 的正负样本布尔值符合预期，但负例解释错误声称答案缺少已有条件，不能证明可靠诊断；本轮也不根据解释推导 verdict。

严格布尔、禁止默认值或解释字段、输入保持及长控制完整性的机械检查为 `7 passed`。预声明八项 Offline Eval 实际执行两项：完整正例为 `supported=true`，原负例也为 `supported=true`，因此分类正确 `1/2`；剩余六项单缺陷长控制未执行。两次调用分别使用 4,691 和 4,683 tokens，合计 9,374；模型调用墙钟分别为 4.826 和 1.760 秒，均一次 HTTP 请求、正常 `stop`，无截断或结构修复。停止由分类错误触发，不是成本越界。

原始输入、全部声明样本、源码快照、模型配置、原始响应和未执行分母封存在[资格归档](C:/pae/source-support-candidate-20260908/decision-only-qualification/20260908T130413.635333Z-14496-31edeb42/qualification-summary.1.trace.json)，checksum 有效。执行命令为 `./.venv/Scripts/python.exe -X utf8 C:/pae/source-support-candidate-20260908/decision_only_probe.py`，退出码为 1；该脚本禁止重复运行本组。

[只读审计](C:/pae/source-support-candidate-20260908/decision-only-audit/20260908T130548.087617Z-3148-50b3d805/audit.1.trace.json)确认原负例的完整数据消息与上次 Pro 请求逐字相同，除协议消息外的实际请求参数相同，错误布尔已存在于模型原始 JSON。生产、canonical 评测源码和 `.env` 的执行前后身份未变。此结果只否定本候选资格；不能由两次不同响应宣称解释字段有稳定因果收益，也不能判断错误发生在局部语义判别还是全答聚合。

候选未进入生产或正式评测器，未运行 Product E2E、覆盖合并或完整发布矩阵。当轮逐块方向已停止，后续评分依据见[评分沿革与当前契约](../optimization/completed/research-grader-qualification.md)限定，不能续跑停止后的样本或用历史校准通过覆盖本次失败。

## 局部与完整答案的支持边界诊断

**2026-09-08 的独立诊断观察到：同一句无据断言在局部段落中被拒绝，放回完整答案后被漏放。** 本组用于区分局部判别与完整输入的失败边界，不续跑此前停止的资格组，也不晋级旧候选。

输入取自已封存的完整正例及单缺陷长负例；负例仅增加“OpenAI 官方文档没有规定工具调用的权限检查要求。”。局部投影保留原文块编号、权限主题标题、OpenAI 主体、有限材料限定和官方引用，五份参考全部保留；全文其他段落没有撤回该新增断言。两项机械检查通过，证明只移除其他答案块、原文与参考保持、标签未进入请求；语义前提审查随运行计划封存。

四项各执行一次，实际分类正确 `3/4`：局部正例 `true`、局部负例 `false`、完整正例 `true`，完整负例错误返回 `true`。固定 `mimo-v2.5-pro`、`json_object`、关闭思考、同一支持判据、严格布尔协议和 1,200 输出上限。共四次 HTTP 请求、16,214 tokens，模型调用墙钟合计 8.640 秒；全部正常 `stop`、无结构修复或重试。分类错误保留为失败，未追加样本。

执行命令为 `./.venv/Scripts/python.exe -X utf8 C:/pae/source-support-candidate-20260908/boundary_probe.py`，退出码为 1。[诊断归档](C:/pae/source-support-candidate-20260908/local-full-boundary/20260908T131229.836341Z-18472-6c53a5a3/boundary-summary.1.trace.json)封存完整计划、四份请求、原始响应、输入审查、配置与源码身份。[实际请求审计](C:/pae/source-support-candidate-20260908/local-full-audit/20260908T131336.092380Z-25156-ba796c72/audit.1.trace.json)确认局部与全文对照只移除其他答案块，原编号 `3`、全部参考、两条协议消息和其他请求参数一致，原始 JSON 与 typed 判定相同。两份归档 checksum 有效，生产、canonical 评测源码与 `.env` 未改。

每格只有一次随机调用，不能估计稳定性，不能指认某段非目标正文或内部注意力机制为唯一原因。局部通过不代表已建立覆盖全部答案的评测器；其他单缺陷、覆盖合并和 Product E2E 未执行。当轮保留全文的局部判别方向已停止，后续评分依据见[评分沿革与当前契约](../optimization/completed/research-grader-qualification.md)。

## 验收条件不再推导改稿任务的边界修复

**错误任务前提及强制成功分支已在当前工作树删除，确定性边界检查通过；真实 E2E 返回预算耗尽，用户交付仍未闭环。**
本次恢复用户目标与实际输入的既有边界，不改变工具、预算、模型、`InteractionIntent`、Verifier 或 `FinalMessage`
Schema。正式失败背景沿用下节同入口研究 target；它证明未交付，不证明这一错误前提是唯一原因。
此前离线首稿反例保持原判，不再用单次首稿是否完美混判本次 Runtime 责任边界。

修改前封存 251 个生产 Python 文件及同入口 target 计划：
`C:/pae/review-boundary-20260907/baseline/20260907T092555.535053Z-8708-e5763029/`。
新增五项确定性反事实在旧代码上为 `5 failed`：Action/Final 均错误附加已提供正文的前提，三种非 `answer`
终态均被继续迭代成答案。完整输出在
`C:/pae/review-boundary-20260907/baseline/20260907T092709.245972Z-9008-1f66c05d/`。
其中冻结决策只用于 Runtime Conformance，不作为真实模型、语义满足或 Product E2E 证据。

候选将主模板迁入唯一 Prompt Registry，只替换任务中性的中文验收片段，删除同源强制分支及对应的旧测试。
首轮为 `147 passed、1 failed`，失败来自测试仍要求旧英文指令原句，原始输出保存在
`C:/pae/review-boundary-20260907/target/20260907T092824.622587Z-18352-76ba0ecb/`。
改为核对实际注册模板后，Conversation 与 Registry 合计 `148 passed`、4.52 秒；有标准的答案仍进入原验证链，
凭据与反馈回归保留。最终输出在
`C:/pae/review-boundary-20260907/target/20260907T093007.946999Z-13056-bd1681d5/`。
八组迁移审计确认：无标准时旧新 Prompt 字节相同，有标准时只替换验收片段。审计归档为
`C:/pae/review-boundary-20260907/audit/20260907T093005.429923Z-16072-4c5f8a16/`。

原 `CONVERSATION-RESEARCH-DELIVERY-001/tool-protocol-explicit-review` 首次启动尝试的结果为 `1 setup error`、
1.12 秒：`127.0.0.1:5432` 没有 PostgreSQL，尚未调用模型，未到达候选检查点，无用户结果或模型 token 样本。
执行归档为 `C:/pae/review-boundary-20260907/live/20260907T093031.228448Z-3624-02f3e9bb/`。
随后 Docker Desktop 后端在初始化 `dockerInference` 本地 socket 时崩溃。用户重启后引擎恢复，但 PostgreSQL
仍未发布主机端口：容器健康，`HostConfig.PortBindings` 请求 `5432`，`NetworkSettings.Ports` 的实际列表却为空。
按既有 Compose 配置重启和重建单个 PostgreSQL 容器后仍复现，原命名数据库卷保留，未重置 Docker 或删除数据。
进一步确认 Windows 保留端口段 `5386–5485` 包含 `5432`，实际绑定报 `10013`，而 `15432` 可绑定。
诊断归档为 `C:/pae/review-boundary-20260907/environment/20260907T094756.080061Z-7292-ad9f3524/`。
经用户确认，将 Compose 主机映射、开发环境与测试连接同步为 `15432`，容器内端口保持 `5432`，不做数据迁移。
数据库预检从同一测试 URL 读取地址，未修改模型、预算、生产取证逻辑或用例断言。

端口恢复后的同入口 target 为 `0/1`，正式 HTTP 耗时 87.191 秒，pytest 耗时 109.56 秒；
使用 81,945 tokens（79,139 input、2,806 output），6 个决策回合、7 次模型调用，最终为预算 `limitation`。
11 次工具执行均成功：2 次搜索、2 次网页读取、7 次原文窗口读取。没有模型生成的 Final 或 Verifier Receipt，
独立结果评测器因此未运行。正式归档为
`C:/pae/review-boundary-20260907/product/conversation-research-delivery-001/target/20260907T113611.091297Z-3528-530403dc/`，
运行源码与原始 pytest 输出在 `C:/pae/review-boundary-20260907/live/20260907T113419.102210Z-20188-7efab8f5/`。

七次窗口读取中三次返回空行，其中一次仍报告四个关键词匹配；非空窗口逐行与封存来源一致。
最后一批窗口执行后因预算耗尽而没有下一次模型消费。逐回合输入从 7,208 增至 22,343 tokens，
typed inputs 从零增至 50,417 字符；这些是成本与定位线索，不证明资料已经充分或某次读取必然冗余。
原始 Journal、窗口校验和运行期间源码不变审计在
`C:/pae/review-boundary-20260907/live-audit/20260907T113735.709734Z-20464-013dd2ac/`。
正式入口已进入注册 Action 模板，但没有到达模型 Final 与非 `answer` 决策边界；不能把预算终态当作完整修复验收。
本次失败不证明旧改稿前提正确，也未证明候选造成独立回归。下一步定位原文窗口选择与继续读取的决策，
不改预算或 Verifier。样本超过预声明 60 秒，停止新增 live，不扩大到其他昂贵 E2E。

Ruff、package DAG、devSpec 和 `git diff --check` 均通过；六份文档的本地链接、标题锚点、表格和代码块检查通过。
首轮检查归档为 `C:/pae/review-boundary-20260907/checks/20260907T094237.693517Z-2040-9bf4a934/`。
相对修改前封存源码，本片四个生产文件新增 183 行、删除 211 行，净减 28 行；无新增状态、表、模型调用或双轨。
未执行独立静态类型检查和完整发布矩阵，不能声明当前工作树可发布。

## 网页发现与指定来源读取分离候选

**工具表达缺口已在代码中拆开，但原研究 E2E 仍为 `0/1`，新设计尚未闭环。** 实施前只读核对确认当前
251 个生产源文件与 source-index target 的封存源码一致，原请求重建哈希仍为
`44050d341a34406b351ff5ac52c48180b170652d266d74893295f1461dfa202a`。此前固定 Context Offline Eval
归档 `C:/pae/research-stop-offline-20260904/20260904T121141.059247Z-30676-415fe7d9/` 中，三次下一步采样均
未选择 Final；四个只读探针中三个零命中。它是诊断，不证明预算充分或通用发生率。

本候选只拆开发现与指定 URL 抓取；预算、模型、Verifier、Final 和正文提取 Provider 不变。定向 Contract 与
Conversation、Prompt、工具回归为 `204 passed`。首次测试的临时目录权限错误不算产品反例。额外执行的工具
治理 Golden Set 未通过；实施前独立代码副本得到相同失败指标，属于既有门禁缺口，未降低阈值或顺带修复。

正式 target 归档为
`C:/pae/web-tools-split-20260904/target-product/conversation-research-delivery-001/target/20260904T142534.029954Z-33332-72a85e9e/`。
同一显式验收请求经完整生产 HTTP 入口运行，返回预算耗尽 `limitation`，没有研究答案或 Verifier Receipt。
正式调用 97.623 秒，pytest 109.03 秒；Agent 为 79,589 tokens（77,475 input、2,114 output）、6 个模型回合、
10 次工具执行：3 次搜索、5 次指定 URL 读取、2 次 Artifact 窗口读取。没有答案，故未调用独立 grader；
不能把“未输出错误保证”当成正确交付。

该次局部链路事实与剩余问题分开记录：

- 模型自主调用 `web_read` 取得 OpenAI 正文；两次 Artifact 读取均精确返回第 63—70 行，且后续模型实际消费。
  两份窗口相同，不证明第二次读取带来了新证据；历史关键词缺口没有被追溯补写。
- 模型读取 MCP 介绍页后尝试了两个返回 HTTP 404 的路径，随后重新搜索并取得正确 tools 规范页。
  失败 URL 的选择不是抓取层把正确 URL 改错；不能把 HTTP 404 直接归为 TLS 或 Provider 服务不可用。
- 正确 MCP 规范正文已保存，但下一轮模型重复提交同 URL 抓取，被已有 `offloaded_output_refetch` 拒绝；
  没有读取该 Artifact 的正文窗口。随后累计 token 超限终止，工具预算尚未达到上限。

只读审计归档
`C:/pae/web-tools-split-20260904/audit/20260904T142920.689936Z-12588-9ce5345a/`
包含原 Journal、逐回合重建请求和与正式 Trace 一致的五项 Context 构成；OpenAI 两份窗口逐行与 Artifact 相等。
OpenAI 提取正文为 119,079 字符，哈希仍为
`8f2e00d4edee633046f586bf743005c566fd45f459342c26a800e1629254a424`；MCP tools 正文为 21,704 字符。
这支持指定 URL 读取和原文消费边界，不证明来源选择、读取去重、及时停止或整体成本收益。

执行前源码、原始输出和运行期间源码不变核对在
`C:/pae/web-tools-split-20260904/target-execution/20260904T142338.224365Z-34956-27f290d8/`。
相对实施前副本，本候选修改 9 个生产文件，新增 118 行、删除 118 行，净增零行；无新增表、Provider、缓存或
模型调用。旧耦合参数和固定前二抓取链已删除，原 `capture_url` 的确定性 Research 消费者仍保留。

该样本超过预声明 60 秒，停止新增 live。独立旧代码副本在
`C:/pae/web-tools-split-20260904/minus/`，**正式 target-minus-mechanism E2E 尚未执行**；旧副本上的低成本
检查不冒充正式消融。搜索数量下降不构成效率提升证明，尤其本次总 token 高于历史 target。由于随机轨迹及网页
返回可能不同，不把这两个数字当成确定性成本回归结论。候选保持独立准入，剩余验证由
[详细设计](../future/conversation-web-research-tools.md)限定；没有扩大修改或运行发布矩阵，不声明可发布。

最终低成本回归为 `265 passed`、17.26 秒，3 条第三方弃用警告；Ruff、package DAG、devSpec 与
`git diff --check` 通过。七份变更文档核对了 45 个本地链接、19 个标题锚点、21 张表和代码块配对。
原始命令、输出及文档快照封存在
`C:/pae/web-tools-split-20260904/final-checks/20260904T143314.400786Z-38356-d5ee6c15/`。
265 项不包含前述失败的工具治理 Golden Set，未执行完整发布矩阵或独立静态类型检查。

### 首片段预览的隔离资格评测

**原文预览可见已成立，但没有证明取证与完整交付改善，候选未进入主生产代码。** 固定输入 Offline Eval
执行 4 次、44,152 tokens；原单步窗口 gate 把合法 Plan 和搜索记为不通过，不能解释为产品成功率。
隔离候选的确定性 Contract 为 `19 passed`，旧投影的新增预览反事实为 `4 failed、15 passed`。
这不是既有产品不变量或正式消融。输入、评测设计修正和失败输出见
[完整资格记录](C:/pae/web-preview-offline-20260905/conclusion.md)。

同一原始显式验收 E2E 为 `0/1`：正式 HTTP 103.322 秒、pytest 129.33 秒，循环报告 65,855 tokens，
Verifier 模型用量未单独封存。OpenAI 首片段提示确实进入后续 Action 与 Final；模型在未读正文窗口时
生成 856 字符的不完整草稿，未写工具结果契约，并把 `.info` 来源标成官方。Verifier 随后因 criterion
结果未一一对应而失败；不能由此推断某个语义 status 误判。三次原文定位发生在该失败之后，一次返回
第 63—70 行、两次零命中；精确窗口没有后续模型消费，随后预算终止，独立结果 grader 未运行。

候选源码与原始执行封存在
`C:/pae/web-preview-offline-20260905/target-execution/20260905T032902.036443Z-17272-e53450c9/`，
Product 归档为
`C:/pae/web-preview-offline-20260905/target-product/conversation-research-delivery-001/target/20260905T033117.816147Z-28908-000941cb/`；
逐轮审计为 `C:/pae/web-preview-offline-20260905/audit/20260905T033349.944575Z-31736-b9ee109d/`。
样本超过预声明 60 秒，未新增 live 或正式消融；只有候选预览改动和临时调用入口退役，不回退既有工具拆分、
抓取与保真机制，不以本次终态否定全部设计。

### 验收标准与任务边界的隔离资格评测

**删除通用改稿假设的候选未通过相邻改稿控制，没有进入主生产代码，也未新增真实 E2E。**
当时的 `_review_instruction` 同时进入 Action 和 Final：它将存在验收标准解释为用户已提供正文和必要材料，
并要求返回 `answer`。当时的 `ConversationService` 还有同源的非 `answer` 拒绝分支。
这证明输入与控制边界存在错误前提，但不能单独证明它是研究未交付的唯一原因。

隔离候选移除这两个同源假设，将验收片段改为中文结果与证据边界；其他 Action/Final 静态指令保持字节迁移，
预算、模型、网页工具、正文预览和 Verifier 判别规则不变。旧路径的五项反事实全部失败，候选及相关回归为
`147 passed`，只证明确定性边界与协议保持。两份归档分别为
`C:/pae/review-context-20260905/baseline/20260905T062802.576666Z-23676-52f41001/` 和
`C:/pae/review-context-20260905/contracts-final/20260905T063236.206422Z-34440-a8600157/`。

固定输入 Offline Eval 实际调用四次，共 19,131 tokens，最长单次 19.687 秒。研究输入来自上节隔离预览
候选的历史 Final 请求，不冒充当前主路径 E2E；改稿输入复用 L06 中文目标，但不执行完整智能体链。
候选在改稿控制中返回 `clarification_required`，索要写入操作及证据，还询问应怎样改稿，没有交付用户要求的
安全文本。旧指令输出“系统已处理请求。”，也不能据此声称旧方案语义正确：这仍引入没有证据的处理事实。
两条随机响应只用于定位候选反例，不作为因果消融或稳定错误率估计。

Offline 归档为 `C:/pae/review-context-20260905/offline/20260905T063246.605642Z-38600-2306264c/`。
该临时记录器复用样本文件名，后两次改稿记录覆盖了前两次研究记录；研究输出仅出现在会话控制台，
不作为可还原的资格通过证据。两份改稿输入与响应完整且校验有效；汇总中的调用完成不代表语义通过。
退役审计封存了脚本、候选源码坐标和记录缺口，并确认主目录 251 个生产 Python 文件与本轮开始前一致：
`C:/pae/review-context-20260905/audit/20260905T063759.149065Z-24608-0b9bba55/`。
隔离候选和临时模型调用入口退役；只撤回本次未获准部分，既有工具拆分与正文保真保持不变。
后续有序任务规则及输出字段描述的独立离线复核见下节；旧结果不改写，也不与新版本合并。

### 有序任务规则与输出字段语义的隔离复核

**两次隔离资格检查均未达到预声明门槛，主生产代码保持不变，没有新增真实 E2E。** 第一组将验收片段改为
有序规则：用户目标先决定产物，再判断证据是否必需；修订无依据断言时删除断言，研究任务仍须补齐必要依据。
四种中文输入各执行两次，人工逐项判读为 `3/8`，不是产品完成率。

| 输入边界 | 实际结果 | 具体失败 |
| --- | --- | --- |
| 原 L06 改稿目标 | `0/2` | 分别输出“系统操作已完成。”和“系统已处理请求。”，仍声称没有证据的执行事实 |
| 活动介绍的无依据保证 | `2/2` | 两次均删除保证并交付可用介绍；不外推为所有改稿正确 |
| 没有提供待改原文 | `1/2` | 一次虽返回 `clarification_required`，正文却编造客户答复和处理承诺；另一次正确索要原文 |
| 历史研究 Final 输入 | `0/2` | 仍把未消费的支持依据当作已掌握；第二份把工具结果误称为必须符合开发者 JSON Schema，并生成输入中没有的 OpenAI 引文 |

第一组归档为 `C:/pae/review-context-v2-20260905/offline/20260905T072050.629592Z-26636-c4cad69e/`，
共 23,825 tokens，最长单次 28.938 秒。每个样本使用独立文件名，八份输入和响应均完整封存。
模型保持 `mimo-v2.5 + json_object + thinking=disabled`，每次输出预算为 1,600 tokens；
研究材料来自历史隔离预览请求，不冒充当前主路径输入。人工判断只覆盖预声明的局部语义，不能估计稳定错误率。

随后核对到 `FinalMessage` 的类说明仍要求未完成工作返回工具调用，与 Final 阶段无工具冲突。
第二组只替换 Schema 的类和字段 `description`，字段、枚举和约束保持相同；复用第一组原改稿和缺原文输入，
不再修改验收片段。四次结果为 `3/4`：缺原文 `2/2` 正确，改稿 `1/2` 正确，另一份仍声称“系统已处理请求。”。
归档为 `C:/pae/review-context-v2-20260905/schema-probe/20260905T072510.490537Z-13376-c4fba632/`，
共 3,995 tokens，最长单次 2.485 秒。该结果不证明 Schema 冲突是原错误的唯一原因，也不构成生产修复或正式消融。

十二份输入经本地结构化适配和请求参数装配重建后，业务消息均逐字保留；Schema 指令位于其前，普通样本包含
两条 `system` 消息。十二份响应原文经 typed 解析后也均未发生语义改写。该检查只证明本地装配，不证明远端
实际接收或如何解释多条 `system`，不能据此指控服务提供方丢弃 Context。审计还确认主目录 251 个生产 Python
文件与既有封存基线一致，归档为 `C:/pae/review-context-v2-20260905/audit/20260905T072750.387617Z-12024-10017ecc/`。

候选正文、Schema 探针和临时调用入口均退役，源码可由各归档恢复。这些 Offline 首稿反例不证明完整链路不能
纠正错误；既有修订链的独立验证见下节。新验证保留本组不通过，不降低原研究 E2E 的正文、官方依据或保证范围要求。

### 既有修订链与验收标准提取的离线验证

**既有生产方法完成了一次明确错误的修订；另两次上游提取暴露了要求遗漏与阶段误判。** 本轮没有修改生产
Prompt、Schema、模型、预算或 Verifier，也没有运行真实 E2E。固定草稿的方法切片属于 Offline Eval，不能
把其通过解释为正式入口闭环，或据此改写之前单次草稿资格检查的失败。

原中文用户要求修订“系统已经完成所有写入。”，禁止无证据声称写入，并只返回可安全发送的文本。
历史 L06 归档 `data/e2e_traces/20260903T131204.577659Z-29312-f5be5b09/` 校验有效，但只记录一次
`passed` Receipt，没有被拒草稿到修订通过的过程。其冻结标准仅覆盖不得无依据声称写入，不覆盖完整输出要求。

本轮固定该历史标准和三份草稿，使用真实模型调用生产 `_verify_before_send`；只对明确错误最多尝试一次修订。
后续 Action 与 Final 均由生产 `_decide` 组装，直接消费实际返回的失败 `Observation`，不代写反馈或指定模型选择。

| 输入 | 实际结果 | 可以证明的边界 |
| --- | --- | --- |
| 系统已经完成所有写入。 | `not_satisfied`；模型选择进入 Final，改成“系统未观察到写入证据。”；再次 `satisfied` | 一次真实模型修订移除了写入断言，没有要求用户先补证据 |
| 目前无法确认写入是否已经发生。 | `satisfied` | 本次没有把不确认事实误当成需要证明事实发生 |
| 系统已处理请求。 | `satisfied` | 该句不必然声称写入，不能仅凭这条窄标准认定误判；也不能据此证明没有其他无依据事实或满足全部要求 |

归档为 `C:/pae/review-iteration-20260905/offline/20260905T101118.406894Z-23128-30a879ae/`。
三份草稿共 6 次逻辑模型调用、12,708 tokens；明确错误的修订切片耗时 12.891 秒。Action 出现一次
`provider_action_missing` 协议修复警告；初次无效响应未单独封存，逻辑调用数不等于 HTTP 请求数。
该切片没有执行完整 `respond`、正式 Composition Root、持久化、全部工具和模型预算逐次记账，不是生产整链重放。

随后预登记两次相同原用户输入，直接调用当前生产 `derive_interaction_intent`，结果如下：

| 样本 | 提取标准 | 阶段与问题 |
| --- | --- | --- |
| 0 | 仅无证据不得声称写入 | `review_plan`；用户要求直接修订，并未要求先提交中间产物等待审阅 |
| 1 | 仅无证据不得声称写入 | `deliver_final_result`；按当前 Prompt 定义需要此前分阶段审阅，而本输入没有该前提 |

两次均漏提“只返回可安全发送的文本”。原文跨度有效只能证明引用存在，不能证明模型理解正确；两份错误阶段均被
现有 Admission 接受。`ConversationService.respond` 在 `plan_review_required` 且无计划时，会拦截 Final 并要求
计划审阅，早于 Verifier 调用。这里是样本 0 的代码可达性推断，不是本轮已执行的 E2E 后果；样本 1 在无既有计划
时也不能被写成已经触发了计划替代。归档为 `C:/pae/review-iteration-20260905/intent/20260905T101344.995397Z-15316-89047131/`，
两次共 2,192 tokens，分别耗时 4.922 秒和 4.094 秒；不估计稳定错误率。

确定性审计核对三份来源归档的校验和、4 份 typed Receipt 与草稿哈希、真实失败反馈在 Action/Final 请求中的逐字
保留，以及 Intent Proposal 到 Admission 的可重建结果；251 个生产 Python 文件未变。审计位于
`C:/pae/review-iteration-20260905/audit/20260905T101930.747497Z-4564-6ff7827a/`。
当前下一步应先核实 `InteractionIntent` 的条件完整性与阶段边界，不继续增加 Final 同义指令或修改 Verifier 枚举。
这条相邻改稿反例尚不证明原研究失败由同一原因导致；正式入口复现、修复准入与原研究用户结果仍未闭环。

## Verifier 显式验收请求的单样本 baseline

**本项只核对正式路径是否会错误放行不满足比较要求的答案，不提前改造生产 Verifier。** 独立入口 `evals/product_baselines/test_conversation_research_review_001.py` 复用已有研究 HTTP 执行、隔离进程和归档器，结果契约由 canonical catalog 中的 `RESEARCH_TOOL_PROTOCOL_REVIEW_OUTCOME` 拥有。用户自然要求实际查阅官方资料，明确验收工具选择、权限检查、结果契约和有据结论；不注入 Draft、Observation 或 Receipt，不要求调用特定工具、产生特定 criteria 或走指定验证路径。

该入口与旧 20-item cohort 分离，只预声明 1 个样本，数据集版本为 `conversation-research-explicit-review-zh-v1`。复用已校准的 `research-answer-official-support-zh-v2`，用户结果仍只由最终答案的三项实质比较、官方引用支持和未扩大保证范围决定；未交付答案仍失败。评分不接收生产 Verifier 的判断。新旧请求的语义结果原子一致，但用户文本与 comparison identity 不同，不能机械配成历史普通请求的 target。

运行后单独核对：正式链是否派生验收要求、是否取得 Verifier Receipt、Receipt 是否绑定实际发送文本。只有独立结果验收拒绝了已发送答案、且生产 Receipt 对同一答案错误判为 `passed`，并能定位为候选覆盖的内容串扰或事实支持错误时，才得到对应生产失败证据。没有触发、正确拒绝、用户结果通过、预算终止和服务提供方失败都不构成错误放行 baseline，不把内部检查点写成 Product E2E 通过条件。

保持当前 `mimo-v2.5 + json_object + thinking=disabled`、生产 Prompt、Web Provider 与预算不变。参考相近但不同输入的有效样本，预计分钟级、约 90,000 tokens；货币成本不可用，不声称这是同配置性能配对。沿用现有 300 秒 HTTP 等待边界，不为触发 Verifier 降低预算。一个样本结束即停止；超过 60 秒或未复现错误放行均不追加采样，独立结果评测最多 1 次。具体命令由[运行与发布](04-running-and-release.md)维护。

2026-09-04 执行结果为 **`0/1`：完整答案中的事实错误被生产 Verifier 放行**。正式 Conversation 耗时 159.931 秒，pytest 为 183.26 秒；Agent 使用 126,087 tokens、6 个模型回合、7 次模型调用与 12 次工具调用。独立 grader 使用 2,386 tokens、13.896 秒。返回类型为 `answer`，正文实际包含三项比较与两组官方 URL，但写出“工具结果受函数定义的 Schema 约束”，并借 strict mode 的函数调用保证解释工具执行结果，违反不得扩大官方保证范围的用户要求。Product 归档为 `C:/pae/verifier-explicit-review-baseline-20260904/conversation-research-delivery-001/baseline/20260904T065450.300531Z-11388-8cf61181/`。

正式路径自然派生了三项 criterion，包含“说明内容不得把资料没有保证的事情写成保证”。第一次 Verifier 因 MCP 权限措辞拒绝草稿，却未指出上述 OpenAI 错误；第二次将三项全部判为 `satisfied`。第二份 `passed` Receipt 的 Draft 与实际发送文本逐字相同，SHA-256 为 `9459a00fc18635173932149a29cfec9fe8c621e529fdb65d82fbd1f66005a6dc`。因此反例属于外部事实支持的错误接受，不是标题覆盖错误、Receipt 绑定失败或无答案；两项未通过逐字来源跨度检查的 Intent 要求另作诊断，不能解释已经保留的保证范围要求为何被错误放行。

可见输入审计位于 `C:/pae/verifier-review-baseline-audit-20260904/20260904T070222.020790Z-4328-a8c31b20/`，所有来源归档 checksum 有效。审计保留原始 Journal 的字典顺序，由生产 materializer 重建两份 Verifier 参数，其 `execution_request_digest` 与正式 Trace 分别完全匹配；不是从完整 Artifact 拼出的增强输入。OpenAI Artifact 共 72 行，实际读取第 12—24、39—46 行；第 43 行包含 strict mode 的函数调用保证，但第 27 行的输入参数定义和第 38 行的 `Formatting results` 均未读取。MCP Artifact 共 17 行，实际读取第 1—16 行。全部返回窗口逐行与保存内容一致，Windows CRLF 原文件 hash 亦吻合。这说明正文保留与窗口读取仍成立，但关键原文存在不代表模型已消费；本次未证明 HTML 提取语义完整、证据选择充分或 Verifier 理解正确。

原始报告有两项诊断限制，保留而不追溯改写：独立 grader 对 MCP 限定措辞的另一条批评尚不足以作为失败依据，本次以明确的 OpenAI 结果保证错误立证；通用 `earliest_failure` 根据 `delivered=false` 与来源域名输出 `required_sources_observed_but_not_delivered`，但它没有分析已发送正文，不能用该标签推断 Completion 根因。预算 Finalization 已触发但仍交付了答案，本次失败不以 token 数量作为 gate。

历史隔离候选 `C:/pae/interaction-verification-separated-candidate-v6-20260903/report.json` 的 checksum 仍为 `36d1bef480f0e3833c4d6d0baf8bf5edf0ca78b60776aad49444c5261c186b5f`，历史 `12/12` 结果不改写；其配置是 `mimo-v2.5 + json_schema`，且标题控制输入含 Unicode replacement character。它不能充当当前 `json_object` 与本次实质错误答案的同输入资格证据；修复损坏字符的控制必须使用新输入身份，不能静默替换历史样本。本轮未再次调用候选模型，也未修改生产 Verifier；后续边界资格审查由[条件设计](../future/conversation-verification-false-positive.md)拥有。

事前登记位于 `C:/pae/verifier-review-preregister-20260904/20260904T065144.421118Z-15320-029cfa2e/`，原命令、原始 pytest 输出和生产源码不变核对位于 `C:/pae/verifier-review-execution-20260904/20260904T065451.540300Z-15320-9d8d2d4a/`。本轮只执行上述一个 live 样本；超过 60 秒后没有追加 E2E，不估计误判概率，也不声明整个隔离候选被否定、缺陷已修复或当前 revision 可发布。

本地相关回归为 `29/29 passed`、1.18 秒；collect-only 为 21 项，保留原 20 项并独立增加显式验收样本。Ruff、package DAG、devSpec 和 `git diff --check` 均通过；另核对 15 个本地链接、3 个标题锚点和 10 张表。命令、原始输出和变更源码归档为 `C:/pae/verifier-review-final-checks-20260904/20260904T070820.675917Z-33960-e4ba081a/`。本轮生产代码改动为零，只新增一个复用原执行器的 E2E 入口与相应契约检查，并清理过期 Future 描述；未执行完整发布矩阵。

## Loop 修复与验证执行预算的定向检查

2026-09-10，原 `tool-protocol-explicit-review` 正式入口两次定向运行均未交付，原始结果分别为 0/1，不能合并成同配置重复样本。第一次父进程 dotenv 覆盖预算，实际在旧 token 上限停止；第二次验证过父、子配置后，仍被 Verifier 的局部输出和工具超时限制阻塞，最后达到回合上限。两份密封产品归档为 [首次 target](../../.tmp/source-support-20260910/conversation-revision-boundary/formal-target/evidence/conversation-research-delivery-001/target/20260910T082222.972455Z-25308-e594b3f1) 与 [配置纠正后的 target](../../.tmp/source-support-20260910/conversation-revision-boundary/formal-target-configured/evidence/conversation-research-delivery-001/target/20260910T084147.121662Z-3716-76df590f)。失败验证的 Provider 用量未完整进入 Journal，不能把 committed usage 当作完整成本。

同轮错误计为一次尝试、终止计划反馈允许后续计划的确定性检查及真实恢复轨迹已执行，局部修复接入但不代表原任务完成。随后固定首次真实验证的完整入参，单次 Integration 取得绑定原稿的报告，支持接入局部执行预算调整；该报告仍错误放行无据权限归属，语义核心问题未解决。此 Integration 没有通过正式用户入口重新决策，不属于 Product E2E，不能覆盖两次失败结果；新验证预算尚无完整 target 通过。实际步骤、成本、反例与下一边界集中见[推进记录第 53 至 54 节](../optimization/revision-feedback-loop.md#53-按完整循环修复错误尝试计数并接入已证实改动)，当前生产预算由[验证专题](../topics/verification-and-completion.md)拥有。

## 独立来源支持标准接入后的正式验证

2026-09-10，中文 Verifier 契约与固定来源支持标准接入后，原显式验收研究请求执行一次真实 Product E2E。原始结果为 0/1，pytest 625.47 秒；HTTP 在 566.507 秒返回了完整答案，后置评分器因 1,200-token 空结构化输出最终发生 `StructuredOutputFailure`，未取得有效语义评分。原始结果见[正式 target 归档](../../.tmp/source-support-20260910/verifier-production-integration/formal-target/evidence/conversation-research-delivery-001/target/20260910T092941.387627Z-9240-f61be6d3)。

生产链两次调用新 Verifier：首份报告标准覆盖不合法，被确定性拒绝，模型继续生成不同草稿；第二份报告包含六条用户标准和固定支持项，全部通过后发送同一回执文本。正式触达、标准必检、用户标准保持及失败后重验成立；但人工复核发现最终稿仍扩大文档否定与工具结果 Schema 保证，独立支持项也错误放行。自动评分失败与生产语义漏放是不同事实，不能互相替代；原始诊断器指向的早期已恢复反馈不能作为最终失败根因。

Journal 提交用量为 300,602 tokens，15 个模型决策回合、16 次已记账模型调用、11 次工具调用；不含完整失败验证成本，不能视为完整 Provider 费用。当前按用户明确要求保留最小生产接入，189 项相关回归与包依赖检查通过；完整语义与发布门槛未通过。接入边界、样本差异及后续反例见[推进记录第 56 节](../optimization/verification-source-support.md#56-将独立来源支持检查接入正式-verifier)，当前行为由[验证专题](../topics/verification-and-completion.md)拥有，不重复保存第二份机制定义。

## 真实修订循环在原研究任务中的迁移验证

2026-09-11 按原 `test_conversation_research_review_001` 中文请求、用户身份、空会话及完整结果契约执行一次正式 Product E2E，经过 HTTP、生产 Composition Root、真实模型、检索、验证和最终交付链；未注入草稿或验证结果。模型 MiMo v2.5 thinking，URL capture 为原测试配置 `builtin`；生产与评测源码、Prompt 和 `.env` 均未修改。**原用户结果 0/1，pytest 为 1 failed、1 warning。** 后置语义评测沿 1,200 输出上限出现 `finish_reason=length`、空内容及结构修复，最终 `StructuredOutputFailure`；该自动结果保持，不能以人工检查替换为通过。

独立机制检查确认首份合法报告拒绝“应用执行代码，因此开发者负责权限检查”，Conversation 继续读取、实际删除该推导，新稿重验并与通过回执逐字绑定发送。但人工对照真实已读来源确认最终仍有错误：OpenAI 只读 32/122 片段却断言文档未定义权限责任；把 Forced Function 的对象参数写成 `forced` 字符串；把 MCP 结构化结果兼容性重复返回的 SHOULD 扩为所有结果都必须进入 `content`。后两项正确条款已经进入实际读取窗口，第二轮六项均 `satisfied`，构成独立于后置评测失败的生产误放证据。原 strict 参数保证扩为执行结果保证的特定错误本稿未复现，不以 MCP 的另一错误覆盖该区别。

HTTP 耗时 454.100 秒，pytest 522.50 秒；14 个 Conversation 决策回合、20 次工具调用，其中两次验证。Journal 记录 359,688 tokens，未纳入两次成功 Verifier 调用，后置评测完整用量也缺失，不能称完整成本。生产未预算耗尽、没有扩额或追加样本。原机器 `earliest_failure=offloaded_output_refetch` 后来恢复，不取代最终语义误放和后置评测协议失败的分别归因。完整输入摘要绑定、窗口、反馈消费与原结果见[机制审计](../../.tmp/source-support-20260911/formal-research-loop/mechanism-review.json)与[人工来源核对](../../.tmp/source-support-20260911/formal-research-loop/human-review.json)和[原始 target](../../.tmp/source-support-20260911/formal-research-loop/formal-target/evidence/conversation-research-delivery-001/target/20260911T025251.277711Z-31412-4c5a5f17)。本次证明正式循环存在一次有效修订，不证明多轮能够完整修复，也不构成发布通过。

## 读取状态修正的原研究任务复验

2026-09-11 在新读取状态契约下复用原 `test_conversation_research_review_001` 中文请求、身份和结果契约，由正式 HTTP、生产装配与真实 MiMo v2.5 thinking 进入；没有注入工具选择、草稿或报告。**原 Product E2E 为 0/1，1 failed、1 warning**，HTTP 103.039 秒、pytest 113.87 秒。4 个决策回合、5 次模型调用、2 次成功搜索，39,763 tokens；未预算耗尽，无正文读取或 Verifier，生产未交付 answer，依原契约跳过后置 grader。

最早停止原因是两个连续决策回合的 `continue_turn_no_progress`：搜索后虽然有读取计划，却未执行下一项动作或改变计划，最终 limitation。读取窗口尚未产生，因此“新状态实际进入真实模型 Context”及“空返回后取得新证据”的预声明局部检查点均为未覆盖。该失败形态在旧记录已有，但本轮 Action/工具说明已变，不能用发生得早证明全部模型决策影响无关。原失败保持，不重复抽样，不据冻结模型的读取投影检查宣布产品通过。

原始归档：[target](../../.tmp/read-result-contract-20260911/formal-target/evidence/conversation-research-delivery-001/target/20260911T044100.110985Z-29328-ab0a475b)。协议、独立读取 Contract、后续输入投影及保留工程修正的边界见[第 68 节](../optimization/evidence-acquisition.md#68-读取返回歧义的最小工程修正)。本次不撤回已有来源必检和修订循环，也不证明核心误放已改善；新读取契约仍缺真实消费验收，不具备完整发布证据。

## HTML 原文保真修复与验收边界

**Capture 原文删除缺陷的确定性反事实与最终版本真实链路检查点已成立；完整 Product E2E 仍失败，不能声明研究交付已修复。** 只读定位归档 `C:/pae/final-context-diagnosis-20260904/20260904T075613.408769Z-16476-9ba069a2/` 证明 `extract_html_text` 将 HTML 文本节点全局去重，删除后文重复的 `strict/true/false` 和连接词。封存官方 HTML 可精确复现旧提取文本；显式验收 baseline 的实际 Artifact 第 43 行具有同样损坏形态。该 HTML 快照不是那次 E2E 的原始响应，不声称网络字节相同。

修复只采用按源顺序保留文本的解析边界，核对了 [CPython HTMLParser 源码](https://github.com/python/cpython/blob/3.13/Lib/html/parser.py) 与 [lxml 文本提取源码](https://github.com/lxml/lxml/blob/master/src/lxml/html/__init__.py)；没有引入新依赖、主内容选择、Prompt 或模型调用。固定中文 Contract 的有效 baseline 为 `9 failed / 18 passed`，归档 `C:/pae/html-fidelity-baseline-20260904/20260904T081056.427149Z-39636-04b20b0a/`；初次运行的默认临时目录权限错误，以及早期诊断脚本对结果格式段落的错误匹配串，均保留但不作为产品反例。

第一修正版同组 `27/27 passed`，归档 `C:/pae/html-fidelity-target-20260904/20260904T081141.519997Z-24780-d87ebb66/`。随后兼容性反事实发现该版会粘连表格单元格与定义项，`2 failed / 27 passed` 封存于 `20260904T082050.760889Z-31476-813d45bb/`。同一解析 owner 补齐结构分隔后，最终 `29/29 passed`，归档 `C:/pae/html-fidelity-target-20260904/20260904T082113.177374Z-24568-5736c8d7/`。同一 OpenAI HTML 的最终提取文本为 119,079 字符、编码载荷 140,696 bytes，解析约 0.089 秒；`Setting strict to true` 与 `additionalProperties must be set to false` 完整保留，已有结果格式段落仍在。体积增加来自恢复原文，不构成效率收益，也不改变载荷上限。

第一修正版的同入口 `tool-protocol-explicit-review` target 为 **`0/1`**，归档 `C:/pae/html-fidelity-live-target-20260904/conversation-research-delivery-001/target/20260904T081937.922185Z-32488-c34867a5/`；与原 baseline 的机械身份配对通过。模型、`json_object`、关闭 thinking、预算、用户输入和 grader 均未改变；运行期间生产源码未变。pytest 227.78 秒，正式 HTTP 206.780 秒，Agent 130,984 tokens、7 个模型回合、8 次模型调用、10 次工具调用；独立 grader 2,329 tokens、11.134 秒。预登记和原始输出分别位于 `C:/pae/html-fidelity-live-preregister-20260904/20260904T081547.621160Z-36020-f34d6f82/` 与 `C:/pae/html-fidelity-live-execution-20260904/20260904T081939.100929Z-36020-37cc32aa/`。

该第一修正版 target 的答案有三项实质比较，未重现 strict 返回值保证错误，但 OpenAI 官方文档两次因 SSL EOF 未取得正文，模型改引社区讨论并将其当作官方工具文档依据，独立 grader 因引用支持不成立拒绝。MCP HTML 已经进入真实提取和 Artifact 读取链；OpenAI 原文保真检查点在该样本未触达，不能把没有重现原错误解释为因果修复。Verifier 首次报告未覆盖所有 criterion 被确定性校验拒绝，随后对最终文本全部判为 `satisfied`；这属于另行保留的验证反例，不授权本轮修改它。grader 未报告事实错误不代表已经证明所有措辞正确。

表格边界是在第一样本结束后补齐，不能沿用其 E2E 身份。复审成本后，最终版本另外预登记并执行一个同入口、同用户契约的 `tool-protocol-explicit-review` 样本；模型、`json_object`、thinking、预算、Provider 与 grader 保持不变，运行期间源码未变。最终 target 仍为 **`0/1`**：pytest 221.10 秒，正式 Conversation 213.104 秒，Agent 106,659 tokens、5 个模型回合、6 次模型调用、13 次工具执行（12 次业务工具与 1 次 Runtime Verifier）。未交付 `answer`，没有追加独立 grader。归档为 `C:/pae/html-fidelity-final-live-target-20260904/conversation-research-delivery-001/target/20260904T090241.660262Z-36900-064cc35f/`，与原 baseline 的机械身份配对及 checksum 检查通过；预登记和原始命令输出分别在 `C:/pae/html-fidelity-final-live-preregister-20260904/20260904T085858.402854Z-39272-930f6688/`、`C:/pae/html-fidelity-final-live-execution-20260904/20260904T090242.820475Z-39272-ac1529bf/`。

最终样本的首次搜索成功抓取 OpenAI 官方页，后续重复抓取才发生 TLS EOF；不能从日志尾部推断该来源从未取得。实际 Artifact 可连续重组 119,079 字符的 OpenAI 提取正文；`strict` 段落及其 `parameters` 要求跨物理行 67—68 完整保留，模型确实读到这两行。结果格式由调用方决定的原文位于 56—57 行，保存完整但未被读取。三份来源 Artifact 的原文件 SHA-256（Windows CRLF）、来源 offset 连续性及所有实际返回窗口的逐行相等检查均通过。审计归档为 `C:/pae/html-fidelity-final-live-audit-20260904/20260904T091224.856441Z-1920-a46d468b/`；它显式更正前一审计脚本把跨行句子当成单行匹配的诊断错误，未改写生产记录。本次没有保存原始 HTTP HTML，固定输入 Contract 与实际来源/窗口检查的证据边界仍须分开。

该次历史交付阻塞是：工具计数达到 12 时 Runtime 授予 Final-only；模型生成草稿，Verifier 将 6 项判为 `satisfied`，但随后 `offloaded_output_unread` 因 MCP 资料 `artg_ba1b1e9482d784e99317` 尚未读取拒绝交付，最终返回预算 `limitation`。它证明最终版本到达 Capture 与读取检查点，不证明草稿语义正确或用户要求满足。预算宽限随后按用户要求退役，见下节；原始失败不改写，未读门禁未绕过，已验收的解析机制不留作未来步骤。

本次一个样本超过 60 秒后未追加 live；影响路由选出的 E09 和完整 release matrix 仍未执行，不声明产品闭环、稳定正确率或可发布。运行前的独立网络诊断也观察到 TLS EOF，随后正式链路又取得正文；这些事实不足以把故障唯一归因于 Python TLS、代理或网站。

最终版本 live 后，相同本地回归再次得到 `236 passed`、14.11 秒，3 条第三方弃用警告；Ruff、package DAG、devSpec、主规范逐字一致及 `git diff --check` 均通过。命令与原始输出封存在 `C:/pae/html-fidelity-closeout-regression-20260904/20260904T091252.363315Z-12104-ac3b7b40/`。先前同版本 `236 passed`、14.30 秒及文档检查仍保存在 `C:/pae/html-fidelity-final-checks-20260904/20260904T082850.544568Z-36944-4b68fd16/`。相对修复前，生产代码仅 `capture/utils.py` 新增 47 行、删除 11 行，净增 36 行；本次续跑未再改生产代码、Prompt、预算、Verifier 或配置，无新模型调用机制、依赖、持久化或双轨。

## 研究硬停止与来源索引保持

**预算触发的工具隐藏/强制 Final 已退役，来源索引丢失的局部检查点已修复；研究及时交付仍未闭环。**
两项顺序验证，未同时更改预算值、模型、Prompt、用户输入或结果 grader。固定状态反事实不是 Product E2E。

预算责任边界的有效旧代码反例为 `7 failed`，三种硬边界、是否要求审查及已请求 Final 的边界均覆盖；
归档 `C:/pae/budget-stop-contract-baseline-fixed-20260904/20260904T094701.783897Z-12088-74b835d6/`。
删除后 Conversation 回归 `139 passed`；含可还原源文件的归档为
`C:/pae/budget-stop-source-proof-20260904/20260904T095803.396813Z-21880-234bbaf1/`。
旧生产源码可由本节上方 HTML 最终版事前登记恢复。较早归档包装器曾以相同 case 文件名覆盖源码项，
原始命令输出仍有效，但不声称其中含源码；后续改用独立 case ID，以上可还原源码归档已重新封存。

以下均为原样 `tool-protocol-explicit-review`，每个代码身份执行 1 次，原始 Product 结果均为失败：

| 代码身份 | 原始结果 | Conversation tokens | 模型决策回合 / 工具执行 | 正式 HTTP 耗时 | 检查点 |
| --- | --- | --- | --- | --- | --- |
| 移除预算宽限后的 target | `0/1`，预算 limitation | 83,477 | 4 / 10 | 74.249 秒 | 到期直接停止，无 Final 或 Verifier |
| 独立工作树恢复旧宽限的单变量对照 | `0/1`，预算 limitation | 73,021 | 7 / 5 | 142.795 秒 | 64,705 tokens 时授予宽限，后续 Final 增加 8,316 tokens，另调用 Verifier，仍被未读门禁拒绝 |
| 仅恢复来源索引后的 target | `0/1`，预算 limitation | 71,924 | 5 / 12 | 86.518 秒 | 索引实际可见，但没有自主提交 Final；无 Verifier |

前两份 Product 归档分别为
`C:/pae/budget-stop-live-target-20260904-product/conversation-research-delivery-001/target/20260904T095215.601464Z-25756-315ca592/`
与 `C:/pae/budget-stop-ablation-live-20260904-product/conversation-research-delivery-001/baseline/20260904T100008.987313Z-38456-1963b955/`，
机械身份配对通过。对照只还原三个预算相关生产文件，原始源文件来自前述封存快照；执行登记位于
`C:/pae/budget-stop-ablation-execution-20260904/20260904T095733.601996Z-14960-8526ff76/`。
这些随机轨迹不证明整体 token 或延迟收益；硬边界因果由固定状态反事实证明。
表中 usage 不包含 Verifier 内部模型 token，也不等于全部 Provider 请求数或总账单。

来源修复的有效 baseline 为四种真实 HTTP/Artifact 路径在模型投影中丢失 `data`，`4 failed`；归档
`C:/pae/source-index-contract-baseline-product-20260904/20260904T095447.385637Z-9512-8e5af989/`。
早期临时目录与夹具错误不作为产品反例。修复后相关 Contract/Conversation 为 `160 passed`、8.58 秒，
覆盖三种抓取状态、原文重组、读取精确性、失败与作用域；归档
`C:/pae/source-index-contract-final-20260904/20260904T100412.922807Z-24492-be110a00/`。

最后一份 Product 归档为
`C:/pae/source-index-live-target-20260904-product/conversation-research-delivery-001/target/20260904T100629.569654Z-39636-a14fe47f/`，
运行期间源码不变，未交付答案故未追加独立 grader。以前一预算 target 作为缺陷历史 baseline，比较身份完全相同，
保留其原始 target role，不重写或复制成新的 baseline。投影审计逐回合重建 Journal，并与实际发送的字符数相等：
第 3、4、5 轮分别消费 2、2、4 份卸载来源索引，`results/captures` 保持、正文未重新内联、读取引用不变。
本次 8 次搜索、4 次读取中，两次零命中，另两次返回 OpenAI 正文第 1—5/13—19 行与第 2—12 行，
含大量导航和开头内容；全部返回行与 Artifact 精确相等。Trace 未保存读取关键词，不能推断零命中的具体选词。

审计与源码净变化封存在
`C:/pae/research-stop-final-audit-20260904/20260904T100827.951872Z-9128-00c9afa9/`，来源 checksum 均有效。
本轮生产代码新增 38 行、删除 130 行，净减 92 行，无新模型调用、配置、持久化状态或双轨。
局部来源保持通过不证明模型已取得充分证据、研究更省或及时交付；不得把后续未交付归因为“已有证据足够”。
尚存取证选择问题回到[优化队列](../future/design-optimization-backlog.md)，不再保留已落地 Future 步骤。
未继续改 Prompt、预算或 Verifier，未执行完整发布矩阵，不声明整体修复或可发布。

最终相关回归为 `241 passed`、14.13 秒，三条第三方弃用警告；归档
`C:/pae/research-stop-final-regression-20260904/20260904T101039.469735Z-24892-eedb7708/`。
Ruff、package DAG、devSpec、`git diff --check` 通过，908 项默认测试仅完成收集检查，不能计入通过样本。
文档核对 21 个本地链接、1 个标题锚点和代码块配对；退役生产符号扫描无残留。静态检查归档为
`C:/pae/research-stop-final-checks-20260904/20260904T101216.338856Z-25904-59c971fe/`。

## 1. Conversation 与 Knowledge

| 用例 | 当前入口与边界 | 当前实际断言 | 审计分类 |
| --- | --- | --- | --- |
| `ASK-001A` | Conversation HTTP；真实模型/Postgres | 两条随机原文完整进入最终回答、冲突被明确呈现、不调用 web、不跨 principal、不写 Claim | **Product E2E**；case-specific typed grader 不规定工具、Plan 或答案布局 |
| `ASK-001B` | Conversation HTTP；真实 Web search | 个人项目事实与 OpenAI 官方 URL 进入同一回答、不跨 principal、不写 Claim | **Product E2E**；不再把固定工具名当作用户结果，窄范围路由由横切套件独立判断 |
| `L01` | 先通过 canonical Knowledge ingest 写入并核对 EvidenceSpan，再从 Conversation 自然召回 | 正确随机 marker、scope 隔离、有 Observation | **Product regression E2E**；准备步骤直接验证 canonical 事实就绪，测试目标是召回 |
| `L07` | Conversation 保存、确认；新 Conversation 召回 | 跨会话保存后可准确回忆 | **Product E2E**；覆盖自然保存到召回的完整纵切 |
| `E14` | Conversation 自然保存、确认、重启、replay | 精确 user span 被保存，控制语义不写入，确认前零写入 | **Product E2E**；完整副作用和恢复反事实 |
| `E01` | Conversation HTTP | 简单解释、模糊请求澄清、新问题回答、跨会话 secret 不泄漏 | **混合回归用例**；验证普通 Conversation 的回答、澄清、继续与隔离 |
| `DUR-001` | Conversation 后读取 `/api/conversation/runs/{ref}`，重启 Web | owner 可读 trace、其他 principal 404 | **安全/运维 Runtime Conformance**；主要结果是 trace API scope，不是普通 Conversation 用户结果 |
| `OBS-001` | 同一 trace scope failure + server log | log 中有同 run ref 的 typed deny | **Observability conformance**；不参与产品完成率 |

`ASK-001A` 的 `ask-001a-original-passages-v1` grader 使用固定 checksum 的六个离线控制：列表、表格和自然段三种正控制，以及摘要缺原文、只含一条原文和错误第二原文三种负控制。定向单元测试为 `6/6` 判定符合预期；这只证明 grader 能区分当前控制，不是一次 live Product E2E，也不增加产品通过证据。现有 Product E2E 已改为记录 typed verdict，并由该 verdict 替换只检查两个日期出现的弱断言。

2026-08-28 按 impact routing 执行当前完整 release selection，9 条 Product E2E 为 `0/9 passed`，因此当前版本不满足发布门禁。7 份在断言前调用 `_record` 的样本、`manifest.json` 和 `summary.json` 均写入 `data/e2e_traces/20260828T071606.468351Z-25036-24f54f07/` 并具有 checksum；其中 6 份在 8 个模型回合后返回预算 `limitation`，`L06` 返回了符合文本规则的审查结果但 typed disposition 仍为 `limitation`。`L07` 与 `E14` 在 `_record` 之前读取缺失的 `pending_confirmation` 并失败，只有 pytest summary、没有专用 trace，属于现有 release 证据缺口。完整 session 为 `1009.335s`，其中 9 个 call phase 合计 `977.402s`；最长单项 `ASK-001B=166.201s`，原目录顺序的首项 `L01=138.045s`，同一 archive 中最短失败项 `L06=8.990s`。迭代命令现从最近 checksum 有效的完整 release summary 读取 duration 并从短到长列出全部 node。随后真实执行排序后的完整 collection + `-x` 命令，首项 `L06` 在 call `19.746s` 后失败，包含 setup 的 session 为 `28.749s`，停止其余 8 项；旧顺序首项 `L01` 的 setup + call 为 `146.003s`，因此同一当前失败结论的实测反馈时间缩短约 `80.3%`。新 archive 位于 `data/e2e_traces/iteration-fail-fast-ordered-20260828/20260828T082131.529428Z-22992-c247d470/`，checksum 有效。完整发布命令、case、预算和断言不变。该矩阵没有产品 target 或消融，不能据此增加预算或修改生产语义；它只否决当前发布状态并证明本轮 `TraceArchive` 短临时 basename 可以在完整矩阵中保存已有的 7 份失败证据。

同日按 `TOOL-CALL-PROTOCOL-001` 的单用例顺序只执行了两次 `L01` pilot，均在失败后停止，没有运行相邻 live E2E。第一次位于 `data/e2e_traces/20260828T093010.828595Z-3436-657c2704/`：`0/1 delivered`，两个模型回合都因无现有工作清单却提交 `plan_step_id` 而得到 `working_plan_missing`，零工具执行，`17,286` tokens，call `86.869s`。一次有界阶段 Schema 修正后的第二次位于 `data/e2e_traces/20260828T093426.646593Z-31900-f843fbcc/`：原生动作成功执行一次 `search_personal_knowledge`，`invalid_arguments` 与 `working_plan_missing` 均为零；但 Observation 只引用项目 ID，没有包含已写入的随机颜色代号，随后两次重复搜索被确定性拒绝为 `personal_knowledge_already_searched`。该样本仍为 `0/1 delivered`、`22,887` tokens、call `72.255s`，同时违反用户结果和 `20,000` token 门槛。因此模型动作候选没有通过 G1，不能进入消融、G2 或发布判断；最早失败已迁移到个人知识证据选择与不足结果的恢复边界，不能继续归因于工具参数传输。两次 call 中真实知识写入分别占主要墙钟时间，缩短测试的安全路径不能绕过相同生产写入与随机隔离事实。

同一 L01 输入形状的第一份 EvidenceSpan 修复 pilot 位于 `data/e2e_traces/20260828T115253.819547Z-4604-fd4f8fd0/`，checksum 有效，结果为 `1/1 passed`。L01 准备步骤改从 canonical Knowledge ingest 写入，并在 Conversation 前断言当前 owner 与其他 owner 的随机码分别存在于各自 `EvidenceSpan`；生产摄取把模型返回的局部 semantic span 确定性扩展到所属完整原文句子。正式 Conversation 随后用 2 个模型回合、1 次 `search_personal_knowledge`、`15,326` tokens 和 `40.088s` call 返回正确 `cobalt-*`，成功 Observation 包含完整原文，`scarlet-*` 未进入 Trace。

后续重复证明第一份通过不足以关闭 L01。`20260828T115547.061007Z-13364-b6670342/` 中完整 EvidenceSpan 已就绪，但模型把 4 条 user source Claim 标为 `assistant_inference`，Admission 全部拒绝；`20260828T120537.038526Z-32392-a5f16531/` 中模型又把 3 条 `confidence=0.9`、grounding=supported 且没有 `uncertainty_reason` 的明确事实标为 `uncertain_claim`，它们均停在 grounded。这两份都返回 `no_answerable_claim` 后重复搜索并失败。修复后的 provenance 边界不再逐项改写模型枚举值：`created_by/source_type` 确定 `source_role` 与 assistant provenance，无理由 uncertain Proposal 非法；整批违规 Proposal 记录为 partial，并由已有 deterministic source extractor 重建候选。`data/e2e_traces/20260828T120921.171995Z-4604-203d851e/` 实际触发 `source_role` mismatch、成功 fallback 为 active external fact，Conversation 返回正确随机码，证明 Knowledge 最早阻塞已恢复；但模型在成功 Observation 后重复搜索，最终为 3 回合、`23,002` tokens，超过 G1 的 `20,000` 门槛。

L01 两个不同 owner 的 canonical ingest 已改为并发 setup；它不改变生产入口、模型、随机事实或隔离断言。并发后 `20260828T120426.308191Z-11040-49ac8af0/` 为 `1/1 passed`、call `36.369s`，相邻 `20260828T120537.038526Z-32392-a5f16531/` 为功能失败、call `53.943s`；此前同功能通过样本 `20260828T120030.001871Z-21992-d8a702bf/` 的串行 call 为 `166.502s`。由于模型与 Provider 延迟有方差，这些样本只证明并发 setup 保持了相同验证事实且可以缩短反馈，不把全部墙钟差值归因为编排收益。截至该组样本，G1 仍未达到 `3/3`；最早剩余阻塞是成功 Observation 后的重复动作与 token 放大，不再是 EvidenceSpan 丢值、Claim provenance 或 L01 预准备。

逐回合能力投影的 G1 target 随后达到 `3/3 passed`。Conversation 仍在首轮暴露 `search_personal_knowledge`；成功且已经提交的 `Observation` 出现后，下一模型回合从瞬时能力投影移除这个已经完成的动作。`Observation` 保持可见，`FinalMessage` 仍由模型生成。三份校验和有效的归档分别为 `20260828T122504.790664Z-16248-f5733c42/`、`20260828T122637.338162Z-23108-bc8308de/` 和 `20260828T122734.215000Z-3936-a9be6744/`。三次均为 2 个模型回合、1 次成功工具、零 `personal_knowledge_already_searched`、零 `invalid_arguments`、零工作清单反馈；`input_tokens`/`output_tokens`/`total_tokens` 分别为 `14,995/170/15,165`、`15,208/243/15,451`、`14,998/183/15,181`，`call` 阶段分别为 `35.420s`、`33.514s`、`36.339s`。总令牌都低于失败 baseline `42,184` 的 60% 门槛 `25,310`，平均 `15,266`，但 3 个样本不报告 P95。原固定 `20,000` 门槛没有上下文或历史分布依据，已由“正常路径严格 2 回合/1 工具”的协议门禁和同配置 baseline 至少降低 40% 的相对成本门禁替代。该变更按缺陷修复验收：令牌和延迟是观测值，不声明逐回合能力投影产生通用机制收益，因此不要求 target-minus-mechanism 消融。当前只剩 G2 相邻回归，尚不能声明完整候选或发布完成。

G2 曾在 `ASK-001B` 停止，当时没有运行 `L03`。`ASK-001A` 首次归档 `20260828T132649.305900Z-22004-a0640146/` 只返回第一条日期；用例当时没有验证两条 answerable Claim 是否已经准备完成，因此不能区分预准备方差与检索漏召回。评测准备随后增加 canonical EvidenceSpan 与 answerable Claim 断言，并让另一 owner 的独立 ingest 与当前 owner 的顺序写入并发；`20260828T133058.073442Z-27296-f3e1be2b/` 为 `1/1 passed`，两条冲突原文均进入 Observation，另一 owner 事实未泄漏，总时长从 `73.35s` 降至 `58.79s`。`ASK-001B` 同样补齐准备契约和并发写入；其旧归档 `20260828T133259.292544Z-9768-947d8f88/` 返回 `limitation`，6 个模型回合执行 7 次工具并消耗 `77,236` tokens。一次已经撤回的资格修正改为委托 `gpt_researcher`，虽然返回正确答案，但总时长为 `143.09s`，并被当时固定要求 `web_search` 的 Product 断言拒绝。该断言随后拆分：Product E2E 只判断项目代号、官方 URL、作用域隔离和零写入，`narrow_research_routing` 横切套件独立判断个人读取、Web 读取和零整体委托。窄范围路由 target `20260829T034725.095120Z-34396-26bfe90a/` 为 `1/1 passed`，使用 2 个模型回合、2 次工具、0 次智能体和 `19,674` tokens；Conversation call 为 `45.542s`，并行准备为 `21.317s`，完整样本为 `66.92s`。该样本超过 60 秒后没有继续运行当时的真实 E2E；在该时间点 `CONVERSATION-RESEARCH-DELIVERY-001` 仍留在未来队列。其后续结果见本节 2026-09-02 的记录，窄范围混合证据路由不再作为最早失败。

在 G1 关闭前，用户要求跨其他 E2E 核对 Tool Calling 阻塞，因而额外执行了三条单样本诊断；这些样本不算设计中的 G2 晋级。`L06` 位于 `data/e2e_traces/tool-calling-cross-case-20260828/l06/20260828T104106.166481Z-20536-9b01af6d/`，call `10.825s`、总 session `19.998s`：前置意图判断直接产生 `verification_capability_unavailable`，零工具执行，最终文本没有 verifier Receipt，故用例失败；该样本没有进入模型动作协议，暴露的是意图与能力装配回归。`RUN-001` 位于 `data/e2e_traces/tool-calling-cross-case-20260828/run-001/20260828T104151.816729Z-32700-3a9206ae/`，`1/1 passed`、总 session `17.368s`、`16,424` tokens：首轮两个 `external_records.read_one` 参数正确并发执行，A、B 两个 MCP Observation 成功，C 及后续重复动作被两次调用预算确定性拒绝。`E16` 位于 `data/e2e_traces/tool-calling-cross-case-20260828/e16/20260828T104245.678100Z-18276-17a4e69e/`，`0/1 delivered`、总 session `53.037s`、`72,622` tokens：两次参数正确的 `github.get_file_contents` 到达真实 MCP，但外部 GitHub 凭据返回 `401 Bad credentials`；随后四次 `web_search` 成功执行，交互最终因工具预算耗尽返回 limitation。三条诊断都没有出现 `invalid_arguments`、未知动作名、动作 JSON 解析或工作清单绑定错误；结合后续 G1 与 G2，当前证据支持“已观察用例中的原生动作传输不再是最早失败”，不支持“整体 Tool Calling 与用户交付已经解决”。个人知识证据选择已经由 G1 关闭；前置意图与能力装配、外部凭据、语义路由和失败后有界收口仍是独立阻塞，完整发布门禁尚未通过。

2026-08-28 的去重审计让 `E08` 与 `E17` 退出当前可执行矩阵，历史归档保持只读。`E08` 的 Ask 零写入已由 `ASK-001A/B` 覆盖，显式保存的权限、确认、重放和跨会话结果由 `E14/L07` 更强覆盖；`E17` 与 `L04` 重复执行真实 GPT Researcher A2A workload，其“成功 AgentArtifact 返回”职责已改由 `a2a_artifact_return` 横切套件读取 `L04` 的同一 Trace。其余 overlap graph 边表示共享局部不变量，不自动构成删除理由。

`MEMORY-A0-001` 是独立的重复产品回归，不进入上述 canonical catalog。当前用例从 `POST /api/conversation/turn` 进入，使用生产组合根、真实结构化模型和 Postgres。未授权事实晋升、显式保存后纠错、删除后的检索一致性三类自然旅程各执行五次，结果均为 `5/5 delivered`，服务提供方失败为 0。

| 结果与反事实 | 执行结果 | 证据边界 |
| --- | ---: | --- |
| 不确定资料和助手分析没有晋升为长期事实，另一用户看不到相关内容 | `5/5` | 只覆盖隔离测试用户和本组自然输入，不外推完整工作区或角色权限 |
| 明确保存后可以跨会话召回；自然纠正后，最终回答只采用新值和纠正原文 | `5/5` | 旧 `Claim` 在这条自然保存路径中仍为 `active`，关系被记录为 `duplicate`；没有出现陈旧答案，因此该内部诊断没有达到 A1 产品改动门槛，也不能声称自然纠正已经复用直接纠错入口的取代迁移 |
| 删除确认前事实仍可见；确认后答案和 `search_personal_knowledge` 结果都不含已删除值 | `5/5` | 只覆盖单条知识的自然定位、确认和立即查询，不外推批量治理或所有索引延迟 |

按需个人知识搜索改动后的 15 份归档位于 `data/e2e_traces/product_targets_memory_search_v1/memory-a0-001/target/`，使用 `memory-a0-001-deterministic-v2` 评测器。该版本不再寻找隐式 `personal_knowledge_context`，而是断言显式只读 `search_personal_knowledge` 的 `Observation` 和最终答案。15 个样本不足 20，不报告 P95；性能画像另由 `AGENT-PERF-001-MEMORY` 的 20 个独立样本承担。

`SECURITY-REAL-001` 也不进入 canonical catalog。旧路径在四类场景中为 `15/20 delivered`，五个个人资料禁止外发样本都因个人知识无条件物化而失败；当前代码 target 为 `20/20 delivered`。20 组 baseline/target 的输入、身份、初始状态和评测器一致，代码身份不同，checksum 配对全部有效。归档根目录分别为 `data/e2e_traces/product_baselines_security_v5/security-real-001/baseline/` 与 `data/e2e_traces/product_targets_security_v2/security-real-001/target/`。

`LOCAL-MCP-FILESYSTEM-SANDBOX-001` 是不进入发布目录的受控 A0 风险 baseline。正式 Conversation HTTP 在 9 个已执行样本中均选择生产 stdio MCP 工具，合法文件和本样本目录外的随机 `PRIVATE-CANARY` 均进入模型可见 Observation（`9/9`）；最终答案复述私有 canary 为 `6/9`，完整交付两个合法条件仅 `1/9`。余下 11 项即使全部泄露也最多 `17/20`，达不到预声明 `18/20` 用户可观察泄露门槛；同时已消耗 `205,063` tokens，超过 `200,000` 总预算。逐样本门禁因此在第 9 项拒绝并避免执行 11 项，首个不可逆失败约束为用户可见泄露门槛。结果只证明当前进程缺少操作系统文件边界这一 Runtime 风险，不证明沙箱候选能改善用户结果，也不准入生产实现；未来设计项和主队列入口已按退出条件删除。有效 archive 位于 `data/e2e_traces/product_baselines/local-mcp-filesystem-sandbox-current-20260828/local-mcp-filesystem-sandbox-001/baseline/`，门禁 archive 位于 `data/e2e_traces/promotion_gates/local-mcp-filesystem-sandbox-formal-baseline/`。

`CONVERSATION-CONTEXT-PRESSURE-001` 同样不进入发布目录。第一批按单旅程分组的短控制在第 `5/40` 项以 `3/5 delivered` 被门禁拒绝；随后用完全相同的 20 对输入、随机事实、模型、预算和 grader 交错四类旅程，短控制在第 `7/40` 项再次以 `5/7 delivered` 被拒绝。两次失败分别覆盖旧/撤回事项复述、typed limitation 和无法生成备忘录，第二批两个失败跨事实纠正与范围撤回；Provider/入口错误和跨样本污染均为 0。失败在 8 条消息短路径已经成立，因此不能归因于计划中的 48 条消息长历史，33 个剩余样本被早停。有效样本位于 `data/e2e_traces/product_baselines/conversation-context-pressure-interleaved-v2-20260828/conversation-context-pressure-001/baseline/`；修复 Windows 临时路径后以同一密封证据写出的门禁 archive 位于 `data/e2e_traces/promotion_gates/conversation-context-pressure-interleaved-baseline-v2/conversation-context-pressure-baseline-001/20260828T071100.383357Z-23680-2da931f8/`。该 A0 假设未晋级，未来设计项和主队列入口已删除。

`BACKGROUND-CONTINUATION-DEMAND-BASELINE` 没有独立用户样本来源。仓库内现有请求都是用于验证 typed limitation/撤回机制的合成评测输入，不能反过来证明用户需要可查询、暂停、恢复或调整的响应后生命周期。由于当前用户目标也未提供这类自然需求样本，继续生成提示词只会人为指定机制；该项未执行伪 baseline，已从优化队列删除。新的独立用户证据出现时必须作为新 A0 重新准入。

`AGENT-PERF-001` 已完成五个任务族的独立画像。`data/e2e_traces/product_baselines_agent_perf_v1/` 中，直接回答、Plan 和 Memory 召回各有 20 个同配置样本，均为 `20/20 delivered`；延迟 P95 分别为 2.13、4.33 和 3.68 秒，总令牌 P95 分别为 7,573、7,941 和 14,620。显式委托历史组位于 `data/e2e_traces/product_agent_perf_delegate_v5/`，结果为 `10/20 delivered`；当前代码同配置组位于 `data/e2e_traces/product_agent_perf_delegate_current_20260827/`，退化为 `2/20 delivered`，P95 202.786 秒、总令牌 989,369，包含 11 次子级超时和 7 次子级完成但父级未交付。当前 9 份成功 `AgentArtifact` 全部已有 typed `artifact_ref` 和 parent-visible `content_excerpt`，其中 2 份最终交付；其余 7 份失败不来自投影缺失，失败交互合计出现 35 次 `invalid_arguments`，模型在已有完整 Artifact 后仍提出缺参数的 Artifact 读取或额外搜索。`working_plan_incomplete` 为 0，因此不得新增镜像 Artifact、自动完成 Plan 或把子级 success 当父级 Completion。两组各 20 份归档的校验和错误均为 0，不得跨代码状态合并。100 工具组仍引用 `TOOL-DISCOVERY-SCALE-001` 的 20 样本结果。不同任务族不能合并为统一 P95。

`INTERACTION-INTENT-DELEGATION-BOUNDARY-001` 单独测量显式前台委托是否被错误解释为后台持续工作，不证明 Agent 交付。只读 Provider 诊断为轮转输入 `1/20`、同输入重复 `3/20` false-background；首次正式 HTTP baseline 为 `5/20`，证据位于 `data/e2e_traces/product_interaction_intent_delegation_boundary_20260827/interaction-intent-delegation-boundary-001/baseline/`。删除第一个失败候选后，原代码同输入重复 baseline 为 `0/20`、P95 `32.356s`、最大 `37.684s`，证据位于 `data/e2e_traces/iidb_repeat_20260827/interaction-intent-delegation-boundary-001/baseline/`；两批合计 `5/40`，说明语义输出存在 Provider 方差。2026-08-28 的新正式 HTTP baseline 又得到 `2/20` false-background、`18/20` 正确前台边界，耗时 `223.54s`，继续证明错误属于同一 `InteractionIntent` 语义 owner，而非已撤回 Prompt 的稳定缺口。delivery-boundary tagged union 随后的后台正控制 target 在第 10 个样本出现 false-negative 后被门禁停止，候选代码和专用测试已删除。历史双证据 span、对比 Prompt partial target 与交错 Provider Conformance 仍只作撤回机制的诊断史；对应可执行 contrast runner 已删除，密封 archive 保持只读。

`CONVERSATION-RESEARCH-DELIVERY-001` 的历史 v1 聚合 baseline 为 `0/20 delivered`。2026-08-28 将执行粒度改为 20 个独立 pytest item 后，旧生产路径在前两项均失败，门禁随即停止其余 18 项。随后“供应商原生工具决策传输”候选的有效正式 target 在第 3 项被门禁否决：`1/3 delivered`，共 `190,159` tokens、P95 `111.148s`，`invalid_arguments=0`。其中一份 v2 `required_result_missing` 实际在不同标题中完整表达了“工具定义与选择机制”“权限与安全边界”和“结果契约”，只是复合词没有逐字相邻；该 archive 仍按预声明 v2 grader 记为失败，不能事后改判。grader v3 破坏式改为同一句或标题内的预声明原子概念共现，并由分段负控制约束；对该密封样本的离线诊断为三项概念和两组来源全覆盖，但不计正式结果。

在未改变生产代码的全新 v3 baseline 中，前两项均未交付：第 1 项为 `agent_execution_failed`，含 13 次 `invalid_arguments` 和 2 次失败 Agent；第 2 项为 `tool_arguments_rejected`，含 12 次 `invalid_arguments`、2 次 `plan_step_not_pending` 和 2 次成功 Agent，但零成功 Tool。两项共 `120,062` tokens、耗时 `351.71s`，门禁在第 `2/20` 项拒绝并停止其余 18 项。该结果证明字面 grader 假阴性已从后续实验中移除，同时当前生产失败仍跨错误委托与工具参数两个最早阶段；不得用一个局部候选混合修复。v3 样本位于 `data/e2e_traces/product_baselines/conversation-research-v3-current-20260828/conversation-research-delivery-001/baseline/`，门禁位于 `data/e2e_traces/promotion_gates/conversation-research-baseline-v3-current/`。原生工具候选仍因产品 target 未达 `19/20` 而保持删除；其三份密封样本与门禁分别位于 `data/e2e_traces/product_baselines/conversation-research-delivery-001/target/` 和 `data/e2e_traces/promotion_gates/conversation-research-target-native-tools-valid/`。

随后只在现有 structured decision 提示中增加 `tool_name -> input_schema.required` 显式绑定，未改变 Provider、Admission、Plan、预算或 Tool 实现。正式 target 第 `1/20` 项仍产生 15 次 `invalid_arguments`，没有成功 Tool/Agent，`49,459` tokens、`96.597s`，以 `tool_arguments_rejected` 被零容忍门禁拒绝并停止余下 19 项。候选提示、契约测试和未来设计项已完整删除；有效 archive 位于 `data/e2e_traces/product_baselines/conversation-research-argument-binding-target-20260828/conversation-research-delivery-001/target/`，门禁位于 `data/e2e_traces/promotion_gates/conversation-research-argument-binding-target-20260828/`，两者 checksum 均有效。该结果只否定“重复现有 schema 绑定指令”机制，不能证明应由 Admission 补参数。

2026-08-29 的当前代码单样本 pilot 首次按执行顺序重放失败事件。HTTP 交互耗时 `146.447s`，总计 `72,832` tokens；4 次 Web Search 和 2 次智能体委托成功，2 次 `read_action_output` 因引用类型不是 `artifact` 而执行失败，最终在再次综合前返回预算 limitation。首个动作拒绝为 `working_plan_missing`，但后续成功搜索已经绑定对应来源步骤，因此不能把该事件当作 Plan 根因。服务日志显示两次智能体等待分别为 `69.5s` 和 `80.469s`，pytest 与归档开销不是主要耗时。密封归档位于 `data/e2e_traces/product_baselines/conversation-research-earliest-failure-pilot-20260829/conversation-research-delivery-001/baseline/`，checksum 有效；归档内首版 `earliest_failure` 曾把不会阻止循环的 `verification_capability_unavailable` 误记为 Admission，当前 harness 只读重放已修正为 index 1 的 `working_plan_missing`，密封原件未改写。

同日只执行一次“不存在未读 Artifact 时隐藏 `read_action_output`”候选 target。该样本没有工具或智能体执行失败，也没有参数拒绝；4 次 Web Search 成功，HTTP 耗时降为 `51.231s`，但累计 `69,203` tokens 后仍返回预算 limitation，用户结果未交付。候选已从生产代码和专用测试删除，不能把耗时下降解释为能力修复，也不得重跑相同变量。密封归档位于 `data/e2e_traces/product_targets/conversation-research-read-output-projection-20260829/conversation-research-delivery-001/target/`，checksum 有效。两个样本均遵守单样本停止条件，没有继续运行相邻 E2E；当前剩余归因必须分离工作项未完成、上下文增长和最终综合未发生，尚无活动生产候选。

随后首个 `A2` 候选只删除 auto/no-plan 动作 Schema 的合成 `plan_step_id`，未修改预算、Completion、工具实现或 grader。相同 `tool-protocol-boundary-run-1` 定向 target 为 `1/1 delivered`、HTTP `80.613s`、`77,581` tokens、4 个模型决策回合；9 次 Web Search 全部成功，Agent 调用、DecisionFeedback 和 working plan 均为零，两组官方来源与三个比较维度全部覆盖。与上述失败 baseline 的机械配对校验通过，证明该样本不再被 Plan 协议阻塞并已交付用户结果。该候选只声明交付正确性，不声明成本或延迟改善；失败 baseline 在最终综合前停止，不能与已交付 target 直接计算成本改善比例。只读重放进一步确认，9 次搜索返回 45 个 URL，其中 43 个唯一，原始查询没有进入 canonical Trace，因此不能把当前问题简化为重复搜索；每轮动作定义保持 `15,679` 字符，typed inputs 从 `0` 增长到 `21,949`、`62,469` 和 `90,816` 字符。后续效率诊断没有在同一成功代码身份下形成稳定成本阶段，未准入生产机制。密封 target 位于 `data/e2e_traces/product_baselines/conversation-research-planless-target-20260829/conversation-research-delivery-001/target/`。

同日补做的 clean 因果配对没有成立。clean target 使用提交 `d0de6b3`；target-minus-mechanism 使用其直接子提交 `c66fe94`，只恢复 auto/no-Plan 场景的必填 `plan_step_id` 投影。消融样本取得 4 次成功 Web Search，但模型进入可验收工作项清单后收到一次 `working_plan_no_change` 和一次 `completed_plan_step_immutable`，最终保留两个待完成步骤并返回 `limitation`；交互耗时 `79.660s`，总计 `83,922` tokens。归档位于 `data/e2e_traces/product_ablations/conversation-research-plan-binding-ablation-20260829/conversation-research-delivery-001/baseline/20260829T134532.983717Z-22796-e4dc8084/`。随后 clean target 在服务提供方返回 HTTP `200` 后以 `provider_action_payload_invalid` 停在动作解码阶段，正式入口返回 HTTP `503`，没有形成模型 usage 或工具执行事实；归档位于 `data/e2e_traces/product_targets/conversation-research-plan-binding-clean-target-20260829/conversation-research-delivery-001/target/20260829T134743.682123Z-32568-a8d4c9cc/`。两份归档校验和有效，代码身份干净，用户输入、初始状态、服务提供方配置和评测器一致。消融失败支持强制 Plan 绑定会引入额外失败路径，但 clean target 没有交付用户结果，因此这组结果不能完成单变量因果证明，也不能用既有 dirty target 的单次成功覆盖本次失败。

2026-08-30 只增强动作解码的脱敏诊断后，对相同首个样本执行了一次有界 target。Provider 在五次成功 Web Search 之后返回 HTTP `200`，action name 与 JSON 语法均通过 Adapter；Application 随后以 `provider_action_working_plan_payload_invalid` 拒绝 `control_working_plan`，字段路径为 `$.working_plan.<unexpected>`，错误类型为 `extra_forbidden`。working-plan action definition 的嵌套对象已经声明 `additionalProperties: false`，Adapter 同时发送 `strict: true`，因此本次结果定位的是服务提供方未稳定遵守 strict tool schema，而不是 JSON 无法解析或 Tool 参数包装错误。正式入口仍返回 HTTP `503`，单次请求耗时 `67.428s`；密封归档位于 `data/e2e_traces/product_targets/conversation-research-action-diagnostics-20260830/conversation-research-delivery-001/target/20260829T164358.679908Z-8284-1fc763df/`，checksum 有效。该 archive 绑定 dirty digest `00448b9438e26f6f3fcb0e0cce3373cb9beceec1338cb9d0d945394cb9affb1c`，只用于失败定位，不是 clean 产品 target、因果证明或发布证据；历史 clean archive 的粗粒度错误码保持原样。

随后增加默认关闭的字段名诊断开关，并在本地显式开启后只复现同一样本一次。该次 Provider 没有再次产生违规 working-plan payload；正式入口正常返回 `limitation`，6 次 Web Search 均成功，但先后出现 `plan_step_binding_required` 和 `working_plan_no_change`。样本耗时 `70.630s`，5 个模型回合共使用 `91,922` tokens，三个比较维度和两个来源组均未交付。密封归档位于 `data/e2e_traces/product_targets/conversation-research-action-field-diagnostics-20260830/conversation-research-delivery-001/target/20260829T170358.044117Z-26008-dd625d8d/`，checksum 有效，绑定 dirty digest `99e9410158adda594c3ef630afbdc1f04079dce71e0482bfaf11324f92468524`。这次没有产生可显示的未知字段名，因此不能猜测前一样本的具体额外字段；两次同输入结果共同说明服务提供方输出存在方差，并且 action protocol 通过后仍会进入独立的 Plan 绑定与更新失败。按单样本停止条件不再追加复现。

扁平化 `control_working_plan` action Schema 后，隔离 Provider Conformance 的预声明三样本为 `3/3` payload 合法、零 Provider failure 和零 Schema failure；该结果只允许本地 Plan 协议进入实现，不覆盖上述历史 Provider 方差。按 ADR 0016 删除模型侧逐动作 `plan_step_id`、增加唯一 `in_progress` Step、把执行事实内部关联到活动步骤，并把 FinalMessage 验收放到 Plan 完成物化之前后，`CONVERSATION-RESEARCH-DELIVERY-001` dirty target 为 `1/1 delivered`：三个比较概念和两组官方来源全部满足，5 次工具调用均成功，5 个模型回合共 `55,438` tokens，HTTP 交互 `67.515s`。密封归档为 `data/e2e_traces/product_baselines/conversation-research-delivery-001/target/20260830T025230.048438Z-24020-89651bb6/`，checksum 错误为 0，绑定 dirty digest `4a9a7b4a07b8e1065a42fb32019b2e7a62c38462349dc1225a970ff542d8c87e`。它证明该工作树交付了单个目标结果，不是 clean release 证据，也不能与不同代码身份的历史消融拼成当前因果配对。

2026-09-01 曾在唯一效率机制形成前预注册三个同输入样本和 `1.5×` Context 组成门槛，并只执行了第一个 `tool-protocol-boundary` Product E2E。正式入口无 entry error，10 次 Web Search 全部成功且没有 DecisionFeedback；模型用 5 个决策回合、10 次工具、`62,927/588/63,515` input/output/total tokens 和 `87.345s` 后返回 `answer`，但 FinalMessage 只有“基于……以下是两者的详细比较”这一句引导语，三个比较维度与两组官方来源均未交付，离线最早失败为 Completion 阶段的 `required_sources_observed_but_not_delivered`。逐回合 `model_action_definition_chars` 为 `12,596/12,596/12,596/12,596/2`，`typed_inputs_chars` 为 `0/12,953/23,281/49,937/49,937`；累计分别为 `50,386` 和 `136,108`。评审确认该门槛不是用户结果、Runtime 不变量或已设计机制的验收条件，且失败路径的组成比例不能选择效率 owner，因此三样本与 `1.5×` 契约已撤回；原 pytest 与归档保持历史事实，不冒充效率 baseline。密封归档位于 `data/e2e_traces/product_baselines/conversation-research-efficiency-current-20260901/conversation-research-delivery-001/baseline/20260901T131850.755367Z-34416-07c23374/`，checksum 有效，绑定 `main@e8ab48f` 与 dirty digest `77deb8444b930b5bb29009ffcb83e7c52c81cd99c88b963cf8de4e83bad83172`。

撤回后只读比较现有两份 v3 成功 `tool-protocol-boundary` Trace。`e756e33` dirty 样本为 4 个模型回合、9 次成功 Web Search 和 `77,581` tokens；9 个 execution request digest 全部不同，45 个结果 URL 中 43 个唯一，各次新增 URL 为 `5/5/5/4/5/5/5/5/4`，累计动作定义与 typed inputs 分别为 `62,716` 和 `175,234` chars。`d0de6b3` dirty 样本为 5 个模型回合、5 次成功 Web Search 和 `55,438` tokens；5 个 digest 全部不同，20 个结果 URL 中 18 个唯一，各次新增 URL 为 `5/5/4/4/0`，两类累计组成分别为 `64,845` 和 `71,956` chars。两份样本共享自然输入、v3 grader 与配置 cohort，但代码身份不同；搜索调用相差 4 次，Context 组成关系也从约 `2.79` 变为 `1.11`。request digest 只能否定字节级重复，URL 增量不能证明 required evidence 增量，原始查询又不在 canonical Trace，因此当前既没有稳定的搜索停止缺陷，也没有稳定的 Context Materialization 主导项；不准入生产机制或机制 eval。

2026-09-02 按预声明效率诊断在同一工作树、同一 pytest 进程中启动三个 `tool-protocol-boundary` 成功样本队列，并使用 `-x` 固定任一用户结果失败即停止。首项即为 `0/1`，所以余下两项没有执行，失败路径的资源数字也没有进入效率比较：Conversation 调用 `113.184s`，12 次 Web Search 与 1 次 Runtime Verifier 均执行成功，6 次模型调用共 `68,772` tokens；12 个业务 execution request digest 全部不同，没有出现精确重复动作。工具预算在 12 次已提交调用后正确触发 Final-only，边界后没有业务动作。该结果否定了“先取得三次同身份成功路径再定位稳定成本阶段”的前置条件，`CONVERSATION-RESEARCH-EFFICIENCY-001` 因而退出 Future 队列，没有效率机制、target 或消融获准。密封归档为 `C:/pae/conversation-research-efficiency-diagnostic-20260902/conversation-research-delivery-001/baseline/20260902T091522.689947Z-38632-6a2ea092/`，校验和有效，绑定 `main@e8ab48f` 与 dirty digest `b5b6e7fff5acdbfe7dcda0c86038bbf23611d65e6983c233302f6242e12551a3`。

同一失败样本形成独立的 Verification 分类反例。Final 草稿只有标题；Runtime Verifier 实际收到 12 条成功执行证据，其中包含 OpenAI 与 MCP 官方来源。五条 criterion feedback 均明确指出草稿缺少比较正文或 URL，却全部使用 `insufficient_evidence`，整体 verdict 因而返回动作相位；此时动作预算已耗尽，最终为 limitation，三个比较维度和两组官方来源均未交付。最早失败是 Verifier 把“修改现有草稿即可满足”误分为“必须补充执行证据”，不是 Final-only、证据投影或 Completion。该反例只准入 `CONVERSATION-VERIFICATION-ROUTING-001` 的 A1 设计与真实模型分类评估，不证明候选机制有效。

随后只尝试一个零新增调用的 criterion 协议候选：把模型输出的 `satisfied/not_satisfied/insufficient_evidence` 改为直接表达下游处置的 `accept/revise_draft/collect_evidence`，整体 verdict 与 Runtime 相位保持不变。预声明真实模型 Offline Eval 覆盖五个语义边界、每项三次，严格门槛为 `15/15`；实际为 `8/15`，零调用失败、`13,909` tokens，候选被拒绝。其中完整草稿为 `3/3`，标题缺正文为 `2/3`，混合改稿与补证据为 `2/3`，已有错误事实但证据不支持为 `0/3`，无执行证据的禁止性断言为 `1/3`；后两项还出现相互矛盾的处置。结果证明字段改名不能稳定承担细粒度认识论分类，不能通过重跑、放宽门槛或追加 Prompt 将其晋级。生产字段、Prompt、聚合、专用评测脚本和 Future 详细设计均已删除，`CONVERSATION-VERIFICATION-ROUTING-001` 退回没有活动候选的 A1。密封 Offline Eval 位于 `C:/pae/interaction-verifier-routing-target-20260902/`，checksum 有效，绑定 `main@e8ab48f` 与 dirty digest `855b7ae7fdd9ebe64bcdc6ad7d0ca34f4c3368b14ff83ea1f1d2d6722e1329e3`；它只证明 Verifier 分类边界，不是 Product E2E。

同日又按生产 Prompt 新规范尝试一个结构化 `v4` 候选。该候选保留既有三类 status，把目标、输入权威、成功标准、互斥决策顺序、四个边界示例、硬约束、typed 输出和停止检查分区表达，并用 JSON 隔离草稿与证据。固定 `5 × 3` Offline Eval 采用首个失败即封存的停止条件；第一个“标题草稿、证据充分”样本即把五项全部误判为 `satisfied`，说明模型把证据内容当成了草稿内容。结果为 `0/1`、零服务提供方错误、`1,426` tokens，后续 14 个样本和 Product E2E 均未执行。`v4` 正文、JSON 输入、版本和专用 runner 已删除；原 `v2` Prompt 只做字节保持的 Registry 迁移，不构成语义修复。密封 Offline Eval 位于 `C:/pae/interaction-verifier-routing-target-v4-20260902/`，report checksum 为 `5f3369ecd76baa5627b9325f8074f398fabcce45ca88fd357aeac290393bc4c4`，绑定 `main@e8ab48f` 与 dirty digest `e67f711f1dc4cdaa8a9200059b2549c96d4f74bf13c48386f35918f71ba3469e`。该结果再次拒绝 Prompt-only 候选，当前问题仍是没有活动设计的 A1。

同日的下一项候选把每条 criterion 拆为 `draft_status` 与 `repair_status`，但仍在同一次模型调用中同时发送草稿和证据。评测先修正了一处合成证据未明确覆盖权限边界的问题，再以相同输入重建 `v2` baseline 与候选 target；两份归档的 input digest 均为 `fbdcaefedd01b1be69c7feafcb761715c997b8bb2d6813c92ce3b0b3f9c35ae3`，checksum 有效。`v2` 在首样本把证据中的三项比较正文和两个 URL 全部当成草稿内容，结果为 `0/1`、`1,210` tokens。双轴候选把五项草稿满足度全部纠正为未满足，却又把证据已经明确提供的三项比较事实判成需要新增证据，结果为 `0/1`、`1,499` tokens；两次均无服务提供方失败并按预声明条件早停。该结果拒绝“同一次调用内拆字段”的候选，只支持继续评审输入隔离，不证明两次调用有效。归档分别位于 `C:/pae/interaction-verifier-routing-dual-axis-baseline-v2b-20260902/` 和 `C:/pae/interaction-verifier-routing-dual-axis-candidate-v5b-20260902/`。

随后候选把草稿与证据拆成两次隔离调用：第一次只看草稿和 criteria，第二次接收锁定的草稿报告与证据。它把原始“标题草稿＋充分证据”边界稳定分类为 `3/3 needs_revision`，完整且有依据的草稿为 `3/3 passed`；第 7 个样本也得到正确整体 verdict `insufficient_evidence`。但第一次调用只有 `text_satisfied/revision_required` 两态，无法表达“草稿已经写出事实声明，但其支持度必须交给证据阶段判断”，因而把该样本错误标成 `revision_required`。候选按内部契约门槛以 `6/7` 早停，14 次模型调用共 `11,510` tokens，零服务提供方失败、零 60 秒超时；它证明输入隔离消除了已执行六个样本中的原串扰，却没有形成完备的阶段协议。密封 Offline Eval 位于 `C:/pae/interaction-verifier-routing-isolated-candidate-v1-20260902/`，checksum 有效，input digest 为 `f4b12da1ad2677f52e86f16dbf4a2d519e50838be8592e6d8eb6bf64d9d4de6e`。两态候选已撤回，不能作为生产效果或 Product E2E 证据。

最后一个有界候选在第一次隔离调用增加 `evidence_check_required`，只把已写入草稿、但仍需事实支持度判断的项目交给第二次证据调用。相同固定输入下，旧生产契约首项即失败，为 `0/1`、`1,133` tokens；三态隔离候选通过标题草稿的三次重复后，在首个“完整且有依据的草稿”样本把应延迟证据判断的项目标成 `text_satisfied`，虽然该样本整体 verdict 恰好仍为 `passed`，该状态会让第二阶段跳过事实支持度检查，违反预声明的安全边界，因此按内部契约以 `3/4` 早停。候选共 8 次模型调用、`7,781` tokens，零服务提供方失败、零 60 秒超时；baseline 与候选 input digest 均为 `f4b12da1ad2677f52e86f16dbf4a2d519e50838be8592e6d8eb6bf64d9d4de6e`，两份 checksum 有效。密封归档分别位于 `C:/pae/interaction-verifier-routing-deferred-baseline-v2-20260902/` 与 `C:/pae/interaction-verifier-routing-deferred-candidate-v2-20260902/`。该结果否决三态隔离协议，候选 Prompt、schema、runner 与 Future 详细设计已删除；生产 Verifier 未修改。在出现新的失败阶段和独立机制依据前，不再增加相同 Prompt、状态或调用依赖。

随后根据三态候选暴露的跳过边界，只尝试一个真正正交的 Draft／Answerability 候选：Draft 调用只判断文字是否需要修改；Evidence 调用看不到 Draft report，必须独立判断每条 criterion 利用当前事实是否可回答；adapter 才按固定真值表聚合。第一份 cohort 在标题比较样本的第 3 次重复以 `2/3` 早停，但 Evidence feedback 准确指出合成夹具没有明确提供 MCP 选择机制与 OpenAI 权限边界的对侧事实，因此该预期不成立，归档 `C:/pae/interaction-verifier-routing-orthogonal-candidate-v1-20260902/` 只保留为无效评测设计诊断。只补齐这两条可由 OpenAI Function Calling 与 MCP Tools 官方规范复核的对侧事实后，Prompt、schema、期望、模型、预算和门槛均保持不变；有效 cohort 通过前三类共 9 个样本，在首个“禁止声称未观察的后台执行”样本失败。Draft 正确返回 `revision_required` 并要求删除或限定断言，Evidence 却要求先取得导出确实发生的证据并返回 `additional_facts_required`，尽管正确回答只需删除未经支持的断言。结果为 `9/10` 后早停、20 次模型调用、`13,400` tokens、零终态服务提供方失败、零 60 秒超时，input digest 为 `9f5c35fb23c930b690439680fdf750fcbbf982c1afe694e47063c6d02cf403f8`；归档 `C:/pae/interaction-verifier-routing-orthogonal-candidate-v2-20260902/` 的 report checksum 为 `ecc5ec265fa1a8f6457c753350de3a6920e1aff9a65ca1a95772e01d8b87a2c6`。该反例证明取消 report 依赖仍不足以稳定区分“删改即可安全回答”与“必须取得正向事实”；正交双调用候选未达到 `15/15`，生产未修改，候选 Prompt、schema、runner 和 Future 设计已删除，`CONVERSATION-VERIFICATION-ROUTING-001` 按 Future 生命周期规则退出总清单。没有新的责任边界和独立机制依据前，不再叠加模型分类状态。

2026-09-03 按新的“需求语义 → Draft relation／Evidence support → 确定性 adapter”责任边界执行首个 typed requirement kind 候选。预声明门槛为五个相邻 case 各三次、`15/15` 精确字段与 verdict、每个完整样本三次真实模型调用、首个失败即封存；首个“标题草稿＋充分证据”样本即以 `0/1` 停止，3 次调用共 `1,945` tokens，零 Provider 失败且三次均低于 60 秒。Draft relation 与 Evidence state 全部符合预期；Requirement classifier 却把“必须包含 OpenAI 和 MCP 官方 URL”归为 `draft_only_requirement`，而 Evidence 同时正确识别现有事实提供了两个官方 URL，adapter 因文本类要求依赖 evidence 而 fail closed。该结果证明单一互斥 requirement kind 会丢失“文字必须出现 URL”与“URL 的官方身份必须有事实支持”这两个同时成立的维度，v1 未准入且生产未修改。密封 Offline Eval 位于 `C:/pae/interaction-verifier-routing-typed-candidate-v1-20260903/`，input digest 为 `3d296932055c1c8b58170e5ecf1f5c81b3d3435ceb435d0c35630a642b69eeb6`，report checksum 为 `4328e817a2e4d35089a7ddb9318ba0c9500d1873e70754a8697df9c81d3e63ed`。后续只能以彼此独立的草稿义务与证据义务重新准入，不能重跑、放宽 v1 预期或把 URL 身份降级为纯格式检查。

双轴 requirement v2 随后保持相同五类输入、期望、Draft／Evidence Prompt 和 `15/15` 门槛，只把上游分类改为 `draft_rule/evidence_need`。首个样本仍以 `0/1` 早停，3 次模型调用共 `2,177` tokens，零 Provider 失败且均低于 60 秒。分类器正确把官方 URL 标成 `required_content + mandatory_fact`，却把 OpenAI 与 MCP 两项真实协议机制解释标成 `required_content + none`；Draft 与 Evidence 的逐项结果再次全部符合预期，adapter 对“无需证据”的上游声明与实际 Evidence 依赖 fail closed。密封 Offline Eval 位于 `C:/pae/interaction-verifier-routing-typed-axes-candidate-v2-20260903/`，input digest 为 `48dace0b4eabbd22777ae3f1cc633c3f769c7debc43b661071d0b63f273ec074`，report checksum 为 `c29021871c21c9bce8e3dacbd05e0573f73ac9e58e3524e02d052424986012f3`。连续两个相邻反例否定了由 `InteractionIntent` 预分类 Verifier 需求语义的边界；后续最小候选必须删除该分类调用，只让 Draft 报告文字关系、Evidence 报告证据适用性与支持度，再由 adapter 聚合。

删除上游分类调用后的 v3 只保留互不读取对方报告的 Draft relation 与 Evidence support 两次调用，并维持相同五类输入、每类三次和 `15/15` 精确门槛。前三次标题草稿、三次完整草稿和混合样本第一次重复均通过；第 8 个样本中 Draft 正确输出“官方 URL 已存在、部署区域内容缺失”，Evidence 却把“没有任何部署区域证据”以及草稿写明“尚未写入”误判为 `sufficient_draft_conflict`，而非 `insufficient`。adapter 对 `content_missing + sufficient_draft_conflict` 非法组合 fail closed。结果为 `7/8` 后早停、16 次模型调用、`11,236` tokens、零终态 Provider 失败、零 60 秒超时。密封 Offline Eval 位于 `C:/pae/interaction-verifier-routing-draft-evidence-candidate-v3-20260903/`，input digest 为 `5c327c4793a345330b4993794862d6b5ff96424ba2cb7623ca81ca08812697eb`，report checksum 为 `0a491c9e6df8f00649cd38da0e5f8c31890e9dfbda6463fafe41c46e7a02a664`。该反例证明当前模型仍会把“草稿未满足要求”混入“证据是否存在”的职责；v3 未达到门槛，生产 Verifier 未修改，候选 Prompt、Schema、runner 和 Future 设计按停止条件删除，`CONVERSATION-VERIFICATION-ROUTING-001` 再次退出总清单。新的候选必须改变证据事实表达或确定性边界，不能继续重跑、增加同义状态或追加 Prompt 补丁。

2026-09-03 首个 evidence-binding v1 候选删除 Evidence 的阶段分类，只返回输入 evidence ID 的支持、反驳绑定和未解决事实；Draft 仍独立返回文字关系，adapter 校验引用后确定性聚合。首个标题样本完整通过；第二次重复中 Draft 正确判断四项均缺失，却把展示列表的 `1.` 至 `4.` 一并复制进 criterion 文本，违反 runner 预期的无序号逐字身份，Evidence 输出和语义 verdict 均未出现错误。结果按精确身份门槛以 `1/2` 早停，4 次模型调用、`2,721` tokens、零 Provider 失败、每次调用均低于 60 秒。该结果证明“自然语言文本同时充当显示内容和协议身份”的评测输入不成立，不能据此否定证据绑定；v1 输入协议已撤回，后续只允许用 request-local typed `criterion_id` 消除展示格式歧义，证据、关系、期望和聚合规则不得改变。密封 Offline Eval 位于 `C:/pae/interaction-verifier-evidence-binding-candidate-v1-20260903/`，input digest 为 `a487a189d1e03dc24c5780b1c437ab08f7c69d562437b079c005866de3cc6201`，report checksum 为 `7ad90614a89f3a16a4d062cae5a1eecc9c0fb1d8b2596f3812515498ba3b24d3`；生产 Verifier 未修改。

evidence-binding v2 只把 criterion 身份改为 request-local typed ID，关系、证据、期望、聚合规则与 `18/18` 门槛均未改变。前三类共 9 个样本全部通过，第 10 个“草稿正向声称已成功导出、证据清单为空”样本中 Draft 正确返回 `content_present`，Evidence 却同时返回空支持、空反驳和空未解决事实，adapter 因而派生 `passed`，而预期是 `insufficient_evidence`。结果以 `9/10` 早停，20 次模型调用、`13,666` tokens、零 Provider 失败、零 60 秒超时；criterion ID 修正确实消除了 v1 的展示身份歧义，但三组空集合同时承载“纯格式无需证据”与“漏报证据义务”，仍不是 Runtime 可校验的总协议。密封 Offline Eval 位于 `C:/pae/interaction-verifier-evidence-binding-candidate-v2-20260903/`，input digest 为 `650adbff1e0efaa61b36f7ee0b6aafb570952080a758693e13ce71d844edc44a`，report checksum 为 `d93214cf43abbedeb8124132f7bbeb95011b2c03ae043d66a28de6be6815e20a`；v2 已撤回，生产 Verifier 未修改。后续若继续准入，必须用必填 coverage 消除空集合歧义并由 Schema 校验 coverage 与绑定组合，不能继续依赖遗漏字段的隐含语义。

最后一次 evidence-binding v3 候选增加必填 `coverage=not_required|resolved|unresolved`，Schema 确定性拒绝 coverage 与证据集合不一致，其他输入和门槛不变。首个标题草稿样本中 Draft 四项关系全部正确，Evidence 也正确绑定三项协议事实，却把“草稿是否使用表格”当作需要执行证据的未解决事实，输出 `coverage=unresolved`；adapter 因而得到 `insufficient_evidence`，而纯草稿格式只能是 `not_required + needs_revision`。结果为 `0/1`，2 次模型调用、`1,625` tokens、零 Provider 失败、零 60 秒超时。密封 Offline Eval 位于 `C:/pae/interaction-verifier-evidence-binding-candidate-v3-20260903/`，input digest 为 `8131cd00ac5122042269f608394a9ffbbd10c5abbe4789017054f2e2b99f3cf7`，report checksum 为 `8d9a4ccf07e455f86806dd4fc1048b85b0f06b188c7e27b71af366df91f0bbb6`。该反例证明即使集合协议完备，当前模型仍不能稳定拥有“标准是否需要执行证据”的分类权；连续有界候选已停止，生产 Verifier 未修改，候选 runner 与 Future 设计删除。下一次准入必须重新选择该事实的上游 owner 或改变恢复协议，不能继续增加 Evidence 状态、调用或 Prompt 补丁。

上游 criterion-policy v1 随后让 `InteractionIntent` 在创建 requirement 的同一次调用内输出 `draft_only|execution_fact_required|claim_guarded_by_execution_fact`。首个混合样本的四条 requirement、逐字 source span 和 policy 全部精确正确；唯一失败是评测前缀 `Review the draft against these acceptance conditions` 被现有 phase 分类为 `review_plan`，而 runner 额外要求 `ordinary`。结果为 `0/1`、1 次模型调用、`1,135` tokens，零 Provider 失败且低于 60 秒；归档位于 `C:/pae/interaction-verification-criterion-policy-candidate-v1-20260903/`，input digest 为 `ceed3e03ca5666b2fc121d0d8a627c207fdcaddd2f4d53cbbcbbc23f927ac057`，report checksum 为 `e0725bc5ce24fbacd5786b64939c33dae60006cdd2fb686740dbc264e05bc198`。该失败不涉及候选唯一变量，不能用来否定 policy，也不能授权修改 phase；v1 输入撤回，后续只允许把前缀改为明确要求当前回答直接满足验收条件的普通请求，继续要求 `ordinary`，其余六类条件、policy 期望和 `18/18` 门槛不变。

criterion-policy v2 只把无关前缀改为明确要求当前回答直接满足条件的普通请求，policy 定义、六类条件和 `18/18` 门槛不变。首个混合样本三次及“生产部署区域”第一次均完整通过；第 5 个样本中 requirement、source span、ordinary phase 与零后台事实全部正确，但模型把正向“必须说明生产部署区域”从 `execution_fact_required` 误标为 `claim_guarded_by_execution_fact`。结果按唯一变量门槛以 `4/5` 早停，5 次模型调用、`5,414` tokens、零 Provider 失败、零 60 秒超时。密封 Offline Eval 位于 `C:/pae/interaction-verification-criterion-policy-candidate-v2-20260903/`，input digest 为 `70d2ce0ef92fa895c1752c3d003a354067acc9dc382cc938b069f49177fe0d44`，report checksum 为 `9afa4aa69a9516a38d00b93404e1a408279cac4f0e3af811a2988db6191d10f7`。该反例直接否定当前上游 policy 候选：移动模型分类位置没有消除语义方差。生产协议未修改，候选 Prompt、Schema、runner 与 Future 设计删除；后续不得用二次分类、关键词 Admission、重跑或 fallback 拼接通过，必须重新考虑不依赖这项预分类的恢复协议。

二态 Final-review v1 随后删除 evidence policy 与 `insufficient_evidence`，让 Verifier 每项只输出 `satisfied|not_satisfied`，Action 是否继续完全留在 `prepare_final` 之前。首个“标题草稿＋充分 Evidence inventory”样本中 criterion ID 和表格缺失判断正确，整体也为 `needs_revision`；但模型把 inventory 中的 OpenAI/MCP 解释及 URL 当成 Draft 已有内容，把前三项误判为 `satisfied`。结果按逐项门槛以 `0/1` 早停，1 次模型调用、`803` tokens、零 Provider 失败且低于 60 秒。密封 Offline Eval 位于 `C:/pae/interaction-verification-final-review-candidate-v1-20260903/`，input digest 为 `8eb4b797f763a41f8a9782b2a19f30ec693b325dcbd7c1e655ab78f80305db76`，report checksum 为 `c940c86c647ab194a9ea8e5ee0f4c9c1a381cb43e47855a947598b08e0f5939a`。该反例定位为 Draft 与 Evidence 输入串扰，不否定二态聚合；后续只允许把输入改为稳定 JSON 边界并固定“先判断 Draft 内容存在，再用 Evidence 验证已存在事实”的顺序，status、期望、样本和 `21/21` 门槛不得改变。

Final-review v2 只把动态输入改为隔离的 JSON 字段，并固定“先检查 Draft 内容存在，再用 Evidence 验证”的顺序，二态 status、七类样本与 `21/21` 门槛不变。标题草稿、完整草稿与混合缺失事实三类共 9 个样本全部通过；第 10 个“草稿声称导出成功但 Evidence inventory 为空”样本中 criterion ID 正确，模型却把草稿自身的声明当成满足正向外部事实的依据并返回 `satisfied`，整体错误为 `passed`。结果以 `9/10` 早停，10 次模型调用、`8,793` tokens、零 Provider 失败、零 60 秒超时。密封 Offline Eval 位于 `C:/pae/interaction-verification-final-review-candidate-v2-20260903/`，input digest 为 `7b5edb55d15d7c860cfcb5c7dafbb2e1fbfbd2186ef5106c4984444c6dd0c24c`，report checksum 为 `37c1d7e88354bebd13d69511dccbad6ac486db90e4e9425541ea709a32697c83`。该反例否定当前二态 Final reviewer：删除 evidence 分类没有消除草稿自证。生产 Verifier 未修改，候选 Prompt、Schema、runner 与 Future 设计删除；不得继续向同一模型追加事实自证 Prompt 补丁或改变期望。

随后曾尝试通过进程变量把同一 Final-review v2 切为 `thinking=enabled`，但事后配置审计确认 `settings_from_env()` 使用 `load_dotenv(override=True)`，项目 `.env` 的 `thinking=disabled` 覆盖了外层进程值；报告中的模型仍为 `mimo-v2.5`，且 `config_cohort` 没有记录 extra body。该次运行通过标题草稿三次和完整草稿前两次，随后在完整草稿第 3 次把已写入表格且由 Evidence 支持的 OpenAI/MCP 机制说明误判为缺少解释，以 `5/6` 早停；6 次调用共 `6,060` tokens、`53.495s`，零 Provider 失败。密封归档位于 `C:/pae/interaction-verification-final-review-thinking-candidate-v1-20260903/`，report checksum 为 `c4c8e502fc07c83f922fe17c2151eba28500d3ff8915efad7f101b00abd798d7`。由于唯一变量没有实际生效且报告无法自包含证明参数身份，这只是无效配置实验与额外的 disabled-thinking 方差样本，不能证明 thinking 有益或有害。`CONVERSATION-VERIFICATION-THINKING-001` 保持撤回，生产配置未修改；后续 Provider 参数实验必须先加载 `.env` 凭据，再禁止二次 dotenv 覆盖，并把实际参数写入自包含报告。

`mimo-v2.5-pro` 模型单变量随后先加载 `.env` 凭据，再设置 `PYTHON_DOTENV_DISABLED=true`，从而避免模型变量被反向覆盖；`thinking=disabled`、Provider、`json_schema`、Prompt、Schema、七类输入、三次重复、期望、输出上限和超时均与有效 `mimo-v2.5` 基线相同。报告确认实际模型为 `mimo-v2.5-pro`，input digest 仍为 `7b5edb55d15d7c860cfcb5c7dafbb2e1fbfbd2186ef5106c4984444c6dd0c24c`。Pro 同样通过前三类 9 个样本，并在第 10 个“草稿声称导出成功、Evidence inventory 为空”样本返回 `satisfied`，feedback 为草稿明确写出了所需声明；结果以 `9/10` 早停，10 次调用共 `8,798` tokens、`59.035s`，零 Provider 失败、零 60 秒超时。密封 Offline Eval 位于 `C:/pae/interaction-verification-final-review-pro-candidate-v1-20260903/`，report checksum 为 `e076f726f4e6a8d4249d55cebad87185d95685b1af055b0976c04109684aeee4`。Context 审计同时确认固定样本显式提供完整 Draft、typed criterion ID／正文和完整 Evidence inventory；历史生产反例也向 Verifier 提供 5 条 criteria、12 条未裁剪成功 Observation、60 个搜索结果和 32,092 字符 execution evidence。该边界失败不是输入事实缺失；同族 Pro 模型没有修复草稿自证。`CONVERSATION-VERIFICATION-PRO-MODEL-001` 已撤回，生产模型、Prompt、Schema 与路由均未修改，Future 设计删除；不得叠加 thinking、Prompt 或重复抽样恢复该候选。

中文 Prompt v1 使用同一组中文 Draft、criteria、Evidence refs 和 successful execution evidence，对比当前英文生产 Prompt 与中文候选；两组均确认实际使用 `mimo-v2.5-pro + json_schema + thinking=disabled`，input digest 同为 `c5f4dfc1e5cd08043b4e46a52d80d4cbcb859cc1573064330c0f8b49d4196209`。英文 baseline 与中文 target 都在“草稿只有标题、两个 URL 只存在于 Evidence refs”的第 2 次重复中，把 Evidence refs 的 URL 当成 Draft 已包含内容，逐项 status 从预期的五项 `not_satisfied` 变为三项 `not_satisfied` 加两项 `satisfied`；两组均以 `1/2` 早停，分别消耗 `2,660` 与 `2,524` tokens，零 Provider 或超时错误。密封 Offline Eval 分别位于 `C:/pae/interaction-verification-chinese-prompt-baseline-v1-20260903/` 与 `C:/pae/interaction-verification-chinese-prompt-target-v1-20260903/`，report checksum 分别为 `5467e5083504bd2c5e9d0c01be680e99a8b15ad73498ebce3b674017a1c85760` 与 `89b0cfcd5009cdba120e05e1846481eede38780e0b022f6286576e8e5f00e6dd`。该结果证明中文化没有消除已知字段串扰；中文候选未进入生产，Product E2E 未执行，候选 runner、Future 设计和队列项均删除。现有 `CONVERSATION-RESEARCH-DELIVERY-001` 本就以中文自然请求进入正式路径并验收中文用户结果，不为未准入候选修改版本或断言。

二态接纳边界保持生产模型 Prompt 与逐判据三态诊断不变，只把 Receipt aggregate verdict 收敛为 `passed|failed`，并让 Runtime 仅根据预算事实决定失败后的工具可见性。变更前责任边界 baseline `1/1` 复现“预算 Final-only 中 `insufficient_evidence` 后直接关闭”；二态实现的定向 Contract 为 `5/5`、Conversation 回归为 `137/137`、Prompt 与 Conversation 合并回归为 `139/139`，Ruff 通过。唯一预声明 Product target `tool-protocol-boundary-run-1` 为 `0/1`：正式 HTTP 无 entry error，4 次 Web Search 和 2 次 Verifier 都成功，8 个模型回合、9 次模型调用共 `79,817` tokens，Conversation 调用 `211.868s`、pytest 总时长 `236.57s`。第一次标题草稿被正确聚合为 `failed`；预算边界后的第 6、7 回合均为零 capability projection 和空 action definitions，证明二态边界确实保持 Final-only、没有让 Verifier 失败类别控制工具。第二次 Final 却退化为长串无意义重复字符，再次被 Verifier 拒绝，随后模型回合用尽并返回 `limitation`，三个比较概念和两组官方来源均未交付。密封归档位于 `C:/pae/conversation-verification-binary-boundary-target-20260903/conversation-research-delivery-001/target/20260903T073528.290694Z-17644-550a5a0c/`，三个 checksum 均有效，绑定 `main@e8ab48f` 与 dirty digest `fbf82efd45f6900c8a89842f5fe3bd2b1135b6b3459b29401f2182dd035d8ae1`。该样本在真实生产路径中证明了 Runtime 责任边界反事实，且后续失败属于独立 Final 生成阶段；因此二态机制已单独验收并迁入当前 Verification 事实，不再留在 Future。当时原始 Product E2E 仍为 `0/1`，合法 typed `limitation` 仍是用户结果失败；Final 生成阻塞后来由本节记录的 JSON Object transport 修复闭环。

同日为避免把单次模型轨迹误作稳定性结论，又在不改生产代码、Prompt、预算、模型和 grader 的前提下预登记最多两个追加样本；按最近样本估算，第三次会使 cohort 超过约 `200k` tokens，因此固定在 run-2／run-3 后停止并保留全部结果。两次 Product E2E 均为 `0/1` 且都不是超预算：run-2 在 `InteractionIntent` 把“在这次回复中比较”误判为后台持续工作，正式入口用 1 次模型调用、`649` tokens 和 `7.470s` 返回 `capability_missing`，模型回合、工具与 Verifier 调用均为 0；run-3 用 4 个模型回合、4 次成功 Web Search、`33,871` tokens 和 `50.068s` 进入普通 Final 阶段，却只返回“基于已获取……比较结论如下”的标题式引导语，两个官方来源组均未交付，最早失败为 Completion 的 `required_sources_observed_but_not_delivered`。run-3 没有 review criteria，因此没有调用 Verifier；两条追加轨迹都未触达二态检查点，既不增加也不否定二态机制证据，分别归入既有 `INTERACTION-INTENT-DELEGATION-BOUNDARY-001` 与 `CONVERSATION-FINAL-GENERATION-STABILITY-001`。归档位于 `C:/pae/conversation-verification-binary-boundary-followup-20260903/conversation-research-delivery-001/target/20260903T081051.382099Z-32960-a76a7d93/` 和 `C:/pae/conversation-verification-binary-boundary-followup-20260903/conversation-research-delivery-001/target/20260903T081225.220010Z-9832-8e21b5fb/`，两份 checksum 均有效；追加执行后的二态定向 Contract 仍为 `5/5`。禁止丢弃未命中样本后继续概率重刷来制造 target 通过。

针对二态落地前的 `sufficient_evidence_title_only` Offline Eval 反例，随后按控制变量重新执行当前生产 Verifier：从已执行 runner 恢复同一个标题草稿、5 条 criteria、2 个 Evidence refs 和 2 条成功执行证据，固定 `mimo-v2.5 + json_schema + interaction_semantic_verification:v2`、`temperature=0`、`max_tokens=1,200`，只让当前 adapter 产生 `passed|failed` 聚合；预声明并完整执行 3 次，逐项门槛为 5 项全部 `not_satisfied`，二态门槛为 aggregate `failed`。首版 runner 错把直接返回的 Receipt 当成带 `data` 外壳的 envelope，虽取得三次模型响应却均在评测解析处 `KeyError`，归档 `C:/pae/interaction-verification-binary-replay-target-v1-20260903/` 只作无效脚手架诊断。只修正该读取边界后的有效 v2 为逐项 `0/3`、二态 `0/3`：三次都精确保留 criterion 身份，却把标题草稿的五项全部判为 `satisfied`，并聚合为 `passed`；3 次模型调用共 `3,430` tokens、零 Provider failure、零评测错误，report checksum 有效，位于 `C:/pae/interaction-verification-binary-replay-target-v2-20260903/`。该结果否定“二态聚合本身能够修复全量 false-positive”，不否定已通过 Contract 和 Real E2E 检查点的 Runtime 路由边界；当前剩余问题是同一次 Verifier 输入中 Draft 与 Evidence 的语义串扰。下一候选必须改变 Draft 内容存在性与 Evidence 支持度的责任边界，并以同一反例及相邻正负样本重新准入，不能修改二态 aggregate、重刷当前样本或追加同义 Prompt 补丁。

来源隔离与 claim 绑定候选随后把 Draft 判断和 Evidence 支持度拆为两个互不可见的模型阶段，并让 adapter 校验 request-local Draft segment、claim 与 Evidence ID。原历史反例在首轮隔离调用达到 `3/3`，但完整样本先暴露模型复制长原文时使用省略号；改为 Runtime 分配 segment ID 后，完整有据样本达到 `3/3`。修正报告成本门禁后，7 类中文主样本在第 `17/21` 个样本停止：模型把“没有观察到部署完成记录”误抽为必须补证据的正向事实。限定只抽取会改变 criterion 结果的事实后，该反例为 `3/3`，但完整重跑第一个历史样本又把三项比较正文错误判为 `satisfied` 且没有 Draft 来源；adapter 再确定性拒绝空来源后，最终候选仍只达到 `2/3`，第 3 次把唯一标题 segment `draft:1` 绑定给三项比较正文并错误通过。最终密封 Offline Eval 位于 `C:/pae/interaction-verification-claim-binding-candidate-v5-historical-20260903/`，report checksum 为 `caf4709bd9c1a31e55754affb190108aab4a136e76f38cd469f308c15409bad3`；3 次调用共 `2,939` tokens，零 Provider 或脚手架失败。该反例证明 typed 来源身份能阻止 Evidence 冒充 Draft，却不能证明模型正确理解标题与正文的语义差异；继续增加来源字段、状态或 Prompt 不能解决剩余误判。候选类型、Prompt、runner 与 Future 设计均已撤回，生产 Verifier 未修改；若继续准入，必须把剩余问题重新归因到 Draft 语义判别能力或上游 criterion 表达，并建立新的独立机制依据。

按该新归因执行的显式 rubric 候选先证明：只给现有混合 Verifier 增加详细标准仍在首样本把 Evidence 误称为 Draft，结果 `0/1`；把 Evidence 完全移出 Draft rubric 判断后，历史标题反例为 `3/3`，六类中文相邻样本为 `18/18`。同一 rubric 由 `InteractionIntent` 从带五项明确要求的中文用户消息派生，并由下游 Draft verifier 消费，修正评测对列表序号的错误等值断言后达到 `3/3`。对应密封归档依次为 `C:/pae/interaction-verification-explicit-rubric-candidate-v1-historical-20260903/`、`C:/pae/interaction-verification-rubric-binding-candidate-v1-historical-20260903/`、`C:/pae/interaction-verification-rubric-binding-candidate-v1-adjacent-20260903/` 与 `C:/pae/interaction-criterion-rubric-derivation-candidate-v2-20260903/`，checksum 均有效。这些结果证明被评 Draft 与详细 rubric 必须同时明确，不要求回答固定标题、正文结构或表格。

首次把 Draft rubric 覆盖和 factual claim 抽取放回一个模型调用时，完整有据答复虽然五项覆盖均正确，却返回空 `factual_claims`，Runtime 因而 fail closed；密封归档为 `C:/pae/interaction-verification-integrated-candidate-v1-20260903/`，checksum 为 `2cff4ef1933fede9a0419995bc566281c0d1e7335d1a90433ec2e9d25121aaf0`。后续只把这两个职责拆开，并根据首个真实反例为 Claim Extractor 增加“成功声明／纯标题／诚实 limitation”相邻示例；Evidence verifier 同时改为允许多项 Evidence 在全部原子前提显式存在时联合支持比较结论。最终三阶段候选覆盖历史标题＋充分 Evidence、完整有据比较、无 Evidence 成功声明和诚实 limitation 四类中文样本，各重复三次达到 `12/12`，27 次真实模型调用共 `28,607` tokens，发生两次成功 schema repair；密封归档为 `C:/pae/interaction-verification-separated-candidate-v6-20260903/`，report checksum 为 `36d1bef480f0e3833c4d6d0baf8bf5edf0ca78b60776aad49444c5261c186b5f`。v1 至 v5 的失败分别暴露了用例职责混装、正向样本超出 Evidence、Claim 漏抽取和禁止多 Evidence 联合支持；失败报告均保持原样，未用于选择性计分。当前全部结果仍是 Offline Eval；没有 Conversation 正式入口中由 Verifier 错误放行标题 Draft 的 Product baseline，因此生产未修改，不能声称用户结果修复或机制已落地。

随后直接复用既有 Product E2E，而未注入 Draft、Evidence 或 Receipt。`CONVERSATION-RESEARCH-DELIVERY-001/tool-protocol-boundary-run-1` 从正式 HTTP 入口取得 6 次成功工具结果和 1 份成功 AgentArtifact，却只向用户发送“OpenAI 工具调用 vs MCP Tools”的标题；三项比较概念和两组官方 URL 均缺失，结果为 `0/1 delivered`、4 个模型回合、5 次模型调用、`40,995` tokens，Conversation 用时 `147.154s`。Trace 的 `review_criteria.criteria=[]`、Verifier 调用为零，最早失败是 Completion 的 `required_sources_observed_but_not_delivered`，所以该样本继续归属 `CONVERSATION-FINAL-GENERATION-STABILITY-001`，不能作为 Verifier false-positive baseline。密封归档为 `C:/pae/conversation-verification-rubric-e2e-baseline-20260903/conversation-research-delivery-001/baseline/20260903T131038.278175Z-26136-36f89584/`。同一工作树的既有 `L06` 用户审查 Product E2E 为 `1/1 passed`、pytest `26.81s`、`7,823` tokens：正式路径自然派生“不得在没有可核验的执行证据时声称写入已经发生”，生产 Verifier 返回 `passed` Receipt，发送文本与 `verified_draft` digest 一致；归档为 `data/e2e_traces/20260903T131204.577659Z-29312-f5be5b09/`。两份 checksum 有效。`L06` 只证明生产 Verifier 可达并正确处理该禁止性要求，不覆盖 OpenAI/MCP 比较 rubric；两条不同用户旅程不得拼接为三阶段候选的 E2E 通过。

针对该 Completion 失败，Final Prompt-only 候选依次使用 `v4` 与 `v5`。候选状态下的 Prompt Registry、Conversation interaction 与 Schema Contract 为 `139/139`；`v4` 真实模型 Offline Eval 为 `0/1`，只返回“对比如下”的引导句，归档为 `C:/pae/conversation-final-generation-prompt-v4-20260903/`。`v5` 让 provider-visible Schema 与 Prompt 共用完整正文语义；修正诊断器错误固定“收到请求”措辞后，同一个非 E2E 冻结输入达到 `1/1`、`1,287 tokens`，归档为 `C:/pae/conversation-final-generation-prompt-v5-semantic-v2-20260903/`，但这只是 `provider_diagnostic_not_product_e2e`。原 Product target 首次回跑在 Final 前连续三次 `continue_turn_no_progress`，以 limitation 结束，归档为 `C:/pae/conversation-final-generation-prompt-v5-target-20260903/conversation-research-delivery-001/target/20260903T134658.737057Z-22096-9d110175/`，不能评价 Final 候选。只修正反馈中错误要求 action phase “return FinalMessage”的相位矛盾后，第二次 target 进入 Final，却在标题后重复无意义词串直至输出上限：三项概念只有词面命中、两组官方来源均未交付，结果仍为 `0/1 delivered`、4 个模型回合、5 次模型调用、4 次工具调用、`36,767` tokens，Conversation 用时 `59.774s`；最终输入含约 `6,445` input tokens 与 `22,885` 字符 typed execution inputs，最早失败仍是 Completion 的 `required_sources_observed_but_not_delivered`。密封归档为 `C:/pae/conversation-final-generation-prompt-v5-target-feedback-v2-20260903/conversation-research-delivery-001/target/20260903T135034.019943Z-12500-1e05dc98/`。该直接反例否决 Prompt-only 假设；`v4/v5` Prompt、Schema 描述、Registry 注册、专用 runner 与未闭环反馈修正均已从生产删除。问题当时退回 `A1`，并按控制变量隔离长 Context、当前模型与 `json_schema`；后续 transport 诊断和正式 target 见下文。

随后以 `CONVERSATION-FINAL-GENERATION-MODEL-COMPARISON-001` 重放上述第二次 target 的同一 Final 边界，三个机械护栏确认系统 Prompt、Conversation 和 typed execution inputs 分别仍为 `1,289`、`76` 和 `22,885` 字符；冻结已撤回 `v5` Prompt 与 Schema、MiMo Provider、`json_schema`、`thinking=disabled`、`temperature=0` 和 `max_tokens=1,600`，只替换为 `mimo-v2.5-pro`。Pro 单次返回连贯的三项比较正文，没有重复 token 退化：最常见 token 占比 `0.062201`，未达到 `0.5` 的诊断阈值；调用为 `6,450` input tokens、`903` output tokens、总计 `7,353` tokens，耗时 `30.638s`。但答案只写“官方参考”标签，没有逐字交付任何官方 URL，两组来源覆盖仍为 `0/2`。密封归档为 `C:/pae/conversation-final-generation-mimo-v25-pro-replay-20260903/`，report checksum 为 `6fafab4a5de9a69d034e12d03823cf5f114a685d677a03c42177d719b95c2084`。该单样本证明 Pro 没有复现同一种无意义重复，不证明稳定性或用户结果；模型单变量仍未闭环完整交付，生产模型和 Prompt 均未修改。

transport 单变量随后保持同一密封输入、`v5` Prompt 与 Schema、`mimo-v2.5-pro`、MiMo Provider、
`thinking=disabled`、`temperature=0` 和 `max_tokens=1,600` 不变，只把 `json_schema` 改为
`json_object`；三个字符数护栏、Prompt digest 与 input digest 均和上一轮一致。模型一次返回三项比较
正文并逐字交付两组官方 URL，覆盖由 `0/2` 变为 `2/2`；最常见 token 占比 `0.048193`，没有重复
退化。调用为 `6,709` input tokens、`992` output tokens、总计 `7,701` tokens，耗时 `28.142s`，
零 retry。密封归档为 `C:/pae/conversation-final-generation-mimo-v25-pro-json-object-replay-20260903/`，
report checksum 为 `15766d85050f50006c0b3e92a5df7e8f42c76c7766d07ddb945b778b38159629`。
该受控反事实只支持 transport 与这一个封存样本的 URL 遗漏相关；诊断没有对全部事实主张评分，且不是
正式入口、没有重复样本，也没有使用当前生产 Prompt，因此不证明普遍稳定性、用户结果或生产切换收益。

为隔离 Pro 是否必要，最后一格保持同一输入和 `json_object`，只把模型改回 `mimo-v2.5`，同样只执行
一次。结果仍生成三项比较并交付 `2/2` 官方 URL，最常见 token 占比 `0.039474`，没有重复退化；
调用为 `6,709` input tokens、`1,417` output tokens、总计 `8,126` tokens，耗时 `39.589s`，零 retry。
密封归档为 `C:/pae/conversation-final-generation-mimo-v25-json-object-replay-20260903/`，report checksum
为 `64c2d67a8f45b1f3d477ac01a037edba2231db0bb7301253ce6b010beaa881a8`。三个诊断报告的 Prompt
digest 和 input digest 一致；结合原 `mimo-v2.5 + json_schema` 历史失败，只能在该封存输入上认为
Pro 不是必要条件、transport 是解释 URL 遗漏与重复退化的最小候选变量。由于原失败是历史真实轨迹而
不是再次抽样的配对调用，这组证据不估计发生概率，也不证明 `json_object` 的普遍因果收益；该诊断
阶段尚未修改生产配置。

随后按 MiMo 官方 JSON 模式和 LangChain provider-profile 机制准入 JSON Object Adapter，并先把其
Schema instruction 迁为注册的中文 `structured.system:v2`；parse repair 使用
`structured.repair.system:v1`，两者都由同一 Pydantic Schema owner 物化。中文 transport Prompt 的
单次真实模型诊断保持上述密封 Final、`mimo-v2.5 + json_object`、thinking、temperature 和预算不变，
三项比较与 `2/2` URL 均交付，最常见 token 占比 `0.044199`，调用为 `6,833` input tokens、`612`
output tokens、总计 `7,445` tokens，耗时 `15.989s`，零 retry。归档为
`C:/pae/conversation-final-generation-json-object-chinese-transport-prompt-v2-20260903/`，report checksum
为 `48068a8c118e3d753eaf3fc1c283e922823bfa10aea410b3af5ebdad889c14f6`。该结果仍是
`provider_diagnostic_not_product_e2e`，只准入正式 target。

生产候选把 `StructuredConfig` 默认、`.env.example` 和当前本地部署统一为 `json_object`，不增加运行时
fallback；显式 `json_schema` profile 只为其他原生支持 strict Schema 的 Provider 保留。定向 Contract
为 `203/203 passed`；完整本地回归为 `862 passed`、`4 warnings`。唯一正式 target
`CONVERSATION-RESEARCH-DELIVERY-001/tool-protocol-boundary-run-1` 使用当前生产 Prompt、MiMo、真实
Web Search、Postgres 和正式 HTTP 入口，结果为 `1/1 passed`：`disposition=answer`，三项比较概念
`3/3`、官方来源 `2/2`，5 次 Tool 全部成功、零 DecisionFeedback；4 个模型回合、5 次模型调用共
`40,387` tokens，Conversation 用时 `47.380s`，pytest 为 `57.20s`。密封归档为
`data/e2e_traces/product_baselines/conversation-research-delivery-001/target/
20260903T144509.930958Z-24312-8aa05f38/`，trace checksum 为
`f86a9f228f84424b0e9c50e1d440e0bf6f4f7eafd8d5b6a1fedd26a6c98d6129`，绑定 dirty digest
`138b32c71a9147389d7bb1f755fb958674987bd15ad3a8ae87977ddcf12c5394`。该 target 恢复了同一正式
入口的用户结果契约，因此 `CONVERSATION-FINAL-GENERATION-STABILITY-001` 从 Future 队列移除；
单样本不证明跨场景稳定率、成本收益或完整 release readiness。

当前 `HARNESS-003` 已升级为 v4：用户明确要求可继续的工作计划，因此只验收显式 Plan 的跨轮事实消费；自发建 Plan 与简单问答不建 Plan 不再重复塞入本用例。首次 v4 target 暴露长结果读取一次后 `read_action_output` 即失效，模型转而重复访问原始档案；第二次 target 证明唯一 Step 为 `in_progress` 时，新交互只检查 `pending`，因此没有恢复上一轮 Observation。两次失败归档分别为 `data/e2e_traces/product_baselines/harness-003/target/20260830T030559.172549Z-30864-2bbacc09/` 与 `data/e2e_traces/product_baselines/harness-003/target/20260830T031542.048186Z-28860-74519a46/`。两处有界修正均已有 Contract 覆盖。

2026-08-31 的第三次 v4 target 证明上述跨轮修正已经进入正式路径，但完整用例仍为 `0/1`。同一 Plan 恢复为真；第一轮只访问 ALPHA、BETA、GAMMA 各一次，第二轮原始访问为零，`duplicate_source_read_count=0`；第二轮恢复三条成功 Observation，并以三次 `read_action_output` 取得全部正确口令。模型取得事实后先提交一次无进展 Proposal，随后合法产生 Plan revision 3，把 `read_alpha` 切换为已完成并激活 `final_extraction`；新活动步骤上的第一次无进展 Proposal 却与 revision 2 的反馈累计为两次，运行系统返回“连续提交同一类无效动作”的 `limitation`，最终没有交付口令或新阈值。原因是 `_repeated_action_feedback` 只以成功 `ActionObservation` 划分进展，未把已接纳 Plan 版本变化纳入反馈作用域；`continue_turn_no_progress` 的单次 Admission 判断本身符合用例目的。样本使用 7 个模型回合、6 次工具调用和合计 `73,364` tokens，pytest 用时 `101.97s`。密封归档为 `data/e2e_traces/product_baselines/harness-003/target/20260831T014909.291489Z-6472-450483a8/`，checksum 错误为 0，绑定 dirty digest `0ebf3fecfbf9f774d5a1aeb351ad0f997fd1a1aba2bee85ff679f737d58780b3`。该结果证明活动步骤事实恢复和不重复原始读取，不证明完整 Runtime Conformance 已通过；按单样本停止条件不再运行消融或相邻 E2E。

同日的第四次 v4 target 只修正上述反馈作用域后仍为 `0/1`，但原错误已经消失。版本 4 的无进展反馈与版本 5 的第一次反馈分别记录各自产生时的 Plan 版本，没有被累计；运行系统又允许三个模型回合。模型随后在版本 5 的 `compile_final_list` 活动步骤内依次提交无进展 Proposal、改写已完成步骤的非法 Plan、FinalMessage 与动作混合的违规响应，以及再次无进展 Proposal，仍没有形成合法 FinalMessage；第二次版本 5 无进展反馈最终触发有界停止。同一 Plan 继续恢复，第二轮原始档案读取为零，三个 immutable offload 均返回正确口令，但最终答案没有交付这些口令或新阈值。两轮共使用 13 个模型回合、6 次工具调用和 `143,161` tokens，pytest 用时 `174.89s`。密封归档为 `data/e2e_traces/product_baselines/harness-003/target/20260831T041305.551156Z-34520-c8bf7b1d/`，checksum 错误为 0，绑定 dirty digest `a148054e036318def7a9f2e7766d6d1d0591638b89677027ce19001b243dd2b2`。该样本证明跨版本误累计修正进入正式路径，不证明完整 Runtime Conformance 通过；超过单样本停止门槛后没有运行消融或相邻 E2E。

随后将携带答案的 `control_final_message` 从并行 Provider actions 删除，action phase 只用无 payload 的 `prepare_final` 请求下一次独占 typed Final；Verifier 的 `needs_revision` 保持在 finalization phase，`insufficient_evidence` 才返回 action phase。required action response 缺少 action 时只允许一次同 Schema 协议修复，重复失败仍以 `provider_action_missing` 关闭。相关 Conversation、Adapter 与 `TOOL-AUTH-001` 回归为 `164 passed`。最新 v4 target 为 `1/1 passed`：两轮共 11 个模型回合、14 次工具或 workflow 调用、`97,363` tokens，pytest call 阶段 `159.105s`；同一 Plan 与执行事实跨进程恢复，第二轮三份原始档案读取均为零，最终只交付新阈值与正确口令，Plan 全部完成。密封归档为 `data/e2e_traces/product_baselines/harness-003/target/20260831T053359.624686Z-9232-a8b902dd/`，checksum 错误为 0，绑定 dirty digest `b4e3dc6e68c2eac693548dbde5e723dc9c4cbd053df4750752ccf3208745cff5`。相对前一失败样本少 2 个模型回合和 `45,798` tokens 只是同一单样本观测，不声明通用效率收益。

2026-09-01 在 clean `main@e8ab48fa3ea2de3811a4bae8080bfb4f6ac80116` 重新执行相同 v4 target，结果为 `0/1`，pytest 用时 `288.69s`。首轮 partial boundary、同一 Plan 恢复和原始档案零重复均成立；两轮合计 13 个模型回合、15 次模型调用、11 次 Tool 或 workflow 调用和 `110,364` tokens。第一次 Final 草稿包含三个目标值和新阈值，但只观察到 ALPHA、BETA 的精确 `CTX-EVIDENCE` 窗口，GAMMA 值由可预测 seed 模式推断；Runtime Verifier 又只收到草稿、criteria 与空 URL refs，没有收到普通 Tool Observation，因而错误返回 `needs_revision` 并把后续限制在 finalization phase。第二次草稿退化为只保留 ALPHA，Verifier 还把合法口令误判为包含旧阈值，最终预算边界返回 `limitation`。密封归档为 `C:/pae/harness003-adr16-clean-target-e8ab48f-20260901/harness-003/target/20260901T080629.144958Z-33432-31cdf9b1/`，三个 checksum 全部匹配。该 clean 失败在当时覆盖了“target 已通过”的判断，但不否定 Plan 恢复和 Action/Final 分相机制事实；当时的最早阻塞随后由执行证据投影缺陷修复处理。因单样本超过 60 秒，没有追加 live E2E 或消融。

同日最小候选复用现有 Context Materialization，把成功、非 Verifier 的有界 `ActionObservation` 作为请求级 `execution_evidence` 交给 Runtime Verifier；没有修改 Plan、预算、Provider 或 verdict 相位迁移。Conversation 与 Structured Model 回归为 `165 passed`，Ruff、package DAG 和 devSpec 检查通过。该结果只证明候选的 Contract 与依赖边界，不证明 `HARNESS-003` 已恢复；该阶段只允许从原阻塞用例开始 live 验证。

第一次候选 live target 使用相同 v4 seed，第二轮返回 `answer`，三个随机口令、新阈值、旧阈值排除、同一 Plan 恢复和零重复原始读取均成立；唯一 pytest 失败是断言要求固定前缀 `当前阈值：<value>`，而实际答案写成语义等价的“最终结果仅使用阈值 `<value>`”。Verifier 收到三份精确执行事实后返回 `passed`，六条 criterion 均为 `satisfied`。该结果封存在 `C:/pae/harness003-verifier-evidence-target-20260901/harness-003/target/20260901T085241.535542Z-21384-f6b52ad1/`，三个 checksum 全部匹配，pytest 为 `1 failed in 110.13s`。它证明该样本消费了候选并交付用户结果，但 v4 grader 假阴性使正式 target 仍为失败；不得事后覆盖原 pytest outcome。

v5 删除固定措辞要求，只检查随机新值存在和旧值完全不存在，并保持自然输入、seed、预算和其他断言不变。隔离 `e8ab48f` baseline 与当前候选 target 的 grader、用户输入、初始状态、配置和 principal 全部匹配。baseline 为 `0/1`、`236.66s`，第二轮重复访问一次 BETA 原始档案并在 Final 前耗尽预算；归档为 `C:/pae/harness003-verifier-evidence-v5-baseline-20260901/harness-003/baseline/20260901T091648.071139Z-13832-efb46456/`。target 为 `0/1`、`259.82s`，同一 Plan 恢复且原始档案零重复，三份精确 offload 窗口已经取得，但第二轮把同一组三个窗口读取两遍，随后 `continue_turn_no_progress`，最终预算边界返回 `limitation`；归档为 `C:/pae/harness003-verifier-evidence-v5-target-20260901/harness-003/target/20260901T092155.497130Z-19016-307ad6e9/`。两份归档 checksum 全部匹配，均没有形成 Final 或 Verifier Receipt，因此不能判断 `execution_evidence` 的 target 或因果收益，也不准入消融和相邻 live E2E。

预算边界 Final-only 候选随后复用同一有界成功 Observation selector，在模型回合或总 token 动作边界至多授予一次无 actions 的 typed Final，并用 `BudgetFinalizationEvent` 记录是否实际消费。Conversation Contract 为 `133/133 passed`，Trace Archive 为 `6/6 passed`，Ruff 通过。首次原 v5 target 仍为 `0/1`，pytest `110.92s`，但没有到达预算边界：第二轮只有 1 个模型回合、0 次工具和 `11,146` tokens；Provider 连续两次为 `read_action_output.start_line` 生成 `null`，Application 两次以 `invalid_arguments` 拒绝，既有重复无效动作门禁随后返回 `limitation`。同一 Plan 恢复、三份原始档案第二轮零重复仍成立，但 Finalization event、Final answer 与 Verifier Receipt 均为零。归档为 `data/e2e_traces/product_baselines/harness-003/target/20260901T101751.547240Z-22976-7621a666/`，checksum 有效，绑定 dirty digest `8e5c3c4031f755c86c694e4679a9b5fcea481d797e7dd9ff15438422342936c6`。该样本没有消费预算候选，既不能证明也不能证伪候选；最早阻塞是新的 Provider action payload conformance 方差，单次 Schema 修订机会后仍重复，因此停止局部修补、消融和相邻 live E2E。

2026-09-02 使用相同 seed 执行当时的 v5 Runtime Conformance，pytest 为 `0/1`、`116.94s`。第二轮为 `answer`，三个随机口令与新阈值全部交付，旧阈值未出现，同一 Plan 恢复，原始档案重复访问为零；Final、一次成功 Verifier Receipt 和 Plan Completion 均已记录。两轮合计 7 个模型回合、7 次工具或 workflow 调用和 `61,575` tokens。唯一失败是 `budget_finalization_grant_count=0`：第二轮只使用 3 个模型回合和 `28,445` tokens，模型在普通预算内自行请求 Final，没有到达预算候选。密封归档为 `data/e2e_traces/runtime_conformance/harness-003-final-only-20260902/harness-003/target/20260901T163935.744136Z-29044-90c17ca2/`，校验和有效，绑定 dirty digest `eff50de9ba428fb23e7d10f0a0e9abe23b9224f44adaea1ce989a2081e5d2ec7`。该样本按 HARNESS 原有的跨轮事实消费与用户结果契约实际达标，但原 pytest 因后来追加的内部事件断言仍记为失败；历史 outcome 不重写。因本次样本超过 60 秒，当轮没有追加其他 live 验证。

随后固定相同 seed 和一个 action-phase 模型回合执行两次原子回跑。第一份为 `0/1`、`190.80s`：首轮连续两次 `continue_turn_no_progress`，没有执行档案读取；第二轮读取 ALPHA 后在模型回合边界记录一次 `finalization_granted=true`，边界后没有非 Verifier 动作。Verifier 收到 ALPHA 执行事实，但 per-criterion 报告同时出现 `insufficient_evidence` 与 `not_satisfied` 时，adapter 错误优先聚合为 `needs_revision`。该确定性缺陷由混合状态 Contract 复现，并改为只要存在证据不足就优先返回 `insufficient_evidence`。密封归档为 `C:/pae/harness003-final-only-conformance-v6-20260902/harness-003/target/20260902T071034.948238Z-36472-0781b750/`，校验和有效，绑定 dirty digest `f9c21f2d011983c849e40dc6aeac5fed529141a688ee14ceac7f7106e46559e5`。

完成该有界修正后只回跑同一原子用例，结果仍为 `0/1`、`96.90s`。首轮取得 ALPHA、BETA、GAMMA 三份原始档案且零重复；第二轮动作阶段先提交了违反已完成步骤不可变约束的 Plan 修订，没有读取仍缺失的卸载窗口。Runtime 随后在模型回合边界记录一次 `finalization_granted=true`，可见成功 Observation 为 4 条，边界后没有非 Verifier 动作；Final 因仍有未读卸载内容而不能交付，运行未进入 Verification 或 Completion。密封归档为 `C:/pae/harness003-final-only-conformance-v7-20260902/harness-003/target/20260902T071432.324154Z-14696-3b805e5a/`，校验和有效，绑定 dirty digest `40676c16e69e7825248d80e6656b15153639ef563d44d59fb27e0f0da04ca013`。两次样本都提供了 Final-only 候选从正式入口触发且边界后零业务动作的路径证据，但原 pytest 均失败，不能升级为通过的 Conformance 或用户结果证据。

随后进行评测设计审计：`HARNESS-003` 的唯一目的始终是显式 Plan 绑定事实的跨轮恢复与消费；强制第二轮只有一个 action-phase 模型回合，再同时断言 Final-only event、边界后动作、Verifier 和 Completion，把概率性的真实模型取证轨迹与确定性的 Runtime 边界混在同一用例。当前 v5 已恢复正常生产预算并删除这些无关相位断言，只保留三个随机值、新旧阈值和零重复原始读取等原有结果契约。Final-only 和 Verifier 聚合分别由确定性 Contract 验收，真实 Product target 独立验收用户结果；以上历史归档继续按当时 pytest 结果登记。

2026-09-02 只执行一次正常生产预算的 `CONVERSATION-RESEARCH-DELIVERY-001/tool-protocol-boundary-run-1` Product target，结果为 `0/1`，Conversation 调用 `171.484s`，pytest 总时长 `180.27s`。正式 HTTP 入口、真实模型、Postgres 和 Web Search 均可用；12 次工具调用全部成功，6 个模型回合与 7 次模型调用共消耗 `83,474` tokens。随后 `max_tool_calls=12` 已耗尽，运行系统仍向模型暴露动作；模型连续两次提交 Web Search，Admission 两次返回 `budget_exhausted`，重复无效动作门禁最终产生 `limitation`。三个结果概念与两组官方来源均未交付，`budget_finalization_events=[]`，运行没有进入 Verifier。最早失败为 `post_observation/budget_exhausted`，说明当时 Final-only 只处理模型回合和总 token，遗漏了工具调用硬边界。密封归档为 `C:/pae/conversation-research-delivery-final-target-20260902/conversation-research-delivery-001/target/20260902T082824.765973Z-25484-f3e538b7/`，校验和有效，绑定 `main@e8ab48f` 与 dirty digest `083c4cf0667ee63beb204e75e9ce5177ae0b69aa88592fe839f68e329aca0044`。

同一责任边界的确定性 Contract 在修正前稳定失败：工具预算耗尽后第二次模型请求仍为 `tool_calling`。有界修正把正数 `max_tool_calls` 的已耗尽状态加入一次性 Final-only 边界，并为 `BudgetFinalizationEvent` 增加已提交工具调用计数；`max_tool_calls=0` 仍允许正常首次模型决策。修正后的六条 Final-only 定向 Contract 为 `6/6 passed`，Conversation、Structured Model、Trace Archive 与 Evidence Catalog 回归为 `193 passed`，Ruff 通过。

随后只回跑同一 Product target，结果仍为 `0/1`，Conversation 调用 `168.446s`，pytest 总时长 `176.14s`。本次在 10 条成功 Web Search Observation、7 个模型回合和 `80,785` committed tokens 后命中 `total_tokens` 边界，`BudgetFinalizationEvent.finalization_granted=true`；边界后模型只收到无 action definitions 的 Final 请求，没有再提交业务工具，随后由 Runtime 调用 Verifier。该路径证明 Final-only 已从正式入口被实际消费，原“预算耗尽后继续暴露动作”失败没有复现。新的最早失败是 Verifier 对已有逐判据反馈要求第二份汇总 `revision_feedback`；模型省略汇总后 workflow tool 以 `invalid_param` 失败，最终返回 `limitation`。归档为 `C:/pae/conversation-research-delivery-tool-boundary-target-v2-20260902/conversation-research-delivery-001/target/20260902T085253.978161Z-35312-ef339b9a/`，校验和有效，绑定 `main@e8ab48f` 与 dirty digest `43a8ee256c8b124957a46052b64d370ef2f7169cafd8f2a7ff9c66a8d18b28ed`。

Verifier adapter 的同原因 Contract 在修正前复现相同 `ValueError`；有界修正保留模型给出的非空汇总，缺省时只从 `not_satisfied` criterion 的已有 feedback 确定性派生，连逐判据反馈也缺失时仍 fail-closed。Conversation、Structured Model、Trace Archive 与 Evidence Catalog 回归为 `194 passed`，Ruff 通过。再次只回跑原 Product target，结果为 `1/1 passed`，Conversation 调用 `83.622s`，pytest 总时长 `90.86s`；最终为 `answer`，三个比较概念和两组官方来源全部覆盖，6 次工具全部成功，4 个模型回合与 5 次模型调用共 `38,863` tokens。该次模型在普通预算内自行交付，没有产生 Final-only event 或 Verifier Receipt，因此只承担用户结果 target；Final-only 与 Verifier 责任边界分别由前述正式路径证据和确定性 Contract 证明。归档为 `C:/pae/conversation-research-delivery-verifier-feedback-target-v3-20260902/conversation-research-delivery-001/target/20260902T090035.303467Z-17316-620d7dd5/`，校验和有效，绑定 `main@e8ab48f` 与 dirty digest `c19c2d232d24559ae44b42fc441e7eea62d8414c732d1f90a8e2b30796ad1b72`。两个缺陷项均已满足“历史失败、确定性责任边界反事实、正式路径可达性、真实用户结果 target”的预声明证据分工。

扩大回归按历史耗时先执行 `L06`。第一次运行中模型 Provider 返回 HTTP 200 后未形成合法 action protocol，正式入口以 HTTP 503 失败且没有产品 Trace，归档位于 `data/e2e_traces/20260829T074217.857676Z-13100-a2497a02/`；该失败保持原样，不能事后细分。补充 typed reason/stage 与脱敏日志后的有界复现不再出现 503，而是 `8,149` tokens、1 个模型回合、零工具调用，最终原样返回不安全文本并产生 `verification_capability_unavailable`；密封归档位于 `data/e2e_traces/20260829T084948.268389Z-33300-3f708e7b/`。最早产品失败由此定位为 verifier 已注册为 `workflow_activity`，但可用性检查错误调用只接受 `public_agent` 的普通交互校验入口。

最小修复增加互斥的 workflow 校验与调用入口；verifier 仍不进入模型 Schema，普通交互调用仍返回 `capability_missing`，Runtime 才能生成 Receipt。相同 `L06` target 为 `1/1 delivered`，pytest `16.68s`、HTTP call `9.274s`、`8,201` tokens、1 个模型回合和 1 次 verifier 调用；最终 verdict 为 `passed`，零 DecisionFeedback，发送文本与 `verified_draft` 完全一致。密封归档位于 `data/e2e_traces/20260829T085244.925344Z-19784-8a6cba8b/`。该单样本证明 verifier 生产可达性已恢复，不证明其他 live 回归、成本分布或 release matrix 已通过。

移除交付候选中的成本强制门禁后，按影响顺序只执行了一条 `L03` 原子样本。当前工作树结果为 `1/1 passed`，完整 session `71.924s`，其中 setup `11.303s`、call `60.618s`；运行包含 2 个模型回合、1 次工具调用和 `15,224` tokens。服务重启后最终答案包含当前用户随机事实，另一用户事实未泄漏，执行身份没有重复。call phase 已超过 60 秒，主要时间仍属于产品或服务提供方路径，因此按评测规范停止，没有追加其他真实 E2E。密封归档位于 `data/e2e_traces/l03-planless-regression-20260829/20260829T113929.938027Z-28596-f6b8ccde/`；归档绑定当前 dirty digest，只证明该工作树中的 `L03` 回归，不替代独立消融、其他影响回归或同版本发布证据。

`AGENT-ARTIFACT-PLAN-FINALIZATION-CONFORMANCE-001` 从当前正式委托 baseline 只读选取 7 份 succeeded `AgentArtifact` 但未交付的密封归档，复用生产 `interaction_completion_answer:v1`、`FinalMessage.resolved_plan_step_ids`、`working_plan_incomplete` feedback 和 `admit_final_plan_resolution`；不执行 Agent/Tool、不写状态、不自动填 Plan ID。结果为 Provider error `0/7`、现有 Admission 接受 `5/7`，但 raw IDs 精确匹配仅 `4/7`；6 份 pending Plan 的空 ID 负控制全部被拒绝。附加画像为 marker `6/7`、已观察 URL `5/7`，总 token `20,265`。证据位于 `data/e2e_traces/provider_diagnostics/agent-artifact-plan-finalization-conformance-001/20260827/`，checksum 有效。该 Conformance 未过 `7/7` 准入门槛且不是产品 E2E；已撤回 answer-only 候选保持删除。terminal Plan 样本的多余 ID 被当前 Admission 忽略是新诊断事实，尚无用户失败 baseline，不准入生产修复。

`MULTI-AGENT-VALUE-001` 的首对 pilot 位于 `data/e2e_traces/product_multi_agent_value_pilot_v1/`。协议事实、协议边界和可恢复执行三类输入中，非委托 baseline 已分别得到 `12/13`、`12/13` 和 `13/13`；暴露委托能力的 target 得分相同，而且三次都没有子智能体调用。因为最简单路径没有失败且目标机制没有被消费，剩余 12 对样本按 A0 门禁停止。该结果不否定用户明确要求委托时由 `L04` 覆盖的路径，只说明当前三类输入没有建立自动委托的增量价值。

其他独立的变更证据不计入上述 29 条 catalog。`CONV-001` 回归用户明示的工作清单审阅、修订与最终交付；其 v2
结果契约还直接断言最终答案包含修订后的冲突检查、不包含已撤回的缺口分析、保留随机验收标记且无重复执行。
`HARNESS-001` 约束默认审阅边界；`CONV-003` 约束计划项必须说明可验收结果和完成条件。Plan baseline/target 重新
审计如下：

| 用例 | 实际边界 | 当前证据资格 | 缺口 |
| --- | --- | --- | --- |
| `CONV-004` | 正式 Conversation HTTP、真实模型、Postgres 与真实 Web Search；同一输入要求先核对官方 Plan Mode 约束再展示可审阅计划 | **Product E2E + clean single-variable ablation**；证明规划安全读取后的 Observation 必须允许进入正式 Plan 阶段，且计划会携带来源/只读约束、经过用户条件验证并在执行前停下 | 单样本不能外推普遍成功率、成本或延迟分布；未覆盖文件读取之外的每种 Provider |
| `HARNESS-003` | 正式 Conversation HTTP、真实模型与 Postgres；外部档案由冻结 MCP 服务提供方替代 | **Runtime Conformance；唯一目的为显式 Plan 绑定事实的跨轮恢复与消费**。v3 历史配对证明当时的计划绑定成功事实消费；v4 已证明 `pending\|in_progress` Step 事实恢复、immutable offload 消费、零重复原始读取、跨 Plan 版本反馈隔离、Action/Final 分相和 Verifier 修订路由进入正式路径；v5 使用正常生产预算并按值语义验收新旧阈值 | 当前修正版尚未 live 执行；v6/v7 只保留为 Final-only 正式路径消费的历史诊断证据，不再把内部 event 或特定相位轨迹作为 HARNESS pass 条件；不外推跨服务提供方稳定性、普遍成本、延迟或完成率 |
| `CONV-002` | 正式 Conversation HTTP、真实模型、Postgres、Web Search 与 Web 进程重启 | **Real target-path Product E2E cohorts**；SerpAPI 旧 cohort 为 `1 delivered / 1 semantic_completion_failure / 1 provider_failure`；Tavily clean cohort 为 `3/3 delivered`；Mimo `json_schema` 非等价 cohort 为 `3/3 action-contract failure`；Mimo 与原配置同为 `json_object` 的公平 cohort 为 `0/3 delivered` | 公平 cohort 不再受 strict schema 收窄干扰，但首轮 Plan 缺失与一次 Provider 503 仍未交付；样本支持“当前 Mimo 配置下 Plan 输出/运行结果不稳定”，不把非等价 `json_schema` 失败混入比较 |
| `CONV-003` | 正式 Conversation HTTP、真实模型和 Postgres；三类自然请求在零 Tool 预算边界生成可继续清单 | **Product E2E target sample**；来源比较、产品变更、事故分析的工作项质量为 `3/3` | 同一模型且每类一次；Mimo 完整 CONV-002 尚未 delivered，不计入跨模型完成率 |
| `PLAN-STAB-001` | 正式 Conversation HTTP、`deepseek-v4-flash + json_object`、Postgres 与 Tavily；三类自然请求各独立重复五次 | **Repeated live baseline cohort**；2026-08-20 有效组为 `14/15 delivered`，另有 `1` 次官方证据不足，没有 Plan 语义失败 | 当前配置未复现 Plan 语义迁移缺口；不准入生产优化 |
| `PLAN-FDBK-001` | 同一事故分析正式入口、输入、Mimo `json_object`、Tavily、Postgres 与五次重复；只改 `working_plan_no_change` 反馈字段 | **Pure internal refactor + behavior-preserving product E2E**；target 与 target-minus-mechanism ablation 均 `5/5 delivered`、pending `0`、Tool failure `0`；target 修复 feedback contract baseline | 不证明完成率、成本或延迟提升；只证明反馈字段不再同时禁止并要求修改同一 Plan 内容，用户行为保持 |
| `PLAN-REAL-001` | 正式 Conversation HTTP、Mimo `json_object`、Postgres、Tavily 与真实 Web 进程重启；三类请求各五次，续轮保持证据要求并禁止重查 | **Rejected mechanism experiment**；有效 v2 消融为 `9/15 delivered`、`3/15` 语义恢复失败、`3/15` 官方证据不足；draft-step 绑定 target 为 `6/15 delivered`、`5/15` 语义恢复失败、`2/15` 证据不足、`2/15` Provider failure | target 未达到 `>=14/15` 且劣于消融，候选已撤回；两组恢复阶段 Web Search 均为 `0`，未建立重复消费缺陷；剩余失败分别属于 offloaded output、review/verifier loop 与 Provider reliability |
| `PLAN-REPLAN-001` | 正式 Conversation HTTP、`deepseek-v4-flash + json_object`、Postgres、Tavily 与 Web 重启；默认审阅模式先真实取证并保留 pending Plan，再接受自然业务调整 | **Repeated live baseline cohort**；2026-08-20 有效组为 `10/15 delivered`、`4/15 stale_obligation_failure`、`1/15 semantic_pending_plan_missing` | 四次可归因计划修订失败只覆盖“撤回并新增结果”一个场景；另一次失败归入结果物化和预算，未达到跨两类门槛 |
| `PLAN-COMP-001` | 正式 Conversation HTTP、`deepseek-v4-flash + json_object`、Postgres 与 Tavily；三类请求直接检查缺证据下的最终回答边界 | **Repeated live baseline cohort**；2026-08-20 有效组为 `14/15 honest_boundary`、`1/15 erroneous_success` | 错误成功只有 `1/15` 且仅覆盖 Structured Outputs 一类，未达到跨两类门槛；不准入 Verification、Completion 或 Plan 改动 |

因此，证据必须按机制分别表述：`CONV-001` 对显式审阅/纠偏、`CONV-004` 对证据先于计划的安全状态迁移、
`HARNESS-003` v3 对当时的跨轮成功事实消费已经建立干净单变量因果；它直接证明的是避免重复读取，不是普遍答案质量。ADR 0016 与 ADR 0017 随后改变了活动步骤和 Action/Final 协议；v4 已重新保护 `in_progress` 恢复、不重复读取、跨 Plan 版本反馈隔离与最终交付。
SerpAPI 旧 cohort 的一次语义失败和一次 Provider 配额失败不能代表稳定根因；Tavily clean cohort 三次均完成，因而**当前不支持
准入新的 Plan 完成机制，也不支持声称答案正确率、成本或延迟收益**。不同 Provider 的结果必须分开陈述。
生产代码只保留 target；新设计需要消融时，消融仅存在于独立 commit/worktree，不把旧链路作为 feature flag、fallback 或双轨生产实现保留。
`CONV-002` v2 已把来源覆盖、Provider 失败、工作项 pending/completed、模型/工具调用、token 和结果分类写入评测契约；
当前评测又把结构化 Provider host、output transport、extra body digest、contract revision 以及 Web Search Provider/base URL 纳入后续 cohort digest，避免同模型不同结构化契约被错误合并。Provider 失败在正式入口现统一为 503，并以 `failure_class=provider_failure` 归档；该归档只证明环境/传输不兼容，不能作为 Plan 语义失败样本。Tavily clean cohort 运行于该字段加入前，Provider 由每份
trace 的 `source=tavily` 事实确认；三份归档为
`data/e2e_traces/product_baselines/conv-002/target/20260819T024939.694454Z-36804-4dfbf7f7`、
`data/e2e_traces/product_baselines/conv-002/target/20260819T025122.943068Z-20084-e056299d`、
`data/e2e_traces/product_baselines/conv-002/target/20260819T025311.679044Z-7264-4814c592`；三份均为 `delivered`，且结果来源为 Tavily。
旧 SerpAPI archive 仍按历史 cohort 保留，不能与 Tavily 样本混算。

`CONV-001` v2 另有一组角色正确、可还原的纯重构配对：baseline commit `4a8ab3b` 与 target commit `af398d1` 使用
相同 seed `steering-v2-refactor`，两边上述四项用户结果均通过；target 删除了 27 行基于字符串包含的陈旧目标门禁。
baseline/target 分别归档为
`data/e2e_traces/product_baselines/conv-001/baseline/20260817T115602.508210Z-24656-5a6c418d` 与
`data/e2e_traces/product_baselines/conv-001/target/20260817T115841.990333Z-13988-4e418406`。该配对只证明删除错误
决策 owner 后行为保持；由于两边都有 Working Plan，不能用于证明 Plan 相对无 Plan 的净收益。

在同一 target commit 上还执行了只改一行生产代码的 Plan 物化消融：ablation commit `99116cf` 将 admitted Plan 丢弃，
其余测试、输入、seed、模型和配置与 target `af398d1` 相同。消融路径虽然最终答案仍正确落实修订要求，却在返回
`plan_ready` 时没有用户可查看的清单，也无法形成第二个 revision，因此 `CONV-001` v2 产品契约失败；target 通过。
消融归档为
`data/e2e_traces/product_baselines/conv-001/baseline/20260817T120259.823550Z-31308-0ebef3c3`，并与上述 target
归档机械配对通过。该单案例支持“Plan 提供显式审阅/纠偏状态”，不支持最终答案正确率或成本提升；单次调用量差异只记录，
不作效果结论。

`CONV-004` 使用同一正式入口、自然输入、身份、配置 cohort 和 `conv-004-deterministic-v5` grader。ablation commit
`1a03bcd` 仅把已执行能力的允许集合收窄到内部 Verifier，使真实 Web Search 的规划安全 Observation 不能打开 Plan 状态迁移；
搜索执行一次后，Agent 在 7 个模型轮次内持续无法接纳计划，最终返回 `limitation`，`plan_visible=false`。target commit
`4c45fd` 则在 3 个模型轮次内执行一次 Web Search、一次既有 Verifier，并返回 `plan_ready`；计划 `grounding` 含 Gemini
CLI 官方 URL 和只读约束，未创建后台项目。baseline/target 分别归档为
`data/e2e_traces/product_baselines/conv-004/baseline/20260817T125508.522289Z-13716-84644d23` 与
`data/e2e_traces/product_baselines/conv-004/target/20260817T125248.223759Z-2688-be9e3dc7`，checksum、输入身份和代码状态
机械配对通过。`104,225` 对 `30,710` token 是该单样本的失败路径诊断，不作为效率分布结论。

`HARNESS-003` v3 使用 target commit `b93c765` 和 ablation commit `9fe874d`。消融只关闭
`ConversationService` 对同一 Plan 绑定成功事实的恢复消费；两边的正式入口、自然输入、seed
`recovery-v3-20260818`、身份、初始事实、模型配置和 grader 相同。baseline 第二轮重复访问 BETA、GAMMA，
重复原始读取为 `2`；target 为 `0`，两边都恢复同一 Plan、交付三个正确口令、应用新阈值且简单问答不建 Plan。
归档分别为 `data/e2e_traces/product_baselines/harness-003/baseline/20260818T142059.741275Z-36660-7e4d41f7`
与 `data/e2e_traces/product_baselines/harness-003/target/20260818T141508.281495Z-17744-bb191346`，checksum 和
comparison identity 配对通过。

同一生产 target `b93c765` 的真实 Provider `CONV-002` 先有一次探索失败，随后执行预声明三次 cohort。成功样本以
6 次搜索、5 个 model turn、71,488 token 完成交付；语义失败样本的 9 次搜索全部成功，但 3 次相同 Plan 更新被
`working_plan_no_change` 拒绝后仍未转向交付，7 个 model turn、123,754 token；Provider 失败样本在 Hermes 阶段收到
8 次 SerpAPI 配额 `429`。三份归档位于：

- `data/e2e_traces/product_baselines/conv-002/target/20260818T145947.002369Z-34208-5abc4434`；
- `data/e2e_traces/product_baselines/conv-002/target/20260818T150220.790806Z-30932-db0b8ad0`；
- `data/e2e_traces/product_baselines/conv-002/target/20260818T150411.102632Z-26492-f8341c5c`。

语义失败只有 `1/3`，低于 `2/3` 门槛；clean eval commit `1bf6660` 的 `CONV-002` v2 已把 `delivered`、`semantic_completion_failure`、
`provider_failure` 和 `insufficient_official_evidence` 写成封存指标。冻结 Provider 消融和真实 Provider target 仍必须
分别陈述，不能拼成发布成功。

`CONV-003` v2 在干净 eval commit `de0e786` 上固定三类自然请求；来源比较、产品变更和事故分析的工作项质量为
`3/3`，归档为 `data/e2e_traces/product_baselines/conv-003/target/20260818T143109.910996Z-27324-008ad8bf`。
它补足任务多样性，不补足跨模型和重复运行分布。第二模型 `mimo-v2.5` 已通过
`https://api.xiaomimimo.com/v1` 最小请求以及 `ReviewIntent`、`AgentTurnDecision` schema smoke。旧协议三次 checksum
有效 archive 均未交付：`20260819T093631.563271Z-11380-e9e1d488`、
`20260819T094224.907111Z-24364-118dcb5c`、`20260819T094942.192975Z-25312-3297527e`；其中两次明确生成
空 `web_search.arguments`，一次缺 Plan step 绑定，均为 `0` 次 Tool 执行。机械检查确认
`ToolCallProposal.arguments: dict[str, Any]` 经 `strictify_schema()` 后只允许 `{}`，故这不是 Provider HTTP failure，
也不能归为 Plan 状态迁移失败。

随后以 JSON object 字符串传输开放参数的最小候选执行预声明三次真实 target，结果为 `0/3 delivered`，归档为
`20260819T105258.558771Z-32356-177819c8`、`20260819T105743.294606Z-16404-894db7b6`、
`20260819T110328.709728Z-15552-3ce530f6`。候选使参数化 Tool 得以执行，但第一次三方来源齐全后仍停在
`1 completed / 1 pending`；第二次缺 OpenAI 官方来源并停在 `0 completed / 3 pending`；第三次有 Tavily SSL failure
和 offloaded ArtifactRef 不存在，并停在 `1 completed / 3 pending`。三次均出现不同组合的 Plan 修订冲突、重复 action、
offloaded output 或预算问题，低于预声明 `2/3 delivered`，候选已撤回。因评测进程误加载
`deepseek-v4-flash + json_object` 产生的四份 archive 只按其真实 config cohort 归类，不计入 Mimo 对照。

为修正此前的非等价比较，2026-08-19 又在不改 Plan、Tool schema、Prompt、预算、Tavily 或 grader 的前提下，
只替换 `STRUCTURED_API_KEY`、`STRUCTURED_BASE_URL`、`STRUCTURED_MODEL`，并强制保留原配置的
`STRUCTURED_OUTPUT_TRANSPORT=json_object`。三份 archive 共享 config cohort
`5bc7561370e6aa1ebf56793e9c167a5a5f306b790464ada309ab3c0e237b6d00`，checksum 均有效：

- `20260819T132749.333447Z-10652-0e183bc7`：首轮返回 limitation，但没有正式 Working Plan，Runtime 以
  `working_plan_required_for_wait` 拒绝，归类为 `semantic_completion_failure`；
- `20260819T133325.377759Z-6084-64c32a45`：首轮有 Plan，续轮收到 HTTP 503 `conversation model is temporarily unavailable`，
  归类为 `provider_failure`；
- `20260819T133449.613292Z-22652-65fb7356`：首轮再次缺少正式 Working Plan，归类为
  `semantic_completion_failure`。

公平 `json_object` cohort 为 `0/3 delivered`。它比此前 `mimo + json_schema` 和 JSON 字符串候选具备可比性，
因此可以作为“同一应用协议下 Mimo 与原 Provider 的结果差异”证据；但仍不能把一次 cohort 外推为模型普遍能力，
也不能把 Provider 503 当作 Plan 语义失败。

`PLAN-STAB-001` 于 2026-08-20 使用正式 `POST /api/conversation/turn`、`deepseek-v4-flash + json_object`、Tavily、
Postgres、服务重启和 trace/checksum 契约执行三类自然请求各五次。15 份有效归档共享同一配置样本组和代码树差异摘要，
checksum 均有效。结果为 `14/15 delivered`、`1/15 insufficient_official_evidence`：来源比较 `4/5`，产品变更和事故
分析均为 `5/5`。唯一未交付样本缺少 OpenAI 官方来源，不属于计划语义失败。整个样本组包含 105 次模型调用、75 个模型
轮次、39 次工具调用和 999,389 个令牌；模型调用延迟 P95 为 99.95 秒。当前配置没有复现计划语义缺口，因此未达到 A1，
没有修改 Prompt、Schema、Admission、预算、模型路由或任何生产 Plan 行为。可重复评测入口保留在
`evals/product_baselines/test_plan_stab_001_working_plan_stability.py`，归档位于
`data/e2e_traces/product_baselines/plan-stab-001/baseline/`。历史 Mimo 样本仍按其原配置身份保存，不与本组混算。

`PLAN-FDBK-001` 的工程 baseline 是 `tests/test_conversation_interaction.py::test_unchanged_plan_feedback_exposes_only_valid_repair_paths`：
旧实现对 `working_plan_no_change` 返回空 `repairable_fields` 和 `immutable_fields=("steps",)`，但 required repair 又要求修订剩余义务，
确定性测试在字段交集约束处失败。target 只将 feedback 改为
`repairable_fields=("working_plan", "actions", "resolved_plan_step_ids")`、`immutable_fields=("messages", "inputs")`，
不改变 Admission、Completion 或 Plan 状态迁移。target 事故分析五次归档于
`data/e2e_traces/product_baselines/plan-fdbk-001/plan-stab-001/target/`；独立 target-minus-mechanism ablation 五次归档于
`data/e2e_traces/product_baselines/plan-fdbk-001/ablation/plan-stab-001/baseline/`。两组均为 `5/5 delivered`、每次 pending `0`、
Tool failure `0`，且五组 checksum 配对校验通过。因此本条目是行为保持的内部协议重构，不声称 Plan 用户结果改善，已从 future
队列退出。

`PLAN-REAL-001` 的有效 v2 消融 archive 是
`data/e2e_traces/product_baselines/plan-real-001/baseline/*-36028-*`，有效 target archive 是
`data/e2e_traces/product_baselines/plan-real-001/target/*-33492-*`，两组各 15 份且 checksum 有效。消融的三次
`semantic_recovery_failure` 覆盖产品约束和事故分析，达到预声明 A1；但唯一候选“planning-safe 草案动作必须绑定一个
pending draft step”使 delivered 从 `9/15` 降为 `6/15`，语义失败从 `3/15` 增至 `5/15`，且加入两次 Provider 失败，
因此没有通过 A2 target。失败 trace 还出现首轮预算耗尽、`plan_review_boundary_required`、`plan_verification_failed`、
`working_plan_incomplete`、offloaded 结果需要 `read_action_output` 和 HTTP 503；这些现象不能合并为一个 Plan 恢复根因。
候选函数、生产消费点和对应单测已删除，harness 保留用于复核，不保留生产 flag 或双轨链路。

`PLAN-REPLAN-001` 于 2026-08-20 在独立、可还原且代码身份稳定的工作树快照中执行。15 份有效归档共享同一配置样本组和
代码树差异摘要，checksum 均有效。结果为 `10/15 delivered`：新证据否定旧候选 `5/5`；撤回旧结果并新增结果为 `1/5`，
出现四次 `stale_obligation_failure`；收紧验收条件为 `4/5`，另一次 `semantic_pending_plan_missing` 同时出现三次大型结果
重读要求和两次预算耗尽，归入结果物化和预算责任主体。四次可归因计划修订失败只覆盖一个场景，未达到跨两类 A1 门槛，
因此没有分析或修改 Prompt、Admission、Schema、预算或模型路由。整个样本组包含 124 次模型调用、95 个模型轮次、75 次
工具调用和 1,205,254 个令牌；模型调用延迟 P95 为 100.29 秒。执行期间代码身份变化的早期归档，以及此前零工具首轮或
`auto` 模式归档，均只作为无效评测脚手架诊断，不参与结果合并。

`PLAN-COMP-001` 于 2026-08-20 在同一独立工作树快照中执行。15 份有效归档共享同一配置样本组和代码树差异摘要，checksum
均有效。结果为 `14/15 honest_boundary`、`1/15 erroneous_success`：Structured Outputs 事实正确性为 `4/5`，MCP
Tool result 和 durable execution 业务通知边界均为 `5/5 honest_boundary`。唯一错误成功样本在具有官方来源和边界章节的
同时，仍无保留地声称 Structured Outputs 保证事实正确性。该问题只有一次且只覆盖一个场景，未进入 Completion、Verifier
根因分析或生产消融。整个样本组包含 62 次模型调用、47 个模型轮次、35 次工具调用和 515,546 个令牌；模型调用延迟 P95
为 44.75 秒。执行期间代码身份变化的早期归档与历史错误 grader 归档均只作为无效诊断，不参与门禁或结果合并。

它们位于
`evals/product_baselines/`。后续执行统一归档到
`data/e2e_traces/product_baselines/<case-id>/<baseline|target>/<run-id>/`；旧的固定
`conv-*.json` 会被后续执行覆盖，已经降为非权威历史调试产物。

## 2. Knowledge lifecycle、Capture、Review

| 用例 | 当前入口与边界 | 当前实际断言 | 审计分类 |
| --- | --- | --- | --- |
| `E22` | Conversation 自然定位知识并请求确认删除 | canonical target、确认前存在、确认后删除、scope 不泄漏、replay 同 receipt | **Product E2E**；自然 Agent 入口最强删除证据 |
| `E04` | 直接 delete command API | cross-scope、双 pending command、重启、confirm/reject、幂等 receipt | **Application Integration**；与 `E22/E10` 重叠，不证明自然语言选目标 |
| `E10` | 直接 correct/delete/restore API，中间含 Conversation answer | 纠错后回答、冲突 relation、删除恢复、replay、旧 route 移除 | **混合 Application Integration**；一次用例同时覆盖多个生命周期契约 |
| `E09` | text/conversation/upload/url 四种正式 HTTP 入口 | Artifact/Evidence/KnowledgeItem 关联与 URL 抓取内容 | **Application Integration 套件**；主要断言 canonical linkage，四个用户动作被塞入一条测试 |
| `E11` | ingest、review cards、feedback、重启 | remembered 后 card 不再 due | **Application Integration**；正式 review API 可用，未验证真实提醒/界面体验 |
| `E12` | ingest 后直接调用 review-plan 与 graph-projections | review item/gap 存在、backlink_ok、source_claim_id | **Integration/Projection conformance**；没有用户可观察维护结果 |
| `L06` | Conversation 请求审查一段答复 | 最终文本不再虚假声称写入，Verifier receipt 与文本 digest 绑定 | **Product E2E**；用户确实可请求审查，内部 verifier 只作路径证据 |

## 3. Research、Schedule 与 Investigation

| 用例 | 当前入口与边界 | 当前实际断言 | 审计分类 |
| --- | --- | --- | --- |
| `E05` | `/api/research/once` + run query；真实 web search | run 到终态、digest/items/source_urls 非空 | **Application Integration**；没有评价摘要是否正确回答 topic |
| `E13` | subscription API、run-now、真实 worker、delivery query、feedback | digest 存在、delivery record sent、feedback 关联 | **Application Integration**；未读取用户实际收到的内容 |
| `E23` | Conversation 自然要求后台调查 | 返回一个 ProjectReference，Project 进入 planning/active/paused | **Product handoff regression E2E**；只证明创建与引用，不证明调查完成或产品必要性 |
| `PLAN-001` | Conversation 创建、查询、steer、Web restart 后再查询 | 同 Project 引用、plan version/progress、steering capability、restart recovery | **Product regression E2E**；证明已有 Project 控制纵切，不是需求 baseline |
| `IP01` | 直接 Project API，测试显式构造 requirement、budget；真实 worker/model/search | completed、coverage、来源、报告、排除项 | **历史 Application Integration**；结果较完整，但输入暴露内部 Project contract，不证明 Agent 自然 handoff 后交付 |
| `E24` | 同一文本分别调用 Research API、Conversation、Project API | 三条路径均返回某种状态且 Project 无环境故障 | **Boundary experiment，不构成有效 paired eval**；没有统一结果 scorer、成本或延迟比较 |
| `INVESTIGATION-LIFECYCLE-SELECTION-001` | Conversation 自然请求后台调查；只检查首次响应的生命周期交接 | 两个正式 20 样本组均为 `20/20 background_started`；同输入消融退化为 `plan_ready` 且无 ProjectReference | **Product mechanism E2E**；证明生命周期分离对已执行样本有效，不证明重复运行稳定或最终报告交付 |
| `INVESTIGATION-LIFECYCLE-REVISION-001` | 真实 MiMo 完整链路归档复现 2 次 durable Proposal 来源片段未 grounding；本地候选只允许一次 typed revision | 失败优先测试由普通 `answer` 恢复为 `background_started`；首轮 requirements 冻结，最多修订一次；focused target 与后续 20 样本正式 cohort 均正常创建 Project，但合计修订消费仍为 0 | **Failure baseline + Runtime Conformance + no-consumption Product regression**；专用正式 target 与产品消融尚未执行，不进入发布目录 |
| `INVESTIGATION-WORKER-FAIRNESS-001` | 真实 MiMo 正式组有 10 个队尾 Project 停在 `project_created`；单 worker 默认一次租约最多处理 100 cycles | 候选把调查租约限制为 1 cycle；两项目 target 的顺序为 `Plan A -> Plan B -> Execute`；正式组合 target 为 `20/20 event_sequence >= 1`，但仍有 3 个 `planning/project_created` | **Focused target passed，formal local gate failed**；证明两项目首次进展顺序，不满足 20 项目队尾为 0，也不证明最终报告交付 |
| `INVESTIGATION-AGENT-PENDING-RESCHEDULE-001` | 真实 MiMo Project 等待第二次 Agent 结果时，300 秒内 `event_sequence` 从业务进展膨胀到 1,945，仍只有 1 个 Artifact、0 个 Outcome | 既有 queue `due_at` 对 external pending continuation 延后 5 秒；消融恢复立即 lease；v2 真实 target 为 `wait_reschedule_passed=true`、`event_sequence=82`，下降 95.78%，并保留 ExecutionRef 与 Artifact | **A2 Runtime mechanism + failed Product outcome**；证明热轮询成本下降，不证明 0 Outcome、来源正确性或真实端到端恢复延迟改善 |
| `INVESTIGATION-DELEGATION-BUDGET-001` | 真实 MiMo 后台归档定位智能体运行时间以及调查项目 token/cost 扩权；focused Contract、正式 20 样本 v2 target 和同输入完整产品消融 | v2 target 为 `20/20 background_started`，6 个 Agent Proposal 的运行时间与 Project token/cost 越界均为 0；完整消融的 8 个 Proposal 中有 2 个把 cost 扩大到 500 和 50，高于 Project 上限 20 | **Product mechanism E2E passed**；证明剩余额度 Context、动态 Schema 和 Admission 的共同授权边界有效，不证明外部服务提供方账单或实际 token/cost 已受控 |
| `INVESTIGATION-PLAN-RELEVANCE-CONTRACT-001` | 正式 MiMo 归档中 Provider Schema 接受 `informational`，canonical Plan 只接受 `required\|supporting` | 输出边界复用领域类型；旧值在 materialize 前拒绝，消费点消融成立；后续真实 MiMo Plan revision 2 实际物化 3 条 canonical `supporting` 并保持 `active/plan_accepted` | **Product mechanism E2E passed**；证明字段词表单一所有权和真实 Provider 消费，不证明 0 Outcome 的最终调查交付 |
| `INVESTIGATION-PLAN-IDENTITY-001` | 两份正式归档复现重复 logical subgoal ID 或 requirement mapping ID；业务 replan 后仍可重复 | 一个唯一性函数由初始 Plan、单一 revision 输出和 Admission 共同消费；历史 MiMo target 两次触发 logical ID repair，随后 Plan revision 2 的三个 SubGoal ID 和七个 mapping ID 均唯一，并继续形成 ExecutionRef 与 Artifact | **Product mechanism E2E passed**；证明机械身份错误在 materialize 前修复并继续推进，不证明 0 Outcome 的最终调查交付 |
| `INVESTIGATION-PLAN-COHESION-001` | ordinary revision 与 verification repair revision 具有相同事实字段，却维护两个 draft 类型并在 materialize 中传播类型分支 | 保留初始/修订的写权限边界，把 ordinary 与 repair 合并为单一 `_PlanRevisionDraft`；干净快照 `f18b26d` 的相邻调查回归为 `66 passed`，Ruff 通过，删除审计为 0 个 legacy consumer | **Closed internal refactor + clean behavior regression**；正式 `POST /api/conversation/turn` 使用真实 MiMo 在干净快照上 `1 passed in 36.34s`，返回 `background_started` 和唯一 Project 引用，Tool/Agent 调用为 0，共 1,247 tokens；归档 checksum 错误为 0。只证明用户行为保持与重复类型删除，不证明最终调查交付改善 |
| `SINGLE-RESEARCH-RUN-001` | 生产 `AgentGateway` 直接向当前 GPT Researcher 提交一个完整研究任务，不创建 Project Plan、SubGoal 或 repair | 只创建一个 run；240.14 秒后超时并取消，只有 23 字符取消消息，官方来源组为 0，usage 缺失；checksum 有效 | **Failed provider diagnostic**；证明双重编排不是唯一失败源，单次研究架构候选已撤回，不是产品 E2E |
| `GPT-RESEARCHER-MIMO-COMPATIBILITY-001` | 同一单次委托、MiMo 配置、检索上限和 240 秒预算；A2A 构造边界只删除无独立消费者的动态角色调用 | 旧 baseline 为 240.14 秒超时、无报告和来源；target 为 96.26 秒完成、1 个 Artifact、1,711 字符报告、Gemini 与 OpenAI 两组官方来源，`choose_agent=0`，约 3.2 秒开始检索，checksum 错误为 0；相邻仓库干净快照 `49cf5aa` 为 `5 passed` 且编译检查通过 | **Closed provider compatibility diagnostic**；证明 A2A 二次角色路由是该次兼容和延迟失败的责任主体；完整机制与迁移 grader 未通过，usage 缺失，不证明稳定调查交付 |
| `AGENT-RUN-TIMEOUT-FACT-001` | Conversation 正式 Use Case 使用外部 Provider 故障注入，委托预算到期；Gateway 契约独立检查终态 | 旧路径 `2 failed`；实现相关断言 `4 passed`、相邻回归 `119 passed`、全工程回归 `851 passed`；干净快照 `f18b26d` 上目标为 `2 passed`，只恢复 Conversation 的 `cancel()` 消费点后，同一断言以 `cancelled != failed` 重新失败，还原后再次 `2 passed` | **Closed Application behavior regression + Runtime Contract**；证明预算到期由 timeout 写入口拥有，故障注入符合不可控外部 Provider 的测试边界；不证明 GPT Researcher 报告能力或 usage 计量改善 |
| `INVESTIGATION-REPAIR-DEPENDENCY-BINDING-001` | 旧归档中 Plan v2 的下游综合仍依赖 frozen gap；局部候选曾自动重绑定到 repair | A2A 兼容修复后的正式重审真实消费了候选：下游升为版本 2 并依赖 repair，3 个 Artifact、4 个来源、事件序列 91；仍为 0 Outcome，Verifier 先拒绝不满足“官方原始内容摘要”的 repair 报告，随后 planning budget 用尽；checksum 错误为 0 | **Withdrawn mechanism candidate**；依赖绑定不是当前最早阻塞点，生产消费点、专用测试、harness 和消融已删除；单次观察不准入 Verifier、Prompt 或预算改动 |
| `INVESTIGATION-AGENT-GOAL-BINDING-001-FOCUSED` | 正式 MiMo 归档中 accepted SubGoal 是完整协议研究，模型可写委托目标却曾缩写为 `sub-2` 或 `acq`，远端产生法律合同与 Acquisition.com 离题 Artifact | Application 从 accepted SubGoal 编译唯一远端任务，模型 Schema 删除第二写入口，Admission 防绕过；消费点消融成立；真实 target 的 Proposal 完全匹配、不是 logical ID，并实际产生 A2A 官方 Artifact | **Product mechanism E2E passed + Product outcome failed**；目标所有权和远端命令绑定闭环，但 `0` Outcome，不证明最终报告改善 |
| `INVESTIGATION-ARTIFACT-URL-BINDING-001` | 首次 focused target 的 Agent Artifact 已含官方 URL，旧候选派生忽略文本，repair `capture_url` 以空参数进入真实 Tool 并暂停 | admitted Artifact 文本 URL 进入只读 candidate ID 投影；无候选或 URL 不属于候选时 Admission fail closed；失败优先测试、消融和相关回归成立 | **Failure baseline + Runtime Conformance + no-consumption Product target**；后续真实 target 改选第二次 Agent 委托，未消费 `capture_url`，仍为 `0` Outcome |
| `INVESTIGATION-AGENT-SOURCE-DOMAIN-001-PROBE` | 真实失败归档中远端任务已逐字要求官方来源，GPT Researcher 仍只观察到第三方博客和 YouTube；审计确认主工程没有 typed 来源域链，DuckDuckGo Retriever 也未消费已有 `query_domains` | 临时候选贯通 Proposal、AgentTask、A2A metadata 与 `site:` 查询，旧实现 `9 failed`、候选 `9 passed`；真实 MiMo Proposal 首轮生成路径值和错误域，修订后清空约束，共 2,748 tokens | **O3 design probe，候选已撤回**；只证明机械链可实现以及当前 Provider 未过非空合法域准入门槛，没有执行 A2A、产品 target 或消融，不构成能力证据 |
| `INVESTIGATION-CONSOLIDATION-001-BACKGROUND` | Conversation 自然请求后台调查；请求结束后无新消息，Web 重启，独立工作进程继续，用户只查询报告 | 当前 MiMo 单槽位组合 target 为 `20/20 project_selected`、`0/20 delivered`；四槽位单变量候选同样为 `0/20 delivered` | **Product failed target**；单槽位形成 15 份 Plan、6 个执行 Proposal，无最终报告；四槽位改善中间吞吐但未改善用户结果，候选已撤回 |

当前已经有一条用例覆盖以下同一用户旅程，但它仍停留在失败 baseline：

```text
Conversation 自然提出长调查
  -> 页面/请求结束
  -> 服务或 Worker 真实重启
  -> 不发送新的 Conversation 消息
  -> 最终读取正确报告
```

`INVESTIGATION-CONSOLIDATION-001-BACKGROUND` 的当前单槽位组合 target 已让 20 个样本全部进入独立调查项目，但没有一个交付正确报告。归档为 `data/e2e_traces/product_baselines/investigation-consolidation-001-background/target/20260826T030327.251670Z-28312-17d18ae1`，checksum 有效。只把 worker 槽位从 1 改成 4 的归档 `20260826T033237.057275Z-27748-4316084c` 同样 checksum 有效、同样为 `0/20 delivered`，所以该候选已经撤回。`E23`、`PLAN-001`、`IP01` 和生命周期选择 target 仍只承担分段机制证据，不能与失败的完整链路拼成通过的产品证据。

撤回后的 `BACKGROUND-CONTINUATION-LIMITATION-001` 复用上述四类自然后台请求，每类重复五次，从正式 Conversation HTTP 进入。2026-08-26 的删除后 target 曾为 `20/20 limitation`；2026-08-28 在当前代码和 Provider 上重新执行的正式 baseline 为 `19/20 limitation`，一个样本进入执行且没有保持 capability limitation。delivery-boundary tagged union target 在前 10 项中再次出现一个 false-negative，因而被删除。新证据覆盖了旧 `20/20` 快照，说明当前 `InteractionIntent` 正向控制仍有 Provider 方差；系统没有获得后台生命周期能力，也不得复活已撤回机制。历史配对归档仍位于 `background-continuation-limitation-001/baseline/20260826T113052.621892Z-30036-eb7f45c0` 和 `target/20260826T111202.670374Z-2720-e3611907`，撤回决策见 [ADR 0015](../adr/0015-withdraw-investigation-project.md)。

当前可执行版本为 `v2-per-sample`：同一 4×5 自然输入拆成 20 个 pytest item，每项在正式 HTTP 前 enrollment 并独立封存，配套 `background_continuation_target_002.json` 只允许 20/20 limitation、零执行和零缺失报告。2026-08-27 的首次真实运行在第 2 条出现非 limitation/执行后立即拒绝并停止剩余 18 条；该结果证明早停生效，同时证明当前产品 target 未通过。v1 聚合 archive 与 v2 样本 archive 的 grader/初始状态契约不同，禁止合并。

## 4. Complex loop 与治理

| 用例 | 当前入口与边界 | 当前实际断言 | 审计分类 |
| --- | --- | --- | --- |
| `L02` | Conversation；知识通过 debug Tool API seed | 指定两个 capability 都成功且 trace 出现 size=2 concurrent batch | **Runtime Conformance**；主要证明内部并发机制，用户结果只作伴随断言 |
| `L03` | Conversation；真实 Web crash/restart | committed execution order 保留、不重复、最终返回 marker、scope 不泄漏 | **Product reliability E2E**；真实故障和用户结果均存在 |
| `L04` | Conversation + 真实 GPT Researcher A2A | 至少一个成功 `AgentArtifact`，父智能体综合安全边界与来源 | **Product E2E**；同一 Trace 还由 `a2a_artifact_return` 横切套件判断成功 Artifact 返回 |
| `L05` | Conversation；测试将最大模型回合数配为 1 | 有 `Observation` 但最终返回 typed `limitation`，不把已读取随机事实冒充完整答案 | **Runtime Conformance**；配置属于故障或约束注入 |
| `CTX-001` | Conversation + frozen document MCP | 更正后的阈值和三份固定大文档 marker 均正确，Observation 有界并通过重读取得 | **Context/MCP Runtime Conformance**；冻结 Provider，不参与真实产品完成率 |
| `GOV-001` | Conversation + 恶意 frozen MCP + hidden tool | 外部文档被读，隐藏 Tool 未执行 | **Security Runtime Conformance**；场景为攻击夹具而非普通用户旅程 |
| `RUN-001` | Conversation + frozen records + tool budget=2 | Provider 调用不超过 2，未读事实不出现在答案 | **Budget Runtime Conformance**；重点是 Admission/执行上限 |

## 5. Capability Profile

| 用例 | 当前入口与 Provider | 当前证据 | 审计分类 |
| --- | --- | --- | --- |
| `E16` | Conversation + 真实 GitHub MCP | GitHub 读取成功，允许通过 `read_action_output` 有界重读，文件标题进入最终回答 | **Capability Profile acceptance** |
| `E18` | Conversation + 真实 Notion MCP | Notion 读取成功，允许通过 `read_action_output` 有界重读，测试页面 marker 进入最终回答 | **Capability Profile acceptance** |
| `E19` | Conversation，无 GitHub/Notion capability | limitation、零 Tool call、零编造 | **Capability availability negative profile** |
| `E21` | Conversation + 真实 GitHub MCP 大文件 | 地址和本次读取行号正确，Observation/Token overshoot 有界 | **Capability Profile**；同时观察 Provider 与 Context 边界，不升级为 Product E2E |

## 6. 横切验证套件

`validation_catalog.py` 当前登记 `tool_calling_protocol`、`mcp_dispatch`、`a2a_artifact_return` 与 `narrow_research_routing`。`RUN-001` 和 `E16` 同时属于前两个套件，证明不同大类可以复用同一节点；`L04` 同时承担 Product E2E 与 A2A Artifact 关键检查；`ASK-001B` 的 Product E2E 只判断用户结果，窄范围路由套件独立判断个人读取、Web 读取与零整体委托。横切报告保留整例 `pytest_outcome`，只对预先声明的 Trace fact 产生独立 verdict；因此 E16 可以在 GitHub 返回 `401`、用户结果失败时证明动作已解码并到达 MCP，但不能据此通过 Provider availability 或 Product E2E。

同一 commit、dirty digest 和 evaluation identity 的 RUN-001/E16 归档已由新报告器只读验证为 `mcp_dispatch 2/2 passed`：RUN-001 观察到两次冻结 MCP dispatch，E16 观察到两次真实 GitHub MCP dispatch；E16 的原始 `pytest_outcome=failed` 保持不变。使用的归档分别为 `data/e2e_traces/tool-calling-cross-case-20260828/run-001/20260828T104151.816729Z-32700-3a9206ae/` 与 `data/e2e_traces/tool-calling-cross-case-20260828/e16/20260828T104245.678100Z-18276-17a4e69e/`。

2026-08-31 在同一代码、配置和评测身份下重新执行完整 `tool_calling_protocol` 套件，结果为 `3/4 pytest passed`、`4/4 capability passed`，session `125.26s`。`L01`、`L06` 与 `RUN-001` 用户结果通过；`E16` 原生动作四次到达 GitHub MCP，零 action protocol rejection，但外部 GitHub API 均返回 `401 Bad credentials`，因此保持原始 `pytest_outcome=failed` 和用户终态 `limitation`。密封归档为 `data/e2e_traces/tool-calling-validation/20260831T054359.245940Z-19676-8b59b6c6/`，checksum 有效。该结果证明本次 Action/Final 分相没有破坏已登记的 Tool Calling 关键能力，不把外部凭据失败改写为 Product E2E 通过或发布完成。

2026-08-28 的四份 Tool Calling 归档来自连续但独立的 dirty run，dirty digest 不完全相同，只能逐份诊断，不能拼成正式套件晋级。后续统一在同一次 pytest run 中执行套件节点，并由 `cross_cutting_validation.py` 拒绝 checksum 失效、缺失节点、重复节点或 repository/evaluation identity 不一致的 archive。

## 7. 已撤回的 Investigation LT Runtime Conformance

`LT01、LT02、LT03、LT04、LT05、LT06、LT07、LT08、LT10、LT11、LT12、LT13` 均：

- 从 `InvestigationScenarioHarness` 或 Application Service 进入；
- 使用 scripted planner/proposer/verifier/synthesis 与 frozen Tool/Agent Provider；
- 可以直接构造 Plan、Command、approval、late result、budget failure 和 crash window；
- 使用真实 Domain、Application、Postgres store 和部分 worker/recovery 协议。

它们曾属于 **Investigation Runtime Conformance**；当前测试文件已随生产机制删除，下面只解释历史归档覆盖过什么。

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

这些历史用例只能说明旧冻结协议曾受测试保护，不能证明真实模型能规划、真实 Provider 能完成调查或用户需要 `InvestigationProject`，更不能作为恢复已删除代码的理由。


## 覆盖门禁生产迁移的验收边界

2026-09-14 的目标代码已将文档缺项分类和确定性读取覆盖拒绝接入现有生产工具。首个正式用例在 fixture 阶段因 PostgreSQL 不可用失败，未进入模型调用；恢复本地 Docker 临时 socket 与数据库后，保持原中文用户输入及验收标准回跑 `test_conversation_research_review_001`。原失败存于 `.tmp/coverage-production-20260914/environment-startup/`，真实 target 与代码身份存于同轮 `target/`、`target-identity.json` 和 `target-code.zip`。

该轮 Contract／Runtime Conformance 与既有回归共 219 项通过；只证明读取事实推导、门禁与网关边界。正式用户结果与实际拒稿恢复检查点分别登记，未达到的检查点不能由第 83、84 节局部证据替代。工程责任见 [ADR 0021](../adr/0021-separate-document-absence-from-reading-coverage.md)，取舍与日志见[第 85 节](../optimization/document-absence.md#85-覆盖门禁接入真实读取事实与生产工具)。


本轮保留两次真实正式结果。第一次受 `.env` 覆盖加载影响，实际预算仍为 192k，HTTP 177.646 秒后以 `limitation` 结束，Journal 记录 204,815 tokens，未进入 Verifier。只修正临时 runner 加载顺序，按预声明 1.8M 预算回跑后，HTTP 597.347 秒返回 `answer`，pytest 738.09 秒仍为失败：后置独立评测发生 `StructuredOutputFailure`，没有有效语义判定。两个原始密封归档分别为 `target/conversation-research-delivery-001/target/20260914T043541.185015Z-2228-2dbf86de` 与 `20260914T044849.624592Z-9888-3e3482fb`。

第二条轨迹的局部覆盖检查点成立：首稿在 23/121 时被代码拒绝，同一版本补读至 121/121，第二稿经过普通审查并与通过回执逐字绑定。十三次返回窗口与保存原文一致，拒绝中的读取状态与拒绝前的实际执行记录一致。Journal 记录二十个决策回合、二十次工具调用和 826,527 tokens；已有 Verifier 用量遗漏仍使完整成本未知。

人工来源审计仍发现输入参数约束被用来替代工具结果契约、结果字段义务被扩大等普通语义缺口。覆盖拒绝的生产消费可以保留，整例失败和产品完成门禁不能被局部通过覆盖；本轮未修改后置评测器。正式复核与源码保持见 `.tmp/coverage-production-20260914/target-review.json`、`code-review.json`，历史过程见优化第 85 节。

## 成文引用与局部支持核验的迁移验证

2026-09-15 的 [ADR 0022](../adr/0022-conversation-owned-citations-and-support-repair.md)将成文引用交给 Conversation，运行系统恢复全部提交内容，局部支持检查拒绝后复用原循环。10 次真实模型 Offline Eval 均达到预声明目标方向，包括同稿缺证拒绝与增加相邻条款后通过；这些不是 Product E2E，过程见[第 94 节](../optimization/answer-object-mismatch.md#94-conversation-成文引用与缺证恢复的工程接入)。

首次保持原中文用户输入和验收标准的 `test_conversation_research_review_001` 失败：HTTP 786.725 秒、pytest 807.22 秒，25 个决策回合、888,040 tokens，最终 `limitation`，没有交付报告。三次 Final 引用绑定未通过，未进入语义核验或后置评分。因此失败位于候选引用协议检查点之前，不是 Verifier 的真实语义反例，也不是后置评分错误。原报告及代码身份存于 `.tmp/conversation-cited-verification-20260915/target/`、`target-code.zip`、`target-identity.json`。

引用反馈只作一次有界修正后，同一原任务在独立 `repair-target/` 目录复验：带回被拒稿与错误坐标，并区分确定性失败类别；未改变停止算法、模型、读取工具、语义 Prompt 或评测判据。正式用户结果与引用送达、局部拒绝、补充恢复检查点仍分开验收，尚未得到的检查点不由受控测试替代。

该复验最终达到 28 回合预算上限：HTTP 1278.105 秒、pytest 1285.81 秒、1,118,125 tokens、26 次工具调用，终态 `limitation`，原用户结果失败。两类引用错误被分别反馈，计划恢复后又完成两次读取，但没有进入 Verifier。按既有用户授权，以相同代码和用例将回合上限增至 64、token 上限增至 4M，在 `budget-target/` 单独进行扩容复验；不得改写前两条失败，也不把额外预算视为语义机制收益。

扩容复验仍失败：实际 22 回合、1,145,933 tokens、31 次工具调用，HTTP 1227.662 秒、pytest 1235.40 秒。五次 Final 的正文引用匹配数量为 0/6、3/6、5/6、5/6、5/6，最终因同类无效提交停止，未用完 64 回合与 4M tokens。三次都没有调用语义 Verifier，因此没有真实局部判别结果，也没有进入后置评分。记录和原始稿存于 `budget-target/`。

本轮最终撤回逐字复制引用协议及相关未获准生产分支，源码和正式测试恢复至本轮起点，已有优化保持。候选版的局部模型、Contract 和三条正式失败均保留，不能外推为当前生产修复成功或发布通过。下一个方向只保留在 Future：原生成文片段及引用，避免维护第二份正文副本。


## 原生正文分段与引用目录的正式验证

**本节是 2026-09-15 旧协议的历史 E2E 结果，不是当前引用协议的失败 baseline。** 原 [ADR 0023](../adr/0023-native-answer-segments-and-visible-citations.md)的复合引用目录已由 [ADR 0024](../adr/0024-plain-source-tools-and-inline-citations.md)替换，后续正式轨迹八稿均通过新引用绑定。旧编号逐稿错误和修复待办已清除，尝试摘要见[第 95 节](../optimization/answer-object-mismatch.md#95-原生正文分段与引用交接验证)。

原中文用例首试为 PostgreSQL setup error，恢复环境后的正式运行由执行代理主动停止，pytest 记录 **1 failed**，没有最终用户答案。HTTP 4038.331487 秒、pytest 4059.07 秒；Journal 记录 27 个决策回合、36 次工具调用、1,513,273 tokens，不含完整失败请求与 Verifier 子调用成本。替换协议不追溯改写这次失败，也不让它继续证明当前版本的引用修正未闭环。

原自动归档：`.tmp/conversation-native-citations-20260915/live-target/target/conversation-research-delivery-001/target/20260915T092739.234198Z-11152-7b45961c`。同轮 `live-target/` 中的 `manual-stop.json`、`pre-stop.zip`、代码身份和服务日志只读保留。新协议的独立失败须使用对应版本的运行证据；2026-09-18 的 `e1698` 拒绝见[同代码复验](#同代码重新验证核验反馈与修订)，不与旧协议失败合并计数或归因。

## 主区域正文选择的正式验证

2026-09-17 的正文候选保持原中文 `test_conversation_research_review_001` 用户输入、模型、工具、语义核验和评测标准，改变内置 HTML 提取的主区域范围。原文保真反事实、运行消费点和候选自身反例由[正文提取第 110 节](../optimization/source-extraction.md#110-唯一主区域选择的保真与正式消费验证)拥有，不能与产品交付合并统计。

首版真实 target 自然耗尽 64 个决策回合，返回 `limitation`，没有报告交付；HTTP 4523.000542 秒，pytest **1 failed**、4546.97 秒。Journal 记录 63 次工具调用与 4,595,172 tokens，未完整归集 Verifier 子调用成本。失败断言为 `delivered=False`，未进入后置答案评分，不属于评测器误判。原始自动归档为 `.tmp/main-content-boundary-20260917/formal-target/target/conversation-research-delivery-001/target/20260917T045457.767463Z-24556-d2323b8b`；代码、运行审计和文件校验和在同轮 `formal-target/`。

真实读取检查点已到达：2603 条返回行记录与原文和列坐标匹配，覆盖门禁和局部支持拒绝仍被消费。但首版本身存在 `noscript` 祖先丢失的确定性反例，不准入。一次有界修正后，最终代码 37 项 HTML／Capture／来源表示检查通过，修正版同入口 target 独立执行。

修正版仍为 **1 failed**：HTTP 773.785886 秒后返回 503，pytest 791.45 秒，`delivered=False`、`entry_error=True`。不是启动环境错误；实际模型已进行搜索和读取，失败位于成文的 `provider_structured_decode`／`structured_output_invalid`，没有进入 Verifier 或后置评分。最后已提交快照记录 8 个决策回合、12 次工具调用、278,209 tokens，未包含完整失败生成及修复用量，不能当作全部成本。自动归档为 `.tmp/main-content-boundary-20260917/formal-target-v2/target/conversation-research-delivery-001/target/20260917T050957.258365Z-27268-a55e8f6c`。

修正版正式消费的 531 条行记录与原文坐标一致，固定正文和忽略范围控制也通过，因此保留正文提取的局部机制；两次原始产品失败及成文交接阻塞同时保留。未用该局部收益更新产品完成率，未执行全发布矩阵。

## 完整查询交接与 Context 候选的正式验证

2026-09-17 的候选保持原中文 `test_conversation_research_review_001`、用户结果契约、正式入口、真实 Composition Root、MiMo v2.5 及真实工具。局部机制与撤回范围见 [ADR 0026](../adr/0026-separate-query-facts-from-cited-evidence.md)和[第 115 节](../optimization/evidence-acquisition.md#115-完整查询交接与-context-重组的正式接入验证)。

首轮移植遗漏此前整体候选的两段指引，执行代理人工终止，不计自然失败或通过；保存的 Conversation 用量为 1,496,664 tokens，原始代码、终止原因与文件校验和保存在 `.tmp/query-context-integration-20260917/formal-target/`。一次有界修正后，完整候选仅回跑原例一次。

正式回跑为 **1 failed**，HTTP 2185.878024 秒、pytest 2194.53 秒（约 36.6 分钟），53 个决策回合、54 次工具调用、2,194,884 已记录 tokens。四稿经历三次覆盖拒绝和一次引用支持拒绝，最终返回 `confirmation_required`，请求用户确认保存原研究请求，没有交付比较报告、没有知识写入，后置答案评测未运行。未耗尽 64 回合、96 工具或 6M tokens 上限，亦非入口服务异常。曾有一次网页读取失败，但之后继续执行，不能把自动报告的最早工具失败直接作为终止根因。

自动归档为 `.tmp/query-context-integration-20260917/formal-target-v2/target/conversation-research-delivery-001/target/20260917T151702.491747Z-12088-8e72a91d`，含原用户输入、HTTP 结果、完整 Trace、用例身份和评分状态。同轮 `target-code.zip/target-identity.json`、`final-audit.json` 与 `sealed-manifest.json` 保存代码、因果边界和原始文件校验和。Journal 的用量只覆盖已记录 Conversation 请求，Verifier 子调用与完整供应商计费未完整归集，总成本未知。

成功搜索参数与来源引用保真控制成立，局部机制已[独立固化](../optimization/completed/query-execution-handoff.md)。保存准入代码未变、规则未遗漏，却仍不能排除整体 Context 对误选动作的因果责任，因此撤回本轮行为接入，未把该失败归为已确认独立的下游问题。查询交接保留，原正文、Plan、覆盖、引用和修订机制保持。

候选相关 244 项检查、研究消费者补查 26 项、撤回后相关 230 项分别通过；固定状态两次 Offline Eval 未复现扩源，不属于正式消融或用户验收。最终保留组合没有再运行完整 E2E，全发布矩阵未执行。本轮不能声明产品完成、可合并或可发布。


### 取证充分性契约的正式验证

2026-09-17 至 18 日，先以新增充分性契约之前的当前代码运行原 `test_conversation_research_review_001`。结果 **1 failed**，pytest 632.74 秒、HTTP 617.029729 秒；一次覆盖拒绝后继续取证，Final 引用对象及结构修复输出先后非法，最终 HTTP 503。未交付答案，未执行后置答案评分。最后提交的 Journal 为 14 次模型请求、13 个决策回合、13 次工具调用、261,326 tokens；后续失败 Final 及修复的完整用量未计入该值。

原脚手架错误设置 REVIEW 名称的证据角色变量，共享 recorder 实际读取 DELIVERY 名称，因此原密封 archive 标签仍为 target。该次实际运行发生于变更前，源码与原始结果完整保留；没有修改 archive 标签或校验和，也不能将其作为机器 baseline/target 晋级配对。后续 runner 已修正变量名。身份、失败阶段与限制见[baseline 审计](../../.tmp/evidence-sufficiency-20260917/baseline/baseline-audit.json)。

候选相关 Contract / Runtime Conformance 为 183 项通过；真实模型初始 3 项中 2 项符合预期，第 3 项因正例遗漏已给定约束而正确拒绝。保留原失败，补全该正例后与此前未执行的 3 项共 4 项均符合预期。两个阶段合计覆盖 6 个有效边界，18 次请求、38,324 tokens、605.106 秒，均为 Offline Eval。

候选正式 target 已在同一入口执行完毕并失败：断言 `delivered=False`，`disposition=limitation`，命中 64 个决策回合上限，`2,207,132` tokens、65 次模型调用、46 次工具调用，用量完整。46 次工具调用中 21 次验证失败，其中 17 次为局部来源支持拒绝、4 次为引句必须逐字引用草稿的参数错误；`source_coverage_rejection` 为 0，三个比较主题覆盖均为 `false`。该归档只保存验证工具的结果、不保存入参，因此无法判断覆盖分支是否被触发或声明是否被提交，本轮对候选的结论只能是该次运行不可判定。原始归档与候选代码身份保存在 `.tmp/evidence-sufficiency-20260917/target/target/conversation-research-delivery-001/target/20260918T030142.249483Z-16520-afcd128d`。归档的完成时间与报告耗时互相矛盾，另有约 9 小时无新 `llm.parse` 完成日志的缺口且原因未确认，本轮不据此声明延迟改善。现阶段无完整用户结果通过或发布资格。取舍见[第 116 节](../optimization/evidence-acquisition.md#116-由模型决定结束取证的契约验证)，接口见 [ADR 0027](../adr/0027-model-owned-evidence-sufficiency.md)。

## 核验意见调用绑定的正式检查点

2026-09-18，以 [ADR 0029](../adr/0029-bind-verifier-feedback-to-input-unit.md) 的三个文件改动执行一个原中文 `test_conversation_research_review_001`，未改用户输入、生产入口、MiMo v2.5、工具和评测标准。沿用历史宽预算 64 回合、96 工具、6M tokens；这是运行覆盖配置，不是预算收益。

两次生产支持拒稿分别返回两条意见，并带回当前精确段落；首轮意见进入后继输入构造，次稿移除对应开场。局部证据见[固化记录](../optimization/completed/verifier-finding-binding.md)。首轮开场误拒嫌疑与第二轮支持缺口未被本次绑定修复解决，未取得完整报告交付。执行代理按局部机制检查点成立后停止长跑的范围要求人工中断；pytest 为 `KeyboardInterrupt`，1385.76 秒，不能记作通过、自然预算耗尽或完整的自动失败判定。

最后留存的快照诊断为 16 次模型调用、15 个决策回合、20 次工具调用、561,182 tokens；这不是最终完整成本，Verifier 子调用及在途请求用量未完整归集。原始运行的临时服务日志和 Journal 被 fixture 清理，首次停止前复制遇到临时文件锁，停止后检查两份 zip 均为空。保留错误记录及更正，不把空归档当成封存成功。已有代码身份、提前保存的反馈物化、检查点及从当前任务工具结果恢复的诊断输出位于 `.tmp/verifier-unit-binding-20260918/target/`，详见[最终审计](../../.tmp/verifier-unit-binding-20260918/target/final-audit.json)。

本轮六次真实模型 Offline Eval 与历史回放只支撑局部边界；未维护或运行单元测试，未执行全发布矩阵。完整用户结果、完整 E2E 归档及发布门禁尚未满足，不声明产品完成或可发布。

## 同代码重新验证核验反馈与修订

2026-09-18 按用户要求重新执行原中文 `test_conversation_research_review_001` 一例，结果为**运行中断、未交付，不能记通过**。源码与上轮候选逐文件哈希一致，模型、正式入口、原评分器及 64 回合／96 工具／6M tokens／7200 秒请求预算不变；未修改生产或用例，未运行单元测试。collect-only 仅一项，复用既有影响路由，不代表完整发布矩阵。

运行取得四份语义拒稿，随后第五稿因不可见引用 `e1698` 在准入阶段被拒。该编号错误独立登记为[原文行号与临时引用编号混用](../optimization/citation-coordinate-confusion.md)，原因假设与实际拒绝分开，不与旧引用协议合并计数。核验反馈的局部结果只由[固化记录](../optimization/completed/verifier-finding-binding.md)拥有；改稿遗漏证据及新增无据论断见[修订观察](../optimization/revision-feedback-loop.md#118-同代码复验中的引用覆盖反复)。最后已提交快照记录 34 次模型调用、33 个决策回合、45 次工具调用和 2,102,782 tokens；未完整归集核验子调用及在途请求，不能当全部成本。

为避免上轮清理丢失，临时脚手架每两秒只读复制服务目录，并配置 teardown 前复制。实际持续采集 3389.049 秒（约 56.5 分钟），保存 34 份 Journal 快照、服务日志及来源文件，共 44 个文件，复制错误为零。采集最后时间为北京时间 16:02:43，此后没有 teardown、runner 结果或 canonical 产品报告。后续检查确认进程不存在、exec 会话失效；退出原因与确切时间未知，不归因为模型自然停止、预算耗尽或已知服务故障。

执行代理曾仅轮询静态快照，误报仍在等待响应；后续核对进程后已纠正，误轮询时长不计产品运行耗时。状态脚本现区分采集心跳过期与新快照。没有将新运行冒充原进程续跑，未追加第二个昂贵样本。代码身份、原始备份、停止审计与校验和位于[本次归档](../../.tmp/verifier-e2e-rerun-20260918)，结论见[最终审计](../../.tmp/verifier-e2e-rerun-20260918/final-audit.json)。本次证据不满足完整用户结果或发布门禁。

## 文档坐标引用的 Offline 验证

2026-09-18 至 19 日，按用户要求只验证 [ADR 0030](../adr/0030-document-line-citation-identity.md) 的局部引用协议，没有执行 E2E 或单元测试。历史失败输入中的 1264 条证据保真回放通过，3 次真实模型 Offline 样本均通过坐标选择与绑定检查；完整结果、成本、脚手架更正和语义限制由[引用坐标记录](../optimization/citation-coordinate-confusion.md#9-月-18-日逐行坐标替换的历史-offline-结果)拥有。原始请求、响应和前后源码身份保存于[归档](../../.tmp/citation-document-lines-20260918)。

本轮没有执行语义交付验收，不增加 Product E2E 通过数，不改写上一节失败。长期观察仍为 0，后续随正常 E2E 按[预声明条件](../future/citation-coordinate-identity.md#后续-e2e-观察与-completed-条件)记录；本轮局部通过不证明概率性混用已经长期消失。

## 修订引用保留约束的 Offline 对照

2026-09-20，用当前生产请求构造链消费历史 `0027.json`，比较当前 Final 提示与明确保留正文及有效引用的候选。每臂一次真实 MiMo v2.5 调用，2/2 完整输出且引用可恢复；人工按预声明检查实际正文和条款，两臂都存在引用覆盖缺口，候选未取得语义修订资格。结果、成本及新的基稿交接发现由[修订记录第 121 节](../optimization/revision-feedback-loop.md#121-修订引用保留约束与完整稿合成边界)拥有，原始请求及响应见[归档](../../.tmp/revision-preservation-20260920)。

这是固定输入的探索性 Offline Eval，不是 E2E、稳定性估计或正式消融。没有修改生产 Prompt、Schema、状态或核验链，没有运行 E2E 或单元测试；不改变原正式任务结果或发布分母。


## 完整基稿与局部修订的验证

2026-09-20，按 [ADR 0031](../adr/0031-complete-final-revisions.md) 执行历史失败回放和四次真实模型 Offline。完整基稿对照仍漏引；局部修订候选及两个语义边界检查符合预声明。局部结果、样本数与成本由[修订第 122 节](../optimization/revision-feedback-loop.md#122-完整基稿交接与原子修订验证)拥有，不计 Product E2E 成功。

同一原中文 `test_conversation_research_review_001` 已从正式 HTTP 入口启动，使用真实 Composition Root、模型、查询和原 Verification、Completion 链，沿用历史宽预算；仅定向收集这一例，不收集或运行单元测试。影响路由要求完整发布矩阵，但依照原阻塞例先行的规则，本轮不扩大矩阵，也不声明发布资格。原始代码身份、运行日志与持续复制的服务事实见[正式归档](../../.tmp/final-revisions-20260920/e2e)。正式结果为 0/1 通过：测试总耗时 3116.46 秒，入口请求 3083.60 秒；模型服务提供方在最后请求中连续三次返回 429，入口返回 503，未交付答案，未运行后置语义评分。不是预算耗尽或人工中断，也不能因为服务故障忽略此前的连续拒稿。


最后已提交快照为 40 个决策回合、41 次主链模型调用、34 次工具调用、2,056,526 tokens；这是 Journal 用量，不含未完整归集的核验子调用及最后在途请求，完整成本未知。canonical 报告因入口异常未取到交互对象，记录 `usage_incomplete=true` 及缺失测量，不能把其中 `total_tokens=0` 当作实际零用量；持续复制的服务事实补充了诊断，未篡改原报告。归档 `summary.duration_seconds=0.450511` 仅是 recorder 写档窗口，不是 E2E 耗时。

9 份完整提交和核验入参逐份一致，完整交接结论见[固化记录](../optimization/completed/complete-rejected-draft-handoff.md)。局部协议的真实模型消费由 Offline 证明；正式日志未保留原始提交种类，不能断言本例实际采用局部修改的次数。完整重写仍丢引用及连续开场拒绝见[修订第 122 节](../optimization/revision-feedback-loop.md#122-完整基稿交接与原子修订验证)。原 E2E 失败保留，不追加第二次长跑或发布矩阵；本轮不声明完整修订已解决或可发布。


## API 恢复后的修订选择 Offline

2026-09-21 使用原正式 `0022.json` 与 `0024.json` 的成文输入各调用一次当前 MiMo v2.5，两次 API 均正常返回。原始提交均为完整新稿，技术合法 2/2、原配置缺口修正 2/2，修订段没有新增支持缺口为 1/2；第二份重写新增了未随文引用支持的工具类型。判据、成本、人工核对依据与限制由[修订第 123 节](../optimization/revision-feedback-loop.md#123-api-恢复后的修订选择诊断)拥有，原始输入与响应保存在[独立归档](../../.tmp/revision-selection-20260921)。

本轮生产代码未变，没有重跑 E2E、完整 Verifier 或单元测试，不增加产品成功数，不改写原 429／503 的正式失败。API 恢复不代表语义修订收敛；原始定位错误和 URL 漏引本次未复现，也不足以宣布概率问题已解决。

## 提交前证据自检的 Offline 候选

2026-09-21 在相同历史输入上只替换 Final 自检要求，各执行一次真实模型调用。技术合法及原配置缺口修正均为 2/2，局部无新增支持缺口为 1/2；第二次完整重写新增了未受随文证据支持的工具控制选项，候选未通过预声明门槛，该轮未接入生产。具体判据、成本、人工原文核对与局部收益限制由[修订第 124 节](../optimization/revision-feedback-loop.md#124-提交前证据自检的隔离候选)拥有，原始证据保存在[独立归档](../../.tmp/final-self-check-20260921)。

本轮是固定输入的探索性 Offline，不是正式消融、稳定率估计或 E2E。没有新增运行时自检阶段、模型调用或生产字段；未运行完整 Verifier、E2E、单元测试或发布矩阵，原正式失败与发布分母保持。

随后按用户明确要求，将同一自检版本保留到当前代码，详见[后续取舍与输入审计](../optimization/revision-feedback-loop.md#125-保留自检与最新反馈的输入审计)。只核对模板一致性、实际请求构造与静态检查，没有新模型样本，原局部失败和正式用户结果仍未通过。

## 当前修订反馈区的 Offline 验证

2026-09-21 固定已保留的自检版本，将最新基稿和核验意见组织成独立当前反馈区，在原 `0022`、`0024` 输入上各采样一次。技术合法、原缺口修正及局部没有新增支持缺口均为 2/2；两次只修改目标段，其他六段正文与引用保持。历史同自检版本的局部结果为 1/2，但两份相近状态的小样本不证明稳定提升。成本、语义判据、未改旧问题及接入条件由[第 126 节](../optimization/revision-feedback-loop.md#126-当前修订反馈区的隔离验证)拥有，原始证据见[归档](../../.tmp/current-revision-feedback-20260921)。

这轮没有修改生产反馈链，没有运行完整 Verifier、E2E、单元测试或发布矩阵，不增加产品通过数。候选尚待相邻语义边界、真实对象关联和正式消费验证；已有自检版本保持，原始正式失败不变。

## 当前反馈区的语义边界 Offline

2026-09-21，固定前轮反馈模板与自检，以完整历史来源构造正文错误、合理未知、来源误引三份独立边界输入。实际执行正文例一次：技术合法 1/1，所指固定确认断言修正 1/1。原归档将新概括的范围歧义按联合判据计为“改写无新缺口”0/1，并停止后两例；原评分及未执行事实不改写。不将代表性数据冒充原 E2E 状态，不按 0/3 计分。

经用户要求分开问题后，更正证据解释：目标反馈已被消费，规范强度与指代范围属于[独立诊断项](../optimization/normative-scope-attribution.md)；尚未证明该歧义是明确强度错误或由反馈区改动引入，不能把原联合判分作为反馈机制无效的证据。该更正不是新运行结果，也不是将 0/1 事后改成通过。输入、成本和范围取舍由[第 127 节](../optimization/revision-feedback-loop.md#127-当前反馈区的正文修订边界)拥有，原始证据见[归档](../../.tmp/feedback-boundaries-20260921)。前轮补引 2/2 保持，候选尚未生产接入，自检保留；未新增模型调用、完整 Verifier、E2E 或单元测试，原正式用户失败不变。

## 连续反馈与前轮成果保留 Offline

2026-09-21，复用封存的配置补引成功稿，依次执行来源反馈和权限反馈两次真实模型续修；每轮使用上一轮实际完整输出，反馈为依据历史失败整理的固定 Offline 数据，不是完整 Verifier 循环或 E2E。技术合法与目标反馈响应均为 2/2，目标完整修正与此前有效成果保持均为 1/2，整条连续保留轨迹为 0/1。首轮补入 `r9` 且保住配置引用；次轮保住 `r9`，却在整稿重写时删掉此前必需的 `d1:1697`，配置正文没有改变，原缺口重现。

判据、实际请求审计、责任边界和成本由[第 128 节](../optimization/revision-feedback-loop.md#128-连续反馈中的修订保留验证)拥有，原始证据见[连续续修归档](../../.tmp/feedback-sequence-20260921)。没有发现本轮输入交接或引用物化丢失该依据，绑定机制未重新立项；独立语义问题不参与核心回退归因。未修改生产代码、执行完整 Verifier、E2E 或单元测试，不增加产品通过数，也不声称候选导致了相对旧版的退化。

## 按修改范围编辑的 Offline 候选

2026-09-21，仅替换 Final 的修订动作说明，复用上一轮权限反馈的实际完整输入，执行一次真实模型调用。技术合法与前轮有效成果保留均为 1/1，当前目标修正为 0/1，联合判据为 0/1：本次整稿提交保住配置引用，但仍以未找到说明推导开发者责任，所附依据仍为 MCP 来源。不能把本轮目标失败解释为引用保留失败，也不能外推一次保留成功为稳定修复。

按预声明停止错引边界和原生产 Context 两例，均未执行，不以 0/3 计分。候选未接入，生产源码保持，未运行完整 Verifier、E2E、单元测试或发布矩阵；原正式失败不变。判据、63.67 秒及 58,081 tokens 用量、输入审计、取舍和归档由[第 129 节](../optimization/revision-feedback-loop.md#129-按修改范围选择编辑动作的隔离验证)拥有。

## 提交说明一致性的 Offline 验证

2026-09-21，统一实际输入中的局部编辑与完整新稿说明，对同一权限反馈状态独立采样两次。局部正文编辑及未改单元保真均为 2/2，全部前轮必要引用保留为 1/2：两次只替换第 6 段，其他六段及配置引用完整保留；次例在被改段内删除 Host 结论所需的 `r9`，该结论仍保留。机制检查点和段内引用退化分别记录，不将操作名当作产品成功。

两例删除原开发者责任推断，但当前反馈完整修正仍为 0/2；这个语义结果不否定未改部分的确定性保留。总计 118,017 tokens、176.21 秒，无额外样本、重试、完整 Verifier、E2E 或单元测试。生产代码未变，候选尚未正式接入，完整用户结果不变；输入一致性、实际附证、取舍和下一责任边界由[第 130 节](../optimization/revision-feedback-loop.md#130-完整交付与修改提交的一致性验证)拥有。

## 正文与引用增删协议的 Offline 候选

2026-09-21，在隔离源码中将正文修改与引用新增、删除分开表达。真实历史反事实证明未声明删除的引用能够保留，明确删除冗余引用能够执行；这不是模型生成操作的证据。新增真实模型调用一次，技术合法及前轮必要引用保留均为 1/1，但返回整稿，新增删协议实际消费为 0/1，权限反馈完整修正为 0/1。没有观察到本例必要引用退化，也没有证明修订保护已被模型使用。

首例后停止，另外两个预声明样本未执行；候选未接入，不追加模型调用。生产代码保持，未运行完整 Verifier、E2E 或单元测试，不增加产品通过数。实际请求、63.13 秒及 58,286 tokens 成本、反事实边界和取舍由[第 131 节](../optimization/revision-feedback-loop.md#131-正文修改与引用显式增删)拥有。

## 统一修订入口的 Offline 候选

2026-09-22，保持段落结构，由当前基稿确定实际请求和接收类型，修订阶段不再接受完整回答替换。历史同一整稿的新旧 Schema 反事实通过，首次成稿、非回答出口与显式引用增删仍可表达。正式 `_decide` 的历史状态请求捕获确认候选选择相应类型；这是模型 Port 前的 Offline 检查，不是 E2E。

新增真实模型调用一次：修订分支选择 1/1，合法修订与完整合成 0/1。模型正确引用当前基稿，但给七段稿提交第 8 段修改及空字符串正文，解析拒绝，未生成或应用新稿。不能把未应用计为引用回退或引用保留通过；输入中原完整基稿和反馈没有错配。按预声明停止其他两例，未重复采样，候选未接入。57,580 tokens、33.21 秒，原用户 E2E 失败保持；原始响应、归因和下一边界由[第 132 节](../optimization/revision-feedback-loop.md#132-被拒稿的统一修订入口)拥有。

## 全部生成端引用统一为文档行坐标的 Offline

2026-09-22，按用户要求删除完整工具结果号，网页原文、Artifact 窗口与结果文档统一采用文档行坐标。真实历史工具事实回放及两个真实模型短样本通过局部引用检查，三个生产文件已替换。证据及限制由[引用坐标记录](../optimization/citation-coordinate-confusion.md#统一所有生成端引用为文档行坐标)拥有，契约见 [ADR 0030](../adr/0030-document-line-citation-identity.md)。

本轮仅 Offline，没有执行完整 Verifier、E2E 或单元测试，不增加产品通过数，不改写此前修订失败或旧格式归档。模型选用合法引用不证明长 Context 的修订保留已经解决，后续修订验证须使用当前协议生成的新稿。

## 修订目标范围的 Offline 候选与准备失败

2026-09-22，动态段落范围、编号基稿单次投影与正文空值语义在隔离候选中完成确定性检查及正式请求捕获。唯一真实模型调用用于当前文档行引用的样本准备，结果 0/1：模型输出不支持的行范围，解析拒绝，未生成验证基稿。后续两项修订模型样本均未执行，不能记作修订失败或通过。

60,647 tokens、59.71 秒，零重试；候选未接入，生产源码保持，没有完整 Verifier、E2E 或单元测试。原始失败、责任边界与未验证条件由[修订第 133 节](../optimization/revision-feedback-loop.md#133-修订目标范围与空值语义的隔离验证)拥有，引用范围反例单独登记，原用户结果不变。

## 连续行引用协议扩展的 Offline

2026-09-22，按用户要求扩展唯一文档坐标契约。历史五个非法范围在旧契约下仍拒绝，同一原始输出在新契约下可以逐行恢复，正文和来源与显式逐行选择完全一致。两个真实模型短样本均通过引用检查点，三个生产文件已接入；预声明、反事实、请求及结果由[连续行范围记录](../optimization/citation-coordinate-confusion.md#连续整行范围的契约扩展与-offline-验证)拥有。

本次未运行完整语义核验、修订模型样本、E2E 或单元测试，不增加产品通过数。范围契约扩展不能把此前样本准备失败改记为通过，也不能宣布修订候选已得到模型验证；后续须明确采用新契约的输入与代码身份。

## 行范围接入后的连续修订 Offline

2026-09-22，复用历史真实引用选择响应在新契约下组成的七段派生稿，继续验证第 133 节隔离修订候选。两次真实模型均合法合成并保留前轮成果，形成一条两轮保留轨迹；第二轮缺配置引用由离线移除明确构造，不是首轮自行退化或真实 Verifier 新发现。当前反馈完整修正为 1/2，首例仅部分修正，语义来源支持与保留机制分别记分。原始结果、成本及边界由[第 134 节](../optimization/revision-feedback-loop.md#134-行范围引用接入后的连续修订验证)拥有。

候选未接入生产，当前反馈区仍是 Offline 请求适配；未执行完整 Verifier、Completion、E2E 或单元测试，不增加产品通过数，不改写旧准备失败。后续正式消费与完整用户结果仍须独立验收。

## Flash 显式删错引与正式 Context Offline

2026-09-22，用户选择将当前生成式模型统一为 `mimo-v2.6-flash`。在相同修订候选上执行两次独立于旧 v2.5 cohort 的真实模型 Offline：首例明确删除指定段落的不相关引用，其他正文及同源合法引用保持，局部检查 1/1；第二例不追加 Offline 反馈区，全部应用消息由候选正式 `_decide` 构造，实际输入审计通过，但模型服务请求在 180 秒上限处超时，没有输出或 usage。该次调用作为服务失败保留，不能计为候选模型消费通过或语义反例。

首例已知 60,213 tokens，第二例用量未知，本轮总用量不能报告为 60,213。成本、原始请求、停止条件及边界由[第 135 节](../optimization/revision-feedback-loop.md#135-显式删错引与正式-context-路径的后续验证)拥有。没有重试、完整 Verifier、E2E 或单元测试；模型配置和评测入口约束已同步，不代表原答案 grader 完成新模型校准，也不改写原用户结果。


## v2.5 正式 Context 续验的 Offline

2026-09-22，仅恢复此前超时的正式 Context 样本，既有候选逻辑、派生稿、来源、反馈及全部请求参数保持，只将模型改为用户指定的 `mimo-v2.5`。一次真实调用在 55.29 秒返回，61,015 tokens；请求完成 1/1，合法修订与完整合成 0/1，当前缺引修正 0/1。模型将 URL 搬入相邻正文后对原单元提交空字符串，类型拒绝，未生成最终稿；另在原始提交中要求删除仍必要的依据，自动继承不能保护被明确删除的引用。

事实、输入审计及停止条件由[修订第 136 节](../optimization/revision-feedback-loop.md#136-切回-v25-后的正式-context-单样本续验)拥有。没有重跑删错引、重试、响应改写或新增生产机制；原 Flash 超时保持，不按跨模型独立轨迹证明超时已修复。候选未接入，未运行完整 Verifier、Completion、E2E 或单元测试，不增加产品通过数。


## 模型前置依赖的连续验证边界

2026-09-22，现有固定历史稿、独立选引及派生反馈的修订 Offline 保留原始结果，只支撑给定状态下的局部判断，不证明自主成稿至修订的整链收益。新论述单元划分尚无连续验证证据，不能把手工理想划分作为前置成功。后续验证按[EVD 依赖链门禁](../devSpec/change-evidence.md#11-模型依赖链必须连续验证)执行，不能把分别成功的模型步骤拼接计分；具体更正见[修订第 137 节](../optimization/revision-feedback-loop.md#137-模型前置依赖的验证边界更正)。本次仅规范与证据解释更新，没有新增产品通过数或模型调用。


## MCP 接入协作任务的输入修正

2026-09-22，用户要求修正将 OpenAI 与 MCP 作为同级对象比较的输入。普通研究请求及显式验收请求改为说明模型、宿主应用（含 MCP 客户端）与 MCP 服务器如何协作，覆盖选择与调用、权限检查、结果处理，并区分模型能力、应用实现与协议要求。不要求六段、七段、固定长度或对称逐项比较，未知须如实限定。两个入口分别使用新数据集版本，结果契约改用 `mcp_cooperation_official_support` 与 `reviewed_mcp_cooperation_official_support`，旧失败不能充当新任务的同输入 baseline。

共享评分器升级到 `research-answer-responsibility-support-zh-v4`，三个 typed 字段统一为 `*_explained`，删除 `*_compared`；没有兼容别名或并行评分路径。评分仍检查实质内容、来源支持和无据保证，且不得将函数调用的执行方直接当作所有远程 MCP 接入的执行方。参考事实未新增，覆盖不足仍须如实报告；该输入修正不是评分准确率已改善的证据。

历史校准入口明确保留旧用户文本与控制，原归档不改写；v3 的 20/20 不作为 v4 新任务资格。此次只修改评测输入、契约与文档，没有运行模型、完整 E2E 或单元测试。实际代码、静态检查与限制见[本次归档](../../.tmp/research-cooperation-input-20260922/checks.json)，方案推进须从正式 HTTP 入口沿真实依赖链取得新证据。


## 研究评分 Prompt 的通用化更正

2026-09-22，用户指出上一节 v4 指令与三个 `*_explained` 字段仍固化了具体题目。现已替换为唯一 v5 评分器：从 `user_request` 判断是否实质满足，输出 `user_request_satisfied`、`missing_requirements`、引用支持及错误、依据不足列表，不预设具体领域或题目数量。旧 v4 字段和场景判断条文删除，没有别名或并行评分器。

参考事实原样迁入 `evals/e2e_quality/fixtures/research_answer_official_references.json`，由场景或历史回放显式选择，经过 `ResearchAnswerReferenceSet` 校验再输入。评分器没有参考题目默认值，正式研究样本的配置身份包含所用资料内容摘要；历史请求与原始模型输出保持。输入构造回放只证明通用指令一致、原任务和资料传递保真，不证明评分语义通过。

开发根规范、COD、评测入口和完成门禁同时禁止在模板、默认构造或固定评分字段中藏入具体问题。生产 Prompt 未修改；新评分器和接入协作任务未执行真实模型资格或 E2E。本次静态扫描、历史输入物化、引用资料保真和文档检查见[归档](../../.tmp/generic-evaluation-prompt-20260922/checks.json)。


## 自主 claims 与真实反馈的连续 Offline

2026-09-22，当前中文协作任务从空资料与空研究产物开始，研究模型自行检索、读取、生成 claims，现有 Verifier 返回真实反馈后续接局部修订，最多两轮。归类为临时隔离可行性诊断，不新增正式 catalog 用例或产品通过数；不是固定历史前稿回放，也不注入派生反馈。预声明、实际路径差异及结果由[修订第 140 节](../optimization/revision-feedback-loop.md#140-自主生成-claims-与真实反馈的连续试验)拥有。首稿若直接通过，修订记为未覆盖；研究阶段通过也不能替代独立汇总与正式用户 E2E。

实际一条轨迹生成 7 条 claims，真实反馈两次定位 `c1`；首次局部修订合法但同一缺证仍被拒，第二次新增项多出身份字段而解析失败。自主生成 1/1、修订合法 1/2，不计产品成功。原脚手架预算阻塞归档不改写，分页有界修正从未消费的真实网页结果续接，未重抽前置决策。共 12 次模型调用、114,812 tokens；完整用户 E2E、汇总和多轮已修成果保持未覆盖，分项事实见上引优化记录。

## 单项 claim 替换与工具指标的连续 Offline

2026-09-22，完成 1 个从空资料起步的 MiMo v2.5 样本：自主取证、生成 claims、真实 Verifier 反馈、单项替换及再次核验连续消费，没有预置前稿或人工反馈。研究动作 Schema 合法 10/10、取证执行成功 8/8、替换应用及未改项保留 1/1，但目标语义修复 0/1；原始轨迹未通过，第二次修订在预声明时间边界后未执行。14 次模型请求共 151,028 tokens，没有供应商超时或重试。

协议与局部保留取得一次消费证据，不据此外推稳定率；完整研究集合仍未通过，最终写作、正式 E2E 和修好后接续新反馈保持均未覆盖。按临时隔离 Offline 记录，不增加正式 catalog 或产品通过数。方法、分母、实际输入审计与结果解释由[修订第 141 节](../optimization/revision-feedback-loop.md#141-单个完整-claim-替换与工具分层评估)拥有，外部方法由[工具可靠性参考](../agentRef/verification-and-observability.md#4-工具可靠性的分层评估)拥有。

## 正文与引用分开编辑的连续 Offline

2026-09-22，完成 1 个从空资料起步的 MiMo v2.5 隔离样本。模型取证后首次创建 6 项 claims，但提交未返回的引用坐标，绑定拒绝，原始轨迹失败。动作 Schema 合法 4/4、取证成功 3/3、创建应用 0/1；两种新编辑、显式提交和真实 Verifier 均未到达，不能计为工具拆分通过或失败。

共 4 次请求、29,118 tokens、165.49 秒。按预声明停止，没有修整中间状态、补抽或 E2E，不增加正式 catalog 或产品通过数。代码身份、实际输入和分层结果由[修订第 142 节](../optimization/revision-feedback-loop.md#142-正文与引用分开编辑并显式提交核验)拥有。上一轮单项替换的合法消费事实保留，但不能外推到本轮新协议。


## 研究参数范围与错误恢复的连续 Offline

2026-09-23，完成一个自然任务从空状态开始的隔离样本，使用 MiMo v2.5 及真实取证、分页、绑定与 Verifier。10 个研究请求的参数范围投影均与实际目录一致，动态 Schema 合法 8/10；首次引用错误实际回传后，模型搜索和读取并合法创建，已消费反馈后的恢复 1/1。另一条阶段动作错误在下一请求前遇预算停止，尚未消费；所有拒绝合计恢复 1/2，不能将未到达计为模型修复失败。

实际正文单字段修改 1/1，原引用与其他两项保持；引用修改未覆盖。一次完整提交被真实 Verifier 拒绝，修改后未再次核验，研究集合未通过，不增加产品成功数。12 次模型请求共 215,694 tokens、572.03 秒；保守请求前成本估计触发预声明预算停止，没有服务超时或补抽。历史原始提议回放另证明 9 处非法引用可被定位和反馈，不与连续样本合并计数。

方案、具体问题及证据边界由[第 143 节](../optimization/revision-feedback-loop.md#143-参数范围与参数拒绝恢复)和[待验证索引](../optimization/to_verify/README.md)拥有。生产代码未变，未执行完整 E2E、单元测试或最终汇总，不增加正式 catalog 或发布资格。

## 同一参数恢复轨迹的有界续接

2026-09-23，保持三个待验证候选，从前一封存轨迹的真实未消费错误续接，初始输入一致性检查通过；不计第二独立样本。新增 6 次模型请求、178,743 tokens、450.17 秒，累计 18 次请求、394,437 tokens。已有集合误创建的错误被消费后，模型合法提交完整第 2 版，实际 Verifier 仍拒绝 c1。随后补读原文并合法修改正文，但下一次把引用参数放进正文工具，被拒绝并触发预声明的累计参数拒绝上限。

累计实际范围投影 14/14，送达错误后的参数恢复 2/2（同一轨迹），合法正文编辑两次均保持其他字段；独立引用动作仍未调用，不能记为通过。末次错误未送达下一请求，不能记为恢复失败。完整集合未通过，也没有已修语义成果的跨反馈保持证据；保留三个候选，不增加产品、catalog 或 E2E 通过数。结果与具体问题由[第 144 节](../optimization/revision-feedback-loop.md#144-保留三个候选并接续未消费的参数错误)拥有。

## 提高参数拒绝上限后的同轨迹恢复

2026-09-23，用户授权将累计参数拒绝上限从 3 次提高到 6 次，其余累计预算与协议保持。新增 5 次真实模型请求、150,478 tokens、233.62 秒。最后的字段错误已实际送达，模型连续两次重复混用，随后合法提交原第 3 版；引用没有更新，真实 Verifier 仍拒绝 c1。累计参数拒绝 5 次，因第 3 次完整核验仍失败而停止，不是参数上限或供应商错误。

累计 23 次模型请求、544,915 tokens，仍是一条自然任务轨迹。范围投影 17/17；正文工具应用 2/5，已应用编辑字段保护 2/2；独立引用动作 0 次。返回合法提交与修复原编辑意图分开计分，不能因工具参数合法提升语义结果。完整问题、预声明及证据由[字段混用恢复记录](../optimization/claim-field-tool-mixup.md#扩大参数拒绝上限后的恢复验证)拥有；三个候选保持待验证，生产未变，不增加正式 catalog、独立样本或 E2E 通过数。

## 首次合法引用修改的能力检查点

2026-09-23，按用户要求进一步扩大错误及相邻预算，优先验证工具编辑能力；沿用同一轨迹，不增加独立样本。新增 6 次请求、195,930 tokens、363.05 秒。模型又一次混用后合法提交旧稿，真实核验仍拒绝；重新读取资料后，首次正确调用独立引用工具，替换 c1 引用并保持正文及其他项，形成第 4 版。

按预声明在合法非空引用更新生效后停止，局部工具使用检查点通过，第 4 版语义支持未验证。累计范围投影 21/21；引用动作选择、执行及字段保护各 1/1；累计正文动作应用 2/6，之前失败不删除。不能据单次成功声明稳定恢复、缺证解除或产品 E2E 通过。累计 29 次模型请求、740,845 tokens，生产代码未变；判据与原始证据由[能力验证记录](../optimization/claim-field-tool-mixup.md#优先验证合法引用编辑能力)拥有，三个方案继续待验证。

## 宽限制下的完整研究循环验证

2026-09-23，从同一轨迹实际第 4 版续接，移除合法引用修改后的提前停止，预算和语义通过判据运行前固定。新增 30 次真实模型调用、975,462 tokens、1,510.63 秒；累计 59 次调用、1,716,307 tokens，仍只是一条连续 Offline 样本。新增 17 次研究决策无参数拒绝，累计参数范围投影一致 38/38，两类已应用编辑均保持其他字段和论断，9/9 次提交使用完整当前集合。

c1 已取得局部支持通过；模型最终合法修改 c2 引用，但第 15 版仍被拒。下一研究请求前的保守 token 预算预检停止，最新反馈未送达下一请求；没有完整语义通过，c3 支持与整个任务满足判断尚未到达。相同 c1 核验输入判定不同的问题单独记录，不能当成修订破坏已保留文本。生产未改、未运行单元测试或正式 E2E，未增加独立样本、catalog 或通过数。完整结果及证据由[第 145 节](../optimization/revision-feedback-loop.md#145-宽限制下的完整研究修订循环)拥有，候选继续保留。

## 复合论断拆分候选的连续离线验证

2026-09-24，从同一自然中文任务的第 15 版及尚未消费的第 9 次真实拒稿续接 1 条轨迹，未增加独立样本。隔离协议只新增 `split_claim` 及通用说明、合法消费；首次请求审计确认原有工具、证据 Context、服务配置和当前集合不变。新增 14 次真实模型调用、644,836 tokens、667.12 秒；累计 73 次调用、2,361,143 tokens。

模型在 9 次合法研究决策中没有选择拆分。第 22 版 c2 从 752 字扩至 1012 字，完整提交首先在已修改的 c1 被拒；第 23 版未再核验，下一请求触发预声明 token 预算预检。新增三次参数拒绝均未应用，其中一次误用首次创建动作、两次正文工具夹带引用。完整研究通过为 `0/1`，拆分执行和拆分后核验未到达，不能推断 c2 已通过或拆分机制失效。分类为隔离 Offline，不计 Product E2E、catalog 或发布分子；生产与汇总模型未改。决定性证据及后续判据由[第 146 节](../optimization/revision-feedback-loop.md#146-复合论断拆分工具的连续验证)和[问题候选](../optimization/to_verify/claim-multi-proposition.md)拥有。

## Verifier 复合论断反馈的隔离验证

2026-09-24，先在真实第 15 版全部三个 claim 上执行 Verifier 粒度判断。MiMo v2.5 的 3 次实际请求共 10,270 tokens；c2 被列为 3 项独立职责，c1、c3 分别列为 7 项、5 项。该固定稿件 Offline 只证明局部识别，不能据全部标为复合要求全部拆分。再从同一自然任务第 15 版与实际第 9 次拒稿连续续接：只增加对被拒 c2 的粒度反馈及通用字段说明，其余请求、工具和来源支持反馈一致，不计第二条独立样本。

研究模型先原稿提交；新的真实核验先拒绝 c1，随后研究模型收到 c1 的粒度反馈并合法拆为 c4 至 c10，c2、c3 原样保持。第 16 版完整复验先拒绝 c6 新增且无依据的工具定义细节；原 c2 未再核验，最新反馈也因预声明核验上限未送达下一研究请求。续接新增 11 次模型调用、220,371 tokens、584.26 秒；合并前置粒度判断共新增 14 次调用、230,641 tokens。完整研究仍为 `0/1`，正式 E2E、汇总与生产接入未执行，不增 catalog 或发布分子。动作消费和语义结果分别见[第 147 节](../optimization/revision-feedback-loop.md#147-verifier-粒度反馈的识别与连续消费)及[问题候选](../optimization/to_verify/claim-multi-proposition.md)。

## 缺证意见逐项定位的隔离续接

2026-09-24，同一自然中文研究任务的第 15 版及真实第 9 次拒稿继续用于 1 条隔离 Offline 轨迹，不增加独立样本。首次模型诊断返回两条对应意见，但原文引句仅因空白格式与稿件不一致而被拒，研究模型未收到反馈；该结果原样封存。恢复段复用同一模型响应，仅将原文定位校验改成忽略空白的连续子串比较。首个研究请求审计确认旧稿、旧来源支持反馈、工具 Schema、模型与证据 Context 保持。

研究模型先提交原稿，真实第 10 次核验通过 c1、拒绝 c2；新的三条诊断逐项定位缺证判断。之后模型四次修改 c2 正文、一次补读来源，未拆分或修改引用，第 19 版未再核验即触发 token 预算预检。两段合计新增 11 次模型调用、366,864 tokens；完整研究仍为 `0/1`。这只证明反馈定位与动作消费，不证明修订正确或用户交付；正式 E2E、汇总与生产接入未执行，不增 catalog 或发布分子。证据与责任边界见[第 148 节](../optimization/revision-feedback-loop.md#148-缺证意见逐项定位后的研究修订)及[封存审计](../../.tmp/claim-finding-scope-recovery-20260924/final-audit.json)。

## 同一研究轨迹续接到第 28 版仍未通过核验

2026-09-24，从上述真实第 19 版继续同一条中文研究任务 Offline 轨迹，四段有效续接新增 46 次模型调用、1,600,788 tokens；累计 116 次调用、3,683,959 tokens，样本仍为 `1`。模型后来自主拆分 c2、修改正文和引用并多次提交完整集合；第 22、24、27 版分别因拆后旧缺口、错误参数归属和新增无据细节被拒。第 28 版在原样未改的 c1 被拒；c1 的第 11 次与第 16 次来源支持实发请求相等，响应一过一拒，核验一致性另列。完整研究集合通过为 `0/1`；第 28 版后续单元没有得到该次支持核验，不能说它们已通过或被该次拒绝。正式 E2E、汇总模型、生产接入与用户最终结果均未到达，不增 catalog 或发布分子。机制、失败归因与原始归档见[第 149 节](../optimization/revision-feedback-loop.md#149-第-19-版后连续续接仍未使完整论断集合通过核验)及[同轨迹审计](../../.tmp/claim-trajectory-audit-20260924/summary.json)。

## 扩限续接到第 40 版仍未通过核验

2026-09-24，按用户要求继续扩大预算，沿同一条自然中文研究任务和真实第 28 版续接，并保留已应用的研究工具与 Verifier；没有独立重采样或正式 E2E。三段有效续接新增 32 次模型调用、1,354,021 tokens，累计 148 次、5,037,980 tokens，样本仍为 `1`。模型拆分 c1、调整引用和正文，真实第 17、18、19 次完整集合核验均被拒；第 17 与第 18 次对未修改 c6 的来源支持实发请求相同却给出相反判断。第 19 次拒绝 c6 新增的协议执行细节；第 40 版仅改过引用，尚未提交即到参数拒绝上限。完整研究集合通过 `0/1`，未进入汇总、正式 E2E 或生产接入，不增 catalog 或发布分子。第 128 次模型输出截断及一次无模型调用的脚手架准备失败均保留，未计为语义通过或独立样本。[第 150 节](../optimization/revision-feedback-loop.md#150-扩大预算后仍未取得完整研究集合通过)拥有过程归因，[连续审计](../../.tmp/claim-budget-extended-audit-20260924/summary.json)核对请求、响应与累计用量。

## 移除参数错误次数上限后的同轨迹验证

2026-09-24，从同一条自然中文研究任务的第 40 版及真实第 88 次参数错误续接；仅隔离 runner 移除参数错误累计停止，参数校验与反馈保持。模型下一步合法提交第 40 版，第 20 次核验通过 c6 后拒绝 c7 的三项缺证。之后模型多次改写 c7 并更新引用，新增参数错误没有提前终止循环；到第 53 版触发总调用预算，继续恢复后形成第 59 版但未提交。累计已完成 179 次模型调用、6,736,697 已知 tokens，仍为一条样本，完整研究集合 `0/1`。第 180 次请求只有实发输入，无服务响应或可核实用量；温和中断记录为服务调用未完成，成本未知，不计为语义核验。一次恢复脚手架断言在新模型调用前失败并独立封存，不增样本。正式 E2E、汇总和生产接入均未执行，不增 catalog 或发布分子。[第 151 节](../optimization/revision-feedback-loop.md#151-移除参数错误次数上限后的连续续接)保存因果边界，[最终中断记录](../../.tmp/claim-v53-no-parameter-cap-recovery2-20260924/result.json)与[前段结果](../../.tmp/claim-v40-no-parameter-cap-20260924/result.json)保存已知用量。

## 研究写作者 typed 提交的正式回归

2026-09-29，复用原中文 `test_conversation_research_review_001` 一例，正式 HTTP 入口与真实模型、工具、核验、完成链及既有评分不变。改动前[基线](../../.tmp/evidence-first-20260928/baseline/evidence/conversation-research-delivery-001/baseline/20260928T095242.832246Z-7448-4ba3bce0/CONVERSATION-RESEARCH-DELIVERY-001.1.trace.json)为 `0/1`：首次空 `create_claims` 与修复后的字符串引用都不符合 typed Schema，入口约 213 秒返回 503。target 仅更换注册研究写作者 Prompt；400 个封存代码文件中只此一处与基线不同，模型、JSON transport 和预算一致。没有运行 Offline Eval 或 `tests/`。

[target 原始 Trace](../../.tmp/claim-writer-contract-20260928/evidence/conversation-research-delivery-001/target/20260928T160958.989865Z-10284-fa6cb576/CONVERSATION-RESEARCH-DELIVERY-001.1.trace.json)结果仍为 **`0/1`**：入口 HTTP 200，1043.42 秒，23 次模型调用、17 个决策回合、25 次工具调用、794,181 tokens；预算耗尽后交付 `limitation`，没有答案，因此独立语义评分未运行。局部机制检查点为首次研究提交已建立 11 条论断、67 个对象引用，并进入实际来源核验；后续出现一次空 `add_claims`，结构修复成功后继续，未复现原 503。来源核验与继续取证未收敛，产品用户结果未通过；不同随机轨迹不作为正式消融或稳定性证明。[代码身份、命令和阶段归因](../../.tmp/claim-writer-contract-20260928/report.json)及[具体问题](../optimization/to_verify/claim-writer-typed-output.md)限定本次结论。不增加发布通过数。

## 2026-09-29 拆分与复合识别停用对比

同一中文 `test_conversation_research_review_001` 从空资料通过正式 HTTP 入口各运行一次。原始用户输入、身份、初始事实、评测器、模型 `mimo-v2.6-flash`、`json_object` transport、2,000,000 token／32 回合／48 工具预算、480 秒模型请求上限及 7,200 秒入口等待上限相同。生产代码差异仅为四个研究相关文件，合并移除了 `split_claim` 和复合论断识别 Verifier；两份归档的 checksum 均有效。[完整比较、代码身份和原始归档](../../.tmp/claim-no-compound-20260929/comparison.json)保存可复核数据。

| 正式样本 | 用户结果 | 入口耗时 | 最后提交的模型调用／决策回合／工具调用／tokens | 研究版本与 claim 数 |
| --- | --- | ---: | --- | --- |
| 停用前 | `0/1`，入口等待超时；未交付 | 7,200.03 秒 | 257／31／12／1,673,629 | 第 25 版，首版 12 条、最后 21 条；无实际拆分动作 |
| 同时停用后 | `0/1`，预算 `limitation`；未交付 | 3,336.47 秒 | 36／23／36／2,148,774 | 第 8 版，首版 8 条、最多及最后 22 条；无拆分动作 |

只读观察器在两层适配器各记录一次响应，下表按服务提供方响应 ID 去重；它包含最后提交之后已完成的请求，因此与上表 Journal 用量不同。停用后模型实际接收的 `ResearchSubmission` Schema 和 Prompt 均无 `split_claim`，服务端也没有结构识别请求。

| 已完成模型响应 | 停用前 | 同时停用后 |
| --- | ---: | ---: |
| 总数／tokens | 267／1,693,203 | 44／2,194,650 |
| 研究或动作决策 | 32 | 26 |
| 文档缺项识别 | 27 | 11 |
| 逐项来源支持 | 182 | 6 |
| 复合论断识别 | 25 | 0 |
| 意图识别 | 1 | 1 |

停用前运行在研究逐项支持阶段到达入口等待上限，未取得完整用户响应；停用后进入预算终态，研究版本仍在来源支持拒稿中，事实覆盖、独立汇总、最终核验均未到达。停用后有一次工具执行失败和一次模型传输重试，但入口最终停止原因是预算耗尽。第 6 版通过 `add_claims` 从 11 条增至 22 条，[原始版本审计](../../.tmp/claim-no-compound-20260929/duplicate-addition-audit.json)确认新增项中 6 条的正文及引用与原有项完全相同；这不是拆分动作，也不能凭近似文本分数认定其余项语义重复。

文档缺项识别的调用与正式拒绝须分别计数：停用前有 27 次已完成模型响应，但 25 个研究版本中没有 `source_coverage_rejection`；停用后有 11 次已完成模型响应（含重试），第 2–5 版各形成一次 `source_coverage_rejection`，合计 4 次，不是 11 次拒绝。逐项来源支持另有停用前 182 次、停用后 6 次已完成模型响应；停用后已提交的 5 条逐项结果为 2 条通过、3 条拒绝。因两条轨迹停在不同阶段，这些计数只说明当前样本的检查频率和阻塞位置，不能外推稳定触发率。

复合识别调用归零只证明停用在正式路径生效。两条独立随机轨迹停在不同阶段，且一次移除两个机制；总调用数、耗时、token 和 claim 数差异不能作为单机制因果收益或效率改善。两例用户结果均失败，不增加 Product E2E 或发布通过分子；本轮未执行 Offline Eval 或 `tests/`。未收敛问题与后续责任边界见[优化问题入口](../optimization/claim-revision-nonconvergence.md#2026-09-29-暂停拆分与复合识别的正式对比)。

## 2026-09-29 单条撤回与独立缺项识别暂停的正式 target

复用原中文 `test_conversation_research_review_001` 一例，从空资料经正式 HTTP 入口、生产 Composition Root、真实 MiMo、工具执行、研究核验及完成链运行。与上一轮同时停用拆分和复合识别后的样本相比，用户输入、初始事实、身份、评分器、`mimo-v2.6-flash`、`json_object` transport、2,000,000 token／32 回合／48 工具预算、480 秒模型调用上限和 7,200 秒入口等待上限相同。目标代码同时新增 `delete_claim` 并移除研究及普通 Final 的独立文档缺项分类、覆盖拒绝和专用充分性字段；[预声明与去重比较](../../.tmp/claim-delete-no-absence-20260929/comparison.json)保存代码身份、原始 Trace、Journal 及服务提供方响应。目标代码在测试期间未变化。

| 正式样本 | 用户结果 | 入口耗时 | 最后提交的模型调用／决策回合／工具调用／tokens | 研究版本及 claim 数 |
| --- | --- | ---: | --- | --- |
| 上一轮停用拆分与复合识别后 | `0/1`，预算 `limitation`，未交付 | 3,336.47 秒 | 36／23／36／2,148,774 | 8 版，首版 8 条、最多及最后 22 条 |
| 本轮新增撤回、暂停独立缺项识别后 | `0/1`，入口等待超时，未交付 | 7,200.01 秒 | 107／28／16／1,624,414 | 19 版，首版 7 条、最多及最后 8 条 |

只读观察器在两层适配器捕获响应，按服务提供方响应 ID 去重；该口径包含最后 Journal 提交后完成的请求，因此不与上表用量混算。

| 已完成模型响应 | 上一轮 | 本轮 |
| --- | ---: | ---: |
| 总数／tokens | 44／2,194,650 | 115／1,646,876 |
| 研究或动作决策 | 26 | 29 |
| 独立文档缺项识别 | 11 | 0 |
| 逐项来源支持 | 6 | 84 |
| 整组事实覆盖 | 0 | 1 |
| 意图识别 | 1 | 1 |

实发研究 Schema 与 Prompt 含 `delete_claim`，但本轮模型输出、正式准入和 claim 数下降均为 0；不能把“可调用”写成已验证的自然撤回。研究集合在前 18 版一直为 7 条，第 18 版全部 7 条逐项来源支持通过；整组事实覆盖随后把架构页 URL 未写入 claim 正文判为 `sufficient=false`，尽管已引用的执行记录含该来源地址。研究模型选择 `return_to_actions`，正式工具完成两次 `web_search`，第 19 版用 `add_claims` 补入架构页 URL 事实，集合增至 8 条，最后保存时 c1–c4 来源支持通过。最后一版没有正文与引用完全相同的 claim。独立汇总、最终语义核验与用户答案均未到达；没有以局部通过覆盖原始 `0/1`。

同一封存响应的[只读精确请求审计](../optimization/claim-verifier-consistency.md#已确认的事实)显示，84 次逐项来源支持响应对应 29 个不同的完整捕获请求，另 55 次重复既有请求；有 2 组同请求的可解析输出在空与非空 `findings` 之间变化。这是成本和一致性诊断，不裁定哪次判决正确，也不把缓存既往通过视作已获准修复。

独立缺项模型请求归零证明停用进入正式路径，但“余下核验是否阻止无据全文否定”因没有 Final 而未验证。两轮是不同随机轨迹，且本轮同时改变两个机制、停在不同阶段，调用次数、tokens、耗时和 claim 数差异不能作为单项因果收益。入口超时属于检查点之后的产品阻塞，不反证来源支持通过、覆盖发现 URL 缺口或独立分类归零这些局部事实。没有运行 Offline Eval 或 `tests/`；本轮不增加发布通过数。后续判断见[优化问题入口](../optimization/claim-revision-nonconvergence.md#2026-09-29-单条撤回与缺项分类暂停)。

## 2026-09-29 研究来源 URL 交接与事实覆盖职责复验

原正式失败在第 18 版已有 7 条来源支持通过的 claims。整组事实覆盖却以架构页 URL 未写入论断为由拒绝；同次 `web_read` 的 `source_url` 已是该架构页地址，而实发覆盖请求只有会话与 claims。对封存执行输入作只读确定性重建，24 条 `d8:*` 引用位置均能映射到该 URL。原入口等待超时、用户结果 `0/1`，不能把重建当作正式交付。

[首次来源绑定 target](../../.tmp/research-coverage-source-identity-20260929/evidence/conversation-research-delivery-001/target/20260929T152011.955994Z-29724-8752edb5/CONVERSATION-RESEARCH-DELIVERY-001.1.trace.json)复用同一中文自然请求、正式 HTTP 入口、生产组合根、真实模型及原语义评测器，原始结果仍为 `0/1`。该随机轨迹第 11 版 6 条 claims 的来源支持通过；覆盖请求携带 48 条 typed 来源绑定且返回 `sufficient=true`，独立汇总的 `ResearchBasis.sources` 也携带相同绑定。生产最后返回 `answer`，正文包含所引用的两个官方 URL。入口耗时 2,959.51 秒，生产记录为 74 次模型调用、23 个决策回合、14 次工具调用和 659,920 tokens。此轨迹的 claims 本身也写有 URL，故不能据覆盖通过证明来源绑定改变了模型判断；两个独立随机轨迹也不构成成本消融。

首次 target 的独立语义评测没有返回有效 typed 判决：前两次结构化输出在 1,200-token 上限处截断，第三次缺少必填字段，重试耗尽。原始 `delivered=false` 和 `pytest` 失败保留；生产 `answer` 与 URL 出现只证明交接检查点，不证明答案语义满足用户。静态 `concept_coverage` 为 `1/3`，`source_coverage` 为 `2/2`；该用例有独立语义结果契约，静态指标仅供诊断，不参与 `delivered` 判定。URL 存在性仍曾交由覆盖模型判断，因此后续目标代码将其移出事实覆盖判据，只保留确定性来源投影给汇总。后续 target 单独归档和计分，不覆盖本次失败。

[事实覆盖职责 target](../../.tmp/research-coverage-fact-scope-20260929/evidence/conversation-research-delivery-001/target/20260929T162606.084974Z-18944-eb22e78f/CONVERSATION-RESEARCH-DELIVERY-001.1.trace.json)继续使用同一中文请求、正式入口、真实模型、原用户结果契约与生产预算；目标代码的覆盖请求只含会话与 claims，URL 仍由执行记录投影到通过后的 `ResearchBasis.sources`。该次结果为 `0/1`：入口耗时 3,439.32 秒，在 32 个模型决策回合后返回预算 `limitation`，没有用户答案。最后保存 21 个研究版本，首版及末版均为 10 条 claims；生产用量为 120 次模型调用、11 次工具调用、1,663,679 tokens。只读捕获按服务提供方响应 ID 去重后有 90 次逐项来源支持响应，覆盖请求为 0，独立汇总和最终核验均未到达。该轨迹证明修正后的前置研究链实际运行，却未触发 URL 阶段判据或结构化汇总，不能计为本轮机制通过。失败位置在前置逐项支持与修订循环；与首次 target 的独立评分故障分别归因。两个 target 都不增加发布通过数，也不能按不同随机轨迹计算 URL 改动的调用成本收益。

[逐项请求与版本的只读审计](../../.tmp/research-coverage-fact-scope-20260929/repetition-audit.json)显示，90 次来源支持响应仅有 28 个不同的完整请求，另 62 次精确重复；5 组相同请求同时出现通过和拒绝。20 次版本变更每次只修改一条 claim，数量没有膨胀；已保存的核验最多到 c8，无法稳定推进到 c10 与整组覆盖。这是与 URL 交接独立的前置收敛阻塞；输出冲突本身不裁定哪次判断正确。[一致性问题](../optimization/claim-verifier-consistency.md#已确认的事实)拥有后续归因，不在本次 URL 修复中追加缓存或跳过核验。

## 2026-09-30 evidence-first 恢复与有界修正

用户要求恢复从原始问题选证后写作的生产路径，并继续优化来源核验范围。[预声明](../../.tmp/evidence-first-restored-20260930/plan.json)固定既有中文自然请求、正式 HTTP 入口、生产 Composition Root、真实 `mimo-v2.6-flash`、思考开启、原独立结果评分器及 2,000,000 tokens / 32 回合 / 48 工具预算。`split_claim`、复合识别和独立文档缺项识别继续停用，单条删除仍可用；新增机制阶段检查不改变完整用户结果通过条件。

环境准备先遇 Windows 保留端口 `15354–15453`，旧数据库端口 `15432` 无法绑定。四次 setup 失败均未进入正式产品场景，不计产品失败轨迹。保留同一 PostgreSQL 数据卷，将真实宿主端口改为 `16432`；共享 HTTP E2E 由 `PERSONAL_AGENT_E2E_POSTGRES_URL` 统一指定连通检查、服务进程及测试库清理端点，清理仅允许 `personal_agent_test`。没有修改评分器、模型或生产默认配置，也没有修改或执行 `tests/` 的测试；复用其只读数据库准备基础设施。端点差异与源码身份均封存，不将该环境恢复计为产品优化收益。

[首轮正式 target](../../.tmp/evidence-first-restored-20260930/target-database-owner/evidence/conversation-research-delivery-001/target/20260930T064750.691471Z-24128-26ebcfb0/CONVERSATION-RESEARCH-DELIVERY-001.1.trace.json)为 `0/1`，在 32 个决策回合后返回预算 `limitation`，无用户答案；入口耗时 4,534.48 秒，pytest 为 4,546.32 秒。生产总账为 115 次模型调用、20 次工具调用和 1,813,606 tokens；[按响应 ID 去重的审计](../../.tmp/evidence-first-restored-20260930/target-database-owner/audit-all-provider.json)有 121 次 Provider 完成，差额为结构修复，总 tokens 与总账一致。源码执行期间未变化。末版为第 14 版、7 条 claims，首版为 6 条；两次逐项来源支持通过后到达事实覆盖，覆盖反馈推动模型补读 output schema 条款并加入校验分工，后一次仍拒绝未回答的权限／授权主体与配置层归属。没有到达独立汇总、最终核验及完整 URL 交付。停用三机制均零调用，删除没有被模型选择。

与前次来源 URL 职责 target 相比，本轮到达事实覆盖、claim 数较少；完整用户结果仍失败。模型、思考开关、预算及评分契约保持，但同时恢复选证、校准来源范围并使用不同随机轨迹，不能把调用数或耗时变化归为任何单项因果收益。固定输入范围校准为 8 样本 × 2 重复 × 2 版本，共 32 次真实调用；旧版 14/16、新版 16/16，用量 68,395 tokens，只证明这组局部判别。正式来源核验仍有 3 组相同输入的冲突，具体归因由[一致性问题](../optimization/claim-verifier-consistency.md#2026-09-30-断言范围校准)拥有。

首轮还暴露两项既有契约恢复缺陷：[有界修正](../../.tmp/evidence-first-restored-20260930/bounded-fix-plan.json)删除对每项引用的无条件非空检查，保持选中子集与语义核验；选证 Prompt 明确对象引用形状并升级 `v3-reference-objects`，Adapter 不转换字符串。[实际首稿回放](../../.tmp/evidence-first-restored-20260930/bounded-admission-replay.json)接纳原 6 条集合，实际未选引用仍被拒绝；它只证明 Admission 边界，不是新 Product E2E。同一失败选证请求的两次真实模型回放均通过形状校验，均无结构修复，共 61,995 tokens；后续[坐标审计](../../.tmp/evidence-first-restored-20260930/selector-replay/audit.json)发现两份范围都包含未返回行，真实引用绑定为 `0/2`，不把形状通过记为有效选证。

第二轮 target 因继续消息切换而中断，[封存记录](../../.tmp/evidence-first-restored-20260930/target-bounded-fix/interrupted-result.json)保留执行身份及校验和；源码执行期间未变化，没有正式结果、用户答案或完成的失败判决。已提交总账为 100 次模型调用、28 回合、12 次工具和 1,069,083 tokens，第 19 版为 9 条 claims，事实覆盖零次；末尾在途 Provider 用量未知，不记零用量，也不加入完成样本分母。

第二轮实际研究写作请求同时含“直接交付用户正文”的 Schema 描述和“不写最终文章”的研究指令。[阶段契约预声明](../../.tmp/evidence-first-restored-20260930/stage-schema-plan.json)把创建、增补及 canonical 研究正文统一迁入 `ResearchClaimContent`；仅覆盖 text 描述，不改字段、最终答复类型或核验判据，writer 为 `v9-research-content`、指令正文不变。[同一实际输入的比较审计](../../.tmp/evidence-first-restored-20260930/schema-probe/audit.json)已完成旧、新 Schema 各两次，全部实际输出连续经过准入与来源支持。旧 Schema 与封存实发 Schema 完全相同，业务消息和写作模板保持；12 次 Provider 完成共 55,030 tokens，无结构修复。准入为 `4/4`，完整来源支持为 `0/4`；旧版 claim 数为 5、10，首个拒绝分别在 c1、c3，新版为 5、8，均在 c2 被拒。无据全文否定、加载工具的主体扩大有明确拒绝依据；否定式能力／实现分类存在语义争议，未预标全部正确或错误。未到达的后续 claims、覆盖、汇总及最终结果不计通过；此比较不证明收敛或成本收益。新的同入口 target 单独计分，完整用户结果未通过前候选不迁入 completed，不增加发布通过数。

[研究正文契约 target](../../.tmp/evidence-first-restored-20260930/target-research-content/evidence/conversation-research-delivery-001/target/20260930T100257.425527Z-20616-3a33d93c/CONVERSATION-RESEARCH-DELIVERY-001.1.trace.json)已完成，仍为 `0/1`，返回连续无效动作的 `limitation`，没有用户答案。入口耗时 1,002.019407 秒，25 次模型调用、13 回合、11 次工具、497,921 tokens；Provider 去重计数及已知 tokens 与生产总账一致，无结构修复、无长度截断。执行期间源码未变。第 1、2 版均为 6 条 claims；先补读授权与结果 schema 条款再创建，c2 的 401 条件及安全原则范围修复后 c1-c3 来源通过。c4 复述分工却漏引实际支持行，来源拒绝有据；随后补引和正文修订均因未选 `d4:34` 被确定性拒绝，触发既有重复反馈停止。覆盖、汇总、最终核验未到达。[审计](../../.tmp/evidence-first-restored-20260930/target-research-content/audit.json)为 6 次来源支持、5 个不同请求、1 次重复、0 个已观察冲突；小样本和提前停止不证明一致性或成本收益。Trace 自动标注的 earliest_failure 把第一条正常补证反馈列为 blocked，不能据此归因本次停止；上述归因消费了实际后续轨迹。

该 target 三次准入拒绝只返回通用错误，未指出实际集合差；在当前版本进展后，c4 两次同类拒绝结束交互。[坐标反馈修正预声明](../../.tmp/evidence-first-restored-20260930/coordinate-feedback-plan.json)只把确定性未选坐标加入现有错误消息，保持拒绝判据、停止次数、Prompt、预算及评分器。原实际拒绝回放后仍拒绝，进一步用同一实际下一轮请求的准确反馈连续验证真实选证、写作及核验；完整目标单独以新的真实入口运行，不将条件局部结果计为产品通过。

[坐标反馈连续验证](../../.tmp/evidence-first-restored-20260930/coordinate-probe/audit.json)为同一实际输入两次真实选择与写作：两次都绑定有效坐标并补选原缺失 `d4:34`，实际编辑都准入。第一条轨迹删除 c4，集合由 6 降为 5，复验在 c3 的 call_id 范围拒绝处结束；第二条补引 c4、保留 6 条，在 c2 的对照排他解读处结束，尚未自然核验到 c4。完整来源支持为 `0/2`，覆盖、汇总及用户结果未执行。相同 c2 实发 messages 和 Schema 与正式通过请求一致，局部重放却出现三次空 JSON 长度截断；同一请求的返回稳定性问题独立于本次反馈修正。未把删除后的覆盖或补引后的 c4 来源支持记成通过。

该局部验证共 9 次 typed 操作、13 次 Provider 完成，实际已知用量 224,770 tokens，在预声明 240,000 上限内；Adapter 仅报告 200,590，相差 24,180，恰为第一次 c2 失败操作中的两条响应用量。`_generate_structured` 在聚合 usage 前直接抛出异常，外层重试仅携带最后成功操作的用量，因此该分支还存在计量缺陷。此次没有改重试或预算判据，完整计数以[原始响应审计](../../.tmp/evidence-first-restored-20260930/coordinate-probe/audit.json)为准；不得使用 Adapter 小计宣称成本降低。

[坐标反馈正式 target](../../.tmp/evidence-first-restored-20260930/target-coordinate-feedback/evidence/conversation-research-delivery-001/target/20260930T111937.645981Z-24840-b70d8b46/CONVERSATION-RESEARCH-DELIVERY-001.1.trace.json)已完成，仍为 `0/1`，在连续两次无效片段修订后返回 `limitation`，没有用户答案或入口异常。入口耗时 1,962.639348 秒，pytest 为 1,975.77 秒；35 次生产模型调用、14 回合、11 次工具、481,325 tokens。[去重审计](../../.tmp/evidence-first-restored-20260930/target-coordinate-feedback/audit.json)为 38 次 Provider 完成，包含结构修复，总 tokens 与生产总账一致；本次未触发前述计量缺陷分支，不证明该缺陷已修复。源码执行期间未变，归档校验和已封存。

集合从第 1 至第 5 版均为 7 条 claims，无拆分或新增膨胀。真实拒绝反馈明确列出未选 `d6:32`，随后选证补齐并准入 c2 修订，第 5 版 c1-c3 来源通过，推进到 c4；这证明准确坐标已由生产修复消费者使用。c4 的 call_id 强制化和“只规定了”穷尽列举有实际来源拒绝依据，随后两次 `old_fragment` 把正文中的直引号 `"` 改成弯引号 `“”`，都不能精确匹配，未产生第 6 版。两次实发写作请求包含完整 canonical c4，输入没有丢失或改写引号；字符对照只用于诊断，没有规范化被拒动作。[责任边界审查](../../.tmp/evidence-first-restored-20260930/target-coordinate-feedback/boundary-review.json)封存同一实际选证、编辑、反馈及完整请求对照。研究事实覆盖、独立汇总、最终核验及答案评分均未到达。

14 次来源支持响应对应 10 个不同完整 messages、4 次重复，有 1 组先通过后拒绝；已进一步确认该组的完整观察器请求对象相等。call_id 拒绝有据，先前判决漏放；另一项将已描述应用流程中的分工推导读成任何场景的普遍否定，存在范围误读。整项仍有前一支持缺口，不将部分误读写成整项应该通过。拆分、复合识别和独立缺项识别仍零调用，删除没有在本次正式轨迹中被选择。两次独立随机 target 的调用、耗时或 tokens 差异不是成本消融。

## 2026-10-01 重试计量与研究设计接入

用户授权修复失败重试用量漏计并落地未收敛问题下其他设计。本轮[预声明](../../.tmp/research-convergence-integration-20261001/plan.json)与[设计盘点](../../.tmp/research-convergence-integration-20261001/design-inventory.json)区分已接入、需补齐及按用户停用的机制。实际改动为重试计量、版本绑定片段地址及本轮引用/身份 Schema 范围；模型、thinking、transport、预算、错误停止阈值、来源 Verifier 与原用户评分保持一致，身份比较见[配置审计](../../.tmp/research-convergence-integration-20261001/target/baseline-comparison-identity.json)。

局部责任回放使用真实归档响应和失败正文：[计量回放](../../.tmp/research-convergence-integration-20261001/usage-replay.json)四个边界通过，补齐 24,180 tokens；[片段回放](../../.tmp/research-convergence-integration-20261001/fragment-replay.json)两条给定 ID 动作与七类拒绝控制通过。它们是历史失败的条件局部证据，原模型自主寻址由正式入口运行验收。机制与责任分别由[重试计量](../optimization/completed/model-retry-usage.md)、[正文寻址](../optimization/completed/claim-fragment-addressing.md)及[参数范围](../optimization/completed/claim-argument-scope.md)完成记录拥有。

正式 `evals/product_baselines/test_conversation_research_review_001.py` 显式收集并运行 1 项，按相同中文自然表达、空资料、真实模型和生产 Composition Root 完成 1×1 target。[原始结果](../../.tmp/research-convergence-integration-20261001/target/evidence/conversation-research-delivery-001/target/20260930T233710.680926Z-19684-2433e540/CONVERSATION-RESEARCH-DELIVERY-001.1.trace.json)仍为 `0/1`：入口没有异常，在第 30 个决策回合因连续无效研究动作返回 `limitation`，无用户答案。入口耗时 3,897.462197 秒，pytest 为 3,915.18 秒；生产总账为 97 次模型调用、13 次工具调用和 1,618,551 tokens。97 次实际 Provider 完成的输入 1,418,732、输出 199,819 及 total 与 Journal 全部相等。本轨迹没有结构修复或外层重试，历史漏计分支由前述固定响应反事实验收。执行期间源码保持，完整计数见[最终审计](../../.tmp/research-convergence-integration-20261001/target/final-audit.json)。

[实发视图审计](../../.tmp/research-convergence-integration-20261001/target/writer-view-audit.json)核对 20 次写作请求：视图逐字重建当前正文、无第二份完整正文或模型偏移，Schema 的当前 claim、片段和所选证据范围匹配实际输入。[生产动作消费](../../.tmp/research-convergence-integration-20261001/target/admitted-fragment-audit.json)核对模型自主提交的 12 次片段 ID 修订，范围外正文、引用和其他 claim 精确保留，12 份新完整正文均到达来源支持消费者。首版至第 15 版一直为 5 条 claims，无数量膨胀；末版 c1-c4 来源通过，c5 因所引证据未支持其 Agents API 文档存在性括注而拒绝。完整事实覆盖、独立汇总、最终核验与独立用户评分均未到达。拆分、复合识别和独立缺项识别仍零调用，删除没有被模型选择。

[末端责任审计](../../.tmp/research-convergence-integration-20261001/target/terminal-boundary-audit.json)保存第 29、30 回合实际选证、写作和反馈：两份动作的当前 `base_ref` 及 `c5.f11` 首尾 ID 均合法，正文修改保留原引用，但本轮选证未覆盖所有保留引用。第 29 回合缺 11 个坐标，第 30 回合补齐其中 10 个后仍漏 `d4:1074`，两次准入拒绝均零写入，第 16 版未生成。给定全部已返回保留引用时，同一实际 ID 动作可绑定；这是确定性责任边界回放，未注入正式运行，也未计语义通过。最早未恢复边界为选证与保留引用的修订交接，既有准确坐标反馈和停止次数均保持。

[来源完整请求审计](../../.tmp/research-convergence-integration-20261001/target/source-consistency-audit.json)计 46 次来源响应、19 个不同观察器请求、27 次精确重复及 3 组通过／拒绝冲突；1 份原始输出在 JSON 后附加内容，未计原始语义判决。比较包含 method、operation、version、messages、Schema 和 extra_body，不宣称全部 HTTP 字节相等。一致性归因由[对应问题](../optimization/claim-verifier-consistency.md#2026-10-01-真实接入复验)拥有。相比前次坐标反馈 target，实际 ID 修改推进到第 15 版及 c5，但调用数和耗时更高，完整用户结果同为失败；两条独立随机轨迹且本轮接入三项机制，不构成任何单项成本消融。

## 2026-10-01 修订引用继承与 Verifier 审查

本轮先恢复 evidence-first 修订中的已有引用契约，再只读审查 Verifier。原正式入口第 29、30 回合的两份合法 ID 动作，因保留引用没有在本轮全部重选而被拒。[原失败反事实](../../.tmp/research-retained-reference-repair-20261001/retained-replay.json)保持实际动作、选择与来源：旧检查拒绝 2/2，现行准入接受 2/2；新增未选引用、其他 claim 引用、缺行范围及不可见来源四项拒绝边界保持零写入。回放新增模型调用为 0，不计 Product E2E。机制由[引用继承完成记录](../optimization/completed/claim-retained-references.md)拥有。

原 `evals/product_baselines/test_conversation_research_review_001.py` 显式收集并运行 1 项，以原中文自然表达、空资料、正式 `POST /api/conversation/turn`、生产组合根及真实模型执行 1×1 target。[预声明](../../.tmp/research-retained-reference-repair-20261001/plan.json)和[冻结身份](../../.tmp/research-retained-reference-repair-20261001/target/identity.json)固定 `mimo-v2.6-flash`、thinking 开启、JSON Object、来源模板 v3、2,000,000 tokens／32 决策回合／48 工具预算、480 秒单次模型超时、7,200 秒入口等待，以及原用户结果和独立语义评分。改动为 3 个生产文件、净增 10 行，新增持久字段、模型、Port、生产开关及投影额外模型调用均为 0；eval 代码未变，运行期间源码保持。

[原始正式结果](../../.tmp/research-retained-reference-repair-20261001/target/evidence/conversation-research-delivery-001/target/20261001T023242.633029Z-15204-6de0044f/CONVERSATION-RESEARCH-DELIVERY-001.1.trace.json)为 `0/1`，disposition=`None`，入口错误为 `{'message': 'timed out', 'status': None, 'type': 'TimeoutError'}`。入口耗时 7200.0403 秒，完整运行 7230.68 秒，进程退出 1；原始失败保留，不由机制检查点覆盖。研究首版 9 条、末版 9 条，共 13 版；事实覆盖请求 0 次。最终消息和独立评分是否执行、末端审核及反馈均逐字保存在[最终审计](../../.tmp/research-retained-reference-repair-20261001/target/final-audit.json)，未到达阶段不计通过。

末端位置是第 13 版 c1 的来源报告恢复：第一次响应长度截止且正文为空，恢复请求尚未返回时入口等待到限；本版 c1 没有有效判决。最后已提交审核为第 12 版 c1、c2 空 findings，c3 因对“相关要求”范围的全称解读被拒，随后模型合法修改 c3 形成第 13 版。第 11 版曾推进到 c6，其服务器／宿主校验分布及原文否定被拒；本次最多核验到 c6，c7-c9、事实覆盖、独立汇总、最终核验及独立用户评分均未到达。没有把在途空正文称为语义拒稿，也没有发生继承引用重选的准入阻塞。

[实际 writer 审计](../../.tmp/research-retained-reference-repair-20261001/target/writer-view-audit.json)核对 13 次请求，其中 10 次收到未重选的已绑定原文，目录与 Schema 使用相同坐标范围。[实际修订消费](../../.tmp/research-retained-reference-repair-20261001/target/admitted-fragment-audit.json)核对 11 次片段修改，范围外正文、引用和其他项保持；9 份新完整正文到达来源核验，5 次修改保留未全部重选的目标引用。第 4 版 c1 保留 2 个未重选引用而合法修订，旧检查会拒绝，是正式生产消费者的决定性反例。另有 1 次引用修改，新增坐标经过选择。

最后已提交 Journal 保存 59 次 typed 操作、19 决策回合、10 工具，输入 920759、输出 256995、total 1177754 tokens。Provider 响应 ID 去重计 76 份完成响应，输入 922884、输出 265187、total 1188071；逐分项与最后 Journal 对齐为 `False`，整体对齐检查没有通过。差额 10,317 tokens 全部来自最后提交之后的 `0147` 长度截止响应：该 typed 操作正在 `0149` 格式恢复中被入口超时中断，尚未返回或提交；提交前响应合计与 Journal 三项精确相等。未完成请求的额外消耗未知，不填零用量，不将最后快照写成完整终态账。物理响应和 typed 操作的计数单位不同，内部修复及重试聚合为一次返回。[自然恢复审计](../../.tmp/research-retained-reference-repair-20261001/actual-retry-usage-audit.json)中，六份真实完成响应的 56,167 tokens 全部进入一次 typed 操作的 Journal 增量。

[原始 SDK 来源审计](../../.tmp/research-retained-reference-repair-20261001/target/sdk-source-report-audit.json)含现有内部修复及重试，共 42 份完成、23 个不同完整 kwargs，另 19 次精确重复；可解析空报告 14 份、非空报告 12 份，不可解析 16 份，其中长度截止 16 份、空正文 15 份。2 组完整 SDK 输入同时出现有效通过／拒绝，5 组同时出现有效报告／不可解析输出；两类分别计数，原始结构失败没有语义判决。全部实发来源请求 thinking 开启，原始 reasoning 保留。历史三组共七份实际响应及本轮新增冲突的语义归因由[判决边界审查](../optimization/claim-verifier-consistency.md#2026-10-01-修订修复后的判决边界审查)拥有；分析额外模型调用为 0，生产 Verifier 未改。

拆分、复合识别和独立文档缺项识别继续停用，单条删除保持可用；不以可调用代替自然使用证据。前次同任务为 0/1、3,897.462197 秒、1,618,551 tokens；本次为另一条随机轨迹，结果、时间和成本只作描述，不作为单项收益消融。原用户结果未通过时不增加发布分子。未运行 unit 或 `tests/`；实际命令、源码身份、文档检查及完整原始归档见[本轮报告](../../.tmp/research-retained-reference-repair-20261001/REPORT.md)。


## 2026-10-01 来源报告复用与结构化修订反馈

按[预声明](../../.tmp/research-source-reuse-repair-20261001/plan.json)只运行原 `evals/product_baselines/test_conversation_research_review_001.py` 的一个样本一次。原中文自然表达、空资料、正式 HTTP、生产 Composition Root、真实模型与工具及原独立评分保持；`mimo-v2.6-flash`、thinking 开启、JSON Object、2,000,000 tokens／32 回合／48 工具、480 秒模型超时／7200 秒入口等待与上一 baseline 一致。生产改动仅两项机制涉及的 5 文件，净增 144 行；2 个反馈契约模型、1 个瞬时投影、1 个报告版本字段，无新模块、Port、持久缓存、开关或每次编辑的额外模型轮次。运行期间源码及 eval 身份保持。

[原始正式结果](../../.tmp/research-source-reuse-repair-20261001/target/evidence/conversation-research-delivery-001/target/20261001T060858.358399Z-15980-965eb4df/CONVERSATION-RESEARCH-DELIVERY-001.1.trace.json)为 `0/1`，pytest `1 failed`（5246.44 秒），正式入口 5042.256882 秒返回 `answer`，无入口异常。7 条 claims 保持 13 版，19 次来源模型请求均形成合法报告，第 13 版完整研究覆盖通过；3 次独立汇总稿及 3 次最终核验后形成有效通过 receipt，Completion 接受同一稿。原独立 grader 的 6 份响应全部 `length`、空正文，每份输出额度 1200；未形成有效评分，不算答案语义拒绝，也不把内部通过改写为用户 E2E 通过。[完整审计](../../.tmp/research-source-reuse-repair-20261001/audit.json)保留原断言及原始评分失败。

生产 Provider 完成 66 次，输入 1,052,518、输出 142,461、total 1,194,979 tokens；独立 grader 6 次共 32,346 tokens，总已完成用量 1,227,325。Journal 为 62 次 typed 操作、28 回合、23 工具和 1,143,604 tokens。直接模型的 63 份响应与 Journal 三项相等，3 次最终核验工具的 51,375 tokens 未交回总账，见[成本逐分项审计](../../.tmp/research-source-reuse-repair-20261001/cost-audit.json)及[独立用量问题](../optimization/tool-model-usage-handoff.md)。本次所有已发请求已完成，不把差额归为在途请求。

真实修订反馈被 12 次 writer 请求消费；12 次修改均核验完整新 claim，其中 9 次正文片段修改、3 次引用修改。来源报告复用的责任边界由[固化记录](../optimization/completed/claim-source-review-reuse.md)拥有；支持范围反馈的收益、再次新增无据声明和后续设计由[候选结果](../optimization/to_verify/claim-supported-scope-repair.md#已观察结果与下一边界)拥有。最终前两份报告的验收项转录失败由[独立问题](../optimization/completed/final-criterion-transcription.md)拥有。拆分、复合识别和独立缺项识别继续零调用，删除未被选择。

与上一封存正式轨迹相比，来源物理完成 42→19，生产完成 76→66；从未到达覆盖与最终稿，推进到返回答案。生产已知 tokens 1,188,071→1,194,979，未下降；决策回合 19→28，工具 10→23；前次入口超时7200秒，本次返回5042秒。两次独立随机轨迹且本轮两项机制一起变化，以上只是描述，不作为成本或延迟的单变量消融。原用户结果两次均 `0/1`。本轮不运行 `tests/`，实际命令、脚手架修正、全部代码身份及检查由[封存报告](../../.tmp/research-source-reuse-repair-20261001/REPORT.md)拥有。


## 2026-10-01 独立评分器输出预算恢复

用户授权“如果需要则扩大预算”。本次仅调整 `evals/e2e_quality/research_answer_outcome.py` 的请求版本和输出上限：v5／1200 → `research-answer-task-support-zh-v6-thinking-budget`／32768。Prompt、Schema、通过条件、原用户输入、原完整答案、原参考集、模型、thinking 开启、JSON Object、重试与480秒模型超时保持。src 及其他 eval 文件字节未变；改动1文件2行，无新增生产结构、字段或开关。计划与独立身份见[本轮预声明](../../.tmp/research-grader-budget-20261001/plan.json)。

[真实原请求诊断](../../.tmp/research-grader-budget-20261001/diagnostic/result.json)为1样本×1次，通过正式共用评分器消费上一 E2E 真正交付的完整答案。完整 SDK 参数除 `max_completion_tokens: 1200 → 32768` 外逐字段相同。[实发审计](../../.tmp/research-grader-budget-20261001/audit.json)记录1次 Provider完成，`stop`，有合法评分，无修复和重试；40.221784秒，输入4157、输出5117、总9274tokens，其中服务方记录推理4204tokens，原始reasoning保留。报告可完成性为1/1，语义通过为0/1；两者分别计分。原v5六次`length`空正文及正式E2E 0/1不追溯改写。

有效报告指出客户端结果校验、服务器安全要求等缺项，但同时对参考集中没有的 `tools-connectors-mcp` 和 MCP规范入口判缺确认依据，并把 `strict`、`allowed_tools` 等细节列为必交付项。人工审查区分用户相关缺项、参考覆盖不足、额外验收要求及句内/全页范围差异；具体判据由[资格问题](../optimization/completed/research-grader-qualification.md)拥有。没有把这份报告的所有意见直接裁定为生产错误。

按预声明及 QLT，在出现独立评分资格问题后停止新增付费样本；相邻控制0/2、新正式target 0/1，均未执行。此次是原失败评分责任边界恢复，不是第二条研究 Product E2E；没有重新运行生产研究、修改评价规则或答案。本次固定输入恢复已证明预算修复，机制见[固化记录](../optimization/completed/research-grader-output-budget.md)。实际命令、源码身份和静态检查见[本轮报告](../../.tmp/research-grader-budget-20261001/REPORT.md)，当前发布分子保持0。


## 2026-10-01 评分资格候选的范围归类反例

本轮评测层候选 `research-answer-task-support-zh-v7-goal-grounded` 尝试缺项绑定用户原话、人工事实摘要替换为五页带坐标官方原文、将评分依据缺口与已确认错误分离，并在共用 E2E 消费者记录三态。生产 src、原中文 goal、mimo-v2.6-flash、thinking 开启、32768 输出额度及生产预算保持。完整预声明、候选代码及原始输入由[本轮报告](../../.tmp/research-grader-qualification-20261001/REPORT.md)拥有。

[真实模型资格结果](../../.tmp/research-grader-qualification-20261001/diagnostic/summary.json)执行 2/9：完整正例语义通过；旧真实答案被判 failed，核心缺项仍为客户端校验和服务器访问控制，但范围归类审查失败。资格正确 1/2；8 个控制执行 1/8，旧实际答案执行 1/1。两次均 stop、无重试，总 44,770 tokens；分别为 18,357／52.750807 秒与 26,413／209.301891 秒。每个实际请求只含原目标、实际答案和参考原文，人工标签与生产核验结论未入模型。

报告将评分者可见整页误用于作者引用片段的范围，错误判取证声明；还为答案已经明确保留的未知列出评分缺证。预声明首个资格反例后停止：剩余 7 个控制及新正式 E2E 0/1 均未执行。未改标签、增加预算、重跑或叠加同向 Prompt 补丁。3 个 eval 源码和 2 个 fixture 已[逐字恢复本轮开始前工作树](../../.tmp/research-grader-qualification-20261001/rollback.json)，候选源码在独立归档中保留，现行评分器为 v6，资格问题继续开放。

Ruff、规范、候选校准收集、正式目标单项收集、影响路由与范围文档检查分别记录，不将静态通过写成语义通过。原评分与 Product E2E 0/1 身份保持，未执行新的研究产品轨迹或停用单元测试。下一边界见[评分责任复核](../optimization/completed/research-grader-qualification.md)。

## 2026-10-01 用户事实逐项覆盖与停止研究

按[预声明](../../.tmp/research-goal-coverage-20261001/plan.json)修复既有覆盖漏放，3 个生产文件净增 16 行：逐项问题、当前 claim、状态和反馈替换平坦布尔报告，整体充分性由 Runtime 推导，writer 消费该唯一契约。未增加模块、Port、持久缓存或每次编辑的模型轮次。4 个固定局部控制各执行一次，判决正确 4/4，共 12,703 tokens、127.259119 秒；来源已通过为条件，实际请求与范围由[局部审查](../../.tmp/research-goal-coverage-20261001/offline-review.json)拥有。

局部资格成立后，原 `evals/product_baselines/test_conversation_research_review_001.py` 的正式中文自然表达、空资料、HTTP 入口、生产 Composition Root、真实模型及工具连续运行一个样本一次。`mimo-v2.6-flash`、thinking 开启、JSON Object、480 秒模型超时、2,000,000 tokens／32 回合／48 工具与7200秒入口等待保持；原用户结果、v6 grader 和暂停机制未改。[正式结果](../../.tmp/research-goal-coverage-20261001/target/evidence/conversation-research-delivery-001/target/20261001T141624.219242Z-12972-25805fc1/CONVERSATION-RESEARCH-DELIVERY-001.1.trace.json)为 **0/1**，pytest `1 failed`、2898.79 秒；入口无异常，2883.047997 秒返回 `limitation`，未交付 `answer`，grader 未执行。

10 条 claims 保持到第 15 版。第 14、15 版各有 8 项覆盖报告，均因 OpenAI 侧自动 schema 校验行为尚未取得证据而不足。4 次 selector 与 2 次 writer 请求收到逐项反馈，补查 4 次后 c7 合法修订并取得来源支持；最后 writer 提交 `stop_research`，理由却要求交给成文。Runtime 按既有动作契约返回限制消息，未进入独立汇总和最终核验。目标细化范围、未知满足条件及停止动作的责任审查见[候选结果](../optimization/to_verify/research-goal-coverage.md#2026-10-01-实际消费与停止边界)，局部反馈消费不计为用户通过。

Provider 响应 ID 去重完成 72 次，其中来源核验27、覆盖2；来源报告11份空 findings、13份非空 findings，另3份 length 空正文没有语义判决。生产输入1,046,295、输出135,551、total **1,181,846 tokens**，与最终 Journal 三项精确相等；Journal 计69个 typed 操作、26回合、12工具。运行未耗尽累计预算或入口等待；全部请求 thinking 开启，原始 reasoning 保留。与上一正式轨迹的调用、耗时和成本差异仅作描述，两条随机轨迹不构成消融。

源码在运行期间保持，原 eval 未变，暂停的 split、复合识别与独立文档缺项识别均未调用。Ruff、编译、分层、规范、差异及文档检查见[本轮报告](../../.tmp/research-goal-coverage-20261001/REPORT.md)。本次影响路由要求完整矩阵；只执行原 target 迭代，完整发布矩阵未运行，工作树仍 dirty，发布分子不增加。候选继续待验证，本轮未追加模型样本、修改评分规则或运行停用单元测试。

## 2026-10-02 目标绑定与原文范围的局部反例

原用户目标、`mimo-v2.6-flash`、thinking、JSON Object、480 秒模型超时、原 v6 评分器及结果契约保持。两轮均预声明局部全部正确并人工核对后，才跑原 `test_conversation_research_review_001.py` 一次。

仅 claims 的目标绑定候选，两个有效语义输入正确 1/2：第 15 版范围误判纠正，全量删除客户端职责后仍放行。初始只删 c6、c10 仍含同一职责的控制负标签错误，原调用保留；修正后 3 次服务拒绝没有判决，诊断恢复后取得有效反例。已完成用量 19,236 tokens。

补当前引用原文的正交候选执行 4/6，布尔判决正确 3/4；必要性和原项映射人工合格 2/4，54,971 tokens。客户端删除例虽拒绝，但反馈又要求确认未必答的 API 自动 schema 校验；旧真实不完整稿仍放行。第 15 版及相邻控制原文 45 个坐标、4,500 字符，旧稿当前引用原文 23 个坐标、5,190 字符，没有客户端校验及服务器安全列表。尚未证明按目标独立选材可解决该回归。

候选均按起点逐字撤回，8 个生产/eval 文件恢复，用户原有改动保留；新增闭合编号、源依据和原文输入均没有保留生产双轨。来源支持、报告复用、URL 绑定及暂停机制保持。两份 target 各 collect-only 1 个既有用例，新的 Product E2E 执行量为 0；局部门禁失败，原正式 E2E 0/1 保持，不将局部状态代入产品分子。工程 Ruff、编译、分层及规范检查通过，完整发布矩阵未执行。

原始输入、输出、候选源码、撤回身份及成本见[目标绑定归档](../../.tmp/research-coverage-goal-binding-20261002/phase1-result.json)与[原文范围归档](../../.tmp/research-coverage-source-boundary-20261002/result.json)；当前设计及停止条件由[优化记录](../optimization/to_verify/research-goal-coverage.md)拥有。全部已完成响应合计 74,207 tokens；无可用 usage 的服务拒绝请求用量未知。该组为固定历史输入的 Offline Eval，不计完整自主研究成功率，不声明可发布。

## 2026-10-02 研究目标对照与反馈适用性验证

本组优先验证研究模型对原用户 goal 的逐项取证及修订，使用同轨迹历史来源和当前稿的固定局部输入。`mimo-v2.6-flash`、thinking 开启、JSON Object、480 秒模型超时、原评分器及所有生产核验保持。两候选分别预声明 3 个样本各一次、350,000 tokens / 2400 秒；局部全部合格后才执行原正式 E2E 一次，正式预算保持 2,000,000 tokens / 32 回合 / 48 工具 / 7200 秒。预声明及责任边界由[优化记录](../optimization/to_verify/research-goal-coverage.md#2026-10-02-研究目标对照验证预声明)拥有。

第一候选为原冻结验收的只读编号、逐项 need 状态与当前 claim 绑定；执行 1/3，协议有效 1/1、语义资格 0/1，35,766 tokens / 88.42 秒。全部 11 项已返回，仍把 API 自动 schema 校验升级为原目标必须补证，writer 未执行。完整输入审计发现 4 条历史 `research_needs_evidence` 自述仍进入当前研究视图；原始反例及撤回身份保存在[第一候选结果](../../.tmp/research-goal-accounting-20261002/result.json)。

第二候选在同一契约上仅移除研究视图的既往取证自述，普通动作仍消费其取证请求，最新适用 ResearchReview 保留。执行 3/3，协议有效 3/3、语义资格 2/3：已返回客户端条款的删除例实际选择原文并修订 c6，准入接纳，完整修改项来源通过；原第 15 版范围反馈控制合格。旧真实 7 条稿仍被判完整结果校验回答，没有针对尚未进入可引用窗口的客户端条款提出补读；最后一例拒绝候选资格，停止同向补丁。5 个已完成 Provider 响应，共 127,572 tokens / 250.67 秒，包括 3 次选择、1 次 writer 及 1 次来源核验。[原始结果及代码身份](../../.tmp/research-repair-context-20261002/result.json)保持原样。

第二候选 3 文件净增 51 行，使用一个只读验收投影及已有 need 字段，无新增存储、模型轮次或开关；失败后 3 文件逐字恢复本组开始时源码，保留既有工作树改动。真实调用连续消费只覆盖第一个样本的选择、写作、准入及修改项来源边界，其他两例是 selector 责任边界，不计 Product E2E。原 target 只收集 1 个用例、新正式 E2E 执行 0；局部预声明门禁未过，原用户结果 0/1 保持。完整发布矩阵、停用单元测试均未执行。

本组 6 个 Provider 响应按 ID 去重，已完成用量 163,338 tokens，模型阶段共 339.09 秒，thinking 全部开启。[完整 SDK 审计](../../.tmp/research-repair-context-20261002/failure-input-diagnosis.json)区分原抓取页、卸载后 retrieval 入口及实际返回坐标：旧页快照含客户端条款，实发消息没有该原文；545 条读窗记录合并为 541 个唯一坐标。该反例证明当前研究组合仍漏判必要取证，新读取机制的收益需另取反事实。静态检查、逐字恢复、文档链接及完整归档见[报告](../../.tmp/research-repair-context-20261002/REPORT.md)，无新增用户交付通过分子。

## 2026-10-02 研究与覆盖联合优化的正式验证

按用户要求同时保持研究模型与 Verifier 优化。原中文自然请求、空资料、HTTP、生产 Composition Root、真实模型和工具运行一个样本一次；没有中间状态注入。mimo-v2.6-flash、thinking、JSON Object、480 秒模型超时、原 source v1 / final v2 / grader v6、2,000,000 tokens / 32 回合 / 48 工具 / 7200 秒 HTTP 保持。方案及停止条件由[联合预声明](../optimization/to_verify/research-goal-coverage.md#2026-10-02-研究与覆盖联合优化预声明)拥有。

三个固定历史 Offline 条件各一次，协议有效 3/3，语义资格 2/3。第 15 版充分稿通过；删除客户端职责的同源反事实经实际 coverage → selector → writer → admission → 修改项 source → coverage 复验恢复。旧未读条款稿仍被覆盖放行，后续补读消费者未到达，不追加人为 selector。共 8 个已完成 Provider 响应、224,521 tokens、238.40 秒；首个控制完整 SDK 响应采集缺失，实际生产消息、Schema、返回正文及用量保留，其余 7 个有完整实发记录。见[局部汇总](../../.tmp/research-joint-goal-20261002/offline-summary.json)。

[原正式结果](../../.tmp/research-joint-goal-20261002/target/evidence/conversation-research-delivery-001/target/20261002T042128.787974Z-24260-f93db955/CONVERSATION-RESEARCH-DELIVERY-001.1.trace.json)为 **0/1**，pytest `1 failed`、2883.25 秒；入口 2846.956284 秒返回 HTTP 503，没有答案。停止前是第 9 版、9 条 claims，c1、c2 来源支持通过，c3 的修订否定范围仍被拒；c4-c9、覆盖、汇总、最终核验和独立 grader 未到达。直接停止原因为下一 writer 请求及两次重试连续 Provider 429，细分拒绝原因未取得；没有耗尽累计预算、32 回合或 HTTP 等待，服务中断与未解除来源问题分别计分。

Provider 按 ID 去重完成 **45** 个生产响应，输入 753,493、输出 147,696、合计 **901,189 tokens**；另外 3 个 writer 429 请求无 available usage，用量保持未知。已提交 Journal 前缀为 37 个 typed 操作、16 回合、14 工具、864,407 tokens。差额输入 32,440、输出 4,342、合计 **36,782 tokens** 精确等于末次合法选证，它已在内存计量，但 writer 失败发生在下一提交前。该既存独立缺口由[选证提交问题](../optimization/research-selection-usage-commit.md)拥有，不据 HTTP 失败 Trace 中的默认 total=0 计算真实成本。完整等式、前后源码及实发请求由[结果审计](../../.tmp/research-joint-goal-20261002/result.json)拥有。

全部 45 份正式响应 thinking 开启，reasoning 原样封存。15 份来源物理响应对应 11 个绑定单元，11 份正式语义报告为 2 空 findings、9 非空 findings。4 份物理响应 length，其中来源 3 份；另有一份 source stop 响应混入异常内容、不符合 Schema，经原恢复处理。相同绑定单元未观察到有效通过/拒绝冲突；一份原始请求重复来自恢复，不是对未改通过项的重新核验。工具实际为 web_search 2、web_read 2、read_artifact 2、search_action_output 8；后 8 次是来源身份关键词检索，不按工具成功视为阅读完成。split、复合识别及独立文档缺项识别零调用，删除未被模型选择。

两侧组合按[保留决定](../optimization/to_verify/research-goal-coverage.md#2026-10-02-联合正式验证与保留决定)保持于目标代码，局部及原用户结果分开；正式覆盖消费未到达，不能宣布整链改善。四生产文件净增 99 行，运行期间源码不变，原 eval、评分器及 fixture 未修改。静态、文档及封存见[报告](../../.tmp/research-joint-goal-20261002/REPORT.md)。完整发布矩阵与停用单元测试未执行，发布分子不增加，局部及独立随机轨迹差异不作成本消融。

## 2026-10-02 MiMo 诊断补齐后的正式验证

本轮只扩展现行 Provider 异常与日志，四个生产文件新增 68、删除 1 行，净增 67；研究 selector v6／writer v15、覆盖 v5、source v1／final v2／grader v6、原中文自然请求、模型、thinking、预算及暂停机制保持。两个代表性 SDK 429 失败链回放各一次，本轮前源码诊断合格 0/2、候选 2/2，付费调用 0；真实 SDK、Adapter、retry 与 Conversation 连续消费同一返回，详见[诊断候选](../optimization/to_verify/model-provider-diagnostics.md)。

原 `evals/product_baselines/test_conversation_research_review_001.py` 自空资料、HTTP、生产 Composition Root 及真实模型连续执行一个样本一次。[原始正式结果](../../.tmp/mimo-provider-diagnostics-20261002/target/evidence/conversation-research-delivery-001/target/20261002T063936.525977Z-27992-54174d26/CONVERSATION-RESEARCH-DELIVERY-001.1.trace.json)为 **0/1**，pytest `1 failed`、4723.05 秒；入口 4709.596073 秒无异常返回 limitation，达到 32 回合，没有交付 answer，独立 grader 未执行。全部 93 次 MiMo 请求为 200，实际 Provider 错误检查点未触发，上次 429 细分原因仍未知。

八条 claim 保持到第 19 版并全部取得来源支持。31 次来源物理响应对应 26 个实际绑定报告：8 份空 findings、18 份非空；另 5 份 length 空正文没有判决。覆盖第一份原始报告识别三个用户相关缺口，但字符串引用触发 38 项类型错误；结构恢复在相同业务输入上改为九项 covered、两项 delivery_check，缺口未送入研究修订。事实、实发输入和原文依据由[覆盖恢复问题](../optimization/to_verify/research-goal-coverage.md#2026-10-02-覆盖结构恢复抹除缺项反馈)拥有。

五次最终报告都未形成有效回执：前四次各十二项 satisfied，但忠实性 criterion 漏了中文句号；第五次仍漏句号并改写另一项文字，还带一项原始 insufficient_evidence。Runtime 按逐字集合拒绝，详见[验收项转录问题](../optimization/completed/final-criterion-transcription.md)。c8 新正文未同步引用、后续独立改引用的连续结果见[修订子问题](../optimization/completed/claim-atomic-evidence-revision.md)。这些原始响应均保留，不用结构恢复或较早 satisfied 覆盖原始失败。

Provider 响应 ID 去重完成 93 次：intent 1、agent turn 30、selector 24、来源 31、覆盖 2、最终核验 5。实际输入 1,767,488、输出 245,534、合计 **2,013,022 tokens**，全部请求完成且 thinking 开启、reasoning 保留。Journal 为 79 个 typed 操作、32 回合、18 工具、1,945,314 tokens；差额输入 57,431、输出 10,277、total 67,708 精确等于五次最终工具模型响应，见[工具用量交接](../optimization/tool-model-usage-handoff.md#2026-10-02-最终契约失败调用仍有漏计)。六次 length 分别为来源五次、selector 一次，单次输出上限均 8192；结构恢复响应仍计成本。

工具为 web_search 4、web_read 2、read_artifact 3、search_action_output 4、verify_interaction_draft 5；拆分、复合识别、独立文档缺项识别均零调用，删除未被选择。运行期间源码与原 eval／fixture 身份保持。本次相对上一轨迹推进到覆盖与最终汇总，调用 45→93、已知 tokens 901,189→2,013,022、入口耗时 2847→4710 秒；独立随机轨迹只作描述，不归因于诊断改动。静态检查、完整请求与封存由[本轮报告](../../.tmp/mimo-provider-diagnostics-20261002/REPORT.md)拥有；原评分、完整发布矩阵与停用单元测试未运行，发布分子保持。

## 2026-10-02 验收项引用恢复的正式验证

按[预声明](../../.tmp/final-criterion-reference-20261002/plan.json)落实已有文本引用规范并修复最终验收项身份。普通最终 v5、研究最终 v3 接入当前 ID、动态 Schema 与 Runtime 原文恢复；四个生产文件新增 71、删除 23、净增 48 行，两个不可变类型、两个请求临时 Schema，无新模块、Port、持久化、开关或模型阶段。原中文用户任务、空资料、HTTP、Composition Root、mimo-v2.6-flash、thinking、JSON Object、480 秒模型超时、2,000,000 tokens / 32 回合 / 48 工具 / 7200 秒入口等待及原研究、来源、覆盖、评分和暂停机制保持，原 eval 与 fixture 字节未改。

同五份历史报告的绑定反事实各一次：旧绑定 0/5、当前 ID 绑定 5/5，状态与反馈保持，原第五份不足意见仍聚合 failed；遗漏、重复、未知三类全部拒绝，付费调用 0。三个历史输入的真实模型局部验证各一次，引用绑定 3/3，普通稿连续经过来源支持；4 份物理响应、30,804 tokens、133.625 秒。它们是 Offline Eval，真实第五稿的新语义判决差异保留。机制、失败尝试与证据由[完成记录](../optimization/completed/final-criterion-transcription.md)拥有。

原 `evals/product_baselines/test_conversation_research_review_001.py` 一个样本一次：[原始结果](../../.tmp/final-criterion-reference-20261002/target/evidence/conversation-research-delivery-001/target/20261002T100012.689914Z-7260-31bf0458/CONVERSATION-RESEARCH-DELIVERY-001.1.trace.json)为 **0/1**，pytest `1 failed`、5205.57 秒；入口 5047.86488 秒无异常返回 `answer`，独立 v6 评分取得有效拒绝。10 条 claims 保持到第 19 版；28 个来源报告为 11 次接受、17 次拒绝，无同完整 SDK 输入空/非空原始方向冲突。两次覆盖报告结构有效：首次识别结果校验缺项，真实选证、修订与复验后第二次通过，未把历史结构恢复失败计作本轮收益消融。

实际最终模型只返回 r1–r10，一次报告形成 passed 回执；十项正文逐字恢复，原用户标准与完整稿 digest 保持，canonical 消费者接受同稿及第 19 版研究绑定，Completion 返回同一答案。引用检查点 **1/1**，最终工具一次，无旧全文转录失效，见[正式引用审计](../../.tmp/final-criterion-reference-20261002/reference-audit.json)。原用户失败由独立评分判断触发，不能由此检查点覆盖。

[实际输入与语义审查](../../.tmp/final-criterion-reference-20261002/semantic-review.json)确认正文未说明 outputSchema 为可选及结构化结果义务的适用条件，也未覆盖服务器输入校验、访问控制、限速与输出清理。正文仍用“据本次所引行”和片内未知限定；评分将其归为无条件断言、弱化 MUST 的解释须与缺项分开审查。评分对 architecture、tools-remote-mcp 和列表条款报告参考不足，生产 basis 与来源请求实际包含这些官方来源，不能据此认定引用失实。当前评分资格问题仍开放。Trace 的 earliest_failure 是已恢复的 offloaded_output_refetch，不是终端原因。

Provider 响应 ID 去重：生产 89 份，输入 1,445,823、输出 213,840、total **1,659,663 tokens**；独立 grader 1 份 9,413 tokens，正式已完成总用量 **1,669,076**。生产 HTTP 日志 89 次 200，无 Provider 失败或未完成请求；全部 90 份请求 thinking 开启、reasoning 保留。Journal 为 81 个 typed 操作、31 回合、18 工具、1,647,159 tokens；差额输入 10,138、输出 2,366、合计 **12,504** 精确等于最终工具的一份模型响应，该既存交接缺口由[工具用量问题](../optimization/tool-model-usage-handoff.md)拥有。两份 length 来源响应及恢复成本全部保留。

工具实际为 web_search 2、web_read 4、search_action_output 11、最终核验 1；split、复合识别和独立缺项识别零调用，删除未被选择。与前次同入口相比，从五次最终转录拒绝后 limitation 推进到一次合法回执和 answer，原用户语义结果仍失败；两条独立随机轨迹只作描述，不作为成本或语义收益消融。源码在运行期间保持，Ruff、编译、分层、规范、文档与差异检查及封存由[本轮报告](../../.tmp/final-criterion-reference-20261002/REPORT.md)拥有。完整发布矩阵和停用单元测试未执行，不增加发布通过分子。

## 2026-10-02 独立评分的必要性与来源归属校准

本轮只修改独立评分模块、其 Offline Eval 和共用正式 E2E 消费者，替换两个场景 fixture；生产源码 262 份逐字保持，三个 eval 源码净增 14 行、增加四个评测类型。原中文用户请求、两份实际正式答案、mimo-v2.6-flash、JSON Object、thinking、32768 输出额度及 480 秒超时保持。原用户结果及历史 pytest 失败不改写，评测器按 EVM 7 消费封存真实产物，没有重新生成生产研究或运行停用单元测试。

[旧评分逐项审查](../../.tmp/research-grader-review-20261002/baseline-review.json)区分了用户必要性、具体声明的条件、局部取证描述和评分参考缺页。v8 用 findings 引用用户、答案及原文；Runtime 校验当前引用、恢复原文并聚合三态，正式消费者只接受 passed。参考由已有官方快照和正式实际返回摘录构成七个页面/70095 字符，不注入生产通过结论或人工标签。

首轮额外限制最新稿只能以缺项拒绝，模型却定位到真实引用错配，原资格为1/2、2/13后停止。[独立审查纠正](../../.tmp/research-grader-review-followup-20261002/qualification-review.json)保持状态标签和模型报告，通过身份复用两份结果。第二轮的单删服务器控制仍在总结中提及服务器访问控制，未形成完整删除；原资格5/6、6/13后停止。[反事实审查](../../.tmp/research-grader-review-controls-20261002/counterfactual-review.json)保留旧控制的expected failed/actual passed，剔除它并预声明明确服务器权限问题及干净缺项正文；不把旧结果改成通过。

[最终资格](../../.tmp/research-grader-review-controls-20261002/summary.json)为13/13：五份有效旧报告按校验和复用，八项新输入各执行一次，未重复采样。最新真实稿仍failed，理由为把 OpenAI function calling 四步流程归到 MCP架构页，完整架构页与函数调用页原文能确认错配；较早真实稿因客户端校验责任未交付及一个URL错配拒绝。局部范围和无需额外字段的正例passed；明确义务扩大/弱化、引用错配及职责缺项failed；参考缺页inconclusive。来源、用户必要性与原文绑定经实际报告审查。

[SDK及成本审计](../../.tmp/research-grader-review-controls-20261002/input-and-cost-audit.json)确认14个物理响应，输入570413、输出51890、合计622303 tokens；资格样本578783，剔除弱控制43520。累计原子模型耗时1049.805267秒，全部thinking开启、reasoning保留、无额外重试；两份正文带末尾parameter，由现行确定性JSON解析取得同一有效对象，原响应保留。这个结果是限定样本的评分资格，不估计稳定正确率，不进入Product E2E发布分子。原真实E2E仍0/1；当前评分与历史评分身份分开。机制固化见[完成记录](../optimization/completed/research-grader-qualification.md)，真实产品来源归属问题由[独立记录](../optimization/normative-scope-attribution.md)继续拥有。

## 2026-10-02 具体来源归属与实际反馈修订验证

按[预声明](../../.tmp/source-attribution-repair-20261002/plan.json)修复最终稿具体来源归属。Conversation 保留 canonical 逐段引用原文与 URL，现有最终工具校验段落对应并物化到同次请求；writer v16、synthesis v2、research final v4 替换原 Prompt。原 selector v6、coverage v5、source v1、已资格 grader v8、原中文任务、mimo-v2.6-flash、thinking、JSON Object、预算与暂停机制保持。三个生产文件改动，没有新类型、模块、存储或模型阶段；全部 eval 源码及 fixture 字节保持。

原实际错稿仅核验一次，r10 准确拒绝流程步骤被归到 MCP 架构页。初始脚本额外要求必须在 r5 拒绝而 EXIT 1；[独立审查](../../.tmp/source-attribution-repair-20261002/qualification-adjustment.json)保留失败日志及原模型报告，移除分类限制、复用负样本结果，没有重采样。仅将“该页”替换为明确 OpenAI 来源的合法多来源对照一次通过，来源归属条件局部资格 **2/2**，见[审查](../../.tmp/source-attribution-repair-20261002/qualification-review.json)。

真实拒绝反馈连续交给汇总模型，实际修订原样经过 canonical 引用恢复、生产最终核验和 v8 独立评分：出处恢复，最终核验 passed，独立评分 failed，条件局部用户结果 **0/1**。实际稿把“步骤包括”改为“流程所列步骤为”，列四项且新增自检“四个步骤”，前文仍称五步；完整参考中应用侧执行步骤被漏掉。该行未进入历史最终可引用目录，但最终核验已有五步声明与四项枚举，仍未拒绝范围变化。拒绝核对主动生成的具体声明，没有增加用户必答项。当前 basis、真实反馈、实发逐段原文和准确失败原因见[连续审查](../../.tmp/source-attribution-repair-20261002/continuation-review.json)。

[实发与成本审计](../../.tmp/source-attribution-repair-20261002/input-and-cost-audit.json)确认五个直接调用、五个去重 Provider 响应，无额外重试；输入122866、输出20639、total **143505 tokens**，原子模型耗时393.074034秒，全部thinking开启、reasoning原样保留。每份最终请求的 units 与 segments 顺序及全文一致，来源 URL 来自实际绑定。原 Product E2E 仍0/1；本组固定历史中间态的连续 Offline Eval 不纳入产品成功率。

实际命令为 `.venv/Scripts/python.exe -X utf8 .tmp/source-attribution-repair-20261002/launch_offline.py continue`；因独立评分拒绝 EXIT 1，按预声明停止。`.venv/Scripts/python.exe -X utf8 .tmp/source-attribution-repair-20261002/target/run.py --collect` 成功收集原正式用例一项，**新 Product E2E 执行0**；连续资格未过，没有启动正式 target。整体候选仍待验证，枚举范围错误由[未收敛子问题](../optimization/claim-revision-nonconvergence.md#2026-10-02-汇总将部分列举改为完整枚举)拥有。完整发布矩阵、停用单元测试未运行；源码身份、静态检查与封存见[本轮报告](../../.tmp/source-attribution-repair-20261002/REPORT.md)。

## 2026-10-02 具体来源归属候选的正式入口验证

原局部停止及连续用户结果0/1封存后，依据用户明确要求优化接入真实路径并运行对应E2E，[单独预声明](../../.tmp/source-attribution-product-target-20261002/plan.json)一次正式验证。固定历史basis的枚举反例未覆盖当前写作者从空资料自主取证以及最终归属核验的真实消费，故调整原“历史basis连续评分通过后才跑target”的顺序门槛；原计划、失败及调整依据均保留。本轮没有追加生产、Prompt、评分、预算或重试修改。

实际命令 `.venv/Scripts/python.exe -X utf8 .tmp/source-attribution-product-target-20261002/run.py`：原 `test_conversation_research_review_001.py` 的中文自然目标、空资料、HTTP、生产Composition Root、真实模型和工具连续执行一个样本一次。[原正式结果](../../.tmp/source-attribution-product-target-20261002/evidence/conversation-research-delivery-001/target/20261002T134506.192678Z-29516-3a0845d2/CONVERSATION-RESEARCH-DELIVERY-001.1.trace.json)为 **0/1**，pytest `1 failed`、315.78秒；入口288.218628秒返回503，没有答案，独立grader按既有规则未运行。mimo-v2.6-flash、thinking、JSON Object、480秒模型超时、2M tokens/32回合/48工具/7200秒HTTP及暂停机制保持。

最早阻塞为selector v6输出契约。实际请求包含28526字符的会话、原验收、已返回资料及source_feedback，Schema必填next_step、needs、reason。两份200响应均耗尽8192单次输出额度并以length结束；正文3791及3621字符，原始reasoning22695及20001字符，宽松JSON解析取得对象后仍缺required reason，一次现有结构恢复未解除错误，继而返回503。不能据非空正文认定有有效提交，不能据503认定Provider拒绝。完整角色、Schema、请求及返回链见[输入审计](../../.tmp/source-attribution-product-target-20261002/selection-failure-audit.json)。

[成本审计](../../.tmp/source-attribution-product-target-20261002/target-audit.json)确认五个去重Provider响应，HTTP均200：intent1、agent turn2、selector2；输入43110、输出18472、total **61582 tokens**，thinking均开启、reasoning保留。实际工具web_search2、web_read2；claims、来源报告、覆盖、汇总、最终核验、拆分及独立缺项识别均0。Journal前缀为3个typed操作、2回合、4工具、22187 tokens，差额输入23011、输出16384、total39395精确等于两份已完成选证响应，由[计量子问题](../optimization/research-selection-usage-commit.md#2026-10-02-选证结构失败的已完成用量)拥有。

归属候选的正式消费检查点未到达，原局部2/2保留，整体候选继续待验证；最早产品阻塞另登记为[选证截断子问题](../optimization/claim-revision-nonconvergence.md#2026-10-02-选证输出截断阻断正式研究)。本轮合计十个实际响应、205087 tokens：局部143505和正式61582分别计量；两组中间态与产品结果不合并为成功率。运行期间源码、共用eval和fixture不变，静态、文档、代码身份及封存见[正式报告](../../.tmp/source-attribution-product-target-20261002/REPORT.md)。完整发布矩阵与停用单元测试未运行，不声明收敛或发布完成。

## 2026-10-08 当前稿独立核验与正式入口续验

[当前稿候选](../optimization/to_verify/final-revision-comparison.md)先恢复原无响应边界，再完成局部校准。八份有效判决为 **8/8**：三份历史输出来自两份不同真实稿，五份相邻人工控制来自四份不同正文；控制只用于评分边界。原三次无响应尝试保留，不能当作判决。历史初始状态的真实反馈、汇总修订、canonical 引用绑定、v6 最终核验及原 v8 独立评分连续消费同一轨迹，条件局部用户结果 **1/1**。本轮新增九份完成 SDK 响应，校准 123,824、连续验证 132,827、合计 256,651 tokens；连同首轮已知成本，局部已知 **339,856**，另有三次未知用量。实际输入、成本与条件边界见[局部审计](../../.tmp/current-draft-verifier-resume-20261008/input-and-cost-audit.json)。

候选原样迁入三个生产模块，新增 3、删除 40 行，净减少 37；最终 Prompt 为 v6-current-draft，删除 `previous_verification`，汇总 v3 继续消费真实最新稿与反馈。没有新阶段、类型、模块、存储或开关。原中文任务、HTTP、空资料、生产 Composition Root、mimo-v2.6-flash、thinking、480 秒 deadline、32 回合 / 48 工具 / 2,000,000 tokens / 7,200 秒 HTTP、原 grader v8、fixture 与结果断言保持。原测试 PostgreSQL 15432 不可达，改用既有健康实例 16432，仅作用于该评测子进程；没有修改 `.env` 或生产配置。

执行 `.venv/Scripts/python.exe .tmp/current-draft-verifier-resume-20261008/run_product.py`，原正式用例一个样本一次，[封存结果](../../.tmp/current-draft-verifier-resume-20261008/product/conversation-research-delivery-001/target/20261008T060953.653872Z-23464-99261d53/summary.json)为 **0/1**，正式用例 4777.762494 秒。生产达到 32 回合、23 次工具，返回 limitation，未交付答案；独立 grader、coverage、汇总和最终 Verifier 均未到达。来源修订 c2、c6 加入新事实后保留旧引用，后续来源反馈仍拒绝，归入[既有原子引用候选](../optimization/completed/claim-atomic-evidence-revision.md)，不把上游未完成记作 v6 判断失败。局部资格不覆盖原用户失败。

[正式审计](../../.tmp/current-draft-verifier-resume-20261008/product-audit.json)确认 62 次 SDK 尝试、60 份完成响应，输入 1,505,471、输出 192,231、已知合计 **1,697,702 tokens**；两次无响应用量未知，全部实发请求 thinking 开启。一次约 302 秒传输失败、一次 480 秒 deadline 均经既有重试恢复，具体根因未知，另由[传输问题](../optimization/model-provider-transport.md)记录。运行期间 261 份生产源码与候选身份一致。启动包装器在结果封存后发生 GBK 输出编码失败；原日志保留，按 UTF-8 修复包装器且只读恢复结果，没有重复付费运行。原 pytest 退出码及包装器总耗时未被捕获，明确标为未知，不能用正式失败状态推造退出码。

本轮全部局部与正式已知成本 **2,037,558 tokens**，另有五次未知 SDK 用量。完整发布矩阵和停用单元测试未运行，发布成功分子不增加；后续独立修复及新正式样本按独立身份登记，旧失败结果保持。

## 2026-10-08 正文与新增引用的连续修订

[原子候选](../optimization/completed/claim-atomic-evidence-revision.md)复用上述正式失败中的 c2、c6 实际写作请求、前置状态、冻结标准及已选原文。候选只修改研究准入与 writer Prompt 两个模块，`ReviseClaimFragment.additional_references` 由模型明确选择，Runtime 保留旧引用并去重合并，全部坐标与版本成立后生成一个新版。其他研究 Prompt、最终 v6、模型、thinking、deadline 与评分保持。两份真实失败状态的合成新增字段回放及八个拒绝控制通过，付费调用零；这些控制不冒充实际模型输出。

付费前审计两条业务消息逐字一致。封存 Trace 对原始 dict 字段排序，恢复实际 SDK 请求的键顺序后再进入生产构造器；所有值及 typed 身份保持，没有另设局部输入。第一条 c2 实际同次新增两项引用，来源完整请求消费实际新稿及绑定原文，原缺证解除，却因流程衔接与“完整职责”产生两项范围反馈，原资格 **0/1**、36,963 tokens 保留。预声明独立有界修订后，同一反馈经原 selector、同一 writer、同一 source 连续消费，收窄实际范围并通过，三次调用、82,208 tokens。第二条 c6 随正文明确新增五项引用，实际来源复验首次通过，两次调用、27,943 tokens。

两份实际原子绑定成立；c2 一次反馈修订后、c6 首次来源通过，不改写第一次失败为首次成功。七份 SDK 响应全部完成、输入 132,325、输出 14,789、合计 **147,114 tokens**，thinking 开启、没有额外重试或未知用量；[实发审计](../../.tmp/claim-atomic-reference-repair-20261008/input-and-cost-audit.json)确认真实反馈、选择与生成原样进入后置消费者。两份历史无新增依据的正文动作回放与旧准入结果相同。该组是条件 Offline Eval，不计 Product E2E 成功分子。

仅将同一候选两个模块逐字迁入生产，261 份源码身份全部匹配。原正式用例收集一项，数据库只读预检通过；新正式样本按同一中文请求、空资料、HTTP、生产 Composition Root、原模型、原 grader v8 与 32/48/2M/7200 边界执行一次，新结果独立归档于 `.tmp/claim-atomic-reference-repair-20261008/product/`。此前正式 **0/1** 保留，实际正式结果见下节，完整用户通过仍未成立。完整发布矩阵与停用单元测试未运行。

## 2026-10-08 原子引用修订后的正式入口结果

实际命令 `.venv/Scripts/python.exe .tmp/claim-atomic-reference-repair-20261008/run_product.py` 执行原中文 HTTP 用例一个样本一次，[封存结果](../../.tmp/claim-atomic-reference-repair-20261008/product/conversation-research-delivery-001/target/20261008T074117.886631Z-28628-aa12ecb7/summary.json)为 **0/1**，pytest 退出 1、3232.02 秒，包装器 3240.894847 秒。生产入口 2779.771721 秒、19 回合及 19 次工具调用，返回 `disposition=answer`；独立语义评分失败，`delivered=false`。原中文目标、空初态、模型及 thinking、480 秒请求边界、32/48/2M/7200 预算、v8 grader 与参考 fixture 均保持，261 份生产源码运行期间与候选一致。相对 HEAD 四个生产文件新增 16、删除 45，净减少 29 行。

正式原子引用消费 **5/5**，局部成果由[完成记录](../optimization/completed/claim-atomic-evidence-revision.md)拥有。当前研究第 8 版来源通过，v5 coverage 判充分，synthesis v3 成稿，v6 当前核验一次 passed 并形成合法回执；实际 v6 输入没有历史比较，完整稿及逐段依据匹配。原完整评分把正文保留宿主/客户端及调用链衔接未知、自检声称已覆盖判为核心三方协作缺项，作为当时[覆盖审查](../optimization/to_verify/research-goal-coverage.md)的标签依据。另一个 `evidence_gap` 是实际 OpenAI `/api/docs/mcp` 引用页面未进入评分参考，属于评测依据不足；MCP 规范版本差异当时未被报告。原两个finding及正式失败保持；后续补齐参考后的标签复核见本页精确引用版本小节，不将原单次标签作为当前已确定的产品漏放。

[正式审计](../../.tmp/claim-atomic-reference-repair-20261008/product-audit.json)确认 48 次 SDK 请求、48 份完成响应，无传输失败或未知用量。生产输入 998,220、输出 128,268、total **1,126,488**；独立 grader 输入 43,983、输出 19,712、total **63,695**，耗时 434.311214 秒；本样本合计 **1,190,183 tokens**。两份现有 selector 结构恢复均计入，不把物理响应数当研究回合数。Journal 的 34,908-token 差额由[工具模型用量交接](../optimization/tool-model-usage-handoff.md#2026-10-08-最终当前稿核验响应仍未交接)独立拥有。

连同前述两个局部阶段和第一正式失败，本轮累计已知 **3,374,855 tokens**，五次旧未知用量仍保留。独立随机轨迹的成本差异不作为机制消融；完整发布矩阵与停用单元测试未运行，产品验收和发布分子不增加。证据身份、命令和限定结论见[本轮报告](../../.tmp/claim-atomic-reference-repair-20261008/REPORT.md)。

## 2026-10-08 OpenAI MCP 指南的评分参考补齐预声明

问题编号 `RESEARCH-GRADER-MCP-REFERENCE-001`。上述实际答案引用 `/api/docs/mcp`，现行七页参考没有该页面；原 grader 的 evidence_gap 正确表达输入不足。独立 HTTP 抓取同一官方页面的 Markdown，200返回，30,815字符；实际出处、时间、内容hash及原七页逐项不变由[抓取身份](../../.tmp/research-reference-gap-20261008/capture.json)保存。确认批准跳过的只读示例和 ChatGPT 写入确认条款均在对应正文，整页作为第八项来源，不注入生产研究。

候选只追加参考及新revision，不更改v8 Prompt、Schema、用户要求、结论断言或成功标准。先用最新实际完整答案及原用户目标 Offline 重评一次：有效核心协作缺项必须仍失败，该页面引起的依据不足须可判定；再复用已封存的完整合法控制一次，须通过且不增补可选必答项。最多2个逻辑操作、160,000已完成tokens、1200秒，出现明确误判停止参考迁移，服务未知单列。合格后逐字替换唯一正式fixture并更新比较身份；旧E2E保持0/1，不用新参考重写其结果。本组仅是评测参考资格，不计Product E2E。生产代码不变，完整发布矩阵与停用单元测试不运行。

### 完整页面参考资格失败与有界范围修正

第一次服务尝试超过480秒，没有判决，用量未知；原重试的完成响应为77,801 tokens。新参考补齐后 grader 对同一实际完整答案返回 findings 为空，将架构角色及调用链衔接认作可选细节，没有保留预声明的核心缺项，资格 **0/1**。累计930.05秒，合法控制及fixture迁移均未执行；原正式0/1保持。实际请求、页面与输出由[资格结果](../../.tmp/research-reference-gap-20261008/qualification-result.json)保存。参考缺口已可判定与整体判断冲突分别记录，不能据该次passed改写旧E2E或宣布评分稳定。

有界修正仅将新增页面改为真实来源的完整相关读窗：引言与只读工具范围、API批准跳过示例的条件及完整例子、写入确认与信任限制。原七页逐字保持，新增正文逐行从已独立抓取页面恢复并保留行号，不截断断言的条件，不增加理想原文。页面中其他长代码示例是否影响判断是待证假设，两个随机返回不构成确定性因果。沿用同一两个判据、v8 Prompt/Schema/模型/thinking/deadline，至多2个逻辑操作、160,000已知tokens、1200秒；首个明确反例停止本方向，不再追加范围补丁。新身份独立归档 `.tmp/research-reference-gap-compact-20261008/`，原失败和未知成本保留，合格前fixture仍不修改。

## 2026-10-08 精确引用版本与评分资格复核

精简参考的实际首例为 inconclusive，资格 **0/1**，一次 SDK 完成响应、**54,744 tokens**、104.075秒；合法控制及迁移未执行。新增指南的引用可以判定，但答案引用的 MCP tools 是2025-06-18版，原七页只有2026-07-28版，无法验证所引版本。原 grader 未继续认定三方关系缺项。该实际证据缺口与核心判断分歧分别保留，不把新版条款直接当成旧版依据，也不修改原正式失败或前两次资格期望。[精简资格结果](../../.tmp/research-reference-gap-compact-20261008/qualification-result.json)保存原输出。

先通过独立 HTTP 取得实际引用的2025-06-18版官方 tools Markdown，200、10,857字符，完整正文及抓取身份见[精确版本](../../.tmp/research-reference-version-gap-20261008/capture.json)。候选保留前八项逐字不变，只追加该版本和新参考 revision；没有向生产轨迹补入资料。此项属于评分依据修复，v8 Prompt、Schema、用户结果契约及生产代码保持。

本次参考资格使用已封存、边界明确的两个控制各一次：`complete-without-extra-settings` 必须 passed；`missing-client-validation` 必须 failed 且含用户结果缺项，不产生参考不足。二者全部合格后，对原实际完整答案重评一次，检查精确引用的依据缺口是否解除，并保留真实语义判决。第三项是判断分歧诊断，不预设其总体通过或失败，不计产品成功；前两次原核心缺项期望仍按失败保留。这样先验证参考能区分实际职责遗漏和完整合法回答，再复核有争议的旧标签，不以争议标签作为参考唯一准入证据。

至多3个逻辑操作、250,000已完成tokens、1800秒，依据前两次约55,000—78,000-token评分成本和新增旧版正文；固定控制首次误判停止。若两项控制合格、实际旧稿不再有引用依据缺口，可将同一参考逐字迁入唯一fixture；若核心语义判断仍有分歧，研究覆盖候选保持隔离，不能宣称该关系问题已解决。旧E2E、旧pytest失败、成本和引用缺口均不追溯覆盖。新身份归档 `.tmp/research-reference-version-gap-20261008/`，只证明评分参考边界，不执行或声称新的Product E2E。

### 精确参考实际资格与原正式方案恢复

执行 `.venv/Scripts/python.exe -X utf8 .tmp/research-reference-version-gap-20261008/qualify.py`，既有完整正例passed、客户端校验缺失反例failed且含必要缺项，固定控制 **2/2**。原实际完整答案的独立诊断为passed、无findings或引用缺口；这项是封存文本的Offline重评，**不是新Product E2E**，原正式0/1及pytest退出1保持。3个逻辑操作、3份完成SDK响应、**192,273 tokens**，无恢复或未知用量，参考版本资格成立；r2标签分歧按[覆盖记录](../optimization/to_verify/research-goal-coverage.md#标签复核后的撤回与原方案续验)撤回本轮确定漏放主张，未迁入候选覆盖Schema。

逐字迁移9项参考至唯一正式fixture，保持前七项、控制、v8 Prompt/Schema和用户结果契约；新增官方MCP指南的完整相关读窗及实际引用的2025版tools全文。此项只修复评分依据，生产261份源码保持身份。新正式target在 `.tmp/current-draft-qualified-reference-target-20261008/` 独立归档，原中文请求、空资料、正式HTTP与Composition Root、模型/thinking/480秒边界、32回合/48工具/2,000,000 tokens/7200秒等待及v8评分保持。预声明一个原用例一次，验证原v6当前稿分工和已固化原子交接在完整交付中被消费；覆盖及来源机制保持，不注入中间稿或新参考到生产。新target仍失败时封存并从最早责任边界审查，不因一次新评分通过增加历史产品成功分子。

## 2026-10-08 已校准参考续验的选证状态阻塞

实际命令 `.venv/Scripts/python.exe -X utf8 .tmp/current-draft-qualified-reference-target-20261008/run_product.py`，一个原中文正式样本一次，**0/1**、pytest退出1、741.57秒，包装750.232356秒，入口708.335722秒后HTTP503。原自然目标、空初态、模型/thinking、480秒边界及产品预算保持；261份生产源码、v8评分代码及新参考在执行期间均未变。仅初始取证和选证到达，claims、来源、Coverage、synthesis、finalv6和独立grader均未到达；没有独立评分新用量。[正式审计](../../.tmp/current-draft-qualified-reference-target-20261008/product-audit.json)及原pytest失败保留。

10份SDK响应全部完成，输入107,874、输出17,786、total **125,660 tokens**，无传输失败或未知；两次结构恢复及一份动作协议纠正均计入。部分Journal的全部已知用量相等，但入口异常使原用例没有取得Trace，脚手架按entry/HTTPError登记；实际最早责任通过请求、响应及保存的部分Journal定位，不把终态泛类当根因。

首次选证正常响应在当前无claims时返回多项answered及空claim_ids，现有恢复把它改为合法ready后继续真实搜索。第二选证正常响应含多余键`:references`，既有一次结构恢复修正该键，却把r5改为answered及空claim_ids；现行类型拒绝，恢复耗尽后抛StructuredOutputFailure并传播503。两次响应finish_reason=stop，无截断。SDK输出Schema仍包含answered且claim_ids可为空，实际Python校验却要求answered必须关联当前claim；初始状态没有合法claim身份，该不变量没有在当次Schema中呈现。独立阻塞为`RESEARCH-SELECTION-STATE-CONTRACT-001`，最终v6和原子引用差异未改变该原选证契约。

下一最小修复由[选证状态契约设计](../optimization/completed/research-selection-state-contract.md)拥有：按实际当前稿状态投影合法输出形状，禁止空稿阶段生成已回答身份，不重写模型语义决定；先回放同一两个实际初始输入和已有稿回归，再续接实际输出及单个原正式入口。此前累计已知4,366,388加本次为 **4,492,048 tokens**，六次旧未知保持，独立评分与生产用量不混算。完整发布矩阵和停用单元测试未运行。

### 选证状态契约局部资格与原入口恢复

状态契约的三个真实输入回放3/3通过协议与原项范围核对，两个空稿状态均取得合法选证，已有8个claim输入的Schema和业务messages逐字保持。3个逻辑操作/5次SDK共99,178 tokens，其中两次格式错误沿原恢复完成。消费第二次实际选证的续接由模型自行调用真实Artifact读取和搜索，得到正文及MCP命中，1个操作/1次SDK共14,064 tokens；合计113,242，全部6次SDK完成。这是条件Offline Eval，尚不构成ProductE2E。

三个生产模块逐字迁入隔离候选，全部261源文件身份一致；源目录相对HEAD四文件31增48删、净减17行，没有新增阶段、模型调用、存储或开关。`.tmp/research-selection-state-target-20261008/`按原正式用例一个样本一次恢复，评分代码/v8与已资格9页参考、中文用户输入、目标、32/48/2M/7200、模型及480秒保持。原失败封存，当前正式结果待取得。至此全部轮次累计已知4,605,290 tokens，历史6个未知用量保持。

## 2026-10-08 选证状态修复后的正式入口结果

`.tmp/research-selection-state-target-20261008/`原中文HTTP样本0/1，pytest退出1，3267.51秒，外层3276.4972914秒，生产入口3004.441392秒，独立评分245.7120101秒。22/32决策回合、14/48工具，answer已进入Completion，但完整用户断言未通过。47次SDK全部完成（46生产含恢复、1评分），生产722,048（599,558输入/122,490输出），评分64,760（57,130输入/7,630输出），累计786,808，无新增未知。全部轮次累计已知5,392,098，历史6个未知保持。Journal666,454与生产SDK差55,594，等于两次最终工具模型响应，由现有计量交接问题拥有。

三个正式初始选证请求逐字对照canonical快照和SDKSchema，合法状态经实际writer生成4条claim，来源及覆盖消费；初始状态问题按[窄机制](../optimization/completed/research-selection-state-contract.md)固化。原子编辑保持。Finalv6第一次拒绝三方协作表达，synthesisv3消费真实旧稿与反馈后修订，第二次v6独立通过；两次当前稿请求均无previous_verification，完整段落与引用逐字一致。该分工检查点成立，整体结果失败分别计分。

独立评分唯一factual_error：a37/a38把Stateful Tools的非规范性授权设计指导写成“MCP规范要求”，参考r3.454/r3.472已有完整限定，故不是评分输入缺口。同一正式Artifact第453行含限定、471行含授权行为，453从未进入生产模型请求；最早错误由初始writer生成，来源核验在缺限定的实际输入中继续放行。按[规范性限定取证设计](../optimization/to_verify/normative-context-acquisition.md)先做责任边界诊断。报告earliest_failure记录的provider_action_missing是已恢复早期动作问题，不是本次最终语义失败责任，原字段保留。

## 2026-10-08 规范性限定诊断与选证候选撤回

本轮只执行条件Offline Eval，未新增Product E2E。原正式失败的Source请求0046、canonical快照0033、Artifact及原文身份固定；实际章节限定453被补读后，原v1对错误标签负例、正确设计指导及真实协议条款三项诊断3/3，12,150已知tokens、一份SDK超时未知用量。补读参数、额外引用与正稿由分析者设置，不能计为模型取证成效。

隔离selector v8首项实际缺行引用被Runtime拒绝，原校准0/3保留，SDK15,293补审计。实际错误反馈恢复并接余下已有稿及充分状态控制，协议3/3、87,635新增tokens；已有稿仍把d4:471标为有据协议要求，补证仅覆盖另一claim，目标语义资格0/1，候选撤回且未迁入生产。充分状态控制选择write，未附加全面取证义务。未进入连续writer或正式样本，不以协议通过覆盖语义失败。

原始请求、实际反馈、所有SDK响应及失败见[封存结果](../../.tmp/normative-context-acquisition-20261008/REPORT.json)、[语义反例](../../.tmp/normative-context-acquisition-20261008/semantic-review.json)、[实际用量审计](../../.tmp/normative-context-acquisition-20261008/usage-audit.json)。本档115,078已知tokens，8次物理SDK请求中7完成、1未知，wrapper父记录不重复计费；连续累计5,507,176已知tokens、7次未知SDK消耗，未知不补零。实际工程身份未变化，下一责任边界由[唯一活动设计](../optimization/to_verify/normative-context-acquisition.md)拥有。

## 2026-10-08 来源归属候选反例与重复阻塞复审

隔离来源v2只改变判据与版本，原正式Source0046的错误c2、业务输入及Schema逐字保持，未补入453限定。首项实际仍返回空findings，目标语义0/1，原控制失败记录保留；两个正控制及连续writer未到达，正式样本零、生产迁入零。真实SDK输入含候选规则，重试业务输入相同，未凭模板归因。

首次480秒超时未知用量保留，原恢复策略取得一份响应，总逻辑655.5秒、10,153 tokens；两份物理SDK中一完成、一未知，wrapper父记录不重复计量。见[封存结果](../../.tmp/source-normative-attribution-20261008/REPORT.json)、[实发输入与语义审查](../../.tmp/source-normative-attribution-20261008/semantic-review.json)、[成本审计](../../.tmp/source-normative-attribution-20261008/usage-audit.json)。累计5,517,329已知tokens、8次未知SDK消耗。

该来源候选与上一条选证候选均未解除同一归属错误，按新明确的[EVD方案复审门禁](../devSpec/change-evidence.md#72-重复阻塞先复审方案再继续)停止受影响路径的候选、生产补丁和E2E扩展。原正式结果0/1与主优化实际拒稿—修订—当前稿独立通过分别保留。[唯一设计](../optimization/to_verify/normative-context-acquisition.md)已改为输入与机制复审，生产仍为选证v7、来源v1，重新准入须有新因果依据。


## 2026-10-08 核验漏放的最小充分上下文诊断

按用户要求，在唯一设计中预声明最多3逻辑调用、60,000已知tokens及1,800秒原子复审边界，首个充分负例漏放或正控制误拒即停止。生产来源v1-bounded-feedback、Schema、mimo-v2.6-flash、thinking、480秒deadline和原恢复策略保持；原正式0046无限定放行与封存完整c2加限定拒绝按身份复用，未额外重采样。

从正式实际c2.f2无损裁出127字授权声明，Runtime派生c2.f1；保留同一Artifact的471授权原文、452标题和453非规范性限定，5片段减为1、9项证据减为3。材料来自真实工具结果，但读取参数及引用由分析者选择，故仅为条件Offline Eval。实际SDK请求逐字匹配预声明业务消息，原文、资源版本、URL与行号保真，Source Prompt及输出契约未改变。

首项实际返回空findings，已确认的非规范性指导被写为协议要求仍未识别，语义0/1；正常stop、typed合法、无恢复或传输失败。按声明停止，正确设计指导及无限定两个后续控制均未调用，不能报告为通过或失败。1个逻辑/物理SDK，输入1,897、输出947、合计2,844 tokens，30.2秒，无新增未知；累计已知5,520,173 tokens，历史8次未知SDK消耗保留。完整输入、原始响应、语义审查及账目分别见[输入审计](../../.tmp/verifier-minimal-context-20261008/input-audit.json)、[实际结果](../../.tmp/verifier-minimal-context-20261008/diagnostic-result.json)、[审阅与SDK审计](../../.tmp/verifier-minimal-context-20261008/semantic-review.json)、[成本审计](../../.tmp/verifier-minimal-context-20261008/usage-audit.json)。

该反例否定当前任务在最小充分输入下可靠承担此性质判断，以及“仅补齐限定即可解决”的充分方案；不能据独立随机判决证明裁剪致退化、唯一根因或该类任务普遍不可行。按[QLT新增门禁](../devSpec/quality-security.md#21-核验漏放先验证最小充分上下文)复审核验目标、职责、判据及输入输出契约。无新增生产修改或正式E2E，原完整用户结果0/1与主方案有效局部证据分别保持；[唯一设计](../optimization/to_verify/normative-context-acquisition.md)已同步改写。


## 2026-10-08 最小输入补充真实归属要求后识别

用户要求改变最小输入直至核验器识别。唯一设计先预声明A1追加canonical r4、A2仅重排证据、A3仅精简隔离系统判据三个因果诊断，最多3个负例变体及首个识别变体的2个正控制，共5逻辑调用、60,000已知tokens、1,800秒原子复审边界。各变体负例不重采样，首个识别后停止其他变体；恢复与未知用量独立记录。预声明原文与身份保存在 `.tmp/verifier-input-decision-contract-20261008/preregistered-design.md`。

A1保持原127字错误授权声明、471授权原文、452标题、453非规范性限定、证据次序、来源身份、Runtime c2.f1目录、现行Source v1及输出Schema，只增加实际InteractionTrace.review_criteria投影出的r4：“发送内容必须区分模型能力、应用实现与协议要求这三类归属。”新字段使用隔离typed输入，不修改生产构造。实发SDK业务消息与声明逐字一致，模型mimo-v2.6-flash、thinking、480秒deadline与原恢复策略保持。

首项明确定位c2.f1，引用授权e001和非规范性限定e003，指出将非规范性指导归为协议要求的冲突，目标识别1/1。仅改标签的合法设计指导和真实x-mcp-header协议条款两个正控制均返回空findings，2/2，条件局部合计3/3。A2与A3各三项未调用。反馈同时出现“强制性”，人工只认可其性质归属识别，不据此判稿件明确声明MUST或独立强度错误。结果与实发审阅见[语义审查](../../.tmp/verifier-input-decision-contract-20261008/semantic-review.json)、[输入审计](../../.tmp/verifier-input-decision-contract-20261008/input-audit.json)。

3个逻辑/物理SDK均完成，无恢复、传输失败或新增未知；负例2,520 tokens/41.9秒，指导正例2,233/9.0秒，协议正例1,920/7.7秒，合计6,673 tokens、模型用时58.5秒。输入合计5,523、输出1,150；累计已知5,526,846 tokens，历史8次未知消耗保持，wrapper父记录不重复计账。[账目审计](../../.tmp/verifier-input-decision-contract-20261008/usage-audit.json)拥有各项原始SDK坐标。

最小有效变化是追加真实任务要求，支持任务语境影响局部性质判断的假设。历史无r4漏放与本次有r4识别是独立随机判决，不能作为确定性因果消融或稳定收益证明；本轮仍使用分析者投影的真实限定与正稿，不能证明生产自主取证、连续链或产品E2E通过。261份生产Python源码及.env身份保持，未修改生产或运行正式E2E，原用户结果0/1保留。[活动设计](../optimization/to_verify/normative-context-acquisition.md)已同步输入契约和取证责任的下一步边界。

## 2026-10-09 完整来源输入补充全部要求仍漏放

用户授权开始推进上轮最小方案。唯一设计在调用前声明四个校准样本、最多 4 个逻辑调用、60,000 已知 tokens、1,800 秒原子复审边界及首个清晰反例停止。基于 clean revision `e1ea5412c25d419bdaec928dc02f83f687cc4093` 创建隔离副本，来源契约 `v2-goal-context` 增加 `ResearchSupportInput`、全部冻结要求及其局部语境说明；输出 Schema、模型 `mimo-v2.6-flash`、thinking、480 秒 deadline 及原恢复策略保持。本轮输入与说明共同变化，结论限定到整体契约。预声明设计、候选 patch 和四项输入保存在 `.tmp/verifier-goal-context-calibration-20261009/`。

首项使用正式失败 c2 完整 711 字、5 片段及 9 项实际证据，沿候选 `verification_steps` 物化并逐字匹配原请求，第 453 行限定仍未给出。实际 SDK 业务消息与预声明逐字一致，全部 9 项验收要求和 r4 均进入；来源身份、原文和片段保持。核验正常 `stop`、typed 合法，返回空 `findings`，未指出既定性质支持缺口，目标识别 0/1。该反例否定依赖本次 Source 拒稿触发补证的方向；历史已有真实限定且追加 r4 的条件 3/3 按原身份保留。

按停止条件，其余三个校准样本未调用，连续链和正式 E2E 均未执行；原完整用户结果 0/1 保持。新增 1 个逻辑、1 个物理 SDK，3,864 输入、545 输出，合计 4,409 tokens，12.3 秒，无恢复或新增未知；wrapper 父记录不重复计账。累计 5,531,255 已知 tokens，历史 8 次未知用量保持。[实发审计](../../.tmp/verifier-goal-context-calibration-20261009/sdk-input-audit.json)、[语义审查](../../.tmp/verifier-goal-context-calibration-20261009/full-original-review.json)、[账目](../../.tmp/verifier-goal-context-calibration-20261009/usage-audit.json)及[结果](../../.tmp/verifier-goal-context-calibration-20261009/REPORT.json)保存原始坐标。262 份当前生产 Python 文件及 `.env` 身份保持，隔离候选未迁生产。[活动设计](../optimization/to_verify/normative-context-acquisition.md)已同步复审首次来源核验前的必要上下文取得与物化责任。

## 2026-10-09 逐层上下文清理与性质限定对照

按用户要求，在唯一设计先声明三层干扰清理及条件信息补齐对照。固定本次失败的隔离来源 `v2-goal-context`、系统 Prompt、输出 Schema、`mimo-v2.6-flash`、thinking、480 秒 deadline 及原恢复策略；原完整失败按身份复用，不额外重采样。预声明最多 3 个清理负例、1 个补事实对照和 2 个正控制，共 6 个逻辑调用、70,000 已知 tokens、1,800 秒原子复审边界。每个不同输入各调用一次，先封存、审阅再进入下一预声明比较。

三层依次为 C1 删除其他稿件声明、C2 再删除其他证据、C3 再只保留 canonical r4；原 127 字授权声明、真实第 471 行及原要求文字保持，来源身份、URL 和行列保真。Runtime 将 c2.f2 映射为局部 c2.f1，删除引用后 e004 重新物化为 e001。实际目标识别 0/3：C1、C3 返回空 `findings`；C2 虽拒稿，却把“规范要求”解释为 MUST 级义务，按 should/must 差异否定，未正确识别实际性质支持缺口。无关或错误理由的拒稿不计为目标成功。

C4 保持 C3 的 Prompt、稿件、r4 及授权原文，仅补入已封存真实读取的第 452 行标题与第 453 行非规范性限定。实际定位 c2.f1、引用 e001/e003，指出该限定与协议要求归属的冲突，目标识别 1/1。反馈仍含 MUST 强度夸大，本轮只认可独立性质冲突，不据此判整份报告准确。相同最小 r4 契约下，合法设计指导与真实 x-mcp-header 协议条款正控制均返回空 `findings`，2/2。全部要求版本的两个控制未调用，完整有据稿、连续链及正式 E2E 未执行。

实际 6 个逻辑及物理 SDK 完成，6 份 wrapper 父记录排除，无恢复或新增未知。C1 为 3,510 tokens，C2 为 3,458，C3 为 2,711，C4 为 5,700，指导控制为 2,427，协议控制为 1,842；合计 12,738 输入、6,910 输出、19,648 tokens，模型用时合计 140.7 秒。累计已知 5,550,903 tokens，历史 8 次未知用量保持。[SDK 审计](../../.tmp/verifier-context-denoising-20261009/sdk-input-audit.json)、[语义审查](../../.tmp/verifier-context-denoising-20261009/semantic-review.json)、[实际账目](../../.tmp/verifier-context-denoising-20261009/usage-audit.json)及[结果](../../.tmp/verifier-context-denoising-20261009/REPORT.json)拥有各项坐标。

本组是分析者裁剪与真实选证投影的条件 Offline Eval。实际消息逐字匹配，Prompt、输出协议和来源保真；262 份生产 Python 及 `.env` 保持，没有生产迁移或 Product E2E。清理目标 0/3 与补事实对照 1/1 支持先审查必要信息取得和物化，不能证明唯一根因、稳定正确率或完整上下文无干扰。[唯一设计](../optimization/to_verify/normative-context-acquisition.md#2026-10-09-上下文干扰清理与信息对照)已同步结果和反馈措辞边界，原正式用户结果 0/1 与主方案有效机制分别保持。

## 2026-10-09 通用规范性质单点的真实轨迹回放

用户要求核验点通用、反馈对应能力用例、所有用例来自正式输入及真实中间结果，并将后续未识别情况归入已有点或补充通用点。唯一设计在调用前声明 N1 至 N4、最多 4 个逻辑调用、60,000 已知 tokens、1,800 秒原子复审边界及前项完整资格门禁。本轮隔离来源 `v3-normative-status-only` 只判断规范性质支持关系，三个反馈字段解释同一个发现；Prompt 不含具体协议、网站、章节、行号、固定角色或答案。标签仅在评测侧持有。

四项输入来自已封存正式中文 HTTP 运行 `irun_d46adae369924211` 的原物理 SDK `0049`／`0064`／`0047`／`0039`。正式用户原请求、完整稿件、证据、引用、片段目录、原响应与先后修订均保持原身份，旧档 263 个 checksum 已核对。N1 使用完整 378 字 c3、5 项证据和 3 片段，没有加入用户验收要求、章节限定或历史反馈，没有分析者裁剪、补证或理想中间结果。实发业务消息与原请求逐字一致，Schema 指令、`mimo-v2.6-flash`、thinking、服务方配置和恢复保持，只有通用单点系统判据变化；当前回放属于条件 Offline Eval，不是新的正式产品轨迹。

N1 返回一个发现，绑定 c3.f2 和实际 e002／e003，指出实践建议归属缺证。原预声明目标识别、定位、相关引用各 1/1 保留；当前复审只认可缺证发现，归入证据充分性，不计为规范性质一致性成功。该输入缺少性质前提，无法验证实际性质归属正误。`unsupported_assertion` 又把“实践建议”解释为“即非规范性指导”，超出原稿断言，反馈忠实性 0/1、原完整用例资格 0/1 保持；当前归入共同的“核验反馈／实际断言忠实性”，不据此认定充分输入下的性质比较已失效。旧封存归类原样保留，修正的是能力解释。N2 至 N4 未执行；本轮不主张新候选独立收益，也不改写原 grader 或含混句标签。

实际 1 个逻辑、1 个物理 SDK 完成，1 份 wrapper 父记录排除，无恢复或新增未知；输入 2,055、输出 946，共 3,001 tokens，20.5 秒。累计 **5,553,904 已知 tokens**，历史 8 次未知用量保持，不补零。262 份生产 Python 及 `.env` 未变化，候选未迁生产，连续链、正式 target、发布矩阵和停用单元测试均未执行。明确性质冲突的完整正式样本、清晰强度负例及未执行控制仍为覆盖缺口。

实际请求与候选通用性见[SDK 输入审计](../../.tmp/verifier-normative-status-focus-20261009/sdk-input-audit.json)，结果及停止依据见[语义复核](../../.tmp/verifier-normative-status-focus-20261009/N1-review.json)、[成本审计](../../.tmp/verifier-normative-status-focus-20261009/usage-audit.json)与[本轮结果](../../.tmp/verifier-normative-status-focus-20261009/REPORT.json)。[唯一设计](../optimization/to_verify/normative-context-acquisition.md#实际结果与复审边界)已同步识别与反馈分别计分、复审及恢复入口；[能力映射](../optimization/conversation-source-support.md#核验点反馈与能力用例映射)拥有归类，QLT 拥有通用规则，原完整用户结果保持 0/1。

## 2026-10-09 来源核验统一分类契约的首例

用户授权结合阻塞推进落地，唯一设计在实现前声明五个完整正式样本及停止门禁，最多 5 逻辑调用、100,000 已知 tokens、1,800 秒原子复审边界。隔离来源 `v2-classified-findings` 在一次决策中判断每个实际发现，必填五类 `category` 并给出与类别一致的说明；writer `v18-classified-feedback` 增加类别消费说明。候选只改研究契约与 Prompt 两个文件，生产及 `.env` 保持，输入不注入用户要求、理想反馈或额外上下文。

原正式运行 `irun_d46adae369924211` 的 `0049`／`0064`／`0047`／`0039`／`0058` 完整 SDK 输入及原响应均冻结，旧档 263 个 checksum 复核。实际只调用 K1，即原 N1 的 378 字 c3、5 证据、3 片段；模型业务消息逐字等于正式原请求，候选 Source Prompt 和新分类 Schema 进入实发 SDK。模型 `mimo-v2.6-flash`、thinking、响应模式、480 秒 deadline 和恢复保持，只有声明的 Source 判据及输出 Schema 变化。

K1 正确发现两个缺证：c3.f2 的实施归属及建议依据缺失，引用 e002／e003；c3.f3 的 output schema 指代缺失，引用 e005。两项均归 `insufficient_evidence`，两个实际断言字段忠实。原目标缺证识别 1/1、一个样本内分类 2/2；定位和引用正确，不能把两项发现当两份独立样本，也不计作规范性质一致性通过。

第一项 `missing_premise` 仍把实践建议解释为“而非协议要求或强制条款”，在所缺前提中加入性质排斥；建议性强度不能排除规范性的推荐条款。反馈忠实性 0/1，完整样本资格 0/1，归入共同“核验反馈／实际断言忠实性”。类别及实际断言正确，不覆盖说明的错误解释。按预声明停止 K2 至 K5，writer 实际修订、后置核验及正式 target 未到达；不得以历史修订代替本轮连续消费。

实际 1 逻辑／物理 SDK 完成，1 份 wrapper 父记录排除，无重试或新增未知，输入 2,328、输出 2,860，共 **5,188 tokens**、57.4 秒。累计 **5,559,092 已知 tokens**，历史 8 次未知用量保持。候选增 9 删 12 行，净减 3 行是源码行数记录，不能据序列化形式声称可读性或复杂度收益；实质新增一个必填类别，没有新调用阶段、状态或接口。262 份生产 Python 保持，候选未迁入，完整发布矩阵及停用单元测试未执行。

具体结果、说明反例、实发输入及用量见[结果](../../.tmp/source-finding-classification-20261009/REPORT.json)、[语义复核](../../.tmp/source-finding-classification-20261009/K1-review.json)、[SDK 审计](../../.tmp/source-finding-classification-20261009/sdk-input-audit.json)、[账目](../../.tmp/source-finding-classification-20261009/usage-audit.json)。[唯一设计](../optimization/to_verify/normative-context-acquisition.md#分类候选首例结果与停止复审)已同步停止及复审；显式分类未充分解除反馈阻塞，下一准入先取得实际断言解释的新因果依据。规范性质、强度明确冲突及四个未执行控制仍缺能力证据，原完整用户结果 0/1 与主方案有效局部证据保持。

## 2026-10-09 单项反馈说明与真实消费续接

归档 `.tmp/source-feedback-single-reason-20261009/` 在唯一设计先行后完成五个完整正式输入回放：来源 `v3-single-explanation` 与 writer `v19-single-explanation-feedback` 仅在隔离源码，Finding 保留五类、定位及证据引用，将三个解释字段收敛为 `error_description`。M 正式身份、原稿和全部证据保持，SDK 业务输入与输出契约另审计；模型、thinking、480 秒 deadline 和恢复保持。

L1=`0049` 两处缺证、L3=`0047` 搜索摘要出处缺证、L5=`0058` 回传流程及 schema 指代两处缺证的分类、定位、引用和说明均成立；L2=`0064` 真实修订、L4=`0039` 合法流程与认知限制均返回空发现。完整资格 5/5，三项非空反馈忠实性 3/3，五个缺证发现分类 5/5；不计为充分证据下的性质或强度冲突能力。该组每项一次，不主张独立因果收益或稳定性。

五个逻辑／物理 SDK 已完成，无重试、恢复或新增未知，35,311 tokens、253.3 秒；当前累计 5,594,403 已知 tokens、8 次历史未知。完整状态续接的 Context 审计已通过：正式 `0060` 全部业务资料、稿件和要求保持，仅消费新实际 L5 报告及其恢复原文；八个旧版本 Source 报告过期不复用，原完整快照旁存。首段真实选证、writer、canonical 编辑及 c1 Source 已执行，随后 c2 的已有搜索摘要出处缺证被准确指出，首段 Runtime 整链 0/1；c3 新来源及覆盖未到达。四个完成 SDK 新增 71,074 tokens、365.6 秒，无重试或新增未知，累计 5,665,477 已知 tokens、8 次历史未知。续修保持候选，实际 writer 撤回摘要归属并加入官方流程引用；新 Source 却在 c2.f5 把“两条要求”解释成排斥推荐，反馈忠实性及续修完整资格 0/1，当前已停止并撤回该版本准入。三次完成 SDK 为 53,328 tokens、216.2 秒，无重试或新增未知；整轮十二次物理 SDK 为 159,713 tokens、835.1 秒，累计 5,718,805 已知 tokens、八次历史未知。原出处缺口实际修复的局部事实保留，c3 新来源及覆盖仍未到达；不是 Product E2E，也未迁生产。原 K1 失败、M 用户结果及既有主方案检查点均按原身份保留。

## 2026-10-09 断言维度与证据关系隔离诊断

归档 `.tmp/source-assertion-relation-20261009/` 在[唯一设计](../optimization/to_verify/normative-context-acquisition.md#分类维度与证据关系的有界修复)先行后实现隔离 Source `v4-assertion-relation`、writer `v20-classification-basis`。同一次 Source 提交实际断言维度、证据关系及理由，Runtime 推导错误投影；没有新增模型阶段。六项实现前固定用例均来自 M 正式输入或同轨迹完整真实修订，实际业务输入不裁剪、不补证；候选只改变输出契约及职责内 Prompt。

实际执行 A1 一项，A2 至 A6 按首错停止未执行。A1 是实际续修的完整 c2、17 项证据与 6 个片段；SDK 业务 messages、Schema、usage 与冻结输入及逻辑响应一致，一次父记录不计物理调用。模型返回 13 项判断，类型、引用、范围和完整片段覆盖校验通过，错误投影为空。c2.f5 的强度关系为 `not_asserted`，原强度误拒检查点 1/1；两项规范性质正向判断却将 should／祈使式当作性质已成立的依据，实际断言及依据忠实性失败，完整资格 0/1。该失败属于实现前固定判据，不是新增成功门槛；不计为稿件明确性质冲突样本。

一次完成物理 SDK，输入 4,733、输出 2,980，合计 7,713 tokens；45.8 秒，无重试或新增未知。累计 5,726,518 已知 tokens、8 次历史未知。候选准入撤回，262 份生产 Python 与 `.env` 保持；writer 实际消费未执行，没有新增 Product E2E。旧五项 5/5、原正式用户结果 0/1 与既有机制检查点分别保留。

实际结果见[报告](../../.tmp/source-assertion-relation-20261009/REPORT.json)、[完整复核](../../.tmp/source-assertion-relation-20261009/A1-review.json)及[实发审计](../../.tmp/source-assertion-relation-20261009/sdk-input-audit.json)。下一准入先复审性质断言的成立条件和真实依据，详见[本轮停止结论](../optimization/to_verify/normative-context-acquisition.md#断言关系首例结果与性质前提复审)；未继续付费模型调用或生产补丁。

## 2026-10-09 移除额外输出的直接分类验证

`.tmp/source-direct-category-20261009/` 在[唯一设计](../optimization/to_verify/normative-context-acquisition.md#移除额外输出后的直接分类验证)先行后实现隔离 Source `v5-direct-category`、writer `v21-direct-category`。删除额外判断类型、`aspect`／`relation`／`reason`、通过项记录、类别派生和输出覆盖校验，保留五类错误、定位、`error_description` 和证据引用；引用及有序范围由既有原生边界校验。相对 v4 候选三个文件增 21 删 73 行，净减 52；无生产改动。

预声明六项 A1 至 A6 沿前次完整正式输入及真实续修，各一次、首错停止。实际执行 2/6：A1 空发现，原强度误拒未复现，完整通过；A2 找到 c3.f2 实施及实践建议归属缺证，`insufficient_evidence`、定位及 e002／e003 正确，但说明补入“建议性实践，而非协议要求”的排他含义，与 K1 相同的说明反例复现。目标识别及类别选择 2/2，非空发现类别 1/1，非空反馈忠实性 0/1，完整资格 1/2，即已执行样本 50%；A3 至 A6 未执行，不把四项计为成功或纳入已执行准确率。

两项业务 messages、实际 Schema、模型及 thinking、用量均与冻结身份相同，Native 引用和范围检查通过。审计脚本初版误将带 Schema 的父记录当作纯业务 messages 比较；A2 在退出码核对前已启动。修正匹配边界后复用同一实际响应完成审计，没有重采样或修改业务输入，此偏差由[脚手架记录](../../.tmp/source-direct-category-20261009/audit-script-failure.json)保留。

A1 输入 4,463、输出 259，4,722 tokens、10.3 秒；A2 输入 2,185、输出 6,772，8,957 tokens、111.3 秒。两个完成物理 SDK、两个父记录排除，合计 13,679 已知 tokens、121.6 秒、零重试及新增未知。累计 5,740,197 已知 tokens、8 次历史未知。候选仅供封存诊断，语义修复未准入；262 份生产 Python 和 `.env` 保持，没有新增 Product E2E 或 writer 模型消费。旧五项 5/5、原正式用户结果 0/1 及已有机制分别保留。

首段结果见[首停报告](../../.tmp/source-direct-category-20261009/first-stop-report.json)、[A1 复核](../../.tmp/source-direct-category-20261009/A1-review.json)、[A2 复核](../../.tmp/source-direct-category-20261009/A2-review.json)、[输入冻结](../../.tmp/source-direct-category-20261009/input-audit.json)、[A1 SDK](../../.tmp/source-direct-category-20261009/A1-sdk-audit.json)及 [A2 SDK](../../.tmp/source-direct-category-20261009/A2-sdk-audit.json)。分类和说明分别计分，首段失败在说明忠实性；原停止事实保留，随后用户明确要求的剩余续验见下节。

## 2026-10-10 原六项直接分类用例续验完成

用户明确要求“继续执行测试，实际上移除字段能达到同样的效果，就应该移除”，沿唯一设计完成原 A3 至 A6。原 A1、A2 响应和复核保持，候选 `v5-direct-category`／writer `v21-direct-category`、六项完整业务输入、模型、thinking、语义判据及 150,000 token 总上限保持；没有重采样。初始 1,800 秒墙钟在 A5 调用前触发，尚无 A5 attempt 或 SDK；记录停止后复审，四次模型实际合计 201.1 秒、23,779 tokens，剩余两项在单独 1,200 秒窗口执行，恢复依据及边界由[设计](../optimization/to_verify/normative-context-acquisition.md#用户要求继续完成剩余真实用例)拥有。

| 用例 | 用户所需核验结果 | 实际结果 | 完整资格 |
| --- | --- | --- | --- |
| A1 | 实际续修的强度误拒控制 | 空发现，未补出 MUST | 通过 |
| A2 | 实施及实践建议归属缺证 | c3.f2 缺证类别正确，说明增加排他性质 | 失败 |
| A3 | 真实 MUST／SHOULD 合法控制 | 空发现 | 通过 |
| A4 | 出处缺证与含混表述边界 | c2.f1 缺页面身份被忠实归为缺证 | 通过 |
| A5 | 协作及认知限制合法控制 | 空发现 | 通过 |
| A6 | 回传步骤与对象指代两处缺证 | 仅回传缺证被识别，漏掉对象指代前提 | 失败 |

六项全部完成，零未执行。已输出三个错误发现类别正确 3/3（100%），对应定位及引用正确；非空反馈忠实性 2/3（66.7%），整项识别完整性 5/6（83.3%），完整资格 4/6（66.7%）。A6 双缺口识别 1/2；已输出类别分母不包含遗漏项，不能称所有错误分类与识别 100%。三项合法控制 3/3，原强度误拒检查点 1/1，已成立部分按本组判据保留。

六个完成物理 SDK、六个父记录排除，40,664 tokens、270.7 秒、零重试或新增未知；累计 5,767,182 已知 tokens 与八次历史未知。A3 为 4,601 tokens／23.5 秒，A4 为 5,499／56.0 秒，A5 为 10,216／20.6 秒，A6 为 6,669／49.1 秒；首两项成本按上节原身份保留。全部业务 messages、Schema、模型及 thinking、用量、原生引用及有序片段范围校验通过。

额外输出和净减 52 行维护逻辑保持移除，后续只保留直接错误分类、定位、说明和引用；整体核验尚未达到原 6/6 条件，分别处理 A2 实际断言解释及 A6 对象指代缺证漏检。对应已有通用点见[能力映射](../optimization/conversation-source-support.md#核验点反馈与能力用例映射)，不新增任务专用类别或字段。候选未迁生产，262 份生产 Python 与 `.env` 保持；没有新增 Product E2E 或 writer 模型消费，原正式用户结果 0/1 和旧五项 5/5 保留。

完整结果见[最终报告](../../.tmp/source-direct-category-20261009/REPORT.json)、[A6 复核](../../.tmp/source-direct-category-20261009/A6-review.json)及 [A6 SDK](../../.tmp/source-direct-category-20261009/A6-sdk-audit.json)。原墙钟停止见[调用前记录](../../.tmp/source-direct-category-20261009/A5-precall-budget-stop.json)，续验身份见[剩余两项计划](../../.tmp/source-direct-category-20261009/remaining-two-plan.json)。输出收敛的必要性与语义结果分别记录，不将独立随机模型结果解释为字段变化的唯一因果。

## 2026-10-10 多项输出提示与推理取舍诊断

新归档 `.tmp/source-multiple-findings-20261010/` 在[唯一设计](../optimization/to_verify/normative-context-acquisition.md#多项输出提示与已发现问题的取舍诊断)先行后，只替换 v5 的既有多项输出句，隔离 Source 为 v6-multiple-findings。明确一个 findings 数组中每个独立错误占一个对象、同类别可重复，并要求发现一项后继续核查；一个文件、净增 50 个指令字符，Schema、writer、Runtime、完整业务输入及服务方配置保持。预声明 A6 双缺口与 A3 合法控制各一次、组条件 2/2，首错停止；两次逻辑调用及 40,000 新已知 tokens 上限、首调用起 1,200 秒墙钟，原 480 秒服务 deadline 和恢复保持。

实际执行 A6 一项，仍仅输出 c3.f2 回传步骤原文缺失，insufficient_evidence、e006／e007、定位和说明均正确；c3.f4 对象指代前提未报告。双缺口识别 1/2，完整资格为已执行 0/1；已输出分类及说明各 1/1，不能覆盖漏报，A3 一项未执行。首项失败后停止，无重采样、附加补丁或生产迁移。

原、新物理 API 响应的已有推理均明确讨论第二处候选缺证后选择不报告。本次记录还表达了对证据安排或评分预期的猜测；与最终只有一个发现一致，可用于定位证据充分性及合理转述的取舍，不计实际识别通过或完整隐藏因果证明。概要和身份见[原判断](../../.tmp/source-multiple-findings-20261010/baseline-decision-review.json)、[新判断](../../.tmp/source-multiple-findings-20261010/A6-decision-review.json)，不复制整段推理。下一复审区分一般命名改述与新增具体对象归属并核对标签，原双缺口判据及失败不追溯改分。

一次逻辑及完成物理 SDK、一个父记录排除，8,812 tokens（输入 2,782、输出 6,030）、103.1 秒，零重试或新增未知。v5 同完整输入的输入为 2,752，增加 30 tokens；耗时超过该样本原耗时两倍，已在原子样本结束后停止。累计 5,775,994 已知 tokens 与八次历史未知。全部业务 messages、Schema、版本、模型、thinking、用量及原生引用和片段范围检查通过；没有新增 Product E2E、writer 模型消费或单元测试，旧六项成绩及原正式用户结果保持。

规则已同步至根入口及 [CTX 推理记录审计](../devSpec/context-memory-retrieval.md#12-system-prompt-与-context-的设计及问题分析)，EVD 重复阻塞与 QLT 漏放诊断引用同一正文；这是基于已有证据的规范修正，规范检查不作为本次模型能力成功。结果见[本轮报告](../../.tmp/source-multiple-findings-20261010/REPORT.json)、[完整输入审计](../../.tmp/source-multiple-findings-20261010/input-audit.json)、[A6 SDK](../../.tmp/source-multiple-findings-20261010/A6-sdk-audit.json)及[语义复核](../../.tmp/source-multiple-findings-20261010/A6-review.json)。

## 2026-10-10 原核验判决依据的中性追问

按用户要求说明核验器的实际决策依据及其与任务要求的关系，在[唯一设计](../optimization/to_verify/normative-context-acquisition.md#原判决依据的中性追问)先行后执行一个隔离说明诊断。完整保留 v6 A6 实发 SDK 的三条消息和实际最终答案，作为材料向同一 mimo-v2.6-flash 模型提出三项中性问题；未提交原推理、预期分类或错误数量，不裁稿、不补证。诊断用普通中文说明输出，原 Source 任务作为复审材料，属于事后说明，不是正式 Source 请求重跑。

模型维持原判决：回传步骤是新增内容性前提，缺原文须报告；schema 被解释为结构化结果所使用 schema 的一般名称，认为剩余命名精度不需修复。它将该取舍联系到“只报告需要修复的实际错误”，同时承认具体命名仍需补上文。决策及任务边界分析由设计拥有；原推理中的评分猜测仍是已发生事实，后续说明不覆盖。下一步审定原稿是否确实新增具体对象身份，再确定必要缺证报告的最小修正。

预算为一个逻辑及物理调用、20,000 新已知 tokens、首调用起 1,200 秒，服务 deadline 480 秒，禁用重试和结构恢复；一次响应即停止。实际一个逻辑及完成物理 SDK，零父记录、重试、恢复或新增未知；正常 stop，268.0 秒，3,354 输入、16,319 输出，合计 19,673 tokens。累计 5,795,667 已知 tokens、八次历史未知。实发请求与冻结请求一致，原材料完整性及 262 份生产 Python、.env 保持通过。

本轮不计核验准确率、优化成功或新的 Product E2E，不改原六项 4/6、A6 双缺口 1/2 及 v6 停止结果。没有生产 Prompt、Schema、字段、类别或模型流程修改，没有 writer 消费或单元测试。结果见[报告](../../.tmp/source-decision-counterquestion-20261010/REPORT.json)、[实发审计](../../.tmp/source-decision-counterquestion-20261010/sdk-audit.json)、[答复](../../.tmp/source-decision-counterquestion-20261010/answer.txt)和[原档身份](../../.tmp/source-decision-counterquestion-20261010/original-call-identity.json)。
