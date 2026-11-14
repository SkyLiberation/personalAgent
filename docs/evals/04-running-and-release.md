# 运行、归档与发布

## Toolathlon MCP 验证

Toolathlon 的隔离产品进程关闭前置意图分类。各场景按自己的核验配置运行，生成的 `feature_flags.toml` 随结果保存。

需要上游任务材料或验证聚合网关时，按[本地部署说明](../../evals/Toolathlon/DEPLOYMENT.md)准备固定版本的独立检出。

从仓库根运行。Time 镜像使用 Toolathlon 锁定的 Time Server 依赖。每个场景创建独立数据库、产品进程和工具容器。`protocol_and_lifecycle_passed` 评价接线与生命周期。`--model-env` 可追加一次正式对话并归档答复及模型请求声明。

```powershell
docker build --tag personal-agent-toolathlon-time:0.6.2 evals/Toolathlon
$toolathlonRun = ".tmp/toolathlon-" + (Get-Date -Format "yyyyMMdd-HHmmss-fff")
.\.venv\Scripts\python.exe -B -X utf8 -m evals.Toolathlon.runner --scenario read --time-image personal-agent-toolathlon-time:0.6.2 --postgres-image paradedb/paradedb:latest --output "$toolathlonRun/read"
```

生命周期场景包括 `unmapped`、`partial`、`duplicate` 和 `disconnect`。每个场景使用新的输出目录。文件权限与覆盖探测使用[专用 Filesystem 镜像](../../evals/Toolathlon/Dockerfile.filesystem)和临时样本。

```powershell
docker build --platform linux/amd64 --tag personal-agent-toolathlon-filesystem:2.2.0 --file evals/Toolathlon/Dockerfile.filesystem evals/Toolathlon
$env:PYTHONPATH = (Join-Path (Get-Location) "src")
.\.venv\Scripts\python.exe -B -X utf8 -m evals.Toolathlon.filesystem_probe --image personal-agent-toolathlon-filesystem:2.2.0 --output "$toolathlonRun/filesystem"
```

报告中两个样本的 `isolated` 均应为 `true`。冲突样本的 `existing_destination_overwritten` 应为 `false`，`overwrite_error` 应表明目标已存在，样本目录中的源文件和原目标文件均应保留。

确认派发探针复用同一镜像和正式工具 HTTP 入口。它记录远端实际收到的调用，验证未确认、参数自报确认、配置拒绝和正常读取。

```powershell
.\.venv\Scripts\python.exe -B -X utf8 -m evals.Toolathlon.confirmation_probe --image personal-agent-toolathlon-filesystem:2.2.0 --postgres-image paradedb/paradedb:latest --output "$toolathlonRun/confirmation"
```

