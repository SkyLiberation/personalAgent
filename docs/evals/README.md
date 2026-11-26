# 评测体系索引

当前 `evals/` 保留以下公开数据集的评测及其共用工具。数据集发布者提供原始问题、语料与评分参考，仓库维护加载、执行适配和指标计算。

## 公开数据集评测

| 评测入口 | 数据来源 |
| --- | --- |
| [Open RAGBench](../../evals/open_ragbench/README.md) | [Vectara 数据集](https://huggingface.co/datasets/vectara/open_ragbench) |
| [MultiHopRAG](../../evals/multihoprag/README.md) | [MultiHopRAG 数据集](https://huggingface.co/datasets/yixuantt/MultiHopRAG) |
| [Galileo RAGBench](../../evals/galileo_ragbench/README.md) | [Galileo 数据集](https://huggingface.co/datasets/galileo-ai/ragbench) |
| [LongDS](04-running-and-release.md#公开数据集运行) | [LongDS 数据集](https://huggingface.co/datasets/zjunlp/LongDS) |
| [Agent Durability Lab 对照](../problems/Agent-Durability-Lab/ambiguous-effect.md) | [公开故障用例 `ambiguous-effect`](https://github.com/sjarmak/agent-durability-lab/blob/68a3d73a9d1bafe12d5be188624a802fc11404df/benchmarks/agent-durability/contract-v1.json#L31-L36) |
| [DynaRev 对照](04-running-and-release.md#dynarev-同轮补充对照) | [DynaRev 公开原题](https://github.com/zsq259/DynaRev)：邮轮追加要求、Apple 换型号、AKC 条件覆盖 |
| [Marathon 对照](../problems/marathon/marathon-0.md) | [CTXAgent 公开用例 `marathon:0`](https://github.com/MatthiasHBusch/CTXAgent/blob/77ec7a9e9127e3258b035af32dc7f13730979902/bench/tasks_mix.py) |
| [Skill-Use-Bench 对照](../problems/Skill-Use-Bench/SF03_t1_merge_unordered.md) | [公开 PDF 合并用例 `SF03_t1_merge_unordered`](https://github.com/JinyiHan99/Skill-Use-Bench/blob/1a80e93479e1a9f5ce4be2e27550edaf7f9d6ffc/benchmark/pdftk-server/tasks/t1_merge_unordered.yaml) |
| [BrowseComp-Plus 对照](../../evals/BrowseComp-Plus/README.md) | [公开检索问答、语料及预计算向量](https://huggingface.co/collections/Tevatron/browsecomp-plus) |

[Toolathlon MCP 接线、文件隔离与 PDF 交付](04-running-and-release.md#toolathlon-mcp-验证)使用上游工具配置和镜像，按实际边界记录支持证据。工作区和 PDF 用例共享[对话预算配置](04-running-and-release.md#对话预算)，可通过[并行入口](04-running-and-release.md#多用例并行执行)批量调度。

[Canvas 对照](04-running-and-release.md#canvas-未提交测验与作业的-csv-交付)覆盖评测工作区读写、会话级 Python 装配及官方 Agent 的执行材料隔离。

地图用例可使用[评测专用的 SerpApi 接入](04-running-and-release.md#serpapi-地图工具)。

Redis Helm 用例支持[官方 Agent 与 personalAgent 对照](04-running-and-release.md#redis-helm-官方-agent-对照)。

Toolathlon 配对运行使用[共用 MCP 工具清单](04-running-and-release.md#toolathlon-共用-mcp-工具清单)，并从实际模型请求核对工具可用性。

## 外部 Agent 共用部署

[DeepSeek Harness 评测部署](../../evals/deepseek-harness-deployment.md)提供共享检出、构建和原生 Bash 运行入口。[Toolathlon 对照](../../evals/Toolathlon/DEPLOYMENT.md#deepseek-harness-对照)维护任务专用配置和历史结果。

[BobFlow 评测部署](../../evals/bobflow-deployment.md)提供独立检出、上游运行时和 LongDS 验收条件。

## Conversation 用户结果采集

LongDS 和 Toolathlon 从同一[正式 HTTP 流程](04-running-and-release.md#conversation-评测共用入口)准备原件并提交对话，各自保留数据集材料清单、环境和评分。新增 Conversation 用户结果评测沿用这条链路，见[评测模块规范](../../evals/AGENTS.md#2-canonical-owner-与写入口)。

## 验证与结果边界

现行运行范围以上述公开数据集为准。历史自建用例、夹具、评分和晋级记录按原版本查阅。发布资格按目标版本的实际证据判断。[评测盘点](02-current-case-inventory.md) · [运行与归档](04-running-and-release.md#公开数据集运行) · [证据分类](01-evidence-classes.md)

历史方法和结果见 [baseline-first 审计](03-baseline-first-audit.md)、[旧 E2E 矩阵观测记录](05-observability-metrics.md)与 [Open / Galileo 历史检索报告](retrieval-benchmark-20260709.md)。
