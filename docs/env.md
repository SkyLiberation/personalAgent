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
PERSONAL_AGENT_GRAPH_SEARCH_LIMIT=10
PERSONAL_AGENT_GRAPH_SEARCH_CITATION_LIMIT=20
PERSONAL_AGENT_POSTGRES_URL=postgresql://postgres:postgres@127.0.0.1:5432/personal_agent?sslmode=disable
PERSONAL_AGENT_FEISHU_ENABLED=false
FEISHU_APP_ID=cli_xxx
FEISHU_APP_SECRET=xxx
FEISHU_BASE_URL=https://open.feishu.cn
```

说明：

- `PERSONAL_AGENT_POSTGRES_URL` 为必填项。知识、复习、待确认操作、跨请求状态及 LangGraph checkpoint 都以 Postgres 为唯一持久化存储。
- `uploads/` 仍用于保存原始上传文件；数据库保存其引用及提取后的知识内容。

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
OPENAI_BASE_URL=https://api.deepseek.com
OPENAI_API_KEY=your_llm_key
OPENAI_MODEL=gpt-4.1-mini
OPENAI_SMALL_MODEL=gpt-4.1-nano
```

`OPENAI_*` 用于入口路由、任务规划、重规划、直接回答和 ReAct 等业务 LLM 调用。Graphiti 抽取模型使用下方独立的 `PERSONAL_AGENT_GRAPHITI_LLM_*` 配置，不受这组配置影响。Ask 前的 `query_planner.py` 优先复用 LangExtract 的 `PERSONAL_AGENT_EXTRACT_*` 配置，以便使用 `qwen3-coder-flash` 的 strict `json_schema` 输出；未配置 extract key 时才回退到 `OPENAI_SMALL_MODEL`。

默认值（不设环境变量时）：
- `OPENAI_MODEL`：`gpt-4.1-mini`
- `OPENAI_SMALL_MODEL`：`gpt-4.1-nano`

可选调参：

```env
PERSONAL_AGENT_LLM_PROVIDER=  # LLM provider，默认 "stub"（仅开发调试用，生产需设 openai）
PERSONAL_AGENT_OPENAI_TIMEOUT_SECONDS=30
PERSONAL_AGENT_OPENAI_MAX_RETRIES=2
```

## Ask 组件配置

```env
PERSONAL_AGENT_ASK_RERANKER=heuristic
PERSONAL_AGENT_ASK_CANDIDATE_ENRICHER=parent_child
PERSONAL_AGENT_ASK_PARENT_CHILD_TOP_N=3
PERSONAL_AGENT_ASK_PARENT_CHILD_MIN_OVERLAP=2
PERSONAL_AGENT_ASK_NEIGHBOR_CHUNK_WINDOW=0
PERSONAL_AGENT_ASK_GRAPH_NOTE_EVIDENCE_MODE=all
PERSONAL_AGENT_ASK_GRAPH_NOTE_EVIDENCE_MIN_OVERLAP=2
PERSONAL_AGENT_ASK_CONTEXT_MAX_ITEMS=12
PERSONAL_AGENT_ASK_CONTEXT_CHAR_BUDGET=5000
PERSONAL_AGENT_ASK_LLM_RERANK_TOP_N=20
PERSONAL_AGENT_ASK_LLM_RERANK_TIMEOUT_SECONDS=20
PERSONAL_AGENT_ASK_LLM_RERANK_MODEL=
```

- `PERSONAL_AGENT_ASK_RERANKER` 当前可选 `heuristic` / `llm`。默认 `heuristic` 保持原有稳定路径；`llm` 会先用启发式召回 top N，再用 strict `json_schema` listwise rerank 重排证据。
- `PERSONAL_AGENT_ASK_CANDIDATE_ENRICHER` 当前可选 `parent_child` / `none`。默认 `parent_child` 会在 rerank 前补齐 parent 命中的高相关 child sections，以及 child 命中的 parent。邻近 chunk 默认不补，避免给 LLM rerank 注入过多相邻但不直接回答的候选。
- `PERSONAL_AGENT_ASK_GRAPH_NOTE_EVIDENCE_MODE` 当前可选 `all` / `cited_overlap` / `none`。`all` 会把 Graphiti 映射回来的 notes 作为 evidence 交给 ContextPack；`cited_overlap` 只放入 citation 命中或 query overlap 足够的 notes；`none` 关闭该桥接。
- LLM rerank 优先复用 `PERSONAL_AGENT_EXTRACT_*` 的 DashScope/qwen 配置；未配置 extract key 时回退到 `OPENAI_*`。
- `PERSONAL_AGENT_ASK_CONTEXT_MAX_ITEMS` 和 `PERSONAL_AGENT_ASK_CONTEXT_CHAR_BUDGET` 控制进入 prompt 的 evidence 数量和字符预算。

