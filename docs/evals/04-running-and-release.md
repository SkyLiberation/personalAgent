# 运行、归档与发布

## LongDS 长程分析基线

### v1.1 Lite 剩余任务执行规格（2026-10-25）

用户要求继续运行其余用例，并选择 Lite；随后明确要求没有官方翻译就保留原稿。已核对官方 Kimi Code 的 `build_turn_prompt` 直接使用原 `context/question`，官方数据集未提供中文题面。本次固定数据 revision `6b448459c333ecc050a2e89fcc65c0e044d763ac`，从官方 `task/longds_v1.1/task_list_lite.json` 收集 24 项，跳过已完整执行的 `business/netflix_movies_and_tv_shows/task3`，剩余 23 项、741 轮使用英文原稿各执行一次。旧任务中文 36 轮交付、27/36 评分保留原身份，与新英文结果分开报告。

| 需求 | 执行与验收 |
| --- | --- |
| `LITE-1`：保持官方任务边界 | 按官方清单顺序，每项从第 1 轮开始，使用该项原始数据和完整轮数；仅在真实 `answer` 后继续。每项新主体、对话、Python 许可和归档，失败保留，后续独立任务继续；同项不自动补跑 |
| `LITE-2`：官方题面保真 | 英文 `context/question` 逐字来自固定版本原件，按官方 `Context/Question` 标签拼接；不翻译、不改写、不提供参考答案或程序。保留原件、来源 URL、Git blob/LFS 校验和及题面摘要；独立评分读取原始答案 |
| `LITE-3`：沿用真实链路与评分 | 继续生产 HTTP、Composition Root、真实 MiniMax medium、固定分析镜像以及 `direct/none`；仍为 `unverified_flow_capture`。只评分 HTTP 成功且 `disposition=answer` 的实际回答，采用已核对版本的官方 Judge 和已有同配置资格，参考答案仅评分侧读取 |
| `LITE-4`：保持身份与停止线 | 每项固定 60M 已知生成 tokens、每轮 10M/40 次主决策及 3600 秒；未知用量记录但不单独停止。每项 Judge 独立 2M。任务间校验冻结源码、配置与材料，变化停止新任务；不覆盖任何已有归档 |

这是评测输入和执行适配，不改变 Runtime、生产 Prompt、权限或工具。现有 `longds_materials.py` 继续拥有准备与 seal，`run_longds.py` 继续拥有正式 HTTP 采集，`longds_judge.py` 继续拥有官方评分；将仅适用于 task3 的轮数、文件数和字节数约束改为固定来源的实际清单约束。批次入口负责串行选择、原件准备、逐项运行和结果索引，不替模型做分析。生产装配与依赖方向保持，架构正文无需新增业务结构。

零模型清单已收集：23 项轮数为 23—42，共 741 轮，原始输入约 9.47GB，包含目录、同名文件及非 CSV。单层文件保持原件上传；有目录的任务通过无分析结果的 ZIP 保留完整相对路径和原始字节，生成侧自行读取。材料准备逐文件校验 Git blob 或 LFS SHA-256，归档保存完整映射。既有 Python 输入 64MiB、512MiB 内存及 32MiB 临时盘限制保持；超过能力的真实拒绝或失败按原身份记录，不能缩减数据、抽样或扩大生产权限来迎合评测。

实施顺序：先按固定清单零模型收集轮数、文件类型与大小；再扩展已有材料和采集的任务边界，保持旧 task3 原件验证；静态检查和真实材料只读校验通过后，以首个剩余任务作为批次首项开始运行，逐项记录实际反馈和成本。沿用先前 36 轮约 3995 秒、26.4M tokens 作为规模参考，实际任务差异逐项报告；同配置成本明显超过该任务按轮数折算的参考两倍时，在任务安全结束后暂停新增任务并重审，不压低生产预算。

来源收集根为 `.tmp/longds-remaining-20261025/`，实际执行使用短路径 `.tmp/ls25/t01` 至 `t23`，避免 Windows `MAX_PATH`；任务编号由结果内的完整官方身份绑定。下载缓存按经核验的 Git/LFS 摘要命名，ZIP 内仍保持官方原相对路径。启动时冻结全部原题、数据树、来源 URL 和摘要，任务开始前及材料准备后校验冻结材料、源码和配置；采集抛异常且无法确认 Web 已停止时暂停批次。历史 Judge 资格从原封存目录只读引用，不复制进新费用账本。

