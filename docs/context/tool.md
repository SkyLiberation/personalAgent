# 工具输出超限的处理

## 会话文件替换决定

状态：主链路已接入。`filter-low-selling-products` 的第 17 至 18 次请求保留了已有消息，但新增商品原件同时改写四份工具 Schema 的资源 ID 枚举，MiniMax 报告的命中比例从 97.94% 降至 5.13%。同一真实轨迹把早先外置的商品页作为 Python 输入，文件续读和 Python 输入都需要保留。[实发差异](../../.tmp/step-budget-20261116/remaining-prefix-cohort.json)

| 需求 | 决定 | 验收 |
| --- | --- | --- |
| F1 回执提供可执行的续读入口 | 采用 [DeepSeek Harness 固定实现](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/spill/spill-policy/src/index.ts#L92-L150)。超限后将原始正文一次写入应用数据目录下的会话子目录，原调用回执提供文件路径。路径相对会话文件系统根。继续复用 Artifact 的不可变文件、摘要和内部来源身份，支持引用、跨轮恢复和 Bash 命令恢复。删除 `action_output` 通用成品写入口。 | 回放真实商品结果，校验原始字节、文件提交、回执配对、限长预览、只读分页、搜索命中及续页。 |
| F2 稳定工具契约与权限 | 替换旧三种结果读取能力为 `read_file` 和 `grep_file`。已经授权的普通 Artifact 通过 `artifacts/<ID>` 路径读取。Runtime 依据当前任务已提交事实匹配精确路径，文件存储继续校验归属和内容摘要。工具 Schema 保持参数形状，观察到的新文件只加在工具回执中。Bash 容器可用回执中的原相对路径读取卸载文件。 | 同轨迹对照新增文件前后，Schema 字节一致，旧工具名消失，指定路径可读，跨会话、未发布路径和路径穿越请求被拒绝。核对相对路径对应的 Bash 工作区原件。 |
| F3 保留跨轮依据 | 原调用回执携带路径，压缩后通过已有原件定位区继续提供路径。成功续读及搜索仍按内部来源和正文范围归因。失败保存只返回限长预览和原因。按已保存结果约束重复抓取。 | 回放归档中的真实回执及其有效后续读取。验证文件重启可读，压缩定位能指回同一文件，保存失败不产生可执行路径。使用同端点可比的 MiniMax replay 核对缓存用量；正式用例结果独立记录。 |
| F4 按需补读 | 外置结果是否还需查阅由模型依据当前用户目标决定。Conversation 按原交付契约处理最终答复，移除逐份检查外置结果读取回执的规则和对应拒绝提示。 | 从 GDP 正式轨迹第 26 轮交付判定前的已提交状态，通过正式 HTTP 入口回放。相同输入下旧运行时拒绝，新运行时提交原答复，零新增模型请求和外部写入。原整题评分和历史运行保留独立身份。 |

文件路径是会话内的模型接口。目录采用 DeepSeek Harness 的 `session-<hash>` 分组，存储位置为 `<应用数据根>/tool-output/session-<hash>/<调用摘要>.txt`。当前配置的应用数据根为 `data/`。模型收到从应用数据根起算的路径，Runtime 按路径和权限定位文件。Artifact 管理不可变字节和元数据，Conversation 从 Journal 投影当前任务可读范围并生成回执。评测产物写入 `data/e2e_traces/toolathlon/`。已有归档可通过统一的文件工具读取原有 Artifact 字节。验证不通过时撤回本次替换版本。[DeepSeek 本地目录实现](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/spill/spill-local/src/store.ts#L72-L80)

主循环的 System Prompt 说明读取范围和证据使用规则。读搜工具的参数名称、类型和续读坐标由各自的 Schema 与工具说明声明，具体路径和续读位置来自材料和回执。Runtime 负责路径解析、权限和身份校验。LongDS NYC Task 2 首轮第 17 步的实发请求同时带有 `resource_id` 的旧全局指令与要求 `file_path` 的工具 Schema。删除中英文主提示中的读搜参数说明，将调用契约交给已有的工具声明。[实发请求](../../.tmp/nyc2-hist-20261119/t2/capture/sdk/ef6a41896e244f12ad3fd38f6820658b.http.request.json)

验收使用上述真实阶段输入。重新渲染中英文主提示，核对正文仅变更读搜说明，工具声明、消息顺序和原续读回执保持。用完整英文阶段输入和同一模型做一次请求回放，记录读搜选择、实际参数及停止原因。该回放以复现合法文件参数为目标，评分和整题表现独立计算。

同一契约也用于搜索分页、阅读反馈和摘要恢复。搜索分页沿用原 `file_path`；续读指向实际声明的 `tool_read_file`。工具额度耗尽会撤下对应声明，已发生的读搜调用和回执仍按原身份接续。

首次回放核对中英文的主提示与读搜 Schema。该次英文拟发请求仅改动 System Prompt 的读搜说明，原工具声明和续读位置均保留。MiniMax 用 `tool_read_file` 对 `/tmp/out/report.md` 发出合法的 `file_path` 参数，从第 34 行读取。该次回放止于模型提议。[请求核对](../../.tmp/file-schema-prompt-20261119/audit.json) · [模型回放](../../.tmp/file-schema-prompt-20261119/replay-report.json)

后续复核用第 16、17 步实发请求重建当前中英文契约。工具集相同且余额变动时，System Prompt 和工具定义逐字一致。用第 17 步的更新请求实发一次，MiniMax 再次返回带合法 `file_path` 的 `tool_read_file`。[当前上下文核对](../../.tmp/dsh-budget-20261119/context-audit.json) · [当前模型回放](../../.tmp/dsh-budget-20261119/file-model-replay.json)

## 1. 触发条件

普通工具回执按 JSON 序列化后的 UTF-8 体积检查 **50 KiB（51,200 字节）**上限，正文、预览和元数据共用。续读与搜索窗口沿用独立的 20,000 字符限制，完整模型请求继续独立检查容量。[体积检查](../../src/personal_agent/application/conversation/observation_bounds.py) · [原始契约](../adr/0013-bounded-observation-and-offloaded-read.md)

## 2. 外置原件并返回限长回执

- **原件保存成功。** Runtime 将工具实际取得的内容保存为可读资源。主模型收到与原调用配对的限长回执，内含状态、省略信息、完整文件路径和一份文本预览。续读指引只列出当轮已声明且允许访问该原件的工具。没有可用预览时，沿用回执中的元数据。
- **原件保存失败。** 回执保留可提供的限长正文，并说明原件不可用的原因。工具本身在抓取或执行时已截断、失败的内容，按实际取得的范围记录。

Runtime 从执行时的完整文本生成 `observation_excerpt`。优先使用工具提供的正文，缺少正文时使用准备外置的序列化文本。预览按原顺序从开头连续保留，在实际序列化后的剩余空间内尽量多放原文。单行过长时允许显示行首。新回执用 `retrieval.original_bytes` 记录原始回执的字节数，用 `observation_excerpt_omitted_chars` 记录预览省略的正文字符数。已有归档回执继续使用其中可用的预览和原件引用。

会话记录保存已提交的回执及内部来源引用，完整正文由 Artifact 写入应用数据目录的 tool-output 会话子目录。主请求在已有预览上装配当轮读搜指引，并再次计量整个回执。[回执生成](../../src/personal_agent/application/conversation/service.py) · [模型请求投影](../../src/personal_agent/application/conversation/context_materialization.py)

### 原生工具消息的展示

主模型在与原调用配对的工具消息里依次收到工具状态、适用的原件定位和续读说明、原文预览。状态、文件路径、原件总行数和预览省略量优先用文字说明。需要精确传递的工具数据与来源引用单独列出。预览正文在独立标题下逐字显示，保留换行、引号和反斜杠。原件保存失败时，预览前说明不可续读的原因。来源证据继续由实际读取的行及其引用身份提供。

预览展示由 `render_interaction_input` 在原生工具消息路径生成。会话记录、核验视图和未配对的结构化执行输入沿用各自契约。单条预算继续约束回执载荷，最终模型请求由现有容量检查计量。[回执渲染](../../src/personal_agent/application/conversation/interaction_projection.py) · [调用配对](../../src/personal_agent/application/conversation/model_history.py)

### 普通 MCP 回执正文去重

`k8s-redis-helm-upgrade` 的第 31 个模型请求包含 45 条原生工具消息，每条都同时展示 `data.content`、`data.raw.content` 和从同一内容块拼接的 `data.text`。一次 7,568 字符的文件读取形成 24,136 字符的工具消息，随后随历史重复进入模型请求。[实发请求归档](../../.tmp/ta27-1113-k8s/final-redis-helm-upgrade/k8s-redis-helm-upgrade/product-data/interaction_runs/irun_e4434c8b063b4519/ed48ae1b648a41e887e782f395735a45/request.json)

- **TOOL-CTX-01 正文只展示一次。** 对 MCP 适配器生成的回执，Conversation 在回执渲染处投影模型所需内容。保留 `data.content` 及各内容块，省略完全相同的 `data.raw.content`、由这些文本块原样拼接的 `data.text`，以及与 `data.structured_content` 相同的原始结构化副本。保留不同值、结构化结果、状态、错误和原始回包中的独有元数据。比较采用完整值等价，正文相似或部分相同不触发省略。
- **TOOL-CTX-02 保留结果来源和原件位置。** 展示与历史摘要读取同一去重投影。未配对回执也使用这一投影。工具适配器继续拥有 MCP 校验和完整回包，Conversation 只生成请求内投影。Journal、审计、外置原件、读取授权及预算边界沿用现行契约。
- **验收。** 复用 Redis 样本 31 次已封存模型请求及同轨迹 45 条原始回执，验证调用 ID 和消息顺序、正文与结构化数据保真、重复字段消除以及原件位置保真。用已有 Toolathlon 结构化回执及一份超限 PDF 回执核对结构化结果和原件预览。对比相同历史上重新组装的 SDK 请求 UTF-8 字节数。回放通过后使用原评测入口及预算复跑 Redis 一次，单独记录实际模型用量和官方评分。不同模型轨迹的总量和得分按各自结果解读。

离线回放通过。Redis 31 轮请求体累计从 7,008,709 字节降至 4,301,925 字节，减少 38.6%。末轮从 422,699 字节降至 239,745 字节，减少 43.3%。45 条 Redis 回执、8 条结构化回执和 1 条超限 PDF 回执均通过对应检查。请求体字节用于同输入对照，实际 token 用量由模型服务统计。[回放报告](../../.tmp/mcp-model-dedup-1113/report.json)

原预算下的真实复跑使用 32 个决策轮和 47 次工具调用，计 1,280,897 token。第 28 轮将 Chart 升至 `22.0.0`。官方评分确认版本和自定义配置符合要求，Pod 运行检查未通过，整例评分为 0.8。对话耗尽决策轮数后结束。[复跑报告](../../.tmp/mcp-model-dedup-1113/live/k8s-redis-helm-upgrade/report.json) · [官方评分](../../.tmp/mcp-model-dedup-1113/live/k8s-redis-helm-upgrade/grader.log)

## 3. 续读与跨轮保留

- **需要细节时读取同一原件。** 已知位置时直接读取相应窗口，未知位置时先搜索再读取。长行按返回的续读位置继续。只有实际读取的范围计入已读和引用证据。已有外置结果时，相同抓取请求会被拦截。[Runtime 拦截反馈](runtime-feedback.md#4-工具知识操作与委托准入)
- **历史压缩后的续读。** 近期预览随原工具交换保留。压缩覆盖该交换后，主模型按定位区块中的文件路径和工具名读取原件。[压缩后的字段、消息顺序和快照恢复](agent-loop.md#31-压缩后如何定位工具原件)

GDP 的第 26 轮提交了已写入正确表格的答复。旧检查要求单独获取的 `Country` 原件留下读搜回执，随后模型补读失败。DeepSeek Harness 的外置策略在工具结果中提供恢复入口，主循环在模型返回无工具调用的正文后结束本轮。本工程据此退役额外的交付条件，沿用已装配的答复校验与文件读取权限。[GDP 原始轨迹](../../.tmp/bash-execution-20261117/gdp-fixed/gdp-cr5-analysis/personal/product-data/interaction_runs/irun_e15642cc405443a9/0237.json) · [DeepSeek 主循环](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/core/agent-loop/src/agent.ts#L573-L602) · [ADR 0013](../adr/0013-bounded-observation-and-offloaded-read.md)

同一份已提交状态的 HTTP 回放中，修改前记录 `offloaded_output_unread` 并返回 `limitation`，修改后返回原始 `answer`，两次均无新增模型请求或工具调用。该回放覆盖交付阶段。整例验证见 [Toolathlon 最新复跑](../problems/toolathlon/agent-comparison.md#正式配置与原件预载定向复验)。[修改前](../../.tmp/unread-gate-1117/b/report.json) · [修改后](../../.tmp/unread-gate-1117/c/report.json)

## 4. 已有验证

会话文件替换使用 `filter-low-selling-products` 第 18 次请求对应的 57,109 字节原文进行中英文回放。写盘字节完全一致，回执为 51,200 字节，重启后可按行读取和搜索。首次生成文件前后的工具定义一致。跨会话直接使用路径、路径穿越及无授权路径均被拒绝。该历史回放也验证了当时 Python 工具的文件身份。保存失败时，回执不会生成文件路径。实际线上用量以同用例的独立正式运行记录为准。[回放报告](../../data/e2e_traces/toolathlon/spill-1116/replay-report.json)


真实历史压缩回放使用覆盖 51 项旧历史的快照，校验摘要和文件内容，生成 11 行路径定位提示。[压缩回放](../../data/e2e_traces/toolathlon/spill-1116/compaction-replay.json)

用第 17、18 次真实请求的同一消息，在 MiniMax-M3.1-Flash 端点重做工具 Schema 对照。两组各发 2 次请求并采用独立缓存身份。保留工具选择策略，原件枚举变化组第 18 次命中 128 / 121,177 token（0.11%）；移除枚举组第 18 次命中 112,339 / 118,255 token（95.00%）。该对照验证枚举变化对缓存的影响。[MiniMax 用量](../../data/e2e_traces/toolathlon/spill-1116/minimax-cache-usage.json)

正式复跑中，17 条超限回执在 Windows 深目录写入时返回文件找不到。复现定位到不可变文件提交的临时文件名，它在目标文件名上叠加了随机后缀，使绝对路径超过 Windows 限制。临时文件改用独立短随机名，同目录原子提交和内容校验沿用原契约。最终目录在更深的数据根通过写入和续读。正式复跑止于工作计划参数类型校验，上游评分未通过。[最终正式复跑](../../data/e2e_traces/toolathlon/spill-1116/target-fixed-report.json) · [故障报告](../../data/e2e_traces/toolathlon/spill-1116/target-retry-report.json)

在第 18 次模型阶段回放中，用新回执替换同一商品查询调用的旧回执。模型从回执取得新目录中的正确路径，提交 `tool_read_file`，Runtime 返回原文件前 5 行。[模型回放](../../data/e2e_traces/toolathlon/spill-1116/model-path-replay.json)

2026-11-10 调整单条上限与预览。Toolathlon 已封存的九份超限 PDF 回执中，同一正文在 MCP 回执的多个字段重复出现。旧算法按所有长字段分配空间，九条展示均只有 2,483 字符。新方案采用 [OpenCode 固定版本的 UTF-8 字节上限及开头预览](https://github.com/anomalyco/opencode/blob/3104c1428ec91f809e5ab86631300de41eb6952e/packages/opencode/src/tool/truncate.ts#L76-L139)，保留本工程既有 Artifact 引用、原生调用配对和授权读搜。统一字节上限处理长单行，继续使用已有分页工具。

九份原始回执经现行回执构造和主请求投影回放，均完整展示一份正文文本字段。正文为 3,828 至 11,754 字符，`case1.pdf` 第 1–4 页从 2,483 增至 4,842 字符。以同一真实回执放大正文验证长行截断，回执为 51,199 字节，下一字符即超限。原件保存失败仍给出原文前缀和不可续读原因。历史回放核对了调用配对、旧检查点的原件定位和续读。验证覆盖回执及请求契约，模型选择和整例成绩未重跑。[九条回放](../../.tmp/tool-result-preview-50k-20261110/replay-report.json) · [边界反事实](../../.tmp/tool-result-preview-50k-20261110/boundary-report.json)

2026-11-10 调整原生工具回执展示。前版 Toolathlon 真实回执回放中，长行预览的原文占 45,918 个 UTF-8 字节，作为 JSON 字符串占 50,510 字节。采用 [OpenCode](https://github.com/anomalyco/opencode/blob/3104c1428ec91f809e5ab86631300de41eb6952e/packages/opencode/src/tool/truncate.ts#L124-L139) 和 [DeepAgents](https://github.com/langchain-ai/deepagents/blob/fd3e64ab6b605450bed5a2c22ef2ec84cd40542e/libs/deepagents/deepagents/middleware/_message_eviction.py#L241-L280) 的可读正文形式，保留本工程的结构化来源身份和引用边界。验收重放同一批 PDF 回执及长行反例，核对适配器实际组装的工具消息角色、调用 ID、原文保真、可用续读、保存失败和压缩后定位。普通回执、已读证据行和结构化回执保留原有契约。

展示验证重放 9 条真实 PDF 回执，工具消息保持原调用 ID，正文与工具文本逐字一致。长行反例保留同一份 36,738 字符预览，工具消息正文从 51,458 字节降到 46,891 字节。中英文、原件不可读、结构化输入和第 17、18、27 轮历史回放通过。抽查的 5 条已读原件和搜索工具消息与归档逐字一致。此处核对的是适配器组装结果，整例模型与评分未重跑。[请求回放](../../.tmp/tool-result-preview-display-20261110/replay-report.json) · [展示边界](../../.tmp/tool-result-preview-display-20261110/boundary-report.json)

调整前，同一 PDF 回执的离线回放通过 10 项检查，覆盖预览限长、调用配对、不同请求视图和当轮续读能力。Toolathlon 实际运行中，9 条超限 PDF 回执均携带配对预览、原件引用和合法读取指引，随后读搜了其中 6 个原件。整例因预算结束且上游评分未通过，验证结论限于超限回执机制。[离线回放](../../.tmp/tool-observation-preview-20261110/result.json) · [实发请求审计](../../.tmp/tool-observation-preview-live-20261110/model-input-audit.json) · [整例报告](../../.tmp/tool-observation-preview-live-20261110/target/report.json)
