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

- `PERSONAL_AGENT_POSTGRES_URL` 为必填项。Personal Knowledge/知识、Review、受治理执行、
  Investigation journal、worker queue 等各自通过生产 Store 使用 Postgres。普通 Conversation
  的 Interaction trace 当前由 `PERSONAL_AGENT_DATA_DIR/interaction_runs` 下的
  `FileInteractionJournal` 保存；历史 LangGraph checkpoint 表不是当前普通对话真源。
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

## Review Digest 飞书触达配置

Review Digest 是应用内 job 能力，环境变量只作为当前阶段的配置型订阅来源；后续可替换为数据库订阅表。

```env
PERSONAL_AGENT_REVIEW_DIGEST_ENABLED=false
PERSONAL_AGENT_REVIEW_DIGEST_USER_ID=default
PERSONAL_AGENT_REVIEW_DIGEST_FEISHU_CHAT_IDS=oc_xxx,oc_yyy
PERSONAL_AGENT_REVIEW_DIGEST_TIME=09:00
PERSONAL_AGENT_REVIEW_DIGEST_TIMEZONE=Asia/Shanghai
PERSONAL_AGENT_REVIEW_DIGEST_SCHEDULER_ENABLED=false
PERSONAL_AGENT_REVIEW_DIGEST_SCHEDULER_TICK_SECONDS=60
```

- `PERSONAL_AGENT_REVIEW_DIGEST_ENABLED=true` 后，`review-digest` job 会从配置生成飞书订阅目标。
- `PERSONAL_AGENT_REVIEW_DIGEST_FEISHU_CHAT_IDS` 是飞书会话 ID 列表，多个用逗号分隔。
- `PERSONAL_AGENT_REVIEW_DIGEST_USER_ID` 决定读取哪个用户的长期知识和复习卡。
- `PERSONAL_AGENT_REVIEW_DIGEST_TIME` / `TIMEZONE` 描述订阅调度语义；当前 CLI job 不自行常驻调度，应用内 scheduler 或外部触发器都应调用内部 job 入口。
- `PERSONAL_AGENT_REVIEW_DIGEST_SCHEDULER_ENABLED=true` 时，FastAPI 进程启动应用内 scheduler，按订阅时间 tick 并调用内部 job。
- `PERSONAL_AGENT_REVIEW_DIGEST_SCHEDULER_TICK_SECONDS` 控制应用内 scheduler tick 间隔，最小按 10 秒处理。

手动触发一次内部 job：

```bash
uv run personal-agent review-digest
```

也可以覆盖本次发送目标：

```bash
uv run personal-agent review-digest --user-id default --chat-id oc_xxx
```

cron / systemd timer / K8s CronJob 可以周期性调用同一个内部 job，例如每分钟唤醒一次；业务幂等由 `digest_deliveries` 的 `subscription_id + digest_date` 保证：

```cron
* * * * * cd /path/to/personalAgent && uv run personal-agent review-digest
```

飞书内也可以直接管理当前会话订阅：

- `订阅简报`
- `取消订阅简报`
- `简报时间 08:30`

## 知识缺口主动追问

知识缺口追问是 Review Digest 之上的主动能力：后台检测知识孤岛与潜在矛盾，按独立时间主动向用户提问。复用 Review Digest 的飞书订阅目标，但调度时间独立（默认 20:00，与日报错开）。详见 [proactive-knowledge-loop.md](proactive-knowledge-loop.md)。

```env
PERSONAL_AGENT_KNOWLEDGE_GAP_ENABLED=false
PERSONAL_AGENT_KNOWLEDGE_GAP_TIME=20:00
PERSONAL_AGENT_KNOWLEDGE_GAP_SCHEDULER_ENABLED=false
PERSONAL_AGENT_KNOWLEDGE_GAP_SCHEDULER_TICK_SECONDS=300
PERSONAL_AGENT_KNOWLEDGE_GAP_MAX_GAPS=3
PERSONAL_AGENT_KNOWLEDGE_GAP_MIN_DEGREE=1
PERSONAL_AGENT_KNOWLEDGE_GAP_RECENT_NOTE_LIMIT=30
```

