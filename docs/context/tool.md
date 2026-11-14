# 工具输出超限的处理

## 1. 触发条件

普通工具回执按 JSON 序列化后的 UTF-8 体积检查 **50 KiB（51,200 字节）**上限，正文、预览和元数据共用。续读与搜索窗口沿用独立的 20,000 字符限制，完整模型请求继续独立检查容量。[体积检查](../../src/personal_agent/application/conversation/observation_bounds.py) · [原始契约](../adr/0013-bounded-observation-and-offloaded-read.md)

## 2. 外置原件并返回限长回执

- **原件保存成功。** Runtime 将工具实际取得的内容保存为可读资源。主模型收到与原调用配对的限长回执，内含状态、省略信息、原件 ID 和一份文本预览。续读指引只列出当轮已声明且允许访问该原件的工具。没有可用预览时，沿用回执中的元数据。
- **原件保存失败。** 回执保留可提供的限长正文，并说明原件不可用的原因。工具本身在抓取或执行时已截断、失败的内容，按实际取得的范围记录。

Runtime 从执行时的完整文本生成 `observation_excerpt`。优先使用工具提供的正文，缺少正文时使用准备外置的序列化文本。预览按原顺序从开头连续保留，在实际序列化后的剩余空间内尽量多放原文。单行过长时允许显示行首。新回执用 `retrieval.original_bytes` 记录原始回执的字节数，用 `observation_excerpt_omitted_chars` 记录预览省略的正文字符数。已有归档回执继续使用其中可用的预览和原件引用。

会话记录保存已提交的回执，Artifact 保存完整可续读内容。主请求在已有预览上装配当轮读搜指引，并再次计量整个回执。[回执生成](../../src/personal_agent/application/conversation/service.py) · [模型请求投影](../../src/personal_agent/application/conversation/context_materialization.py)

### 原生工具消息的展示

主模型在与原调用配对的工具消息里依次收到工具状态、适用的原件定位和续读说明、原文预览。状态、原件 ID、原件总行数和预览省略量优先用文字说明。需要精确传递的工具数据与来源引用单独列出。预览正文在独立标题下逐字显示，保留换行、引号和反斜杠。原件保存失败时，预览前说明不可续读的原因。来源证据继续由实际读取的行及其引用身份提供。

预览展示由 `render_citable_input` 在原生工具消息路径生成。会话记录、核验视图和未配对的结构化执行输入沿用各自契约。单条预算继续约束回执载荷，最终模型请求由现有容量检查计量。[回执渲染](../../src/personal_agent/application/conversation/citations.py) · [调用配对](../../src/personal_agent/application/conversation/model_history.py)

### 普通 MCP 回执正文去重

`k8s-redis-helm-upgrade` 的第 31 个模型请求包含 45 条原生工具消息，每条都同时展示 `data.content`、`data.raw.content` 和从同一内容块拼接的 `data.text`。一次 7,568 字符的文件读取形成 24,136 字符的工具消息，随后随历史重复进入模型请求。[实发请求归档](../../.tmp/ta27-1113-k8s/final-redis-helm-upgrade/k8s-redis-helm-upgrade/product-data/interaction_runs/irun_e4434c8b063b4519/ed48ae1b648a41e887e782f395735a45/request.json)

- **TOOL-CTX-01 正文只展示一次。** 对 MCP 适配器生成的回执，Conversation 在原有引用目录和回执渲染处投影模型所需内容。保留 `data.content` 及各内容块，省略完全相同的 `data.raw.content`、由这些文本块原样拼接的 `data.text`，以及与 `data.structured_content` 相同的原始结构化副本。保留不同值、结构化结果、状态、错误和原始回包中的独有元数据。比较采用完整值等价，正文相似或部分相同不触发省略。
- **TOOL-CTX-02 引用按原回执坐标绑定。** 保留行使用原回执摘要、行号和文本。展示与引用解析消费同一目录，省略行不可再引用。未配对回执和历史摘要采用同一去重规则。工具适配器继续拥有 MCP 校验和完整回包，Conversation 只生成请求内投影。Journal、审计、外置原件、读取授权及预算边界沿用现行契约。
- **验收。** 复用 Redis 样本 31 次已封存模型请求及同轨迹 45 条原始回执，验证调用 ID 和消息顺序、正文与结构化数据保真、重复字段消除、原行号引用可回查，以及省略行拒绝。用已有 Toolathlon 结构化回执及一份超限 PDF 回执核对结构化结果和原件预览。对比相同历史上重新组装的 SDK 请求 UTF-8 字节数。回放通过后使用原评测入口及预算复跑 Redis 一次，单独记录实际模型用量和官方评分。不同模型轨迹的总量和得分按各自结果解读。

离线回放通过。Redis 31 轮请求体累计从 7,008,709 字节降至 4,301,925 字节，减少 38.6%。末轮从 422,699 字节降至 239,745 字节，减少 43.3%。45 条 Redis 回执、8 条结构化回执和 1 条超限 PDF 回执均通过对应检查。请求体字节用于同输入对照，实际 token 用量由模型服务统计。[回放报告](../../.tmp/mcp-model-dedup-1113/report.json)

