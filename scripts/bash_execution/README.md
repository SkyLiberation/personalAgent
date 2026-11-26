# Bash 评测工具链镜像

镜像为评测工具链提供 Bash、Python 和固定版本的 pandas 与 NumPy。本 Agent 的正式 Bash 入口使用 Linux 本机的 `bubblewrap` 和 `bash`。 [原生沙箱契约](../../docs/adr/0056-bash-workspace.md#linux-原生沙箱迁移)

从仓库根构建并记录 image ID。

```powershell
docker build --iidfile .tmp/bash-image-id.txt -t personal-agent-bash:local scripts/bash_execution
```

按 [Bash 部署配置](../../docs/env.md#通用-bash-执行许可)启动本 Agent。
