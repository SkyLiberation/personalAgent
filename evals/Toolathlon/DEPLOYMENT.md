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

## DeepSeek Harness 对照

检出、构建及会话启动使用 [DeepSeek Harness 共用部署](../deepseek-harness-deployment.md)。Toolathlon 提供原题、任务镜像、网关与官方评分器。测试使用的 MCP 配置通过 SSE 转 stdio 桥接访问任务网关。

首轮对照使用 `find-alita-paper` 原题、固定 Toolathlon 任务镜像和官方评分器。使用 DeepSeek Harness 的 JSON-RPC SDK、会话日志和 MCP 客户端，经 SSE 转 stdio 的桥接访问本题工具。模型沿用本工程评测配置中的 `MiniMax-M3.1-Flash`；不同执行配置、请求参数和工具协议分别记录。参考文件仅交给评分流程。

首题执行一次，使用新的任务环境和会话。上游评分器检查下载的 PDF，单独核对三行答复。记录实际用时、模型用量、工具调用和停止原因。首题达到 200,000 tokens 后完成成本复核，追加 `imagenet` 和 `interview-report` 各一次，覆盖 PDF 和 Word 工具；历史同题合计约 83 万 tokens、310 秒。两题串行执行，沿用 64 个模型步骤、单次最多输出 32,768 tokens 和每题等待上限 1,200 秒。扩测在累计用量达到 120 万 tokens 或出现服务配额异常后停止启动新题。结果属于外部 Agent 样本，后续按题目、初始环境、模型、预算和评分身份配对。

复跑使用本题准备的工作区和 Cordis 配置，通过共用入口启动 Harness，保留本次会话产物交给官方评分器。旧脚本随原运行身份保存在历史归档。

### 2026-11-17 样本结果

`pnpm install --frozen-lockfile` 和 `pnpm run build` 均退出 0。三题都获得官方评分，1/3 通过，2/3 返回正式答复。累计 1,386,947 tokens，含缓存读取。一次在模型调用前失败的启动诊断单独保留。样本结果见[汇总](../../.tmp/deepseek-toolathlon-20261117/summary.json)。

| 用例 | 官方评分 | 模型步骤／工具调用 | Agent 耗时 | Tokens | 结果 |
| --- | --- | ---: | ---: | ---: | --- |
| [`find-alita-paper`](../../.tmp/deepseek-toolathlon-20261117/alita-01/report.json) | 通过 | 10／13 | 48.9 秒 | 218,375 | PDF 与官方参考一致；答复多了一段说明，不满足只返回三行的要求。 |
| [`imagenet`](../../.tmp/deepseek-toolathlon-20261117/imagenet-01/report.json) | 未通过 | 10／16 | 23.2 秒 | 143,892 | 已写出 `survey.tex`，但两行的 FID 排序与题目要求相反。 |
| [`interview-report`](../../.tmp/deepseek-toolathlon-20261117/interview-01/report.json) | 未通过 | 64／108 | 212.8 秒 | 1,024,680 | 工具调用均为读取或列举，达到模型步骤上限时未生成报告或返回正式答复。 |

汇总按题面摘要和原始网关工具清单匹配 personalAgent 历史报告，三题的官方评分结果相同。双方的提示、模型请求参数、材料进入模型的方式和预算不同。配对用于后续分析，本轮未重跑 personalAgent，三题结果不外推到全量套件。

### Canvas 排考定向运行

2026-11-17 使用 `MiniMax-M3.1-Flash` 执行一次 `canvas-arrange-exam`。预处理容器初始化 Canvas 和邮件，执行容器接收原始工作簿、记忆和服务连接配置。终端从固定任务镜像加载 `openpyxl 3.1.5`，官方评分在独立容器读取产物。前两次启动检查分别发现终端命令解析和 Python 依赖问题，均未调用模型。[运行入口](../../.tmp/deepseek-canvas-20261117/run_canvas.py) · [隔离检查](../../.tmp/deepseek-canvas-20261117/canvas-03/isolation.json)

官方评分 9/9 匹配。独立读取工作簿确认表头与原模板一致，课程集合与参考一致。Harness 在 20 个模型步骤、44 次工具调用后返回正式答复，耗时 67.7 秒，累计 1,149,199 tokens，含缓存读取。题面摘要与 personalAgent 的历史定向复验一致。该历史样本也匹配了全部 9 门课，但多写入了已经考完的 CS101。[Harness 报告](../../.tmp/deepseek-canvas-20261117/canvas-03/report.json) · [官方评分](../../.tmp/deepseek-canvas-20261117/canvas-03/grader.log) · [personalAgent 历史评分](../../.tmp/mcp-sandbox-1117/run/canvas-arrange-exam/personal/grader.log)
