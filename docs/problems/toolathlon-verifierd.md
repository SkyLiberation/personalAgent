# Toolathlon-Verified 历次评测问题汇总

截至 2026 年 11 月 12 日，固定版本 `9be8d8fe07a497b18ee61e3f2ae694e9797f39eb` 的 108 个官方用例中，69 个到达 personalAgent 正式对话入口。按下表所列运行和适用复评计，20 个通过官方评分，其中 8 个也交付了正式答复。其余 12 个产物评分通过的用例以执行限制、待确认或超时结束。早期样本使用各自的预算和功能配置，历史成绩按原运行身份解读。历次启动记录见[分批评测记录](toolathlon-verified.md)。

| 证据组 | 进入对话 | 官方评分通过 | 正式答复且评分通过 | 原始记录 |
| --- | ---: | ---: | ---: | --- |
| 文件整理与 PDF 先导 | 3 | 0 | 0 | [整理与 ImageNet](../../.tmp/ta3-1111-122140/audit.json) · [法律条款](../../.tmp/dtr-1111-120455/audit.json) |
| 扩展评测首轮 | 12 | 7 | 1 | [首轮汇总](../../.tmp/ta40-1111/summary.json) |
| 14 个预检受阻用例重跑 | 14 | 2 | 2 | [重跑汇总](../../.tmp/ta14-rerun-1111/summary.json) |
| 全量补跑的本地及公开数据用例 | 7 | 1 | 0 | [补跑汇总](../../.tmp/ta-remaining-1111/summary.json) |
| GitHub 测试账号补跑 | 3 | 2 | 0 | [GitHub 汇总](../../.tmp/ta-github-1112/summary.json) |
| 宾大路线先导 | 1 | 1 | 0 | [路线运行报告](../../.tmp/ta-serpapi-1112/run-ef9790/upenn-campus-route/report.json) |
| 已配置服务后的补跑 | 21 | 5 | 4 | [服务补跑汇总](../../.tmp/ta-live-1112/summary.json) |
| Notion 官方 MCP 复制验证 | 8 | 2 | 1 | [Notion 补跑汇总](../../.tmp/ta-notion-mcp-1112/summary.json) |

## 工具参数和错误恢复

