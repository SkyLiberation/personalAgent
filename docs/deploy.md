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
uv run uvicorn personal_agent.web.api:app --reload
```

默认地址：

- API: `http://127.0.0.1:8000`
- Docs: `http://127.0.0.1:8000/docs`

## 7. 启动前端

```bash
cd frontend
npm run dev
```

默认地址：

- Frontend: `http://127.0.0.1:5173`

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
