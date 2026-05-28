# Restart Backend

## Description
安全重启 personalAgent 后端（uvicorn），先杀旧进程再启动新实例，避免端口冲突。

## When to Use
- 修改了 `.env` 配置、Python 依赖、LangGraph 编排等需要完整重启的场景
- `--reload` 热重载不够，需要干净重启时
- 怀疑旧 worker 占用端口时
- 修改了 Python 源码但行为未生效（可能是旧进程残留）

## Steps

### 1. 杀掉旧进程（两阶段）

**第一阶段：定向杀 uvicorn**
```bash
tasklist | grep -i uvicorn
```
对每个 PID 执行：
```bash
taskkill //F //PID <PID>
```

**第二阶段：验证端口并兜底杀全量 Python**

`uv run uvicorn` 会创建父进程管理子 worker，单独杀 uvicorn 可能不够——父进程会重启 worker 导致旧代码继续运行。因此必须验证端口是否真正释放：

```bash
netstat -ano | grep ":8000" | grep LISTENING
```

如果仍有 LISTENING 条目，说明旧 worker 残留，执行全量清理：
```bash
taskkill //F //IM python.exe
taskkill //F //IM uvicorn.exe
```

再次验证端口：
```bash
netstat -ano | grep ":8000" | grep LISTENING
```
确认无输出后再启动。

> **注意**:
> - 不要用 `powershell -Command` 执行复杂内联脚本，Windows 下转义不可靠。用简单的 `tasklist` + `taskkill` 组合。
> - `taskkill //F //IM python.exe` 会杀掉所有 Python 进程，确保没有其他重要的 Python 程序在运行。

### 2. 清除 `__pycache__`

修改了 Python 源码后，`.pyc` 缓存可能未更新（尤其是 `--reload` 未触发时）。重启前清理：
```bash
find d:/mySoft/workspace/personalAgent -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
```
或使用 PowerShell：
```powershell
Get-ChildItem -Path d:\mySoft\workspace\personalAgent -Directory -Recurse -Filter __pycache__ | Remove-Item -Recurse -Force
```

### 3. 启动后端
```bash
cd d:/mySoft/workspace/personalAgent && uv run uvicorn personal_agent.web.api:app --host 0.0.0.0 --port 8000 --reload
```
作为 **后台任务** 运行，不阻塞会话。

### 4. 验证启动
等待 3 秒后检查输出，确认包含：
- `Application startup complete.`
- 无 error 级别日志

### 5. 报告结果
告知用户后端地址 `http://127.0.0.1:8000`。
