# DeepSeek Harness 评测部署

各数据集共用 `evals/deepseek-harness/` 的独立 Git 检出和源码构建。数据集负责题面、工作区、可用工具、Cordis 配置和评分。运行器只接收本题允许的输入和工具，评分材料留在独立环境。[评测索引](../docs/evals/README.md)

## 准备运行时

从仓库根执行。以下检出命令用于首次准备。已有本地检出时，核对提交后直接构建。

```powershell
git clone https://github.com/deepseek-ai/deepseek-harness.git evals/deepseek-harness
git -C evals/deepseek-harness checkout --detach b150a551b8d465e31e418e1b2eaf5e79bbb7d28e
pnpm --dir evals/deepseek-harness install --frozen-lockfile
pnpm --dir evals/deepseek-harness run build
```

Windows 移动已有检出后，用 `pnpm --dir evals/deepseek-harness install --frozen-lockfile --force` 重装依赖并刷新旧工作区链接。源码、Git 元数据及构建产物随整个目录移动，外层仓库忽略该检出。

[每日源码对照](../docs/vsDSH/README.md)将共用检出同步到上游默认分支。运行评测前按目标提交重建运行时。复现历史评测时可用独立检出固定归档所记录的提交，保留该次模型、工具和评分配置。

## 共用评测入口

从仓库根运行 `python -m evals.run_deepseek_harness`。传入数据集准备的原题文件、隔离工作区、Cordis 配置和工作区外的新输出目录。配置须装配 stdio JSON-RPC SDK Server、模型及 JSONL 会话持久化。会话存储使用 `DSH_SESSION_ROOT` 作为 `root`，设置 `compression: none`。配置中模型密钥通过环境变量引用。

```powershell
.\.venv\Scripts\python.exe -B -X utf8 -m evals.run_deepseek_harness `
  --prompt-file $casePrompt --workspace $caseWorkspace --cordis $caseCordis `
  --provider $caseProvider --model $caseModel --output $caseOutput
```

运行器使用上游 Python SDK 和 `packages/examples/jsonrpc-demo/lib/bin.js`。输出包括 `sessions/` 下的原始会话、`report.json` 的运行身份与结束原因，以及取得终态时的 `final-response.txt`，附 `checksums.sha256`。可通过 `--max-tokens` 设置单次模型输出上限，通过 `--timeout-seconds` 设置等待时限，默认 1,200 秒。Harness 正常结束返回 0，评分由各数据集执行。Toolathlon 的镜像、MCP 接线及历史结果见[任务部署](Toolathlon/DEPLOYMENT.md#deepseek-harness-对照)。