- **本地 Schema 收窄了 MCP 输入。** `git-milestone` 先把 `headers` 传成数组，第二轮改成上游允许的 `{"Accept": "application/vnd.github+json"}`，仍被本地封闭对象规则拒绝。`identify-all-songs` 的语言请求头遇到同类问题。`paper-checker`、`shopping-helper`、`profile-update-online` 触发了读取文件的参数校验，其中 `profile-update-online` 省略上游允许缺省的 `tail` 后仍被拒绝。改为沿用上游 `inputSchema` 后，回放确认非法数组仍被拒绝，合法请求头对象和省略 `tail` 的调用可派发。真实 MCP 入口也收到了自定义请求头，文件读取范围通过核对。[历史 Schema 对照](../../.tmp/ta14-rerun-1111/schema-projection.json) · [修复回放](../../.tmp/mcp-upstream-contract-1111/replay.json) · [真实入口验证](../../.tmp/mcp-upstream-contract-1111/verification.json)
- **有具体反馈时，模型仍会重复提交无效参数。** `detect-revised-terms` 的一次重跑把 PDF 页码传成字符串，下一轮收到整数示例后原样重试，两次调用均在动作解码处被拒。`university-course-selection` 还出现过将 PDF 搜索页大小写成 `"40"`，随后在 Excel 格式化参数上重复失败。`interview-report` 两次提交包含额外属性的计划。`canvas-list-test` 在交付前提交了当前 Schema 枚举中不存在的原件 ID，随后因重复无效动作停止。`youtube-repo` 两轮均收到动作协议反馈，工具调用计数为 0。对允许的页码字段，Runtime 已用共用十进制整数读取函数处理规范字符串。四个历史字符串调用和一个原生整数对照已通过真实 PDF MCP 回放。最新法律条款整例没有触发字符串页码，官方 CSV 评分仍失败。[整数表示与验收](../context/runtime-feedback.md#显式允许的整数表示) · [计划轨迹](../../.tmp/ta40-1111/batch-02/interview-report/product-data/interaction_runs/irun_bb7f3e07ccfe46fb/0046.json) · [Canvas 运行日志](../../.tmp/ta-live-1112/batch-05/canvas-list-test/web.log) · [YouTube 轨迹](../../.tmp/ta-live-1112/batch-05/youtube-repo/product-data/interaction_runs/irun_3a6a56c6fe5544cf/0013.json)
- **PDF 工具回包成功，审计入库失败。** `imagenet` 的 PDF MCP 回包含 NUL 字符，PostgreSQL 拒绝将其写入 `JSONB`，Web 返回 HTTP 500，未产出 `survey.tex`。入库前清理审计副本后，已通过含 NUL 和不含 NUL 的真实工具 HTTP 回放。含 NUL 的回包原样交给运行时，审计可保存。修复证据覆盖工具返回和审计写入，完整 ImageNet 交付仍待验证。[原始运行](../../.tmp/ta3-1111-122140/run/imagenet/report.json) · [数据库复现](../../.tmp/imagenet-pdf-replay-20261111/report.json) · [修复回放](../../.tmp/audit-nul-20261111/verified/report.json)
- **评测容器漏挂 Notion OpenAPI 补丁。** 旧 `API-post-page` 要求 `parent.page_id`，`oil-price` 和 `notion-movies` 的新增数据库记录调用均在参数校验处被拒。补挂 Toolathlon 自带补丁后，网关声明包含 `database_id` 和 `data_source_id`，两例复跑均未再触发同一拒绝，油价汇总表写入 12 行。旧 `API-patch-page` 还要求 `properties.title` 并禁止自定义属性，`notion-find-job` 连续两次更新申请状态时被拒。补丁已开放该属性对象，`notion-find-job` 尚未使用补丁复验。[补丁前的申请工具声明](../../.tmp/ta-notion-mcp-1112/remaining-notion/notion-find-job/tools.json) · [申请运行日志](../../.tmp/ta-notion-mcp-1112/remaining-notion/notion-find-job/web.log) · [补丁后的网关工具声明](../../.tmp/ta-notion-mcp-1112/oil-price-schema/oil-price/tools.json)
- **模型响应归档路径过长。** `quantitative-financial-analysis` 的 Notion 副本校验通过，首个模型 HTTP 请求返回 200，随后对话在 `application_persistence` 阶段返回 HTTP 500。该次运行没有归档模型响应，评分器也未找到有效的 Google Sheets 链接。同机按相同路径长度复现了 Windows 重命名失败，归档布局已压缩并通过真实响应回放。等长目录复跑时对话返回 HTTP 200，已交付答复。官方评分器查询 Notion 页面评论时收到 HTTP 403，整例评分未通过。[原运行报告](../../.tmp/ta-notion-mcp-1112/remaining-notion/quantitative-financial-analysis/report.json) · [归档修复与验证](../optimization/completed/model-archive-path.md) · [复跑报告](../../.tmp/ta-notion-mcp-1112/remaining-verify/quantitative-financial-analysis/report.json) · [复跑评分日志](../../.tmp/ta-notion-mcp-1112/remaining-verify/quantitative-financial-analysis/grader.log)
- **评分凭据和评测工具分别缺少评论能力。** `quantitative-financial-analysis` 的官方评分器使用 `ToolAthlon测试` 连接。开启读取评论权限后，评论接口返回 HTTP 200，复评从正文找到了表格链接，但页面没有指定评论。该次 MCP 网关已公布创建评论工具，评测脚本漏配映射，模型把指定评论写成了正文。补齐映射并保留上游 Schema 后，为模型所用的 `Toolathlon Eval` 开启插入评论。两个 API 令牌已更新。官方 MCP 重新授权后恢复模板复制，首次正式复跑遇到模型请求超时并返回 HTTP 504。下一次按同样配置复跑，模型通过 MCP 创建了指定评论并交付正式答复。官方评分验证了评论、表格链接、工作簿和 168 行数据，整例通过。[映射复核](../../.tmp/ta-notion-mcp-1112/rescored/quantitative-financial-analysis/comment-mapping.json) · [超时报告](../../.tmp/ta-notion-mcp-1112/comment-auth/quantitative-financial-analysis/report.json) · [通过报告](../../.tmp/ta-notion-mcp-1112/comment-retry/quantitative-financial-analysis/report.json) · [官方评分](../../.tmp/ta-notion-mcp-1112/comment-retry/quantitative-financial-analysis/grader.log)

## 长上下文、完成检查和预算

- **PDF 正文预览与压缩后的原件定位曾不够用。** 九份封存的 PDF 回执在多个字段重复正文，旧预览切分后每份只展示 2,483 字符。`detect-revised-terms` 的旧轨迹还显示，压缩后模型能看到资源 ID，却失去 ID 对应的文件和页码，随后再次调用 MCP 读同一原件。预览和原件定位已分别通过真实回执回放。法律条款新运行记录到一次压缩和第 18 至 30 轮的定位区块，整例仍有条款筛选和文本保真偏差。[PDF 预览](../context/tool.md#4-已有验证) · [压缩定位回放](../context/agent-loop.md#5-实现对照与验收状态) · [新运行审计](../../.tmp/dtr-1111-120455/audit.json)
- **完成反馈没有进入下一次模型请求。** `find-alita-paper` 已下载正确 PDF。完成检查以 `offloaded_output_unread` 退回后，恢复分支从同一研究结果重建旧答复，导致 378 次同类退回。模型调用停在 11 次，主决策停在第 9 轮。调用方最终超时。`dietary-health` 收到同类反馈后仍继续调用模型，因此其超时只能归到该次运行的实际轨迹。[最终快照](../../.tmp/ta40-1111/alita/product-data/interaction_runs/irun_bd7a3a11f1424abf/0819.json) · [饮食分析报告](../../.tmp/ta40-1111/batch-03/dietary-health/report.json)
- **产物已生成，对话在确认或预算门禁结束。** `sales-accounting` 的账本已经写好，最终等待确认将内容写入长期知识。`courses-ta-hws` 在第 32 轮用尽轮数，`excel-market-research`、`git-repo`、`wandb-best-score` 到达 token 上限。四例产物均通过评分，用户收到执行限制。历史运行按已入账用量检查剩余预算，一次请求的用量入账后可超过 200 万 token。[账本对话](../../.tmp/ta40-1111/batch-01/sales-accounting/report.json) · [预算检查](../../src/personal_agent/application/conversation/budget.py#L56) · [W&B 对话](../../.tmp/ta-live-1112/batch-01/wandb-best-score/report.json)
- **多轮查询会耗尽轮数、调用次数或累计 token。** `cvpr-research`、`stock-build-position`、`academic-pdf-report`、`language-school`、`canvas-do-quiz`、`vlm-history-completer` 都用了 48 次工具调用，评分仍发现缺项。法律条款早期在 22 万、80 万和 200 万 token 配置下分别出现预算或轮数停止。200 万组的 209.7 万 token 中约 205.8 万是输入。后续运行已能交付 CSV，评分偏差见逐例记录。[预算实验](../mcpDesign/README.md#73-pdf-资料与文件交付验证) · [14 例重跑](../../.tmp/ta14-rerun-1111/summary.json) · [21 例补跑](../../.tmp/ta-live-1112/summary.json)
- **Notion 用例耗尽预算时只完成了部分交付。** `oil-price`、`experiments-recordings`、`notion-hr` 和 `notion-movies` 的最后一次对话均达到 200 万 token 上限。其中油价数据通过官方复评，对话仍停在执行限制。`task-tracker` 用完 48 次工具调用，评分时 Notion 表仍缺 29 行，GitHub 未创建 `finalpool` 分支。[Notion 补跑轨迹和用量](../../.tmp/ta-notion-mcp-1112/summary.json) · [任务追踪评分](../../.tmp/ta-notion-mcp-1112/remaining-notion/task-tracker/grader.log)
- **上游模型超时与调用方等待超时发生在不同边界。** `reimbursement-form-filler`、`add-bibtex`、`verl-dataset`、`personal-website-construct`、`gdp-cr5-analysis`、`investment-decision-analysis`、修正接线后的 `mrbeast-analysis` 均返回上游模型请求超时的 HTTP 504。另一些用例在 600 秒内未返回对话结果，其中 `cooking-guidance`、`excel-data-transformation`、`sync-todo-to-readme`、`upenn-campus-route` 的工作区或远端写入仍通过评分。超时记录只能证明当次请求未取得终态，应结合产物与运行轨迹判断完成程度。[补跑对话结果](../../.tmp/ta-remaining-1111/summary.json) · [GitHub 对话结果](../../.tmp/ta-github-1112/summary.json) · [服务补跑结果](../../.tmp/ta-live-1112/summary.json)

## 任务判断与核验偏差

- **文件归类错误随清单一起获批并写入。** `arrange-workspace` 的正式审批与 38 项写操作通过，文件内容保持一致。两次完整评分均发现 `cv-gboeing.pdf` 与 `exam.xlsx` 归错目录。12 次工具调用配置下的恢复对话耗尽额度，独立配置重跑可以答复，位置偏差仍复现。更早的受治理入口探针还发现待确认的移动已派发到只读 Server。修正后同请求零远端派发，合法读取正常。该探针验证派发门禁，整例问题落在文件归类和交付。[完整样本评分](../../.tmp/ta3-1111-122140/run/arrange-workspace/grader.log) · [重跑与门禁证据](../mcpDesign/README.md#8-实施顺序迁移与状态)
- **输出存在时，实质判断、原文和完整性仍可能不合格。** `detect-revised-terms` 最新 CSV 有 10 行，完整标准为 9 行，7 行完全匹配，1 个对应关系多报，另有 2 对条文正文不同。`dietary-health` 有 3 处营养数值差异。`course-schedule` 把考场 `3302` 写成 `3303`。`apply-phd-email` 已发邮件并答复，解包复评发现奖项 PDF 内容不同。`personal-website-construct` 建站后仍保留模板姓名。这些是评分证实的结果差异，各自的模型推理原因尚需同轨迹证据。[条款差异](../../.tmp/dtr-1111-120455/grader-diff.json) · [邮件复评](../../.tmp/ta-live-1112/rescored/apply-phd-email/grader.log) · [网站评分](../../.tmp/ta-github-1112/batch-01/personal-website-construct/grader.log)
- **评分范围与用户看到的结果有差异。** `train-ticket-plan` 的文件在评分器采用 11 月 19 日和 22 日时通过，答复正文写的是 11 月 12 日和 15 日，日期未写进产物。`invoice-org` 的评分核对 7 行发票和总金额，商家列未纳入判据。[车票复评说明](toolathlon-verified.md#火车票依赖与评分输入) · [发票评分](../../.tmp/ta40-1111/batch-04/invoice-org/grader.log)

## 已运行样本中的评测接线和评分问题

| 问题 | 观察与处置 | 证据 |
| --- | --- | --- |
| 早期预算配置不一致 | 早期工作区和 PDF 用例各有预算预设，恢复对话可能落到 Runtime 默认的 12 次工具调用。配置验收确认三例使用同一 `.env` 时均得到 200 万 token、32 轮、48 次工具调用。只提供模型配置时均回落到默认的 32,000 token、8 轮和 12 次调用。 | [配置验收](../../.tmp/toolathlon-budget-20261111/report.json) |
| 网关传输与工具映射 | 聚合网关使用旧式 SSE，直接对 `/sse` 发 POST 得到 405，`/mcp` 得到 404。stdio 到 SSE 的转接让样本完成真实调用。后续 `mrbeast-analysis` 的视频／字幕命名冲突与 `canvas-do-quiz` 的 `canvas_` 前缀都曾造成工具漏映射。补齐后两例都进入对话，后续分别因模型超时和测验结果未达标失败。 | [传输探测](toolathlon-verified.md#网关接入与任务服务) · [映射修正后运行](toolathlon-verified.md#工具映射和模板预处理) |
| 历史依赖配置与缓存 | `git-milestone` 的示例令牌触发 GitHub HTTP 401，隔离配置清除占位令牌后，匿名请求生成了评分参考。`train-ticket-plan` 曾因 npm 缓存找不到 `minimatch@3.1.5`，刷新元数据后通过初始化。 | [GitHub 重跑](toolathlon-verified.md#预检受阻的-14-个用例重跑) · [12306 依赖日志](../../.tmp/ta-remaining-1111/batch-02/train-ticket-plan/gateway.log) |
| 评分容器缺依赖或挂载 | 法律条款评分在宿主缺少 `termcolor` 和上游配置，改用官方镜像复评。`shopping-helper` 初次评分缺少 `configs/mcp_servers`，补齐后确认 3 条推荐未通过。 | [法律条款评分环境](../mcpDesign/README.md#73-pdf-资料与文件交付验证) · [购物补评](../../.tmp/ta40-1111/score-replay/shopping-helper/grader.log) |
| 评分输入缺本轮元数据 | `train-ticket-plan` 评分从日志读 `config.launch_time`，首次缺字段，补入真实启动时间后同一产物通过。`gdp-cr5-analysis` 和 `inter-final-performance-analysis` 首次未取得本轮文件夹 ID，补入后仍分别缺目标表与 `sheet_url.txt`。 | [车票复评](../../.tmp/ta-remaining-1111/rail-rescore/train-ticket-plan/grader.log) · [GDP 复评](../../.tmp/ta-live-1112/rescored/gdp-cr5-analysis/grader.log) · [比赛表现复评](../../.tmp/ta-live-1112/rescored/inter-final-performance-analysis/grader.log) |
| 评分临时文件不可写 | `apply-phd-email` 需要解包附件，`inventory-sync` 需要清理配置。只读挂载使两个评分器报错。提供可写的独立副本后使用原结果复评，确认 1 份 PDF 内容不符、51 个商品库存数量不符。 | [首次与复评记录](toolathlon-verified.md#评分输入和临时目录) |
| 地图服务返回与评分解析 | SerpApi 适配器的一次依赖复验中，原评分器收到无法按 JSON 读取的地点详情，同版本再次执行通过。宾大路线、地铁和巴黎行程的通过记录对应 SerpApi 条件。 | [地图复验证据](../mcpDesign/README.md#533-serpapi-地点与距离矩阵) |
| Notion 复制与授权会话 | 浏览器复制曾在 `Duplicate` 菜单定位处超时。切换官方 MCP 后，容器内置的 `mcp-remote@0.1.16` 无法读取 Windows 授权端 `0.16.6` 的会话目录。将预处理桥接固定为 `0.16.6` 后，8 个用例的副本均通过校验。 | [复制修复记录](toolathlon-verified.md#notion-官方-mcp-复制验证) |
| Notion 评分查询中断 | `oil-price` 补挂 Schema 后，评分器已读到 12 行月度数据，后续 Notion 查询遇到 TLS 连接中断。原产物复评通过，新增模型调用为 0。 | [首次评分](../../.tmp/ta-notion-mcp-1112/oil-price-schema/oil-price/grader.log) · [复评报告](../../.tmp/ta-notion-mcp-1112/rescored/oil-price/report.json) |

## 逐例核对

### 2026 年 11 月 13 日的 27 个待运行用例

27 个用例均进入 personalAgent 正式对话并取得官方评分结果。7 个产物评分通过，其中 5 个也交付了正式答复；其余 20 个未通过官方评分。27 个用例中，17 个对话以执行限制结束，2 个未在超时前取得答复。全套 108 个用例已有 96 个进入过正式对话，剩余 8 个 Google Cloud 和 4 个 Snowflake 用例按此前决定跳过。[逐例结果与重试记录](../../.tmp/ta27-1113-k8s/summary.json)

本轮沿用 MiniMax-M3.1-Flash、32 个主决策轮、48 次工具调用、200 万 token 和 600 秒对话时限。Kubernetes 用例由官方预处理为每个任务建独立 Kind 集群。49 次运行尝试中包含预处理失败后的定向重试；仅补评分的操作单独记录。已记录约 4,102 万 token，有 1 次模型运行的提供方用量不完整。[运行身份](../../.tmp/ta27-1113-k8s/identity.json) · [校验和](../../.tmp/ta27-1113-k8s/summary.sha256)

- **Docker 并行启动多个 Kind 集群时失去响应。** Docker API 返回 HTTP 500，WSL 的 2 GiB 交换空间用满。四个已经进入对话的用例在导出或清理阶段中断。Docker 恢复后沿用原产物补评，四例均未通过。Kind 集群改为逐个启动。[补评归档](../../.tmp/ta27-1113-k8s/rescore/)
- **Kubernetes 评测启动器遗漏集群脚本、工作区挂载和工具映射。** 首轮五例均在预处理退出。补齐上游脚本和初始化卷后，`k8s-deployment-cleanup` 已到达对话，但该次仅映射一个 Kubernetes 工具，用完 48 次调用后仍有五项部署未清理。后续运行的 `k8s-pr-preview-testing` 实际收到 17 个 Kubernetes 工具，部署通过健康检查，评分发现测试报告缺失。[首次进入对话的清理用例](../../.tmp/ta27-1113-k8s/serial-deployment-cleanup/k8s-deployment-cleanup/report.json) · [预览部署评分](../../.tmp/ta27-1113-k8s/serial-pr-preview-testing/k8s-pr-preview-testing/grader.log)
- **MySQL 容器已就绪时，导入连接仍可能未就绪。** 上游预处理使用 Pod 内的本地连接判断就绪，随后经 TCP 导入数据时曾收到连接拒绝。临时启动器改为等 TCP 接受连接再导入，正式对话随后启动，达到 32 个主决策轮后仍缺评分要求的目标文件。另一个 Kubernetes 用例 `k8s-safety-audit` 已生成表格，但一项风险分写成 6，参考值为 7。[MySQL 运行](../../.tmp/ta27-1113-k8s/final-mysql/k8s-mysql/report.json) · [安全审计评分](../../.tmp/ta27-1113-k8s/serial-safety-audit/k8s-safety-audit/grader.log)
- **Redis 评分器从任务目录读取参考配置。** `k8s-redis-helm-upgrade` 首次评分只向评分命令传入参考目录参数，未在评分器实际读取的位置放置参考文件。补齐挂载后复验，评分器确认两个副本运行、服务可用且自定义配置保留，但 Helm Chart 仍是 19.0.0，未升级到目标版本 22.0.0，评分 0.8/1.0。对话累计用量达到 token 上限后结束。[首次评分](../../.tmp/ta27-1113-k8s/serial-redis-helm-upgrade/k8s-redis-helm-upgrade/grader.log) · [复验评分](../../.tmp/ta27-1113-k8s/final-redis-helm-upgrade/k8s-redis-helm-upgrade/grader.log)
- **WooCommerce 预处理的单次请求超时。** `filter-low-selling-products` 在清理及重建商品时遇到 10 秒请求超时。为该用例延长预处理请求时限并补建动态评分目录后，对话能够运行，远端商品结果通过官方评分，对话以执行限制结束。[补跑报告](../../.tmp/ta27-1113-k8s/wc-reference/filter-low-selling-products/report.json)
- **动态评分参考目录缺失。** `student-interview` 的预处理缺少 `groundtruth_workspace`，无法写入 `today.txt`。补建目录后进入正式对话并通过官方产物评分，对话在第 48 次工具调用后以执行限制结束。[补跑报告](../../.tmp/ta27-1113-k8s/student-serial/student-interview/report.json)
- **Canvas 评分需要可写临时目录，仍有工具兼容问题。** `canvas-new-students-notification` 首次评分无法写入 `temp_mapping_workspace`。使用可写副本复评后，评分确认 13 名学生未选课。私信检查调用 `canvas_get_conversation` 时返回 `Unknown tool`，评分报告的私信缺失数量需要结合该错误解读。[补评日志](../../.tmp/ta27-1113-k8s/rescore/canvas-new-students-notification/grader.log)
- **Hugging Face 的三个用例均进入对话。** `huggingface-upload` 的评分器未找到目标仓库，`dataset-license-issue` 的 GitHub Issue 未关闭，`merge-hf-datasets` 的合并数据含字段类型差异。[批次报告](../../.tmp/ta27-1113-hf/report.json)

“评分通过”表示上游评分器接受所核对的产物。“正式答复”对应产品的 `answer` 终态。表中优先记录最后一次到达正式对话入口的结果，使用补评的用例引用对应补评。更早的独立复验见前文。

### Redis Helm 官方 Agent 对照

2026 年 11 月 13 日，使用同一 MiniMax-M3.1-Flash、原题、初始 Redis Chart 和官方评分器，比对了 personalAgent 历史样本与 Toolathlon 官方 Agent 的本地运行。两边均未提交 `helm upgrade`，终态均为 `19.0.0`、评分 `0.8/1.0`。健康 Pod 和配置保留是旧部署的状态。[复跑入口](../evals/04-running-and-release.md#redis-helm-官方-agent-对照) · [官方复验报告](../../.tmp/tarc-1113-r2/report.json)

| 样本 | 模型轮数 | 工具调用 | 累计 token | 到达阶段与停止原因 |
| --- | ---: | ---: | ---: | --- |
| personalAgent 历史样本 | 31 | 45 | 2,073,858 | 已写入候选 `redis-values.yaml`，累计预算检查在第二次渲染派发前结束对话。 |
| 官方 Agent，默认 SSE 等待 | 32 | 36 | 未知 | 7 次 SSE 调用等待 5 秒后超时。用完决策轮数。官方汇总在此退出路径把已发生的模型用量记为 0。 |
| 官方 Agent，SSE 等待 90 秒 | 32 | 52 | 815,633 | 目标 Chart 已下载。用两个临时 Python 脚本查询镜像，继续读配置和模板，未写升级配置。用完决策轮数。 |

官方复验的 52 次工具调用中，48 次使用终端，12 次收到终端安全规则拒绝，SSE 等待超时为 0。它查到了默认镜像 `404` 和备用镜像 `200`，与 personalAgent 定位到同一个镜像问题。复验按 MiniMax 的 32 条成功 HTTP 响应统计用量，因为官方 Agent 在决策轮耗尽时没有累加 SDK 的整轮用量。[默认等待轨迹](../../.tmp/tarc-1113/traj_log.json) · [复验轨迹](../../.tmp/tarc-1113-r2/traj_log.json) · [模型用量](../../.tmp/tarc-1113-r2/model-usage.jsonl)

官方复验采用 90 秒 SSE 等待时间。接入代码第一次执行时有一个关键字参数名不匹配，官方 Agent 未启动，该次评分仅反映初始部署，单独保留。两种 Agent 各自沿用原有 Prompt、工具编排和预算机制，官方 Agent 没有 personalAgent 的 48 次工具和 200 万 token 限制。本次对照只描述这几条真实轨迹。[接入失败日志](../../.tmp/tarc-1113-sse90/agent.log) · [personalAgent 历史报告](../../.tmp/ta27-1113-k8s/final-redis-helm-upgrade/k8s-redis-helm-upgrade/report.json)

#### 64 轮预算复验

同一原题、模型和评分器下，两个 Agent 分别使用新集群复跑。两边的会话上限为 600 秒，personalAgent 使用已去重的工具结果、128 次工具调用和 800 万累计 token 上限，官方 Agent 使用 90 秒 SSE 等待。[运行配置](../evals/04-running-and-release.md#redis-helm-官方-agent-对照) · [对照汇总](../../.tmp/mcp-model-dedup-1113/comparison-64.json)

| Agent | 已记录模型轮数 | 工具调用 | 已记录 token | Chart 终态 | 官方评分 | 对话终态 |
| --- | ---: | ---: | ---: | --- | ---: | --- |
| personalAgent | 42 | 76 | 2,654,403 | `19.0.0` | 0.8 | 调用方等待 600 秒后超时，未收到答复 |
| Toolathlon 官方 Agent | 64 | 68 | 1,979,015 | `22.0.0` | 1.0 | 第 64 轮后停止，未交付正式答复 |

官方 Agent 第 52 轮执行了升级。评分时两个副本运行正常、服务可用，自定义配置通过核对。Agent 自身在 392 秒时耗尽 64 轮，官方循环状态仍是 `failed`。personalAgent 的 76 次工具调用里有 18 次终端规则拒绝，超时前尚未提交升级。两条新轨迹说明放宽轮数后实际到达的边界，单次运行无法分离预算与模型动作选择对结果的各自影响。[官方报告](../../.tmp/ta-redis-64-official/report.json) · [personalAgent 报告](../../.tmp/mcp-model-dedup-1113/expanded/k8s-redis-helm-upgrade/report.json) · [personalAgent 评分](../../.tmp/mcp-model-dedup-1113/expanded/k8s-redis-helm-upgrade/grader.log)

#### personalAgent 超时断点续跑

原评测清理了测试集群和临时数据库。续跑按官方预处理重建集群，核对 Redis Chart 为 `19.0.0`、Helm 修订为 `1`，恢复工作区文件并保留新集群生成的 kubeconfig。用原运行 ID `irun_aa8b27330d0d4e4e` 提交原请求，HTTP 等待延长至 1,200 秒。对话快照保留了前 42 轮，超时时尚未完成的模型请求在续跑中被记为第 43 轮。[恢复配置](../../.tmp/ta-rr/recovery.txt) · [运行报告](../../.tmp/ta-rr/report.json)

续跑新增 22 轮、32 次工具调用和 2,967,151 个已记录 token。模型第 55 轮写入候选配置，第 63 轮运行 `helm upgrade --dry-run`，未提交实际升级。对话到第 64 轮耗尽轮数预算，累计 108 次工具调用和 5,621,554 个已记录 token。官方评分为 `0.8/1.0`，确认 Redis 仍为 `19.0.0`。[最终快照](../../.tmp/ta-rr/product-data/interaction_runs/irun_aa8b27330d0d4e4e/0391.json) · [官方评分](../../.tmp/ta-rr/grader.log)

#### 统一主循环关闭核验复验

2026 年 11 月 13 日，用统一主循环和 MiniMax-M3.1-Flash 从空会话复跑原题。仅本次关闭目标核验与回答核验，保留低预算提示。预算为 64 轮、128 次工具调用和 800 万 token，HTTP 等待上限为 1,200 秒。首次预处理在更新 Bitnami 仓库时失败，复跑用留存的同版 Chart 初始化 `19.0.0`、修订 `1`。Agent 自行下载 `22.0.0`。运行记录确认第 1 轮接纳了目标，两类核验均未调用。仓库默认配置仍开启两类核验。[首次预处理](../../.tmp/rno-1113/k8s-redis-helm-upgrade/k8s-preprocess.log) · [复跑配置](../../.tmp/rno-1113/retry/k8s-redis-helm-upgrade/feature_flags.toml) · [运行身份](../../.tmp/rno-1113/retry/identity.json)

第 32 轮首次 dry-run 成功渲染目标 Chart，第 42 轮提交实际升级。Toolathlon 网关等待终端 MCP 60 秒超时后重试，返回 Helm 的 `another operation (install/upgrade/rollback) is in progress`。原 Helm 进程继续等待镜像拉取和 Pod 就绪，第 59 轮查到 `22.0.0`、修订 `2` 已部署。官方评分为 `1.0/1.0`，两副本正常、服务可用且自定义配置通过检查。[调用核对](../../.tmp/rno-1113/retry/audit.json) · [滚动更新记录](../../.tmp/rno-1113/retry/rollout-observations.jsonl) · [官方评分](../../.tmp/rno-1113/retry/k8s-redis-helm-upgrade/grader.log)

调用方等待 1,200 秒后超时，未收到正式答复。最终快照在第 64 轮记录 `limitation`，共 97 次工具调用、5,363,192 token。与此前续跑相比，升级得分由 `0.8` 升至 `1.0`。此次只有一个样本，主循环也已更换，历史轨迹未实际触发两类核验，因此不能把差异归因于关闭核验。[复跑报告](../../.tmp/rno-1113/retry/k8s-redis-helm-upgrade/report.json) · [最终快照](../../.tmp/rno-1113/retry/k8s-redis-helm-upgrade/product-data/interaction_runs/irun_8beb6489042c4ab3/0384.json)

### 文件整理与 PDF 先导

| 用例 | 可观察结果 | 证据 |
| --- | --- | --- |
| `arrange-workspace` | 22 份文件中 2 份归错目录。早期恢复对话耗尽工具额度。 | [对话与评分](../../.tmp/ta3-1111-122140/audit.json) · [目录差异](../../.tmp/ta3-1111-122140/run/arrange-workspace/grader.log) |
| `detect-revised-terms` | 最新运行给出答复和 CSV。标准 9 行中 7 行完全匹配，多 1 个对应关系，另有 2 对正文不同。 | [对话审计](../../.tmp/dtr-1111-120455/audit.json) · [CSV 差异](../../.tmp/dtr-1111-120455/grader-diff.json) |
| `imagenet` | 读取模板曾被参数校验拦截。后续 PDF 回包导致审计入库 HTTP 500，缺少 `survey.tex`。 | [早期与后续运行](../mcpDesign/README.md#73-pdf-资料与文件交付验证) · [HTTP 500 运行](../../.tmp/ta3-1111-122140/run/imagenet/report.json) |

### 扩展评测首轮

| 用例 | 可观察结果 | 证据 |
| --- | --- | --- |
| `cooking-guidance` | 对话超时，工作区快照补评通过。 | [补评](../../.tmp/ta40-1111/score-replay/cooking-guidance/grader.log) |
| `courses-ta-hws` | 产物通过评分，第 32 轮返回执行限制。 | [运行](../../.tmp/ta40-1111/batch-02/courses-ta-hws/report.json) |
| `dietary-health` | 对话超时，产物有 3 处营养数值偏差。 | [评分](../../.tmp/ta40-1111/batch-03/dietary-health/grader.log) |
| `excel-data-transformation` | 对话超时，导出的工作簿补评通过。 | [补评](../../.tmp/ta40-1111/score-replay/excel-data-transformation/grader.log) |
| `excel-market-research` | 产物通过评分，累计 2,047,238 token 后返回执行限制。 | [运行](../../.tmp/ta40-1111/batch-02/excel-market-research/report.json) |
| `find-alita-paper` | 下载正确 PDF，完成检查重复退回，正式答复未交付。原评分器联网查询 arXiv 版本失败后用缓存评分。 | [运行](../../.tmp/ta40-1111/alita/report.json) · [评分](../../.tmp/ta40-1111/alita/grader.log) |
| `interview-report` | 计划步骤额外字段重复被拒，未生成候选人报告。 | [轨迹](../../.tmp/ta40-1111/batch-02/interview-report/product-data/interaction_runs/irun_bb7f3e07ccfe46fb/0046.json) · [评分](../../.tmp/ta40-1111/batch-02/interview-report/grader.log) |
| `invoice-org` | 正式答复和评分通过。轨迹有 2 次工具参数校验反馈，评分未覆盖商家列。 | [首轮汇总](../../.tmp/ta40-1111/summary.json) · [评分](../../.tmp/ta40-1111/batch-04/invoice-org/grader.log) |
| `paper-checker` | 两次读取文件参数校验失败，4 个文件仍与预期有差异。 | [运行](../../.tmp/ta40-1111/batch-02/paper-checker/report.json) · [评分](../../.tmp/ta40-1111/batch-02/paper-checker/grader.log) |
| `privacy-desensitization` | 第 32 轮停止，13 个脱敏输出内容有差异。 | [运行](../../.tmp/ta40-1111/batch-02/privacy-desensitization/report.json) · [评分](../../.tmp/ta40-1111/batch-02/privacy-desensitization/grader.log) |
| `sales-accounting` | 账本评分通过，最后要求确认保存长期知识。 | [运行](../../.tmp/ta40-1111/batch-01/sales-accounting/report.json) |
| `shopping-helper` | `head` 类型错误与 `tail` 缺失导致提前停止，补评 3 条推荐均未通过。 | [轨迹](../../.tmp/ta40-1111/batch-03/shopping-helper/product-data/interaction_runs/irun_10057f6f00de45b2/0023.json) · [补评](../../.tmp/ta40-1111/score-replay/shopping-helper/grader.log) |

### 14 个用例重跑

| 用例 | 可观察结果 | 证据 |
| --- | --- | --- |
| `cvpr-research` | 用完 48 次工具调用，缺研究者名单。 | [评分](../../.tmp/ta14-rerun-1111/batch-01/cvpr-research/grader.log) |
| `git-milestone` | 两次请求头参数被拒，缺 `github_info.json`。 | [运行](../../.tmp/ta14-rerun-1111/git-retry/git-milestone/report.json) |
| `hk-top-conf` | 达到 32 轮，缺 `result.md`。 | [评分](../../.tmp/ta14-rerun-1111/batch-02/hk-top-conf/grader.log) |
| `identify-all-songs` | 请求头反复被拒，缺 `songs.md`。 | [评分](../../.tmp/ta14-rerun-1111/batch-02/identify-all-songs/grader.log) |
| `ipad-edu-price` | 到达 token 上限，缺 `result.json`。 | [评分](../../.tmp/ta14-rerun-1111/batch-01/ipad-edu-price/grader.log) |
| `latex-prompt-box` | 到达 token 上限，宏包导入已写入，缺颜色定义。 | [评分](../../.tmp/ta14-rerun-1111/batch-01/latex-prompt-box/grader.log) |
| `logical-datasets-collection` | 到达 token 上限，缺 `datasets.tex`。 | [评分](../../.tmp/ta14-rerun-1111/batch-01/logical-datasets-collection/grader.log) |
| `ppt-analysis` | 正式答复和评分通过，轨迹有 1 次工具参数校验反馈。 | [重跑汇总](../../.tmp/ta14-rerun-1111/summary.json) |
| `profile-update-online` | 两次读取文件的 `tail` 参数被拒，缺两篇论文更新。 | [评分](../../.tmp/ta14-rerun-1111/batch-02/profile-update-online/grader.log) |
| `reimbursement-form-filler` | 上游连接提前关闭，重试后返回 HTTP 504，缺部门报销表。 | [运行](../../.tmp/ta14-rerun-1111/batch-01/reimbursement-form-filler/report.json) |
| `stock-build-position` | 用完 48 次工具调用，美团初始仓位未填。 | [评分](../../.tmp/ta14-rerun-1111/batch-02/stock-build-position/grader.log) |
| `travel-exchange` | 正式答复和评分通过，轨迹有 1 次工具参数校验反馈。 | [重跑汇总](../../.tmp/ta14-rerun-1111/summary.json) |
| `university-course-selection` | 格式化参数被拒后停止。生成了 4 份课程方案，要求删除的模板仍在工作区。 | [运行](../../.tmp/ta14-rerun-1111/batch-01/university-course-selection/report.json) · [评分](../../.tmp/ta14-rerun-1111/batch-01/university-course-selection/grader.log) |
| `yahoo-analysis` | 达到 32 轮，缺目标文件。 | [评分](../../.tmp/ta14-rerun-1111/batch-02/yahoo-analysis/grader.log) |

### 全量补跑、GitHub 和宾大路线

| 用例 | 可观察结果 | 证据 |
| --- | --- | --- |
| `academic-pdf-report` | 用完 48 次工具调用，6 篇论文完整匹配 0 篇。 | [评分](../../.tmp/ta-remaining-1111/batch-01/academic-pdf-report/grader.log) |
| `add-bibtex` | 上游模型请求超时，缺参考文献条目。 | [评分](../../.tmp/ta-remaining-1111/batch-01/add-bibtex/grader.log) |
| `course-schedule` | 对话超时，考场字段写成 `3303`，期望 `3302`。 | [评分](../../.tmp/ta-remaining-1111/batch-01/course-schedule/grader.log) |
| `language-school` | 用完 48 次工具调用，缺 `cs_top10_us.xlsx`。 | [评分](../../.tmp/ta-remaining-1111/batch-01/language-school/grader.log) |
| `nvidia-market` | 到达 token 上限，四张工作表均未通过检查。 | [评分](../../.tmp/ta-remaining-1111/batch-01/nvidia-market/grader.log) |
| `train-ticket-plan` | 对话返回执行限制且日期有偏差，补入启动时间后文件通过评分。 | [对话](../../.tmp/ta-remaining-1111/rail-online/train-ticket-plan/report.json) · [复评](../../.tmp/ta-remaining-1111/rail-rescore/train-ticket-plan/grader.log) |
| `verl-dataset` | 上游模型请求超时，缺 `verl_deepscaler.parquet`。 | [评分](../../.tmp/ta-remaining-1111/batch-02/verl-dataset/grader.log) |
| `git-repo` | `result.json` 通过评分，累计 2,104,898 token 后返回执行限制。 | [运行](../../.tmp/ta-github-1112/batch-01/git-repo/report.json) |
| `personal-website-construct` | 仓库已创建，上游模型请求超时，站点姓名仍为模板默认值。 | [评分](../../.tmp/ta-github-1112/batch-01/personal-website-construct/grader.log) |
| `sync-todo-to-readme` | README 更新通过评分，对话超过 600 秒未返回。 | [运行](../../.tmp/ta-github-1112/batch-01/sync-todo-to-readme/report.json) · [评分](../../.tmp/ta-github-1112/batch-01/sync-todo-to-readme/grader.log) |
| `upenn-campus-route` | 五段路线通过 SerpApi 条件下的官方评分，对话超过 600 秒未返回。 | [运行](../../.tmp/ta-serpapi-1112/run-ef9790/upenn-campus-route/report.json) |

### 已配置服务后的补跑

| 用例 | 可观察结果 | 证据 |
| --- | --- | --- |
| `apply-phd-email` | 已发邮件并正式答复，复评发现一份奖项 PDF 内容不符。 | [复评](../../.tmp/ta-live-1112/rescored/apply-phd-email/grader.log) |
| `canvas-do-quiz` | 补齐工具映射后用完 48 次工具调用，14 份测验中满分数为 0。 | [评分](../../.tmp/ta-live-1112/canvas-recheck/canvas-do-quiz/grader.log) |
| `canvas-list-test` | 连续无效动作后停止。测验与作业 CSV 各 1 行，期望分别为 13 行和 4 行。 | [运行](../../.tmp/ta-live-1112/batch-05/canvas-list-test/report.json) · [评分](../../.tmp/ta-live-1112/batch-05/canvas-list-test/grader.log) |
| `fillout-online-forms` | 正式答复和评分通过，评分器确认两份答卷符合预期。 | [评分](../../.tmp/ta-live-1112/service-recheck/fillout-online-forms/grader.log) |
| `gdp-cr5-analysis` | 上游模型请求超时。补齐文件夹 ID 后仍找不到目标表。 | [复评](../../.tmp/ta-live-1112/rescored/gdp-cr5-analysis/grader.log) |
| `inter-final-performance-analysis` | 达到 32 轮。补齐文件夹 ID 后仍缺 `sheet_url.txt`。 | [复评](../../.tmp/ta-live-1112/rescored/inter-final-performance-analysis/grader.log) |
| `inventory-sync` | 对话超时，复评确认 51 项商品库存数量不符。 | [复评](../../.tmp/ta-live-1112/rescored/inventory-sync/grader.log) |
| `investment-decision-analysis` | 上游模型请求超时，目标文件夹中没有所需工作表。 | [评分](../../.tmp/ta-live-1112/batch-02/investment-decision-analysis/grader.log) |
| `llm-training-dataset` | 到达 token 上限，评分器读取的 `ptdata` 为空或不存在。 | [评分](../../.tmp/ta-live-1112/batch-02/llm-training-dataset/grader.log) |
| `mrbeast-analysis` | 补齐 YouTube 工具后仍遇上游模型超时，工作簿明细 0 行，期望 32 行。 | [评分](../../.tmp/ta-live-1112/service-recheck/mrbeast-analysis/grader.log) |
| `music-analysis` | 对话超时，缺 `music_analysis_result.xlsx`。 | [评分](../../.tmp/ta-live-1112/batch-01/music-analysis/grader.log) |
| `nhl-b2b-analysis` | 对话超时，评分器未读到至少一行表头和一行数据。 | [评分](../../.tmp/ta-live-1112/batch-03/nhl-b2b-analysis/grader.log) |
| `nvidia-stock-analysis` | 接入网页搜索后到达 token 上限，缺 `results.xlsx`。 | [评分](../../.tmp/ta-live-1112/search-retry/nvidia-stock-analysis/grader.log) |
| `search-ca-school` | 到达 token 上限，缺学校排名 JSON。 | [评分](../../.tmp/ta-live-1112/batch-02/search-ca-school/grader.log) |
| `subway-planning` | 正式答复和评分通过。 | [运行](../../.tmp/ta-live-1112/batch-02/subway-planning/report.json) |
| `trip-adviser` | 到达 token 上限，缺 `travel_plan.json`。 | [评分](../../.tmp/ta-live-1112/batch-03/trip-adviser/grader.log) |
| `trip-itinerary-generator` | 正式答复和评分通过，营业时间与路线距离符合判据。 | [评分](../../.tmp/ta-live-1112/batch-04/trip-itinerary-generator/grader.log) |
| `vlm-history-completer` | 用完 48 次工具调用，匹配 20 个模型，架构和来源各有 0 项正确。 | [评分](../../.tmp/ta-live-1112/batch-04/vlm-history-completer/grader.log) |
| `wandb-best-score` | 产物评分通过，累计 2,048,375 token 后返回执行限制。 | [运行](../../.tmp/ta-live-1112/batch-01/wandb-best-score/report.json) |
| `wandb-shortest-length` | 正式答复和评分通过。 | [运行](../../.tmp/ta-live-1112/batch-01/wandb-shortest-length/report.json) |
| `youtube-repo` | 两轮动作协议反馈后停止，工具调用计数为 0，缺 `ml_tech.md`。 | [运行](../../.tmp/ta-live-1112/batch-05/youtube-repo/report.json) · [评分](../../.tmp/ta-live-1112/batch-05/youtube-repo/grader.log) |

### Notion 官方 MCP 复制后的补跑

| 用例 | 可观察结果 | 证据 |
| --- | --- | --- |
| `oil-price` | 写入 12 行月度数据，原产物复评通过。对话达到 token 上限并返回执行限制。 | [对话](../../.tmp/ta-notion-mcp-1112/oil-price-schema/oil-price/report.json) · [复评](../../.tmp/ta-notion-mcp-1112/rescored/oil-price/grader.log) |
| `experiments-recordings` | 达到 token 上限，评分中的 2 项预期实验记录均未匹配。 | [评分](../../.tmp/ta-notion-mcp-1112/remaining-notion/experiments-recordings/grader.log) |
| `notion-find-job` | 两次页面属性更新被拒后停止。评分时两项申请状态仍是 `Checking`，期望为 `Applied`。 | [评分](../../.tmp/ta-notion-mcp-1112/remaining-notion/notion-find-job/grader.log) |
| `notion-hr` | 补挂 Schema 后复跑达到 token 上限，评分读取到 7 条候选人记录，期望 10 条。 | [重跑评分](../../.tmp/ta-notion-mcp-1112/database-schema-recheck/notion-hr/grader.log) |
| `notion-movies` | 补挂 Schema 后复跑达到 token 上限。评分器读到了目标电影记录，缺少 YouTube 预告片链接。 | [重跑评分](../../.tmp/ta-notion-mcp-1112/database-schema-recheck/notion-movies/grader.log) |
| `notion-personal-website` | 正式答复和官方评分均通过。 | [评分](../../.tmp/ta-notion-mcp-1112/remaining-notion/notion-personal-website/grader.log) |
| `quantitative-financial-analysis` | 该批次在持久化阶段返回 HTTP 500。2026 年 11 月 13 日修复归档与 Notion 评论权限、工具映射后，定向复跑交付正式答复并通过官方评分。 | [该批次对话](../../.tmp/ta-notion-mcp-1112/remaining-notion/quantitative-financial-analysis/report.json) · [定向复跑](../../.tmp/ta-notion-mcp-1112/comment-retry/quantitative-financial-analysis/report.json) |
| `task-tracker` | 用完 48 次工具调用。Notion 表有 87 行，期望 116 行。GitHub 缺少 `finalpool` 分支。 | [评分](../../.tmp/ta-notion-mcp-1112/remaining-notion/task-tracker/grader.log) |
