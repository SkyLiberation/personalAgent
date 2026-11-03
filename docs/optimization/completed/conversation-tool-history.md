# 跨用户轮次的工具历史与单份引用展示

2026-10-30：本次限定的历史组织问题已关闭。独立 Python direct 分析在连续用户轮次间保留真实 assistant、调用参数、服务方推理和配对返回，引用正文使用单份坐标行展示。该结论不表示长程分析的所有语义错误已解决；本次原六轮独立评分为 4/6，第三轮数量条件及第五轮计算仍失败，详见[正式验证记录](../to_verify/verify_results/analysis-correctness.md#16-历史工具组织优化后的完整六轮)。

## 问题与依据

此前 v630 的同一轮内部已使用原生工具交换，但进入下一用户轮次只继承观察，历史调用参数和完整 assistant 未按原会话位置传递。第六轮首步把 20 条工具观察和 61 项文件信息放在当前 user 后的 system，共 191,047 字符；其中 84,579 字符为引用原文，逐行 JSON 包装约另占 63,500。该轨迹证明时间关系缺失及包装成本，不证明它们是全部语义错误的唯一原因。

原始采集 `.tmp/v630/c/` 和新候选 `.tmp/h630/` 均保留，旧评分 1/6 不改写。实现前需求、比较条件和停止线原在长程分析 Spec §7.6，关闭后在本页维护当前机制；原始源码、计划、离线请求和费用记录仍由归档持有。

## 采用机制与责任

| 职责 | 当前机制 |
| --- | --- |
| 原始会话与执行事实 | 原 Journal／Artifact 继续拥有唯一记录；无新状态、存储、模型阶段或第三方依赖 |
| 选择历史运行 | `prior_analysis_turns` 匹配同一主体、对话、Python 授权、原用户消息前缀及实际终答；不匹配的分支不恢复为原生历史 |
| 保留工具关系 | `project_conversation_history` 消费已物化、可见的 CitableInput，把已结束运行的完整交换放在对应历史终答之前；当前轮仍在末尾续接，结果不再重复进入执行材料区 |
| 请求布局 | 原 ModelToolExchange 增加可选的 `before_message_index`；位置随原请求封存，Adapter 检查范围、顺序、host／model 和原 ID 配对。缺省位置表示末尾，不改写 assistant 或推理字段 |
| 引用展示 | `render_citable_input` 展示元数据及 `evidence_id\|原文`，逐字保留行文本和坐标；完整 typed 记录及引用绑定保持，文件 owner 由 Runtime 恢复，不逐项重发 |
| 压缩与恢复 | 原容量估算、输出／协议预留及 HistoryCompactor 保持。重放仍消费压缩后的可见集，不从原 Journal 绕过选择恢复隐藏结果；原件和现有摘要继续可用 |

正式装配仍为 HTTP → ConversationService → 原 Model Port／Adapter。历史派生内聚于 `model_history.py`，展示归 `citations.py`，Service 只装配；没有 Application 自行拼接 provider 协议或第二份可写会话。跨模块决定由 [ADR 0042](../../adr/0042-native-model-tool-continuation.md)拥有。只改 JSON 空白不能恢复轮次关系，固定增加摘要调用又不能替代原生协议，因此未采用这两个替代方案。

## 参考依据与本地差异

- [Hermes 的请求副本](https://github.com/NousResearch/hermes-agent/blob/9dfbde19db7b108f9e961eec367ca5b54c8ad7d6/agent/conversation_loop.py#L2238)及[配对工具返回](https://github.com/NousResearch/hermes-agent/blob/9dfbde19db7b108f9e961eec367ca5b54c8ad7d6/agent/tool_executor.py#L2739)：历史记录与发送视图区分，工具结果保持调用身份；本工程复用既有 Journal 和引用，不迁移其数据库或有损裁剪分支。
- [DeepSeek Harness 的历史投影](https://github.com/deepseek-ai/deepseek-harness/blob/b150a551b8d465e31e418e1b2eaf5e79bbb7d28e/packages/core/session/src/index.ts#L726)及[成组压缩边界](https://github.com/deepseek-ai/deepseek-harness/blob/b150a551b8d465e31e418e1b2eaf5e79bbb7d28e/packages/compaction/compaction-basic/src/region.ts#L98)：原事件留存，模型只消费当前可见历史；本工程继续采用原压缩器，不引入其事件框架或直接照搬阈值。
- [MiniMax 正式协议](https://platform.minimax.io/docs/api-reference/text-openai-api)要求多轮工具对话保留完整 assistant、tool_calls 和 reasoning_content。本次按原字段传递，不把推理拼进用户正文。

## 验证范围与效果

六个完整真实首步输入的零模型投影全部通过，原 assistant／推理、引用行逐字可逆及轮次位置成立；同源第六轮材料展示从 190,877 降至 125,625 字符，减少约 34.2%。剩余 system 材料区为 21,019 字符，其余观察进入工具返回。恢复参数和推理后全部 messages 为 390,689 字符，因此不把 system 变短称为总输入降低。证据见[离线报告](../../../.tmp/h630/offline-report.json)。

新空对话只使用原题和 CSV，完整交付 6/6。21 次实际请求逐项通过原问答、历史观察、原生响应、引用及 SDK 绑定审计；历史观察在第二至六轮继承 6／7／9／11／14 条，Intent／criteria 和 Runtime 核验调用均为 0。原六个外部会话运行不会被当前分支选入，21 份实际存储请求恢复及摘要绑定通过。见[请求审计](../../../.tmp/h630/audit.json)和[恢复与范围审计](../../../.tmp/h630/scope-and-restoration-audit.json)。

本次仍为 direct／none，非发布证据。压缩未触发，英文镜像只完成注册及结构核对；不计跨轮压缩后的语义保真、其他 Provider 或所有研究入口通过。主模型仍自主选择动作，不新增前置 criteria、claim 或核验阶段。相对旧随机轨迹的分差、调用数和 tokens 变化只报告本例观察，不能当作单项机制的独立质量贡献。

## 失败处理与重新打开条件

原结果集合视图的问题由真实请求定位，生产仅保留新的当前路径。评分启动因旧资格目录缺失在请求前停止；现存资格属于其他配置，遂复用校验有效的旧正反样例重新取得相同 MiMo 协议资格，原六份生成未改写或重跑。两个资格调用通过，共 5,300 tokens；零模型脚本导入及总预留检查的失败另保留。新增资格与评分统一计量，外层上限按 308,610 的必要预留一次调整为 400K，内层配置、Prompt 和正确性判据保持。完整费用由验证记录拥有。

后续新的真实任务若再次丢失本次范围内的历史调用／返回、错误串入其他分支、破坏引用原文或绕过压缩可见集，则按新轨迹重新打开本问题；独立的数量判断、标签映射或计算错误不否定已成立的历史组织机制。

## 2026-11-03：补齐核验反馈与实际修复的历史顺序

最新状态：该核验反馈范围已由新的真实全量运行重新打开。第四轮同号回执跨 run 碰撞，4 份失败反馈在 5 次后继实际请求中遗漏；第五轮两次压缩后仍容量失败。当前活动问题及新增用例由[目标维护 Spec §9.18—§9.19](../to_verify/analysis-goal-maintenance.md#918-核验反馈与实际修复按原交互进入主循环)拥有，结果见[记录 §38](../to_verify/verify_results/analysis-correctness.md#38-完整反馈历史候选的-task2-全量连续运行)。下文 52 阶段通过仅属于该旧输入集，不再作为当前完整历史契约关闭的依据；2026-10-30 的工具配对与引用成果保持原范围。

新的真实 task2 第三轮复现了另一处历史投影缺口：主模型只收到最新核验回执，旧候选持续累计，最新判决却位于旧回答之前。问题按该范围重新打开，先行设计由[目标维护 Spec §9.18](../to_verify/analysis-goal-maintenance.md#918-核验反馈与实际修复按原交互进入主循环)拥有。此次局部修复已完成：删除 latest-only 核验筛选，`decision_input_indices` 恢复自动核验与触发决定的归属，`ModelToolExchange.runtime_feedback` 在原 assistant／tool 之后交给 Adapter；同一合法分支的前轮判决按原交换继承。真实判决从可见输入派生，不新增判断、工具、存储或调用，主请求摘要与字符计量包含反馈；压缩使用同一原子归属组。

原三轮 52 个完整真实主决策阶段通过当前生产投影和 SDK 序列化回放，核对全部当时已发生的回执、判决原文与对应稿件、先后顺序、跨轮保留及原 assistant／工具 ID 配对。原第三轮内部第 20 次请求从本轮仅 1 份回答回执恢复为全部 9 份，并分别跟随对应候选；前两轮的判决也按各自位置保留。结果见[封存离线报告](../../../.tmp/runtime-feedback-history-20261103/replay-04/report.json)，新增模型与执行调用均为 0。首次回放脚手架缺少引用视图包装的失败保留在同目录 `replay-01`；后续仅完善脚手架与断言，生产修正没有多次试采或替换原结果。

当时历史保留与时序缺陷按上述旧输入集的局部判据关闭；原 task2 运行及评分暂停、第三轮未交付均保持旧身份。没有验证主模型能否据此修正补位，也没有新触发摘要或恢复原终态；这些边界不计为本次离线历史检查通过。后续真实输入若再次丢失或错置对应反馈，按新轨迹重新打开。
