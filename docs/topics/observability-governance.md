# 观测与治理层说明

本文汇总当前项目观测与治理层的职责划分、当前能力、已知限制和后续改进方向。对应代码主要位于 [src/personal_agent/core/logging_utils.py](../../src/personal_agent/core/logging_utils.py)、[src/personal_agent/web/auth.py](../../src/personal_agent/web/auth.py)、[src/personal_agent/web/api.py](../../src/personal_agent/web/api.py) 和 [tests/](../../tests/)。

## 设计目标

观测与治理层负责让系统可运行、可排查、可限制、可测试：

- 统一日志输出
- 关键链路结构化事件
- health 检查
- API Key 鉴权
- 基础限流
- 用户隔离
- 高风险操作审计
- 自动化测试覆盖核心模块

## 当前能力

### 1. 日志与 trace

`setup_logging()` 会同时输出 console 和 `log/run.log`。

`log_event()` 和 `trace_span()` 提供结构化字段日志能力，可记录：

- trace start/end/error
- duration
- trace_id
- user_id
- span
- error type

### 2. Health

`GET /api/health` 返回运行状态，并作为公开路径绕过 API Key 鉴权。

### 3. API Key 鉴权

`AuthMiddleware` 支持：

- `Authorization: Bearer <key>`
- `X-API-Key`
- `api_key` query 参数，主要用于 SSE EventSource

鉴权成功后会将 `user_id` 写入 `request.state.user_id`。

### 4. 限流

`RateLimiter` 当前是进程内简单 token bucket：

- 按 API Key 计数
- 超限返回 429
- 返回 `Retry-After`

### 5. 用户隔离

主要通过 `user_id` 分隔：

- notes
- reviews
- ask history
- pending actions
- cross-session state
- graph group

### 6. 高风险操作审计

`PendingActionStore` 会记录 pending action 的 audit log，覆盖创建、确认、拒绝、过期和执行等事件。

### 7. 测试

测试覆盖范围包括：

- router
- planner
- validator
- executor
- replanner
- tools
- memory
- storage
- API
- CLI

## 已知限制

### 1. 限流是进程内的

当前 `RateLimiter` 不适合多实例共享限流状态。多实例部署时需要 Redis 或网关层限流。

### 2. 日志还不是完整 observability 平台

当前主要是文件日志和结构化字段日志，还没有接入 metrics、tracing backend、dashboard 或 alert。

### 3. API Key 模型较轻量

适合个人或轻量多用户场景。更复杂的组织、角色、权限、租户隔离和 key 生命周期管理仍需增强。

### 4. 外部工具权限治理还不完整

工具层还没有统一权限模型，例如公网访问、写入长期知识、高风险操作和外部副作用的统一策略。

### 5. Debug reset 风险较高

`/api/debug/reset-user-data` 能清理用户数据，当前适合开发调试。生产化时需要更严格的权限、审计和确认。

## 演进方向

- 将限流迁移到 Redis 或 API 网关
- 接入 metrics 和 tracing backend
- 增加结构化错误码与告警
- 完善 API Key 生命周期管理
- 为工具调用建立统一权限和审计模型
- 为 debug / destructive 操作增加更强确认和权限控制
- 扩大端到端回归评测样本

