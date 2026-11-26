# DeepSeek Harness 评测部署

各数据集共用 `evals/agents/deepseek-harness/` 的独立 Git 检出和源码构建。数据集负责题面、工作区、可用工具、Cordis 配置和评分。运行器只接收本题允许的输入和工具，评分材料留在独立环境。[评测索引](../docs/evals/README.md)

## 准备运行时

从仓库根执行。以下检出命令用于首次准备。已有本地检出时，核对提交后直接构建。

```powershell
git clone https://github.com/deepseek-ai/deepseek-harness.git evals/agents/deepseek-harness
git -C evals/agents/deepseek-harness checkout --detach b150a551b8d465e31e418e1b2eaf5e79bbb7d28e
pnpm --dir evals/agents/deepseek-harness install --frozen-lockfile
pnpm --dir evals/agents/deepseek-harness run build
```

Windows 移动已有检出后，用 `pnpm --dir evals/agents/deepseek-harness install --frozen-lockfile --force` 重装依赖。检查各工作区 `node_modules` 的 Junction，重建仍指向旧位置的链接。用 `pnpm --dir evals/agents/deepseek-harness run build` 验证构建，并用新路径的 SDK 和 JSON-RPC 运行时验证初始化。移动了主工作树时，先用 `git worktree repair` 修复关联工作树的 Git 路径。外层仓库忽略整个 `evals/agents/`。

[每日源码对照](../docs/vsDSH/README.md)将共用检出同步到上游默认分支。运行评测前按目标提交重建运行时。复现历史评测时可用独立检出固定归档所记录的提交，保留该次模型、工具和评分配置。

## 共用评测入口

从仓库根运行 `python -m evals.run_deepseek_harness`。传入数据集准备的原题文件、隔离工作区、Cordis 配置和工作区外的新输出目录。配置须装配 stdio JSON-RPC SDK Server、模型及 JSONL 会话持久化。会话存储使用 `DSH_SESSION_ROOT` 作为 `root`，设置 `compression: none`。配置中模型密钥通过环境变量引用。

```powershell
.\.venv\Scripts\python.exe -B -X utf8 -m evals.run_deepseek_harness `
  --prompt-file $casePrompt --workspace $caseWorkspace --cordis $caseCordis `
  --provider $caseProvider --model $caseModel --output $caseOutput
```

运行器使用上游 Python SDK 和 `packages/examples/jsonrpc-demo/lib/bin.js`。输出包括 `sessions/` 下的原始会话、`report.json` 的运行身份与结束原因，以及取得终态时的 `final-response.txt`，附 `checksums.sha256`。可通过 `--max-tokens` 设置单次模型输出上限，通过 `--timeout-seconds` 设置等待时限，默认 1,200 秒。Harness 正常结束返回 0，评分由各数据集执行。Toolathlon 的镜像、MCP 接线及历史结果见[任务部署](Toolathlon/DEPLOYMENT.md#deepseek-harness-对照)。

## 使用 Bash 的数据集

LongDS、Marathon 和 Skill-Use-Bench 共用 DeepSeek 官方 `dsh --profile sdk-minimal` 入口，执行镜像安装发布包 `@deepseek-ai/dsh@0.2.2-rc.5`。Node.js 直接承载 Harness，每次 Bash 调用由上游本机沙箱启动独立进程。适配层沿用各数据集的 Linux 工具链，在 workspace 和任务临时目录上运行原生工具。`--harness-image` 可指定同一部署契约的镜像。

执行环境只挂载本题材料、任务工作区、运行配置和本题会话存储。模型请求由 Node.js 发送，Bash 在独立网络命名空间中运行。模型密钥文件在启动后和提交题目之前删除。数据集仍负责原题、会话预算、产物和评分。历史 Docker Exec 适配运行保留原身份。

在仓库根构建待运行数据集的镜像。Marathon 和 Skill-Use-Bench 先按各自 README 准备基础镜像。

```powershell
docker build -f evals/deepseek-runtime.Dockerfile -t personal-agent-dsh-longds:local evals
docker build -f evals/deepseek-runtime.Dockerfile --build-arg BASE_IMAGE=personal-agent-marathon:go127-node22 -t personal-agent-dsh-marathon:local evals
docker build -f evals/deepseek-runtime.Dockerfile --build-arg BASE_IMAGE=personal-agent-skill-use:local -t personal-agent-dsh-skill-use:local evals
```

### LongDS 对照的文件工具

LongDS 在只读 `/workspace` 提供校验过的原件，`/tmp` 是本题的共享临时目录。`bash`、`read`、`write` 和 `edit` 使用同一 Linux 文件系统。使用既有封存材料和新输出目录预检。

```powershell
.\.venv\Scripts\python.exe -B -X utf8 -m evals.longDS.run_longds_harness `
  --materials $sealedLongDSMaterials --output $newRunDirectory --check-only
```

预检向本机受控端点发送请求，检查 Node.js 主进程、原生工具声明、跨调用文件读写、原件只读、Bash 网络与密钥边界、评分材料不可达。请求和回执保存在 `tool-preflight.json`，运行身份保存在 `harness-runtime.json`。预检结果只作为执行环境证据。

正式采集移除 `--check-only`，使用 `STRUCTURED_BASE_URL`、`STRUCTURED_MODEL` 和 `STRUCTURED_API_KEY`，并选用新的输出目录。取得有分配对时双方从空会话独立执行并使用原评分契约。
