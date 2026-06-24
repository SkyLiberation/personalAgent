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

当前工程以 Graphiti 为核心能力，不再提供关闭图谱的开关。本地开发请启动 Neo4j，并确保 `.env` 中的 Graphiti、LLM 和 Embedding 配置完整。

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

### 6.1 开发环境重启后端

上面的 `--reload` 用于监听 Python 源码变化并自动重载 worker，不等于可靠的完整重启。以下场景应显式停止旧进程再启动：

- 修改 `.env` 配置
- 安装或更新 Python 依赖
- 修改 LangGraph 编排、checkpoint backend 或其他会在进程内缓存的运行时对象
- 页面行为与当前源码不一致，怀疑仍有旧 worker 占用 `8000` 端口

推荐步骤：

1. 在启动后端的终端中按 `Ctrl+C`，等待 Uvicorn reloader 与 worker 都退出。
2. 在 PowerShell 中确认端口没有残留监听：

```powershell
Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue
```

3. 如果仍能看到监听进程，先查看对应命令；确认它属于本项目后，终止旧 Uvicorn reloader 及其 worker 进程树：

```powershell
$listenerPid = (Get-NetTCPConnection -LocalPort 8000 -State Listen).OwningProcess
Get-CimInstance Win32_Process -Filter "ProcessId = $listenerPid" |
  Select-Object ProcessId, ParentProcessId, CommandLine

function Stop-ProcessTree([int] $ProcessId) {
  Get-CimInstance Win32_Process -Filter "ParentProcessId = $ProcessId" |
    ForEach-Object { Stop-ProcessTree $_.ProcessId }
  Stop-Process -Id $ProcessId -Force -ErrorAction SilentlyContinue
}

$reloader = Get-CimInstance Win32_Process |
  Where-Object {
    $_.Name -eq "uvicorn.exe" -and
    $_.CommandLine -match "personal_agent\.web\.api:app"
  } |
  Select-Object -First 1

if ($reloader) {
  Stop-ProcessTree $reloader.ProcessId
}
```

4. 重新启动后端：

```powershell
uv run uvicorn personal_agent.web.api:app --host 0.0.0.0 --port 8000 --reload
```

不要在旧实例仍占用端口时重复启动后端。对于 LangGraph 这类会缓存已编译 graph 的代码，完整重启后，新请求才会确定使用最新编排定义。

### 6.2 飞书接入注意事项

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

在前端 `采集` 页面底部提供了“一键清空调试数据”入口，便于快速回到干净状态。该操作影响所有用户，仅用于开发环境。

它会清理：

- 配置的 Postgres 当前 schema 中全部普通表数据，包括业务表和 LangGraph checkpoint/迁移元数据；清理后会重建 LangGraph 迁移版本记录
- `data/uploads/` 下全部上传源文件
- 配置的 Neo4j 数据库中全部图谱节点和关系

## Docker Compose

当前 `docker-compose.yml` 包含：

- `backend`
- `research-worker`
- `research-scheduler`（一次性 job，由外部 cron 调用）
- `frontend`
- `neo4j`
- `postgres`

先从样例生成真实环境文件并填写密钥：

```bash
cp .env.example .env
```

启动常驻服务：

```bash
docker compose up -d backend frontend neo4j postgres research-worker
```

### Research 生产调度

生产环境不在 FastAPI 内启动 Research Scheduler。宿主机 cron 每分钟执行一次。仓库提供
[`deploy/cron/personal-agent-research.cron.example`](../deploy/cron/personal-agent-research.cron.example)
作为安装模板：

```cron
* * * * * cd /path/to/personalAgent && /usr/bin/flock -n /tmp/personal-agent-research-scheduler.lock /usr/bin/docker compose --profile jobs run --rm research-scheduler >> /var/log/personal-agent-research-scheduler.log 2>&1
```

`research-scheduler` 只扫描到期订阅、创建幂等 `ResearchRun` 并写入 Postgres 队列，正常情况下会快速退出。耗时的搜索、聚类、验证和投递由常驻 `research-worker` 完成。

`flock` 防止上一次 scheduler 尚未退出时又启动一个容器；数据库幂等仍是最终兜底。三个 Python 服务使用根目录 `Dockerfile` 构建统一镜像，因此 cron 每次启动 job 时不会重新安装依赖。

手动验证：

```bash
docker compose --profile jobs run --rm research-scheduler
docker compose logs -f research-worker
```

生产 `.env` 必须保持：

```env
PERSONAL_AGENT_RESEARCH_SCHEDULER_ENABLED=false
```

即使 cron 被重复触发，ResearchRun、worker task 和 delivery ledger 的数据库唯一键仍会阻止同一时间窗口重复执行或投递。

`Ask History` 不再单独存档 — 同一会话的问答以 LangGraph checkpoint 中的 `state.messages` 为唯一真源，前端历史列表通过 `/api/entry/runs` 渲染最近 run snapshot。

## 常见排障

### 1. 飞书能回复，但日志里报 Graphiti / Neo4j 错误

典型表现：

- `Couldn't connect to localhost:7687`
- `Neo4j is unreachable`

说明：

- 飞书接入本身已经成功
- 是图谱层依赖的 Neo4j 没有启动

解决方式：

```bash
docker compose up -d neo4j
```

### 2. 飞书后台配置为长连接，但日志没有 `connected to wss://...`

排查：

- 检查 `FEISHU_APP_ID / FEISHU_APP_SECRET` 是否正确
- 检查飞书后台是否确实选择了“使用长连接接收事件”
- 检查当前应用是否已发布

### 3. 收到同一条飞书消息两次

飞书在超时场景下可能重推事件。当前代码已做短时去重，但如果处理链路仍然过慢，建议优先检查 Neo4j、LLM 和 Embedding 服务是否稳定。
