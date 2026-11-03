# LLM 决策设计的实践对照

复核日期：2026-10-29。以“如何作出能完成任务的决定”为比较目标。源码条目为 A 级，官方说明补充公开行为；未执行第三方项目或模型调用。固定提交仅证明所列分支，不能证明 personalAgent 的决策正确率或最新版本行为。

## 1. PydanticAI：输入依赖、输出验证和执行循环共同工作

固定提交：`pydantic/pydantic-ai@922ee561846333665a5bd5391e175b4b20867667`。

- [Agent 装配](https://github.com/pydantic/pydantic-ai/blob/922ee561846333665a5bd5391e175b4b20867667/pydantic_ai_slim/pydantic_ai/agent/__init__.py#L1846)：准备输出契约并构造图；`GraphAgentDeps` 接收实际依赖、输出校验器、用量限制及取消上下文。
- [实际请求与消费](https://github.com/pydantic/pydantic-ai/blob/922ee561846333665a5bd5391e175b4b20867667/pydantic_ai_slim/pydantic_ai/_agent_graph.py#L2825)：`ModelRequestNode` 使用真实消息和工具／输出参数，请求前检查用量；`CallToolsNode` 处理响应，进入工具、再次请求或结束分支。
- [结构与结果验证](https://github.com/pydantic/pydantic-ai/blob/922ee561846333665a5bd5391e175b4b20867667/pydantic_ai_slim/pydantic_ai/_output.py#L1092)：`ObjectOutputProcessor.validate()` 调用实际类型校验器；`OutputValidator` 调用应用提供的验证函数，验证错误和 `ModelRetry` 进入相应恢复处理，不只声明一个输出类型。
- [工具消费](https://github.com/pydantic/pydantic-ai/blob/922ee561846333665a5bd5391e175b4b20867667/pydantic_ai_slim/pydantic_ai/tool_manager.py#L601)：参数经实际校验，`handle_call()` 再组合校验与执行。拒绝结果仍须由调用方正确分类，不可把消息字符串当成功。
- [预算边界](https://github.com/pydantic/pydantic-ai/blob/922ee561846333665a5bd5391e175b4b20867667/pydantic_ai_slim/pydantic_ai/usage.py#L603)分别检查请求、tokens、费用及工具调用限制；这是执行控制，不能使错误语义自动变正确。

**可采用：** 将必要依赖、清楚的输入表达、类型校验、业务验证及错误反馈连成实际消费链。单次判断也需要这一最小支撑，但不因此必须增加多步 agent。

**适用差异：** 验证函数能检查什么取决于应用的事实与判据；本工程的语义、权限、执行和完成责任继续分开。框架允许转换结果或自动恢复，不授权本工程静默补业务语义。工具输出策略及终止条件须沿实际模型和分支核对。

公开输入依赖与输出方式补充见 [Dependencies](https://ai.pydantic.dev/dependencies/)及 [Output](https://ai.pydantic.dev/output/)。运行时依赖须经指令或工具结果进入请求，不能只因它存在于代码对象中就认定模型已获得信息。

## 2. LangChain：响应结构由运行图解析并决定后续动作

复用仓库已有参考并重新核对：`langchain-ai/langchain@b15a385cb1aa4507b86a3ba1e6430748b0c4ae4b`。

- [策略装配](https://github.com/langchain-ai/langchain/blob/b15a385cb1aa4507b86a3ba1e6430748b0c4ae4b/libs/langchain_v1/langchain/agents/factory.py#L1062)：`create_agent()` 根据输出契约准备结构化结果工具，调用时选择原生结构化策略或工具承载策略。
- [实际解析及反馈](https://github.com/langchain-ai/langchain/blob/b15a385cb1aa4507b86a3ba1e6430748b0c4ae4b/libs/langchain_v1/langchain/agents/factory.py#L1246)：`_handle_model_output()` 处理当前策略；工具策略将参数交给 `OutputToolBinding.parse()`，可按错误策略回传与原 call ID 配对的反馈。
- [校验的具体边界](https://github.com/langchain-ai/langchain/blob/b15a385cb1aa4507b86a3ba1e6430748b0c4ae4b/libs/langchain_v1/langchain/agents/structured_output.py#L77)：该提交的原始 JSON Schema 字典分支直接返回数据；类型分支经 `TypeAdapter.validate_python()`。不能把“配置过 Schema”概括为所有分支都执行了相同本地校验。
- [继续或结束](https://github.com/langchain-ai/langchain/blob/b15a385cb1aa4507b86a3ba1e6430748b0c4ae4b/libs/langchain_v1/langchain/agents/factory.py#L1997)：运行边检查待处理调用与本轮结构化结果，分派工具、返回模型或退出；得到结构化结果不代表本工程的用户结果与 Completion 已通过。

**可采用：** 配置、实际请求、解析、反馈、循环控制逐项相连；根据当前观察决定继续，保留工具执行结果供下一次模型调用使用。

**适用差异：** 原生策略和工具策略的错误处理不同，不能推断所有错误都会自动重试。当前库的能力识别、JSON Schema 分支或退出条件不替代本工程服务方核对、本地契约及完成门禁。

公开行为补充见[结构化输出](https://docs.langchain.com/oss/python/langchain/structured-output)与[上下文组织](https://docs.langchain.com/oss/python/langchain/context-engineering)。这些动态页面与固定源码版本分别解释，不据页面新参数推定固定版本已支持。

## 3. 综合采用与复杂任务设计

以下是依据上述机制和本工程约束作出的设计结论，不是外部项目的统一实现承诺。

| 问题 | 对设计的要求 |
| --- | --- |
| Schema 能否保证决定正确 | 形状与语义分开验证；字段合法不证明依据充分、选择正确或任务完成 |
| 输入是否必须全部结构化 | 程序输入保持 typed；模型接收能理解且保真的必要事实，不机械注入完整内部对象 |
| 何时需要多步 Runtime | 当前观察会改变后续决定时使用反馈循环；固定依赖用显式编排，单次判断保留最小实现 |
| 怎样引导复杂任务 | 形成有完成条件的子目标，每轮提供当前事实和可用动作，消费真实结果后修订计划并检查整体交付 |
| 是否要增加规划、核验或多模型 | 分别说明真实消费者、可判断标准、成本与预期收益，有必要才加入 |

例如，任务要求依据多份资料给出建议：先明确建议必须覆盖的用户要求；模型识别缺证并选择读取，Runtime 返回实际材料及范围；模型据新材料修订判断，证据不足时继续补证或明确限制；最终按用户结果和证据支持验收。计划、引用或工具回执分别证明对应事实，不能单独证明建议已满足要求。

[Anthropic：Building effective agents](https://www.anthropic.com/research/building-effective-agents)（2024-12-19，B 级官方工程文章，2026-10-29 复核）补充固定子任务链、动态任务分解及环境反馈的适用条件。本技能采用其按任务选择简单流程与反馈循环的思路，不默认引入所有规划、并行或评价组件；文章已提示工具生态变化，不把其中框架列表当作当前技术清单。

来源复核与采用遵守 [EVD](../../../../docs/devSpec/change-evidence.md#6-外部参考的证据分级)。已有有效对照可复用；新增机制时明确“参考怎样做、当前怎样做、差异为何必要”，本地收益仍按实际任务验证。

## 4. 任务理解不自动形成前置调用

本节补充复核日期：2026-10-30。以下按已核对入口区分主模型理解任务、显式前置分析及独立执行者；不将框架允许的扩展推定为所有配置的默认行为。

- **Hermes 的核心对话路径：** 固定提交 `NousResearch/hermes-agent@9dfbde19db7b108f9e961eec367ca5b54c8ad7d6` 的 [run_conversation](https://github.com/NousResearch/hermes-agent/blob/9dfbde19db7b108f9e961eec367ca5b54c8ad7d6/agent/conversation_loop.py#L1823)接收用户消息与历史，准备当前消息、系统提示和工具请求，循环消费模型决定与工具结果。该入口没有固定的 criteria 提取阶段；不能由此断言所有可选插件、压缩或其他配置都没有额外调用。
- **DeepSeek Harness 的默认驱动：** 固定提交 `deepseek-ai/deepseek-harness@b150a551b8d465e31e418e1b2eaf5e79bbb7d28e` 的 [preStep 与 step](https://github.com/deepseek-ai/deepseek-harness/blob/b150a551b8d465e31e418e1b2eaf5e79bbb7d28e/packages/core/agent-loop/src/agent.ts#L225)组装提示与动态状态，将输入追加到会话，再从 `deriveMessages()` 构建模型请求、消费响应和工具动作。这个默认驱动没有把任务理解规定为独立模型阶段；扩展点存在不等于默认启用前置语义调用。
- **Anthropic 的研究系统：** [公开架构说明](https://www.anthropic.com/research/multi-agent-research-system)（2025-06-13，官方工程说明，非完整源码）描述主研究 Agent 分析用户问题、制定策略、分派工作并综合结果。任务分析属于主研究 Agent 的工作；该说明没有将其定义为一次固定的独立 criteria 调用，也不足以还原所有物理请求。
- **明确阶段链的适用性：** [Building effective agents](https://www.anthropic.com/research/building-effective-agents)将固定子任务链与动态行动循环分开，举出先生成并检查提纲再写正文、先分类再路由的用法。采用的是“前一步产生下一步需要的产物”这一机制，不把其示例扩大为所有任务都须先抽取标准。

**设计推导：** 任务理解是完成任务所需的能力，独立调用只是可选实现。优先比较由主模型直接理解并行动的简单方案；确需单独路由、用户确认，或任务定义被多个真实消费者复用时，再评估拆分。复杂或长历史本身不证明应增加调用；须核对拆分是否减少目标遗漏、错误继承或协调成本，并计入额外延迟、输入重复与解释失真。

若单独调用，前置阶段接收原始请求、仍有效的会话条件，以及解释指代所需的实际材料，输出足够交接的任务理解、来源与待澄清项。执行阶段继续接收必要原始依据，再加前置阶段的实际产物、当前能力及执行反馈。两阶段各有适用的职责提示，不能只给执行者一份脱离原话的结论；任务解释可被纠正，不能以便于通过为由改变用户标准。具体历史及 think 的组织复用 [Context 实践](context-lifecycle.md#3-同一任务的不同调用不必共享所有历史)，不新增固定的大型任务理解 Schema。
