# ADR 0036：原生动作使用明确对象载荷

- 状态：Superseded；模型可见协议已由 [ADR 0043](0043-direct-code-agent-tool-parameters.md) 替换，以下保留原决定与证据身份。
- 日期：2026-10-21
- 范围：Conversation 的模型可见动作、名称投影和解码
- 唯一规格：[主循环 Spec §3.15](../optimization/to_verify/conversation-loop-boundaries.md#315-显式业务载荷映射的审查候选)

## 背景与决定

研究真实轨迹反复把直接控制参数包入 `arguments`，统一外层的隔离候选又遗漏实验工具的内部 `action`。参数值本身有效，旧 Schema 正确拒绝；不得将旧非法调用自动补成执行。此前两个候选及重复组的失败原样保留。

全部原生动作采用唯一 `arguments: object` 外层。Plan／Agent 及空载荷 `prepare_final` 去掉该外层后进入原 Proposal。仅 `retrieval_experiment` 在同轮 frozen `ModelActionDefinition` 中声明 `payload_field="action"`，从原 canonical Args 派生内层完整 Schema；严格校验后无损恢复原 `{action:payload}`。`write_artifact.request` 和其他工具保持原业务对象。Schema 最后一次严格化后才给对象分支 union 补明确对象类型，Adapter 直接消费最终定义。

模型可见 policy 的调用名从同一 Definition 派生，canonical identity 仅关联历史执行事实。完整 wire 校验和拒绝坐标由模型接口 decoder 拥有；原调用仍是未执行数据，反馈保真。Admission、Registry、业务服务继续拥有参数语义、授权和执行；原 canonical Args、scope／call_id／request digest、持久接受与恢复均不变。无第二 transport、别名、非法字符串转换或双形状兼容。

## 依据、防护与复杂度

独立审查修正了 Artifact 字段误写、完整 Schema 校验缺项及 strictify 顺序。实际两项失败值的零模型反事实验证了 canonical 等价、原绑定摘要及改值／改身份后的摘要差异；4 项真实普通读取保持。一次完整 Native 模型阶段为 1 物理、0 修复、17,688 tokens、53.937 秒，实际选中映射工具并通过完整 Schema，零执行。原档和限制见唯一规格，不把它计为 Product E2E 或成功率提升。

新增一个 typed 内部字段和一项实际映射声明，复用现有定义、业务 DTO 与 Proposal；删除混合控制参数入口和重复名称来源。直接改 canonical Args 会扩大 Journal／工具／恢复迁移；另建 JSON 动作通道会增加第二协议；单独改提示仍要求模型搬运内部封装。保持单一模型接口模块，避免新增 codec 插件或治理元数据。

## 验收与退出

生产候选须回放上述实际输出和普通／控制产物，核对最终 SDK、严格拒绝、反馈物化及 Journal 保真，完成适用工程检查。完整研究继续原 E1／P1、评分资格、target 和下载／复现验收；控制协议受影响的普通调用按原用户结果验证。历史 accepted request 直接恢复，无新 wire 解码迁移。

若同一真实请求在原有界修复后仍无法遵守唯一对象声明，或映射需猜测字段、语义补参、改业务摘要，停止对应路径并重审这一协议；不增加兼容分支或延长原组。局部通过不声明可上线。