- `PERSONAL_AGENT_KNOWLEDGE_GAP_ENABLED=true` 启用检测；`SCHEDULER_ENABLED=true` 时 FastAPI 进程启动应用内 runner。
- `MAX_GAPS` 限制单次提问条数，避免打扰用户。
- `MIN_DEGREE` 是判定知识孤岛的图谱连接度阈值；`RECENT_NOTE_LIMIT` 是矛盾检测扫描的最近笔记数。
- 同日去重由 `knowledge_gap_deliveries` 表的 `gap:{subscription_id}:{date}` 主键保证，跨进程重启幂等。
- 提问措辞在 `OPENAI_*` 配置可用时经 LLM 改写，否则使用确定性模板。

## LLM 配置

```env
STRUCTURED_BASE_URL=https://api.xiaomimimo.com/v1
STRUCTURED_API_KEY=your_mimo_key
STRUCTURED_MODEL=mimo-v2.5
STRUCTURED_OUTPUT_TRANSPORT=json_schema
STRUCTURED_EXTRA_BODY={"thinking":{"type":"disabled"}}
PERSONAL_AGENT_STRUCTURED_TIMEOUT_SECONDS=60
PERSONAL_AGENT_STRUCTURED_MAX_RETRIES=2

OPENAI_BASE_URL=${STRUCTURED_BASE_URL}
OPENAI_API_KEY=${STRUCTURED_API_KEY}
OPENAI_MODEL=${STRUCTURED_MODEL}
OPENAI_SMALL_MODEL=${STRUCTURED_MODEL}
PERSONAL_AGENT_GRAPHITI_LLM_BASE_URL=${STRUCTURED_BASE_URL}
PERSONAL_AGENT_GRAPHITI_LLM_API_KEY=${STRUCTURED_API_KEY}
PERSONAL_AGENT_GRAPHITI_LLM_MODEL=${STRUCTURED_MODEL}
PERSONAL_AGENT_GRAPHITI_LLM_SMALL_MODEL=${STRUCTURED_MODEL}
PERSONAL_AGENT_EXTRACT_BASE_URL=${STRUCTURED_BASE_URL}
PERSONAL_AGENT_EXTRACT_API_KEY=${STRUCTURED_API_KEY}
PERSONAL_AGENT_EXTRACT_MODEL=${STRUCTURED_MODEL}
```

`STRUCTURED_*` 是生成式模型的 canonical 配置。直接回答、结构化决策、Graphiti 生成、
LangExtract 在没有显式 Adapter override 时均从这里解析；当前部署统一使用
`mimo-v2.5`。embedding 和 transcription 不属于生成式模型切换，继续使用
`EMBEDDING_*` / `OPENAI_EMBEDDING_MODEL` 与 `OPENAI_TRANSCRIPTION_MODEL`。

MiMo 当前使用原生 `json_schema`，并通过 `STRUCTURED_EXTRA_BODY` 关闭思考模式。默认
思考模式曾把结构化输出预算耗尽为无正文；`json_object` 在正式入口又无法稳定满足
`WorkingPlan` Schema，因此二者都不是当前配置。

生命周期选择的正式 E2E 已在当前 `max_retries=2` 配置下达到
`20/20 background_started`、`20/20` 返回 ProjectReference、最终请求失败为 0，P95
为 36.91 秒。零重试同输入组也达到 `20/20`，P95 为 36.04 秒；因此生命周期结果不依赖
技术重试。该结果证明自然后台请求能够进入独立调查项目，不证明后台报告已经最终交付，
也不证明 MiMo 的所有语义操作都达到发布门槛。详细归档和边界见
[设计优化清单](future/design-optimization-backlog.md) §3。

后续后台最终报告 baseline 在同样 20 个输入中只创建 18 个 Project，说明跨重复样本的
生命周期选择仍有方差。该 baseline 为 `0/20 delivered`，且只有 3 次真实 GPT Researcher
调用；因此检索候选数 1 与 5 的对照没有进入 target，当前
`PERSONAL_AGENT_GPT_RESEARCHER_A2A_MAX_SEARCH_RESULTS` 继续保持为 1。

`STRUCTURED_*` 也是相邻 GPT Researcher `docker-compose.deepseek.yml` 的唯一配置源；通过
`docker compose --env-file ../personalAgent/.env` 注入，不复制令牌。OpenAI SDK transport
不做隐式 retry，`*_MAX_RETRIES` 由 typed model-operation decorator 唯一执行；流式响应
在出现部分输出后不会自动重放。release E2E 默认使用
`PERSONAL_AGENT_E2E_MODEL_PROFILE=configured` 和 120 秒单请求 timeout。

