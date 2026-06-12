# solidify_conversation Workflow

`solidify_conversation` 用于把当前 thread 中已经讨论出的结论沉淀为长期知识。它不是把用户的“保存一下”指令本身入库，而是先从 checkpoint 对话中选择本次请求指向的知识范围，再复用 capture 链路写入 `knowledge_notes`。

对应代码：

- [workflow.py](../../src/personal_agent/agent/workflow.py)：`SolidifyConversation WorkflowSpec`
- [orchestration_nodes/_steps.py](../../src/personal_agent/agent/orchestration_nodes/_steps.py)：草稿生成和工具输入注入
- [orchestration_nodes/_helpers.py](../../src/personal_agent/agent/orchestration_nodes/_helpers.py)：候选对话 turn 渲染与草稿解析
- [capture_text.py](../../src/personal_agent/tools/capture_text.py)：复用 capture 工具写入长期记忆
- [ingestion_pipeline.py](../../src/personal_agent/agent/ingestion_pipeline.py)：Unstructured partition/chunk、local store、graph sync

## 固定拓扑

```text
solidify_conversation
  sol-1 compose
    -> sol-2 tool_call(capture_text)
```

这个 workflow 会投影成前端可展示的 `ExecutionStep`，但拓扑固定，不由 LLM 规划。LLM 的职责只在 `sol-1`：判断哪些历史 turn 属于本次固化范围，并生成可独立入库的知识草稿。

## Step 契约

| Step | 类型 | 作用 | 关键契约 |
| --- | --- | --- | --- |
| `sol-1` | `compose` | 从 checkpoint 对话中选择相关事实并整理为知识草稿 | `llm_decision_node=solidify_draft`；没有有效草稿则 abort |
| `sol-2` | `tool_call` | 调用 `capture_text` 写入长期知识 | `side_effects=write_longterm`，低风险，不需要确认 |

## 执行细节

1. Router 将“把刚才结论记下来 / 沉淀一下”归类为 `solidify_conversation`，并标记为需要 step projection。
2. `WorkflowStepProjector` 从 `WORKFLOW_REGISTRY` 确定性投影 `sol-1 -> sol-2`。
3. `StepProjectionValidator` 校验 workflow 必须包含 `tool_call(capture_text)`，且 `sol-2` 依赖 `sol-1`。
4. `sol-1` 使用 checkpoint 中的历史 `messages` 构造候选 turn，上下文不直接当长期事实，而是供模型选择本次要固化的范围。
5. `solidify_draft` prompt 要求输出 JSON：`selected_turn_ids/title/content`，并禁止把操作指令本身写入知识。
6. `_solidify_note_text()` 把 JSON 草稿转换成可入库正文；如果正文为空，workflow 失败并不写库。
7. `draft_ready` 事件携带草稿，前端可展示给用户理解“将保存什么”。
8. `sol-2` 的 `capture_text` 输入由 `sol-1` 的草稿动态注入，而不是使用原始“保存一下”指令。
9. `capture_text` 复用 capture 主链路：结构化解析、Unstructured chunk、Postgres note/chunk、review card、graph sync。
10. `finalize_step_execution` 汇总写入结果，并返回 plan steps / execution trace。

## 范围选择规则

`solidify_conversation` 的核心难点是“保存哪部分对话”。当前 prompt 明确：

- 候选会话可能包含多个无关主题，必须根据当前保存请求做语义选择。
- 不能仅因为某段出现在上下文中就写入笔记。
- 不能写入“保存一下”这类操作指令本身。
- 当用户说“该知识 / 这个内容 / 上述回答”且没有指定主题时，只提炼保存请求之前最近一轮助手回答表达的知识。
- 没有足够知识正文时正文留空，系统 abort，不写入长期知识。

## 与 capture_text 的关系

`solidify_conversation` 只负责从短期现场生成草稿；真正长期知识入库仍走 `capture_text`。因此它继承 capture 的能力：

- `RawIngestItem` 和 source metadata。
- Unstructured partition / chunk。
- parent/chunk note。
- duplicate fingerprint 和 related note 计算。
- graph sync 与 graph quality 指标。
- `EvidenceItem` / citation 后续可回溯。

## 失败分支

| 场景 | 处理 |
| --- | --- |
| checkpoint 中没有可固化对话 | `sol-1` 失败，不写库 |
| LLM 输出无法解析或正文为空 | `sol-1` abort，返回未生成有效草稿 |
| capture_text 写入失败 | `sol-2` abort，保留步骤失败事件 |
| 用户原话只是在发命令 | prompt 要求不把操作指令作为知识正文 |

## 面试讲法

可以说：固化对话不是把聊天记录直接存进长期记忆，而是一个两步 workflow。第一步从 checkpoint 里选择本次请求真正指向的知识并生成草稿，第二步复用 capture 链路写入长期知识。这样既避免把临时对话和助手推测当事实，也让最终入库内容仍走统一 chunk/index/graph/evidence 管线。
