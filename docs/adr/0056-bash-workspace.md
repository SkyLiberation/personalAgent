# ADR 0056 通过受控工作区执行 Bash

## 背景

Toolathlon 的 GDP 用例已有可读原件。模型连续五次抄错会话目录，进程均未启动。此前专用 Python 工具要求模型在代码之外再提交文件路径与绑定名。[原始运行](../../.tmp/execution-input-removal-20261116/gdp/gdp-cr5-analysis/personal/report.json)

## 决定

正式工具 `bash` 接受命令、用途说明和可选工作目录。Conversation Journal 按当前任务和已授权的工作区模式选择并冻结只读输入。原生适配器按约定路径挂载输入并执行。模型消费 Bash 的 stdout、stderr 及退出状态。Artifact 保存冻结的命令、输入版本和双流，支持按原调用核对执行事实。

当部署把具名 MCP 服务的工作区绑定到当前会话时，Bash 和 MCP 使用同一获准的宿主目录。冻结的用户附件和已加载 Skill 脚本在 `/workspace/inputs` 只读挂载。会话原件经读搜能力获取。命令摘要从许可取得绑定身份，失败或未知写入沿原执行事实处理。[Skill 资源接入](0058-skill-script-resources.md) · [接入和验收](../mcpDesign/README.md#可比的执行环境)

## 取舍与防护

### Linux 原生沙箱迁移

Bash 采用 DeepSeek Harness 的 Linux `bwrap` 执行方式。Agent 服务直接启动 `bwrap`，普通命令各自使用 PID 和挂载命名空间。宿主目录只读映入沙箱，文件读取和网络沿用执行账户的宿主权限。沙箱自身提供 `/workspace`。Agent 数据目录对命令隐藏，冻结的只读输入挂载到授权的输入根。共享工作区用部署明确绑定的宿主目录，任务级 `/tmp` 用主机目录跨轮承载。普通调用使用各自的临时文件系统。Windows 上通过 WSL 运行同一 Linux Bash 入口。[DeepSeek Linux 沙箱](https://github.com/deepseek-ai/deepseek-harness/blob/4b399c39a6d1479cd84ca591b4d7c88e24d38a96/packages/sandbox/sandbox-local/src/profiles.ts#L16)

原生执行器拥有命令进程、双流和实际退出状态。超时及输出溢出终止当前调用。启动前持久声明已尝试执行的身份，主进程退出时 `--die-with-parent` 结束该调用，恢复只消费已落盘结果或报告结果未知。旧 Docker 执行配置、进程记录与镜像字段整体替换。通用 Bash 的预算保留时限与双流大小，其余资源由宿主运维设置管理。

评测可在 Bash 许可内用本机沙箱屏蔽评分目录并禁用命令联网，模型供应方连接仍由 Agent 服务负责。封存输入通过正常的授权快照挂回。本机沙箱的文件和网络策略由许可摘要绑定。

任务工作区的精确编辑沿用 `tool_edit`，宿主工作区记录保存专用读写确认的文件摘要。适配器用该摘要核对编辑前的文件版本，任务工作区释放时同时清除版本记录。[编辑契约和验收](../optimization/to_verify/program-artifact-contract.md#模型编辑工具)

WSL2 上的 `bwrap` 探针验证了三轮任务之间的文件保留及后台命令收尾，并覆盖退出码、双流、限时、输出上限、回执重读、单次临时盘和共享目录的读写边界。历史 Docker 运行保持原证据身份。[原生执行探针](../../.tmp/native-bash-migration-20261125/probe-result.json)

在同一 WSL2 环境离线回放了 LongDS 附件验收封存的两条 Bash 命令。两条命令的退出码、文件清单、附件摘要和字节数符合原记录，stderr 精确匹配。目录列表仅忽略宿主相关的时间和属主等元数据。[LongDS 原生命令回放](../../.tmp/native-bash-migration-20261125/longds-replay-result.json)

### LongDS 任务级持久 Bash

LongDS 的 `longds-bench` 要求同一任务的 Python 语句使用同一个 IPython 内核。原生逐次 `bwrap` 在命令返回时结束进程，只有文件跨轮保留。DeepSeek 的 `persistent-bash` 则给同一 Agent 会话复用一个被沙箱保护的 Bash。独立三轮探针在禁网配置下验证了原版 `pysession.py` 的同 PID 接续。证据用于采用进程生命周期，历史评测得分仍归原路径。[DeepSeek 持久 Bash](https://github.com/deepseek-ai/deepseek-harness/blob/4b399c39a6d1479cd84ca591b4d7c88e24d38a96/packages/shell/tool-bash-persistent/src/index.ts#L225-L299) · [三轮探针](../../.tmp/longds-ipython-persistent-bash-20261125/run-075232-ef2a5421/result.json)

任务授权显式启用 `persistent_bash`，并使用已有的独立任务工作区及轮次链验证。原生执行器为同一任务串行发送冻结命令给一个 Bash，在沙箱内保留 Bash、后台进程和 `/tmp`，仍为每条命令返回独立退出码与双流。使用管道传输命令以保留现有 Bash 工具的独立双流和非交互输入契约。输入先按原 Artifact 身份冻结，再发布到只读任务输入挂载。任务来源集合缩小时停止复用。超时、输出上限或终端退出结束该沙箱，后续合法命令可从新 Bash 开始。工作区关闭或服务关停结束后台进程。已有回执恢复只认已保存的命令结果。

配对使用封存的 Netflix Task 2 英文原题 34 轮和同一 MiniMax 模型。双方用相同 Linux 评测环境和依赖、非 root 身份，按 DeepSeek 的任务级 `bwrap` 装配隔离 PID 和网络，任务输入只读、`/tmp` 可写。评测进程各有独立实例。双方关闭 Goal，技能库只装载同版本 `longds-bench`。每轮由评测器投递当前题，模型经原版 `pysession.py` 完成计算，不取得题目清单或参考答案。先验证两边能从独立用户轮读回同一内核 PID 和内存变量、正常退出与隔离成立，再运行真实模型。用独立官方判分报告已作答、有效评分、通过及未执行轮次。技能和执行装配有各自的记录，单个任务不外推机制增益。

### Bash 许可随部署生效

2026-11-26 决定。LongDS 旧授权在服务保持装配时也会因独立到期时钟被恢复准入拒绝。上一轮以真实轮次回放了两种 Goal 模式的绑定校验。相同 LongDS 的 DeepSeek Harness `0.2.2-rc.5` 在单题运行实例内持续装配 Bash，任务终端和沙箱限制执行，命令采用 60 秒时限。本工程采用装配生命周期和单条命令限制，删除独立授权到期时间、工作区到期扫描与进程到期定时器。沿用受信部署文件、主体和会话绑定、许可摘要及工作区前驱约束。[旧边界回放](../../.tmp/dynarev-goal-decouple-20261126-180637-151/bash-expiry-replay.json) · [Harness 实跑配置](../../.tmp/longds-persistent-bash-pair-2g-20261125/harness/profile/cordis.json) · [Harness 运行报告](../../.tmp/longds-persistent-bash-pair-2g-20261125/harness/report.json)

Runtime 在启动时装配许可，撤销通过停止使用该许可的实例并更新部署配置生效。Conversation 按开始时间和 `turn_timeout_seconds` 冻结单轮截止，Journal 继续计算任务累计执行时间和 token 用量。原轮次恢复保留原截止、许可摘要和已经发生的消耗。执行器负责单条命令时限、沙箱及任务工作区关停。常规关停清除工作区。进程异常退出时，原生沙箱随父进程结束，残留的本机暂存文件只能由同一许可及合法前驱恢复。该许可退役且使用它的实例均已停止时，可清理 `bash_execution_jobs/task-workspaces/<许可摘要>` 下的残留暂存。已落盘的执行事实继续通过原命令身份读取。LongDS、Toolathlon 和 Marathon 的许可生成切换至同一配置格式。旧部署文件和封存检查点沿其原版本读取，历史证据保持原身份。

定向验收使用 LongDS 真实轮次，以旧许可到期时刻回放两种 Goal 模式的已完成轮次及新的轮次准入。覆盖原许可缺失、主体或会话不符、已过单轮截止和预算耗尽。使用 Linux 原生工具再核对连续任务轮次共享 Bash 状态、单条命令超时、沙箱与关停清理，补充同一执行器的普通和共享目录回放。离线回放与原生执行探针各一次，按实际边界记录。任一授权隔离、单轮截止或清理判据失守时，撤回此次切换。

两种 Goal 模式的离线回放均在旧到期时刻取回原答复并接纳下一轮，沿用已发生的消耗。缺许可、摘要变化及跨主体、跨会话恢复均被拒绝。单轮过期时返回限制终态，未新增模型调用。Linux 原生探针确认合法前驱跨轮保留同一 Bash、环境变量和文件，旁支拒绝复用。命令超时结束进程，下一条合法命令可读同一任务的暂存文件。关停结束进程并清理工作区。普通及共享目录模式的定向探针也通过。[离线回放](../../.tmp/bash-deployment-lifetime-20261126-191116-395/replay-result.json) · [原生探针](../../.tmp/bash-deployment-lifetime-20261126-191116-395/native-result.json)

### 历史 Docker 装配

2026-11-17 接受替换 Bash 容器生命周期。执行适配器以主体、Turn 和部署许可绑定一个 Docker 容器，每条命令使用独立的非 root Docker Exec 进程。回收或重用前须确认容器中无前次命令的遗留进程。普通及共享工作区的挂载权限由原许可决定。执行恢复按原命令身份核对，未落盘的完整双流不从退出码推断。Turn 终态释放容器，到期自行退出。基线、迁移、替代方案和验收由 [Bash 容器复用 Spec](../optimization/to_verify/python-data-analysis-tool.md#在同一-turn-内复用-bash-容器)维护。

新 Bash 容器由镜像自带的 `python3` 作为 PID 1，按截止时间停止并收尾退出的孤儿进程。Docker Exec 继续提供执行身份、双流及退出事实。存活后台进程仍使容器退出复用。部署选择支持 `python3` 的 Linux 镜像。

独立分析许可可配置 `retain_task_workspace: true`。Conversation Journal 将任务及对话分支绑定进冻结命令。Docker 适配器为该任务保留容器的 `/tmp`，沿用 DeepSeek LongDS 的单目录做法。许可摘要绑定该路径。对于冻结命令仍可见、内容摘要一致的只读输入，Docker 适配器复用同一任务的暂存文件。Bash 进程与 IPC 仍按调用检查，任务关停、授权到期或工作区失效时回收容器和文件。普通 Bash 和 MCP 许可逐命令清理 `/tmp`，按 Turn 回收容器。[任务工作区设计及证据](../optimization/to_verify/python-data-analysis-tool.md#bash-跨轮任务工作区候选)

任务工作区的只读输入包含用户附件和任务资料。Bash 自身发布的命令、清单和双流保留为会话原件，按回执路径读取。Journal 在准入和核验使用同一投影，原冻结命令继续拥有恢复身份。[输入边界与验收](../optimization/to_verify/python-data-analysis-tool.md#任务工作区的内容边界)

精确编辑通过 `tool_edit` 进入同一 Bash 接受、执行与恢复链。Conversation 按授权声明 `/tmp` 的读取和编辑。适配器在任务容器记录中保存专用读写产生的文件摘要，按进程原生回执确认，编辑时用它复核当前字节。版本属于容器生命周期，容器回收时随工作区记录清除。Artifact owner 继续以确切快照提交草稿新版本。[编辑契约和验收](../optimization/to_verify/program-artifact-contract.md#模型编辑工具)

采用 DeepSeek Harness 的 shell 工具接口及进程回执。应用沿用会话授权、临时盘及进程限额，检索实验沿用固定 worker。Bash 容器默认禁网，具名 MCP 工作区的部署许可可以显式指定任务网关的 Docker 容器 ID。Bash 共享该网关的网络命名空间，在独立容器内执行已授权的文件操作。Toolathlon 配对入口按任务装配这项权限。[网络装配和验收](../mcpDesign/README.md#可比的执行环境) · [Bash 工具契约](../optimization/to_verify/python-data-analysis-tool.md#bash-替换脚本执行工具)