默认值（不设环境变量时）：
- 所有生成式 Adapter：`deepseek-v4-flash`
- `OPENAI_EMBEDDING_MODEL`：`BAAI/bge-m3`
- `OPENAI_TRANSCRIPTION_MODEL`：`whisper-1`

可选调参：

```env
PERSONAL_AGENT_LLM_PROVIDER=  # LLM provider，默认 "stub"（仅开发调试用，生产需设 openai）
PERSONAL_AGENT_OPENAI_TIMEOUT_SECONDS=30
PERSONAL_AGENT_OPENAI_MAX_RETRIES=2
```

## Ask 组件配置

```env
PERSONAL_AGENT_ASK_RERANKER=heuristic
PERSONAL_AGENT_ASK_GRAPH_PROVIDER=graphiti
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
- `PERSONAL_AGENT_ASK_GRAPH_PROVIDER` 当前只接受 `graphiti` / `structural` / `hybrid`。
  `graphiti` 使用在线实体关系图谱；`structural` 使用本地 parent-section 结构召回；
  `hybrid` 组合 structural + Graphiti。未知值在配置加载阶段 fail closed，不会静默改绑 Provider。
- `PERSONAL_AGENT_ASK_CANDIDATE_ENRICHER` 当前可选 `parent_child` / `none`。默认 `parent_child` 会在 rerank 前补齐 parent 命中的高相关 child sections，以及 child 命中的 parent。邻近 chunk 默认不补，避免给 LLM rerank 注入过多相邻但不直接回答的候选。
- `PERSONAL_AGENT_ASK_GRAPH_NOTE_EVIDENCE_MODE` 当前可选 `all` / `cited_overlap` / `none`。`all` 会把 Graphiti 映射回来的 notes 作为 evidence 交给 ContextPack；`cited_overlap` 只放入 citation 命中或 query overlap 足够的 notes；`none` 关闭该桥接。
- LLM rerank 优先复用 `PERSONAL_AGENT_EXTRACT_*` 的 DashScope/qwen 配置；未配置 extract key 时回退到 `OPENAI_*`。
- `PERSONAL_AGENT_ASK_CONTEXT_MAX_ITEMS` 和 `PERSONAL_AGENT_ASK_CONTEXT_CHAR_BUDGET` 控制进入 prompt 的 evidence 数量和字符预算。

## Embedding 配置

```env
EMBEDDING_BASE_URL=https://api.siliconflow.cn/v1
EMBEDDING_API_KEY=your_embedding_key
OPENAI_EMBEDDING_MODEL=BAAI/bge-m3
```

推荐使用 SiliconFlow 的 `BAAI/bge-m3`。`EMBEDDING_BASE_URL` 填 API
根路径 `/v1`，OpenAI-compatible 客户端会自动追加 `/embeddings`。

可选：

```env
PERSONAL_AGENT_EMBEDDING_PROVIDER=local  # embedding provider，默认 "local"
```

## Graphiti 配置条件

当前工程默认以 Graphiti 为核心能力，不再提供图谱启停开关。需要同时满足下面条件，图谱链路才可正常工作：

1. Neo4j 可连接
2. canonical `STRUCTURED_*` 或显式 `PERSONAL_AGENT_GRAPHITI_LLM_*` override 已齐全
3. `EMBEDDING_API_KEY` 或 `OPENAI_API_KEY` 可用
4. `EMBEDDING_BASE_URL` 或 `OPENAI_BASE_URL` 可用

补充说明：

- Graphiti 抽取模型可单独覆盖；当前部署直接引用 canonical `STRUCTURED_*`：

```env
PERSONAL_AGENT_GRAPHITI_LLM_API_KEY=${STRUCTURED_API_KEY}
PERSONAL_AGENT_GRAPHITI_LLM_BASE_URL=${STRUCTURED_BASE_URL}
PERSONAL_AGENT_GRAPHITI_LLM_MODEL=${STRUCTURED_MODEL}
PERSONAL_AGENT_GRAPHITI_LLM_SMALL_MODEL=${STRUCTURED_MODEL}
```

- Graphiti OpenAI-compatible Adapter 会归一化 reasoning 字段，并在 Graphiti 提供响应模型时使用 `json_schema` 结构化输出
- `PERSONAL_AGENT_GRAPH_SEARCH_STRATEGY` 用于切换图谱检索策略，当前可选：
  - `hybrid_rrf`：默认策略，Graphiti combined hybrid search + RRF
  - `hybrid_mmr`：Graphiti combined hybrid search + MMR
  - `hybrid_cross_encoder`：Graphiti combined hybrid search + BFS + cross encoder
  - `edge_rrf`：只检索关系边，RRF 重排
  - `edge_node_distance`：只检索关系边，node distance 重排
- `PERSONAL_AGENT_GRAPH_SEARCH_LIMIT` 控制 Graphiti search 原始返回规模，`PERSONAL_AGENT_GRAPH_SEARCH_CITATION_LIMIT` 控制项目侧从 Graphiti edges 中保留多少 citation hits 用于 episode -> note 映射。
- 如果 Neo4j 或模型配置缺失，图谱写入/检索会失败，日志中会提示具体原因

## Web 搜索配置

`web_search` 工具的生产默认 Provider 是 `anysearch`，使用通用且唯一的
`PERSONAL_AGENT_WEB_SEARCH_*` 凭据：

```env
PERSONAL_AGENT_WEB_SEARCH_PROVIDER=anysearch
PERSONAL_AGENT_WEB_SEARCH_API_KEY=your_anysearch_api_key
PERSONAL_AGENT_WEB_SEARCH_BASE_URL=https://api.anysearch.com
PERSONAL_AGENT_WEB_SEARCH_TIMEOUT_MS=60000
PERSONAL_AGENT_URL_CAPTURE_PROVIDER=builtin
```

Provider 由 Composition Root 静态绑定，不做运行时 fallback；AnySearch Adapter 使用
`POST /v1/search`、Bearer API Key 和结构化 `data.results`；SerpAPI Adapter 仅保留为显式
历史/对照配置，已移除 Firecrawl Web Search Adapter。
`PERSONAL_AGENT_URL_CAPTURE_PROVIDER` 独立决定 URL 正文读取使用 `firecrawl` 还是 `builtin`；
它是一个单值绑定，不会在执行失败后自动切换 Provider。未显式设置时，有 Firecrawl key 的
环境解析为 `firecrawl`，否则解析为 `builtin`。

## MCP 工具接入

GitHub MCP 有一组一等配置，适合默认启用官方 Docker stdio server 的只读仓库能力：

```env
PERSONAL_AGENT_GITHUB_MCP_ENABLED=true
GITHUB_PAT=your_github_personal_access_token_here
PERSONAL_AGENT_GITHUB_MCP_TOKEN_ENV=GITHUB_PAT
PERSONAL_AGENT_GITHUB_MCP_TOOLS=search_code,get_file_contents,search_repositories
```

启用后会注册：

- `github.search_code`：搜索 GitHub 仓库代码。
- `github.get_file_contents`：读取 GitHub 仓库文件内容。
- `github.search_repositories`：搜索 GitHub 仓库。

这些工具都声明为 `public_agent`、`low` 风险、`external_network`、`github:repo:read`，并通过 ToolGateway 统一执行审计、超时、重试和限流。默认 Docker 启动参数会传入 `GITHUB_READ_ONLY=1`，避免暴露 issue/PR/文件写入类工具。

同时，每个 GitHub MCP mapping 会注册一份 `MCPCapability`：

| Tool | semantic_domains | resource_types | operations | trust / credential / egress / attestation |
| --- | --- | --- | --- | --- |
| `github.search_code` | `codebase` | `repository`, `file`, `code` | `search` | `scoped` / `delegated_token` / `content` / `pinned` |
| `github.get_file_contents` | `codebase`, `docs` | `repository`, `file` | `read` | `scoped` / `delegated_token` / `content` / `pinned` |
| `github.search_repositories` | `codebase`, `repository_discovery` | `repository` | `search` | `scoped` / `delegated_token` / `content` / `pinned` |

Notion MCP 也有一组一等配置，默认只映射 personal knowledge 只读能力：

```env
PERSONAL_AGENT_NOTION_MCP_ENABLED=true
NOTION_TOKEN=your_notion_integration_token_here
PERSONAL_AGENT_NOTION_MCP_TOKEN_ENV=NOTION_TOKEN
PERSONAL_AGENT_NOTION_MCP_TOOLS=API-post-search,API-retrieve-page-markdown
PERSONAL_AGENT_E2E_NOTION_PAGE_ID=<explicit non-sensitive test page id>
PERSONAL_AGENT_E2E_NOTION_EXPECTED_TEXT=PERSONAL_AGENT_NOTION_E18_MARKER
```

启用后会注册：

- `notion.search`：搜索当前 Notion integration 授权可见的页面和 data source。
- `notion.retrieve_page_markdown`：读取指定 Notion 页面 Markdown 正文。

默认 stdio 命令是 `npx -y @notionhq/notion-mcp-server`。这些工具都声明为 `public_agent`、`low` 风险、`external_network`、`notion:personal knowledge:read`，并通过 ToolGateway 统一执行审计、超时、重试和限流。当前 preset 不映射 `update-page-markdown`、`move-page`、评论、data source 更新等写操作；这些能力应作为单独 workflow 接入，并声明中高风险、确认和幂等策略。

每个 Notion MCP mapping 也会注册一份 `MCPCapability`：

| Tool | semantic_domains | resource_types | operations | trust / credential / egress / attestation |
| --- | --- | --- | --- | --- |
| `notion.search` | `knowledge_knowledge`, `docs` | `page`, `data_source` | `search` | `scoped` / `delegated_token` / `content` / `pinned` |
| `notion.retrieve_page_markdown` | `knowledge_knowledge`, `docs` | `page` | `read` | `scoped` / `delegated_token` / `content` / `pinned` |

`PERSONAL_AGENT_MCP_SERVERS` 仍可用一个 JSON 对象注册其他经过业务批准的 MCP 工具。项目启动时会先发现远端 MCP server 的工具，再只把 `tools` 中显式映射的能力注册进 `ToolGateway`；每个映射必须同时声明 `risk_level`、`side_effects`、`permission_scope`、限流、超时、审计配置和 capability metadata。缺少 capability metadata 的旧格式 mapping 会被配置解析拒绝：

- `semantic_domains`：能力所属语义领域，例如 `codebase`、`knowledge_knowledge`、`docs`。
- `resource_types`：可操作资源，例如 `repository`、`file`、`page`、`data_source`。
- `operations`：允许的操作类型，例如 `search`、`read`、`list`、`create`、`update`、`delete`。
- `trust_level`：`trusted`、`scoped`、`external`、`untrusted`。
- `credential_mode`：`user_token`、`delegated_token`、`service_token`、`none`。
- `data_egress_class`：`none`、`metadata`、`content`、`sensitive`。
- `attestation_status`：`verified`、`pinned`、`self_claimed`、`unknown`。
- `freshness_profile`：`realtime`、`near_realtime`、`static`、`unknown`。

这些字段会写入 tool 的 `extras["mcp_capability"]`，启动时转换为 canonical `MCPCapability` 并进入 `CapabilityPortfolio`。Portfolio 将静态定义与实时 `ExecutionCapabilityAvailability` 分开；`CapabilityResolver` 按 Goal requirement、资源范围、Policy 和 provider binding 生成精确 Grant。远程能力没有可用性观测或 credential 未就绪时 fail closed，`tool_quality` 同时校验 capability metadata、治理字段和安全边界。

当前支持两类 transport：

- `http`：使用 `endpoint`、`headers` 或 `authorization` 访问 JSON-RPC / Streamable HTTP MCP server。
- `stdio`：使用 `command`、`args`、`env` 启动本地 MCP server，适合 Docker 或本地二进制形式的 MCP server。

GitHub MCP 的只读仓库检索示例：

```env
GITHUB_PAT=your_github_personal_access_token_here
PERSONAL_AGENT_MCP_SERVERS={"enabled":true,"servers":[{"server_id":"github","transport":"stdio","command":"docker","args":["run","-i","--rm","-e","GITHUB_PERSONAL_ACCESS_TOKEN","-e","GITHUB_READ_ONLY","ghcr.io/github/github-mcp-server"],"env":{"GITHUB_PERSONAL_ACCESS_TOKEN":"${GITHUB_PAT}","GITHUB_READ_ONLY":"1"},"tools":[{"remote_name":"search_code","name":"github.search_code","description":"Search code in GitHub repositories that the configured token can read.","business_role":"enterprise_knowledge_search","side_effects":["external_network"],"permission_scope":"github:repo:read","semantic_domains":["codebase"],"resource_types":["repository","file","code"],"operations":["search"],"trust_level":"scoped","credential_mode":"delegated_token","data_egress_class":"content","attestation_status":"pinned","freshness_profile":"near_realtime","allowed_domains":["github.com"]},{"remote_name":"get_file_contents","name":"github.get_file_contents","description":"Read file contents from a GitHub repository that the configured token can read.","business_role":"enterprise_knowledge_search","side_effects":["external_network"],"permission_scope":"github:repo:read","semantic_domains":["codebase","docs"],"resource_types":["repository","file"],"operations":["read"],"trust_level":"scoped","credential_mode":"delegated_token","data_egress_class":"content","attestation_status":"pinned","freshness_profile":"near_realtime","allowed_domains":["github.com"]}]}]}
```

同一配置展开后等价于：

```json
{
  "enabled": true,
  "servers": [
    {
      "server_id": "github",
      "transport": "stdio",
      "command": "docker",
      "args": [
        "run",
        "-i",
        "--rm",
        "-e",
        "GITHUB_PERSONAL_ACCESS_TOKEN",
        "-e",
        "GITHUB_READ_ONLY",
        "ghcr.io/github/github-mcp-server"
      ],
      "env": {
        "GITHUB_PERSONAL_ACCESS_TOKEN": "${GITHUB_PAT}",
        "GITHUB_READ_ONLY": "1"
      },
      "tools": [
        {
          "remote_name": "search_code",
          "name": "github.search_code",
          "business_role": "enterprise_knowledge_search",
          "side_effects": ["external_network"],
          "permission_scope": "github:repo:read",
          "semantic_domains": ["codebase"],
          "resource_types": ["repository", "file", "code"],
          "operations": ["search"],
          "trust_level": "scoped",
          "credential_mode": "delegated_token",
          "data_egress_class": "content",
          "attestation_status": "pinned",
          "freshness_profile": "near_realtime",
          "allowed_domains": ["github.com"]
        },
        {
          "remote_name": "get_file_contents",
          "name": "github.get_file_contents",
          "business_role": "enterprise_knowledge_search",
          "side_effects": ["external_network"],
          "permission_scope": "github:repo:read",
          "semantic_domains": ["codebase", "docs"],
          "resource_types": ["repository", "file"],
          "operations": ["read"],
          "trust_level": "scoped",
          "credential_mode": "delegated_token",
          "data_egress_class": "content",
          "attestation_status": "pinned",
          "freshness_profile": "near_realtime",
          "allowed_domains": ["github.com"]
        }
      ]
    }
  ]
}
```

GitHub MCP 官方镜像支持 `GITHUB_READ_ONLY=1`，建议默认启用，并且先只映射 `search_code` / `get_file_contents` 这类读工具。后续如需 issue、PR、workflow 等写入能力，应单独声明为中高风险工具并加确认、权限域和幂等策略。

## GPT Researcher A2A 配置

本工程可把已部署的 `gpt-researcher` A2A JSON-RPC 后端注册为外部 Agent `gpt_researcher`，由 AgentGateway 治理 AgentRun / AgentEvent / AgentArtifact。后端必须同时加载基础 Compose 与 Provider 覆盖，避免回落到 `gpt-researcher/.env` 中的另一套模型配置：

```powershell
docker compose --env-file ..\personalAgent\.env `
  -f docker-compose.a2a.yml `
  -f docker-compose.deepseek.yml `
  up -d --no-build
```

