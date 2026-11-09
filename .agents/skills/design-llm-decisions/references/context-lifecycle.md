# 多次 LLM 调用中的 Context 组织实践

复核日期：2026-10-29。以外部 Agent 的实际装配、调用和消费源码为依据；未运行第三方项目或模型。固定提交证明相应分支，动态 API 文档只说明复核时的协议，不能据此推定所有历史版本行为一致。

Context 是某次模型调用实际收到的信息。以下分别检查运行记录、当前会话历史和最终请求，不能将三者统称为“全部 context”。重点查找符号：`api_messages`、`archive_and_compact`、`deriveMessages`、`surfaceOp`、`reasoning_content`。

## 1. Hermes：发送副本、旧历史压缩与原记录分开

固定提交：`NousResearch/hermes-agent@9dfbde19db7b108f9e961eec367ca5b54c8ad7d6`。

| 环节 | 核对到的实现 |
| --- | --- |
| 构造真实请求 | [conversation_loop.py](https://github.com/NousResearch/hermes-agent/blob/9dfbde19db7b108f9e961eec367ca5b54c8ad7d6/agent/conversation_loop.py#L2238)从当前消息结构复制发送副本，清除内部元数据、执行适配，再加入系统提示；不是将会话统一转为长文本 |
| 续接工具调用 | 主循环调用工具执行器；[tool_executor.py](https://github.com/NousResearch/hermes-agent/blob/9dfbde19db7b108f9e961eec367ca5b54c8ad7d6/agent/tool_executor.py#L2739)可按配置外置大结果，再构造带调用身份的工具结果并追加、持久化 |
| 控制历史规模 | [context_compressor.py](https://github.com/NousResearch/hermes-agent/blob/9dfbde19db7b108f9e961eec367ca5b54c8ad7d6/agent/context_compressor.py#L4029)存在确定性的旧结果去重、裁剪路径；另有整段压缩及可配置的轮后滚动摘要，不仅在每次调用后无限追加 |
| 滚动摘要 | [微压缩入口](https://github.com/NousResearch/hermes-agent/blob/9dfbde19db7b108f9e961eec367ca5b54c8ad7d6/agent/context_compressor.py#L6678)合并已有摘要与较旧交互，保留决定、需求、路径和未决问题；使用 Markdown 小节，删去失效细节 |
| 恢复与原文 | [hermes_state.py](https://github.com/NousResearch/hermes-agent/blob/9dfbde19db7b108f9e961eec367ca5b54c8ad7d6/hermes_state.py#L11260)的原地压缩事务将旧行软归档，写入新的活动消息。活动历史加载与归档检索分开；归档原文仍可由对应查询恢复 |

**可采用：** 消息原件与请求适配副本分开；大工具结果按需外置；压缩当前工作历史并维护一致的恢复视图，而非仅在内存删消息。摘要中的可读结构服务于继续任务。

**边界：** 上述归档能力针对已核对的 SessionDB 路径，不代表所有日志、插件或部署都提供相同恢复能力。裁剪包含有损分支，不能宣称压缩天然无损。其稳定系统提示与缓存策略不意味着动态事实也应冻结。

## 2. DeepSeek Harness：追加事件，用摘要替换模型可见的片段

固定提交：`deepseek-ai/deepseek-harness@b150a551b8d465e31e418e1b2eaf5e79bbb7d28e`。

1. **调用前组装。** [agent.ts](https://github.com/deepseek-ai/deepseek-harness/blob/b150a551b8d465e31e418e1b2eaf5e79bbb7d28e/packages/core/agent-loop/src/agent.ts#L225)组装系统提示、工具和动态内容；每个执行步骤再从 `session.deriveMessages()` 取得请求消息。这里的 surface 指事件日志中当前被选为模型可见历史的有序片段。
2. **原事件与工作历史分开。** [Session](https://github.com/deepseek-ai/deepseek-harness/blob/b150a551b8d465e31e418e1b2eaf5e79bbb7d28e/packages/core/session/src/index.ts#L604)按顺序追加不可变事件，`deriveMessages()` 按当前 surface 生成消息；日志恢复会重放相同的片段变更，不等于把全部事件发给模型。持久化存储由相应后端负责。
3. **动态信息按变化传递。** [runtime-context.ts](https://github.com/deepseek-ai/deepseek-harness/blob/b150a551b8d465e31e418e1b2eaf5e79bbb7d28e/packages/core/agent-loop/src/runtime-context.ts#L61)比较当前快照，仅有变化才生成新消息；[提示渲染](https://github.com/deepseek-ai/deepseek-harness/blob/b150a551b8d465e31e418e1b2eaf5e79bbb7d28e/packages/core/system-prompt/src/index.ts#L236)说明新快照取代旧快照。
4. **压缩有真实入口。** 标准预设装配压缩器与工具结果裁剪器；[压缩器](https://github.com/deepseek-ai/deepseek-harness/blob/b150a551b8d465e31e418e1b2eaf5e79bbb7d28e/packages/compaction/compaction-basic/src/index.ts#L137)在步骤前检查压力，并处理模型请求超窗。保留近期尾部时，[片段选择](https://github.com/deepseek-ai/deepseek-harness/blob/b150a551b8d465e31e418e1b2eaf5e79bbb7d28e/packages/compaction/compaction-basic/src/region.ts#L98)退回到工具配对完整的边界。
5. **摘要替换可见历史。** [摘要提示](https://github.com/deepseek-ai/deepseek-harness/blob/b150a551b8d465e31e418e1b2eaf5e79bbb7d28e/packages/compaction/compaction-basic/src/summarizer.ts#L31)采用 Markdown，记录目标、文件、错误处理、待办、当前工作、下一步及关键约束；已有摘要更新时保留有效内容、去掉过期内容。该辅助调用复用原系统提示、工具与选定消息前缀，再追加摘要指令，兼顾缓存复用。
6. **落地与失败边界。** 摘要器拒绝空摘要、输出截断和错误结果；[提交事务](https://github.com/deepseek-ai/deepseek-harness/blob/b150a551b8d465e31e418e1b2eaf5e79bbb7d28e/packages/compaction/compaction-basic/src/region.ts#L359)要求带包装的摘要更短且片段未变化，追加摘要事件与替换事件，并保留来源事件序号。原始事件不因此被物理删除。

**可采用：** 运行记录持续追加，模型可见历史允许受控替换；动态快照有更新语义；完整工具交互作为压缩边界；原记录与替换关系可追溯。

**边界：** 保留来源事件序号不自动提供模型重读原文的工具，本次没有据此确认通用恢复入口。压缩默认比例与 Hermes 的有效输入预算口径不同，不照抄为统一阈值；更短、无协议错误也不证明任务信息完整。

## 3. 同一任务的不同调用不必共享所有历史

- **Hermes 的独立子任务：** [delegate_tool.py](https://github.com/NousResearch/hermes-agent/blob/9dfbde19db7b108f9e961eec367ca5b54c8ad7d6/tools/delegate_tool.py#L1173)用任务目标、显式补充材料和必要工作区规则构造子任务提示；子调用从新会话开始，父任务消费子任务结果，而不默认复制其全部工具轨迹与推理。
- **DeepSeek Harness 明确区分两种方式：** [spawn](https://github.com/deepseek-ai/deepseek-harness/blob/b150a551b8d465e31e418e1b2eaf5e79bbb7d28e/packages/subagent/subagent-spawn-in-process/src/index.ts#L41)以新会话开始；[fork](https://github.com/deepseek-ai/deepseek-harness/blob/b150a551b8d465e31e418e1b2eaf5e79bbb7d28e/packages/subagent/subagent-fork-in-process/src/index.ts#L40)继承父任务到最近已结束轮次的日志前缀，排除尚未配对完成的当前工具交互。它们是可选能力，不是每个任务都会执行的固定阶段。
- **Deep Agents 提供同一实现中的两种上下文模式：** 固定提交 `langchain-ai/deepagents@3efa098130d6670fe713f841072bc11ff40545da` 的[调用准备](https://github.com/langchain-ai/deepagents/blob/3efa098130d6670fe713f841072bc11ff40545da/libs/deepagents/deepagents/middleware/subagents.py#L804)在独立模式下用任务说明创建消息，在继承模式下传入父任务有效历史及新任务说明。[历史构造](https://github.com/langchain-ai/deepagents/blob/3efa098130d6670fe713f841072bc11ff40545da/libs/deepagents/deepagents/middleware/subagents.py#L380)应用已有压缩并去掉末尾尚待响应的委派调用。存在继承模式不证明所有独立阶段都应使用它。
- **OpenAI Agents SDK 提供工具历史过滤能力：** 固定提交 `openai/openai-agents-python@cd26bbbc52847845fde73b9952b51e62e2bcbdc0` 的[remove_all_tools](https://github.com/openai/openai-agents-python/blob/cd26bbbc52847845fde73b9952b51e62e2bcbdc0/src/agents/extensions/handoff_filters.py#L33)可过滤交接历史中的结构化工具条目，也会移除相应 reasoning 条目；它是显式选择的过滤器，不是所有交接的固定行为。已被复制到普通正文或摘要中的工具内容不会因此自动消失，不能把该函数当作语义相关性判断或跨服务方续接协议。

**设计推导：** 外部实践同时允许独立输入与历史继承，不能据其中一种得出所有调用都应清空或全量继承的结论。先判断下一次调用的信息依赖；职责独立的阶段也可以是普通模型调用，无需新增 agent。交接应覆盖整体目标、本阶段问题、仍有效前提、实际结果与证据、未知项及输出消费者；独立核验应有原始要求与真实待验结果，生成者自评只说明其主张。

例如，目标解释调用遇到“沿用上一轮短名单”“按原门槛”时，需要相关用户原话、历史答复，以及能够确定所指对象和口径的实际材料。材料可能来自研究工具，不能因它不是目标解释调用产生的就排除；内部重试、无关输出和完整计算代码则不因同属任务就必须进入。只保留历次目标解释会丢失原始依据，统一传入全部记录也不是已证明的最优方案。相关工具结果可以作为带来源和适用范围的数据交接；若重放原生交互，仍须满足工具配对与服务方推理协议。尚不能可靠筛选且没有补读能力时，优先保证必要信息覆盖，再验证裁剪效果。

[Anthropic 的 Context 工程说明](https://www.anthropic.com/research/effective-context-engineering-for-ai-agents)（2025-09-29，2026-10-29 复核）补充逐轮选择信息、按需读取及压缩的取舍，并强调先保证相关信息召回再减少冗余。这是官方工程建议，不能替代上述源码路径，也不证明任一种组织方式在本地任务上必然更好。当前 skill 作为可修订的方法稿，采用结论须由参考机制、实际输入及任务结果共同核对。

## 4. think 是否回传取决于协议与调用关系

think 在这里指服务方返回的推理字段或内容块，不等于应用设计的计划、简要依据或工具结果。

- [DeepSeek Thinking Mode](https://api-docs.deepseek.com/guides/thinking_mode/)在复核时规定：携带工具定义的 thinking 请求，要回传历史推理字段 `reasoning_content`，包含没有实际调用工具的轮次；不带工具定义时，旧推理字段不参与后续上下文。不能把早期模型的行为当当前统一规则。
- [Claude 的工具续接说明](https://platform.claude.com/docs/en/build-with-claude/thinking-tool-workflows)要求工具结果返回时，带回完整且未修改的 assistant 内容，包括需要保留的推理块、签名及不可读的推理内容；只摘取正文或重建遗漏字段的消息会破坏协议。
- Hermes 的发送构造也保留相关服务方推理元数据。具体规则仍须核对实际适配器、模型与模式，不能从某一种消息格式外推所有服务方。

**设计推导：** 同一会话续接由适配器忠实处理协议要求；独立阶段默认通过显式成果与依据交接，不把另一次调用的 think 当作通用共享状态。不可见推理无需尝试提取，必要业务信息也不能只存在于推理中。历史压缩应尊重仍需续接的协议内容，不自行摘要重写签名或不透明推理块。

Markdown 是已核对实现中的文本组织手段，没有单独证明它优于所有格式。需要保留什么、如何交接及压缩后能否完成原任务，比统一使用某种标记格式更关键。
