# 独立检索实验工具

从仓库根运行 `python -m scripts.retrieval_experiment --help`。本工具供开发者执行一次实验、复算及复现；研究设计由[唯一 Spec](../../docs/optimization/to_verify/verify_results/research-experiment.md#31-先行交付独立实验工具-implementation-plan)拥有。控制端路径由受信操作者提供，不是模型参数协议。

工程入口只转调 `src/personal_agent/adapters/cli/retrieval_experiment.py`，不初始化 Runtime。独立 CLI 和生产 `DockerExperimentBackend` 共用 `infra/retrieval_experiment/` 的检索、评分和候选执行实现；业务类型与无 IO 冻结规则由 `application/retrieval_experiment/` 拥有。原工程命令和 `--help` 只需下列 control requirements；`reproduce` 读取正式 Artifact 与 Settings，使用已安装项目生产依赖的原授权运行环境，也不构造 Runtime。worker 从仓库根构建，专属 `Dockerfile.worker.dockerignore` 只允许固定依赖和必要 Python 源码进入上下文；候选镜像仍使用原目录构建。新 worker 使用独立标签，历史冻结仍绑定原确切镜像与源码，不能换成新镜像。

当前源码将 `per_query.json` 保持为标准 JSON 对象、每查询一行，便于原读取／搜索按完整查询定位；评分值和 JSON 消费者保持。须使用包含此源码的新 worker 镜像，原单行文件与确切旧镜像保留，详见[格式范围与验证](../../docs/optimization/to_verify/verify_results/research-experiment.md#逐查询产物的可定位格式候选)。

生产装配由 `PERSONAL_AGENT_RETRIEVAL_EXPERIMENT_CONFIG` 指向受信 JSON，顶层为 `deployment` 与 `environment`。前者绑定主体、四种原件角色、manifest、固定镜像和模型身份及额度；后者含 `endpoint`、`network`、`es_endpoint`、绝对 `model_path` 和 `workspace_root`。加载入口为 `infra.retrieval_experiment.deployment.load_retrieval_deployment`。实际部署还须完成生成模型 capacity 准入；完整接受、授权、恢复及完成规则见 [受限实验能力](../../docs/optimization/to_verify/research-experiment-protocol.md#2-受限实验能力)，本 CLI 不替代该生产入口。

## 准备

需要 Python 3.11+、Linux Docker Engine（API 1.44+）及已获准的数据和固定模型快照。运行时只使用本地镜像、离线模型，不自动下载。控制端和 Docker daemon 必须能访问同一输入暂存目录；本例已针对 Windows Docker Desktop 使用命名管道。

控制端为实际使用的镜像建立 `personal-agent-retrieval-snapshots:sha256-*` 本地保留标签，防止移动 build tag 后丢失冻结版本。保持这些标签及许可模型／数据快照，才可按冻结身份重跑；跨机器复现须预先导入同一镜像和资源。清理镜像属于操作者的资源管理，工具不自动删除复现依赖。worker 镜像明确固定 NumPy `1.26.4`，以兼容固定 BEIR 所用 Elasticsearch `7.9.1` client。

```powershell
uv pip install --python .venv/Scripts/python.exe -r scripts/retrieval_experiment/requirements-control.txt
docker build -f scripts/retrieval_experiment/Dockerfile.worker -t personal-agent-retrieval-worker:query-lines-20261021 .
docker build -f scripts/retrieval_experiment/Dockerfile.candidate -t personal-agent-retrieval-candidate:20261020 scripts/retrieval_experiment
docker pull docker.elastic.co/elasticsearch/elasticsearch:7.17.28
docker network create --internal retrieval-experiment-tool
docker run -d --name retrieval-experiment-es --network retrieval-experiment-tool --memory 2g --cpus 2 --pids-limit 256 -e discovery.type=single-node -e xpack.security.enabled=false -e ES_JAVA_OPTS="-Xms512m -Xmx512m" docker.elastic.co/elasticsearch/elasticsearch:7.17.28
```

Elasticsearch 是本工具新建的独立服务，不映射宿主端口。等待服务就绪后执行 BM25；实验结束可用 `docker stop retrieval-experiment-es` 停止服务。正式知识库的 Elasticsearch、索引或凭据不属于本例环境。

本仓库已审计原件位于 `.tmp/retrieval-experiment-scenario-20261018/sources/`；固定来源、许可限制及校验和见[材料审计](../../docs/agentRef/task-benchmarks.md#8-beirscifact-检索实验材料)。模型需要固定 `sentence-transformers/all-MiniLM-L6-v2` revision `1110a243fdf4706b3f48f1d95db1a4f5529b4d41` 的 Sentence Transformers 配置、tokenizer 和 safetensors，放到本地目录；无需下载其他格式权重。控制端不将 qrels 或模型目录交给候选程序。

## 执行和复算

以下 PowerShell 示例使用本次本地材料；输出目录必须尚不存在，失败及历史结果不会被覆盖。

```powershell
$engineEndpoint = 'npipe:////./pipe/dockerDesktopLinuxEngine'
$workerImage = 'personal-agent-retrieval-worker:t2-20261020'
$candidateImage = 'personal-agent-retrieval-candidate:20261020'
$sourceDir = '.tmp/retrieval-experiment-scenario-20261018/sources'
$experimentDir = '.tmp/my-retrieval-experiment'
$modelDir = '.tmp/retrieval-experiment-tool-20261020/model'

.\.venv\Scripts\python.exe -m scripts.retrieval_experiment prepare --corpus "$sourceDir/BeIR-scifact/corpus.parquet" --queries "$sourceDir/BeIR-scifact/queries.parquet" --qrels "$sourceDir/BeIR-scifact-qrels/train.tsv" --split train --output "$experimentDir/train"
.\.venv\Scripts\python.exe -m scripts.retrieval_experiment prepare --corpus "$sourceDir/BeIR-scifact/corpus.parquet" --queries "$sourceDir/BeIR-scifact/queries.parquet" --qrels "$sourceDir/BeIR-scifact-qrels/test.tsv" --split test --output "$experimentDir/test"
.\.venv\Scripts\python.exe -m scripts.retrieval_experiment run --endpoint $engineEndpoint --image $workerImage --dataset "$experimentDir/train/manifest.json" --method bm25 --network retrieval-experiment-tool --es-endpoint http://retrieval-experiment-es:9200 --output "$experimentDir/bm25"
.\.venv\Scripts\python.exe -m scripts.retrieval_experiment run --endpoint $engineEndpoint --image $workerImage --dataset "$experimentDir/train/manifest.json" --method dense --model $modelDir --model-revision 1110a243fdf4706b3f48f1d95db1a4f5529b4d41 --output "$experimentDir/dense"
.\.venv\Scripts\python.exe -m scripts.retrieval_experiment rrf --endpoint $engineEndpoint --image $workerImage --dataset "$experimentDir/train/manifest.json" --inputs "$experimentDir/bm25/result.json" "$experimentDir/dense/result.json" --output "$experimentDir/rrf"
.\.venv\Scripts\python.exe -m scripts.retrieval_experiment score --endpoint $engineEndpoint --image $workerImage --dataset "$experimentDir/train/manifest.json" --result "$experimentDir/rrf/result.json" --output "$experimentDir/recalculated"
```

每个成功结果目录包含 `result.json`、`rankings.json`、`coverage.json`、`metrics.json`、`per_query.json`、作业身份及有界日志。`result.json` 绑定输入、实际配置、BEIR／工具源码、包版本、模型和镜像身份。缺查询执行直接失败；已完成但零命中按零分进入完整分母。指标为五位小数的 nDCG@10 和 Recall@100，不能解释为科学声明真值或中文私人知识库效果。

## 候选程序

```powershell
.\.venv\Scripts\python.exe -m scripts.retrieval_experiment program --endpoint $engineEndpoint --image $workerImage --candidate-image $candidateImage --dataset "$experimentDir/train/manifest.json" --inputs "$experimentDir/bm25/result.json" "$experimentDir/dense/result.json" --program fusion.py --output "$experimentDir/candidate"
```

程序使用 Python 标准库，从命令行第一个参数指定的只读目录读取 `rankings_0.json`、`rankings_1.json`、`queries.json`、`corpus_ids.json`；可选 `--config` 提供自己生成的 JSON 配置，目录中命名为 `config.json`。stdout 必须是唯一 JSON 对象 `{query_id: {document_id: finite_score}}`，包含当前 split 全部查询，诊断文字写 stderr。完整输入不是必须使用的固定算法；程序自行实现组合或重排。

固定启动命令为 `python -I /inputs/program.py /inputs`。候选禁网、非 root、只读根与输入、512 MiB 内存、1 CPU、64 个进程、32 MiB 临时空间；默认执行 60 秒，`--timeout` 接受 1—1200 秒并随源码冻结，stdout 上限 16 MiB，stderr 上限 64 KiB。超时／输出超额会停止并核对容器终态。状态未知时保留容器身份及暂存输入供操作者对账，不自动重启或评分。控制端存活时负责截止；控制端宕机后的自动 TTL 未实现。

候选原始输出、源码和作业事实保存在 `candidate/`，外部评分产物在 `candidate/scored/`。执行成功不等于方法有效或研究完成；程序自报指标不会被采信。

## 冻结和最终 test

先根据开发证据选择方案，再冻结。基线无需 `--inputs`；RRF／候选需按实际顺序提交原开发输入。冻结候选时使用 `candidate/scored/result.json`。

```powershell
.\.venv\Scripts\python.exe -m scripts.retrieval_experiment freeze --result "$experimentDir/rrf/result.json" --inputs "$experimentDir/bm25/result.json" "$experimentDir/dense/result.json" --output "$experimentDir/frozen-rrf"
.\.venv\Scripts\python.exe -m scripts.retrieval_experiment freeze --result "$experimentDir/bm25/result.json" --output "$experimentDir/frozen-bm25"
.\.venv\Scripts\python.exe -m scripts.retrieval_experiment freeze --result "$experimentDir/dense/result.json" --output "$experimentDir/frozen-dense"
.\.venv\Scripts\python.exe -m scripts.retrieval_experiment test --endpoint $engineEndpoint --image $workerImage --dataset "$experimentDir/test/manifest.json" --frozen "$experimentDir/frozen-bm25/frozen.json" --network retrieval-experiment-tool --es-endpoint http://retrieval-experiment-es:9200 --output "$experimentDir/test-bm25"
.\.venv\Scripts\python.exe -m scripts.retrieval_experiment test --endpoint $engineEndpoint --image $workerImage --dataset "$experimentDir/test/manifest.json" --frozen "$experimentDir/frozen-dense/frozen.json" --model $modelDir --model-revision 1110a243fdf4706b3f48f1d95db1a4f5529b4d41 --output "$experimentDir/test-dense"
.\.venv\Scripts\python.exe -m scripts.retrieval_experiment test --endpoint $engineEndpoint --image $workerImage --dataset "$experimentDir/test/manifest.json" --frozen "$experimentDir/frozen-rrf/frozen.json" --inputs "$experimentDir/test-bm25/result.json" "$experimentDir/test-dense/result.json" --output "$experimentDir/test-rrf"
```

候选 test 额外提供同一 `--candidate-image`，源码和配置从冻结目录恢复。换数据、实现、模型、镜像、参数或输入生成规则会失败。冻结文件只约束本工程工具的复现输入，不提供多用户授权或不可篡改的产品 Journal；受信操作者负责保持 train／test 协议。再次复现使用同一冻结文件和资源，在新的输出目录运行相同命令。

## 从研究交付包复现

在已安装项目生产依赖、保留原授权资源的环境中下载并解压研究交付的 `reproduction.zip`。继承该环境已有的 Settings 和 `PERSONAL_AGENT_RETRIEVAL_EXPERIMENT_CONFIG`；清单不能覆盖部署地址、模型位置、评分权限或额度。用户只需提交包内清单和新输出目录：

```powershell
.\.venv\Scripts\python.exe -m scripts.retrieval_experiment reproduce --manifest D:/downloads/reproduction/manifest.json --output D:/experiments/reproduced-run
```

启动前核对全部导出文件大小与摘要，以及本地许可材料、固定模型和镜像身份。包包含用户可读的实验文件、源码及配置；原始材料、模型和私有评分标签由受信部署恢复。未获私有评分许可时明确失败，不会把“已运行但不可评分”写成通过。

复现任务从同 run 的实际成功事实导出：重跑全部实际候选开发结果，以及冻结方案的完整最终评测。选回基线仍保留并重跑候选开发，不给被否定候选追加 test。执行沿原唯一引擎，按相同查询／文档及排名顺序、原分数绝对差不超过 `1e-6`、展示指标五位小数一致核对；仅全部符合才在新目录写 `reproduction.json`。原交付包和冻结结果不变，模型、凭据及私有 test 标签不会进入包。该命令提供工程复现证据，不单独构成 Product E2E。
