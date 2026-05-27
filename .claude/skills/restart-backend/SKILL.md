# Restart Backend

## Description
安全重启 personalAgent 后端（uvicorn），先杀旧进程再启动新实例，避免端口冲突。

## When to Use
- 修改了 `.env` 配置、Python 依赖、LangGraph 编排等需要完整重启的场景
- `--reload` 热重载不够，需要干净重启时
- 怀疑旧 worker 占用端口时

## Steps

### 1. 杀掉所有 uvicorn 进程
```bash
tasklist | grep -i uvicorn
```
对每个 PID 执行：
```bash
taskkill //F //PID <PID>
```
重复检查直到没有 uvicorn 进程。

> **注意**: 不要用 `powershell -Command` 执行复杂内联脚本，Windows 下转义不可靠。用简单的 `tasklist` + `taskkill` 组合。

### 2. 启动后端
```bash
cd d:/mySoft/workspace/personalAgent && uv run uvicorn personal_agent.web.api:app --host 0.0.0.0 --port 8000 --reload
```
作为 **后台任务** 运行，不阻塞会话。

### 3. 验证启动
等待 3 秒后检查输出，确认包含：
- `Application startup complete.`
- 无 error 级别日志

### 4. 报告结果
告知用户后端地址 `http://127.0.0.1:8000`。
