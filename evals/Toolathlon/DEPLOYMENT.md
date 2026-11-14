# Toolathlon-Verified 本地部署

Compose 使用固定摘要的上游任务镜像，启动 `finalpool/find-alita-paper` 的预处理与 MCP Gateway。Python、Node.js 和工具依赖均在容器内。容器挂载固定版本的上游文件，任务工作区位于容器内。

从仓库根准备独立的 Toolathlon-Verified 上游检出。已有检出时核对提交号即可。使用其他位置时，将 `TOOLATHLON_UPSTREAM_DIR` 设置为该检出的绝对路径。

```powershell
git clone https://github.com/hkust-nlp/Toolathlon.git toolServer/Toolathlon
git -C toolServer/Toolathlon checkout --detach 9be8d8fe07a497b18ee61e3f2ae694e9797f39eb
```

## 启停和连接

在仓库根执行以下命令。首次启动需要下载上游镜像。

```powershell
docker compose -f evals/Toolathlon/compose.yaml up -d --wait --wait-timeout 180
Invoke-RestMethod http://127.0.0.1:18160/health
docker compose -f evals/Toolathlon/compose.yaml logs --tail 100 alita
```

MCP 客户端使用 SSE 传输，地址为 `http://127.0.0.1:18160/sse`。健康检查要求 `arxiv_local`、`filesystem` 和 `scholarly` 均已连接。`filesystem` 的作用域为 `/workspace/dumps/workspace`。

如需保留产物，先导出工作区。启动时上游预处理会重建工作区。

```powershell
docker compose -f evals/Toolathlon/compose.yaml cp alita:/workspace/dumps/workspace ./.tmp/toolathlon-workspace
docker compose -f evals/Toolathlon/compose.yaml down
```

## 正式评测

此 Compose 服务用于验证首题工具环境。正式评测由上游运行器执行，它为每次评测准备任务状态、运行智能体并调用评测器。模型配置由 Toolathlon 自己提供。使用 `unified` 时，在独立的 Linux 或 WSL 运行环境配置 `TOOLATHLON_OPENAI_BASE_URL`，并按模型服务要求设置 `TOOLATHLON_OPENAI_API_KEY`。入口见[上游 Quick Example](https://github.com/hkust-nlp/Toolathlon/blob/9be8d8fe07a497b18ee61e3f2ae694e9797f39eb/README.md#quick-example)和[解耦运行器](https://github.com/hkust-nlp/Toolathlon/blob/9be8d8fe07a497b18ee61e3f2ae694e9797f39eb/DECOUPLED_AGENT_LOOP.md#main-script)。

全量评测另需上游声明的应用账号、凭据和服务。上游 `global_preparation/deploy_containers.sh` 会清理 Docker 守护进程上的未使用资源，因此全量服务应使用独立的 Docker 守护进程。配置要求见[上游 Full Preparation](https://github.com/hkust-nlp/Toolathlon/blob/9be8d8fe07a497b18ee61e3f2ae694e9797f39eb/README.md#full-preparation)。
