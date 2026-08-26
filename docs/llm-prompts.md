# LLM Prompt 与决策边界

**Prompt Registry 只拥有可复用的版本化提示模板，不拥有业务事实、权限、执行结果或完成结论。** 文本事实源位于 `kernel/prompt_templates/`；调用方通过 `kernel.prompts.get_prompt()` 读取 `PromptSpec(name, version, output_contract, template)`。

## 当前 Registry

| Prompt | 生产消费者 | 输出边界 |
| --- | --- | --- |
| `answer_generation.system` | Conversation runtime LLM | 约束模型回答风格；最终回答仍由 Agent loop 与 Completion Gate 接受 |
| `evidence_rerank.system/user` | Evidence reranker | 只排序已有 evidence id，不创造证据或写入知识 |
| `react.system` | 受限 ReAct 执行 | 只能在本轮 allowlist 与预算内提出 ToolCall |
| `structured.system` | 通用 structured model adapter | 要求符合调用方给出的 schema，不定义业务 schema |
| `delete_candidate_resolve.user` | 删除候选解析 | 只能选择已有候选 id，不能执行删除 |
| `solidify_draft.user` | Conversation solidify | 只形成待准入草稿，不能直接写长期知识 |
| `graphiti.custom_extraction` | Graphiti adapter | 约束外部图谱抽取，不替代 Personal Knowledge admission |

动态 Agent loop、grounding judge 与领域 extraction 的提示在各自 owner 内组装，因为其 typed schema 和 validator 属于该决策点；它们仍通过 `StructuredModelRequest` 记录 schema、模型和调用结果。

## 变更门禁

- 修改 Prompt 必须同步检查其 schema、validator 与唯一生产消费者；零消费者 Prompt 直接移除。
- 模型输出必须经过 typed parse 与所属 Application/Domain 的 deterministic admission。
- Prompt 测试只证明模板契约；产品效果必须由自然输入的 E2E 或语义 Eval 证明。
- 版本变化应运行 `tests/test_prompt_registry.py`、直接消费者测试和受影响的 E2E。
