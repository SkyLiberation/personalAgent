# 本地开发与部署

## 1. 安装 Python 依赖

```bash
uv sync
```

## 2. 安装前端依赖

```bash
cd frontend
npm install
```

## 3. 配置环境变量

```bash
cp .env.example .env
```

然后填写你的：

- `OPENAI_API_KEY`
- `OPENAI_BASE_URL`
- `OPENAI_MODEL`
- `EMBEDDING_API_KEY`
- `EMBEDDING_BASE_URL`
- `OPENAI_EMBEDDING_MODEL`

如果你暂时不想启动 Neo4j，建议先把：

```env
PERSONAL_AGENT_GRAPHITI_ENABLED=false
```

这样 Web 问答会自动走非图谱降级链路，不会因为 `localhost:7687` 不可用而长时间重试。

## 4. 启动 Neo4j

```bash
docker compose up -d neo4j
```

默认地址：

- Neo4j Browser: `http://127.0.0.1:7474`
- Bolt: `bolt://127.0.0.1:7687`

默认账号密码：

- username: `neo4j`
- password: `password`

## 5. 启动 Postgres

```bash
docker compose up -d postgres
```

默认地址：

- Postgres: `127.0.0.1:5432`

默认账号密码：

- username: `postgres`
- password: `postgres`
- database: `personal_agent`

## 6. 启动后端

```bash
uv run uvicorn personal_agent.web.api:app --host 0.0.0.0 --port 8000 --reload
```

默认地址：

- API: `http://127.0.0.1:8000`
- Docs: `http://127.0.0.1:8000/docs`

## 6.1 飞书接入注意事项

当前项目使用飞书官方 Python SDK 的”长连接接收事件”模式。

### 推荐配置

飞书开发者后台：

- `权限管理`
  - `im:message.p2p_msg:readonly`
  - `im:message:send_as_bot`
- `事件与回调`
  - 订阅方式：`使用长连接接收事件`
  - 事件：`im.message.receive_v1`
- `版本管理与发布`
  - 确保以上配置已经发布生效

本地后端：

- `.env` 中配置：
  - `PERSONAL_AGENT_FEISHU_ENABLED=true`
  - `FEISHU_APP_ID`
  - `FEISHU_APP_SECRET`
- 启动后端即可，代码会在应用启动时自动拉起飞书长连接客户端

### 长连接模式的特点

- 本地开发不需要配置公网地址
- 不需要 `ngrok / frp / Cloudflare Tunnel`
- 正常情况下，`log/run.log` 中会出现：
  - `Feishu long connection startup requested`
  - `Feishu long connection thread started`
  - `connected to wss://...`
  - `Feishu long connection event accepted`
  - `Feishu reply sent`

## 7. 启动前端

```bash
cd frontend
npm run dev
```

默认地址：

- Frontend: `http://127.0.0.1:3000`

> **Windows 注意**: 端口 5173 可能被系统保留（Hyper-V/WSL 动态端口范围），导致 `EACCES` 权限错误。项目默认端口已改为 3000。如需使用其他端口：
> ```bash
> npx vite --host 127.0.0.1 --port <端口号>
> ```

## 8. 构建前端

```bash
cd frontend
npm run build
```

构建完成后，FastAPI 会自动托管 `frontend/dist`。

## 日志位置

当前运行日志默认写入项目根目录：

- `log/run.log`

## 调试重置

在前端 `采集` 页面底部提供了“一键清空调试数据”入口，便于快速回到干净状态。

它会清理当前用户的：

- 本地笔记
- 复习任务
- 本地会话
- 上传源文件
- `Postgres.ask_history`
- 当前用户对应的图谱分组数据

## Docker Compose

当前 `docker-compose.yml` 包含：

- `backend`
- `frontend`
- `neo4j`
- `postgres`

直接启动：

```bash
docker compose up --build
```

`Ask History` 的服务端存档默认使用 `Postgres` 中的 `ask_history` 表，保存问句、回答、引用、是否命中图谱、`session_id` 以及时间戳。

## 常见排障

### 1. 飞书能回复，但日志里报 Graphiti / Neo4j 错误

典型表现：

- `Couldn't connect to localhost:7687`
- `Neo4j is unreachable`

说明：

- 飞书接入本身已经成功
- 是图谱层依赖的 Neo4j 没有启动

解决方式二选一：

1. 启动 Neo4j

```bash
docker compose up -d neo4j
```

2. 暂时关闭图谱

```env
PERSONAL_AGENT_GRAPHITI_ENABLED=false
```

### 2. 飞书后台配置为长连接，但日志没有 `connected to wss://...`

排查：

- 检查 `FEISHU_APP_ID / FEISHU_APP_SECRET` 是否正确
- 检查飞书后台是否确实选择了“使用长连接接收事件”
- 检查当前应用是否已发布

### 3. 收到同一条飞书消息两次

飞书在超时场景下可能重推事件。当前代码已做短时去重，但如果处理链路仍然过慢，仍然建议优先关闭不必要的图谱依赖，保证消息在更短时间内完成处理。
