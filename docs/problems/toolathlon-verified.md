# Toolathlon-Verified 扩展评测问题

2026 年 11 月 11 日在 personalAgent 上运行。目标为从未运行的官方任务中选 40 个，每批最多 8 个。上游固定在 `9be8d8fe07a497b18ee61e3f2ae694e9797f39eb`，经正式 `POST /api/conversation/turn` 进入 personalAgent。模型为 MiniMax-M3.1-Flash，沿用 32 个主决策轮、48 次工具调用和 200 万 token 的配置。题面保留原始英文并附任务工作区路径。之前的 `arrange-workspace`、`imagenet` 和 `detect-revised-terms` 评分保留原运行身份。[运行归档](../../.tmp/ta40-1111/) · [归档时工作树指纹](../../.tmp/ta40-1111/identity.json)

## 运行结果

共尝试 26 个不同任务，12 个进入正式对话并取得上游评分，14 个停在网关预检。距 40 个正式用例仍差 28 个，其中 14 个尚未排程。评测配置每批最多 8 个任务槽，按首笔模型请求到 Web 停止信号计，正式对话峰值并发为 7。已归档轨迹共记录 14,282,152 token。[逐例结果](../../.tmp/ta40-1111/summary.json) · [证据校验和](../../.tmp/ta40-1111/summary.sha256)

上游评分通过 7 个、未通过 5 个。`invoice-org` 同时返回了正式答复并通过评分。另 6 个通过上游文件检查的任务都未交付正式答复。

| 任务 | 对话结果 | 上游评分 |
| --- | --- | --- |
| `invoice-org` | 正式答复 | 通过 |
| `find-alita-paper` | 完成检查反复提交后超时 | 缓存 PDF 比对通过 |
| `cooking-guidance`、`excel-data-transformation` | 请求超时 | 文件补评通过 |
| `excel-market-research`、`courses-ta-hws` | 执行预算限制 | 通过 |
| `sales-accounting` | 等待长期知识保存确认 | 通过 |
| `interview-report`、`paper-checker`、`shopping-helper` | 重复无效动作后停止 | 未通过 |
| `privacy-desensitization` | 执行预算限制 | 未通过 |
| `dietary-health` | 请求超时 | 未通过 |

## 完成检查拒绝后重复提交旧答复

`find-alita-paper` 成功检索和下载 Alita 论文，并将 PDF 移入任务工作区。上游评分器无法联网解析 arXiv 的当前版本，按自身回退逻辑核对缓存，确认 PDF 与 v1 参考文件的 MD5 一致并返回 0。日志里有一笔 `web_read` 的 TLS 证书验证失败，后续仍取得了论文、标题和链接。调用方最终等到请求超时，运行日志未形成 `final_message`。[先导报告](../../.tmp/ta40-1111/alita/report.json) · [评分日志](../../.tmp/ta40-1111/alita/grader.log) · [最终状态快照](../../.tmp/ta40-1111/alita/product-data/interaction_runs/irun_bd7a3a11f1424abf/0819.json)

