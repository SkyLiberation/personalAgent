# Bash 分析镜像

镜像包含 Bash、Python 和固定版本的 pandas 与 NumPy。运行时按确切 image ID 启动一个供当前 Turn 复用的容器，默认禁网。容器为每条命令启动独立的非 root 进程，只读挂载本次命令的输入快照，并在下次调用前清理 `/tmp`。存在遗留进程时，执行器停止容器并核对终态后才允许替换。

从仓库根构建并记录 image ID。

```powershell
docker build --iidfile .tmp/bash-image-id.txt -t personal-agent-bash:local scripts/bash_execution
```

`PERSONAL_AGENT_BASH_EXECUTION_CONFIG` 指向包含 `authorization` 和 Docker `endpoint` 的部署 JSON。许可绑定主体、会话、到期时间、执行额度及 image ID。见 [Bash 工作区与执行契约](../../docs/optimization/to_verify/python-data-analysis-tool.md#bash-替换脚本执行工具)。