原预算下的真实复跑使用 32 个决策轮和 47 次工具调用，计 1,280,897 token。第 28 轮将 Chart 升至 `22.0.0`。官方评分确认版本和自定义配置符合要求，Pod 运行检查未通过，整例评分为 0.8。对话耗尽决策轮数后结束。[复跑报告](../../.tmp/mcp-model-dedup-1113/live/k8s-redis-helm-upgrade/report.json) · [官方评分](../../.tmp/mcp-model-dedup-1113/live/k8s-redis-helm-upgrade/grader.log)

## 3. 续读与跨轮保留

- **需要细节时读取同一原件。** 已知位置时直接读取相应窗口，未知位置时先搜索再读取。长行按返回的续读位置继续。只有实际读取的范围计入已读和引用证据。本轮成功取得的外置结果还没有任何成功读搜回执时，Runtime 会拦截收尾。已有外置结果时，相同抓取请求会被拦截。[Runtime 拦截反馈](runtime-feedback.md#4-工具知识操作与委托准入)
- **历史压缩后的续读。** 近期预览随原工具交换保留。压缩覆盖该交换后，主模型按定位区块中的资源 ID 和工具名读取原件。[压缩后的字段、消息顺序和快照恢复](agent-loop.md#31-压缩后如何定位工具原件)

## 4. 已有验证

2026-11-10 调整单条上限与预览。Toolathlon 已封存的九份超限 PDF 回执中，同一正文在 MCP 回执的多个字段重复出现。旧算法按所有长字段分配空间，九条展示均只有 2,483 字符。新方案采用 [OpenCode 固定版本的 UTF-8 字节上限及开头预览](https://github.com/anomalyco/opencode/blob/3104c1428ec91f809e5ab86631300de41eb6952e/packages/opencode/src/tool/truncate.ts#L76-L139)，保留本工程既有 Artifact 引用、原生调用配对和授权读搜。统一字节上限处理长单行，继续使用已有分页工具。

九份原始回执经现行回执构造和主请求投影回放，均完整展示一份正文文本字段。正文为 3,828 至 11,754 字符，`case1.pdf` 第 1–4 页从 2,483 增至 4,842 字符。以同一真实回执放大正文验证长行截断，回执为 51,199 字节，下一字符即超限。原件保存失败仍给出原文前缀和不可续读原因。历史回放核对了调用配对、旧检查点的原件定位和续读。验证覆盖回执及请求契约，模型选择和整例成绩未重跑。[九条回放](../../.tmp/tool-result-preview-50k-20261110/replay-report.json) · [边界反事实](../../.tmp/tool-result-preview-50k-20261110/boundary-report.json)

2026-11-10 调整原生工具回执展示。前版 Toolathlon 真实回执回放中，长行预览的原文占 45,918 个 UTF-8 字节，作为 JSON 字符串占 50,510 字节。采用 [OpenCode](https://github.com/anomalyco/opencode/blob/3104c1428ec91f809e5ab86631300de41eb6952e/packages/opencode/src/tool/truncate.ts#L124-L139) 和 [DeepAgents](https://github.com/langchain-ai/deepagents/blob/fd3e64ab6b605450bed5a2c22ef2ec84cd40542e/libs/deepagents/deepagents/middleware/_message_eviction.py#L241-L280) 的可读正文形式，保留本工程的结构化来源身份和引用边界。验收重放同一批 PDF 回执及长行反例，核对适配器实际组装的工具消息角色、调用 ID、原文保真、可用续读、保存失败和压缩后定位。普通回执、已读证据行和结构化回执保留原有契约。

展示验证重放 9 条真实 PDF 回执，工具消息保持原调用 ID，正文与工具文本逐字一致。长行反例保留同一份 36,738 字符预览，工具消息正文从 51,458 字节降到 46,891 字节。中英文、原件不可读、结构化输入和第 17、18、27 轮历史回放通过。抽查的 5 条已读原件和搜索工具消息与归档逐字一致。此处核对的是适配器组装结果，整例模型与评分未重跑。[请求回放](../../.tmp/tool-result-preview-display-20261110/replay-report.json) · [展示边界](../../.tmp/tool-result-preview-display-20261110/boundary-report.json)

调整前，同一 PDF 回执的离线回放通过 10 项检查，覆盖预览限长、调用配对、不同请求视图和当轮续读能力。Toolathlon 实际运行中，9 条超限 PDF 回执均携带配对预览、原件引用和合法读取指引，随后读搜了其中 6 个原件。整例因预算结束且上游评分未通过，验证结论限于超限回执机制。[离线回放](../../.tmp/tool-observation-preview-20261110/result.json) · [实发请求审计](../../.tmp/tool-observation-preview-live-20261110/model-input-audit.json) · [整例报告](../../.tmp/tool-observation-preview-live-20261110/target/report.json)