最终快照包含 378 对同轮次的 `submitted_final` 与 `offloaded_output_unread`，模型调用量停在 11 次、主决策停在第 9 轮。完成检查要求查看工具输出省略部分，提交恢复分支随后从已审查的研究结果重建同一份答复。恢复分支只检查研究结论和核验状态，新的完成反馈没有使旧答复失效，下一次循环也就没有把反馈交给模型。这个循环在固定的轮数、工具和 token 用量下继续写入快照，直到评测请求到达 600 秒超时。[恢复入口](../../src/personal_agent/application/conversation/service.py#L658) · [研究答复恢复](../../src/personal_agent/application/conversation/answer_results.py#L281) · [完成反馈](../../src/personal_agent/application/conversation/service.py#L1014)

## 网关接入与任务服务

聚合网关通过旧式 SSE 返回调用结果。当前 HTTP 客户端直接初始化时，`POST /sse` 得到 405，`POST /mcp` 得到 404。评测临时使用 stdio 到 SSE 的转接，先导样本已验证实际的列目录、检索、下载与文件移动调用。[接入验证](../mcpDesign/README.md#531-聚合网关接入验证) · [能力发现](../../.tmp/ta40-1111/discovery.json)

首批 8 个本地任务均通过联网的网关预检。正式尝试时改为断网冷启动，7 个在网关健康检查阶段超时，只有 `sales-accounting` 进入对话。随后改为在联网时初始化网关、核对已连接服务，再断网进入本地文件任务对话。该轮仍有 `ppt-analysis` 在进入模型前超时，网关日志记录了 MCP 初始化等待 10 秒未收到响应。[联网预检](../../.tmp/ta40-1111/preflight/report.json) · [断网冷启动记录](../../.tmp/ta40-1111/batch-01/) · [PPT 网关日志](../../.tmp/ta40-1111/batch-02/ppt-analysis/gateway.log)

第二组候选的 8 个任务首次均在网关健康检查前超时。重试优先使用 npm 缓存，`dietary-health`、`invoice-org` 和 `shopping-helper` 通过预检。另 8 个候选仍未在 100 秒内通过健康检查。上游网关在所需 Server 完成连接后才对外提供健康检查，超时记录需结合各任务启动日志判断。[第二组预检](../../.tmp/ta40-1111/preflight/public-report.json) · [第二组预检重试](../../.tmp/ta40-1111/preflight-retry/public-report.json) · [另 8 个候选的预检](../../.tmp/ta40-1111/preflight-more/public-report.json)

`invoice-org` 首次正式尝试通过网关预检后，卡在评测数据库的 `pg_isready` 探针，单次 `docker exec` 超过 5 秒。单独重试时就绪探针通过，随后完成正式对话和评分。评分器核对了 7 行发票数据和总金额，CSV 的商家列不在该评分判据中。[首次尝试](../../.tmp/ta40-1111/batch-03/invoice-org/report.json) · [重试评分](../../.tmp/ta40-1111/batch-04/invoice-org/grader.log)

网关启动阻塞在有界重试后仍出现，后续批次暂停排程。本机以示例配置启动网关，尚未配置完整数据集所需的基准测试账号和隔离服务，包括 Google 相关服务、Canvas、邮件与 WooCommerce。[评测阻塞规则](../devSpec/change-evidence.md#72-重复阻塞先复审方案再继续)

## 动作参数校验后提前停止

`paper-checker` 首次文件读取提案缺少 `head`、`tail`，第二次的 `tail` 类型不符合模型动作 Schema。两个提案在模型动作校验处被拒。运行时随后返回重复无效动作的限制答复，评分器发现 4 个文件还有差异。将预检取得的 Schema 通过当前投影代码重算，上游只要求 `path`，模型动作要求 `path`、`head` 和 `tail` 都出现，后两项允许填 JSON `null`。归档保留字段级诊断和请求引用，服务方对原始请求的约束执行情况未验证。[上游 Schema](../../.tmp/ta40-1111/preflight/paper-checker/report.json) · [动作定义](../../src/personal_agent/application/conversation/model_actions.py#L178) · [评分日志](../../.tmp/ta40-1111/batch-02/paper-checker/grader.log)

`interview-report` 在生成报告前连续两次提交不符合 Schema 的工作计划。第一次的步骤有额外属性，且 `status` 不符合约束。第二次仍包含额外属性。运行时返回同一类限制答复，评分器发现缺少候选人报告。该轨迹同时记录了模型连接提前关闭与重试。[状态快照](../../.tmp/ta40-1111/batch-02/interview-report/product-data/interaction_runs/irun_bb7f3e07ccfe46fb/0046.json) · [评分日志](../../.tmp/ta40-1111/batch-02/interview-report/grader.log)

`shopping-helper` 在两次文件读取提案分别触发 `head` 类型错误和 `tail` 缺失后返回限制答复。它在进入网页查询前就已停止。原始评分启动时缺少评分容器的 `configs/mcp_servers` 挂载。补齐挂载后对原工作区重评，3 条推荐均未通过字段及链接检查。[状态快照](../../.tmp/ta40-1111/batch-03/shopping-helper/product-data/interaction_runs/irun_10057f6f00de45b2/0023.json) · [原始评分日志](../../.tmp/ta40-1111/batch-03/shopping-helper/grader.log) · [补评日志](../../.tmp/ta40-1111/score-replay/shopping-helper/grader.log)

## 文件完成后进入无关的保存确认

`sales-accounting` 的本地账本通过上游检查。原题要求读取记忆中的交易并补到账本，正式对话却在最后返回 `confirmation_required`，要求确认写入长期知识，用户未收到任务答复。评测保留了这次确认和账本评分。[对话结果](../../.tmp/ta40-1111/batch-01/sales-accounting/report.json) · [评分日志](../../.tmp/ta40-1111/batch-01/sales-accounting/grader.log)

## 执行预算耗尽

`excel-market-research` 在累计 2,047,238 token 后返回预算限制。上游评分通过，模型未交付最终答复。发送前检查已入账的余量，单次请求的用量入账后超过 200 万 token。[预算检查](../../src/personal_agent/application/conversation/budget.py#L56) · [对话结果](../../.tmp/ta40-1111/batch-02/excel-market-research/report.json) · [评分日志](../../.tmp/ta40-1111/batch-02/excel-market-research/grader.log)

`privacy-desensitization` 在第 32 个主决策轮、累计 1,811,730 token 时返回预算限制。评分器发现 13 个脱敏输出的内容与期望不同。[对话结果](../../.tmp/ta40-1111/batch-02/privacy-desensitization/report.json) · [评分日志](../../.tmp/ta40-1111/batch-02/privacy-desensitization/grader.log)

`courses-ta-hws` 同样在第 32 个主决策轮停下，累计 1,609,478 token。工作区文件通过上游评分，对话返回预算限制。[对话结果](../../.tmp/ta40-1111/batch-02/courses-ta-hws/report.json) · [评分日志](../../.tmp/ta40-1111/batch-02/courses-ta-hws/grader.log)

## 对话超时后补评已导出的文件

`cooking-guidance` 与 `excel-data-transformation` 在 600 秒请求时限内没有返回。两例最后保留的轨迹分别累计 1,929,784 与 1,917,594 token，均在本轮预算内。同版上游评分器对到期时的工作区快照补评，两例的文件均通过。[原始报告](../../.tmp/ta40-1111/batch-02/report.json) · [菜谱评分](../../.tmp/ta40-1111/score-replay/cooking-guidance/grader.log) · [表格评分](../../.tmp/ta40-1111/score-replay/excel-data-transformation/grader.log)

`dietary-health` 超时前已生成饮食分析文件，累计 1,859,124 token。上游评分发现三处营养数值偏差，包括期望最小值 123.5 g、实际 130.0 g。该轨迹在收到工具原件未读反馈后继续调用模型，与先导样本的自动重提交轨迹不同。[对话结果](../../.tmp/ta40-1111/batch-03/dietary-health/report.json) · [评分日志](../../.tmp/ta40-1111/batch-03/dietary-health/grader.log)

## 预检受阻的 14 个用例重跑

2026 年 11 月 11 日重跑首轮停在预检的 14 个用例，按 8 个和 6 个排程。上游版本、personalAgent 源码指纹、模型、轮数和工具与 token 预算均与首轮一致。新一轮从容器内探测网关就绪，保留上游预处理和 Server 初始化日志。网关启动等待窗口为 210 秒，正式对话请求时限仍为 600 秒。任务环境和评分各自归档。[重跑身份](../../.tmp/ta14-rerun-1111/identity.json)

14 个用例均进入正式对话并完成上游评分。`ppt-analysis` 和 `travel-exchange` 返回正式答复并通过评分。其余 12 个中，7 个到达执行预算，4 个在重复参数校验失败后停止，1 个在模型请求超时后返回 504。本次轨迹记录了 17,729,890 token。[逐例汇总](../../.tmp/ta14-rerun-1111/summary.json) · [证据校验和](../../.tmp/ta14-rerun-1111/summary.sha256)

`git-milestone` 首次重跑时，GitHub API 对三个仓库 ID 都返回 HTTP 401。上游示例令牌是占位值。仅在该用例的隔离配置里清空该值后，官方预处理通过匿名请求生成了评分参考，网关就绪并进入正式对话。模型随后两次提交无效的 `fetch.fetch_json` 参数，对话在第 2 个主决策轮停止。评分发现缺少 `github_info.json`。[预处理日志](../../.tmp/ta14-rerun-1111/batch-01/git-milestone/gateway.log) · [重试结果](../../.tmp/ta14-rerun-1111/git-retry/git-milestone/report.json) · [评分日志](../../.tmp/ta14-rerun-1111/git-retry/git-milestone/grader.log)

| 任务 | 对话与评分结果 |
| --- | --- |
| `ppt-analysis` | 返回正式答复并通过上游评分。[评分](../../.tmp/ta14-rerun-1111/batch-01/ppt-analysis/grader.log) |
| `git-milestone` | 两次 `headers` 参数校验失败后提前停止，缺少结果文件。[结果](../../.tmp/ta14-rerun-1111/git-retry/git-milestone/report.json) |
| `cvpr-research` | 用完 48 次工具调用，缺少研究者名单。[评分](../../.tmp/ta14-rerun-1111/batch-01/cvpr-research/grader.log) |
| `logical-datasets-collection` | 达到 token 预算，缺少 `datasets.tex`。[评分](../../.tmp/ta14-rerun-1111/batch-01/logical-datasets-collection/grader.log) |
| `ipad-edu-price` | 达到 token 预算，缺少 `result.json`。[评分](../../.tmp/ta14-rerun-1111/batch-01/ipad-edu-price/grader.log) |
| `latex-prompt-box` | 达到 token 预算。评分找到宏包导入，未找到颜色定义。[评分](../../.tmp/ta14-rerun-1111/batch-01/latex-prompt-box/grader.log) |
| `reimbursement-form-filler` | 模型连接连续提前关闭，重试后对话返回 504。评分缺少部门报销表。[结果](../../.tmp/ta14-rerun-1111/batch-01/reimbursement-form-filler/report.json) |
| `university-course-selection` | 两次 Excel 格式化参数校验失败后停止。生成了 4 个课程方案，原题要求删除的模板仍在工作区，评分因有 5 个 Excel 文件而失败。[评分](../../.tmp/ta14-rerun-1111/batch-01/university-course-selection/grader.log) |
| `identify-all-songs` | 两次 `fetch.fetch_markdown` 的 `headers` 被拒，对话停止，评分缺少 `songs.md`。[评分](../../.tmp/ta14-rerun-1111/batch-02/identify-all-songs/grader.log) |
| `profile-update-online` | 两次文件读取的 `tail` 参数被拒，对话停止，评分未找到要求更新的两篇论文条目。[评分](../../.tmp/ta14-rerun-1111/batch-02/profile-update-online/grader.log) |
| `stock-build-position` | 用完 48 次工具调用。评分发现美团的初始仓位未填。[评分](../../.tmp/ta14-rerun-1111/batch-02/stock-build-position/grader.log) |
| `yahoo-analysis` | 到达第 32 个主决策轮，评分缺少目标文件。[评分](../../.tmp/ta14-rerun-1111/batch-02/yahoo-analysis/grader.log) |
| `hk-top-conf` | 到达第 32 个主决策轮，评分缺少 `result.md`。[评分](../../.tmp/ta14-rerun-1111/batch-02/hk-top-conf/grader.log) |
| `travel-exchange` | 返回正式答复并交付 `calculation.json`，上游汇率及支出检查均通过。[评分](../../.tmp/ta14-rerun-1111/batch-02/travel-exchange/grader.log) |

`git-milestone` 和 `identify-all-songs` 暴露了同一个工具 Schema 投影问题。上游 `fetch` 允许可选的请求头对象。当前投影要求 `headers` 出现，并给对象设置 `additionalProperties: false`，任何实际请求头键都会在发起调用前被拒。用本次工具发现结果重算投影，复现了这一约束。[Schema 对照](../../.tmp/ta14-rerun-1111/schema-projection.json) · [投影实现](../../src/personal_agent/kernel/llm_schemas.py#L122)

## 全量补跑

固定版本的 `finalpool` 共有 108 个任务。本轮开始时，29 个已进入 personalAgent 正式对话，另有 79 个待跑。继续使用 MiniMax-M3.1-Flash，每批最多 8 个，单任务预算为 32 个主决策轮、48 次工具调用、200 万 token，对话请求时限为 600 秒。每个任务使用独立数据库和工作区，由同版上游评分器评估导出的产物。[全量清单](../../.tmp/ta-remaining-1111/inventory.json) · [逐例结果](../../.tmp/ta-remaining-1111/summary.json) · [校验和](../../.tmp/ta-remaining-1111/summary.sha256)

本轮 7 个新任务进入正式对话并完成上游评分，累计覆盖 36 个。上游评分通过 1 个，未通过 6 个。通过的火车票文件对应的对话返回了 `limitation`，因此本轮同时取得正式答复和评分通过的任务数为 0。轨迹共记录 8,065,499 token，两例模型请求超时后的提供方用量记录不完整。

| 任务 | 对话结果 | 上游评分 |
| --- | --- | --- |
| `academic-pdf-report` | 用完 48 次工具调用 | 6 篇论文中完整匹配 0 篇。[评分](../../.tmp/ta-remaining-1111/batch-01/academic-pdf-report/grader.log) |
| `add-bibtex` | 上游模型请求超时，返回 HTTP 504 | 缺少参考文献条目。[评分](../../.tmp/ta-remaining-1111/batch-01/add-bibtex/grader.log) |
| `course-schedule` | 对话请求到达 600 秒时限 | 考场字段期望为 `3302`，实际为 `3303`。[评分](../../.tmp/ta-remaining-1111/batch-01/course-schedule/grader.log) |
| `language-school` | 用完 48 次工具调用 | 缺少 `cs_top10_us.xlsx`。[评分](../../.tmp/ta-remaining-1111/batch-01/language-school/grader.log) |
| `nvidia-market` | 达到 token 预算后返回限制 | 四张工作表的检查均未通过。[评分](../../.tmp/ta-remaining-1111/batch-01/nvidia-market/grader.log) |
| `train-ticket-plan` | 写出车票方案，对话返回 `limitation` | 补齐评分日志元数据后，同一文件通过上游复评。[对话](../../.tmp/ta-remaining-1111/rail-online/train-ticket-plan/report.json) · [复评](../../.tmp/ta-remaining-1111/rail-rescore/train-ticket-plan/grader.log) |
| `verl-dataset` | 匿名 Hugging Face MCP 就绪。上游模型请求超时，返回 HTTP 504 | 缺少 `verl_deepscaler.parquet`。[评分](../../.tmp/ta-remaining-1111/batch-02/verl-dataset/grader.log) |

### 火车票依赖与评分输入

`train-ticket-plan` 第一次在 12306 MCP 初始化阶段超时。第二次预装 `12306-mcp@0.3.9`，npm 读取旧缓存时报告找不到 `minimatch@3.1.5`。预装时刷新 registry 元数据后，四个所需 MCP 全部就绪，任务进入正式对话。[首次预检](../../.tmp/ta-remaining-1111/batch-01/train-ticket-plan/gateway.log) · [缓存诊断](../../.tmp/ta-remaining-1111/batch-02/train-ticket-plan/gateway.log) · [就绪记录](../../.tmp/ta-remaining-1111/rail-online/train-ticket-plan/health.json)

评分器从对话日志的 `config.launch_time` 计算下周四、周日。首次评分的适配层只传了命令行参数，评分器读取日志时触发 `KeyError: 'config'`。用网关记录的实际启动时间补齐日志后，对原文件复评，周四和周日的车票检查均通过。文件只包含车次与时刻，评分器使用 11 月 19 日与 22 日核对这些车次。对话正文写的是 11 月 12 日与 15 日，日期差异未体现在文件评分里。[首次评分](../../.tmp/ta-remaining-1111/rail-online/train-ticket-plan/grader.log) · [文件](../../.tmp/ta-remaining-1111/rail-online/train-ticket-plan/workspace/train-ticket-plan.json) · [复评输入](../../.tmp/ta-remaining-1111/rail-rescore/train-ticket-plan/grader-input.json)

### 尚未进入正式对话的任务

72 个任务仍待跑。按本轮要求跳过 51 个缺少基准账号或授权的任务，其中 15 个也依赖本地服务。另有 20 个只依赖本地服务，涉及 Canvas、Poste、WooCommerce 和 Kubernetes。依赖组合和对应任务可逐例查询。[依赖清单](../../.tmp/ta-remaining-1111/summary.json) · [上游账号准备](https://github.com/hkust-nlp/Toolathlon/blob/9be8d8fe07a497b18ee61e3f2ae694e9797f39eb/global_preparation/how2register_accounts.md)

`nvidia-stock-analysis` 是其余 1 个用例。题目声明需要 `web_search` MCP，固定版本只提供上游智能体内部使用的搜索工具。预检连接了其他 5 个 MCP，缺少题目声明的 `web_search`，未启动模型。[预检结果](../../.tmp/ta-remaining-1111/preflight/nvidia-stock-analysis/report.json)

- Poste 固定使用 `analogic/poste.io:2.5.5`。Docker Registry 返回 HTTP 404，Docker CLI 报告 `no such manifest`。[镜像查询](../../.tmp/ta-remaining-1111/poste-image.log)
- Canvas 和 WooCommerce 的镜像拉取仍未完成。重试后 Canvas 仍有镜像层待拉取，WordPress 备用 Registry 查询返回 EOF。[镜像状态](../../.tmp/ta-remaining-1111/local-fixture-images.json) · [Canvas 拉取](../../.tmp/ta-remaining-1111/canvas-pull-retry.log) · [WordPress 拉取](../../.tmp/ta-remaining-1111/woo-fixture/wordpress-pull-retry.log) · [备用 Registry](../../.tmp/ta-remaining-1111/woo-fixture/ecr-manifest.log)
- Kubernetes 使用上游任务镜像自带的 kind 进行独立探测。拉取 `kindest/node:v1.27.3` 时超过探测窗口，清理了探测集群和网络。[探测日志](../../.tmp/ta-remaining-1111/kind-probe.log)

## GitHub 测试账号配置后的补跑

2026 年 11 月 12 日，使用测试账号 `KingTomL` 补跑 3 个用例。模型、预算、600 秒对话请求时限和上游版本沿用上一轮配置。3 个均进入 personalAgent 正式对话并取得官方评分，累计覆盖 39/108。官方评分通过 2 个，正式答复与官方评分均通过的用例数为 0。轨迹共记录 4,517,003 token，其中网站用例的提供方用量记录不完整。[运行身份](../../.tmp/ta-github-1112/identity.json) · [逐例结果](../../.tmp/ta-github-1112/summary.json) · [校验和](../../.tmp/ta-github-1112/summary.sha256)

| 用例 | 对话结果 | 官方评分 |
| --- | --- | --- |
| `git-repo` | 累计记录 2,104,898 token，返回执行预算限制 | `result.json` 通过检查。[对话](../../.tmp/ta-github-1112/batch-01/git-repo/report.json) · [评分](../../.tmp/ta-github-1112/batch-01/git-repo/grader.log) |
| `personal-website-construct` | 创建了 `LJT-Homepage`，后续模型请求超时并返回 HTTP 504 | 站点配置的姓名仍为模板默认值。[对话](../../.tmp/ta-github-1112/batch-01/personal-website-construct/report.json) · [评分](../../.tmp/ta-github-1112/batch-01/personal-website-construct/grader.log) |
| `sync-todo-to-readme` | 达到 600 秒对话请求时限 | `LUFFY` 的 `dev` 分支 README 中，TODO 列表更新通过检查。[对话](../../.tmp/ta-github-1112/batch-01/sync-todo-to-readme/report.json) · [评分](../../.tmp/ta-github-1112/batch-01/sync-todo-to-readme/grader.log) |

`sync-todo-to-readme` 的上游预处理会把 GitHub 令牌写到任务工作区。评测适配层在对话启动前移除了该文件，并通过 GitHub MCP 提供对 `LUFFY` 的写操作。Notion 用例仍待完成官方 MCP OAuth，其他 GitHub 用例仍有邮件、Hugging Face 写入、YouTube 或 Notion 依赖。[预检与适配](../../.tmp/ta-github-1112/preflight.py) · [其余用例依赖](../../.tmp/ta-remaining-1111/summary.json)

## 已配置服务后的补跑

2026 年 11 月 12 日，沿用 MiniMax-M3.1-Flash、32 轮、48 次工具调用、200 万 token 和 600 秒对话请求时限。地图服务使用 SerpApi。按本轮要求跳过 8 个 Google Cloud 云资源用例和 4 个 Snowflake 用例。首批尝试并行启动 8 个用例。Docker 在后续启动隔离数据库时返回 HTTP 500，此后每次同时运行至多 6 个用例。[运行身份](../../.tmp/ta-live-1112/identity.json) · [校验和](../../.tmp/ta-live-1112/summary.sha256)

本轮尝试 22 个用例，其中 21 个进入正式对话并取得官方评分，1 个停在预处理。官方评分通过 5 个，正式答复与官方评分均通过的有 4 个，分别为 `fillout-online-forms`、`subway-planning`、`trip-itinerary-generator` 和 `wandb-shortest-length`。累计进入正式对话的用例达到 61/108。剩余 47 个包括本轮跳过的 12 个、预处理受阻的 1 个和本轮尚未启动的 34 个。[逐例汇总](../../.tmp/ta-live-1112/summary.json)

有 6 个用例的最后一次对话以模型请求超时或 600 秒对话请求超时结束。`wandb-best-score` 的产物通过官方评分，对话达到 token 上限后返回 `limitation`。[W&B 评分](../../.tmp/ta-live-1112/batch-01/wandb-best-score/grader.log)

### 工具映射和模板预处理

- `mrbeast-analysis` 首次接入时，评测适配层混淆了 `youtube` 与 `youtube-transcript` 的工具归属，产品未提供视频与频道查询工具。按最长服务名前缀识别归属并补齐映射后，重跑时已提供这些工具。模型请求后续返回 HTTP 504，工作簿缺少视频明细。[首次运行](../../.tmp/ta-live-1112/batch-01/mrbeast-analysis/report.json) · [重跑](../../.tmp/ta-live-1112/service-recheck/mrbeast-analysis/report.json) · [评分](../../.tmp/ta-live-1112/service-recheck/mrbeast-analysis/grader.log)
- `canvas-do-quiz` 的 MCP 工具名保留 `canvas_` 前缀，首次映射遗漏了该服务的工具。补齐映射后进入正式对话，使用了 48 次工具调用。评分器检查了 14 份测验，满分数为 0。[首次预检](../../.tmp/ta-live-1112/local-01/canvas-do-quiz/report.json) · [重跑](../../.tmp/ta-live-1112/canvas-recheck/canvas-do-quiz/report.json) · [评分](../../.tmp/ta-live-1112/canvas-recheck/canvas-do-quiz/grader.log)
- `oil-price` 的官方预处理需要把源模板复制到评测页。诊断重试中，Playwright 等待 `Duplicate` 菜单项 30 秒后超时，预处理未生成 `duplicated_page_id.txt`，用例在启动模型前终止。该记录定位到模板复制步骤。[预处理日志](../../.tmp/ta-live-1112/notion-diagnostic/oil-price/gateway.log) · [上游选择器](https://github.com/hkust-nlp/Toolathlon/blob/9be8d8fe07a497b18ee61e3f2ae694e9797f39eb/utils/app_specific/notion/notion_page_duplicator.py#L110)

### 评分输入和临时目录

- `gdp-cr5-analysis` 和 `inter-final-performance-analysis` 首次评分未取得本轮预处理生成的文件夹 ID。补齐后用原产物复评，前者仍找不到目标工作簿，后者仍缺少 `sheet_url.txt`。[GDP 复评](../../.tmp/ta-live-1112/rescored/gdp-cr5-analysis/grader.log) · [比赛表现复评](../../.tmp/ta-live-1112/rescored/inter-final-performance-analysis/grader.log)
- `apply-phd-email` 的评分器需要在临时目录解包附件，`inventory-sync` 的评分器需要删除本轮商店配置。首次使用只读挂载导致这两处操作失败。为评分器提供可写的独立副本后，使用原产物复评，邮件附件有一份 PDF 内容不符，库存有 51 项数量不符。两次复评均未调用模型。[邮件复评](../../.tmp/ta-live-1112/rescored/apply-phd-email/grader.log) · [库存复评](../../.tmp/ta-live-1112/rescored/inventory-sync/grader.log)

## Notion 官方 MCP 复制验证

用 Toolathlon 已有的官方 MCP 分支替换评测环境中的浏览器复制流程。评测预处理复用 `notion-duplicate-page` 和 `notion-move-pages`。复制返回异步任务时，先查询任务结果，再使用该任务返回的副本 ID。OAuth 会话仅交给预处理，模型网关沿用限定到评测页的 Notion 工具配置。上游任务和评分器使用同一个副本 ID。[上游复制流程](https://github.com/hkust-nlp/Toolathlon/blob/9be8d8fe07a497b18ee61e3f2ae694e9797f39eb/utils/app_specific/notion/notion_page_duplicator.py#L529) · [Notion 官方工具契约](https://developers.notion.com/guides/mcp/tools-pages-reference)

先用 `oil-price` 验收。预处理应在 `Notion Eval Page` 下生成新副本，评测令牌能访问两张目标数据库，并把副本 ID 写入 `duplicated_page_id.txt`。通过该检查后，经正式入口运行原题和原评分器，分别记录模型答复与官方评分。按此顺序验证其余 7 个 Notion 用例。

Windows 完成授权的桥接版本为 `mcp-remote@0.16.6`。镜像内置的 `0.1.16` 使用不同的会话目录，首次容器尝试无法读取该授权。将预处理桥接固定为与登录端相同的版本后，容器可发现复制、查询异步状态和移动工具。`oil-price` 的本次真实复制响应直接返回副本 ID。校验确认副本位于评测页下，`Oil Market Summary` 和 `Spread Strategy Backtest` 均可读取，模型网关内已移除 OAuth 会话。[副本校验](../../.tmp/ta-notion-mcp-1112/oil-price-official/oil-price/notion-preflight.json) · [评测适配](../../.tmp/ta-notion-mcp-1112/preflight.py)

首次正式对话达到 token 预算后结束，官方评分发现总结数据库无有效数据。第 16 轮新增数据库记录时，网关发现的 `API-post-page` 只接受 `parent.page_id`。Toolathlon 自带的运行器会挂载 OpenAPI 补丁，该补丁声明了 `database_id` 和 `data_source_id` 两种数据库父级。本轮评测适配补齐该挂载，以网关实收 Schema 和同题重跑验证。[首次正式评分](../../.tmp/ta-notion-mcp-1112/oil-price-official/oil-price/grader.log) · [上游挂载](https://github.com/hkust-nlp/Toolathlon/blob/9be8d8fe07a497b18ee61e3f2ae694e9797f39eb/scripts/run_single_decoupled.sh#L493)

8 个用例均通过副本校验、进入正式对话并取得原评分器结果。官方评分通过 2 个，正式答复与评分均通过 1 个。以下结果采用每例最后一次运行及适用复评。[逐例归档](../../.tmp/ta-notion-mcp-1112/summary.json) · [校验和](../../.tmp/ta-notion-mcp-1112/summary.sha256)

| 用例 | 结果 | 证据 |
| --- | --- | --- |
| `oil-price` | 补挂 Schema 后写入 12 行月度数据。首次评分的 Notion 后续查询遇到 TLS 中断，同一产物复评通过。对话达到 token 上限并返回 `limitation`。 | [重跑对话](../../.tmp/ta-notion-mcp-1112/oil-price-schema/oil-price/report.json) · [原产物复评](../../.tmp/ta-notion-mcp-1112/rescored/oil-price/grader.log) |
| `notion-personal-website` | 正式答复和官方评分均通过。 | [评分](../../.tmp/ta-notion-mcp-1112/remaining-notion/notion-personal-website/grader.log) |
| `experiments-recordings` | 官方评分中 2 项预期记录均未匹配。 | [评分](../../.tmp/ta-notion-mcp-1112/remaining-notion/experiments-recordings/grader.log) |
| `notion-find-job` | 两项申请状态仍为 `Checking`，期望 `Applied`。 | [评分](../../.tmp/ta-notion-mcp-1112/remaining-notion/notion-find-job/grader.log) |
| `notion-hr` | 补挂 Schema 后评分读取到 7 条候选人记录，期望 10 条。 | [重跑评分](../../.tmp/ta-notion-mcp-1112/database-schema-recheck/notion-hr/grader.log) |
| `notion-movies` | 补挂 Schema 后未再出现数据库父级参数拒绝。评分器读到目标电影记录，缺少 YouTube 预告片链接。 | [重跑评分](../../.tmp/ta-notion-mcp-1112/database-schema-recheck/notion-movies/grader.log) |
| `quantitative-financial-analysis` | 对话返回 HTTP 500，评分器没有找到有效的 Google Sheets 链接。 | [对话](../../.tmp/ta-notion-mcp-1112/remaining-notion/quantitative-financial-analysis/report.json) · [评分](../../.tmp/ta-notion-mcp-1112/remaining-notion/quantitative-financial-analysis/grader.log) |
| `task-tracker` | Notion 表有 87 行，期望 116 行。GitHub 缺少 `finalpool` 分支。 | [评分](../../.tmp/ta-notion-mcp-1112/remaining-notion/task-tracker/grader.log) |
