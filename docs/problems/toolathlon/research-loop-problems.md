# Toolathlon 研究增强执行链问题汇总

截至 2026-11-14 21:39（UTC+8），本轮双 Agent 复跑已封存 60 个用例的至少一侧结果。personalAgent 有 56 份报告，其中 48 份追踪记录有已接纳的 Goal 操作，5 份有当前链的追踪但未接纳 Goal，3 份缺少可用的对话追踪。当前链在本轮关闭目标核验和回答核验，仍执行 Goal 维护、动作校验和交付检查。另纳入明确执行了 Goal 的 Redis、法律条款、文件审批和时区专项验证。[对照批次归档](../../../.tmp/tac1114/summary.json) · [专项验证入口](../../optimization/to_verify/analysis-goal-maintenance.md#统一入口复验结果)

首批和定向重试的生产源码指纹对应 `345c626`，晚间续跑的指纹还包含当时工作区的对话循环改动。三组都使用 MiniMax-M3.1-Flash 和 Toolathlon `9be8d8fe07a497b18ee61e3f2ae694e9797f39eb`。现象对应各自运行版本，跨样本汇总只用于定位问题。原始题目、配置、日志和评分按各运行身份封存。[首批身份](../../../.tmp/tac1114/runs/identity.json) · [重试身份](../../../.tmp/tac1114/retries/identity.json) · [续跑身份](../../../.tmp/tac1114/window-20261114-102056/identity.json)

按 21:39 同一快照剔除 `canvas-list-test` 的泄露配对后，44 个有效评分配对中，两边均通过 17 例，仅官方通过 5 例，仅 personalAgent 通过 3 例，两边均未通过 19 例。personalAgent 有 6 例产物评分通过但未返回正式答复。评分异常、额度中断和未评分结果单独看待。12 个 Google Cloud 或 Snowflake 用例按既定范围暂缓。

## Goal、计划和证据动作

| 问题 | 已观察到的执行后果 |
| --- | --- |
| Goal 的证据位置无法接纳 | `nvidia-market` 前两轮提交的任务证据均无法在当前用户消息定位，运行在任何工具执行前停止，四张表都未通过。其他用例也收到同类反馈，其中部分随后恢复，单次拒绝不能解释整例失败。[追踪记录](../../../.tmp/tac1114/runs/nvidia-market/personal/product-data) · [评分](../../../.tmp/tac1114/runs/nvidia-market/personal/grader.log) |
| 工作计划引用 Goal 条目失败后，模型仍提交错误形状 | `detect-revised-terms` 第 4 轮计划与 Goal 绑定失败。随后模型把要求传数组的 `goal_item_ids` 传成对象，再传成包含 JSON 字面的字符串。重复拒绝后停止，缺少 `revised_terms.csv`。`mrbeast-analysis` 在同一字段连续传对象，工作簿的明细表有 0 行，参考为 32 行。[条款追踪](../../../.tmp/tac1114/runs/detect-revised-terms/personal/product-data/interaction_runs/irun_d4ed0c7a52e04d7d/0034.json) · [视频明细追踪](../../../.tmp/tac1114/runs/mrbeast-analysis/personal/product-data/interaction_runs/irun_f735f388573b4126/0063.json) · [视频明细评分](../../../.tmp/tac1114/runs/mrbeast-analysis/personal/grader.log) |
| 研究证据选择反复违反声明 | `find-alita-paper` 已下载与参考一致的 PDF，`logical-datasets-collection` 已生成评分接受的产物。两例提交 `control_select_research_evidence` 时用了无效的 `status` 或把 `references` 数组传成对象，最终没有答复。`add-bibtex` 两次在 `references` 上失败，已有 BibTeX 仍有作者不符和条目缺失。[PDF 追踪](../../../.tmp/tac1114/runs/find-alita-paper/personal/product-data/interaction_runs/irun_86518b7ce3984150/0059.json) · [数据集报告](../../../.tmp/tac1114/runs/logical-datasets-collection/personal/report.json) · [BibTeX 评分](../../../.tmp/tac1114/runs/add-bibtex/personal/grader.log) |
| 最终答复引用了材料中不可用的行 | `gdp-cr5-analysis` 的表格满分。第 37、38 轮的答复分别引用了未完整返回或不存在的行，连续被退回后以 `limitation` 结束。[答复追踪](../../../.tmp/tac1114/window-20261114-102056/gdp-cr5-analysis/personal/product-data/interaction_runs/irun_de6b6b12e1694d96/0228.json) · [表格评分](../../../.tmp/tac1114/window-20261114-102056/gdp-cr5-analysis/personal/grader.log) |
| 卸载长输出后，交付要补读材料 | 14 个 personalAgent 样本收到 `offloaded_output_unread`。例如 `cooking-guidance` 两次被退回，补读后提交了答复，最终扣分来自购物清单。`dataset-license-issue` 最终写入了合格产物，但到第 64 轮仍未提交答复。这些历史运行中的未读检查在两类语义核验关闭时仍执行。该检查现已退役。[烹饪报告](../../../.tmp/tac1114/runs/cooking-guidance/personal/report.json) · [许可问题报告](../../../.tmp/tac1114/window-20261114-102056/dataset-license-issue/personal/report.json) |
| 计划之外的普通工具也会反复收到非法参数 | `canvas-do-quiz` 已完成 13/14 份满分测验。第 28、29 轮的 `tool_graph_search` 参数接连违反 `structured_context` Schema，对话在补齐最后一项前停止。此处只确认停止前的拒绝，最后一份测验失分的业务原因需另查。[追踪记录](../../../.tmp/tac1114/runs/canvas-do-quiz/personal/product-data/interaction_runs/irun_9ab0997f99a34b34/0173.json) · [评分](../../../.tmp/tac1114/runs/canvas-do-quiz/personal/grader.log) |

## 工具接入和执行结果

| 问题 | 已观察到的执行后果 |
| --- | --- |
| 工具声明缺少评测工作区 CSV 的读写入口 | `canvas-list-test` 的 personalAgent 看到了 Canvas、Memory 和草稿工具。草稿入口支持 Python、JSON 或 Markdown 草稿，尝试以它创建 CSV 时被拒。模型搜索模板期间 22 次 Canvas 文件读取和 17 次网页读取失败，最终用完 128 次调用。两份原始 CSV 未修改，各只有 1 行，参考为 13 条测验和 4 条作业。官方 Agent 在评测工作区用 Python 读写 CSV，并用脚本批量查询 Canvas，共 26 次工具调用。工具集差异会影响这组时长和用量对照。[personalAgent 追踪](../../../.tmp/tac1114/runs/canvas-list-test/personal/product-data/interaction_runs/irun_957b1451c46b4acf/0166.json) · [官方追踪](../../../.tmp/tac1114/runs/canvas-list-test/official/traj_log.json) |
| 邮件协议回包和实际发送结果冲突 | `git-bug-hunt`、`filter-low-selling-products`、`apply-phd-email` 的 personalAgent 共 19 次邮件 MCP 调用均收到 SMTP `550 Authentication required`。服务回包同时声明 `isError: false`，客户端按协议标志记录为成功。前两例评分邮箱未找到目标邮件。第三例评分找到附件但有一份 PDF 内容不同，不能用那批调用的成功状态证明附件已正确送达。[Git 调查追踪](../../../.tmp/tac1114/window-20261114-102056/git-bug-hunt/personal/product-data/interaction_runs/irun_eca5e6f3683544c1/0060.json) · [商品追踪](../../../.tmp/tac1114/window-20261114-102056/filter-low-selling-products/personal/product-data/interaction_runs/irun_c12a4bcd606e45a7/0363.json) · [申请追踪](../../../.tmp/tac1114/window-20261114-102056/apply-phd-email/personal/product-data/interaction_runs/irun_e9a672ecfb5a4028/0384.json) · [MCP 客户端](../../../src/personal_agent/infra/mcp.py#L84) |
| 长操作返回超时后，实际操作仍可能运行 | Redis 专项中，第 42 轮发起实际升级，网关等终端 MCP 60 秒超时后重试，撞上仍在运行的 Helm 操作。第 59 轮确认 Chart 已升到 `22.0.0`、修订 2，评分满分。HTTP 调用方仍在 1,200 秒后超时，最终追踪记录在第 64 轮结束。单样本可确认命令、集群及交付的三个状态，无法量化关闭核验的单独收益。[Redis 报告](../../../.tmp/rno-1113/retry/k8s-redis-helm-upgrade/report.json) · [Redis 评分](../../../.tmp/rno-1113/retry/k8s-redis-helm-upgrade/grader.log) |
| 审批写入成功后，续跑一度缺少工作区执行证据 | 专项首次批准并完成文件移动，答复阶段反复收到无效结果或动作反馈，最终返回 `limitation`。补入已提交的操作状态和路径后，同入口专项复验通过，审批前无写入，审批后文件位置正确且交付答复。该结论覆盖专项文件移动。[首次报告](../../../.tmp/one-loop-approve/report.json) · [复验报告](../../../.tmp/one-loop-ap2/report.json) · [实现与验收记录](../../optimization/to_verify/analysis-goal-maintenance.md#统一入口复验结果) |

`canvas-list-test` 在 2026-11-14 的定向复跑中补齐了工作区 Filesystem MCP。模型读取了两份原始 CSV，另一次独立检查确认写工具能覆写同名文件。复跑仍未通过。模型在查完 14 门课的作业与测验列表后仍继续查询或检索，累计 45 轮、128 次工具调用，结束前没有提交文件写入。两份模板仍各有 1 行，评分预期分别为 13 条测验和 4 条作业。[接入与复跑记录](../../evals/04-running-and-release.md#canvas-未提交测验与作业的-csv-交付) · [复跑轨迹](../../../.tmp/tac1114/csv-fix-1114/canvas-list-test/personal/product-data/interaction_runs/irun_4c88ddf7a44542b7/0273.json)

2026-11-15 补齐 `canvas-list-test` 的本地 Python 接入。授权会话成功执行 Python，原题复跑也验证了模型可见性及两份 CSV 的写回。剩余评分差异集中在测验的收录范围和课程学分。[本地 Python 接入复验](../../evals/04-running-and-release.md#本地-python-接入复验)

旧官方样本的 Python 读取了生成评分参考的预处理配置。将官方 Agent 移入独立容器后，Python 能访问两份原始 CSV，Canvas 和 Memory 可用，预处理与评分材料不可读。官方复跑写出两份 CSV 并答复。作业表完全匹配，测验表因遗漏三个练习测验未通过，另有八个学分与参考不一致。官方旧样本退出有效对照统计，隔离复跑作为独立结果记录。[隔离与复跑](../../evals/04-running-and-release.md#官方-agent-的评测材料隔离) · [官方新评分](../../../.tmp/tac1114/canvas-clean-1114/canvas-list-test/official/grader.log)

## 预算与交付

本轮 13 个 personalAgent 样本以执行预算限制结束。10 例走到第 64 轮，包括 `academic-pdf-report`、`apply-phd-email`、`canvas-art-manager`、`dataset-license-issue`、`hk-top-conf`、`huggingface-upload`、`inter-final-performance-analysis`、`language-school`、`latex-prompt-box` 和 `nvidia-stock-analysis`。`canvas-list-test`、`interview-report` 用完 128 次工具调用。`filter-low-selling-products` 在第 53 轮累计入账 8,028,273 token，超过 800 万运行预算。

这 13 例中，`dataset-license-issue`、`huggingface-upload` 和 `nvidia-stock-analysis` 已通过产物评分。另有 3 例在产物通过后因重复无效动作停止，见[证据选择和引用问题](#goal计划和证据动作)。

## 交付内容与原题或评分要求的差异

| 用例 | 可核实的差异 |
| --- | --- |
| `arrange-workspace` | 3 份文件位置不符，2 个应在 `Work` 下的目录放到了 `Work/Software`。双方均有 3 份文件归错。[personalAgent 评分](../../../.tmp/tac1114/runs/arrange-workspace/personal/grader.log) · [官方评分](../../../.tmp/tac1114/runs/arrange-workspace/official/grader.log) |
| `canvas-arrange-exam` | 9 行均有结果，8 行在来源类别中加了公告标题，`Announcement` 字段比对失败。官方写了类别值，9 行通过。[评分](../../../.tmp/tac1114/runs/canvas-arrange-exam/personal/grader.log) |
| `cooking-guidance` | 模型把库存的五花肉视为菜谱要求的五花肉薄片，未将后者列入购物清单。评分器将薄片计为库存缺项，购物覆盖率 8/9，低于 90% 门槛。[评分](../../../.tmp/tac1114/runs/cooking-guidance/personal/grader.log) |
| `dietary-health` | 正确计算实际摄入，也在正文算出适用于 BMI 约 28.1 的休息日目标。摘要仍用通用目标，碳水 130–162.5 g、蛋白质 97.5 g。评分读取摘要，参考为 123.5–143 g 和 78 g。[产物](../../../.tmp/tac1114/runs/dietary-health/personal/workspace/analysis.md) · [评分](../../../.tmp/tac1114/runs/dietary-health/personal/grader.log) |
| `apply-phd-email` | 收到的附件目录中 `All_Awards_Certificates.pdf` 内容与参考不同。官方 Agent 附件评分通过，其对话在第 64 轮结束，未交付正式答复。[personalAgent 评分](../../../.tmp/tac1114/window-20261114-102056/apply-phd-email/personal/grader.log) · [官方报告](../../../.tmp/tac1114/window-20261114-102056/apply-phd-email/official/report.json) |
| `canvas-art-manager` | 评分按 `admin3` 对应的 27 门预期课程检查，在相应讲师名下未找到这些课程。日志确认远程结果缺失，具体创建流程卡点待定位。[评分](../../../.tmp/tac1114/runs/canvas-art-manager/personal/grader.log) |
| `canvas-submit-late-work` | 作业 4 和 6 的记录都没有评分器能匹配的附件或正文。[评分](../../../.tmp/tac1114/runs/canvas-submit-late-work/personal/grader.log) |
| `academic-pdf-report` | 复跑的报告中，评分检查的 6 篇论文无一填全。日志列举了第一作者、机构和 Google Scholar 资料缺项。[复跑评分](../../../.tmp/tac1114/retries/academic-pdf-report/personal/grader.log) |
| `detect-revised-terms` | 较早的 Goal 专项能写出 CSV 和答复，但产物 10 行，参考接受 9 行或 8 行。双 Agent 批次中，本侧在计划阶段停止，官方侧写了 12 行。两次 personalAgent 运行暴露了不同边界的问题。[Goal 专项](../../../.tmp/one-loop-ta/report.json) · [批次本侧评分](../../../.tmp/tac1114/runs/detect-revised-terms/personal/grader.log) · [批次官方评分](../../../.tmp/tac1114/runs/detect-revised-terms/official/grader.log) |
| `imagenet` | 已写出 `survey.tex`，评分首个差异出现在模型列表，本侧填了 `LlamaGen-3B`，参考同位置是 `DiT-XL/2`。当前执行链的本次失败发生在产物比对。[评分](../../../.tmp/tac1114/runs/imagenet/personal/grader.log) |
| `interview-report` | 重试后 DOCX 正文通过。表头单元格颜色检查失败，报告在用完工具额度时仍有版式差异。[复跑评分](../../../.tmp/tac1114/retries/interview-report/personal/grader.log) |
| `inventory-sync` | personalAgent 在 1,200 秒内未返回正式答复。结束时库存数量核对准确率为 0%，最后封存的追踪在第 37 轮。官方侧库存评分通过。当前日志可以确认数量不同，尚未定位首次错误读取或写入。[本侧报告](../../../.tmp/tac1114/window-20261114-102056/inventory-sync/personal/report.json) · [本侧评分](../../../.tmp/tac1114/window-20261114-102056/inventory-sync/personal/grader.log) · [官方评分](../../../.tmp/tac1114/window-20261114-102056/inventory-sync/official/grader.log) |
| `ipad-edu-price` | 对话给出价格结论并以 `limitation` 结束，评测工作区缺少指定的 `result.json`。[运行报告](../../../.tmp/tac1114/runs/ipad-edu-price/personal/report.json) · [评分](../../../.tmp/tac1114/runs/ipad-edu-price/personal/grader.log) |
| `latex-prompt-box` | `main.tex` 已引入宏包并定义颜色。填入内容的开头与评分器接受的 Simple Prompt 渲染不符。[评分](../../../.tmp/tac1114/runs/latex-prompt-box/personal/grader.log) |
| `privacy-desensitization` | 返回正式答复并生成产物，评分报告有 13 处内容差异。这份记录只能确认差异数，各差异的隐私影响仍需逐条复核。[评分](../../../.tmp/tac1114/runs/privacy-desensitization/personal/grader.log) |
| `hk-top-conf`、`language-school`、`inter-final-performance-analysis` | 三例到达第 64 轮。评分分别缺少 `result.md`、`cs_top10_us.xlsx` 和 `sheet_url.txt`。第三例网关另有 60 秒等待超时记录，现有证据未确认所有未写出产物的上游原因。[会议评分](../../../.tmp/tac1114/runs/hk-top-conf/personal/grader.log) · [学校评分](../../../.tmp/tac1114/runs/language-school/personal/grader.log) · [比赛分析评分](../../../.tmp/tac1114/window-20261114-102056/inter-final-performance-analysis/personal/grader.log) |

在有效配对中，`identify-all-songs` 是仅 personalAgent 有合格产物且有正式答复的一例，官方侧缺 `songs.md`。`course-assistant` 双方产物均通过，只有 personalAgent 返回正式答复。时区专项走过 Goal 和两类核验，上海 09:00 转换东京 10:00 的运行通过。[歌曲评分](../../../.tmp/tac1114/runs/identify-all-songs/official/grader.log) · [课程助理报告](../../../.tmp/tac1114/window-20261114-102056/course-assistant/official/report.json) · [时区专项](../../../.tmp/one-loop-time/report.json)

## 评测准备、评分和外部服务

| 问题 | 已观察到的执行后果 |
| --- | --- |
| 准备阶段的服务失败 | `experiments-recordings` 两侧均在等待预处理参考文件时超过 360 秒，模型未启动，尚不能从该日志确认 Notion 内部阻塞点。`email-paper-homepage` 的本侧预处理创建 GitHub 仓库收到 403，官方侧进入对话但把要求的 `COML 2025` 写成了 `COML 2026`。`inter-final-performance-analysis` 官方侧预处理因 SSL EOF 失败。[Notion 预检](../../../.tmp/tac1114/window-20261114-102056/experiments-recordings/personal/report.json) · [GitHub 预检](../../../.tmp/tac1114/window-20261114-102056/email-paper-homepage/personal/gateway.log) · [官方会议信息评分](../../../.tmp/tac1114/window-20261114-102056/email-paper-homepage/official/grader.log) · [Sheets 预检](../../../.tmp/tac1114/window-20261114-102056/inter-final-performance-analysis/official/gateway.log) |
| 部分预检问题通过重试进入正式评测 | `git-milestone` 占位令牌触发 401，匿名查询公开仓库后两边均通过。`apply-phd-email` 首次 IMAP 登录因非 TLS 连接拒绝明文认证，续跑两侧都进入正式评测，附件和发信结果见上文。[GitHub 首次日志](../../../.tmp/tac1114/runs/git-milestone/personal/gateway.log) · [GitHub 复跑](../../../.tmp/tac1114/retries/git-milestone/personal/report.json) · [IMAP 首次日志](../../../.tmp/tac1114/runs/apply-phd-email/personal/gateway.log) |
| 评分器读远端结果所需的工具不可用 | `canvas-new-students-notification` 两侧均给出正式答复，评分器调用 `canvas_get_conversation` 时收到 `Unknown tool`。该次评分无法判断通知实际内容。[personalAgent 评分日志](../../../.tmp/tac1114/runs/canvas-new-students-notification/personal/grader.log) · [官方评分日志](../../../.tmp/tac1114/runs/canvas-new-students-notification/official/grader.log) |
| 官方搜索被拒与本侧模型请求被拒 | 官方侧 `academic-pdf-report`、`add-bibtex`、`cvpr-research` 调 Serper 收到 403。personalAgent 的 `cvpr-research` 另因模型提供方返回 422，由接口作为 502 报出，未生成研究者名单。归档只表明提供方拒绝请求，未定位 422 的具体字段。[Serper 日志](../../../.tmp/tac1114/runs/academic-pdf-report/official/agent.log) · [本侧请求错误](../../../.tmp/tac1114/runs/cvpr-research/personal/http-error.log) · [本侧评分](../../../.tmp/tac1114/runs/cvpr-research/personal/grader.log) |
| 产物导出和对话等待中断 | `academic-pdf-report` 首次容器工作区导出失败，重试成功导出并进入评分。`interview-report` 首次对话超时并发生进程关闭错误，重试取得 DOCX 评分。`paper-checker` 的本侧报告仍只有对话等待超时和进程关闭错误，缺少可用的对话追踪和评分。官方侧该例有 3 份文本与参考不符。[导出报告](../../../.tmp/tac1114/runs/academic-pdf-report/personal/report.json) · [面试报告首次证据](../../../.tmp/tac1114/runs/interview-report/personal/report.json) · [论文检查本侧报告](../../../.tmp/tac1114/runs/paper-checker/personal/report.json) · [论文检查官方评分](../../../.tmp/tac1114/runs/paper-checker/official/grader.log) |
| 模型额度中断 | MiniMax 返回 429、错误码 2056。此快照有 10 个用例仍带额度中断记录，包括 `profile-update-online`、`reimbursement-form-filler`、`search-ca-school`、`shopping-helper`、`stock-build-position`、`subway-planning`、`train-ticket-plan`、`travel-exchange`、`trip-adviser`、`trip-itinerary-generator`。中断前保存的评分可说明已有产物状态，不能用于比较完成能力。[额度查询](../../../.tmp/tac1114/quota.json) |

问题归因固定于上述证据快照。后续封存结果见[最新测试结果](agent-comparison.md)。
