# CTXAgent Marathon

本目录运行论文发布版的公开用例 `marathon:0`。准备器和评分器调用上游构题、临时文件和评分回调。两边发送同样的 212 轮英文原题，每边使用一个会话。只替换沙箱绝对路径和 JavaScript 提示中的 Linux 命令路径。[验收与结果](../../docs/problems/marathon/marathon-0.md)

## 准备

1. 检出 [CTXAgent 发布版](https://github.com/MatthiasHBusch/CTXAgent/tree/77ec7a9e9127e3258b035af32dc7f13730979902)，按其 `bench/external/fetch.ps1` 取得 Aider Polyglot 和 SciCode 源码。可跳过其中的 Go、JavaScript 和官方 Harness 安装，工具链由本目录的 Docker 镜像提供。上游构题还会读取 [Letta Evals 的 Filesystem Agent 数据](https://github.com/letta-ai/letta-evals/tree/e6140262abf970b7ea94bcac548b52a9dd7a7e2b/letta-leaderboard/filesystem-agent)。将该版本检出到 `bench/external/letta-evals`。
2. 将 [SciCode dev JSONL](https://huggingface.co/datasets/SciCode1/SciCode/blob/4510f6a6aa27c43fad7b43da2c59602a86e88480/problems_dev.jsonl) 和[数值参考文件](https://huggingface.co/datasets/Srimadh/Scicode-test-data-h5/blob/72c247d3a8410921b2e848e046d71ed63d9a0ddb/test_data.h5) 放入上游检出的 `bench/external/SciCode/eval/data/`。准备器校验 HDF5 的 SHA-256。
3. 在临时工具目录放入官方 Linux x64 的 Go 1.27.3（命名为 `go.tar.gz`）、Node 22.22.0（命名为 `node.tar.xz`），并将上游的 `bench/external/js_shared.package.json` 复制为 `package.json`。使用下列命令构建镜像。基础镜像使用项目已有 Bash 沙箱。

```powershell
docker build --build-context toolchain=.tmp/marathon-toolchain -t personal-agent-marathon:go127-node22 evals/marathon
.\.venv\Scripts\python.exe -B -X utf8 -m evals.marathon.run prepare --upstream .tmp/ctxagent-marathon-upstream --output .tmp/marathon-materials
```

## 执行

在 Linux 或 WSL2 中执行对照。本 Agent 使用宿主的 `bwrap`、Bash 和题目工具链，需准备本题所用的 Go、Node、Jest 和 Python 依赖。DeepSeek 使用基于 Marathon 工具链镜像构建的执行镜像，任务配置与镜像身份随运行归档。 [共用部署](../deepseek-harness-deployment.md#使用-bash-的数据集)

```powershell
docker build -f evals/deepseek-runtime.Dockerfile --build-arg BASE_IMAGE=personal-agent-marathon:go127-node22 -t personal-agent-dsh-marathon:local evals
python -B -X utf8 -m evals.marathon.run run --upstream .tmp/ctxagent-marathon-upstream --prepared .tmp/marathon-materials --output .tmp/marathon-run --model-env .env
```

两边在轮与轮之间检查 6 亿已知 tokens 的停止线，单轮主决策上限为 100。本 Agent 保留 1,000 万单轮 token 上限。1500 秒用于本 Agent 的 Bash 执行授权及 HTTP 等待，并作为 DeepSeek SDK 的请求超时。DeepSeek SDK 等待轮次结束通知使用其原生行为。两边使用 1M 模型窗口和禁网的 Bash 工作区。DeepSeek 镜像配置 1 CPU 和 1 GiB 内存，本 Agent 的资源额度由宿主控制。保留各自的对话控制、压缩机制和工具协议。在特定一侧的归档目录创建 `stop-after-turn` 可在当前轮完结后停止。

`progress.json` 记录实际提交和交付。完成采集后，上游评分器在禁网容器中检查双方各自的终态工作区。每侧有 `report.json`、原始交互、`scores.json`、最终工作区副本和校验和。`comparison.json` 汇总交付、官方分项、用量、峰值和压缩证据。未到达的轮次单独计数。

如评分环境需修正，可读取封存工作区和回复，以独立归档重新调用同一套上游评分。该步骤不调用模型。

```powershell
.\.venv\Scripts\python.exe -B -X utf8 -m evals.marathon.run grade --upstream .tmp/ctxagent-marathon-upstream --capture .tmp/marathon-run --output .tmp/marathon-regrade
```
