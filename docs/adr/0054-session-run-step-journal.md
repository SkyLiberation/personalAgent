# ADR 0054：会话拥有轮次历史

Turn 接口和 Step 身份于 2026-11-17 切换。2026-11-19 的 LongDS 归档对照定位到续聊依赖客户端全量历史。现行实现由服务端持有有序历史，SQLite 提交 Turn 及其修订。[现行实现](../architecture/core-architecture-current-state.md#32-会话运行与主决策的现状) · [生命周期规格和证据](../optimization/to_verify/conversation-loop-boundaries.md#320-sessionturn-与-step-生命周期)

## 决定

借鉴 DeepSeek Harness 按会话身份装载持久历史再追加输入的做法。每个认证主体下的 Session 保存一条有序 Turn 历史。首次创建显式声明，续聊根据 `session_id` 和新输入进入，由 Journal 冻结已提交的前驱。单个 SQLite Journal 原子提交会话身份、轮次和请求幂等绑定。已有未结束轮次时从原 `turn_id` 恢复或确认，执行事实及未决副作用继续由原责任主体处理。相同 Session 的历史不再通过回传助手全文定位。[DeepSeek Harness 恢复源码](https://github.com/deepseek-ai/deepseek-harness/blob/2e39e70496aa02986ca6a820c5d497e816b69d7e/packages/core/agent-loop/src/index.ts#L793-L818)

## 存储启用与验收

SQLite 在 `conversation_journal` 下初始化。既有文件归档原样保留，新入口只读取新库。原模型请求与响应仍按调用另存，Turn 修订保存其引用。验收使用真实历史回放和正式入口续聊，结果由[生命周期规格](../optimization/to_verify/conversation-loop-boundaries.md#320-sessionturn-与-step-生命周期)维护。

普通 MCP 写调用在派发前向同一个 Turn Journal 登记。恢复已保存的模型响应时，已有登记且尚无结果的原调用以未知结果进入原生工具消息。SQLite 保存登记，目标端仍拥有实际写入和回执。这项决定避免用模型响应是否已消费来猜测外部写入。依据、保守恢复边界和复验由 [MCP 进程恢复规格](../mcpDesign/README.md#普通-mcp-写调用的进程恢复)维护。
