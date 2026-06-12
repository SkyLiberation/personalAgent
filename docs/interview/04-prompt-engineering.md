# Prompt 工程

### 1. 项目里的 prompt 是怎么组织的？集中管理还是散落？

集中管理。项目把高频 LLM prompt 收敛到一个 registry：`core/prompts.py` 里用 `PromptSpec`（`@dataclass(frozen=True)`，字段 `name / version / template / output_contract / owner`）注册了 23 个 prompt，存进 `_PROMPTS` 字典，key 用点分命名空间寻址，比如 `ask.unified_answer.user`、`router.classify.system`、`thread_context_compression.user`。对外只暴露两个函数：`get_prompt(name)`（返回 spec，未知 name 直接抛 `KeyError`）和 `render_prompt(name, **vars)`（= `spec.template.format(**vars)`）。

所有调用方都改成从 registry 取，不再各自硬编码：router、query_planner、runtime_ask、runtime_llm、thread_summarizer、rerankers、replanner、orchestration_nodes（`_react / _steps / _entry / _helpers`）、graphiti ontology 全部 `from core.prompts import get_prompt/render_prompt`。

这是一次有意识的重构（早期 prompt 确实散落在各模块的 f-string 里）。收敛后的价值：prompt 与代码解耦、单点维护、可按名字寻址、能挂元数据。最能体现这点的是共享 grounding 约束——`answer.dialogue_context_policy` 这段"对话线索不是事实证据"的指令现在是 registry 里的一个 `prompt_block`，通过 `{dialogue_context_policy}` 占位符注入 web/unified/graph/local 四个 answer 模板，改一处四处生效，不再需要在四个文件里同步同一句话。

### 2. PromptSpec 上的 version 和 output_contract 各解决什么问题？

`version` 解决可观测性。每个 prompt 带独立版本，且已经开始分化——`answer_generation.system`、`router.classify.system`、`react.system`、`replanner.*`、`delete_candidate_resolve.user`、`solidify_draft.user` 等已经迭代到 v2，其余 v1。调用方把 `spec.version` 写进 `llm_trace` 的 span / event metadata（`prompt_name + prompt_version`），所以线上能定位到"这次回答用的是哪个 prompt 的哪个版本"，而不是以前那种所有调用都吃默认 `"v1"`。

`output_contract` 解决输出约束的显式标注。它把每个 prompt 期望的输出形态写在 registry 上：`free_text`（面向用户的自由回答）、`json_schema`（strict 结构化）、`tool_call`（function calling）、`prompt_block`（可复用片段），以及一批领域契约名（`RouterDecision / QueryUnderstanding / EvidenceRerank / ThreadSummary / DeleteCandidate / SolidifyDraft` 等）。这让"这个 prompt 该配什么 response_format、解析成什么 Pydantic 模型"在声明层就一目了然，和实际调用路径一致。

诚实的边界：version 现在是"能记录、已分化"，但还**没有**版本演进策略、灰度或回滚机制；JSON schema 本身也没进 registry，仍在 query_planner / rerankers 各自本地构造，registry 只管文案与契约名。

### 3. 结构化输出怎么约束？为什么不是所有 LLM 调用都用 json_schema？

按链路分级，并由 `output_contract` 显式标注，不是一刀切：

- **strict json_schema**（最强）：用在内部决策链路。query planner、replanner、router、evidence rerank 都走 `strict_json_schema_response`（`additionalProperties:false` + 全字段 required），再解析成对应 Pydantic 模型（`RouterDecision / QueryUnderstanding` 等）双保险。这些输出要被代码消费，格式错一点下游就崩。
- **tool_call**：ReAct（`react.system`）走真正的 function/tool calling（`tool_choice="auto"`），不是用 JSON 字符串模拟工具调用。
- **json_object / 降级**：Graphiti 抽取按模型能力在 json_schema 和 `{"type":"json_object"}` 之间降级，兜底 qwen3-coder-flash 这类会忽略 schema 的模型。
- **free_text**（无 response_format）：四个面向用户的 answer prompt 全是自由文本输出。

关键取舍是：**内部决策要确定性、面向用户的生成要表达自由**。如果给 answer 也套 schema，回答会变机械，所以生成环节放开格式，citation 编号用"软要求"+ 下游 verifier 校验来兜，而不是硬 schema。

### 4. evidence 是怎么注入 prompt 的？怎么防止模型引用没给它的证据？