开始前核实 Docker、固定镜像及本地评测数据库；不运行已停用单元测试。批次已于 2026-10-25 北京时间 13:46 启动，后续题面语言和实际成绩由[用例盘点](02-current-case-inventory.md#2026-10-25-longds-v11-lite-剩余-23-项原稿执行原批次结束续跑已启动)及独立归档记录。

```powershell
.\.venv\Scripts\python.exe -B -X utf8 -m evals.product_baselines.longds_suite --root .tmp/longds-remaining-20261025 --collect-only
.\.venv\Scripts\python.exe -B -X utf8 -m evals.product_baselines.longds_suite --root .tmp/longds-remaining-20261025 --output .tmp/ls25
```

执行目录必须尚不存在；`progress.json` 提供当前任务、逐项结果及停止原因，`t01` 至 `t23` 的材料、采集和评分独立封存。进程异常或成本停止后保留剩余未执行量，不用同目录覆盖重跑。

#### 429 中断后的续跑（2026-10-25）

原批次已结束：Netflix task2 在第 21 轮返回未决工具执行限制；task4 在第 12 轮遇到 429，后续 21 项也在首轮遇到相同拒绝。用户推测五小时额度已用尽并授权继续；五小时原因尚未证实，恢复是否成立由下一次正式请求判断，不另发合成探针。

本次操作脚本为 `.tmp/lr25/resume.py`，进度及新归档使用同一短根，原 `.tmp/ls25/` 只读。先逐字核对生产及原评测源码、配置、材料 seal 和原题；不改生产代码。task4 从第 12 轮继续，复制原主体、对话、完整 Journal、文件引用及原 Python 许可，保留前 11 轮实际消息、先前消费和失败。原第 12 轮的 run 已超过一小时截止，使用正式入口创建新 run 重新请求同一道原题；不改旧截止、不替换原许可、不清空任务消费。新分段报告记录 `preceding_source_turns=11`，只评分新增回答，旧评分原样保留。

其余 21 项复用封存的官方材料，因原批没有回答或执行结果，以新采集身份从首轮开始；原 429、未知用量及失败身份仍作为本次来源记录。若再次收到 429，当前原子调用安全结束后暂停整批，不继续提交后续任务，也不循环重采样；服务是否恢复先消费 task4 的实际第 12 轮请求验证。原每项 60M、每轮 10M/40 次决策、原模型及官方 Judge 条件保持。

Netflix task2 的 20 轮已交付结果和未决执行单独保留；本次可续队列为 22 项、696 轮，另 14 轮当时属于该阻塞。原全体 741 轮及未完成 710 轮的分母保持。启动前验证新操作脚本的源码和路径、旧封存身份及 HTTP 输入；续跑结果不改写原批次成绩。

#### Netflix task2 的单次事故恢复（2026-10-26）

用户进一步授权恢复 task2，按 [ADR 0046](../adr/0046-sealed-pre-dispatch-incident-recovery.md)在新 `.tmp/lr2/` 副本中处理原第 21 轮的确证未派发失败。操作适配器仅对绑定的单一 Command 提供恢复事实，经现有执行服务和 Journal 公共写入口收敛；原 `.tmp/ls25/t01`、生产代码、冻结 Command、原许可及前 20 轮不改写。完成事故核对后，新 run 使用实际原消息从第 21 轮进入正式 HTTP，并按原 60M 总额度扣除已知消费后继续至第 34 轮；新增 14 轮单独采集和评分，原 3/20 成绩保持。真实同名容器非 404、封存或绑定不符、许可失效、新未决状态及 429 均停止，不重跑到成功。

用例与预算由[研究 Spec §9](../optimization/to_verify/knowledge-decision-delivery.md#9-longds-长程数据分析设计)拥有，结果契约为 `LONGDS_OUTCOME`。准备命令不调用模型、不执行分析程序；来源目录为已核查的固定版本原件，输出目录必须尚不存在。

```powershell
.\.venv\Scripts\python.exe -B -X utf8 -m evals.product_baselines.run_longds prepare --source-directory .tmp/longds-design-20261023 --output .tmp/longds-implementation-20261023/materials
.\.venv\Scripts\python.exe -B -X utf8 -m evals.product_baselines.run_longds baseline --materials .tmp/longds-implementation-20261023/materials --output .tmp/longds-implementation-20261023/l1-baseline
```

基线须先配置真实模型、两条匹配的容量配置和既有本机评测数据库凭据；本次每 run 10M tokens、40 次主决策，其他参数按 Spec 固定。调用正式 `/api/artifacts/upload` 后，按顺序发送最多两轮完整中文请求至 `/api/conversation/turn`；只在实际 `answer` 后继续，不代答澄清或确认。参考答案不挂载。采集器复用现有只读 SDK／HTTP 观察及实际进程身份，保存源快照、原始请求、回答、Journal、用量和校验和；不提供解题代码。`report.json` 的 `not_scored` 仅记录流程，不能计作正确性或完整 36 轮通过。

独立 Python 能力 target 使用相同入口和新的输出目录；本次固定镜像如下。该目录若已经存在，保留原运行，不覆盖或以同名重跑。

```powershell
.\.venv\Scripts\python.exe -B -X utf8 -m evals.product_baselines.run_longds baseline --purpose target --user-turns 2 --materials .tmp/longds-implementation-20261023/materials --python-image-id sha256:510b3b843826cf0bb0684f73e33171ef96735856d2f6569c7a235a2426678755 --docker-endpoint npipe:////./pipe/dockerDesktopLinuxEngine --output .tmp/longds-implementation-20261023/l1-python-target
```

生成进程已停止且 seal 有效后，独立评分才读取实际 Final。Judge 资格与 2M 独立额度由 Spec 固定；下面复用已通过的同配置资格，不重复计资格样本或把评分回灌生成侧。

用户授权的无 claim／核验流程使用相同采集入口，运行前显式设置 `$env:PERSONAL_AGENT_ANSWER_RESULT = '{"writer":"direct","verification":"none"}'`，输出另取尚不存在的目录。本次目录为 `.tmp/answer-result-modules-20261023/l1-direct-flow`，该配置自动记录为 `unverified_flow_capture`、`release_eligible=false`；不得计作完整 Product E2E。默认配置对照不设置该变量；同对话与同 run 不能换装配，后续 claim 消融使用独立对话并固定 verification，实际确认 claim 机制已被消费。预算与判据由[Spec §9.9](../optimization/to_verify/knowledge-decision-delivery.md#99-可替换回答模块与无核验流程验证)拥有。

```powershell
.\.venv\Scripts\python.exe -B -X utf8 -m evals.product_baselines.longds_judge score --judge-root .tmp/longds-implementation-20261023/judge --source-directory .tmp/longds-design-20261023 --materials .tmp/longds-implementation-20261023/materials --capture .tmp/longds-implementation-20261023/l1-python-target --name l1-python-target
```

本次额度、未知消费和真实 Python 执行阶段的局部诊断源码随 `.tmp/longds-implementation-20261023/` 独立结果封存；不以标准任务成功率报告它们，也不覆盖独占目录。权限／原件／执行恢复回放的模型和新增执行均为 0；声明的 Provider 响应交付丢失只作用于独立控制分支，正式生成轨迹保持原输入。

MiMo 的两轮实际配置、结果和后续预算见 [Spec §9.10](../optimization/to_verify/knowledge-decision-delivery.md#910-切回-mimo-的长任务验证)。新启动器读取当前 Settings 和既有凭据，不能复用显式指定 DeepSeek 的旧实验启动器；两轮独立身份已封存，禁止覆盖。完整任务须显式指定 `--purpose target --user-turns 36 --task-token-limit 60000000 --stop-after-checkpoint`，沿原固定镜像与新的输出目录启动；任务额度同时供许可、观察停止及归档使用，省略仍为原 20M，L1 拒绝改额度。只有第 17 轮真实完成并封存后才按该开关退出。

恢复使用 `--recovery-checkpoint <完整L2归档>/checkpoint-17`，同时指定 `--purpose target --user-turns 36` 及新的 `--output`，沿用原模型配置。恢复继承原授权文件、原额度及已发生消费，显式传入不同额度在新增调用前拒绝；不能提供新 `--python-image-id`、`--docker-endpoint` 或重复指定 `--stop-after-checkpoint`。检查点须有完整 seal、相同源码／配置、原第 17 轮实际消息及未过期许可。本次以同轨迹后半段覆盖 L3，不再重复一次第 18—36 轮；当前尚无真实检查点或完整成绩，CLI 可加载不代表 L3 通过。

MiniMax low 的新完整流程按 [Spec §9.11](../optimization/to_verify/knowledge-decision-delivery.md#911-minimax-low-的完整流程验证)执行，启动器为 `.tmp/minimax-longds-e2e-20261023/full-launch.py`，收尾为同目录 `complete-longds.py`，后者绑定启动身份中的真实 Python PID。先用 `scoring_admission.py` 对既有成功／503 两份完整采集做零模型准入回放：只把实际 HTTP 成功且 `disposition=answer` 的原回答送入既有评分器，失败正文保留未评分，消费未知则停止评分。模型、端点和 thinking 从当前配置读取，原 MiMo 启动器仅保留历史身份，不用于新任务。

2026-10-24用户调为 medium 后，完整流程使用新身份 `.tmp/minimax-medium-longds-e2e-20261024/`，按 [Spec §9.12](../optimization/to_verify/knowledge-decision-delivery.md#912-minimax-medium-的完整36轮验证)执行。当前配置和实际 SDK 已核对；新 full-launch.py 仍调用正式 baseline 完成1—17及原许可恢复18—36，新 complete-longds.py 绑定该次实际PID后才收尾。旧 low 启动器及归档不修改，新的观察器删除已退役 Args.program_ref 统计读取；评分仍由原官方 Judge 和共享预算拥有，不给生成侧反馈。

用户取消用量未知停止线后的完整运行由 [Spec §9.13](../optimization/to_verify/knowledge-decision-delivery.md#913-用量未知不再单独停止并继续完整验证)拥有，独立目录为 `.tmp/usage-nonblocking-longds-20261024/`。执行 `python -B -X utf8 .tmp/usage-nonblocking-longds-20261024/full-launch.py`；收尾脚本为同目录 `complete-longds.py --launcher-pid <该次真实PID>`。未知用量继续记录，不阻止生成、检查点、恢复或合法答案评分；额度阈值按已知消费执行，未决执行及原授权／截止保持。上方 low／medium 原档案的未知停止线只解释其历史运行，不用于本次启动。

**当前 E2E 数量以测试收集与 `evidence_catalog.py` 为准；已撤回的 Investigation Project 及其 scripted conformance 不再属于当前执行矩阵。**

## 模型 HTTP 诊断的真实阶段回放

MiMo 工具流式接入使用[独立传输规格](../optimization/model-provider-transport.md#2026-10-23-mimo-工具流式接入规格)。局部入口 `python -m evals.product_baselines.mimo_tool_stream_replay --output <尚不存在的目录>` 读取固定历史完整 SDK 阶段，只以本机 SSE 服务替代外部响应，不调用真实模型或工具。新完整轨迹由 `.tmp/mimo-tool-stream-20261023/full-launch.py` 调用上方同一 LongDS 正式入口，收尾脚本 `complete-longds.py` 等待真实生成退出、校验各段及恢复身份，再以新 Judge 名称评分；原失败轨迹和一次未知消费保持。

[传输诊断规格](../optimization/to_verify/model-provider-diagnostics.md#本轮验收与实施顺序)固定三例及真实输入，执行入口如下；`before-source` 指向修改前完整源码快照，`capture` 指向原 LongDS 归档的 SDK 目录，输出目录必须尚不存在。

```powershell
.\.venv\Scripts\python.exe -m evals.product_baselines.model_transport_diagnostics --capture .tmp/research-mimo-longds-20261023/l2-prefix-17/sdk --before-source .tmp/mimo-transport-diagnostics-20261023/before/src --output .tmp/mimo-transport-diagnostics-20261023/offline-v5
```

入口只把外部 HTTP 服务替换为回环故障／正常响应服务，对两组子进程设置相同 `NO_PROXY=127.0.0.1`；生产配置保持。该 Offline Eval 不启动模型生成、工具执行或原任务恢复，不覆盖预算准入、真实 MiMo 根因和完整产品结果；原档案及已经存在的输出目录不得覆盖。

## 新运行的归档位置

新运行按 [EVM 归档规则](../../evals/AGENTS.md#5-比较身份与归档)显式选择独立的 `.tmp/` 根目录。以下执行示例先在同一 PowerShell 会话设置变量；每次独立样本组重新生成根目录，子进程继承相同配置：

```powershell
$evaluationEvidenceRoot = ".tmp/evaluation-" + (Get-Date -Format "yyyyMMdd-HHmmss-fff")
$env:PERSONAL_AGENT_E2E_TRACE_DIR = "$evaluationEvidenceRoot/e2e"
$env:PERSONAL_AGENT_PRODUCT_EVIDENCE_DIR = "$evaluationEvidenceRoot/product"
```

读取历史证据时使用其原真实目录，不移动或改写旧归档。需要共享或发布的证据另封存到可访问位置；本节路径设置不改变证据类别、输入、评分或发布门槛。

## 参数恢复的完整真实阶段回放

2026-10-22 的一次性脚手架与封存规则由[主循环Spec](../optimization/to_verify/conversation-loop-boundaries.md#2026-10-22-必填参数恢复候选)拥有；来源是当前正式E1的实际SDK，而非重造短输入。实际命令如下，归档身份已关闭，不再执行或覆盖：

```powershell
.\.venv\Scripts\python.exe -B -X utf8 .tmp/action-parameter-repair-20261022/replay.py baseline
.\.venv\Scripts\python.exe -B -X utf8 .tmp/action-parameter-repair-20261022/replay.py candidate
.\.venv\Scripts\python.exe -B -X utf8 .tmp/action-parameter-repair-20261022/run_group.py prepare
.\.venv\Scripts\python.exe -B -X utf8 .tmp/action-parameter-repair-20261022/run_group.py run
.\.venv\Scripts\python.exe -B -X utf8 .tmp/action-parameter-repair-20261022/replay.py retained
```

prepare与replay零HTTP；run保留源模型／完整Context和Schema、零重试／工具执行，使用当前受信DeepSeek凭据且不落密钥。SDK调用后按生产解析器和decoder检查提议，不通过脚本执行或修订参数；原生调用／结果历史没有被重排。结果须逐份审读，Schema接受不代表执行或用户完成。本组按首个候选失败早停，未执行项与费用由[当前盘点](02-current-case-inventory.md#2026-10-22-参数恢复的局部对照失败)记录；后续任何候选须另有准入和独立身份。

## Python结果分析的局部Offline回放

当前Agent能力验收按[范围修正](../optimization/to_verify/knowledge-decision-delivery.md#85-agent能力范围收回与删除计划)不再打包或下载：正式采集只POST自然任务、GET当前Trace并封存SDK／执行／费用及适用安全观察；完成审计核对实际SubmittedFinal和Final，不要求report文件、manifest、ZIP、downloads/index或外部CLI。旧文件版封存按原代码身份读取，历史资格／交付命令不能作为当前能力门槛。

本次确定性完成回放命令为`.venv/Scripts/python.exe -B -X utf8 .tmp/agent-capability-scope-20261022/replay.py`，实际两份完整历史阶段输入已执行并关闭；不在独占目录重跑。没有新增付费E1或语义组，原下载429、SQL审计缺口及旧退出码保留。旧capture按新范围单列审计，不能覆盖旧封存结果。


用户随后授权将新接口接回生产并继续验证，执行前计划由[Spec §3.3](../optimization/to_verify/python-data-analysis-tool.md#33-接回生产链路并继续正式流程验证)拥有，新身份`.tmp/python-schema-production-20261022/`。正式准备、F1及initial_closure分别沿该目录的`launcher.py prepare`、`scope`、`verify`、`run`执行；运行已结束，原下载429及SQL关闭缺口保留。随后`continue_downloads.py`在独立目录通过认证GET取得同一110资源并按Retry-After等待，`audit.py`分别记录原采集与续接证据；旧64位评分审计失败后，经真实排名诊断修正正式delivery auditor，并单独生成`ranking-audit-binary32.json`。首次`launcher.py reproduce`长路径失败后，`reproduce_short.py`在`.tmp/py-prod-repro-20261022/`消费同一下载清单，以原生产CLI完成7项复现。当前原组已关闭，不可重跑或覆盖独占输出；后续需要新身份。使用本地`.venv`解释器，凭据只从既有受信配置读取、不打印；不强制Python或自然压缩，不因合法工具选择撤回接口。结果与完整流程尚缺的SQL审计关闭由[评测盘点](02-current-case-inventory.md#2026-10-22-python新接口接回生产与正式续验)拥有。

2026-10-22的Schema候选实现与10+10阶段回放已关闭于`.tmp/python-schema-implementation-20261022/`；工具选择自由，Python覆盖不足，候选已撤回。原运行使用该目录的`offline.py prepare/execute`、`post_execution.py`及逐次`model_group.py next`，均须绑定归档代码身份；不可在当前旧契约下重跑已关闭目录或解析其新接受载荷。判据、费用及后续验收边界见[Spec §3.2](../optimization/to_verify/python-data-analysis-tool.md#32-本次实施与局部验收计划)，实际结果见[评测盘点](02-current-case-inventory.md#2026-10-22-python-schema候选实施与覆盖不足)。下面仍是此前自主分析旅程的入口，不能用它补本轮覆盖次数。

[唯一工具Spec](../optimization/to_verify/python-data-analysis-tool.md#7-验收规格与费用边界)固定真实0056报告阶段、完整原任务与材料、10baseline＋10candidate及停止线。该回放经AgentService／AgentRuntime连续消费真实模型与工具输出；只将历史截止映射到当前，证据身份仍为Offline Eval，不计作完整研究或长任务E2E。

```powershell
.\.venv\Scripts\python.exe -X utf8 -m evals.provider_diagnostics.python_result_analysis --prepare --group-dir .tmp/python-analysis-20261021/group-1
.\.venv\Scripts\python.exe -X utf8 -m evals.provider_diagnostics.python_result_analysis --validate-inputs .tmp/python-analysis-20261021/input-validation-2 --group-dir .tmp/python-analysis-20261021/group-1
.\.venv\Scripts\python.exe -X utf8 -m evals.provider_diagnostics.python_result_analysis --run-next --group-dir .tmp/python-analysis-20261021/group-1 --input-validation .tmp/python-analysis-20261021/input-validation-2
.\.venv\Scripts\python.exe -X utf8 -m evals.provider_diagnostics.python_result_analysis --record-review .tmp/python-analysis-20261021/group-1/B1.review.input.json --group-dir .tmp/python-analysis-20261021/group-1
```

先在当前进程绑定与源profile一致的受信端点及凭据，禁止dotenv覆盖；预检不打印或保存密钥。prepare零模型封存新组；validate-inputs经原Web Composition Root生成两个arm的真实首SDK并在HTTP前截断，只有声明变量可不同；示例group-1已用于本次归档，不能覆盖或重复准备。run-next一次只执行下一原子样本，必须独立审读全部实际成稿并登记绑定结果摘要的五项关系后才允许继续。程序／配置不能被文件名或关键词自动算成报告。每支最多4次物理发送，整组80次／20M已知tokens／2小时；逐次预留完整SDK输入、协议和最大输出，未知用量、费用不足或首次明确candidate语义失败停止全组，不补样。

零模型工具边界入口为 `python -m evals.provider_diagnostics.python_execution_boundary --help`；它使用真实原件、原FileJournal／Artifact／ToolExecutor及既有Docker，不替代上述自主模型回放。实际样本、代码身份、费用和限制由[当前评测盘点](02-current-case-inventory.md)拥有。

## 检索实验研究能力准入

`RETRIEVAL-EXPERIMENT-001`（E1）与 `RETRIEVAL-EXPERIMENT-PROGRAM-001`（P1）的阶段 0 正式入口及预算由[唯一 Spec](../optimization/to_verify/knowledge-decision-delivery.md#72-完整落地-implementation-plan)拥有。节点采用真实 Web 子进程、生产模型与 `POST /api/conversation/turn`，原件只经 Artifact owner 准备，不摄入知识，也不向模型提供预生成排名、候选代码或 test 标注。当前独立准入节点不加入默认 release 分母。

先收集和零模型材料预检：

```powershell
.\.venv\Scripts\python.exe -m pytest --collect-only -q evals/product_baselines/test_retrieval_experiment_001.py
.\.venv\Scripts\python.exe -m evals.product_baselines.retrieval_baseline --output-root .tmp/research-capability-20261020/material-preflight-new
```

本轮真实基线按 E1 后 P1 的顺序各一条，分别选择尚不存在的输出根；仅在 E1 是合格产品失败且未越预声明成本时继续 P1。wrapper 在当前已核实环境安全绑定既有 16432 评测数据库，进程内传递配置、不打印凭据；换环境须先核对实际连接，不能照搬端口：

```powershell
.\.venv\Scripts\python.exe -X utf8 -m evals.product_baselines.run_retrieval_baseline --case e1 --output-root .tmp/research-capability-20261020/e1-baseline-new
.\.venv\Scripts\python.exe -X utf8 -m evals.product_baselines.run_retrieval_baseline --case p1 --output-root .tmp/research-capability-20261020/p1-baseline-new
```

研究采集器 `run_retrieval_acceptance` 及评分资格入口保留 Settings 的实际 timeout/max_retries，并通过原子进程环境传入。任务总时间与单请求超时分开；新正式准备必须显式给出 `--run-timeout-seconds` 和 `--max-execution-seconds`，同一部署供Runtime、环境附件和采集监督读取。下一次1小时验收两项均设3600；轮数／工具／委派／tokens使用既有 `PERSONAL_AGENT_INTERACTION_MAX_MODEL_TURNS`、`PERSONAL_AGENT_INTERACTION_MAX_TOOL_CALLS`、`PERSONAL_AGENT_INTERACTION_MAX_AGENT_CALLS`、`PERSONAL_AGENT_INTERACTION_MAX_TOTAL_TOKENS`，此前零模型预算切片使用64／256／4／2000000；用户在调研后已选下一例累计20000000 tokens，其他为64／256／4；仅用于独立准备身份，旧配置原件保持，见同节的累计Token调研。现有dotenv会覆盖外层环境变量；需要覆盖时，先加载既有配置，再设置本例值并使用已有 `PYTHON_DOTENV_DISABLED=true` 进入入口，实际归档一致后才运行。新配置形成独立准备身份，具体实施与验证状态见[Spec预算切片](../optimization/to_verify/knowledge-decision-delivery.md#长任务预算与诊断范围)。旧T0／v1／v2的120秒评测profile和旧900秒运行保留原配置身份，不与新身份混算。structured／openai的实际单次超时由每次 `configuration.json` 拥有，不能将历史480／30当成任务总时限。

正式采集监督绑定首份真实Journal截止，启动健康检查和Journal出现前的入口等待各最多30秒，收尾最多30秒，不增加模型额度；停止及终态核对实际Web解释器和包装进程，HTTP超时本身不算停止。旧T0节点仍沿原900秒监督身份。原始用户结果缺交付时保留pytest失败；环境／模型异常或未知生成产物不能当能力准入。初始材料、实际SDK输入／输出、完整源码身份、独立归档及用户结果分开保存；基线缺项检查不能接受完整target，后续完整评分资格及复算／复现仍按Spec执行。

研究采集器消费 Settings 已有的 `STRUCTURED_MODEL_CAPACITY`、`OPENAI_MODEL_CAPACITY` JSON 配置，分别绑定该路径的实际 model／provider_host。任一路径显式配置时，两条都须提供有效 profile；缺一或身份不符会在准备／业务连接前拒绝。两条都未配置时保留原已核 Flash 缺省。更换模型须先核对公开规格、实际 endpoint 可用性及完整生效配置，不沿用其他模型的容量或评分资格；dotenv 的实际加载结果必须进入每次配置原件，不能仅以外层环境变量推定生效。新 Pro 准备的依据及准入边界见[唯一 Spec](../optimization/to_verify/knowledge-decision-delivery.md#新模型配置的正式评测准备)。

当前设计先完成[初步闭环](../optimization/to_verify/knowledge-decision-delivery.md#11-当前先完成的闭环)，claim／语义 verifier 及新评分资格后置。`initial_closure`、SubmittedFinal／Manifest v2 绑定已由新 DeepSeek E1 到达真实交付、下载、复算及复现；独立审读发现错例分析错误，完整用户验收未通过。初步机械结果及语义审读单独记录，不使用下面的 target 准入冒充已取得完整语义资格；首次发布故障 F3 仍未覆盖。

2026-10-22 的当前版本 E1 已按[§8.3流程计划](../optimization/to_verify/knowledge-decision-delivery.md#83-当前版本完整流程-e2e2026-10-22)执行一次并关闭：模型后续Python调用重复漏必填inputs，流程未到冻结、test、清单v3及下载复现；语义未评分，详见[本轮结果](02-current-case-inventory.md#2026-10-22-当前版本完整流程-e2e-失败)。归档 `.tmp/research-e2e-flow-20261022/` 已使用，不得重跑。F1启动器已对齐服务端进程记录参数并复用ActualWebProcess监督实际解释器，限定授权拒绝复验通过，原失败保持。

前一次 Pro E1 的 480 秒截止与新 DeepSeek E1 的实际结果均保留于[评测盘点](02-current-case-inventory.md#2026-10-20-检索实验研究能力准入)。新归档汇总只绑定 auditor 实际消费的来源：正式 GET 已绑定 Trace 时，即使提供备用 `--trace-seal` 也不将它误作消费原件；只有正式 GET 未取回时才消费该 seal。旧封存与采集源码身份保持，不因 reader 修正重跑模型。

后置的完整研究采集 `--phase target` 仍必须提供真实完成的 `--qualification <目录>` 及 `--qualification-review <独立准确性审读原件>`；入口会在任何业务连接前只读核对当前 grader identity、18 次判断、原请求／响应／引用、费用与逐关系审读，不接受单个分类达标标签。来源审读如实区分人和独立 agent；审读与评分原记录分别封存，Admission 绑定两者摘要。资格准备不接收这两个参数。只读核对已完成归档：

```powershell
.\.venv\Scripts\python.exe -B -X utf8 -m evals.product_baselines.run_retrieval_grader_qualification verify --qualification <真实资格归档目录> --accuracy-review <独立准确性审读原件>
```

该命令不发模型请求；当前尚无合格完整资格归档。四个真实 CLI 拒绝已验证，接受分支待真实组，不能构造假通过档替代。

资格材料构造入口为 `python -m evals.product_baselines.retrieval_qualification_materials --selection <独立审读选择表> --output <新目录>`。输入必须绑定实际已结束的 E1／P1 preparation、正式完整下载、原排名审计和干净 CLI 复现；缺材料会拒绝，不人工补稿。构造成功后才用原 qualification `collect`／`run`；来源和准确性审读的契约由[研究 Spec §6.1](../optimization/to_verify/knowledge-decision-delivery.md#61-资格材料与审读的实现契约)拥有，成功路径仍待真实材料。

已停止采集的机械审计入口为 `python -m evals.product_baselines.retrieval_capture_audit --preparation <preparation.json> --capture <capture-result.json> --trace <最终Journal.json> --output <新报告.json>`；正式 GET 未取得 Trace 时另须 `--trace-seal <同run原seal.json>`，不能以未绑定的后读 Journal 补原 HTTP。只输出实际物理费用、终态及 `missing／present_unscored`，不代替语义、资格、独立复算／复现或产品 passed。

缺交付汇总入口为 `python -m evals.product_baselines.retrieval_acceptance_result --preparation <preparation.json> --capture <capture-result.json> --trace <最终Journal.json> --output <新报告.json>`，同样按需提供 `--trace-seal`。它复用机械审计，只有绑定 Journal 明确缺 answer Final 或必要交付角色时才报告用户结果失败，保留原阶段、`not_scored` 与 known／unknown 费用；仅入口／下载取证不足不能判业务失败。完整交付会明确拒绝进入本路径，完整 target 的评分与全证据汇总仍待准入；不能把该报告当产品通过。v6／v7 两份真实归档回放与跨身份拒绝已验证，均未调用模型。

知识快照独立入口为 `python -m evals.product_baselines.retrieval_knowledge_snapshot --preparation <preparation.json> --output <新快照.json>`，仅作当前主体真实只读取证。正式 target runner 已在进程开始前／实际停止后装配 before／after，含失败原件一起封存；资格门禁不满足时不会读取数据库或启动模型。独立命令不能补造旧 run 的 before，知识零写入仍须结合完整写入口审计，详见[同一任务证据汇总](../optimization/to_verify/knowledge-decision-delivery.md#62-同一任务的最终证据汇总)。

SQL 观察审计入口为 `python -m evals.product_baselines.retrieval_knowledge_write_audit --directory <同轮knowledge-write-audit目录> --output <新审计.json>`。target 的专用 Web 进程透明记录原同步 SQL，collector 在原认证下关闭观察后停止进程；安装、日志和关闭回执随 capture 封存。CLI 只读原件，未知及关闭后日志变化不能计零写入；完整结论还须绑定同轮 before／after、源码覆盖、主体和实际停止。真实 Web／只读接口的零模型诊断已通过，不能替代完整 target。

F1 初始 Artifact 权限反事实采用独立新 E1 preparation，配置／镜像沿同一准备命令，正式入口为：

```powershell
.\.venv\Scripts\python.exe -B -X utf8 -m evals.product_baselines.retrieval_scope_counterfact --preparation <独立准备目录>/preparation.json --output <同一准备目录>/scope
```

输出必须尚不存在，不能复用已执行 E1／P1；零模型／零实验及 60 秒 Web 进程监督由 Spec 拥有。正式节点 `evals/e2e_quality/test_retrieval_scope_boundary.py::test_retrieval_scope_boundary` 复用同一入口；须显式设置 `PERSONAL_AGENT_RETRIEVAL_SCOPE_PREPARATION` 和 `PERSONAL_AGENT_RETRIEVAL_SCOPE_OUTPUT` 后执行，否则跳过。分类是 HTTP boundary_evaluation、real_model_required=false，不进产品 release 分母。本轮实际执行该 CLI；节点完成 collect-only，未把它记成一次额外执行。

F2 原生 start 响应中断复用研究采集 CLI。按 Spec 单独准入后，用同一 `prepare` 命令的 `--case e1 --fault start_response_interrupt` 建新准备目录，再执行：

```powershell
.\.venv\Scripts\python.exe -B -X utf8 -m evals.product_baselines.run_retrieval_acceptance run --preparation <F2独立准备目录>/preparation.json --phase fault_boundary
```

故障与普通准备不可混用。`fault_boundary/fault-configuration.json` 绑定实际部署，`fault-control/transport-observations.json` 保存真实 create／start／响应／查询及清理观察，SDK、HTTP、Journal 和终态沿原采集归档。canonical catalog 以 `RETRIEVAL-EXPERIMENT-START-RESPONSE-001` 登记此 CLI；它使用真实模型及进程内故障控制，分类 boundary_evaluation。真实到达、安全结论与完整交付分别报告，不凭注入次数计成功，不计产品发布分子。

## claim 指标持续评估

指标定义与收益判据固定在[claim 指标规格](../ablation/claim-verifier.md#21-具体评估指标)，历史基线由[冻结计划](../ablation/claim-verifier-baseline.plan.json)标识。下列命令只读重算已裁判的完整阶段归档，零模型调用，不收集或运行测试：

```powershell
$claimMetricsOutput = ".tmp/claim-metrics-" + (Get-Date -Format "yyyyMMdd-HHmmss-fff")
.\.venv\Scripts\python.exe -X utf8 -m evals.e2e_quality.claim_ablation_metrics `
  --plan docs/ablation/claim-verifier-baseline.plan.json `
  --output-root $claimMetricsOutput
```

输出根必须尚不存在。每次归档保存源汇总、计划、报告、重算源码及校验和；源 SHA-256、完整配对、标签覆盖或任务映射不符时拒绝出具报告。该入口目前自动统计预设关系、任务均值与核验成本，缺少闭环或整例证据的指标保持未测。

后续新模型、Prompt、Context 或修订链评估使用新冻结计划与真实产物，按指标规格连续消费实际输出；本命令不负责采样或生成语义裁判。旧结果不覆盖，跨评测身份不直接合并，阶段重算不计发布通过。

## 收集当前矩阵

```powershell
uv run pytest evals/e2e_quality --collect-only -q --e2e-scope=release
uv run pytest evals/e2e_quality --collect-only -q --e2e-scope=diagnostic
```

收集结果随代码版本变化；分类、数量和已有执行结果统一见[当前用例盘点](02-current-case-inventory.md)。发布时使用目标版本的实际收集结果。

## 执行机器 release selection

日常修改先用影响路由决定最小 live selection：

```powershell
uv run python scripts/e2e_impact.py
```

当变更必须覆盖完整矩阵时，路由同时输出两个用途不同的命令：

- `iteration command` 带 `-x`，仍在 collection 阶段检查完整 release catalog，但首个失败后停止；当本地存在 checksum 有效且包含全部 release case 的历史 archive 时，命令按最近一次实测 duration 从短到长列出全部 node，并打印排序证据坐标；没有完整历史时回退到目录收集顺序。排序只改变迭代反馈时间，不改变 case、预算或断言，也不能作为发布证据；
- `release evidence command` 不带 `-x`，执行并记录全部 case outcome，保持下面的完整发布证据契约。

`--quiet` 为已有调用方保持原行为：完整矩阵路由只输出不带 `-x` 的 release evidence command。

```powershell
$env:PERSONAL_AGENT_REQUIRE_LIVE_E2E = "true"
$env:PERSONAL_AGENT_E2E_TRACE_DIR = "$evaluationEvidenceRoot/e2e"
uv run pytest evals/e2e_quality --e2e-scope=release `
  --e2e-require-complete-matrix -q -s
```

该命令需要真实 PostgreSQL、真实 structured model，并按 case profile 需要 Web Search、Firecrawl、GitHub MCP、Notion MCP 或 GPT Researcher A2A。skip 在强制 live 模式下会转为失败。

共享 HTTP E2E fixture 默认连接本地 `15432` 的 `personal_agent_test` 数据库；主机端口不可用时，可显式设置 `PERSONAL_AGENT_E2E_POSTGRES_URL` 为真实隔离评测数据库的连接串。依赖检查与正式 HTTP 子进程消费同一地址，不使用模型或数据库替身。配置差异须进入本次运行身份；只覆盖该共享 fixture 的用例，其他支持用例的独立数据库配置不据此外推。

## 执行 diagnostic selection

### Runtime 策略审计隔离的定向验证

`AUD-001` 拥有独立数据库基础设施，不调用共享 `personal_agent_test` 清理。先将 `PERSONAL_AGENT_E2E_POSTGRES_URL` 指向可创建隔离库的真实本机 PostgreSQL，并显式设置上文两个归档目录；每次只创建和删除本轮 `pa_audit_` 随机库。模型、预算与成本预声明按[唯一规格](../optimization/to_verify/runtime-policy-audit-isolation.md)，不得为文档或静态修改启动模型。

```powershell
.\.venv\Scripts\python.exe -m pytest evals/e2e_quality/test_policy_audit_isolation.py --collect-only -q
.\.venv\Scripts\python.exe -m pytest evals/e2e_quality/test_policy_audit_isolation.py -q -s
```

`AUD-001-REPLAY` 只消费 checksum 有效的正式 `AUD-001` baseline，并核对源 Journal 与该归档实际 owner HTTP Trace 相等。它恢复完整真实读取输入，经同一双应用 HTTP 进程验证 scope 与审计，零模型，属于 supporting boundary evaluation：

```powershell
.\.venv\Scripts\python.exe -m evals.e2e_quality.policy_audit_replay `
  --source-archive <AUD-001-baseline-run-dir> `
  --output-root "$evaluationEvidenceRoot/policy-audit-replay"
```

原始完整用户结果和阶段回放分别保存，不用回放替代产品通过；当前真实结果见[用例盘点](02-current-case-inventory.md#2026-10-16-runtime-策略审计隔离)。

```powershell
uv run pytest evals/e2e_quality --e2e-scope=diagnostic -q -s
```

该 selection 同时包含三种不同成本和语义：

- 真实外部 Provider profile：`E16/E18/E19/E21`；
- 真实模型 + frozen provider 的 HTTP conformance：`CTX-001/GOV-001/RUN-001`；
- 已撤回机制的 `LT` scripted Investigation 用例已删除；需要解释旧结论时只读取 checksum 有效的历史归档，不把它们作为当前测试矩阵。

`diagnostic` 不是一个同质测试层级。

## 执行横切验证套件

横切套件不创建第二套 E2E。`validation_catalog.py` 只引用 canonical catalog 中的既有节点，并为 Tool Calling、MCP dispatch、A2A Artifact 返回或窄范围研究路由预先声明关键检查点。同一节点可以进入多个套件；原始 pytest 结果、Product E2E 结果和发布门禁判断保持不变。

先列出套件节点并完成 collect-only、impact routing 与成本估算：

```powershell
$nodes = uv run python -m evals.e2e_quality.cross_cutting_validation `
  --suite tool_calling_protocol --list-nodeids
uv run pytest $nodes --collect-only -q
```

需要新 live 证据时，把节点放在同一次 pytest run 中，整例失败仍封存供关键检查点读取的 Trace。迭代可按 [EVM 执行效率](../../evals/AGENTS.md#7-e2e-执行效率是评测设计门禁)定向或 fail-fast，但未执行节点不计通过；完整套件声明须有全部节点的有效证据。预算与停止条件按任务预声明，默认耗时和 token 数是成本重审信号，数学早停仍按实际晋级约束执行。

```powershell
$env:PERSONAL_AGENT_REQUIRE_LIVE_E2E = "true"
$env:PERSONAL_AGENT_E2E_TRACE_DIR = "$evaluationEvidenceRoot/e2e/tool-calling-validation"
uv run pytest $nodes -q -s
```

pytest 可以因用户结果失败返回非零；随后对控制台打印的单一密封 run 目录生成横切报告：

```powershell
uv run python -m evals.e2e_quality.cross_cutting_validation `
  --suite tool_calling_protocol `
  --archive <sealed-run-dir>
```

报告中的 `pytest_outcome` 是整例事实，`capability_passed` 只表示该套件预先声明的关键 Runtime Mechanism 检查点。比如真实 MCP 返回 `401` 时，动作解码与 MCP dispatch 可以通过，而 Provider availability 和用户结果仍失败。缺失节点、重复节点、checksum 失效或 repository/evaluation identity 不一致都会使报告失败；禁止从不同 revision 或 cohort 挑选局部成功样本拼成套件通过。

## Archive 当前内容

每次 run 生成：

- `manifest.json`：commit、branch、dirty、Python/platform、MeasurementProfile；
- `*.trace.json`：case trace、test outcome、可选 CaseMeasurement；
- `summary.json`：pytest phase outcome 和 duration；
- `checksums.sha256`：全部 JSON 的完整性封印。

Archive 保存执行证据；Persona、需求/contract 来源、baseline 引用、用户结果和反事实由 catalog 的 typed `UserOutcomeContract` 拥有，release gate 必须同时取得该 contract 与同 revision archive。

## 独立变更准入证据

**`evals/product_baselines/` 不再写 `conv-*-baseline.json` 这类可覆盖文件；每次执行都生成独立且 checksum 封印的 archive。**

未显式覆盖输出根时，机器仍使用以下历史默认结构；新运行由本节变量覆盖写入根，不据此迁移旧归档：

```text
data/e2e_traces/product_baselines/<case-id>/<baseline|target>/<run-id>/
```

每条 trace 的 `product_evidence` 记录 case、role、证据类别、正式入口、交互模式、principal、用户输入 digest、初始事实 digest、配置 cohort 和 grader 版本；manifest 记录 commit、dirty 状态与 dirty digest。测试默认记录 `target`，需要在旧实现保存 baseline 时显式设置对应 role，例如：

```powershell
$env:PERSONAL_AGENT_CONV_001_EVIDENCE_ROLE = "baseline"
$env:PERSONAL_AGENT_CONV_001_EVIDENCE_SEED = "same-pair-seed"
.\.venv\Scripts\python.exe -m pytest -q -s `
  evals/product_baselines/test_conv_001_working_plan.py
```

target 必须使用相同 seed、用户输入、principal、正式入口、初始事实和 grader，再执行机械配对校验：

```powershell
.\.venv\Scripts\python.exe -m evals.product_baselines.evidence `
  <baseline-run-dir> <target-run-dir>
```

校验会拒绝 checksum 失效、role 错误、输入/身份/入口/交互模式/初始事实/grader 不一致，以及代码与配置身份完全相同的伪配对。旧的固定 `conv-*.json` 只能视为历史调试产物，不能作为 paired baseline/target 或发布证据。

### 逐样本晋级门槛与早停

高成本、重复采样的独立 target 可以使用 typed promotion spec。门禁在每个 `ProductEvidenceRecorder` archive 封存后计算；只在门槛已经数学上不可达到时提前拒绝，绝不因 partial target 暂时良好而提前通过。示例：

```powershell
.\.venv\Scripts\python.exe -m pytest -q -s `
  evals/product_baselines/test_interaction_intent_delegation_boundary_001.py `
  --product-promotion-spec `
  evals/promotion_specs/interaction_intent_target_001.json `
  --product-promotion-output `
  "$evaluationEvidenceRoot/promotion_gates/interaction-intent-target"
```

spec 固定 `case_id`、target role、stage、`expected_samples` 和 typed constraints。当前约束支持 boolean minimum/maximum count、numeric maximum sum、nearest-rank percentile 上限和 conditional rate 下限；`result_report_missing` 与 `test_failed` 是 recorder/pytest 产生的 boolean 执行事实。runner 还会机械拒绝：

- source archive checksum 无效；
- case/role、正式入口、交互模式、代码/config、grader 或 evidence class 不同；
- 同一 archive 被重复消费（相同自然输入的独立重复运行仍合法）；
- 指标缺失、类型错误或 conditional numerator 不蕴含 denominator；
- 测试全部结束但仍未收齐预声明样本。

该命令必须只选择一个专用 cohort，不与 `--maxfail` 组合。pytest 自身测试失败、internal error 和 usage error 不会被 promotion pass 覆盖。输出 archive 的 evidence class 是 `evaluation_promotion_decision_not_product_e2e`；它能证明 cohort 晋级决策，不能替代 baseline、单变量消融、完整真实 target 或 release gate。

历史 archive 可只读回放，不重新调用 Provider：

```powershell
.\.venv\Scripts\python.exe -m evals.e2e_quality.promotion_gate `
  evals/promotion_specs/interaction_intent_target_001.json `
  <target-archive-root> `
  --output-root "$evaluationEvidenceRoot/promotion_gates/replay"
```

默认一次性 `capture` 仍适用于没有 pre-capture 失败 baseline 的用例。已证明昂贵调用可能在结果报告形成前失败时，必须在调用前 enrollment，再在完整 grader report 形成后提交结果：

```python
product_evidence_recorder.enroll(nodeid=nodeid, identity=identity)
result = invoke_formal_entrypoint()
product_evidence_recorder.capture_report(build_grader_report(result))
```

enrollment 只冻结可在执行前知道的 case、role、正式入口、身份、输入、初始事实、config cohort 和 grader version，不得预填用户结果。call phase 异常会封存 `enrolled_without_result_report`；如果测试返回成功但没有 `capture_report`，pytest 会被强制置为 failed。fixture/setup 在 test body 前失败时仍没有合法场景 identity，不进入 cohort，禁止从 nodeid 或 stdout 补造。

当前已迁移的 Agent 委托 cohort 使用：

```powershell
.\.venv\Scripts\python.exe -m pytest -q -s `
  evals/product_baselines/test_agent_perf_delegate_001.py `
  --product-promotion-spec `
  evals/promotion_specs/agent_delegate_target_001.json `
  --product-promotion-output `
  "$evaluationEvidenceRoot/promotion_gates/agent-delegate-target"
```

该 spec 对 `result_report_missing` 和 `test_failed` 都要求零容忍，因此任一正式样本在调用阶段失败即可停止余下 cohort。它不改变产品 target 门槛，也不把执行失败解释成用户结果失败类型。

同一逐样本门禁也接受 `role=baseline`、`stage=failure_baseline`，用于昂贵 A0/baseline 在预声明结论已不可逆时停止后续样本。baseline 仍必须收齐其 spec 要求的样本才能判定 `passed`；门禁不会把提前观察到若干失败自动升级成完整 cohort，也不允许 baseline 与 target 混合。

受控本地 MCP 文件边界 baseline 的可执行入口为：

```powershell
$env:PERSONAL_AGENT_LOCAL_MCP_FILESYSTEM_SANDBOX_001_EVIDENCE_ROLE = "baseline"
.\.venv\Scripts\python.exe -m pytest -q `
  evals/product_baselines/test_local_mcp_filesystem_sandbox_001.py `
  --product-promotion-spec `
  evals/promotion_specs/local_mcp_filesystem_sandbox_baseline_001.json
```

该用例只创建 pytest 临时根中的随机 `ALLOWED`/`PRIVATE-CANARY`，不枚举或读取真实用户文件。2026-08-28 的正式 cohort 在第 `9/20` 项已无法达到预声明 `18/20` 最终答案泄露门槛，同时超过 `200,000` token 总预算；门禁拒绝并停止余下 11 项。`9/9` 模型可见越界读取只作为 Runtime 风险证据，不能替代产品失败 baseline 或触发沙箱实现。

长短 Conversation 历史配对 baseline 使用短控制优先、四类旅程交错的 40-item 顺序：

```powershell
$env:PERSONAL_AGENT_CONVERSATION_CONTEXT_PRESSURE_001_EVIDENCE_ROLE = "baseline"
$env:PERSONAL_AGENT_CONTEXT_PRESSURE_SEED = "<本次冻结 seed>"
.\.venv\Scripts\python.exe -m pytest -q `
  evals/product_baselines/test_conversation_context_pressure_001.py `
  --product-promotion-spec `
  evals/promotion_specs/conversation_context_pressure_baseline_001.json `
  --product-promotion-output "$evaluationEvidenceRoot/pg"
```

短控制最多允许一个失败；只有至少 `19/20` 短控制交付后才有资格执行 24 回合、48 条消息的长路径。2026-08-28 的交错正式运行在第 `7/40` 项出现第二个短控制失败，停止余下 33 项，未把短路径错误归因给 Context 增长。长输出根曾使 Windows 原子临时文件越过路径上限；`TraceArchive` 现使用同目录短临时 basename 后再原子替换，最终文件名、checksum 和 archive 契约不变。同一批密封证据已在原长输出根成功重放并写出完整门禁 archive。

普通 Conversation 研究 cohort 也使用逐样本归档。`19/20 delivered` 已不可达到时，门禁停止余下昂贵请求；单条通过不能提前晋级：

当前生产路径与 corrected-grader v3 的 baseline 入口为：

```powershell
$env:PERSONAL_AGENT_CONVERSATION_RESEARCH_DELIVERY_001_EVIDENCE_ROLE = "baseline"
$env:PERSONAL_AGENT_PRODUCT_EVIDENCE_DIR = `
  "$evaluationEvidenceRoot/product/conversation-research-v3-current"
.\.venv\Scripts\python.exe -m pytest -q -s `
  evals/product_baselines/test_conversation_research_delivery_001.py `
  --product-promotion-spec `
  evals/promotion_specs/conversation_research_baseline_003.json `
  --product-promotion-output `
  "$evaluationEvidenceRoot/promotion_gates/conversation-research-baseline-v3"
```

v3 把每个必需复合概念定义为预声明原子词集合，并要求原子词出现在同一句或同一标题；跨句散落的原子词负控制必须失败。旧 v2 archive 保持原 grader 结果，不能用 v3 离线重放事后晋级。2026-08-28 的新 baseline 在 `0/2 delivered` 后拒绝并停止 18 项，说明修正 grader 后当前生产失败仍成立。

只有获得已准入的生产候选后，才运行 target spec：

```powershell
.\.venv\Scripts\python.exe -m pytest -q -s `
  evals/product_baselines/test_conversation_research_delivery_001.py `
  --product-promotion-spec `
  evals/promotion_specs/conversation_research_target_002.json `
  --product-promotion-output `
  "$evaluationEvidenceRoot/promotion_gates/conversation-research-target-002"
```

当前 per-sample 入口收集 20 个 pytest item，每项只执行一次正式 HTTP 请求并形成一份 checksum archive。历史 v1 聚合 archive 保持只读，不能与新 cohort 合并。

显式验收要求的研究请求使用独立单样本入口，不加入上述 20-item promotion cohort，也不改变默认 release matrix。用例目的、独立评测器、成本和停止条件见[当前用例盘点](02-current-case-inventory.md#verifier-显式验收请求的单样本-baseline)。先只收集，再执行一次：

```powershell
$env:PERSONAL_AGENT_REQUIRE_LIVE_E2E = "true"
$env:PERSONAL_AGENT_CONVERSATION_RESEARCH_DELIVERY_001_EVIDENCE_ROLE = "baseline"
$env:PERSONAL_AGENT_PRODUCT_EVIDENCE_DIR = "$evaluationEvidenceRoot/product/research-review"
.\.venv\Scripts\python.exe -X utf8 -m pytest --collect-only -q `
  evals/product_baselines/test_conversation_research_review_001.py
.\.venv\Scripts\python.exe -X utf8 -m pytest -q -s `
  evals/product_baselines/test_conversation_research_review_001.py
```

该入口复用 `CONVERSATION-RESEARCH-DELIVERY-001` 的正式请求与归档协议，`scenario_id`、用户输入 digest 和数据集版本独立；不能与普通研究请求拼接为同输入配对。命名为 baseline 不代表一定复现产品错误，未复现时停止生产实施。

网页工具拆分候选继续使用这个节点，执行 target 时将 evidence role 设为 `target`，而非另建用户契约。
2026-09-04 的执行包装、源码快照和只读审计位于 `C:/pae/web-tools-split-20260904/`；包装脚本只启动原 pytest
和归档，不替换生产模型或注入执行事实。该次已超过单样本成本停止线，不重复执行包装脚本刷通过。
剩余对照与失败归因见[候选评测记录](02-current-case-inventory.md#网页发现与指定来源读取分离候选)。

后台持续能力边界已采用同样的逐样本结构，当前可执行入口只保留参数化 v2：

```powershell
.\.venv\Scripts\python.exe -m pytest -q -s `
  evals/product_baselines/test_background_continuation_limitation_001.py `
  --product-promotion-spec `
  evals/promotion_specs/background_continuation_target_002.json `
  --product-promotion-output `
  "$evaluationEvidenceRoot/promotion_gates/background-continuation-target-002"
```

该命令收集 20 个 pytest item，而不是在一个 item 内循环 20 次。每项只执行一个正式 HTTP 请求并生成一个 archive，因此零容忍失败可以在样本边界立即停止。历史 `grader-v1` 聚合 archive 只服务已经关闭的 ADR 0015 证据；不能与 `v2-per-sample` 合并计算稳定性或晋级结果。

### CONV-002 Provider 公平 cohort

复现历史 `CONV-002` 公平同配置样本组时，必须保持该组的应用 transport 为 `json_object`，并让评测在配置不符时直接失败。下面的命令只替换 Provider、base URL 和 model；API key 由当前 shell 的密钥注入，不写入命令或 archive。新的服务提供方评测应使用其已准入的能力配置档案，不能把本节的历史 transport 当作全局规则：

```powershell
$env:STRUCTURED_OUTPUT_TRANSPORT = "json_object"
$env:PERSONAL_AGENT_CONV_002_EXPECTED_TRANSPORT = "json_object"
$env:STRUCTURED_API_KEY = $env:MIMO_API_KEY
$env:STRUCTURED_BASE_URL = "https://api.xiaomimimo.com/v1"
$env:STRUCTURED_MODEL = "mimo-v2.5"
$env:PERSONAL_AGENT_WEB_SEARCH_PROVIDER = "anysearch"
$env:PERSONAL_AGENT_WEB_SEARCH_BASE_URL = "https://api.anysearch.com"

1..3 | ForEach-Object {
  $env:PERSONAL_AGENT_CONV_002_SAMPLE_ID = "mimo-json-object-$($_)"
  uv run pytest -q -s `
    evals/product_baselines/test_conv_002_agent_initiated_working_plan.py
}
```

`config_cohort` 会记录 model、structured provider host、output transport、extra body、预算、交互策略和 Web Search Provider；API key 不进入 digest。不同 transport（例如 `json_schema`）或不同 provider endpoint 的 archive 不得合并到这个 cohort。

### PLAN-STAB-001 重复稳定性 baseline

该用例固定来源比较、产品变更和事故分析三类自然请求，每类独立执行五次。它使用正式 Conversation HTTP、真实模型、
Postgres、AnySearch、服务重启和 checksum 归档；一次完整执行包含 15 个真实外部样本，成本较高，不属于普通回归套件：

```powershell
$env:PERSONAL_AGENT_PLAN_STAB_001_EVIDENCE_ROLE = "baseline"
$env:STRUCTURED_OUTPUT_TRANSPORT = "json_object"
$env:PERSONAL_AGENT_PLAN_STAB_EXPECTED_TRANSPORT = "json_object"
$env:PERSONAL_AGENT_WEB_SEARCH_PROVIDER = "anysearch"
$env:PERSONAL_AGENT_WEB_SEARCH_BASE_URL = "https://api.anysearch.com"

uv run pytest -q -s `
  evals/product_baselines/test_plan_stab_001_working_plan_stability.py
```

2026-08-20 的 `deepseek-v4-flash + json_object` 有效样本组为 `14/15 delivered` 和一次官方证据不足，没有 Plan 语义
失败。该组包含 105 次模型调用、75 个模型轮次、39 次工具调用和 999,389 个令牌，模型调用延迟 P95 为 99.95 秒。
预声明生产变更门槛是至少 `3/15` 次 Plan 语义失败且覆盖至少两类场景；本轮未达到，不能继续追加样本直到碰到阈值。
只有新的用户契约、独立线上问题或模型、服务提供方及交互契约变化时才能预声明新组，并归入新的对照身份。

### PLAN-REAL-001 真实恢复实验

该用例从正式 Conversation HTTP 取得官方资料，重启 Web 进程后以同一 conversation 增加展示要求，并检查旧 Plan、
官方来源、未完成义务、恢复阶段重复 Web Search 和最终用户结果。完整 cohort 为三类请求各五次：

```powershell
$env:STRUCTURED_OUTPUT_TRANSPORT = "json_object"
$env:PERSONAL_AGENT_PLAN_REAL_EXPECTED_TRANSPORT = "json_object"
$env:STRUCTURED_API_KEY = $env:MIMO_API_KEY
$env:STRUCTURED_BASE_URL = "https://api.xiaomimimo.com/v1"
$env:STRUCTURED_MODEL = "mimo-v2.5"
$env:PERSONAL_AGENT_WEB_SEARCH_PROVIDER = "anysearch"
$env:PERSONAL_AGENT_WEB_SEARCH_BASE_URL = "https://api.anysearch.com"

uv run pytest -q -s `
  evals/product_baselines/test_plan_real_001_real_provider_recovery.py
```

有效 v2 target-minus-mechanism archive 位于 `plan-real-001/baseline/*-36028-*`，结果为 `9/15 delivered`、
`3/15 semantic_recovery_failure`、`3/15 insufficient_official_evidence`；draft-step 绑定 target 位于
`plan-real-001/target/*-33492-*`，结果退化为 `6/15 delivered`、`5/15 semantic_recovery_failure`、
`2/15 insufficient_official_evidence`、`2/15 provider_failure`。两组恢复 Web Search 都为零。target 未通过预声明
`>=14/15 delivered`，候选已撤回；该命令现在只用于新 comparison identity 的复核，不得把已否决机制重新解释为优化。

### PLAN-REPLAN-001 义务修订 baseline

有效 v3 使用默认审阅模式，首轮必须真实取得官方资料并返回仍有 pending step 的 Plan；Web 重启后用户以自然业务语言
否定候选、撤回并新增结果或收紧验收，最终答案必须修订同一 Plan、完成新义务且不保留撤回结果：

```powershell
$env:PERSONAL_AGENT_PLAN_REPLAN_001_EVIDENCE_ROLE = "baseline"
$env:PERSONAL_AGENT_PLAN_REPLAN_EXPECTED_TRANSPORT = "json_object"
uv run pytest -q -s `
  evals/product_baselines/test_plan_replan_001_obligation_revision.py
```

2026-08-20 的有效样本组为 `10/15 delivered`、`4/15 stale_obligation_failure` 和
`1/15 semantic_pending_plan_missing`。四次可归因计划修订失败全部出现在撤回并新增结果场景；另一次失败伴随大型结果重读
与预算耗尽，归入结果物化和预算责任主体。可归因失败未覆盖第二类场景，故未达到 A1，不执行生产消融。该组包含 124 次
模型调用、95 个模型轮次、75 次工具调用和 1,205,254 个令牌，模型调用延迟 P95 为 100.29 秒。执行期间代码身份变化的
归档，以及历史零工具首轮和 `auto` 模式归档，只用于评测脚手架诊断，不能与有效样本合并。

### PLAN-COMP-001 完成真实性 baseline

该用例固定 Structured Outputs 事实正确性、MCP Tool result 的 exactly-once/完整交付、durable execution 的业务通知
零重复三个边界，每类五次。grader 直接检查最终回答是否给出用户要求的章节、官方 URL、否定性边界和无保留强结论：

```powershell
$env:PERSONAL_AGENT_PLAN_COMP_001_EVIDENCE_ROLE = "baseline"
$env:PERSONAL_AGENT_PLAN_COMP_EXPECTED_TRANSPORT = "json_object"
uv run pytest -q -s `
  evals/product_baselines/test_plan_comp_001_completion_truthfulness.py
```

2026-08-20 的有效样本组为 `14/15 honest_boundary` 和 `1/15 erroneous_success`。唯一错误成功出现在 Structured
Outputs 事实正确性场景，其余两类均为 `5/5 honest_boundary`，未达到跨两类 A1 门槛。该组包含 62 次模型调用、47 个
模型轮次、35 次工具调用和 515,546 个令牌，模型调用延迟 P95 为 44.75 秒。执行期间代码身份变化的归档与历史错误 grader
归档只作为诊断，不能参与门禁或结果合并。

## 研究答案评测器的前置校准

`RESEARCH-ANSWER-OUTCOME-001` 是真实模型 Offline Eval。共用评分器接收完整用户请求、实际答案及带来源的官方原文，输出引用由 Runtime 恢复，正式消费者只接受 passed。评分契约与版本由[评分固化记录](../optimization/completed/research-grader-qualification.md)拥有；各轮控制集、成本和资格结果见[当前登记](02-current-case-inventory.md#2026-10-02-独立评分的必要性与来源归属校准)，旧任务结果不迁入新任务资格。

运行前按受影响任务声明样本计划、模型配置、成本预算与停止线，设置独立归档根目录。控制集自带自然请求，预期标签不入模型请求；首个资格反例后停止新增样本。历史预算和耗用保留在原运行登记，新运行依据实际输入与历史成本重新声明。

```powershell
$env:PERSONAL_AGENT_RUN_RESEARCH_GRADER_CALIBRATION = "true"
$env:PERSONAL_AGENT_E2E_TRACE_DIR = "$evaluationEvidenceRoot/e2e/research-grader"
.\.venv\Scripts\python.exe -X utf8 -m pytest --collect-only -q `
  evals/e2e_quality/test_research_answer_outcome.py
```

只收集不会启动模型；实际运行需按预声明顺序和停止条件，不能把收集数写成模型通过数。评测器修改可消费封存真实答案，原E2E身份不改写；产品行为改变再执行受影响正式E2E。

## Release gate

```powershell
uv run python -m evals.e2e_quality.release_gate `
  --trace-root "$evaluationEvidenceRoot/e2e"
```

gate 当前检查：

1. catalog 计算为 `release_eligible`；
2. archive checksum 有效；
3. manifest commit 等于目标 revision；
4. archive 和目标工作树 clean；
5. test outcome 为 passed 且存在 trace；
6. capability 所需 evidence id 均 trusted。

gate 还会 fail closed 拒绝缺少 `UserOutcomeContract`、错层或使用 test double 的产品声明。重叠关系由 `evidence_audit` 输出；它不会只因共享断言就删除仍有独有不变量的用例。即便 trusted，也只证明该用户结果在固定 profile/revision 成立，不证明架构最初有产品必要性。

## 当前发布状态

历史压缩的非思考局部回放按[主循环 NS-1／2／3](../optimization/to_verify/conversation-loop-boundaries.md#非思考摘要的局部修正2026-10-22)执行。先运行 `python -m evals.provider_diagnostics.history_compaction --prepare --output-dir .tmp/ctx-compact-no-thinking-20261022` 完成零 HTTP 原输入对照，再对同目录使用 `--run` 执行一次旅程；使用本地 `.venv` 解释器，来源 DeepSeek 凭据只从既有受信绑定读取。本次一次旅程已结束，生成／消费／恢复及摘要语义限制见[当前成绩](02-current-case-inventory.md#2026-10-22-非思考摘要的局部验证)。既有目录禁止重跑；后续新执行须有新的授权、归档和预声明，不运行单元测试或完整产品 E2E 来补本例次数。

已有发布门禁记录曾因目标代码未提交、缺少同版本通过证据而拒绝，保留的原因包括：

```text
target_revision_dirty
missing_same_revision_passing_trace
```

现有定向归档尚未提供目标 clean revision 的完整发布矩阵。提交代码后仍须取得同版本完整证据，才能声明发布资格；历史完整矩阵或定向 archive 不替代该证据。


## 研究评分器输出额度

输出额度的修复机制与正式消费者配置由[评分输出预算固化记录](../optimization/completed/research-grader-output-budget.md)拥有，历史截断和预算恢复结果见[当前盘点](02-current-case-inventory.md#2026-10-01-独立评分器输出预算恢复)。原 E2E、评分反例和产品成功分子保持原身份；预算恢复与定向评分资格分别报告，不替代完整产品交付或发布证据。

## 原生工具历史的真实阶段回放

`python -m evals.product_baselines.model_history_replay --output <全新目录>` 消费固定 MiniMax 原始五阶段及 Journal，经生产原生历史投影、SDK 参数和容量边界检查完整保真、配对、恢复、身份拒绝和并行组选择；零真实模型或工具调用，不是 Product E2E。原件缺少新增决策字段，回放明确从封存 SDK 重建；不能把重建结果冒称旧生产已有历史。版本结果、其他控制／摘要回放及真实阶段限制由[续接规格](../optimization/model-provider-transport.md#2026-10-23-原生工具会话续接规格)拥有；不重用已有输出目录或改写旧封存。

## Code Agent 参数的完整阶段回放

`evals.product_baselines.python_action_replay` 消费原生历史接入后的 LongDS 第三轮完整首次失败请求。baseline 保留原实际 wire；candidate 由正式定义链导出完整声明，只更换已准入的直接参数协议、Python 描述及可选输入，历史原文不改。两组各10次，各自产生反馈并最多一次应用修复，SDK 修复另计，预算与停止由 [Python Spec §3.7](../optimization/to_verify/python-data-analysis-tool.md#37-code-agent-直接参数的接入与验证2026-10-24)拥有。

```powershell
.\.venv\Scripts\python.exe -B -X utf8 -m evals.product_baselines.python_action_replay --group baseline --output .tmp/<独立归档>/baseline
.\.venv\Scripts\python.exe -B -X utf8 -m evals.product_baselines.python_action_replay --group candidate --definitions .tmp/<正式定义导出>/definitions.json --output .tmp/<独立归档>/candidate
```

这是 Offline 参数／反馈阶段；模型选出的程序和工具均不派发，代码语法、所需文件、引用及实际 Python 覆盖另行审读，不按10/10协议合法宣称程序运行、业务答案或长任务通过。生产接续仍从正式自然请求和空 Journal 开始。

## 文件 ID 的完整阶段回放与交接

`artifact_reference_replay` 固定上一候选正式首轮的完整引用失败输入。baseline 保持原 wire，candidate 使用当前生产定义链及文件说明；每组10个独立连续旅程，原模型、think 和输出额度保持，真实拒绝由正式反馈配对。预算与停止由 [Python Spec §3.8](../optimization/to_verify/python-data-analysis-tool.md#38-文件选择只提交现有-id2026-10-24)拥有。prepared 保存完整声明、新旧文件协议段及用于新增反馈的实际身份；反馈 scaffold 清除旧执行记录，仅支持新增响应配对，不替换或裁剪首请求消息。

```powershell
.\.venv\Scripts\python.exe -B -X utf8 -m evals.product_baselines.artifact_reference_replay --group baseline --prepared .tmp/<已核对准备目录> --output .tmp/<独立归档>/baseline
.\.venv\Scripts\python.exe -B -X utf8 -m evals.product_baselines.artifact_reference_replay --group candidate --prepared .tmp/<已核对准备目录> --output .tmp/<独立归档>/candidate
.\.venv\Scripts\python.exe -B -X utf8 -m evals.provider_diagnostics.artifact_id_journey --prepared .tmp/<已核对准备目录> --output .tmp/<全新文件交接目录>
```

参数阶段不执行生成代码。文件交接使用该次实际材料和候选源码，经生产读取／搜索、检查、草稿创建／补丁及恢复边界；零新模型和容器，不代替完整产品结果。Python 真执行沿当前 `python_execution_boundary` 的真实研究源及独立目录运行。旧协议回放保留原源码身份，新正式流程使用空 Journal。
