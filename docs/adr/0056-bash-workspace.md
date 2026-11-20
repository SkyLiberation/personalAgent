# ADR 0056 通过受控工作区执行 Bash

## 背景

Toolathlon 的 GDP 用例已有可读原件。模型连续五次抄错会话目录，进程均未启动。此前专用 Python 工具要求模型在代码之外再提交文件路径与绑定名。[原始运行](../../.tmp/execution-input-removal-20261116/gdp/gdp-cr5-analysis/personal/report.json)

## 决定

正式工具 `bash` 接受命令、用途说明和可选工作目录。Conversation Journal 根据当前任务的可读 Artifact 冻结只读工作区。Docker 适配器按原路径挂载文件并执行。模型消费 Bash 的 stdout、stderr 及退出状态。Artifact 保存冻结的命令、输入版本和双流，支持按原调用核对执行事实。

当部署把一个具名 MCP Server 的工作区绑定到当前会话时，Bash 从授权的镜像和目录运行，Docker 只授予绑定卷子目录的写权限。该卷持有当前工作区文件，MCP 和 Bash 均在这个作用域内执行，评分器读取同一目录。部署可同时绑定一个只读运行时卷。冻结的 Artifact 继续持有只读输入，工作区的实时内容由卷持有。命令摘要从会话许可取得绑定身份，失败或未知写入沿原执行事实处理。[接入和验收](../mcpDesign/README.md#可比的执行环境)

## 取舍与防护

2026-11-17 接受替换 Bash 容器生命周期。执行适配器以主体、Turn 和部署许可绑定一个 Docker 容器，每条命令使用独立的非 root Docker Exec 进程。回收或重用前须确认容器中无前次命令的遗留进程。普通及共享工作区的挂载权限由原许可决定。执行恢复按原命令身份核对，未落盘的完整双流不从退出码推断。Turn 终态释放容器，到期自行退出。基线、迁移、替代方案和验收由 [Bash 容器复用 Spec](../optimization/to_verify/python-data-analysis-tool.md#在同一-turn-内复用-bash-容器)维护。

独立分析许可可配置 `retain_task_workspace: true`。Conversation Journal 将任务及对话分支绑定进冻结命令。Docker 适配器为该任务保留容器的 `/tmp`，沿用 DeepSeek LongDS 的单目录做法。许可摘要绑定该路径。对于冻结命令仍可见、内容摘要一致的只读输入，Docker 适配器复用同一任务的暂存文件。Bash 进程与 IPC 仍按调用检查，任务关停、授权到期或工作区失效时回收容器和文件。普通 Bash 和 MCP 许可逐命令清理 `/tmp`，按 Turn 回收容器。[任务工作区设计及证据](../optimization/to_verify/python-data-analysis-tool.md#bash-跨轮任务工作区候选)

精确编辑通过 `tool_edit` 进入同一 Bash 接受、执行与恢复链。Conversation 按授权声明 `/tmp` 的读取和编辑。适配器在任务容器记录中保存专用读写产生的文件摘要，按进程原生回执确认，编辑时用它复核当前字节。版本属于容器生命周期，容器回收时随工作区记录清除。Artifact owner 继续以确切快照提交草稿新版本。[编辑契约和验收](../optimization/to_verify/program-artifact-contract.md#模型编辑工具)

采用 DeepSeek Harness 的 shell 工具接口及进程回执。应用沿用会话授权、临时盘及进程限额，检索实验沿用固定 worker。Bash 容器默认禁网，具名 MCP 工作区的部署许可可以显式指定任务网关的 Docker 容器 ID。Bash 共享该网关的网络命名空间，在独立容器内执行已授权的文件操作。Toolathlon 配对入口按任务装配这项权限。[网络装配和验收](../mcpDesign/README.md#可比的执行环境) · [Bash 工具契约](../optimization/to_verify/python-data-analysis-tool.md#bash-替换脚本执行工具)
