# 输出 Schema 的字段语义与场景设计

复核日期：2026-10-31。适用于模型工具参数与结构化结果。本文从固定开源源码归纳设计方法，不记录具体工程任务或故障；源码存在不代表本工程效果已验证。

## 1. 开源实现怎样把说明交给模型

### PydanticAI：参数文档进入字段 Schema

固定提交：`pydantic/pydantic-ai@922ee561846333665a5bd5391e175b4b20867667`。

- [`doc_descriptions`](https://github.com/pydantic/pydantic-ai/blob/922ee561846333665a5bd5391e175b4b20867667/pydantic_ai_slim/pydantic_ai/_griffe.py#L23)解析函数说明与参数文档；[`function_schema`](https://github.com/pydantic/pydantic-ai/blob/922ee561846333665a5bd5391e175b4b20867667/pydantic_ai_slim/pydantic_ai/_function_schema.py#L153)把参数说明补入缺少 description 的字段，再生成 JSON Schema。
- 同一构造器在启用 `require_parameter_descriptions` 时收集缺失参数文档并[拒绝生成](https://github.com/pydantic/pydantic-ai/blob/922ee561846333665a5bd5391e175b4b20867667/pydantic_ai_slim/pydantic_ai/_function_schema.py#L223)。该选项默认关闭，不能概括成框架始终强制完整说明，也不代表文字内容已通过语义审查。
- [`Tool.tool_def`](https://github.com/pydantic/pydantic-ai/blob/922ee561846333665a5bd5391e175b4b20867667/pydantic_ai_slim/pydantic_ai/tools.py#L564)交出工具描述和生成后的参数 Schema；[模型适配器](https://github.com/pydantic/pydantic-ai/blob/922ee561846333665a5bd5391e175b4b20867667/pydantic_ai_slim/pydantic_ai/models/openai.py#L2457)把它们放入实际工具定义。

采用：类型负责形状，参数文档负责含义，并沿导出与适配链检查说明是否真正送出。业务字段缺少必要说明应在设计或已有检查入口发现；不能只在工具总描述中列字段名。

### Hermes：字段说明与操作场景共同定义更新语义

固定提交：`NousResearch/hermes-agent@9dfbde19db7b108f9e961eec367ca5b54c8ad7d6`。

- [`TODO_SCHEMA`](https://github.com/NousResearch/hermes-agent/blob/9dfbde19db7b108f9e961eec367ca5b54c8ad7d6/tools/todo_tool.py#L294)的工具说明交代适用场景、读取与写入、返回完整清单，以及列表顺序和完成状态的使用规则。
- 字段不只声明类型：`todos` 说明提交列表用于写入、省略用于读取；`merge` 说明 true 按 ID 合并、false 完整替换。数组元素的字段与必填项在同一 Schema 中定义。
- [`registry.register`](https://github.com/NousResearch/hermes-agent/blob/9dfbde19db7b108f9e961eec367ca5b54c8ad7d6/tools/todo_tool.py#L357)注册该 Schema；[`get_definitions`](https://github.com/NousResearch/hermes-agent/blob/9dfbde19db7b108f9e961eec367ca5b54c8ad7d6/tools/registry.py#L1044)按工具选择生成模型可见定义；[执行入口](https://github.com/NousResearch/hermes-agent/blob/9dfbde19db7b108f9e961eec367ca5b54c8ad7d6/tools/todo_tool.py#L231)依据这些参数读取或写入。

采用：把“什么条件下输出哪些参数”和“这些参数造成什么效果”同时交代。仅写“是否合并”不能替代具体更新语义。该执行入口还含字符串转 JSON 的容错，本工程不据此采用静默载荷转换；来源中的具体步数和完成策略也不自动成为本工程规则。

### LangChain：场景规则必须绑定到实际工具

固定提交：`langchain-ai/langchain@575db57ab3658e38ba1d8c40c2bf62110c8a0c27`。

- [`WRITE_TODOS_TOOL_DESCRIPTION`](https://github.com/langchain-ai/langchain/blob/575db57ab3658e38ba1d8c40c2bf62110c8a0c27/libs/langchain_v1/langchain/agents/middleware/todo.py#L52)说明何时使用、何时直接完成工作，以及开始、更新、受阻、结束时怎样处理清单；明确写清单不等于向用户交付答案。
- [`Todo` 与 `WriteTodosInput`](https://github.com/langchain-ai/langchain/blob/575db57ab3658e38ba1d8c40c2bf62110c8a0c27/libs/langchain_v1/langchain/agents/middleware/todo.py#L25)定义内容、状态及列表形状；[工具构造](https://github.com/langchain-ai/langchain/blob/575db57ab3658e38ba1d8c40c2bf62110c8a0c27/libs/langchain_v1/langchain/agents/middleware/todo.py#L220)同时绑定该描述、参数 Schema 和实际执行函数。
- [执行函数](https://github.com/langchain-ai/langchain/blob/575db57ab3658e38ba1d8c40c2bf62110c8a0c27/libs/langchain_v1/langchain/agents/middleware/todo.py#L153)更新状态并返回与调用配对的工具消息。该代码中的类型或属性注释，不应未经导出核对就算成实际字段 description。

采用：操作场景、参数形状和执行效果保持一致；说明必须绑定到被调用的工具。无需照搬长描述、具体触发步数或 Todo 完成策略，也不把此中间件视为所有 Agent 默认启用。

三份实现分别提供生成、描述和绑定的参考，不代表其中每个字段的说明都足够，也不构成统一行业契约。以下是据此归纳的设计方法。

## 2. 用字段契约指导生成

先按[字段必要性规则](../SKILL.md#41-从消费者确定模型必须输出什么)核对具体消费环节与作用冗余，再为需要模型填写的业务字段说明下列内容。内容应合并到简洁的字段说明、工具说明或输出指令中，不要求模型额外输出一份说明表。

| 设计问题 | 必须明确的内容 |
| --- | --- |
| 表达什么 | 业务含义、与相邻字段的区别；不能只复述名称或类型 |
| 依据什么填写 | 用户原话、当前输入、实际成果或已有合法选项；没有依据时怎样表达未知 |
| 什么时候填写 | 哪种动作或判断分支必填、可选、应省略或禁止 |
| 怎样填写 | 数据形状、数组元素、单位、枚举含义及选择条件、引用格式与可选范围 |
| 不填写意味着什么 | 区分省略、null、空字符串、空数组、默认值与保持不变 |
| 与其他字段什么关系 | 依赖、互斥、条件组合及排序／过滤／数量之间的关系 |
| 被消费后发生什么 | 完整替换、增量合并、删除、保持，或进入哪个必要下游分支 |

说明应放在最接近其含义的位置：字段语义进入字段 description；跨字段条件与操作时机进入工具描述；独立结果的类别选择规则进入对应输出指令。共享规则写一次，不在每个字段重复整段 Prompt。

## 3. 从场景定义操作和字段组合

对存在分支或状态更新的决定，先写清“当前情况 → 选择条件 → 动作 → 参数 → 效果”，再确定 Schema。用户没有提供的策略不能借示例补造。

例如，Hermes 的同一个 Todo 契约区分：省略 todos 读取；提交 todos 且 merge 为 false 完整替换；提交 todos 且 merge 为 true 按 ID 合并。类型都合法的参数会产生不同效果，因此不能只验证 JSON 形状而忽略选择场景。

- 先比较统一操作加枚举、可区分的结果分支和独立工具；根据字段共享程度、理解负担及服务方能力选择，不预设方案。
- 将操作前提与必需、允许、禁止字段一起表达。只藏在 validator 中的组合规则，不能作为模型已经知道规则的依据。
- 提供解释必要差异的最小完整合法示例。重点覆盖易混的非空／空数组、可选项及分支组合；只有形状而没有适用说明不够。示例依据契约，不包含特定任务答案。
- 系统已经知道的固定身份、权限和版本绑定由 Runtime 负责；模型仅选择实际需要判断的对象，不为获得合法参数反复复制内部元数据。

## 4. 把设计检查落实到实际请求

核对字段定义／参数文档 → Schema 生成 → 工具注册 → Provider 适配 → 实际请求。检查嵌套属性、引用定义、枚举、必填项、默认值和分支说明是否保持；变量存在于代码不等于模型已经收到说明。

检查既包括“是否有说明”，也包括“是否足以选对并填对”。描述齐全不保证模型遵守；严格模式约束形状也不保证动作适合当前场景。Provider 的支持范围须单独核对，不跨服务方照搬专用参数。

失败时反馈错误字段、期望类型或条件、实际不符及合法修正方向，保持原调用配对。消费同轨迹下一次参数判断是否修正，区分结构失败、场景误选和业务语义错误；不能用放宽校验、静默转换或无界重试掩盖契约缺口。

纯文档维护只检查结构、链接和源码坐标；生产变更按既定真实输入、反馈恢复及用户结果验证。技能保留通用方法和固定源码依据，本地运行与故障记录归各自权威文档。
