# BrowseComp-Plus 对照评测

使用 BrowseComp-Plus 固定语料，对照 personalAgent 和 DeepSeek Harness 的检索问答结果。评测只改动本次运行配置，personalAgent 关闭 Conversation Goal。

## 样本与验收

| 需求 | 执行与判据 |
| --- | --- |
| BCP-1 同题同资料 | 固定发布方数据版本，按 Hugging Face `test` split 原顺序取前五题 `769`–`773`。两边各以新会话收到未经改写的英文原题，各跑一次。 |
| BCP-2 共用检索 | 下载全部四份官方 `Qwen3-Embedding-8B` 文档向量，以同一份 FAISS 内积索引提供 MCP `search`、`get_document`。正文通过 Hugging Face Dataset Viewer 按命中 ID 读取，逐次核对固定语料修订和截断标记。沿用上游 top-5 和 512 token 摘要。查询经硅基流动的同名 4096 维模型编码，使用上游查询前缀并归一化。 |
| BCP-3 隔离与运行 | personalAgent 经正式 Conversation HTTP，沿用评测开关并设置 `PERSONAL_AGENT_CONVERSATION_GOAL_MODE=disabled`。DeepSeek Harness 经官方 SDK，MCP 外的文件、命令、联网工具不进入模型。两边使用同一聊天模型和服务方，保留各自原生 Prompt。 |
| BCP-4 独立评分 | 双方运行产物封存后，用官方 `Qwen/Qwen3-32B`、评分模板和解析规则对最终答复做语义评分，沿用上游采样参数，改用已配置的硅基流动推理接口。评分材料单独保存。无答复、运行失败和判分失败单列。 |

评测适配层复用仓库的 Conversation HTTP、DeepSeek SDK 容器及 MCP 配置。数据发布方拥有题目、标签、向量和文档。共用服务的数据入口限于向量和正文。每次运行归档实际模型设置、原始双方轨迹、检索调用、样本状态与校验和。五道题用于定向对照。

本机完整语料下载耗时较长，Dataset Viewer 支持按多个 ID 读取原始正文，响应携带语料修订和截断标记。因此本接入只需预下载向量分片和 tokenizer。缺文档、截断或版本不符时以工具失败记录。

单题每方上限 40 个模型步骤。对照配置让本 Agent 通过 `PERSONAL_AGENT_INTERACTION_MAX_TOOL_CALLS=unlimited` 采用 DeepSeek Harness 的工具次数口径，保留 200 万总 token 上限。600 秒对应 HTTP 读取等待和 DeepSeek SDK 单次通知等待。先做环境预检，验证真实 MCP 工具边界及其中立查询。完成预检后跑已选配对，记录服务故障和预算终态。[工具次数对齐与复跑判据](../../docs/budge/README.md#browsecomp-plus-工具次数对齐)

本 Agent 的实际模型请求须出现两个检索工具，后续请求可随运行预算撤下工具。评分读取已封存的正式 HTTP 终态和实际工具声明。达到预算后的 `limitation` 计入已执行且未交付完整答复。

## 运行

准备 Docker Desktop、DeepSeek SDK 检出 `4b399c39a6d1479cd84ca591b4d7c88e24d38a96` 和 `personal-agent-dsh-runtime:0.2.2-rc.5` 镜像。模型配置复用 `.env` 的 `STRUCTURED_*` 和硅基流动 `EMBEDDING_BASE_URL`、`EMBEDDING_API_KEY`。 [DeepSeek Harness 部署](../deepseek-harness-deployment.md)

```powershell
$cache = '.tmp/browsecomp-plus-2026-11-26'
New-Item -ItemType Directory -Force $cache | Out-Null
git clone https://github.com/texttron/BrowseComp-Plus.git "$cache/upstream"
git -C "$cache/upstream" checkout --detach 046949032b0328319cc9a02663a759ec601d9402
uv pip install --python .venv/Scripts/python.exe 'mcp==1.27.0' 'faiss-cpu==1.13.2' 'tokenizers==0.22.2' 'datasets==4.4.1'
.venv/Scripts/python.exe -B -X utf8 -m evals.BrowseComp-Plus.run collect --upstream "$cache/upstream"
.venv/Scripts/python.exe -B -X utf8 -m evals.BrowseComp-Plus.run download --cache $cache
.venv/Scripts/python.exe -B -X utf8 -m evals.BrowseComp-Plus.run run --upstream "$cache/upstream" --cache $cache --output "$cache/run-01"
.venv/Scripts/python.exe -B -X utf8 -m evals.BrowseComp-Plus.run grade --upstream "$cache/upstream" --capture "$cache/run-01" --output "$cache/grade-01"
```

[上游评测仓库](https://github.com/texttron/BrowseComp-Plus/tree/046949032b0328319cc9a02663a759ec601d9402) · [题目](https://huggingface.co/datasets/Tevatron/browsecomp-plus) · [语料](https://huggingface.co/datasets/Tevatron/browsecomp-plus-corpus) · [8B 向量](https://huggingface.co/datasets/Tevatron/browsecomp-plus-indexes/tree/main/qwen3-embedding-8b)

[2026-11-26 五题对照结果](../../docs/problems/BrowseComp-Plus/2026-11-26-five-questions.md)

追加 `--query-id 773` 可定向采集一对。评分按采集计划中的题号运行。每次复跑使用新输出目录。