`report.json` 和摘要记录实际配置与结果。验证范围见 [MCP 接入 Spec](../mcpDesign/README.md#7-场景推演与验收)。

工作区正式用例通过真实模型提交清单，并由测试调用方在认证 Web 入口决定。按场景独立运行 `approve`、`reject`、`disconnect` 和 `arrange`。完整整理需要固定版本的上游 checkout，评分器在工具容器外运行。输出目录名宜保持简短以兼容 Windows 的模型归档路径。

```powershell
.\.venv\Scripts\python.exe -B -X utf8 -m evals.Toolathlon.workspace_case --scenario approve --image personal-agent-toolathlon-filesystem:2.2.0 --postgres-image paradedb/paradedb:latest --model-env .env --output .tmp/workspace-approve
.\.venv\Scripts\python.exe -B -X utf8 -m evals.Toolathlon.workspace_case --scenario arrange --image personal-agent-toolathlon-filesystem:2.2.0 --postgres-image paradedb/paradedb:latest --model-env .env --upstream toolServer/Toolathlon --output .tmp/workspace-arrange
```

`approval_passed` 核对正式确认和实际 MCP 派发，`workspace_passed` 核对外部文件终态，`answer_passed` 核对产品交付。完整样本还记录上游评分退出码和文件内容摘要。


PDF 文件交付样本使用同一独立环境。原件挂载为只读，模型将新文件写入本次输出目录。用例运行固定的上游评分器，并在报告中分别记录真实工具预检、产品答复和文件评分。 PDF 页范围的两个整数字段通过本地映射启用[模型参数读取约定](../context/runtime-feedback.md#显式允许的整数表示)，原题和评分条件沿用上游。

```powershell
.\.venv\Scripts\python.exe -B -X utf8 -m evals.Toolathlon.pdf_cases --scenario imagenet --upstream toolServer/Toolathlon --model-env .env --output .tmp/pdf-imagenet
.\.venv\Scripts\python.exe -B -X utf8 -m evals.Toolathlon.pdf_cases --scenario detect-revised-terms --upstream toolServer/Toolathlon --model-env .env --output .tmp/pdf-revised
```

### SerpApi 地图工具

地图用例可以使用 [SerpApi 地图适配器](../../evals/Toolathlon/serpapi_maps.py)。从仓库根目录运行以下命令，`$toolathlonNetwork` 取本次样本网关与评分器使用的 Docker 网络。服务容器使用评测镜像中的 MCP SDK，结束本次运行后按返回的容器 ID 回收。

```powershell
$env:SERP_API = [Environment]::GetEnvironmentVariable('SERP_API', 'Machine')
$mapsAdapter = (Resolve-Path 'evals/Toolathlon/serpapi_maps.py').Path
docker run --rm -d --network $toolathlonNetwork --network-alias serpapi-maps -e SERP_API --mount "type=bind,source=$mapsAdapter,target=/run/serpapi_maps.py,readonly" --entrypoint /workspace/.venv/bin/python lockon0927/toolathlon-task-image:1016beta -B /run/serpapi_maps.py
```

在网关和通过 `MCPServerManager` 查询地图的评分器容器启动参数中，将 [SerpApi MCP 配置](../../evals/Toolathlon/serpapi_maps.yaml)只读挂载到 `/workspace/configs/mcp_servers/google_map.yaml`。网关工具名使用 `google_map-` 前缀，产品映射使用 `google_map.` 前缀，后缀为 `maps_directions`、`maps_search_places`、`maps_place_details` 或 `maps_distance_matrix`。权限为读取，外部请求使用服务凭据。报告须记录 SerpApi 作为地图服务方。判据见 [MCP 接入 Spec](../mcpDesign/README.md#533-serpapi-地点与距离矩阵)。

### 对话预算

工作区和 PDF 用例从 `--model-env` 指定的配置读取累计 token、主决策轮数和工具调用上限。使用仓库的 `.env` 时，两类用例均采用[本地对话预算](../env.md#对话运行预算)。命令行的 `--model-budget`、`--model-turns` 和 `--tool-calls` 分别覆盖对应字段，文件中缺失的值采用 Runtime 默认配置。每个用例的报告记录三个生效值。

预算装配验收核对同一配置文件在工作区和 PDF 入口启动的子进程，以及批量入口的逐项覆盖。对照使用缺少预算字段的配置，核对 Runtime 默认值。以子进程读取到的预算为准。

2026-11-11 核对 `arrange-workspace`、`imagenet` 和 `detect-revised-terms` 的批量参数与实际子进程配置。三例读取同一 `.env` 时均为 32 轮、48 次工具调用、2,000,000 tokens。单项覆盖、三项覆盖及缺失字段回退均通过。该检查覆盖预算配置，模型调用为零。[配置验证报告](../../.tmp/toolathlon-budget-20261111/report.json)

### 多用例并行执行

批量入口接收用空格分隔的用例列表，按 `--workers` 限制同时运行的用例数，默认是 2。从仓库根运行，`--output` 须指向新目录。可用用例名称见 `--help`。

```powershell
.\.venv\Scripts\python.exe -B -X utf8 -m evals.Toolathlon.parallel imagenet detect-revised-terms --workers 2 --model-env .env --output .tmp/tap
```

每个用例由独立子进程调用原单用例 CLI，继续使用该入口的产品配置、工具映射和评分器。产品子进程自行绑定 Web 端口，并在退出前持有端口。工作区和 PDF 用例要求 `--model-env`。`--upstream` 默认是 `toolServer/Toolathlon`。批量入口向工作区和 PDF 用例转发三个对话预算参数。

每个用例的产物和原报告保存在批次目录下的同名子目录，子进程日志保存在同名 `.log` 文件。批次 `report.json` 按输入顺序记录每个用例的执行时间、退出码及证据位置。单例失败后继续调度其余用例。所有子进程退出码均为 0 时批次返回 0，否则返回 1。

调度验收使用已有 Time 接线和启动拒绝场景，核对真实子进程重叠、独立报告及原有判据。另用一个无效 Time 镜像与一个正常 Filesystem 探针同批运行，核对失败后其余用例仍完成、批次返回非零。

### Redis Helm 官方 Agent 对照

`k8s-redis-helm-upgrade` 用于观察同一 MiniMax-M3.1-Flash 在 Toolathlon 官方 Agent 与 personalAgent 中如何推进 Redis Helm 升级。历史 personalAgent 样本在累计 200 万 token 后结束，官方评分为 0.8。待验证的问题是官方 Agent 是否会提交升级，以及它在镜像检查、配置迁移、工具拒绝和验收上的实际路径。

1. 复用固定版本的上游预处理、Kubernetes／终端／文件系统 MCP 网关和 Redis 评分器。每次建独立 Kind 集群，使用同一原题与工作区说明，初始 Chart 为 `19.0.0`。上游评分器负责核对目标 `22.0.0`、自定义配置和服务状态。
2. 从仓库根调用 `evals.Toolathlon.compare.redis_helm`。入口使用现有 Docker 容器辅助函数，将上游官方单轮 Agent 连接到本次网关，模型配置从 `--model-env` 读取。`--model-turns` 设置官方 Agent 的内部决策轮数，默认 32。两边的会话等待上限均为 600 秒。历史 personalAgent 使用 32 轮、48 次工具调用和 200 万累计 token。对照保留双方 Prompt、工具协议和预算差异，结论以实际轨迹及评分为准。
3. 先核对入口参数、历史报告与固定版本，然后串行运行官方样本。首次使用上游默认 SSE 等待时间，真实终端调用多次在 5 秒时超时。后续用 `--mcp-session-timeout 90` 为终端自身的 60 秒命令上限预留回包时间，其余 Agent 行为沿用上游。两次运行分别归档。评分记录 Agent 终态、升级版本与官方分数，同时保存可取得的模型请求数、token、工具调用、耗时、原始轨迹及校验和。结果归档在 `.tmp/`，可选的 `--personal-run` 指向已有 personalAgent 用例目录。

```powershell
.\.venv\Scripts\python.exe -B -X utf8 -m evals.Toolathlon.compare.redis_helm --model-env .env --output .tmp/ta-redis-compare --mcp-session-timeout 90 --personal-run .tmp/ta27-1113-k8s/final-redis-helm-upgrade/k8s-redis-helm-upgrade
```

本地入口启动上游 `scripts.decoupled.host_agent_loop`，任务与评分来自上游 `9be8d8fe07a497b18ee61e3f2ae694e9797f39eb`。`--check-only` 核对版本、模型与历史输入，不启动容器。实际对照结果见[历次评测问题汇总](../problems/toolathlon-verifierd.md#redis-helm-官方-agent-对照)。

扩大预算的对照为两个 Agent 各执行一次 64 轮样本，沿用同一模型、原题、Kind 初始状态与官方评分器。personalAgent 使用 128 次工具调用和 800 万累计 token，让它有额度继续执行 64 轮。官方 Agent 继续使用 90 秒 SSE 等待设置，工具调用和累计 token 随其原生循环统计。两个新集群串行启动。评分分别核对升级版本、配置及运行状态，另记录停止原因和用量。此前 32 轮运行按原身份保留。

## 公开数据集运行

从仓库根使用以下命令，各抽取一个公开样本，执行词法检索。每次运行使用新的输出目录。数据读取和指标定义见各数据集入口。[公开数据集索引](README.md#公开数据集评测)

```powershell
$evaluationEvidenceRoot = ".tmp/public-evaluation-" + (Get-Date -Format "yyyyMMdd-HHmmss-fff")
$env:PERSONAL_AGENT_E2E_TRACE_DIR = "$evaluationEvidenceRoot/e2e"
$env:PERSONAL_AGENT_PRODUCT_EVIDENCE_DIR = "$evaluationEvidenceRoot/product"

uv run --extra dev --dev python -m evals.open_ragbench.runner --strategies keyword --num-queries 1 --corpus-mode relevant --output "$evaluationEvidenceRoot/open.json"
uv run --extra dev --dev python -m evals.multihoprag.runner --strategies keyword --num-queries 1 --corpus-mode relevant --output "$evaluationEvidenceRoot/multihop.json"
uv run --extra dev --dev python -m evals.galileo_ragbench.runner --strategy galileo_keyword_sentence --subset covidqa --split test --num-queries 1 --output "$evaluationEvidenceRoot/galileo.json"
uv run --extra dev --dev pytest --collect-only -q evals/open_ragbench
```

CI 核对三个命令行入口和 Open RAGBench 的用例收集。词法样本可使用缓存数据运行，指标代表对应检索策略。

LongDS 的现行入口位于 `evals/longDS/`，使用公开题面和语料，采集和独立评分各自封存。先核对官方题目与文件清单：

```powershell
.\.venv\Scripts\python.exe -B -X utf8 -m evals.longDS.longds_suite --root "$evaluationEvidenceRoot/longds" --collect-only
```

正式采集和恢复入口为 `python -m evals.longDS.run_longds`，独立评分入口为 `python -m evals.longDS.longds_judge`。各模块用 `--help` 查看参数。迁移沿用原 HTTP 装配、题面与评分协议，验收核对三个入口、HTTP 健康检查、封存题面及用量。旧检查点的源码摘要包含原路径，续跑使用当次冻结源码。原始预算和已执行记录见 [LongDS 长程分析基线](#longds-长程分析基线)。

## 正式发布验证

按 [REL 发布门禁](../devSpec/migration-release.md#3-完成检查表)，在目标 clean revision 上完成 `evals/` 公开数据集的 Product E2E。运行前确定适用用例、生产配置和通过判据，使用本页现行入口完成采集、评分和归档。通过发布判据后才可正式发布。

当前长程任务可使用上节 LongDS 的正式产品入口。每条发布用例都须满足 [Product E2E 资格](../devSpec/change-evidence.md#2-产品-e2e-的最低资格)。词法检索样本、仅收集用例及未走完整生产链的采集按各自证据类别记录。按 [EVM](../../evals/AGENTS.md#5-比较身份与归档)保留目标版本、配置、实际结果和校验和。

## 历史操作记录

以下内容保留清理前的运行方法、归档位置与发布口径。自建矩阵、晋级门禁和相关脚本已退出当前工作树。复查旧命令时使用对应历史提交。[清理前源码与运行说明](https://github.com/SkyLiberation/personalAgent/blob/b2c34d90e5476a78282b9884e8edc947509525af/docs/evals/04-running-and-release.md)


本文维护执行命令与归档方法；用例、实际成绩和发布证据状态由[用例盘点](02-current-case-inventory.md)维护。命令从仓库根运行，本机使用 `.venv` 解释器。

完整反馈历史候选的 task2 已按[Spec §9.19](../optimization/to_verify/analysis-goal-maintenance.md#919-保留完整核验历史后的-task2-全量连续运行)在 `.tmp/task2-feedback-history-full-20261103/` 一次连续执行并封存。实际请求 5 轮、交付 4 轮，第五轮容量失败；历史碰撞缺陷重新打开，当前不直接启动另一整轮或复用输出目录。结果见[记录 §38](../optimization/to_verify/verify_results/analysis-correctness.md#38-完整反馈历史候选的-task2-全量连续运行)。原命令以 `.venv/Scripts/python.exe -X utf8` 执行该目录的 `preflight.py`、`prepare_judge.py`、`launch.py prepare`、`launch.py run`；生成停止后运行 `audit.py`、`audit_split.py`、`audit_feedback_history.py`、`audit_regeneration.py`、`score.py` 与 `finalize.py`。审计明确保留缺失反馈失败，不将容量预拒绝当作 SDK 派发，也不重采评分覆盖原分。

核验反馈历史的确定性离线回放命令：

```powershell
.\.venv\Scripts\python.exe -X utf8 -m evals.product_baselines.runtime_feedback_history_replay --source .tmp/task2-full-regeneration-20261103/c-recovery --output .tmp/runtime-feedback-history-20261103/replay-04
```

该命令读取已 seal 的完整真实轨迹，经过现行历史投影和 Adapter，仅输出候选 SDK 请求及报告，新增模型／工具调用为 0；输出目录必须尚不存在，重验使用独立目录，不覆盖历史结果。它检验反馈完整性、时间顺序及对应稿件，不接续暂停中的 task2，不代表模型修复或语义收敛通过。验收与已执行范围见[固化记录](../optimization/completed/conversation-tool-history.md#2026-11-03补齐核验反馈与实际修复的历史顺序)。

先按改动范围选择入口，再设置独立归档根。定向实验中的日期、模型、预算和封存目录属于原比较身份；复用其方法时按对应规格重新声明身份，已有目录保持只读。

| 任务 | 入口 |
| --- | --- |
| 设置新运行输出、收集和执行矩阵 | [归档位置](#新运行的归档位置)、[收集矩阵](#收集当前矩阵)、[release selection](#执行机器-release-selection) |
| 诊断与横切机制检查 | [diagnostic selection](#执行-diagnostic-selection)、[横切套件](#执行横切验证套件) |
| baseline／target 配对与逐样本晋级 | [独立变更准入证据](#独立变更准入证据)、[晋级门槛](#逐样本晋级门槛与早停) |
| 判断目标版本发布资格 | [Release gate](#release-gate) |
| LongDS 采集、续跑与独立评分 | [长程分析基线](#longds-长程分析基线)、[Prompt 语言与评分配置](#prompt-语言与独立-longds-评分配置) |
| 重算 claim 历史指标 | [claim 指标持续评估](#claim-指标持续评估) |

## 新运行的归档位置

新运行按 [EVM 归档规则](../../evals/AGENTS.md#5-比较身份与归档)显式选择独立的 `.tmp/` 根目录。以下执行示例先在同一 PowerShell 会话设置变量；每次独立样本组重新生成根目录，子进程继承相同配置：

```powershell
$evaluationEvidenceRoot = ".tmp/evaluation-" + (Get-Date -Format "yyyyMMdd-HHmmss-fff")
$env:PERSONAL_AGENT_E2E_TRACE_DIR = "$evaluationEvidenceRoot/e2e"
$env:PERSONAL_AGENT_PRODUCT_EVIDENCE_DIR = "$evaluationEvidenceRoot/product"
```

读取历史证据时使用其原真实目录，不移动或改写旧归档。需要共享或发布的证据另封存到可访问位置；本节路径设置不改变证据类别、输入、评分或发布门槛。

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

该 selection 包含两类成本与证据边界不同的用例：

- 真实外部 Provider profile：`E16/E18/E19/E21`；
- 真实模型 + frozen provider 的 HTTP conformance：`CTX-001/GOV-001/RUN-001`。

`diagnostic` 不表示同一种证据等级。已撤回的 `LT` scripted Investigation 节点不在现行矩阵中；旧结论只读取 checksum 有效的历史归档。

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

## Release gate

```powershell
uv run python -m evals.e2e_quality.release_gate `
  --trace-root "$evaluationEvidenceRoot/e2e"
```

历史 gate 检查：

1. catalog 计算为 `release_eligible`；
2. archive checksum 有效；
3. manifest commit 等于目标 revision；
4. archive 和目标工作树 clean；
5. test outcome 为 passed 且存在 trace；
6. capability 所需 evidence id 均 trusted。

gate 还会 fail closed 拒绝缺少 `UserOutcomeContract`、错层或使用 test double 的产品声明。重叠关系由 `evidence_audit` 输出；它不会只因共享断言就删除仍有独有不变量的用例。即便 trusted，也只证明该用户结果在固定 profile/revision 成立，不证明架构最初有产品必要性。

## 当前发布状态

当时的发布资格由上节历史 Release gate 判断，实际运行与证据限制见[用例盘点](02-current-case-inventory.md)。历史门禁曾以 `target_revision_dirty`、`missing_same_revision_passing_trace` 拒绝发布。现行要求见[正式发布验证](#正式发布验证)。

## LongDS 长程分析基线

LongDS 采集进程显式关闭前置意图分类，按实际部署配置运行目标和回答核验。有效开关随采集配置封存。

2026-10-28用户要求切回MiniMax后重新执行英文task2，使用当前冻结源码和新空对话；评分器独立保持MiMo Pro。预声明、费用与停止条件见[切回MiniMax规格](../optimization/to_verify/prompt-language-selection.md#12-切回-minimax-后重新执行-task22026-10-28)。先准备独立身份，再运行；已有身份和捕获禁止覆盖。启动器内仍调用正式`run_longds.baseline`，生成停止且封存后自动评分新答案。

```powershell
.\.venv\Scripts\python.exe -B -X utf8 .tmp/task2-minimax-20261028/full.py prepare
.\.venv\Scripts\python.exe -B -u -X utf8 .tmp/task2-minimax-20261028/full.py run
```

当前执行归档为`.tmp/mt28/`，`worker.json`区分生成、评分与已停止；`final.json`产生后才有本次交付和评分汇总，不能把进程启动当作测试通过。

2026-10-29原段在第25轮额度拒绝后，按用户要求接续第25—34轮。使用同一冻结源码、原许可及完整canonical状态，旧24轮与4/24评分只读保留；判据由同一规格的接续小节拥有。执行一次prepare后才能run，新归档为`.tmp/mr29/`；生成封存后只评分新答案，不为恢复重设原任务额度。

```powershell
.\.venv\Scripts\python.exe -B -X utf8 .tmp/task2-minimax-recovery-20261029/resume.py prepare
.\.venv\Scripts\python.exe -B -u -X utf8 .tmp/task2-minimax-recovery-20261029/resume.py run
```

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

用例与预算由[LongDS 长程数据分析 Spec](../optimization/to_verify/longds-analysis.md#longds-长程数据分析-spec)拥有，结果契约为 `LONGDS_OUTCOME`。准备命令不调用模型、不执行分析程序；来源目录为已核查的固定版本原件，输出目录必须尚不存在。

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

用户授权的无 claim／核验流程使用相同采集入口，运行前显式设置 `$env:PERSONAL_AGENT_ANSWER_RESULT = '{"writer":"direct"}'`，并通过 `$env:PERSONAL_AGENT_FEATURE_FLAGS_CONFIG` 选择已声明的独立 TOML，输出另取尚不存在的目录。目标和结果核验的取值与适用范围由[实验组 1](../ablation/experiment.md)拥有；关闭任一核验记录为 `unverified_flow_capture`、`release_eligible=false`，不计完整 Product E2E。默认对照使用默认全开配置；同对话与同 run 不能换装配，后续 claim 消融使用独立对话并固定两项核验开关，实际确认 claim 机制被消费。历史 `.tmp/answer-result-modules-20261023/l1-direct-flow` 的旧 `verification=none` 原件和成绩不改写，原预算与判据由[可替换回答模块与无核验流程验证](../optimization/to_verify/verify_results/longds-analysis.md#2-可替换回答模块与无核验流程验证)拥有。

```powershell
.\.venv\Scripts\python.exe -B -X utf8 -m evals.product_baselines.longds_judge score --judge-root .tmp/longds-implementation-20261023/judge --source-directory .tmp/longds-design-20261023 --materials .tmp/longds-implementation-20261023/materials --capture .tmp/longds-implementation-20261023/l1-python-target --name l1-python-target
```

本次额度、未知消费和真实 Python 执行阶段的局部诊断源码随 `.tmp/longds-implementation-20261023/` 独立结果封存；不以标准任务成功率报告它们，也不覆盖独占目录。权限／原件／执行恢复回放的模型和新增执行均为 0；声明的 Provider 响应交付丢失只作用于独立控制分支，正式生成轨迹保持原输入。

MiMo 的两轮实际配置、结果和后续预算见 [切回 MiMo 的长任务验证](../optimization/to_verify/verify_results/longds-analysis.md#3-切回-mimo-的长任务验证)。新启动器读取当前 Settings 和既有凭据，不能复用显式指定 DeepSeek 的旧实验启动器；两轮独立身份已封存，禁止覆盖。完整任务须显式指定 `--purpose target --user-turns 36 --task-token-limit 60000000 --stop-after-checkpoint`，沿原固定镜像与新的输出目录启动；任务额度同时供许可、观察停止及归档使用，省略仍为原 20M，L1 拒绝改额度。只有第 17 轮真实完成并封存后才按该开关退出。

恢复使用 `--recovery-checkpoint <完整L2归档>/checkpoint-17`，同时指定 `--purpose target --user-turns 36` 及新的 `--output`，沿用原模型配置。恢复继承原授权文件、原额度及已发生消费，显式传入不同额度在新增调用前拒绝；不能提供新 `--python-image-id`、`--docker-endpoint` 或重复指定 `--stop-after-checkpoint`。检查点须有完整 seal、相同源码／配置、原第 17 轮实际消息及未过期许可。本次以同轨迹后半段覆盖 L3，不再重复一次第 18—36 轮；当前尚无真实检查点或完整成绩，CLI 可加载不代表 L3 通过。

MiniMax low 的新完整流程按 [MiniMax low 的完整流程验证](../optimization/to_verify/verify_results/longds-analysis.md#4-minimax-low-的完整流程验证)执行，启动器为 `.tmp/minimax-longds-e2e-20261023/full-launch.py`，收尾为同目录 `complete-longds.py`，后者绑定启动身份中的真实 Python PID。先用 `scoring_admission.py` 对既有成功／503 两份完整采集做零模型准入回放：只把实际 HTTP 成功且 `disposition=answer` 的原回答送入既有评分器，失败正文保留未评分，消费未知则停止评分。模型、端点和 thinking 从当前配置读取，原 MiMo 启动器仅保留历史身份，不用于新任务。

2026-10-24用户调为 medium 后，完整流程使用新身份 `.tmp/minimax-medium-longds-e2e-20261024/`，按 [MiniMax medium 的完整36轮验证](../optimization/to_verify/verify_results/longds-analysis.md#5-minimax-medium-的完整36轮验证)执行。当前配置和实际 SDK 已核对；新 full-launch.py 仍调用正式 baseline 完成1—17及原许可恢复18—36，新 complete-longds.py 绑定该次实际PID后才收尾。旧 low 启动器及归档不修改，新的观察器删除已退役 Args.program_ref 统计读取；评分仍由原官方 Judge 和共享预算拥有，不给生成侧反馈。

用户取消用量未知停止线后的完整运行由 [用量未知不再单独停止，并继续完整验证](../optimization/to_verify/verify_results/longds-analysis.md#6-用量未知不再单独停止并继续完整验证)拥有，独立目录为 `.tmp/usage-nonblocking-longds-20261024/`。执行 `python -B -X utf8 .tmp/usage-nonblocking-longds-20261024/full-launch.py`；收尾脚本为同目录 `complete-longds.py --launcher-pid <该次真实PID>`。未知用量继续记录，不阻止生成、检查点、恢复或合法答案评分；额度阈值按已知消费执行，未决执行及原授权／截止保持。上方 low／medium 原档案的未知停止线只解释其历史运行，不用于本次启动。

### task2 Context 位置与自然语言展示（2026-10-27）

首批范围和预算由[SEM §9](../optimization/to_verify/longtask-semantic-consistency.md#9-context-首批实施与真实用例观察)拥有，结果由[验证记录](../optimization/to_verify/verify_results/longds-analysis.md#11-context-首批实施与接口迁移)拥有。完整真实阶段从封存 SDK 进入当前 Model Adapter；三组各10个初始决策，不执行生成程序，也不把初始提议当最终正确率。

```powershell
.\.venv\Scripts\python.exe -B -X utf8 -m evals.product_baselines.requirements_context_replay prepare --output <新准备目录>
.\.venv\Scripts\python.exe -B -X utf8 -m evals.product_baselines.requirements_context_replay run --prepared <准备目录> --group baseline --output <新基线目录>
.\.venv\Scripts\python.exe -B -X utf8 -m evals.product_baselines.requirements_context_replay run --prepared <准备目录> --group position --output <新位置目录>
.\.venv\Scripts\python.exe -B -X utf8 -m evals.product_baselines.requirements_context_replay run --prepared <准备目录> --group natural --output <新自然语言目录>
```

正式采集仍走 `run_longds baseline --purpose target`，现可显式选2至原总轮数的连续前缀；baseline仍固定两轮。收窄任务额度须有固定 Python 环境及对应授权，保留原材料全部轮数，未执行量单列。本轮实际启动脚本为 `.tmp/criterion-context-implementation-20261027/launch-prefix.py`：先读取本机凭据，再用 `PYTHON_DOTENV_DISABLED=1` 固定 direct/none、10M/40次每run预算，防止再次加载 `.env` 覆盖。首试路径过长，后继使用 `.tmp/cc27p` 短根及扣除首试后的任务额度；所有已有根保持只读。

LongDS Judge 现经 `build_provider_policy` 投影请求，配置身份增加 `request_projection=provider-policy-v1`，实际不发送 temperature；旧资格与旧分数保持原身份。新根先运行 `qualify`，再运行 `score`，两者须用相同 `--token-limit`。本轮使用原官方正例和已封存真实错误首答重新取得资格，具体命令由 `.tmp/criterion-context-implementation-20261027/launch-judge.py` 固定，不为生成侧提供答案。后续批次须显式提供当前 `--qualification` 和匹配的 `--judge-token-limit`，启动前验证；旧批次命令仅解释当时执行，不能沿用旧资格启动新评分。

#### task2 全34轮及既有基线复用

按[SEM §10](../optimization/to_verify/longtask-semantic-consistency.md#10-task2-完整前后表现验证)只新增候选完整生成，用户明确要求不重跑旧基线。旧1—20轮及恢复21—34轮只读；其原始3/34保持，新协议复评另记。冻结代码根 `.tmp/cf27/code`，完整采集 `.tmp/cf27/c` 使用新60M许可和原每run配置，避免Windows长路径及共享工作树漂移。实际执行命令如下，已有输出目录不可覆盖重跑：

```powershell
.\.venv\Scripts\python.exe -B -X utf8 .tmp/task2-context-full-20261027/launch.py prepare
.\.venv\Scripts\python.exe -B -X utf8 .tmp/task2-context-full-20261027/launch.py run
.\.venv\Scripts\python.exe -B -X utf8 .tmp/task2-context-full-20261027/score.py old
.\.venv\Scripts\python.exe -B -X utf8 .tmp/task2-context-full-20261027/score-revised.py qualify
.\.venv\Scripts\python.exe -B -X utf8 .tmp/task2-context-full-20261027/score-revised.py old-missing
.\.venv\Scripts\python.exe -B -X utf8 .tmp/task2-context-full-20261027/resume.py
.\.venv\Scripts\python.exe -B -X utf8 .tmp/task2-context-full-20261027/score-revised.py new-prefix
.\.venv\Scripts\python.exe -B -X utf8 .tmp/task2-context-full-20261027/score-revised.py new-suffix
.\.venv\Scripts\python.exe -B -X utf8 .tmp/task2-context-full-20261027/compare.py
.\.venv\Scripts\python.exe -B -X utf8 .tmp/task2-context-full-20261027/resume-quota.py --check
.\.venv\Scripts\python.exe -B -X utf8 .tmp/task2-context-full-20261027/resume-quota.py --run
.\.venv\Scripts\python.exe -B -X utf8 .tmp/task2-context-full-20261027/score-revised.py new-final
.\.venv\Scripts\python.exe -B -X utf8 .tmp/task2-context-full-20261027/compare.py --include-quota-recovery
.\.venv\Scripts\python.exe -B -X utf8 .tmp/task2-context-full-20261027/audit-context.py
```

`old`只读已有答案、不生成分析；原300K评分在31轮后预算停止，既有判断保留。`score-revised.py`重新取得新预算身份资格，只补旧32—34轮；其统一1M账本发送前累计旧247,988及全部新消费，不重置费用。配置除总预算外的语义摘要必须一致，每轮保留来源配置。首段在第21轮摘要协议失败后20轮已真实停止封存；按Spec10.1以相同冻结源码、原许可和旧消费做一次恢复至.tmp/cf27r/c。`new-prefix`只评分原20轮，`new-suffix`须在后段进程停止及seal通过后评分21—34并汇总；生成侧不读取评分、参考代码或答案。34轮逐项比较、成本、失败与未执行量由[完整验证记录](../optimization/to_verify/verify_results/longds-analysis.md#12-task2-完整前后验证)拥有，不将两条独立随机轨迹解读为严格因果消融。

恢复段在24轮因Token Plan额度上限停止，仅21—23有答案；`new-suffix`只评分这三份实际答案。`compare.py`核对封存原件、配置和费用，保存前23轮配对结果。17:44核实额度恢复、原许可有效后执行`resume-quota.py --run`，新段`.tmp/cf27q/c`携入全部既有消费，从24轮继续。该段停止并封存后，`new-final`只评分新答案，不重评前23轮，统一1M评分账本不清零；`--include-quota-recovery`核对三段真实消息连续性及来源，输出独立`comparison-complete.json/.md`和`new-score-complete.json`，保留原阶段文件。未交付或未评分仍为空值，完整状态按实际34轮判定。

## 模型 HTTP 诊断的真实阶段回放

MiMo 工具流式接入使用[独立传输规格](../optimization/model-provider-transport.md#2026-10-23-mimo-工具流式接入规格)。局部入口 `python -m evals.product_baselines.mimo_tool_stream_replay --output <尚不存在的目录>` 读取固定历史完整 SDK 阶段，只以本机 SSE 服务替代外部响应，不调用真实模型或工具。新完整轨迹由 `.tmp/mimo-tool-stream-20261023/full-launch.py` 调用上方同一 LongDS 正式入口，收尾脚本 `complete-longds.py` 等待真实生成退出、校验各段及恢复身份，再以新 Judge 名称评分；原失败轨迹和一次未知消费保持。

[传输诊断规格](../optimization/to_verify/model-provider-diagnostics.md#本轮验收与实施顺序)固定三例及真实输入，执行入口如下；`before-source` 指向修改前完整源码快照，`capture` 指向原 LongDS 归档的 SDK 目录，输出目录必须尚不存在。

```powershell
.\.venv\Scripts\python.exe -m evals.product_baselines.model_transport_diagnostics --capture .tmp/research-mimo-longds-20261023/l2-prefix-17/sdk --before-source .tmp/mimo-transport-diagnostics-20261023/before/src --output .tmp/mimo-transport-diagnostics-20261023/offline-v5
```

入口只把外部 HTTP 服务替换为回环故障／正常响应服务，对两组子进程设置相同 `NO_PROXY=127.0.0.1`；生产配置保持。该 Offline Eval 不启动模型生成、工具执行或原任务恢复，不覆盖预算准入、真实 MiMo 根因和完整产品结果；原档案及已经存在的输出目录不得覆盖。

## Provider 配置与参数封装回放

[适配规格](../optimization/completed/model-provider-configuration.md)固定两个完整历史主链阶段及来源 checksum；`before-source` 是基线 `5e0963e` 的完整 Python 源码目录，`manifest` 同时绑定请求与响应的路径和 SHA-256，输出目录必须尚不存在。

```powershell
.\.venv\Scripts\python.exe -m evals.provider_diagnostics.model_provider_configuration --before-source .tmp/model-provider-configuration-20261026/before-src --manifest .tmp/model-provider-configuration-20261026/sources.json --output .tmp/model-provider-configuration-20261026/replay-final
```

入口通过真实 OpenAI SDK 和本机 HTTP 服务对照基线与候选的完整主链请求、响应投影，以及 Graphiti/LangExtract 的参数接入；后两项是配置边界检查，不是新的业务真实阶段。配置反事实经过 `Settings.from_env()` 与现有 Adapter，核对 provider 选择、实际模型绑定、显式空对象及网络前拒绝。原始输入、源码 checksum、候选 patch、SDK 请求和报告均保留，零付费模型和工具执行，不进入产品 E2E 分母。

独立策略重构使用[策略记录](../optimization/completed/model-provider-extensibility.md)的已集中参数源码快照，避免把上一轮参数修正混算为本轮收益：

```powershell
.\.venv\Scripts\python.exe -m evals.provider_diagnostics.model_provider_configuration --before-source .tmp/model-provider-policy-20261026/before-src --manifest .tmp/model-provider-configuration-20261026/sources.json --output .tmp/model-provider-policy-20261026/replay-final --baseline-kind consolidated
```

该模式保留原 23 项，再核对 MiMo 完整工具阶段的流式 SDK 出站、配置选择的额外策略及未知 ID 在发送前拒绝，共 26 项。新增策略实验保存新实现和注册内容，并核对接入前后公共请求器、kernel 契约及内置策略的源码哈希不变；整组还检查生产及回放源码在验证前后一致。它证明参数行为保持和扩展约束，不证明真实服务接受性或模型语义。

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

历史压缩的非思考局部回放按[主循环 NS-1／2／3](../optimization/to_verify/conversation-loop-boundaries.md#非思考摘要的局部修正2026-10-22)执行。先运行 `python -m evals.provider_diagnostics.history_compaction --prepare --output-dir .tmp/ctx-compact-no-thinking-20261022` 完成零 HTTP 原输入对照，再对同目录使用 `--run` 执行一次旅程；使用本地 `.venv` 解释器，来源 DeepSeek 凭据只从既有受信绑定读取。本次一次旅程已结束，生成／消费／恢复及摘要语义限制见[当前成绩](02-current-case-inventory.md#2026-10-22-非思考摘要的局部验证)。既有目录禁止重跑；后续新执行须有新的授权、归档和预声明，不运行单元测试或完整产品 E2E 来补本例次数。

## Python结果分析的局部Offline回放

当前Agent能力验收按[当前范围与历史文件交付的关系](../optimization/to_verify/research-experiment-protocol.md#5-当前范围与历史文件交付的关系)不再打包或下载：正式采集只POST自然任务、GET当前Trace并封存SDK／执行／费用及适用安全观察；完成审计核对实际SubmittedFinal和Final，不要求report文件、manifest、ZIP、downloads/index或外部CLI。旧文件版封存按原代码身份读取，历史资格／交付命令不能作为当前能力门槛。

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

`RETRIEVAL-EXPERIMENT-001`（E1）与 `RETRIEVAL-EXPERIMENT-PROGRAM-001`（P1）的阶段 0 正式入口及预算由[唯一 Spec](../optimization/to_verify/verify_results/research-experiment.md#32-完整落地-implementation-plan)拥有。节点采用真实 Web 子进程、生产模型与 `POST /api/conversation/turn`，原件只经 Artifact owner 准备，不摄入知识，也不向模型提供预生成排名、候选代码或 test 标注。当前独立准入节点不加入默认 release 分母。

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

研究采集器 `run_retrieval_acceptance` 及评分资格入口保留 Settings 的实际 timeout/max_retries，并通过原子进程环境传入。任务总时间与单请求超时分开；新正式准备必须显式给出 `--run-timeout-seconds` 和 `--max-execution-seconds`，同一部署供Runtime、环境附件和采集监督读取。下一次1小时验收两项均设3600；轮数／工具／委派／tokens使用既有 `PERSONAL_AGENT_INTERACTION_MAX_MODEL_TURNS`、`PERSONAL_AGENT_INTERACTION_MAX_TOOL_CALLS`、`PERSONAL_AGENT_INTERACTION_MAX_AGENT_CALLS`、`PERSONAL_AGENT_INTERACTION_MAX_TOTAL_TOKENS`，此前零模型预算切片使用64／256／4／2000000；用户在调研后已选下一例累计20000000 tokens，其他为64／256／4；仅用于独立准备身份，旧配置原件保持，见同节的累计Token调研。现有dotenv会覆盖外层环境变量；需要覆盖时，先加载既有配置，再设置本例值并使用已有 `PYTHON_DOTENV_DISABLED=true` 进入入口，实际归档一致后才运行。新配置形成独立准备身份，具体实施与验证状态见[Spec预算切片](../optimization/to_verify/verify_results/research-experiment.md#长任务预算与诊断范围)。旧T0／v1／v2的120秒评测profile和旧900秒运行保留原配置身份，不与新身份混算。structured／openai的实际单次超时由每次 `configuration.json` 拥有，不能将历史480／30当成任务总时限。

正式采集监督绑定首份真实Journal截止，启动健康检查和Journal出现前的入口等待各最多30秒，收尾最多30秒，不增加模型额度；停止及终态核对实际Web解释器和包装进程，HTTP超时本身不算停止。旧T0节点仍沿原900秒监督身份。原始用户结果缺交付时保留pytest失败；环境／模型异常或未知生成产物不能当能力准入。初始材料、实际SDK输入／输出、完整源码身份、独立归档及用户结果分开保存；基线缺项检查不能接受完整target，后续完整评分资格及复算／复现仍按Spec执行。

研究采集器消费 Settings 已有的 `STRUCTURED_MODEL_CAPACITY`、`OPENAI_MODEL_CAPACITY` JSON 配置，分别绑定该路径的实际 model／provider_host。任一路径显式配置时，两条都须提供有效 profile；缺一或身份不符会在准备／业务连接前拒绝。两条都未配置时保留原已核 Flash 缺省。更换模型须先核对公开规格、实际 endpoint 可用性及完整生效配置，不沿用其他模型的容量或评分资格；dotenv 的实际加载结果必须进入每次配置原件，不能仅以外层环境变量推定生效。新 Pro 准备的依据及准入边界见[唯一 Spec](../optimization/to_verify/verify_results/research-experiment.md#新模型配置的正式评测准备)。

当前设计先完成[初步闭环](../optimization/to_verify/research-experiment-protocol.md#1-当前先完成的闭环)，claim／语义 verifier 及新评分资格后置。`initial_closure`、SubmittedFinal／Manifest v2 绑定已由新 DeepSeek E1 到达真实交付、下载、复算及复现；独立审读发现错例分析错误，完整用户验收未通过。初步机械结果及语义审读单独记录，不使用下面的 target 准入冒充已取得完整语义资格；首次发布故障 F3 仍未覆盖。

2026-10-22 的当前版本 E1 已按[当前版本完整流程 E2E（2026-10-22）流程计划](../optimization/to_verify/verify_results/research-experiment.md#43-当前版本完整流程-e2e2026-10-22)执行一次并关闭：模型后续Python调用重复漏必填inputs，流程未到冻结、test、清单v3及下载复现；语义未评分，详见[本轮结果](02-current-case-inventory.md#2026-10-22-当前版本完整流程-e2e-失败)。归档 `.tmp/research-e2e-flow-20261022/` 已使用，不得重跑。F1启动器已对齐服务端进程记录参数并复用ActualWebProcess监督实际解释器，限定授权拒绝复验通过，原失败保持。

前一次 Pro E1 的 480 秒截止与新 DeepSeek E1 的实际结果均保留于[评测盘点](02-current-case-inventory.md#2026-10-20-检索实验研究能力准入)。新归档汇总只绑定 auditor 实际消费的来源：正式 GET 已绑定 Trace 时，即使提供备用 `--trace-seal` 也不将它误作消费原件；只有正式 GET 未取回时才消费该 seal。旧封存与采集源码身份保持，不因 reader 修正重跑模型。

后置的完整研究采集 `--phase target` 仍必须提供真实完成的 `--qualification <目录>` 及 `--qualification-review <独立准确性审读原件>`；入口会在任何业务连接前只读核对当前 grader identity、18 次判断、原请求／响应／引用、费用与逐关系审读，不接受单个分类达标标签。来源审读如实区分人和独立 agent；审读与评分原记录分别封存，Admission 绑定两者摘要。资格准备不接收这两个参数。只读核对已完成归档：

```powershell
.\.venv\Scripts\python.exe -B -X utf8 -m evals.product_baselines.run_retrieval_grader_qualification verify --qualification <真实资格归档目录> --accuracy-review <独立准确性审读原件>
```

该命令不发模型请求；当前尚无合格完整资格归档。四个真实 CLI 拒绝已验证，接受分支待真实组，不能构造假通过档替代。

资格材料构造入口为 `python -m evals.product_baselines.retrieval_qualification_materials --selection <独立审读选择表> --output <新目录>`。输入必须绑定实际已结束的 E1／P1 preparation、正式完整下载、原排名审计和干净 CLI 复现；缺材料会拒绝，不人工补稿。构造成功后才用原 qualification `collect`／`run`；来源和准确性审读的契约由[资格材料与审读的实现契约](../optimization/to_verify/verify_results/research-evaluation-and-delivery.md#5-资格材料与审读的实现契约)拥有，成功路径仍待真实材料。

已停止采集的机械审计入口为 `python -m evals.product_baselines.retrieval_capture_audit --preparation <preparation.json> --capture <capture-result.json> --trace <最终Journal.json> --output <新报告.json>`；正式 GET 未取得 Trace 时另须 `--trace-seal <同run原seal.json>`，不能以未绑定的后读 Journal 补原 HTTP。只输出实际物理费用、终态及 `missing／present_unscored`，不代替语义、资格、独立复算／复现或产品 passed。

缺交付汇总入口为 `python -m evals.product_baselines.retrieval_acceptance_result --preparation <preparation.json> --capture <capture-result.json> --trace <最终Journal.json> --output <新报告.json>`，同样按需提供 `--trace-seal`。它复用机械审计，只有绑定 Journal 明确缺 answer Final 或必要交付角色时才报告用户结果失败，保留原阶段、`not_scored` 与 known／unknown 费用；仅入口／下载取证不足不能判业务失败。完整交付会明确拒绝进入本路径，完整 target 的评分与全证据汇总仍待准入；不能把该报告当产品通过。v6／v7 两份真实归档回放与跨身份拒绝已验证，均未调用模型。

知识快照独立入口为 `python -m evals.product_baselines.retrieval_knowledge_snapshot --preparation <preparation.json> --output <新快照.json>`，仅作当前主体真实只读取证。正式 target runner 已在进程开始前／实际停止后装配 before／after，含失败原件一起封存；资格门禁不满足时不会读取数据库或启动模型。独立命令不能补造旧 run 的 before，知识零写入仍须结合完整写入口审计，详见[同一任务证据汇总](../optimization/to_verify/verify_results/research-evaluation-and-delivery.md#6-同一任务的最终证据汇总)。

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

2026-08-20 的有效样本组、归档和成本见[用例盘点](02-current-case-inventory.md#1-conversation-与-knowledge)。原生产变更门槛为至少 `3/15` 次 Plan 语义失败且覆盖至少两类场景，当轮未达到。只有新的用户契约、独立线上问题或模型、服务提供方及交互契约变化时才预声明新组，不能追加样本直到碰到原阈值。

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

有效 v2 消融与 draft-step 绑定 target 的原归档、逐类结果和失败见[用例盘点](02-current-case-inventory.md#1-conversation-与-knowledge)。候选未通过预声明 `>=14/15 delivered`，已撤回；后续复核须有新的比较身份，不把旧命令或旧结果解释为已准入优化。

### PLAN-REPLAN-001 义务修订 baseline

有效 v3 使用默认审阅模式，首轮必须真实取得官方资料并返回仍有 pending step 的 Plan；Web 重启后用户以自然业务语言
否定候选、撤回并新增结果或收紧验收，最终答案必须修订同一 Plan、完成新义务且不保留撤回结果：

```powershell
$env:PERSONAL_AGENT_PLAN_REPLAN_001_EVIDENCE_ROLE = "baseline"
$env:PERSONAL_AGENT_PLAN_REPLAN_EXPECTED_TRANSPORT = "json_object"
uv run pytest -q -s `
  evals/product_baselines/test_plan_replan_001_obligation_revision.py
```

2026-08-20 的有效样本组、成本和失败归因见[用例盘点](02-current-case-inventory.md#1-conversation-与-knowledge)。可归因计划修订失败未覆盖第二类场景，未达到 A1，当轮不执行生产消融。代码身份变化、零工具首轮和 `auto` 模式的历史归档只作脚手架诊断，不与有效样本合并。

### PLAN-COMP-001 完成真实性 baseline

该用例固定 Structured Outputs 事实正确性、MCP Tool result 的 exactly-once/完整交付、durable execution 的业务通知
零重复三个边界，每类五次。grader 直接检查最终回答是否给出用户要求的章节、官方 URL、否定性边界和无保留强结论：

```powershell
$env:PERSONAL_AGENT_PLAN_COMP_001_EVIDENCE_ROLE = "baseline"
$env:PERSONAL_AGENT_PLAN_COMP_EXPECTED_TRANSPORT = "json_object"
uv run pytest -q -s `
  evals/product_baselines/test_plan_comp_001_completion_truthfulness.py
```

2026-08-20 的有效样本组、成本及唯一错误成功见[用例盘点](02-current-case-inventory.md#1-conversation-与-knowledge)。当轮未达到跨两类 A1 门槛；代码身份变化与错误 grader 的历史归档只作诊断，不参与门禁或有效结果合并。

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

## 研究评分器输出额度

输出额度的修复机制与正式消费者配置由[评分输出预算固化记录](../optimization/completed/research-grader-output-budget.md)拥有，历史截断和预算恢复结果见[当前盘点](02-current-case-inventory.md#2026-10-01-独立评分器输出预算恢复)。原 E2E、评分反例和产品成功分子保持原身份；预算恢复与定向评分资格分别报告，不替代完整产品交付或发布证据。

## Prompt 语言与独立 LongDS 评分配置

Prompt语言与生成／评分模型分别选择，配置入口由[环境说明](../env.md#prompt-语言与独立-longds-评分)拥有。默认中文；英文实验通过typed Settings或独立启动器在配置加载后显式选择`en`，并绑定源码、配置及材料身份。原官方英文题面保持，不能以生产Prompt翻译为由翻译题目。

LongDS CLI从独立`LONGDS_JUDGE_*`配置构建评分器，首次替换模型／端点必须用新账本重新资格；`--token-limit`在资格和评分命令中相同，`--qualification`只接受配置摘要一致的有效封存。完整同组评分预算累计所有子目录，不按答案组重置。

```powershell
.\.venv\Scripts\python.exe -B -X utf8 -m evals.product_baselines.longds_judge qualify --judge-root .tmp/<新Pro账本> --source-directory .tmp/longds-design-20261023 --materials .tmp/longds-implementation-20261023/materials --capture .tmp/longds-implementation-20261023/l1-baseline --token-limit 1000000
.\.venv\Scripts\python.exe -B -X utf8 -m evals.product_baselines.longds_judge score --judge-root .tmp/<同一Pro账本> --source-directory .tmp/longds-design-20261023 --materials .tmp/ls25/t01/materials --capture .tmp/<已停止封存的完整task2> --name <全新评分组> --token-limit 1000000
```

当前输入诊断入口为`evals.provider_diagnostics.prompt_language_actual_inputs`：显式传入`--capture`、`--inventory`、`--current-capture`及新输出目录，消费完整真实SDK与当前Schema／动作工厂，零模型调用。它不验证新模型语义；双语、完整task2及同评分器比较结果见[验证记录](../optimization/to_verify/verify_results/prompt-language-mimo.md)。

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


## criteria 与目标核验的连续阶段回放

2026-10-29 用户已停止历史稿回放，当前执行[空对话六轮](#空对话六轮-criteria-与回答验证)。原阶段的中英文第六轮两条诊断链及脚本封存于 `.tmp/ci29/`，不再保留正式执行入口或重复计划；不得把旧测试回答与条件输入当前六轮模型。

## 空对话六轮 criteria 与回答验证

2026-10-29 按用户更正及 [SEM §7.4](../optimization/to_verify/longtask-semantic-consistency.md#74-从空对话运行六轮并累积业务-context)，停止上节旧稿回放。本次启动脚本只用原题及输入 CSV，空会话、全新 Journal／Artifact，不恢复旧运行；Runtime 使用 `direct+none`。新条件、执行和回答逐轮真实累积，评分仅在采集后进入独立评测侧。

```powershell
.\.venv\Scripts\python.exe .tmp/c629/launch.py prepare
.\.venv\Scripts\python.exe .tmp/c629/launch.py run
```

`prepare` 已执行后不得重复覆盖其源码身份；`run` 使用封存代码、原通用 Docker 镜像和正式 HTTP 采集器，仅连续前六轮。任务总额度 9,854,351 tokens，另保留此前诊断 145,649 的累计费用；每轮原 40 决策、3600 秒及已配置容量保持。该配置属于 unverified flow capture，不替代独立核验验收或发布证据。实际结果见[验证记录 §14](../optimization/to_verify/verify_results/analysis-correctness.md#14-空对话前六轮与跨调用-context)。

本组已完成，后处理命令为：

```powershell
.\.venv\Scripts\python.exe .tmp/c629/audit.py
.\.venv\Scripts\python.exe .tmp/c629/score.py
```

`audit.py` 零模型核对新问答、criteria 及实际请求；`score.py` 已执行，不重复覆盖原评分目录。评分在采集封存且服务退出后独立进行，使用配置摘要一致的 `.tmp/em27/j/qualification`，内层 token limit 1M 与资格身份一致；当前六轮另以统一 300,000 tokens 外层额度按请求预留并计费，不按轮重置。评分原件位于 `.tmp/c629/j/`，汇总为 `.tmp/c629/score-report.json`；运行中不得把该侧材料传回 Agent。

## 合并理解与回答后的空对话六轮

2026-10-30 按 [SEM §7.5](../optimization/to_verify/longtask-semantic-consistency.md#75-独立分析由主模型直接理解并作答)，当前独立 Python direct 分析不再调用 Intent 或输出 criteria。新运行仅使用原题及 CSV，空对话、新主体与 Journal；逐轮消费本次真实回答和执行结果，Runtime 为 `direct+none`。源码封存后不在运行中修改 Prompt，不将旧稿、评分或参考答案交给 Agent。

```powershell
.\.venv\Scripts\python.exe -X utf8 .tmp/v630/launch.py prepare
.\.venv\Scripts\python.exe -X utf8 .tmp/v630/launch.py run
```

先等待 prepare 正常完成，确认 identity.json 已封存，再执行 run。prepare 不能重复覆盖原身份。首段 `.tmp/u630/` 因跨轮读取观察未继承而主动停止，保留 804,633 已知 tokens／未知 1；从同一 10M 总额扣除已知并为未知预留 1M，本次完整新六轮额度为 8,195,367。固定原 MiniMax adaptive／medium、32,768 输出、原容量与 Docker 镜像，每轮 3600 秒；新空对话不消费首段回答。当前采集保持 unverified 身份，不代表已取得语义核验或发布资格。

```powershell
.\.venv\Scripts\python.exe -X utf8 .tmp/v630/audit.py
.\.venv\Scripts\python.exe -X utf8 .tmp/v630/prepare_judge.py
.\.venv\Scripts\python.exe -X utf8 .tmp/v630/score.py
```

audit 必须在六轮采集结束后检查 Context、无 criteria 调用和原生配对。prepare_judge 零模型核对原有效评分资格及配置，不送入旧答案；score 只在采集封存并退出后执行，当前总额度另限 300,000 tokens，沿与资格一致的内层 1M 身份，统一预留并计费。不得重复覆盖原评分组。结果与比较边界由 SEM 的验证记录拥有。

## 工具历史布局优化后的空对话六轮

2026-10-30 按 [SEM §7.6](../optimization/to_verify/longtask-semantic-consistency.md#76-工具历史按原轮次续接并精简发送包装)，新身份 `.tmp/h630/` 验证跨用户轮次原生交换及单份引用展示。`offline.py` 仅投影 v630 六个完整真实首步输入，零模型，不将该历史送入新运行。正式生成另从空对话读取原题及 CSV，`direct+none`、模型、参数和原镜像保持；评分仍在采集退出封存后独立进行。

```powershell
.\.venv\Scripts\python.exe -X utf8 .tmp/h630/offline.py
.\.venv\Scripts\python.exe -X utf8 .tmp/h630/launch.py prepare
.\.venv\Scripts\python.exe -X utf8 .tmp/h630/launch.py run
.\.venv\Scripts\python.exe -X utf8 .tmp/h630/audit.py
.\.venv\Scripts\python.exe -X utf8 .tmp/h630/qualify.py
.\.venv\Scripts\python.exe -X utf8 .tmp/h630/score.py
```

prepare 与 run 顺序执行，不覆盖原身份；当前 prepare、正式采集均只运行一次，复核使用已生成原件。生成上限 6M tokens，评分原 300K 外层限额因旧资格丢失、必要正反样例最坏预留 308,610，在付费前一次调整为 400K，资格与六轮评分共用账本；内层 1M 配置及判据不变。qualify 已执行且通过，不覆盖重跑；原启动失败、零调用准备错误和旧计划均保留。旧费用和未知消费另计。检查实际原问答、跨轮调用及推理保真、配对和轮次位置、引用原文、无 criteria／核验调用、工作树与冻结源码；分别报告用户结果和组织检查，不把当前 system 变短当作总请求开销降低。压缩未触发时单列未验证。

## 用户原话与持续约束优化后的空对话六轮

2026-10-30 按 [SEM §7.8](../optimization/to_verify/longtask-semantic-consistency.md#78-用户原话集中呈现并持续约束主决策)，当前候选每次主决策追加从本次真实会话派生的用户原话区，并更新主模型的条件延续与提交前对照指令。`.tmp/uc630/offline.py` 只审计旧 h630 六轮真实消息的中英文投影，不向新执行模型输入旧答案或程序。正式采集仍只用原题及 CSV，空会话、direct／none。

```powershell
.\.venv\Scripts\python.exe -X utf8 .tmp/uc630/offline.py
.\.venv\Scripts\python.exe -X utf8 .tmp/uc630/prepare_judge.py
.\.venv\Scripts\python.exe -X utf8 .tmp/uc630/launch.py prepare
.\.venv\Scripts\python.exe -X utf8 .tmp/uc630/launch.py run
.\.venv\Scripts\python.exe -X utf8 .tmp/uc630/audit.py
.\.venv\Scripts\python.exe -X utf8 .tmp/uc630/score.py
```

脚本从仓库根执行，offline 可显式设置 `PYTHONPATH=src;.`；其余正式脚本绑定根或冻结代码。prepare_judge 零模型核对同配置 h630 资格 seal，必须先完成再启动生成；不重跑资格。prepare 完成后再 run，原身份与源码不可覆盖。生成上限 6M，六份独立评分统一 300K 外层额度，内层 1M 配置及原判据保持，旧费用另计。六轮已生成后才能 audit／score；审计用户原文与索引逐字保真、每次主请求可见、本轮标识、原生历史和实际 SDK 绑定。第三轮语义失败仍完成计划内其他轮次，冻结运行中不改 Prompt、补反馈或替换失败样本。


## 执行目标维护接入后的 task2 六轮

2026-10-31，新身份 `.tmp/gm630/` 按[目标维护 Spec](../optimization/to_verify/analysis-goal-maintenance.md)和 ADR 0048 运行。当前生成 6M、独立评分统一 300K，原六问／CSV、模型、参数和镜像保持；全新会话，仅继承本次真实输出，不回放旧答案或人工目标。当前前置 Offline Eval 为零模型，六轮必须冻结后再运行。

```powershell
.\.venv\Scripts\python.exe -X utf8 .tmp/gm630/offline.py
.\.venv\Scripts\python.exe -X utf8 .tmp/gm630/prepare_judge.py
.\.venv\Scripts\python.exe -X utf8 .tmp/gm630/launch.py prepare
.\.venv\Scripts\python.exe -X utf8 .tmp/gm630/launch.py run
.\.venv\Scripts\python.exe -X utf8 .tmp/gm630/audit.py
.\.venv\Scripts\python.exe -X utf8 .tmp/gm630/score.py
```

采集封存且进程退出后才独立评分，六份答案各一次，不把评分或标准回流模型。目标前置、目标正文、最终回答及 Runtime 反馈覆盖分别判定，未触发的拒绝或压缩不计已验证。

首次 gm630 在第二轮目标引用协议失败后已停止并封存，1/2 交付、249,371 tokens 保留。一次有界引用选择符修正后，新空会话身份为 `.tmp/gm631/`，上述准备、运行、审计和评分命令的目录改为 gm631；另执行 `reference_replay.py` 和 `goal_audit.py`。新生成限额为原 6M 剩余 5,750,629，不恢复首段会话或输入首段答案，评分额度保持统一 300K。

## 目标执行核对 Prompt 后的 task2 前三轮

2026-10-31 用户授权的新身份 `.tmp/gm633/`，按目标维护 Spec §9 从第一问及 CSV 空会话连续执行前三轮一次。主任务 Prompt 为 `v4-goal-execution-review-md`，包含每轮维护、按目标执行、执行后及提交前核对，以及目标不明确时依据用户原话再次修订。核验器与 criteria 继续关闭；历史反馈只保留原交互，既有执行材料和用户原文视图保持。新生成限额 3M、独立评分 300K；原模型、参数、Docker、每轮限制及评分协议不变，全部旧费用与未知另计。

```powershell
.\.venv\Scripts\python.exe -X utf8 .tmp/gm633/prepare_judge.py
.\.venv\Scripts\python.exe -X utf8 .tmp/gm633/launch.py prepare
.\.venv\Scripts\python.exe -X utf8 .tmp/gm633/launch.py run
.\.venv\Scripts\python.exe -X utf8 .tmp/gm633/audit.py
.\.venv\Scripts\python.exe -X utf8 .tmp/gm633/goal_audit.py
.\.venv\Scripts\python.exe -X utf8 .tmp/gm633/score.py
```

资格核对为零模型，先通过再冻结；生成结束及封存后检查全部实际输入，并对第 1／2／3 轮各独立评分一次。第三轮失败仍保留并结束既定三轮，不修改 Prompt、重抽样或注入正确结果；不将一次连续旅程称为三次独立重复。英文只登记实际注册／投影覆盖，不外推产品语义通过。

gm633 第一轮目标数组格式连续错误后已封存，0/1 交付、2 次主请求、15,700 tokens，未评分。经子 Spec §9 先行复审，只修正 nullable Schema 子错误定位，v4 主任务规则保持；`gm634/diagnostic_replay.py` 零模型回放通过后，上述准备、运行、审计和评分命令目录改为 `.tmp/gm634/`。新空会话生成只剩原 3M 的 2,984,300，保留首段费用和失败，不回放首段目标或答案；同类阻塞再次终止则停止依赖重跑。

gm634 在第二轮来源索引字符串错误后停止，第一轮已评分通过，原三轮未完成。用户随后明确取消 goal 来源索引，按子 Spec §4／§9 删除字段、校验和双语索引要求，并继续原三轮计划。新身份 `.tmp/gm635/`，先运行 `index_removal_replay.py`，再将准备／运行／审计／评分命令目录改为 gm635。生成额度为原 3M 剩余 2,691,176，独立评分外层额度为原 300K 剩余 294,947；内层配置和资格不变，前两段生成 308,824 及评分 5,053 保留。从原第一问和 CSV 空会话运行，不向模型输入旧目标、修正过的诊断输入或历史答案；旧带索引档案保留原冻结源码身份，不嫁接新 Schema。

gm635 已退出封存：8 次主请求、159,129 tokens，第一轮已交付并独立评分通过，第二轮因其他数组格式错误终止，第三轮未执行。目标 Schema、实际调用及回执中的索引删除已核对；原三轮旅程仍未验收，停止继续逐字段补丁和自动重跑。当前段含评分共 9 次物理／162,957 tokens，原三轮计划三段累计 22 次物理／476,834 已知 tokens／未知 0。原件及边界见[验证记录 §20](../optimization/to_verify/verify_results/analysis-correctness.md#20-取消-goal-来源索引与原三轮续验)。

用户本次授权补参数描述并继续，按[子 Spec §9.1](../optimization/to_verify/analysis-goal-maintenance.md#91-字段说明缺口的复审与本次续验)准备新身份 `.tmp/gm636/`：先执行 `schema_audit.py` 零模型输入审计，再将以上准备、运行、实际输入／目标审计及评分命令目录改为 gm636。原生成限额剩 2,532,047、原评分外层剩 291,119，内层评分配置和资格保持。仅更改字段元数据、总说明及英文资源；从原第一问和 CSV 空会话连续前三轮，运行中不再改 Prompt 或追加协议修复。

gm636 已封存并停止：三轮全部交付，15 次主请求、514,885 tokens、185.375 秒；原协议独立评分 2/3（1、1、0），10,361 tokens，当前段共 18 次物理／525,246 已知 tokens／未知 0。15 份实际 Schema 说明及上下文审计通过，两次参数错误均恢复；第三轮仍反转集中度方向并补入不合格市场，未满足本次用户结果。含 gm633—gm636，原计划累计 40 次物理／1,002,080 已知 tokens，生成 982,838、评分 19,242，未重置限额。按停止线结束，不追加重跑；见[验证记录 §21](../optimization/to_verify/verify_results/analysis-correctness.md#21-目标工具字段描述与前三轮续验)。

用户随后要求清除固定提示中的特定任务描述。按[子 Spec §9.2](../optimization/to_verify/analysis-goal-maintenance.md#92-固定提示通用性纠正)使用新身份 `.tmp/gm637/`：执行 `generic_input_audit.py`，再将前述资格、准备、运行、实际请求／目标审计和评分命令目录改为 gm637；另用 `request_generic_audit.py` 检查实际固定资源与动态材料边界。原生成限额剩 2,017,162、评分外层剩 280,758，内层配置及资格保持。主任务采用 v5-general-user-goal-md，从原第一问和 CSV 空会话连续前三轮；清理不冒充特定任务的语义修复，不追加核验器或回放旧答案。

gm637 已退出封存，交付 3/3，独立评分 1/3（1、0、0）：20 次主请求、963,614 tokens、263.906 秒，评分三次、19,290 tokens，当前段 23 次物理／982,904 已知 tokens／未知 0。固定资源与实际 SDK、目标和历史审计通过；第二轮名单范围、第三轮补位仍失败。原前三轮计划累计 63 次物理／1,984,984 已知 tokens，生成 1,946,452、评分 38,532；剩余原限额分别 1,053,548／261,468，旧失败及未知保持原身份。通用性纠正已落实，原语义问题未验收，按停止线结束；详见[验证记录 §22](../optimization/to_verify/verify_results/analysis-correctness.md#22-固定提示通用性纠正与回归)。

## 原失败回答的目标判决依据追问

2026-10-31 用户授权检验目标理解，并要求用反问核对原答依据。按[子 Spec §9.3](../optimization/to_verify/analysis-goal-maintenance.md#93-目标理解与实际判决的隔离追问)，在 `.tmp/goal-comprehension-20261031/` 对 gm637 第二、三轮原最终 SDK 请求续接其同次响应和中立追问，属于隔离诊断，不是新 E2E 或修复验收。工具定义、模型和 Provider 参数保持，不执行工具或把诊断反馈送回原 Runtime。

```powershell
.\.venv\Scripts\python.exe -X utf8 .tmp/goal-comprehension-20261031/probe.py prepare
.\.venv\Scripts\python.exe -X utf8 .tmp/goal-comprehension-20261031/probe.py run
.\.venv\Scripts\python.exe -X utf8 .tmp/goal-comprehension-20261031/audit.py
```

prepare 与 run 已各执行一次，不覆盖归档或重跑；audit 为零模型只读复核。两次完整答复，共 171,107 tokens、未知 0；原生成余量减至 882,441，评分余额 261,468 不变。原完整前缀、目标回执和源码一致性通过，范围及数量例外的理解偏差与原记录相符；结论和自述限制见[验证记录 §23](../optimization/to_verify/verify_results/analysis-correctness.md#23-目标理解与实际判决的隔离追问)。不改原 1/3 成绩，不启动新的产品轮次或继续追问。

## 回答前读取目标接入后的原前三轮

2026-10-31 按[子 Spec §9.4](../optimization/to_verify/analysis-goal-maintenance.md#94-回答前读取当前目标的接入与验证)使用 `.tmp/gm638/`。先离线拒绝反事实与评分资格核对，再冻结源码、从原第一问及 CSV 空会话运行，读取与业务调用共享滚动历史。生成总上限因原余量不足在调用前由 3M 调为 4M；当前段限 1,882,441，评分原余额 261,468 不变。原模型、参数、Docker、恢复限制和 direct／none 保持。

```powershell
.\.venv\Scripts\python.exe -X utf8 .tmp/gm638/offline.py
.\.venv\Scripts\python.exe -X utf8 .tmp/gm638/prepare_judge.py
.\.venv\Scripts\python.exe -X utf8 .tmp/gm638/launch.py prepare
.\.venv\Scripts\python.exe -X utf8 .tmp/gm638/launch.py run
.\.venv\Scripts\python.exe -X utf8 .tmp/gm638/audit.py
.\.venv\Scripts\python.exe -X utf8 .tmp/gm638/goal_read_audit.py
.\.venv\Scripts\python.exe -X utf8 .tmp/gm638/score.py
.\.venv\Scripts\python.exe -X utf8 .tmp/gm638/final_audit.py
```

准备和采集已各一次完成，禁止覆盖或换身份重跑；只有读取审计和静态复核可重读原件。整组 audit 保留第三轮无答案失败，读取及前缀检查另计。第三轮目标参数重复格式错误后采集已停止，前两轮独立 2/2，第三轮未评分；本次不能宣称完整前三轮验收。当前段共 28 次物理／1,599,103 已知 tokens／未知 1；原账本累计生成及诊断 3,707,781、评分 47,413，未知另列。读取协议成立范围和原参数阻塞见[验证记录 §24](../optimization/to_verify/verify_results/analysis-correctness.md#24-回答前读取目标的接入与前三轮验证)，不追加提示补丁或自动重跑。


### 目标工具扁平化的定向验证（2026-11-01）

运行前契约、预算与停止条件由[目标维护 Spec §9.5](../optimization/to_verify/analysis-goal-maintenance.md#95-维护工具扁平化与分支分离)拥有。隔离诊断使用 `.venv/Scripts/python.exe -X utf8 .tmp/gm639/diagnose.py`，最多两次物理调用，不作产品 E2E；原协议历史保真。形状恢复成立后从第一问连续验证三轮，命令依次为 `.tmp/gm639/launch.py prepare`、`prepare_judge.py`、`launch.py run`、`audit.py`、`goal_read_audit.py`、`score.py`，各脚本均通过 `.venv/Scripts/python.exe -X utf8` 执行。正式采集的 direct/none 不具完整产品发布资格；评分独立且不回流 Runtime。原账本与失败保留，不补采或重新资格调用。


### 当前goal接入目标核验的隔离试验（2026-11-01）

输入、顺序、先阶段750K／12次上限、完整与最小诊断判据及条件正式三轮，由[目标维护 Spec §9.6](../optimization/to_verify/analysis-goal-maintenance.md#96-当前执行目标接入既有目标核验)及其预声明快照拥有。以仓库 `.venv/Scripts/python.exe -X utf8` 运行 `.tmp/gv640/prepare_inputs.py baseline`、`prepare_inputs.py candidate`、`run_workflow.py baseline 3`、`run_workflow.py candidate 3`、`run_workflow.py candidate 1`、`run_workflow.py candidate 3 --minimal`、`audit.py`。只有原目标operation可达，其他核验若到达立即拒绝继续调用；素材和源码封印保持，参考答案不送模型。

四次已结束，完整／最小输入未识别目标错误，按停止线没有正式三轮或修订消费，不追加样本。该结果不满足局部语义修复组，不宣称稳定改善。全部原始调用、回执、104,994tokens及未知0由[验证记录 §26](../optimization/to_verify/verify_results/analysis-correctness.md#26-当前-goal-接入目标核验的可行性与最小输入诊断)拥有。


### 单一目标正文与取消目标内成果引用（2026-11-02）

按[目标维护 Spec §9.9](../optimization/to_verify/analysis-goal-maintenance.md#99-单一目标正文与取消目标内成果引用)，先以 `.tmp/gr644/preflight.py` 审计原完整真实阶段接口，再执行 `prepare_judge.py`、`launch.py prepare`、`launch.py run`。首次因 Docker 与评测数据库未运行退出，失败保持原归档；恢复依赖且只读检查通过后，使用 `.tmp/gr645/` 中同名准备／运行脚本重新从原第一问和 CSV 空会话连续三轮一次，生产源码保持相同，不回放旧模型输出。上述脚本均从仓库根以 `.venv/Scripts/python.exe -X utf8` 执行。

生成停止且封存后，依次执行 gr645 的 `audit.py`、`verification_history_audit.py`、`goal_policy_audit.py`、`score.py` 和 `engineering_checks.py`。单一目标正文、每轮维护、原生历史与实际核验反馈消费分别审计；评分资格及原协议不变，评分不进入 Runtime。预算、原费用及停止条件由唯一 Spec 拥有，成绩写入[验证记录 §29](../optimization/to_verify/verify_results/analysis-correctness.md#29-单一目标正文与取消成果引用后的前三轮)，不重复执行付费评分或覆盖历史捕获。


### 统一目标与回答核验的连续前三轮（2026-11-02）

按[Spec §9.11](../optimization/to_verify/analysis-goal-maintenance.md#911-取消隔离前置验证并按新机制连续执行)执行；不运行隔离判定或历史模型回放。仓库根用`.venv/Scripts/python.exe -X utf8`依次运行`.tmp/gv647/prepare_judge.py`（复用资格，零模型调用）、`launch.py prepare`（冻结源码和输入身份）、`launch.py run`（原第一问、CSV、空会话连续三轮）。正式进程停止并封存后执行`audit.py`、`audit_unified.py`检查真实输入、目标写入前核验及反馈和历史续接，再用`score.py`按原协议对实际答案各评分一次；评分不回流Runtime。最后执行`engineering_checks.py`，实际结果及费用写入[记录§31](../optimization/to_verify/verify_results/analysis-correctness.md#31-统一目标与回答核验的空会话连续前三轮)，不覆盖旧运行。


### 单正文内容契约的连续前三轮（2026-11-02）

按[Spec §9.12](../optimization/to_verify/analysis-goal-maintenance.md#912-单正文的任务定义与四项内容核验)执行。在仓库根使用`.venv/Scripts/python.exe -X utf8`运行`.tmp/goal-quality-20261102/prepare_judge.py`、`launch.py prepare`、`launch.py run`；复用评分资格，零资格新调用。原第一问与CSV进入正式HTTP空会话，连续三轮实际维护、核验、执行和回答，真实历史滚动，不运行隔离模型验证。进程停止并封存后运行`audit.py`、`audit_unified.py`、`score.py`和适用用户结果核对；评分逐物理调用预留、原协议不变、不回流Runtime。结果及费用进入[记录§32](../optimization/to_verify/verify_results/analysis-correctness.md#32-单正文四项内容契约的空会话连续前三轮)。


### 逐项用户要求核验的连续前三轮（2026-11-02）

按[Spec §9.13](../optimization/to_verify/analysis-goal-maintenance.md#913-按用户要求逐项比较的统一核验)实施。本次身份`.tmp/goal-checks-20261102/`，仓库根以`.venv/Scripts/python.exe -X utf8`依次执行`preflight.py`（数据库、固定镜像和Schema零模型检查）、`prepare_judge.py`（复用旧资格）、`launch.py prepare`（冻结源码）及`launch.py run`（原第一问、CSV、空会话连续三轮一次）。不运行隔离模型或注入旧目标／回答；评分在生成停止封存后单独运行`score.py`，不回流Runtime。

`audit.py`核对原生交互及SDK请求保真，`audit_unified.py`核对逐项真实输出、回执归一、目标写入前门禁和实际反馈续接；随后核对原用户结果与必要反事实，运行`engineering_checks.py`。实际成绩、费用和未触发边界由[记录§33](../optimization/to_verify/verify_results/analysis-correctness.md#33-逐项用户要求核验的空会话连续前三轮)拥有；本次已执行：第一轮terminal_limitation、正常答案0，后两轮未执行；报告形状及反馈绑定成立，语义失败，不补评分或整轮重采。

### 分离目标与回答核验的连续前三轮（2026-11-03）

按[Spec §9.14](../optimization/to_verify/analysis-goal-maintenance.md#914-分离目标核验与回答核验的职责及历史)在`.tmp/goal-split-20261103/`封存本轮身份。仓库根用`.venv/Scripts/python.exe -X utf8`依次执行`preflight.py`、`prepare_judge.py`、`launch.py prepare`及`launch.py run`，从原第一问、CSV和空会话连续三轮一次；此前三步无新模型调用。新目标、回答、核验与修复均消费本轨迹实际产物，不回放旧答案或隔离核验。

生成停止封存后执行`audit.py`（主循环输入及SDK保真）、`audit_split.py`（两类真实核验请求、同职责历史、回执及反馈）和`score.py`（原协议独立评分，不回流Runtime），随后执行工程检查。本次已完成：三轮正常交付，原分[1,1,1]、预声明用户结果通过／通过／失败。首个score.py在网络派发前因本轮待发请求计数检查错误退出，原失败保留；按子Spec独立恢复决定使用score-recovered.py和j-recovery完成三份答案各一次实际评分，原Prompt／资格／参数／余额保持，无生成重采。实际结果及费用由[记录§34](../optimization/to_verify/verify_results/analysis-correctness.md#34-分离目标与回答核验的空会话连续前三轮)拥有，原始失败与旧身份不覆盖。

### 当前职责分离实现的task2全量运行（2026-11-03）

用户要求完整运行原task2的34轮，计划、60M生成及1M独立评分额度、原参数和停止边界由[Spec §9.15](../optimization/to_verify/analysis-goal-maintenance.md#915-当前实现的task2全量连续运行)拥有。当前源码保持不变，独立身份`.tmp/task2-full-split-20261103/`从原第一问、CSV及空会话连续执行；不继承前三轮运行结果，不在运行中修复生产或使用独立评分筛选答案。

仓库根用`.venv/Scripts/python.exe -X utf8`依次运行该身份下`preflight.py`、`prepare_judge.py`、`launch.py prepare`、`launch.py run`；生成停止封存后运行`audit.py`、`audit_split.py`、`score.py`及`finalize.py`。实际请求3/34、正常交付2轮，原独立分[1,0]；第三轮重复修订参数类型错误后limitation，后31轮未执行。主循环与两类核验历史审计成立，未触发压缩，未完成全量。新增生成32次／1377224已知tokens／未知1，独立评分2次／6930／未知0；结果由[记录§35](../optimization/to_verify/verify_results/analysis-correctness.md#35-当前实现的task2全量连续运行)拥有，不重采生成、不改写旧身份。

### 回答拒稿后原循环重生成的连续前三轮（2026-11-03）

按[Spec §9.16](../optimization/to_verify/analysis-goal-maintenance.md#916-回答拒稿后沿原循环重新生成)及ADR0049，独立身份`.tmp/answer-regeneration-20261103/`保护原工作树、冻结新源码，从原第一问、CSV及正式HTTP空会话连续前三轮一次。生成4M、原MiMo独立评分外层100K，模型／参数／材料／资格保持；不运行隔离模型回放或注入旧目标／答案／判决。

仓库根以`.venv/Scripts/python.exe -X utf8`执行该身份下`preflight.py`、`prepare_judge.py`、`launch.py prepare`后再执行`launch.py run`。停止封存后运行`audit.py`、`audit_split.py`、`audit_regeneration.py`、`score.py`及`finalize.py`，评分不回流Runtime。首次零模型准备在资源清理过程中因Catalog中英文集合不一致退出，尚未冻结源码或发模型；完成清理后按顺序重新预检／冻结，不覆盖该准备失败。实际一次三轮均正常交付，原分[1,1,0]、用户结果通过／通过／失败；三份回答各一次通过核验，回答拒稿重生成未触发。实际请求、绑定及新费用由[记录§36](../optimization/to_verify/verify_results/analysis-correctness.md#36-普通回答改为原循环完整重提的连续前三轮)拥有，不将原题其余31轮记为本次计划内未完成或补0分。

### 原循环重生成实现的task2完整34轮（2026-11-03）

按用户新请求及[Spec §9.17](../optimization/to_verify/analysis-goal-maintenance.md#917-当前原循环重生成实现的task2全量运行)，在`.tmp/task2-full-regeneration-20261103/`保持当前580文件及原模型参数，从原第一问、CSV和空会话连续执行全部34轮一次。生成60M及独立评分1M，错误正常答案继续后续题；原有技术／正式终态边界保持，不沿用前三轮答案或为新运行修复生产。

仓库根用`.venv/Scripts/python.exe -X utf8`依次运行preflight.py、prepare_judge.py、launch.py prepare、launch.py run。进程停止封存后运行audit.py、audit_split.py、audit_regeneration.py、score.py及最终汇总，实际SDK、压缩、历史、结果与成本分别报告，不回流评分。当前为已固定运行计划，尚无本次全量结果。

该次首次Web启动健康检查超时，`c`封存为0用户／0模型；相同源码零模型启动诊断已健康200。按Spec固定一次发题前启动重试，独立输出`c-recovery`，原45秒健康检查、源码、参数和额度保持；不覆盖首试或当作已有轮次恢复。后处理脚本读取明确的`c-recovery`并将首试成本单列。

用户随后要求第3轮结束先暂停：发题进程在等待第三轮时被挂起，Web端继续完成原第三轮。只读现场快照放本次归档；只有第三轮正常answer且原进程仍在时，才可核对PID及创建身份后接续第4题；正式非answer则只让原采集器记录并退出。不是新的空会话、原第17轮checkpoint或完整34轮结果；评分暂不启动。

实际第3轮在40次主决策及30次回答退回后返回limitation，前2轮正常交付；只释放采集器记录正式终态后按原链路退出，第4—34轮未执行。c-recovery及p3副本均已seal，当前没有活跃采集进程；resume.py仅报告原终态，不会启动或跳过第三轮。评分仍暂停，后续须先核对第三轮阻塞与正式接续边界。实际结果、89次物理／7715814已知tokens／未知1及上下文审计由[记录§37](../optimization/to_verify/verify_results/analysis-correctness.md#37-原循环重生成实现的task2在第3轮后停止)拥有。

### 结果卸载与完整交互压缩的task2连续验证（2026-11-03）

当前设计和停止边界由[Spec §9.20](../optimization/to_verify/analysis-goal-maintenance.md#920-结果卸载与完整交互压缩)拥有。仓库根以 `.venv/Scripts/python.exe -X utf8` 依次执行 `.tmp/context-unload-task2-20261103/` 下的 `preflight.py`、`prepare_judge.py`、`launch.py prepare`、`launch.py run`；原34轮从第一题、CSV、新主体和空会话连续一次，生成60M、独立评分1M，原模型、1M容量与每轮40主决策保持。

首次身份 `.tmp/context-unload-implementation-20261103/c-recovery` 第一题在模型派发前因GovernedModelClient缺少容量测量转交返回500，物理调用及tokens均0。一次有界修正后，正式模型工厂的零网络真实请求测量通过；当前新身份冻结582文件，不继承旧答案或覆盖原失败。仅在生成完全停止并封存后运行 `audit.py`、`audit_split.py`、`audit_regeneration.py` 和 `score.py`；审计按每次实际覆盖范围检查未覆盖的原生消息、判决与修复，不把合法摘要遗漏计为反馈丢失，也不以摘要存在代替后继消费。生成期间不得改生产或回流评分。

本次实际已停止封存：十轮正常交付，原分3/10；第十一轮因机器重启中断。同run恢复沿原HTTP、主体、消息、许可及截止时间执行，复用已解码原件、新增模型0，机器再次重启后停止重启生成。`resume.py prepare/run`、`close_interrupted.py`保留两段现场并据真实OS、SDK及Journal记录采集终态，不伪造缺失的HTTP响应。上述审计在生成源码冻结状态执行；之后仅删除不可达函数／调用与未使用双语提示，`cleanup_projection.py before/after`的11个真实阶段完整投影一致。清理后的四份预期源码差异由post-cleanup-source-hashes.json明确记录；原冻结代码及审计不覆盖。详细结果、费用、实际命令及未验证边界见[记录§39](../optimization/to_verify/verify_results/analysis-correctness.md#39-结果卸载与完整交互压缩的-task2-连续验证)。

### 原运行到期后的task2全量重验（2026-11-03晚）

用户再次要求继续时，旧第十一轮截止时间已过；不修改原许可恢复，按[Spec§9.21](../optimization/to_verify/analysis-goal-maintenance.md#921-系统中断后的-task2-完整验证重新执行)从新主体和空会话执行原34题。新归档`.tmp/cu-full-20261103/`复用原`preflight.py`、`prepare_judge.py`、`launch.py prepare/run`、原正式baseline及采集／审计／独立评分工具；冻结当前源码，模型与每轮限制不变。仅使用剩余生成53607951和独立评分952535额度，旧744次／39531277已知及未知3继续累计。旧seal和成绩不改写，任何技术或正式非answer终态仍停止；生产不修改，不做隔离模型实验。运行结果只归入新身份，不冒充原第十二轮接续或确定性收益。

实际生成在第21轮被OS重启中断，20轮正常交付；`close_interrupted.py`从真实Journal和SDK封存无HTTP响应的中断事实。`audit.py`、`audit_split.py`、`audit_regeneration.py`、`artifact_projection.py`完成无模型检查。原`score.py`评分前三轮后再次遇OS重启，`close_grading_interrupted.py`仅按三个有效seal及第4次未决请求保存原分和未知用量，没有重启评分或制造响应；进度日志／预留文件损坏原件保持。原始请求、每轮report、绑定响应及checksums优先于日志文本，结果见[记录§40](../optimization/to_verify/verify_results/analysis-correctness.md#40-原运行到期后的-task2-独立连续重验)。

2026-11-04用户要求补齐20轮评分时，只运行新归档`.tmp/cu-score-resume-20261104/score.py prepare/run`，引用原已封存采集及前三轮report，从第4轮继续。旧归档不写入，旧第4次未知调用预留52839tokens后，新派发额度886684；资格、Prompt、模型、请求参数和官方评分函数保持。补评结束引用前三轮与新增逐轮report合成20轮汇总，旧未知和原分仍按原身份保留，不重启业务生成。

补评实际完成：新增17次调用、94777已知tokens、新未知0，20份答案原分7/20通过。新归档`audit.py`核对全部20轮实际请求、原答案、官方解析、逐轮seal及用量；旧归档保持。逐轮原分、预算与比较边界见[补评结果](../optimization/to_verify/verify_results/analysis-correctness.md#已交付20轮的原评分补齐2026-11-04)。

### 逐次回答目标绑定与核验上下文（2026-11-04）

实验组 1 的接入检查复用下列两轮入口。当前可用 `--feature-flags <TOML>` 显式选择独立实验配置；配置原件随采集归档。评测器修正后，可用 `--continue-source <已封存首轮目录>` 在生产源码、配置和授权保持时续接第二轮，继承累计预算，不重采首轮；`--audit-source` 对已有交付及错误反事实进行零模型资格检查。已执行命令身份为 `.tmp/feature-flags-20261105/` 下的 `target-on`、`target-on-continued`、`target-off`、`target-off-continued` 及 `qualification-*`，实际结果、费用和未覆盖边界由[实验组 1 接入规格](../ablation/experiment.md#接入规格2026-11-05)拥有。关闭核验的采集标为 `unverified_flow_capture`，不提升为完整产品通过。

在仓库根使用 `.venv/Scripts/python.exe -X utf8`。实现前的固定旧真实轨迹、VCTX-1 至 VCTX-4、两轮中文请求及费用边界由[固化方案](../optimization/completed/verification-context-goal-binding.md)拥有。以下输出均采用独立身份，不覆盖已有目录。

```powershell
.\.venv\Scripts\python.exe -X utf8 -m evals.product_baselines.verification_context_projection --source .tmp/context-unload-task2-20261103/c-recovery --output .tmp/verification-context-format-20261104/goal-binding-offline --user-turns 3
.\.venv\Scripts\python.exe -X utf8 -m evals.product_baselines.verification_context_projection --source .tmp/context-unload-task2-20261103/c-recovery --output .tmp/verification-context-format-20261104/goal-revision-offline --user-turns 9 --verification-only-turn 9
.\.venv\Scripts\python.exe -X utf8 -m evals.product_baselines.run_verification_context_target --output .tmp/verification-context-format-20261104/e2e
.\.venv\Scripts\python.exe -X utf8 -m evals.product_baselines.verification_context_projection --source .tmp/verification-context-format-20261104/e2e --output .tmp/verification-context-format-20261104/e2e-projection --user-turns 2 --expect-current-wire
.\.venv\Scripts\python.exe -X utf8 -m evals.product_baselines.run_verification_context_target --audit-source .tmp/verification-context-format-20261104/e2e --output .tmp/verification-context-format-20261104/outcome-qualification-final
```

第三条实际派发真实模型和 Python，其他命令只读真实阶段、不派发模型。旧调用的旧 Schema 序列化身份只在历史评测读取边界核对，生产不增加兼容路径。第 9 轮回放保留前 8 轮原历史，仅检查两类核验阶段，不运行主循环压缩器。`--expect-current-wire` 检查当前中文核验消息与原实发请求相等；英文只检查物化。

结果为 42、10、28 项阶段检查分别全通过；真实两轮交付均通过，首次弱数字断言由封存结果及错误反事实资格 11/11 补正。具体成本与证据边界由[盘点](02-current-case-inventory.md#2026-11-04-逐次回答目标绑定与核验上下文)拥有，不把零模型回放当成产品 E2E 或另加模型用量。评审及资格过程原件保留，生产源码与实际采集相同，评测断言后续修改另存源码身份。

### 核验上下文修正后的task2后台验证（2026-11-04）

计划与预算由[Spec§9.23](../optimization/to_verify/analysis-goal-maintenance.md#923-核验上下文修正后的-task2-后台连续验证)拥有。新归档`.tmp/vctx-task2-20261104/`先执行零模型preflight.py、prepare_judge.py和launch.py prepare，冻结当前源码；再以隐藏后台进程启动pipeline.py，顺序完成原34轮正式生成、输入／职责／修复审计及独立原评分。状态入口status.json，生成日志generation.log，原采集c-recovery，评分score-report.json，最终汇总summary.json；每个阶段独立留日志及退出码。旧归档只读，不复制旧模型输出给新运行，不在本对话持续监控。流水线只验证冻结身份，工作区后续变动另记，不写回生产源码或自动修改权威文档。
