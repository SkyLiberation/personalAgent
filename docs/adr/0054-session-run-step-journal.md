# ADR 0054：会话拥有轮次历史

Turn 接口和 Step 身份于 2026-11-17 切换。2026-11-19 的 LongDS 归档对照定位到续聊依赖客户端全量历史。现行实现由服务端持有有序历史，SQLite 提交 Turn 及其修订。[现行实现](../architecture/core-architecture-current-state.md#32-会话运行与主决策的现状) · [生命周期规格和证据](../optimization/to_verify/conversation-loop-boundaries.md#320-sessionturn-与-step-生命周期)

## 决定

借鉴 DeepSeek Harness 按会话身份装载持久历史再追加输入的做法。每个认证主体下的 Session 保存一条有序 Turn 历史。首次创建显式声明，续聊根据 `session_id` 和新输入进入，由 Journal 冻结已提交的前驱。单个 SQLite Journal 原子提交会话身份、轮次和请求幂等绑定。已有未结束轮次时从原 `turn_id` 恢复或确认，执行事实及未决副作用继续由原责任主体处理。相同 Session 的历史不再通过回传助手全文定位。[DeepSeek Harness 恢复源码](https://github.com/deepseek-ai/deepseek-harness/blob/2e39e70496aa02986ca6a820c5d497e816b69d7e/packages/core/agent-loop/src/index.ts#L793-L818)

## 存储启用与验收

SQLite 在 `conversation_journal` 下初始化。既有文件归档原样保留，新入口只读取新库。原模型请求与响应仍按调用另存，Turn 修订保存其引用。验收使用真实历史回放和正式入口续聊，结果由[生命周期规格](../optimization/to_verify/conversation-loop-boundaries.md#320-sessionturn-与-step-生命周期)维护。

轮内变更在同一 SQLite 修订表追加增量，首个修订和首次终态保存完整快照。写入事实和消费补充指令仍在原事务内完成。会话锁内只复用与当前数据库身份一致的已提交对象，恢复读取同一日志中的基准快照和后续修订。已有完整修订仍可作为快照打开，旧程序回滚须使用改动前的数据库备份。延迟依据、取舍及验收见[轮内增量修订](../optimization/to_verify/conversation-loop-boundaries.md#轮内增量修订)。

普通 MCP 写调用在派发前向同一个 Turn Journal 登记。恢复已保存的模型响应时，已有登记且尚无结果的原调用以未知结果进入原生工具消息。SQLite 保存登记，目标端仍拥有实际写入和回执。这项决定避免用模型响应是否已消费来猜测外部写入。依据、保守恢复边界和复验由 [MCP 进程恢复规格](../mcpDesign/README.md#普通-mcp-写调用的进程恢复)维护。

## 同轮补充指令

DynaRev 真实轨迹到达第一处里程碑后，本工程普通提交入口返回 HTTP 409，DeepSeek Harness 则在当前轮的下一步消费用户消息并继续执行。采用固定版本的会话控制入口、next-step inbox 和终态前再检查模式。验收以已接入的 DynaRev 原题为准，保留原浏览状态，分别断言同轮接收、两条用户原文进入后续真实模型请求和五项终态约束。若自然里程碑缺失，该轨迹单独报告未到达。[对照轨迹](../problems/DynaRev/cruise-steering.md) · [DeepSeek Harness 消费链](https://github.com/deepseek-ai/deepseek-harness/blob/2e39e70496aa02986ca6a820c5d497e816b69d7e/packages/core/agent-loop/src/agent.ts#L354-L406)

Web 通过 `POST /api/conversation/turns/{turn_id}/steer` 接收仅文本的同轮补充指令，按认证主体和轮次绑定。当前执行者仍独占轮次执行。Journal 在短事务内持久化排队的原文，下一步边界将其按顺序移入该轮修订并标记所排在的 Step。原题身份和已保存模型请求继续冻结。重复请求标识与原文一致时返回同一确认，不同内容则冲突。终态与入队由同一 Journal 写入边界排序，已入队的指令先于终答消费，晚到的新指令返回 409。此能力接入普通前台 Web 对话，对已有审批、工作区和实验命令沿用各自的执行契约。

模型输入将补充原文以用户角色插入已完成的原生工具交换之后。装配 Goal 时，旧目标与其当步输入保持绑定，当前目标对新增原文重新确认后才继续业务执行。恢复先处理已保存的未消费模型响应，再消费排队输入。预算与终答验证沿用现有契约。单独回放入口拒绝、同 ID 冲突和匹配重试，并以同一真实 DynaRev 轨迹核对无额外轮次。

普通 Web 对话可由受信的 Web 进程装配一个终答提交前通知。回答通过现有核验、准备写入终态且补充队列为空时，Conversation 等待通知返回，再通过 Journal 提交终答。通知可让 DynaRev 评测器及时走既有鉴权入口送入补充。排队的原文仍由 Journal 按原轮顺序领取，通知不提交任何业务事实。默认无通知消费者。验收身份与结果见[终答提交前接续](../optimization/to_verify/conversation-loop-boundaries.md#终答提交前接续l-18)。
