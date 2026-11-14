# 评测体系索引

当前 `evals/` 保留以下公开数据集的评测及其共用工具。数据集发布者提供原始问题、语料与评分参考，仓库维护加载、执行适配和指标计算。

## 公开数据集评测

| 评测入口 | 数据来源 |
| --- | --- |
| [Open RAGBench](../../evals/open_ragbench/README.md) | [Vectara 数据集](https://huggingface.co/datasets/vectara/open_ragbench) |
| [MultiHopRAG](../../evals/multihoprag/README.md) | [MultiHopRAG 数据集](https://huggingface.co/datasets/yixuantt/MultiHopRAG) |
| [Galileo RAGBench](../../evals/galileo_ragbench/README.md) | [Galileo 数据集](https://huggingface.co/datasets/galileo-ai/ragbench) |
| [LongDS](04-running-and-release.md#公开数据集运行) | [LongDS 数据集](https://huggingface.co/datasets/zjunlp/LongDS) |

[Toolathlon MCP 接线、文件隔离与 PDF 交付](04-running-and-release.md#toolathlon-mcp-验证)使用上游工具配置和镜像，按实际边界记录支持证据。工作区和 PDF 用例共享[对话预算配置](04-running-and-release.md#对话预算)，可通过[并行入口](04-running-and-release.md#多用例并行执行)批量调度。

地图用例可使用[评测专用的 SerpApi 接入](04-running-and-release.md#serpapi-地图工具)。

Redis Helm 用例支持[官方 Agent 与 personalAgent 对照](04-running-and-release.md#redis-helm-官方-agent-对照)。

## 验证与结果边界

本次清理以数据集来源为保留依据。项目自建设例、专用夹具、评分与晋级入口从当前工作树退出。清理前的用例与证据按原版本查阅。[历史用例盘点](02-current-case-inventory.md)

本次验收检查保留目录及依赖、默认用例收集、CI 和文档引用。三套检索评测分别用同一缓存、配置与单样本对比指标。LongDS 复核公开题目、正式 HTTP 采集入口与已有封存的用量结果。历史记录保留原身份，发布资格按实际证据判断。[运行与归档](04-running-and-release.md#公开数据集运行) · [评测规范](../../evals/AGENTS.md) · [证据分类](01-evidence-classes.md)

历史方法和结果见 [baseline-first 审计](03-baseline-first-audit.md)、[观测指标](05-observability-metrics.md)与 [Open / Galileo 历史检索报告](retrieval-benchmark-20260709.md)。