容器内监听 `8001`，当前宿主端口为 `18001`：

```text
Agent Card: http://127.0.0.1:18001/.well-known/agent-card.json
A2A JSON-RPC: http://127.0.0.1:18001/a2a
```

personalAgent 侧配置：

```env
PERSONAL_AGENT_GPT_RESEARCHER_A2A_ENABLED=false
PERSONAL_AGENT_GPT_RESEARCHER_A2A_ENDPOINT=http://127.0.0.1:18001/a2a
PERSONAL_AGENT_GPT_RESEARCHER_A2A_AGENT_CARD_URL=http://127.0.0.1:18001/.well-known/agent-card.json
PERSONAL_AGENT_GPT_RESEARCHER_A2A_TIMEOUT_SECONDS=240
PERSONAL_AGENT_GPT_RESEARCHER_A2A_REPORT_TYPE=research_report
PERSONAL_AGENT_GPT_RESEARCHER_A2A_REPORT_SOURCE=web
PERSONAL_AGENT_GPT_RESEARCHER_A2A_TONE=Objective
PERSONAL_AGENT_GPT_RESEARCHER_A2A_MAX_SEARCH_RESULTS=1
PERSONAL_AGENT_GPT_RESEARCHER_A2A_MAX_CONCURRENT_RUNS=4
```

