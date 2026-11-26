# BobFlow 的 LongDS 评测部署

BobFlow 独立检出在 `evals/agents/BobFlow/`。固定上游提交 `24b419e66fe6b5ee2f1213505c3f0bfa694bb3c8`，以及它记录的 KramaBench 子模块 `f821335b4195d2607e8da006f5fa082b406c7dfc`。评测使用上游 Bun Agent 和 Texera 执行服务。[上游部署与入口](https://github.com/Texera/bobflow/blob/24b419e66fe6b5ee2f1213505c3f0bfa694bb3c8/benchmark/README.md)

## 启动

首次检出从本工程根执行。

```powershell
git -c core.autocrlf=false clone --filter=blob:none --no-checkout https://github.com/Texera/bobflow.git evals/agents/BobFlow
git -C evals/agents/BobFlow config core.autocrlf false
git -C evals/agents/BobFlow checkout --detach 24b419e66fe6b5ee2f1213505c3f0bfa694bb3c8
git -C evals/agents/BobFlow submodule update --init --depth 1 benchmark/Kramabench
```

在能够访问依赖源的 Linux 环境中进入 BobFlow 检出。安装 JDK 17、sbt 1.12.9、Bun、Node.js、uv、Docker Compose 和 Bubblewrap。将模型网关配置放在本地，运行输出留在独立的 `STACK_DIR`。

```bash
benchmark/bench setup base
export STACK_DIR=/var/tmp/personalagent-bobflow
benchmark/bench stack up
benchmark/bench stack status
```

如果 Docker Hub 无法提供上游固定的 MinIO 镜像，优先拉取 Quay 的同标签镜像。在 Quay 也无法访问时，可以用 MinIO 官方发布页同标签的 Linux 二进制构建本地评测镜像，逐一核对发布页的 SHA-256，并记录镜像 ID。[Texera 的镜像迁移记录](https://github.com/apache/texera/pull/8529)

## LongDS 验收

选用本工程已有封存输入的 LongDS v1.1 Lite `geoscience/water-potability/task1`。先提交第 1、2 轮英文原题，检查两轮答复是否正确，以及第 2 轮是否沿用第 1 轮的 `sample_id` 和数据状态。前两轮通过后，用独立运行验证 34 轮完整会话。记录终态、逐轮得分、耗时和 token，以及后续轮次复用数据流节点和执行结果的证据。复用证据用于解释得分，逐轮得分以原题所要求的结果为准。

沿用同一个 BobFlow Agent、工作流和计算单元提交整场会话，使用本工程封存材料对应的参考答案独立评分。模型只接收原题与原始数据。首轮可按上游做法提供数据路径清单，运行记录须标明有无清单。上游 LongDS `catalog-gold` 和 `transcript-depnote` 都会在题后追加标注依赖。复现论文配置的得分须连同这项输入条件单独报告。[上游 LongDS 运行入口](https://github.com/Texera/bobflow/blob/24b419e66fe6b5ee2f1213505c3f0bfa694bb3c8/benchmark/src/bobbench/longds/run_session.py#L179-L201)

## 2026-11-24 本机验证

Windows Docker Desktop 中的 Texera 栈通过 11 项健康检查，BobFlow Agent `/api/healthcheck` 返回 200。模型与独立评分均使用 MiniMax-M3.1-Flash。LongDS 材料固定为 `6b448459c333ecc050a2e89fcc65c0e044d763ac` 的 Water Potability Task 1 英文原题。原始 ZIP 通过 SHA-256 校验，执行器只挂载本题数据。每轮时限为 8 分钟。

| 输入方式 | 第 1 轮 | 第 2 轮 |
| --- | --- | --- |
| 原题与挂载数据 | 28 次数据流调用，482.1 秒后超时 | 人工停止，未交付 |
| 首轮另提供 ZIP 路径 | 404.1 秒，12 次模型调用，0 分 | 424.3 秒，7 次模型调用，1 分 |

第二次试跑交付 2 轮，独立评分通过 1 轮。第 1 轮的行数、可饮用比例和缺失计数正确，答复强调只有首行缺值的 `ph` 符合 “starts with a gap”，评分器据此判 0。第 2 轮复用第 1 轮保存的 `tagged` 节点与 `sample_id`，按题目规定的顺序完成近邻填补，分组均值与参考值一致。两轮正确性门槛未通过，本次停在预检。

部署日志、运行脚本、工作流快照和评分封存在本地 `.tmp/bobflow-longds-20261124/`。评分运行是 `stack/runs/water-pilot-inputs`，评分汇总是 `grade-inputs/report.json`。
