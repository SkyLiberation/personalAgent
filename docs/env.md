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
