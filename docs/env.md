# 环境变量

参考 [.env.example](../.env.example)。

## 基础配置

```env
PERSONAL_AGENT_DATA_DIR=./data
PERSONAL_AGENT_LOG_LEVEL=INFO
PERSONAL_AGENT_DEFAULT_USER=default
PERSONAL_AGENT_GRAPHITI_URI=bolt://localhost:7687
PERSONAL_AGENT_GRAPHITI_USER=neo4j
PERSONAL_AGENT_GRAPHITI_PASSWORD=password
PERSONAL_AGENT_GRAPHITI_GROUP_PREFIX=personal-agent
PERSONAL_AGENT_GRAPH_SEARCH_STRATEGY=hybrid_rrf
PERSONAL_AGENT_POSTGRES_URL=postgresql://postgres:postgres@127.0.0.1:5432/personal_agent?sslmode=disable
PERSONAL_AGENT_FEISHU_ENABLED=false
FEISHU_APP_ID=cli_xxx
FEISHU_APP_SECRET=xxx
FEISHU_BASE_URL=https://open.feishu.cn
```

说明：

- `PERSONAL_AGENT_DATA_DIR` 下当前默认会生成：
  - `notes.json`
  - `reviews.json`
  - `conversations.json`
  - `uploads/`
- 如果配置了 `PERSONAL_AGENT_POSTGRES_URL`，问答历史会额外持久化到 `Postgres.ask_history`

## 飞书配置

- `PERSONAL_AGENT_FEISHU_ENABLED=true` 后才会启用飞书集成
- `FEISHU_APP_ID` 和 `FEISHU_APP_SECRET` 用于：
  - 建立飞书长连接事件监听
  - 把 Agent 的处理结果回发到飞书会话
- `FEISHU_BASE_URL` 默认使用 `https://open.feishu.cn`

当前项目默认推荐使用“长连接接收事件”模式，因此通常只要配置：

```env
PERSONAL_AGENT_FEISHU_ENABLED=true
FEISHU_APP_ID=cli_xxx
FEISHU_APP_SECRET=xxx
```

即可完成本地开发接入。

## LLM 配置

```env
OPENAI_BASE_URL=https://api.moonshot.cn/v1
OPENAI_API_KEY=your_llm_key
OPENAI_MODEL=kimi-k2.5
OPENAI_SMALL_MODEL=kimi-k2.5
```

## Embedding 配置

```env
EMBEDDING_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
EMBEDDING_API_KEY=your_embedding_key
OPENAI_EMBEDDING_MODEL=text-embedding-v4
```

## Graphiti 配置条件

当前工程默认以 Graphiti 为核心能力，不再提供图谱启停开关。需要同时满足下面条件，图谱链路才可正常工作：

1. Neo4j 可连接
2. `PERSONAL_AGENT_GRAPHITI_LLM_*` 或回退使用的 `OPENAI_*` 模型配置已齐全
3. `EMBEDDING_API_KEY` 或 `OPENAI_API_KEY` 可用
4. `EMBEDDING_BASE_URL` 或 `OPENAI_BASE_URL` 可用

补充说明：

- Graphiti 抽取模型可单独覆盖；未设置以下变量时才回退使用 `OPENAI_*`：

```env
PERSONAL_AGENT_GRAPHITI_LLM_API_KEY=your_graphiti_llm_key
PERSONAL_AGENT_GRAPHITI_LLM_BASE_URL=https://api.moonshot.cn/v1
PERSONAL_AGENT_GRAPHITI_LLM_MODEL=kimi-k2.5
PERSONAL_AGENT_GRAPHITI_LLM_SMALL_MODEL=kimi-k2.5
```

- Kimi Graphiti 客户端会发送关闭 thinking 的参数，并在 Graphiti 提供响应模型时使用 `json_schema` 结构化输出
- `PERSONAL_AGENT_GRAPH_SEARCH_STRATEGY` 用于切换图谱检索策略，当前可选：
  - `hybrid_rrf`：默认策略，Graphiti combined hybrid search + RRF
  - `hybrid_mmr`：Graphiti combined hybrid search + MMR
  - `hybrid_cross_encoder`：Graphiti combined hybrid search + BFS + cross encoder
  - `edge_rrf`：只检索关系边，RRF 重排
  - `edge_node_distance`：只检索关系边，node distance 重排
- 如果 Neo4j 或模型配置缺失，图谱写入/检索会失败，日志中会提示具体原因

## LangGraph 总编排与 Checkpoint 配置

```env
PERSONAL_AGENT_LANGGRAPH_CHECKPOINT_BACKEND=sqlite
PERSONAL_AGENT_LANGGRAPH_CHECKPOINT_PATH=./data/langgraph_checkpoints.sqlite
```

说明：

- `PERSONAL_AGENT_LANGGRAPH_CHECKPOINT_BACKEND`：推荐使用 `sqlite`，从而可以在独立脚本中读取运行 checkpoint；`memory` 仅在当前服务进程存活期间可读
- `PERSONAL_AGENT_LANGGRAPH_CHECKPOINT_PATH`：SQLite checkpoint 数据库路径
- entry 请求默认走统一的 `orchestration_graph`，并在图节点后写入 checkpoint
- 运行 `uv run python scripts/export_thread_checkpoints.py <thread_id>` 会将该线程所有持久化 checkpoint 导出到 `scripts/assets/`