## Embedding 配置

```env
EMBEDDING_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
EMBEDDING_API_KEY=your_embedding_key
OPENAI_EMBEDDING_MODEL=text-embedding-3-small
```

默认值：`OPENAI_EMBEDDING_MODEL` 默认为 `text-embedding-3-small`。

可选：

```env
PERSONAL_AGENT_EMBEDDING_PROVIDER=local  # embedding provider，默认 "local"
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
- `PERSONAL_AGENT_GRAPH_SEARCH_LIMIT` 控制 Graphiti search 原始返回规模，`PERSONAL_AGENT_GRAPH_SEARCH_CITATION_LIMIT` 控制项目侧从 Graphiti edges 中保留多少 citation hits 用于 episode -> note 映射。
- 如果 Neo4j 或模型配置缺失，图谱写入/检索会失败，日志中会提示具体原因

## Firecrawl 配置

网页抓取工具使用的 Firecrawl API：

```env
FIRECRAWL_API_KEY=your_firecrawl_key
FIRECRAWL_BASE_URL=https://api.firecrawl.dev
FIRECRAWL_TIMEOUT_MS=60000
```

## 图谱同步调参

```env
PERSONAL_AGENT_GRAPH_SYNC_MAX_ATTEMPTS=3
PERSONAL_AGENT_GRAPH_SYNC_INITIAL_BACKOFF_SECONDS=2.0
PERSONAL_AGENT_GRAPH_SYNC_BACKOFF_MULTIPLIER=2.0
PERSONAL_AGENT_GRAPH_SYNC_MAX_BACKOFF_SECONDS=20.0
```

## Graphiti 内部调参

```env
PERSONAL_AGENT_GRAPHITI_ADD_EPISODE_TIMEOUT_SECONDS=900
PERSONAL_AGENT_GRAPHITI_SEARCH_TIMEOUT_SECONDS=45
PERSONAL_AGENT_GRAPHITI_EPISODE_MAX_CHARS=8000
PERSONAL_AGENT_GRAPHITI_CONTENT_FILTER_FALLBACK=true
```

## 飞书补充配置

```env
PERSONAL_AGENT_FEISHU_USE_DEFAULT_USER=true  # 飞书用户未映射时是否回退到默认用户
```

## 鉴权、限流与 CORS

```env
PERSONAL_AGENT_API_KEYS=key1:user1,key2:user2  # API Key → 用户映射，多个用逗号分隔
PERSONAL_AGENT_RATE_LIMIT_REQUESTS=60
PERSONAL_AGENT_RATE_LIMIT_WINDOW_SECONDS=60
PERSONAL_AGENT_CORS_ORIGINS=http://localhost:3000  # 多个用逗号分隔
```

## 回答校验

```env
AGENT_MAX_VERIFY_RETRIES=1  # 答案校验失败后最大重试次数
```

## LangGraph 总编排与 Checkpoint 配置

```env
PERSONAL_AGENT_POSTGRES_URL=postgresql://postgres:postgres@127.0.0.1:5432/personal_agent?sslmode=disable
```

说明：

- checkpoint 固定使用 `langgraph-checkpoint-postgres`，与业务表共享 `PERSONAL_AGENT_POSTGRES_URL`
- 不提供内存或 SQLite fallback，也不读取原有 SQLite checkpoint 文件
- entry 请求默认走统一的 `orchestration_graph`，并在图节点后写入 checkpoint
- 运行 `uv run python scripts/export_thread_checkpoints.py <thread_id>` 会将该线程所有持久化 checkpoint 导出到 `scripts/assets/`