启用后，GPT Researcher 作为 Agent capability 注册。用户明确点名时，Task Analyzer 形成 required provider binding，Executive 产生 delegate，CapabilityResolver 选择 `gpt_researcher` 并通过 AgentGateway 调用。普通研究任务可由 Executive 选择本地研究动作或 `research_once` Protocol。

当前本地深研 profile 还设置 `PERSONAL_AGENT_INTERACTION_MAX_TOTAL_TOKENS=64000`，为成功 `AgentArtifact` 之后的父级核验、降级修复和最终综合保留预算。代码默认仍为 32,000；没有同类真实深研需求时不得机械提高全局默认。

GPT Researcher 的 OpenAI 兼容客户端把单次请求限制为 60 秒，并允许一次 SDK 重试。该限制只能约束单次服务提供方长尾；一次研究包含多个模型阶段，因此仍可能超过父任务的 240 秒预算。20 个真实委托样本只有 `10/20 delivered`，该配置不得表述为稳定上线。

A2A 入口在构造 GPT Researcher 时绑定一个确定性的通用研究角色，不再额外调用模型生成展示名称和角色 Prompt；普通 GPT Researcher 入口仍保留原有自动角色选择。同任务 MiMo 诊断由 240.14 秒超时改善为 96.26 秒完成并生成两个官方来源组，但完整内容 grader 与 usage 契约仍未通过，因此该配置只关闭角色输出兼容问题，不代表研究能力已经稳定上线。

