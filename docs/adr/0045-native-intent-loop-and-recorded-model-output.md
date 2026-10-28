# ADR 0045：Loop 使用原生意图与可恢复模型响应

状态：原生协议已接入，替代 ADR 0017 的 `prepare_final`＋独立 Final JSON 协议。首版第 17 轮失败后的修订、真实生成、连续交付和恢复结果见 [Loop Spec §16](../optimization/to_verify/conversation-loop-schema.md#16-完整运行结果与实际边界)；流程验证与语义正确性分别报告。执行、核验和 Completion 责任保持。

## 背景与问题

真实 LongDS 第14轮已完成计算并调用空 prepare_final，后续两次 JSON-mode 成文均返回完整 Markdown，导致未交付；应用又将本地输出错误统一暴露为 HTTP 503。实际模型在原生工具阶段已表达合法动作，不能把问题归为 MiniMax 一般能力不足。原件及完整输入构造见[唯一设计](../optimization/to_verify/conversation-loop-schema.md#1-目标范围与真实依据)。

同一循环还把内部身份、修订 union 和完成相位暴露到模型 Schema；内层修复只交回末份响应，无法完整留存与续接。以上属于模型交互和恢复协议的跨模块调整，故记录本 ADR。

## 决定与责任

按[统一 Loop Schema 设计](../optimization/to_verify/conversation-loop-schema.md)及[实际开源调用链比较](../agentRef/model-interaction-protocols.md)，主循环使用原生消息／工具调用，优先处理调用；没有调用时，完整可见正文也形成回答候选。`submit_final` 携带沟通意图、行引用等属性，`revise_final` 修订现稿，两者进入同一提交出口。首版要求所有正文先调用 `submit_final`，已被第 17 轮反例否定。空准备动作与第二次普通成文已删除，claims 继续以业务操作接入同稿出口。

模型决定语义、工具、代码及正文。Runtime 恢复身份／范围／版本，Admission 只接纳或拒绝，执行 owner 写事实，Verifier 与 Completion 各守原职责。原生终止和研究操作独占批次，执行前检查，不根据模型自述批准自己。

内部typed结果按请求声明策略。意图判断及原grounding修订采用提示式JSON文本，不请求未经核实的API格式功能；其他native typed能力及非Loop默认profile保留。原类型、来源Admission及同模式有限修复不变。完整响应在解码前经 typed Port 记录者提交原 Journal／Artifact；稳定 invocation_id、逐次原件及 continuation 支持重启先解码付费输出、恢复有限修复次数。引用只选择当前合法身份，已有正文由 Runtime 恢复。安全错误在 Web／SSE 投影，不能混淆上游 HTTP、本地输出和 Runtime 故障。

原生 typed 修复继续调用同一输出工具，JSON 消费者保留原承载。主回复支持正文，不放宽内部 Schema 或跳过 claims、计划审阅、核验及 Completion。流式 `role` 按结构字段聚合，持续失败事实写入原响应记录，先保存、再校验并用于恢复。缺少终止 `finish_reason` 的响应在保存后拒绝，EOF 不能代替结束事实。首版失败与计费保留，修订后的实际验证范围由上述 Loop 结果拥有。

## 取舍、复杂度与防护

放弃继续加重 JSON 提示、自动把任意正文包装成功、保留双终止协议，以及更换模型来回避协议问题。参考采用携带正文的 finish 和 ToolStrategy；本工程适配保留权限、执行绑定、引用保真及完成检查，未复制第三方先执行再检查混批的顺序。

删除一个模型相位、旧控制字段／Prompt 与 Final 大 union；新增的业务参数投影和逐响应续接字段只服务真实提交、错误和恢复消费者。ModelResponseRecord 是完整 Provider 原件的 immutable 记录，派生 raw／usage 不独立写入，不增加响应数据库或第二收费账本。完成步骤可按新证据重开，原执行事实保留。

## 迁移、验证与撤回

本工程处于正式兼容期前，内部契约在同一变更替换全部生产者、消费者、Prompt 和文档，不保留旧协议 fallback。封存失败 run 不转换、不续跑成新成功；新版本验证使用新身份。若发现真实活跃外部消费者／run，先记录具体兼容事实，不能猜补旧响应。

验证按唯一设计 P0–P6：真实阶段连续模型生成、原件／引用／反馈与新进程恢复、内层消费者、REST／SSE真实失败投影，再进行完整36轮。生成次数、用量、语义与流程分别报告；未知token不单独停止。首版P1通过后，真实完整任务在第17轮再次暴露普通正文通道缺口，故按新实际阶段修订并重新验收；旧原件和已成立检查点保留。实时状态与计数由唯一设计拥有。

迁移检查读取当前配置的数据目录，未发现活跃 Journal head（0 个）；该检查仅覆盖当前目录，不代表封存旧 run 可以按新协议恢复。历史原件维持只读，独立阶段投影的适用范围在唯一设计中明确。

若候选在预声明边界失败，保留原始失败与已成立检查点，按最早责任复审；撤回对应未成立改动，不复活一套并存终止协议。必要版本回退依靠本次改动前工作区快照及版本身份，不覆盖用户其他改动。