统一证据池注入时，每条 `EvidenceItem` 按 `[E1] [E2] …` 编号，source_type 映射成中文标签（图谱事实 / 笔记 / 原文片段 / 网络搜索 / 工具结果 / 历史执行记录），带上 title、URL、source_span、score、rank_reason，内容截断到约 700 字。`ask.unified_answer.user` 模板里的 grounding 指令明确："只基于下面统一证据池回答""标注证据编号如 [E1]""证据不足或冲突要明确说明，不要补空白"。

最值得讲的细节是 **hint gating**（`runtime_ask.py`）：注入 prompt 的 citation_hint / match_hint 只包含 `ContextPack.selected` 里幸存下来的 source_id（`selected_ids`），不在其中的一律回退成"无"。也就是说**只有过了 rerank + 字符预算筛选的证据**才能进 prompt 提示，被裁掉的低分证据无法"偷渡"进模型视野，保证"模型看见的"和"用户最终看到的引用"一致。代码注释直接写了 "cannot smuggle un-reranked, un-budgeted evidence"，并有 `tests/test_unified_prompt_gating.py` 守着——验证空 selection 时 hint 全部回退到"无"。

### 5. prompt 里有哪些防幻觉 / 安全边界指令？

安全约束是 **prompt 里说 + 控制流里拦** 双保险，且约束文案现在都沉淀在 registry 模板里：

- **对话/摘要不是事实**：`answer.dialogue_context_policy` 明确"对话线索只用于理解指代，不是事实证据，不得把历史助手回复当回答依据，与当前证据冲突以当前证据为准"。
- **摘要分桶**：`thread_context_compression.user` 要求助手推测只能进 `assistant_assumptions`、无证据判断进 `unverified_claims`、`evidence_refs` 只能放明确出现的 note_id/citation/tool ref。
- **不能编造 note_id / resolve 只能选候选**：`delete_candidate_resolve.user` 写"note_id 只能是候选 ID 或 null，不确定返回 null，不要生成不存在的 ID"，执行侧 `_steps.py` 还二次校验 `note_id in candidate_by_id`，不在候选内直接返回空。
- **solidify 不写操作指令 / 范围外内容**：`solidify_draft.user` 约束指代消解和"无支撑则正文留空"。
- **删除要确认**：不靠 prompt 自觉，router 强制 `delete_knowledge` 默认 `requires_confirmation=true, risk_level=high`，ReAct 节点还显式拦写操作工具。

口径是：prompt 指令是"软约束"，真正不可绕过的是控制流里的 PlanValidator / PolicyEngine / HITL。prompt 负责"通常照做"，代码负责"绝不越界"。

### 6. 回答语言和口吻是怎么控制的？

口吻在 system prompt 里定义：`answer_generation.system` 要求"严谨、善于归纳，首要任务不是复述检索片段"；direct_answer 分支要求"友好、简洁、保持简短"。回答语言目前**硬编码中文**（answer 模板直接写"用自然中文回答"），内部 prompt（planner / rerank）用英文，因为它们是给检索规划器/重排器的指令，不是面向用户的回答。

诚实的不足：语言写死在文案里，没有 language 参数化或 locale 注入，多语言适配是待补项——这也是 prompt 进了 registry 后比较容易补的一项（给模板加 language 变量即可）。

### 7. prompt 有没有版本管理和测试？

重构后有了基础，但还不完整：

- **registry 测试**：`tests/test_prompt_registry.py` 守三件事——23 个 prompt 都注册了、每个都有 `version`（以 v 开头）和非空 `template`、全部能用样例变量 `render` 出来（含 JSON 字面量转义正确）。这保证了"没有 prompt 漏注册、没有模板占位符写错导致 format 崩"。
- **行为测试**：`test_unified_prompt_gating.py` 守 hint gating；router / planner / replanner / verifier 等测分类、解析、降级行为。

仍要正视的短板：**没有 prompt snapshot / golden-case eval 回归**，措辞微调可能引发行为漂移仍无自动防护；version 能记录能分化，但没有灰度 / A-B / 回滚；还有遗留硬编码（graphiti 调用处仍写死 `prompt_version="v1"` 而非取 spec.version）。继续生产化要补的是：把 prompt 变更纳入 evals 回归、给关键 grounding 约束加快照测试、补真正的版本治理。

---

[← 返回索引 INDEX.md](INDEX.md)