## Firecrawl 配置

Firecrawl 仅作为可选的 URL 正文读取 Provider，不再提供 Web Search：

```env
FIRECRAWL_API_KEY=your_firecrawl_key
FIRECRAWL_BASE_URL=https://api.firecrawl.dev
FIRECRAWL_TIMEOUT_MS=60000
PERSONAL_AGENT_URL_CAPTURE_PROVIDER=firecrawl
```

生产配置使用 `PERSONAL_AGENT_URL_CAPTURE_PROVIDER=builtin`；若显式选择 Firecrawl，
它只改变 URL 正文读取，不改变 Tavily Web Search，也不是运行时 fallback。

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
PERSONAL_AGENT_API_KEYS={"key1":{"tenant_id":"tenant-a","user_id":"user1"}}
# 管理员 Key 使用相同 typed principal 格式：
PERSONAL_AGENT_ADMIN_API_KEYS={"admin-key":{"tenant_id":"tenant-a","user_id":"admin"}}
PERSONAL_AGENT_RATE_LIMIT_REQUESTS=60
PERSONAL_AGENT_RATE_LIMIT_WINDOW_SECONDS=60
PERSONAL_AGENT_CORS_ORIGINS=http://localhost:3000  # 多个用逗号分隔
```

## 回答校验

```env
AGENT_MAX_VERIFY_RETRIES=1  # 答案校验失败后最大重试次数
```

## LangSmith 可观测性

LangSmith 默认关闭。开启后，运行时会把项目配置桥接到 LangSmith 标准环境变量，并在 entry 执行入口创建 trace context。

```env
PERSONAL_AGENT_LANGSMITH_ENABLED=false
PERSONAL_AGENT_LANGSMITH_PROJECT=personal-agent-dev
PERSONAL_AGENT_TRACE_UPLOAD_INPUTS=false
PERSONAL_AGENT_TRACE_SAMPLE_RATE=1.0
LANGSMITH_API_KEY=
LANGSMITH_ENDPOINT=https://api.smith.langchain.com
LANGSMITH_WORKSPACE_ID=
```

说明：

- `PERSONAL_AGENT_LANGSMITH_ENABLED=true` 后才会启用 tracing。
- `LANGSMITH_API_KEY` 为 LangSmith API key。
- `PERSONAL_AGENT_LANGSMITH_PROJECT` 会写入 `LANGSMITH_PROJECT`。
- `LANGSMITH_ENDPOINT` 默认使用 LangSmith SaaS endpoint。
- `LANGSMITH_WORKSPACE_ID` 仅在 LangSmith API key 关联多个 LangSmith workspace 时需要；这是外部产品契约，
  不是本系统的资源可见性层。
- `PERSONAL_AGENT_TRACE_SAMPLE_RATE` 控制 entry trace 采样率，`1.0` 表示全量，`0` 表示不上传。
- `PERSONAL_AGENT_TRACE_UPLOAD_INPUTS=false` 时，LLM wrapper 只向 LangSmith 上传脱敏摘要：
  prompt 名称和版本、模型参数、消息数量/角色/字符数、工具名称、延迟、输出长度和 token usage；
  不上传消息正文、模型输出正文或工具参数。
- `PERSONAL_AGENT_TRACE_UPLOAD_INPUTS=true` 时，允许上传 wrapper 的完整输入输出，可能包含用户原文、
  prompt、检索上下文和模型输出，仅建议用于经过授权的开发环境或非敏感测试数据。

该开关不等于关闭 tracing，也不控制采样。是否启用 LangSmith 由
`PERSONAL_AGENT_LANGSMITH_ENABLED` 决定，采样比例由 `PERSONAL_AGENT_TRACE_SAMPLE_RATE` 决定。
生产环境建议保持 `PERSONAL_AGENT_TRACE_UPLOAD_INPUTS=false`。

结构化模型调用通过 composition root 注入观测装饰器，Conversation、Personal Knowledge、Research 和
Investigation Application 组件不读取该开关。该策略不能保证覆盖第三方库自动产生的全部 trace，
也不能覆盖尚未迁移到统一 Model Client 的旧 LLM 路径。其他 trace metadata 中不要放用户正文、长期记忆内容、URL token、
文件内容或密钥。
完整边界见 [可观测与治理边界](topics/observability-governance.md#2-llm-trace-脱敏策略)。

## PostgreSQL 与遗留 Checkpoint 配置

```env
PERSONAL_AGENT_POSTGRES_URL=postgresql://postgres:postgres@127.0.0.1:5432/personal_agent?sslmode=disable
```

说明：

- Personal Knowledge、Research、Knowledge Lifecycle、Tool governance、Agent run、worker queue 和
  Investigation journal 共享该 PostgreSQL 连接，但各自拥有事实表和恢复语义；
- 普通 Conversation 使用 `data/interaction_runs` 下的 `FileInteractionJournal`，不是 LangGraph
  checkpoint；
- 数据库仍可能包含历史 LangGraph checkpoint/迁移表；它们用于旧数据与运维兼容，不定义当前
  Conversation 主链；
- `scripts/export_thread_checkpoints.py` 只用于历史 checkpoint 诊断，不能作为当前 Interaction
  恢复证据。
## Research / 定时情报简报

```env
PERSONAL_AGENT_RESEARCH_SCHEDULER_ENABLED=false
PERSONAL_AGENT_RESEARCH_SCHEDULER_TICK_SECONDS=60
PERSONAL_AGENT_RESEARCH_MAX_QUERIES=5
PERSONAL_AGENT_RESEARCH_MAX_SEARCH_RESULTS=30
PERSONAL_AGENT_RESEARCH_MAX_FULLTEXT_FETCHES=5
PERSONAL_AGENT_RESEARCH_MAX_TOOL_CALLS=15
```

Research 使用 `PERSONAL_AGENT_WEB_SEARCH_*` 配置的搜索 provider。

生产环境固定使用：

```text
外部 cron
  -> personal-agent research-schedule
  -> Postgres worker_queue_tasks
  -> personal-agent worker --queue research
```

生产环境必须保持 `PERSONAL_AGENT_RESEARCH_SCHEDULER_ENABLED=false`，避免多个 FastAPI 实例重复扫描。应用内 scheduler 仅用于单机开发。
