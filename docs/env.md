# 环境变量

参考 [.env.example](../.env.example)。

## 基础配置

```env
PERSONAL_AGENT_DATA_DIR=./data
PERSONAL_AGENT_LOG_LEVEL=INFO
PERSONAL_AGENT_DEFAULT_USER=default
PERSONAL_AGENT_GRAPHITI_ENABLED=false
PERSONAL_AGENT_GRAPHITI_URI=bolt://localhost:7687
PERSONAL_AGENT_GRAPHITI_USER=neo4j
PERSONAL_AGENT_GRAPHITI_PASSWORD=password
PERSONAL_AGENT_GRAPHITI_GROUP_PREFIX=personal-agent
PERSONAL_AGENT_POSTGRES_URL=postgresql://postgres:postgres@127.0.0.1:5432/personal_agent?sslmode=disable
```

说明：

- `PERSONAL_AGENT_DATA_DIR` 下当前默认会生成：
  - `notes.json`
  - `reviews.json`
  - `conversations.json`
  - `uploads/`
- 如果配置了 `PERSONAL_AGENT_POSTGRES_URL`，问答历史会额外持久化到 `Postgres.ask_history`

## LLM 配置

```env
OPENAI_BASE_URL=https://api.deepseek.com
OPENAI_API_KEY=your_llm_key
OPENAI_MODEL=deepseek-v4-flash
OPENAI_SMALL_MODEL=deepseek-v4-flash
```

## Embedding 配置

```env
EMBEDDING_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
EMBEDDING_API_KEY=your_embedding_key
OPENAI_EMBEDDING_MODEL=text-embedding-v4
```

## Graphiti 启用条件

只有同时满足下面条件，Graphiti 才会真正启用：

1. `PERSONAL_AGENT_GRAPHITI_ENABLED=true`
2. Neo4j 可连接
3. `OPENAI_API_KEY`、`OPENAI_BASE_URL`、`OPENAI_MODEL` 已配置
4. `EMBEDDING_API_KEY` 或 `OPENAI_API_KEY` 可用
5. `EMBEDDING_BASE_URL` 或 `OPENAI_BASE_URL` 可用

补充说明：

- 当前 `OPENAI_*` 这组变量既用于 Graphiti 抽取与检索时的 LLM，也用于 `ask` 阶段的生成式回答
- 如果这组变量未配置，`ask` 仍可工作，但会回退到较弱的本地回答或检索式回答
