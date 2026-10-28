# 开源实践与架构设计依据

复核日期：2026-10-28。以下源码为 A 级固定提交，仅证明所列配置与调用分支的机制；未运行外部服务或验证其在本工程的用户效果。设计选择时只读相关条目，按 [EVD 外部参考规则](../../../../docs/devSpec/change-evidence.md#6-外部参考的证据分级)核对适用条件。

## 1. FastAPI：显式组合入口及生命周期

固定提交：`fastapi/fastapi@45c419938435d668a85a2e81bb9ac41495f8a648`。

- [应用装配](https://github.com/fastapi/fastapi/blob/45c419938435d668a85a2e81bb9ac41495f8a648/fastapi/applications.py#L981)：`FastAPI.__init__()` 构造 `APIRouter`，`FastAPI.include_router()` 将显式参数交给内部 router。
- [路由组合](https://github.com/fastapi/fastapi/blob/45c419938435d668a85a2e81bb9ac41495f8a648/fastapi/routing.py#L3371)：`APIRouter.include_router()` 拒绝包含环，建立 `_IncludedRouter` 并合并 lifespan。该提交采用包含上下文，不是早期复制所有路由的实现。
- [普通 API 请求消费](https://github.com/fastapi/fastapi/blob/45c419938435d668a85a2e81bb9ac41495f8a648/fastapi/routing.py#L1276)：`APIRoute.get_route_handler()` 构造 `get_request_handler()`；后者解析依赖，成功后在普通返回分支调用 `run_endpoint_function()`。

**设计采用：** 功能入口独立定义，组合位置显式给出策略与生命周期；沿实际请求核对配置的消费者。由此检查本工程正式入口是否复用同一业务 owner，构造、调用和关闭责任是否闭合。

**本工程差异：** HTTP 路由与依赖组合不承担领域事实、资源授权或任务完成。保留现有 Composition Root 和治理入口，不据此引入通用容器或把业务规则移入传输层。

## 2. LangGraph：运行契约与持久化实现分离

固定提交：`langchain-ai/langgraph@7d6b5790ba84ce38c26f27a533d8419a31103c36`。

- [编译装配](https://github.com/langchain-ai/langgraph/blob/7d6b5790ba84ce38c26f27a533d8419a31103c36/libs/langgraph/langgraph/graph/state.py#L1177)：`StateGraph.compile()` 接收 checkpointer、store 等依赖，并交给 `CompiledStateGraph`。
- [实际读取](https://github.com/langchain-ai/langgraph/blob/7d6b5790ba84ce38c26f27a533d8419a31103c36/libs/langgraph/langgraph/pregel/main.py#L1392)：`Pregel.get_state()` 取得配置中的 saver；当前图读取分支调用 `checkpointer.get_tuple()`，再形成状态快照。
- [检查点契约](https://github.com/langchain-ai/langgraph/blob/7d6b5790ba84ce38c26f27a533d8419a31103c36/libs/checkpoint/langgraph/checkpoint/base/__init__.py#L176)定义 `BaseCheckpointSaver`；[PostgreSQL 实现](https://github.com/langchain-ai/langgraph/blob/7d6b5790ba84ce38c26f27a533d8419a31103c36/libs/checkpoint-postgres/langgraph/checkpoint/postgres/__init__.py#L192)根据 thread、namespace 及可选 checkpoint ID 读取数据库。[连接工厂](https://github.com/langchain-ai/langgraph/blob/7d6b5790ba84ce38c26f27a533d8419a31103c36/libs/checkpoint-postgres/langgraph/checkpoint/postgres/__init__.py#L62)以上下文管理连接生命周期。

**设计采用：** 先定义运行系统真正消费的契约，再隔离外部存储变化；构造参数必须能追踪到实际使用点，连接生命周期有明确责任。这里核对的是显式配置 saver 的状态读取路径，不外推所有执行、写入与恢复分支。

**本工程差异：** 检查点不自动成为业务事实或执行回执，也不替代权限、外部副作用幂等及 Completion。独立发布包的布局不构成本工程拆包理由；真实持久化需求与唯一 Journal／业务 owner 继续按 ARC、EXE 判断。

## 3. 架构定义与合理性判断的补充依据

- [arc42：目标](https://docs.arc42.org/section-1/)及[解决策略](https://docs.arc42.org/section-4/)将业务目标、关键质量场景与约束作为架构取舍依据。本技能采用“场景与约束 → 关键决定 → 可检查结果”的关系，不复制整套模板。
- [C4：视图](https://c4model.com/diagrams)区分系统边界、静态结构与动态、部署等补充视图，按沟通价值选择。本技能据此区分系统关系、运行调用与代码结构，图的数量不作为设计质量指标。

这些官方文档补充设计表达方法，不作为第三个独立源码实现，也不证明本工程架构已经合理或业务验收通过。
