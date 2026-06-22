# LLM 提示词汇编

本文档收集并总结了当前工程中所有提供给 LLM 的提示词（Prompt），按功能模块分类。

---

## 目录

- [1. 入口路由与意图分类](#1-入口路由与意图分类)
- [2. 任务规划与重规划](#2-任务规划与重规划)
- [3. ReAct 步骤执行](#3-react-步骤执行)
- [4. 答案生成](#4-答案生成)
- [5. 编排节点](#5-编排节点)
- [6. 图谱提取](#6-图谱提取)
- [7. 用户交互提示](#7-用户交互提示)
- [8. Prompt 治理与优化建议](#8-prompt-治理与优化建议)
- [附录：LLM 调用汇总](#附录llm-调用汇总)

---

## 1. 入口路由与意图分类

### 1.1 意图分类 System Prompt

**文件**: [src/personal_agent/agent/router.py](src/personal_agent/agent/router.py#L244-L245)

```
你是一个严谨的意图分类器，只输出 JSON。
```

**调用参数**: `openai_small_model`, temperature=0, max_tokens=500, strict `response_format={"type": "json_schema"}`（`RouterDecision` 契约）

---

### 1.2 意图分类 User Prompt

**文件**: [src/personal_agent/agent/router.py](src/personal_agent/agent/router.py#L209-L231)

```
你是一个入口路由分类器。
请把用户输入分类到以下意图之一：capture_text, capture_link, capture_file, ask,
summarize_thread, delete_knowledge, solidify_conversation, direct_answer, unknown。
capture_text: 用户想记录文字内容。capture_link: 用户发来链接想收录。
ask: 需要检索个人知识库、公共网络或最新外部事实才能可靠回答的问题。
summarize_thread: 需要总结群聊/会话。delete_knowledge: 删除过时或错误的知识笔记。
solidify_conversation: 把对话结论沉淀为知识。
例如已有对话在讨论 DNS，用户再说"将DNS相关知识存储至知识库"，是在要求整理已有会话知识，
必须归为 solidify_conversation，不能把这条操作指令本身按 capture_text 存储。
只有用户输入本身提供了需要原样记录的实质正文时，才归为 capture_text。
direct_answer: 闲聊、问候、感谢、澄清性问题、无需检索的简单说明或常识性问题。
请重点判断信息是否具有时效性：当前天气、实时价格、最新新闻、航班状态等依赖最新外部事实的问题应归为 ask，
不得仅因问题简单而归为 direct_answer。
当输入不足以安全确定或执行意图时设置 requires_clarification=true，并提供 missing_information 和 clarification_prompt；
例如仅说"帮我"或"删除"需要澄清，而"删除关于 DNS 的知识"已提供检索范围，
应归为 delete_knowledge 且 requires_clarification=false，后续会检索候选并要求用户确认。
"你是谁""你好"是完整的 direct_answer，不需要澄清。
只返回符合 schema 的 JSON。route 是最终意图；user_visible_message 是简短分类理由。
requires_tools/requires_retrieval/requires_step_projection/candidate_tools 可以按你的判断填写，系统会再合并默认控制字段。
risk_level: 删除类操作应为 high，一般操作为 low。
requires_confirmation: 删除操作应为 true。
历史 chat messages 只用于理解指代和已有讨论主题；请分类最后一条当前用户输入，不要把历史助手回复当作事实证据。
```

**设计要点**:
- 定义了 9 种意图类型（capture_text, capture_link, capture_file, ask, summarize_thread, delete_knowledge, solidify_conversation, direct_answer, unknown）
- `solidify_conversation` 和 `capture_text` 有明确的区分规则：固化是整理已有会话知识，capture_text 是直接记录用户提供的新内容
- 时效性判断规则：天气、价格、新闻等需要最新事实的问题归为 `ask`
- `requires_clarification` 机制：输入不足时要求澄清，但已提供检索范围的删除请求不需澄清
- 删除操作: risk_level=high, requires_confirmation=true

---

## 2. 任务规划与重规划

### 2.1 任务规划 System Prompt

**文件**: [src/personal_agent/agent/step_projector.py](src/personal_agent/agent/step_projector.py#L111)

```
你是一个严谨的任务规划器，只输出含 steps 数组的 JSON 对象。
```

**当前状态**: 历史 LLM planner 已由确定性 workflow projection 替代，任务规划阶段不再调用 LLM。

---

### 2.2 任务规划 User Prompt

**文件**: [src/personal_agent/agent/step_projector.py](src/personal_agent/agent/step_projector.py#L81-L100)

```
请根据用户意图生成可被现有执行器直接执行的任务计划。
可用 action_type: retrieve(检索), resolve(从候选中解析具体目标),
tool_call(调用工具), compose(生成回答), verify(校验)。
只返回 JSON 对象，顶层仅包含 steps 数组。每个步骤包含以下字段：
  step_id(短标识), action_type, description(对用户友好的中文说明),
  tool_name(nullable), tool_input(对象),
  depends_on(前置步骤 step_id 数组),
  expected_output(可选的展示说明), success_criteria(可选的展示说明),
  risk_level(low/medium/high), requires_confirmation(bool),
  on_failure(skip/retry/abort), execution_mode(deterministic/react),
  allowed_tools(工具名数组), max_iterations(正整数)。
description 应该用自然语言向用户说明这一步要做什么，不要只写枚举值。
expected_output 和 success_criteria 仅用于界面展示，不得声明执行器不能完成的校验动作。
根据 intent 追加工作流约束：
- delete_knowledge 仅允许 retrieve(react) -> resolve -> tool_call(delete_note) -> compose；
  note_id 由执行器注入，删除确认由 delete_note 工具执行，不规划 verify。
- solidify_conversation 仅允许 compose -> tool_call(capture_text)；
  text 由执行器注入，用户已明确请求写入，不规划 retrieve、verify 或二次确认。
意图: {intent}
上下文: {context}
可用工具:
{tool_list}
```

**设计要点**:
- 定义了 5 种 action_type: retrieve, resolve, tool_call, compose, verify
- 每个步骤包含状态、安全字段及 ReAct 执行控制字段
- 关键约束由 `StepProjectionValidator` 同步硬校验：删除目标及固化正文只能在执行阶段动态注入
- 不为删除确认或固化写入生成当前执行器无法兑现的 `verify` 步骤

---

### 2.3 任务重规划 System Prompt

**文件**: [src/personal_agent/agent/restep_projector.py](src/personal_agent/agent/restep_projector.py#L104)

```
你是一个严谨的任务重新规划器，只输出 JSON。
```

**调用参数**: `openai_small_model`, temperature=0, max_tokens=500, strict `response_format={"type": "json_schema"}`（`steps` 契约）

---

### 2.4 任务重规划 User Prompt

**文件**: [src/personal_agent/agent/restep_projector.py](src/personal_agent/agent/restep_projector.py#L76-L92)

```
你是一个任务重新规划器。当前计划中的某个步骤执行失败了，
请根据失败信息和中间结果，生成替换剩余未完成步骤的新计划。
已经完成的步骤不要重新执行。

原始意图: {intent}

原始计划步骤:
{steps_summary}

失败步骤: {failed_step.step_id} ({failed_step.action_type})
失败原因: {error}

已完成的中间结果:
{obs_summary}

请返回一个 JSON 对象，包含 'steps' 数组。每个步骤包含：
  step_id(新的短标识), action_type, description,
  tool_name(nullable), tool_input(对象, nullable),
  depends_on(前置步骤 step_id 数组),
  expected_output, success_criteria,
  risk_level(low/medium/high), requires_confirmation(bool),
  on_failure(skip/abort)。
不要包含已经完成的步骤。如果无法重新规划，返回 {"steps": []}。
```

**设计要点**:
- 仅替换失败的剩余步骤，已完成步骤不重新执行
- 接收失败步骤信息、失败原因和中间结果作为上下文
- 无法重规划时返回空 steps 数组

---

## 3. ReAct 步骤执行

### 3.1 ReAct System Prompt

**文件**: [src/personal_agent/agent/orchestration_nodes/_graph_helpers.py](../src/personal_agent/agent/orchestration_nodes/_graph_helpers.py)

> 注：ReAct 已融入 Graph 编排流程，提示词由 Graph 节点共享的依赖模块统一定义。

```
你是一个在受控环境中执行任务步骤的推理助手。
每一轮必须通过工具调用表达下一步动作：需要外部信息时调用允许列表中的真实工具；
已经可以完成时调用 finish_react。
真实工具参数必须满足对应 tool schema，不要编造未提供的工具名或参数。
```

**调用参数**: `openai_small_model`, temperature=0, max_tokens=400, `tools=[允许的真实工具 schema + finish_react]`, `tool_choice="auto"`

---

### 3.2 ReAct User Prompt 模板

**文件**: [src/personal_agent/agent/orchestration_nodes/_react.py](src/personal_agent/agent/orchestration_nodes/_react.py#L75)

```
## 步骤描述
{step.description}

## 已有上下文
{context_block}

## 可用工具
{tools_block}

请开始推理（最多 {max_iter} 轮）。
```

---

### 3.3 ReAct 错误恢复提示

**文件**: [src/personal_agent/agent/orchestration_nodes/_react.py](src/personal_agent/agent/orchestration_nodes/_react.py#L107)

```
观察：LLM 输出无法解析，请重新输出 JSON。
```

当 LLM 输出无法解析为 JSON 时追加到 user prompt 中。

---

### 3.4 ReAct 工具调用错误提示

**文件**: [src/personal_agent/agent/orchestration_nodes/_react.py](src/personal_agent/agent/orchestration_nodes/_react.py#L148)

```
错误：未指定工具名。请输出合法 JSON。
```

---

## 4. 答案生成

### 4.1 答案生成 System Prompt（通用）

**文件**: [src/personal_agent/agent/runtime_llm.py](src/personal_agent/agent/runtime_llm.py#L29)

> 普通生成和流式生成共用此提示词。

```
你是一个严谨、善于归纳总结的个人知识库问答助手。你的首要任务不是复述检索片段，而是把证据整理成简洁、可信、可读的答案。
```

**调用参数**: `openai_model`, temperature=0.3, max_tokens=600

---

### 4.2 图谱增强回答 User Prompt

**文件**: [src/personal_agent/agent/runtime_ask.py](src/personal_agent/agent/runtime_ask.py#L352-L367)

```
你是个人知识库助手。请基于给定的对话上下文、图谱事实网络和原文证据，
先总结结论，再解释原因，生成一段自然、直接、连续的中文回答。
如果上下文里存在代词或省略，请结合最近几轮对话补全指代。
不要先输出「最相关实体」「关联事实」「根据检索结果」之类栏目标题，不要机械列点，不要把原始片段逐条照搬。
你的主要推理材料是图谱事实网络中的实体、关系边和事实；
笔记片段只用于核对出处、补充限定条件和引用定位。
如果证据不足，要明确指出不确定点。
回答尽量先给出一句直接结论，再补充展开说明。

当前问题：{question}

最近对话与任务上下文：
{context_block}

图谱实体：{focus_entities}

图谱事实网络（优先基于这些实体关系和事实推理）：
{graph_fact_block}

原文证据锚点（用于校验和引用定位）：
{anchored_block}

原文证据片段：
{notes_block}
```

**设计要点**:
- 以图谱事实网络为主要推理材料，笔记片段仅用于核验和引用
- 先结论后展开的结构化回答格式
- 明确禁止机械列点和逐条照搬原始片段
- 证据不足时要求明确指出不确定点

---

### 4.3 网络搜索增强回答 User Prompt

**文件**: [src/personal_agent/agent/runtime_ask.py](src/personal_agent/agent/runtime_ask.py#L237-L246)

```
你是个人知识库助手。你的个人知识库中未能找到足够依据来回答这个问题，
因此进行了一次网络搜索。请基于以下网络搜索结果，用自然中文回答问题。
重要：你必须明确指出信息来源于网络搜索，并标注每个要点的来源编号（如 [来源1]）。
如果搜索结果之间存在矛盾，请如实指出。
如果搜索结果仍不足以完整回答问题，请说明现有信息的局限。

当前问题：{question}

最近对话与任务上下文：
{context_block}

网络搜索结果：
{web_block}
```

**设计要点**:
- 必须标注信息来源于网络搜索
- 要求标注来源编号 `[来源1]`
- 结果矛盾时要求指出，信息不足时说明局限

---

### 4.4 本地知识库回答 User Prompt

**文件**: [src/personal_agent/agent/runtime_ask.py](src/personal_agent/agent/runtime_ask.py#L458-L466)

```
你是个人知识库助手。请基于最近几轮对话和当前匹配到的笔记内容证据，
用自然中文总结并回答用户问题。优先回答用户真正想问的内容，必要时承认信息不足。
不要把答案写成检索结果罗列，也不要简单重复原始片段。
回答尽量先给出一句直接结论，再补充必要解释。

当前问题：{question}

最近对话与任务上下文：
{context_block}

相关内容证据：
{notes_block}
```

---

### 4.5 答案校验修正 User Prompt

**文件**: [src/personal_agent/agent/runtime_ask.py](src/personal_agent/agent/runtime_ask.py#L535-L545)

```
你是个人知识库助手。你刚才的回答存在以下问题，请根据反馈重新生成更准确、更有据可查的回答。

用户问题：{question}

你刚才的回答：
{answer}

校验发现的问题：
{issues_text}

校验提示：
{warnings_text}

请重新生成回答。要求：
1. 直接给出结论，不要列标题
2. 如果证据不足，明确指出
3. 确保每个观点都有相应依据
```

**设计要点**: 用于 verify 步骤后的自动修正重试，接收校验发现的具体问题作为反馈。

---

### 4.6 群聊总结 User Prompt

**文件**: [src/personal_agent/agent/runtime_entry.py](src/personal_agent/agent/runtime_entry.py#L30-L35)

```
你是个人知识库助手。请用自然中文总结以下群聊对话的核心要点。
按主题分点列出讨论的关键事项、达成的结论和待办事项。
保持简洁，每个要点一句话。如果对话内容较少或主题分散，直接概括即可。

群聊消息：
{messages_text}
```

---

## 5. 编排节点

### 5.1 直接回答（direct_answer 分支）

**文件**: [src/personal_agent/agent/orchestration_nodes/_entry.py](src/personal_agent/agent/orchestration_nodes/_entry.py#L551-L613)

**用途**: 处理 direct_answer 意图（闲聊、问候等无需检索的问题），以及分类为 unknown/缺少信息时的澄清追问。

**调用参数**: `openai_small_model`, temperature=默认, max_tokens=300

#### 5.1.1 执行流程

节点 `_node_direct_answer_branch` 的分支逻辑：

1. **空输入** → 直接返回 `"你好，有什么可以帮你的？"`
2. **路由结果为 unknown 或缺失** → 调用 `_build_clarification_answer()` 生成澄清追问（不经过 LLM，由分类结果中的 `missing_information` 拼装）
3. **LLM 可用** → 调用 LLM 生成直接回答
4. **LLM 不可用**（缺少 `openai_api_key`/`openai_base_url`/`openai_small_model` 任一配置） → 返回 `"回答模型当前不可用，请检查 LLM 配置或稍后重试。"`

#### 5.1.2 System Prompt

基础 prompt：

```
你是一个友好、简洁的个人知识库助手。直接回答用户，不需要检索知识库。保持简短。
```

历史对话不再拼进 system prompt，避免和 chat messages 重复注入。

#### 5.1.3 用户消息构造

用户消息通过 `_dialogue_prompt_messages(state.messages)` 从 checkpoint 对话历史构建（角色映射：`ai` → `assistant`，`human` → `user`）。若历史为空则回退为：

```json
[{"role": "user", "content": "<entry_input.text>"}]
```

#### 5.1.4 澄清追问（非 LLM）

当路由无法确定意图时，`_build_clarification_answer` 不调用 LLM，直接从 `router_decision.missing_information` 组装中文提示：

- 路由模型本身不可用时返回预设错误文本
- 否则将缺失信息拼装为 `"我还需要你补充：{details}。你可以说明这是要记录、查询、总结，还是要执行某个操作。"`

---

### 5.2 删除候选选择 User Prompt

**文件**: [src/personal_agent/agent/orchestration_nodes/_steps.py](src/personal_agent/agent/orchestration_nodes/_steps.py#L664-L671)

```
你负责从已有知识笔记候选中定位用户明确要求删除的目标。
只在目标与候选明显对应时选择一条；不确定或有多个可能目标时返回 null。
不要执行删除，也不要生成不存在的 ID。
输出 JSON：{"thought":"简短判断","done":true,"result":{"note_id":"候选ID或null"}}。

用户删除请求：{delete_request}
候选笔记：{candidates_json}
```

**用途**: 在 delete_knowledge 流程中，从检索候选列表中用 LLM 精确匹配用户要删除的目标笔记。

**设计要点**: 不确定时返回 null，不执行删除，不生成不存在的 ID。

---

### 5.3 会话固化 User Prompt

**文件**: [src/personal_agent/agent/orchestration_nodes/_steps.py](src/personal_agent/agent/orchestration_nodes/_steps.py#L700-L710)

```
你负责决定哪些会话事实属于用户本次指定的固化范围，并将它们整理为一条可独立入库的中文知识笔记。
候选会话可能同时包含多个无关主题，必须根据当前保存请求进行语义选择；
不要仅因为某段出现在上下文中就写入笔记，也不要写入操作指令本身。
当当前保存请求使用"该知识""这个内容""上述回答"等指代且未另行指定主题时，
只提炼保存请求之前最近一轮助手回答所表达的知识，不要选择更早的其他主题。
如果候选会话中没有足以支撑本次请求的知识，请将正文留空。

请输出 JSON：
{"thought":"范围判断理由","done":true,"result":{"selected_turn_ids":["turn-N"],"title":"知识标题","content":"仅包含被选择知识的正文"}}。

当前保存请求：{entry_text}

候选会话：
{dialogue}
```

**用途**: solidify_conversation 流程中的 compose 步骤，从多轮对话中提取应固化的知识。

**设计要点**:
- 指代消解规则："该知识""这个内容""上述回答"等指代 -> 只选最近一轮助手回答
- 候选会话可能含多主题，必须语义选择
- 无匹配知识时 content 留空

---

## 6. 图谱提取

### 6.1 知识图谱自定义提取指令

**文件**: [src/personal_agent/graphiti/ontology.py](src/personal_agent/graphiti/ontology.py#L46-L58)

```
Extract entities and relationships for a personal knowledge graph.

Prioritize:
- people, organizations, projects, systems, and technical concepts
- decisions, dependencies, causes, tradeoffs, and applications
- facts that connect a concept to a project, problem, strategy, or outcome

When possible:
- normalize the same concept under one stable name
- preserve directional relationships such as "depends on", "causes", "applies to", "belongs to"
- avoid vague entities like "this", "that", or generic pronouns
```

**用途**: 作为 `custom_extraction_instructions` 传给 Graphiti 的 `add_episode()` 方法，指导 Graphiti 内部的 LLM 进行实体和关系抽取。

**设计要点**:
- 优先抽取人、组织、项目、系统、技术概念
- 关注决策、依赖、因果、权衡等关系
- 要求实体名称规范化，避免歧义代词

---

### 6.2 JSON 输出强制指令

**文件**: [src/personal_agent/graphiti/llm_strategies.py](src/personal_agent/graphiti/llm_strategies.py#L200)

```
Respond with JSON.
```

**用途**: 在 Graphiti 内部 LLM 调用中，当需要确保 JSON 输出时作为额外的 system message 追加。

---

## 7. 用户交互提示

### 7.1 澄清选项提示词

**文件**: [src/personal_agent/agent/orchestration_nodes/_helpers.py](src/personal_agent/agent/orchestration_nodes/_helpers.py#L119-L144)

当 LLM 无法确定用户意图时，通过中断机制向用户展示的澄清选项：

| ID | 标签 | 提示词 |
|----|------|--------|
| `capture` | 记录内容 | 请补充要写入知识库的具体内容。 |
| `ask` | 提出问题 | 请补充你想查询或追问的问题。 |
| `summarize` | 总结内容 | 请补充要总结的文本、会话或范围。 |
| `action` | 执行操作 | 请补充要执行的操作和对象，例如要删除哪条笔记。 |

> 注：这些提示词不直接发给 LLM，而是通过 LangGraph 中断机制展示给用户。

---

## 8. Prompt 治理与优化建议

当前高频 LLM prompt 已收敛到 `src/personal_agent/core/prompts.py`：answer generation、direct answer、router、replanner、ReAct、delete candidate resolve、solidify draft、query planner、evidence reranker、thread summarizer、Graphiti 自定义抽取指令、ask answer/correction 模板和通用 structured system prompt 都有 `name / version / output_contract / template`。调用侧通过 registry 获取 prompt，并把版本写入 trace。

后续治理项：

- **继续沉淀公共约束 block**：`_DIALOGUE_CONTEXT_POLICY` 已进入 registry 并被 ask 模板复用；后续继续把 citation、安全、语言风格等跨 prompt 约束沉淀成可组合 block。
- **做真实版本治理**：现在 registry 和 trace 层已能记录 `prompt_name / prompt_version`，但还缺版本演进、灰度和回滚策略。
- **补 prompt 快照和 eval 回归**：对 answer grounding、router intent、replanner schema、solidify draft 等关键 prompt 做 snapshot / golden case；prompt 改动必须跑对应 eval，防止措辞微调引发行为漂移。
- **收敛 prompt 入口约束**：新增 LLM 调用时要求声明 `prompt_name / prompt_version / output_contract`，低风险一次性 prompt 也不能成为不可观测的裸字符串。

更合适的工程口径是：prompt 不只是几段文案，而是可版本化、可观测、可评测的工程资产。当前已经完成结构化输出和工具调用约束分流，并把高频 prompt 与核心 grounding block 收敛进 registry；剩余重点是版本治理和回归评测。

---

## 附录：LLM 调用汇总

| # | 文件 | 函数 | 模型 | Temp | Max Tokens | 用途 |
|---|------|------|------|------|------------|------|
| 1 | `_helpers.py` | `_react_llm_respond()` | `openai_small_model` | 0 | 400 | Graph ReAct 工具调用 / finish_react |
| 2 | `step_projector.py` | deterministic projection | - | - | - | 任务规划（当前不调用 LLM） |
| 3 | `restep_projector.py:101` | `_replan_with_llm()` | `openai_small_model` | 0 | 500 | 任务重规划 |
| 4 | `router.py` | `_classify_with_llm()` | `openai_small_model` | 0 | 500 | 意图分类 |
| 5 | `runtime_llm.py:26` | `_generate_answer()` | `openai_model` | 0.3 | 600 | 答案生成 |
| 6 | `runtime_llm.py:62` | `_generate_answer_stream()` | `openai_model` | 0.3 | 600 | 流式答案生成 |
| 7 | `_entry.py:593` | `_node_direct_answer_branch()` | `openai_small_model` | 默认 | 300 | 直接回答 |
| 8 | `query_step_projector.py` | `_call_planner_llm()` | LangExtract model (`qwen3-coder-flash`) | 0 | 500 | Ask 查询理解、rewrite、filters、检索计划 |
| 9 | `rerankers.py` | `LlmEvidenceReranker._rank_ids()` | LangExtract model (`qwen3-coder-flash`) 或 `openai_small_model` | 0 | 700 | Ask evidence listwise rerank |
| 10 | `llm_strategies.py:240` | `_generate_response()` | graphiti model | 0.6 | 可配置 | 图谱实体/关系抽取 |
| 11 | `store.py:247` | `add_episode()` | graphiti model | 默认 | 默认 | Episode 提取 |
| 12 | `store.py:270` | `add_episode()` (retry) | graphiti model | 默认 | 默认 | Episode 提取重试 |

**模型说明**:
- `openai_small_model` — 用于内部决策与受控工具选择；router/replanner 使用 strict `json_schema`，ReAct 使用 tool schema
- `openai_model` — 用于答案生成，temperature=0.3，更高 max_tokens，自然语言输出
- LangExtract model — 默认 `qwen3-coder-flash`，Ask query planner 和可选 LLM rerank 优先使用它的 strict `json_schema` 输出，未配置 extract key 时回退到 `openai_small_model`
- graphiti model — Graphiti 库内部使用的模型，用于知识图谱实体和关系抽取

**提示词设计模式总结**:
1. 内部结构化决策使用 strict `json_schema`，工具选择使用 function/tool calling 的 tool schema，避免用普通 JSON 模拟工具调用
2. 所有自然语言输出的 System Prompt 以"你是一个...个人知识库助手"开头，强调归纳整理而非简单复述
3. 关键业务约束（如 delete 必须先 resolve、solidify 必须先 compose）直接写入 User Prompt 模板
4. 不支持的功能通过"无法重新规划返回空数组""不确定时返回 null"等方式优雅降级
