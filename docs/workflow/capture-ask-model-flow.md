# Capture / Ask 当前流程

本文只描述当前工程里 `capture` 和 `ask` 两条主链路的真实实现。更宽泛的 workflow 框架见 [当前 Workflow 框架总览](workflow-framework.md)。

## 当前结论

`capture_*` 和 `ask` 都属于 step projection workflow：

| Intent | 当前执行方式 | 是否投影为 `ExecutionStep` | 核心路径 |
| --- | --- | --- | --- |
| `capture_text` | step projection workflow | 是 | `cap-structure -> capture_text tool -> IngestionPipeline` |
| `capture_link` | step projection workflow | 是 | `cap-link-fetch -> cap-link-store` |
| `capture_file` | step projection workflow | 是 | `cap-file-inspect -> cap-file-store` |
| `ask` | step projection workflow | 是 | `ask-retrieve -> ask-compose -> ask-verify` |

也就是说，`capture` 与 `ask` 都进入 `StepExecutionGraph`，复用步骤状态、checkpoint、事件、失败处理、ToolGateway 和前端 steps 展示能力。

## Capture Step Workflow

capture 由固定 `WorkflowSpec` 投影为步骤。step executor 只负责编排不同来源的正文提取或 artifact 理解，并把可入库文本交给统一的 capture pipeline。

```text
step_execution_graph
  -> capture_text / capture_link / capture_file steps
  -> ToolGateway
  -> capture_text tool
  -> answer = "已收进知识库：{title}"
  -> finalize_entry_result
```

### capture_text

```text
entry_input.text
  -> cap-structure tool_call(capture_text)
  -> AgentRuntime.execute_capture(...)
```

适用于用户直接发送文本、片段、想法、资料内容等。

### capture_link

```text
entry_input.text / metadata.url
  -> prepare_entry_tool_input / _first_url(...)
  -> cap-link-fetch tool_call(capture_url)
       CaptureService.capture_text_from_url(url)
       FirecrawlUrlCaptureProvider
       or BuiltinUrlCaptureProvider
  -> handle_step_success 注入 text
  -> cap-link-store tool_call(capture_text)
  -> AgentRuntime.execute_capture(...)
```

`CaptureService` 只负责把 URL 变成正文；长期存储、chunk、review、graph sync 仍由 `IngestionPipeline` 负责。

### capture_file

```text
entry_input.artifacts[0] / metadata.file_path
  -> cap-file-inspect tool_call(inspect_artifact)
       ArtifactService.inspect_upload(...)
  -> handle_step_success 注入 text/source_type
  -> cap-file-store tool_call(capture_text)
  -> AgentRuntime.execute_capture(...)
```

当前文件入口会先把上传 artifact 理解成可回答/可入库的文本化上下文，再进入统一 capture pipeline。`capture_upload` 工具仍存在并可提取上传文件正文，但当前 `capture_file` 的 `WorkflowSpec` 主路径已经切到 `inspect_artifact -> capture_text`。

## IngestionPipeline

`AgentRuntime.execute_capture()` 是很薄的一层，实际委托给 `IngestionPipeline.ingest()`：

```text
execute_capture(...)
  -> IngestionPipeline.ingest(...)
```

capture pipeline 当前顺序：

```text
source fingerprint dedupe
  -> capture_node
  -> structural_chunk_node
  -> chunk_reconcile_node
  -> enrich_node
  -> link_node
  -> schedule_review_node
  -> _ingest_to_graph
```

### 1. Source Fingerprint Dedupe

入库前先计算 source fingerprint：

```text
text + source_type + source_ref
  -> sha256
  -> memory.find_note_by_source_fingerprint(user_id, fingerprint)
```

如果同一用户下已经采集过相同来源，直接返回已有 parent note 和 chunks，不重复写入。

### 2. capture_node

`capture_node` 把 `RawIngestItem` 转成 parent `KnowledgeNote`：

```text
RawIngestItem
  -> KnowledgeNote(parent)
       source.type
       source.ref
       source.fingerprint
       source.metadata
       body.title
       body.content
       body.summary
       tags
```

parent note 是整篇内容的展示、来源回溯和文档级聚合锚点。

### 3. structural_chunk_node

`structural_chunk_node` 使用 `partition_to_chunk_drafts()` 做结构化 chunk：

```text
KnowledgeNote(parent).body.content
  -> partition_to_chunk_drafts(...)
  -> ChunkDraft[]
```

当前 chunk 来源是 Unstructured-backed partition/chunk，而不是简单固定长度切分。chunk draft 可以携带：

- `title_path`
- `page_number`
- `element_ids`
- `source_span`
- `category`
- 原始 element metadata

如果只有一个 draft，则不额外生成 child chunks，只把 unstructured metadata 写回 parent。

### 4. chunk_reconcile_node

`chunk_reconcile_node` 把 `ChunkDraft` materialize 成 child `KnowledgeNote`：

```text
ChunkDraft[]
  -> KnowledgeNote(chunk 1)
  -> KnowledgeNote(chunk 2)
  -> ...
```

child chunk 是检索和证据单元；parent note 是展示和回溯单元。

### 5. enrich_node / link_node / schedule_review_node

```text
enrich_node:
  -> 更新 summary / tags

link_node:
  -> find_similar_notes(...)
  -> 写入 parent note
  -> 写入 chunk notes
  -> 写入 related_note_ids

schedule_review_node:
  -> 生成 ReviewCard
  -> 写入复习计划
```

### 6. Graph Sync

本地 note/chunk 写入后，`_ingest_to_graph()` 处理图谱同步状态：

```text
if 有 chunk_notes and graph configured:
  parent.graph_sync = skipped
  chunk.graph_sync = pending / skipped by budget
  queued chunks -> worker_queue_tasks(queue="graph", task_type="graph_sync_note")
else:
  graph_store.ingest_note(parent)
```

当前长文优先把 graph sync 委托给 chunk-level notes，避免整篇 parent 被重复做图谱抽取。pending chunk 会进入 durable worker queue；后台可通过 `drain_worker_queue(queue="graph")` 租约执行 `graph_sync_note`，底层仍复用 `sync_note_to_graph(note_id)`。

## Ask Step Projection Workflow

`ask` 和 capture 一样是 step projection workflow。

在 `workflow.py` 中，它的固定步骤是：

```text
ask-retrieve
  -> ask-compose
  -> ask-verify
```

入口执行路径：

```text
project_workflow_steps
  -> validate_projected_steps
  -> prepare_step_execution
  -> select_next_step
  -> execute_step(ask-retrieve)
  -> handle_step_success
  -> select_next_step
  -> execute_step(ask-compose)
  -> handle_step_success
  -> select_next_step
  -> execute_step(ask-verify)
  -> handle_step_success
  -> finalize_step_execution
  -> finalize_entry_result
```

ask 复用的是 plan/step execution 的运行结构，包括：

- `ExecutionStep`
- `StepRunState`
- `StepExecutionState`
- step status
- step dependencies
- `step_execution.results`
- checkpoint
- events
- frontend steps
- failure handling

但 ask 的步骤拓扑不是 LLM planner 生成的，而是 `WorkflowSpec` 固定声明后由 `WorkflowStepProjector` 确定性投影。

## AskRunContext

ask 三个步骤之间共享一个 `AskRunContext`。

```text
AskRunContext
  question
  user_id / session_id
  working_context
  structured_context
  has_dialogue_context
  QueryUnderstanding
  RetrievalPlan
  effective_query
  evidence_pool
  combined_matches
  combined_citations
  web_tried / contrastive_tried
  ContextPack
  selected_matches
  selected_citations
  answer
  verification
  trace_steps
```

大对象不直接写入 LangGraph checkpoint。`ask-retrieve` 会把 context 序列化为 durable artifact：

```text
PostgresAskRunContextStore.put(run_id, ctx)
  -> workflow_artifacts(kind="ask_run_context")
```

后续 `ask-compose / ask-verify` 通过 `run_id` 取回：

```text
PostgresAskRunContextStore.get(run_id)
```

这样 checkpoint 中只保留步骤状态和摘要结果，避免把 evidence pool、ContextPack、完整候选集塞进 LangGraph state；进程重启后 compose / verify 仍可从 artifact 恢复。

## ask-retrieve

`ask-retrieve` 是最重的一步，负责查询理解、多源召回和上下文组装。

对应执行函数：`_execute_retrieve_step()`。

```text
ask-retrieve
  -> _entry_conversation_messages(...)
  -> ask_service.build_run_context(...)
  -> ask_service.run_retrieval_stage(ctx)
  -> ask_run_context_store.put(run_id, ctx)
  -> step result:
       evidence_count
       citation_count
       match_count
       ask_staged=True
```

`RetrievalStage` 内部流程：

```text
question + dialogue context
  -> plan_retrieval(...)
       QueryUnderstanding
       RetrievalPlan
  -> RetrievalCoordinator.run(ctx)
       graph / structural / local / web 按 plan 召回
  -> dedupe_evidence
  -> apply_rrf_fusion
  -> candidate_enricher.enrich(...)
  -> optional sentence-level compression
  -> reranker.rerank(...)
  -> ContextPack
  -> selected_matches / selected_citations
```

当前 QueryUnderstanding / RetrievalPlan 负责：

- query rewrite
- freshness 判断
- personal memory 判断
- graph reasoning 判断
- episodic context 判断
- sub queries
- metadata filters
- sources / parallel 策略

`RetrievalCoordinator` 的召回边界是：

- `graph`：可走 Graphiti、structural 或 hybrid graph provider。
- `local`：本地 note/chunk 检索。
- `web`：按 retrieval plan 主动补充外部证据。
- `sub_queries`：当前用于 graph 子查询扩展。
- `episodic / reflection`：在需要时补充会话事件和反思类上下文。

多路证据进入同一个 `evidence_pool` 后，会通过去重、RRF 融合、候选补全、可选句级压缩和 rerank 统一选择，而不是各来源分别生成答案。

## ask-compose

`ask-compose` 只负责基于 `ask-retrieve` 产出的 `ContextPack` 生成答案，不做第二次检索。

对应执行函数：`_execute_compose_step()`。

```text
ask-compose
  -> ctx = AskRunContextStore.get(run_id)
  -> ask_service.run_generation_stage(ctx)
  -> state.answer = ctx.answer
  -> state.citations = ctx.selected_citations
  -> state.matches = ctx.selected_matches
  -> step result:
       answer
       draft=True
```

`GenerationStage` 调用：

```text
_compose_unified_answer(
  question,
  context_pack,
  selected_matches,
  selected_citations,
  working_context,
)
```

生成阶段的输入边界是 `ContextPack`，不是原始 graph/local/web 结果。graph、local、structural、web 的候选在 retrieve 阶段已经被归一成 `EvidenceItem` 并排序。

## ask-verify

`ask-verify` 负责事实校验、必要时 retry、可选反证补充，以及必要时 web fallback。

对应执行函数：`_execute_verify_step()`。

```text
ask-verify
  -> ctx = AskRunContextStore.get(run_id)
  -> ask_service.run_verification_stage(ctx)
  -> state.answer = ctx.answer
  -> state.citations = ctx.selected_citations
  -> state.matches = ctx.selected_matches
```

`VerificationStage` 当前逻辑：

```text
AnswerVerifier.verify(...)
  -> if 有 selected evidence:
       _retry_if_needed(...)
  -> if contrastive_retrieval enabled and claim contradicted/not_found:
       add_contrastive_evidence(ctx)
       re-assemble ContextPack
       re-run generation
       re-run verification
  -> if evidence insufficient and web available and not web_tried:
       add_web_fallback(ctx)
       re-assemble ContextPack
       re-run generation
       re-run verification/retry
  -> if still insufficient:
       _annotate_answer(...)
```

反证补充和 web fallback 都不是独立复制出来的 ask 流程。它们会把新增 evidence 追加到同一个 `AskRunContext`，再复用 context assembly、generation 和 verification。

## AskResult 输出

`AskService.context_to_result(ctx)` 会把最终 context 转成 `AskResult`：

```text
AskResult
  answer
  citations
  matches
  match_refs
  evidence
  session_id
```

在 entry workflow 中，最终 answer、citations、matches 会回填到 `AgentGraphState`，再由 `finalize_entry_result` 写入 assistant message 和事件。

## Capture 与 Ask 的衔接

capture 产出的长期知识是 ask 的检索基础：

```text
capture
  -> parent KnowledgeNote
  -> child chunk KnowledgeNote[]
  -> source metadata / fingerprint
  -> local lexical/vector indexes
  -> optional Graphiti episode / graph facts
  -> review card

ask
  -> graph / structural / local / web retrieval
  -> EvidenceItem
  -> ContextPack
  -> grounded answer
  -> verifier
```

两条链路之间的关键共享模型：

- `KnowledgeNote`：长期知识和 chunk 的持久化实体。
- `Citation`：回答引用。
- `EvidenceItem`：ask 生成前的统一证据候选。
- `ContextPack`：最终进入 prompt 的证据包。
- `MatchRef`：对外展示和 verifier 使用的匹配引用。

## 当前边界

### Capture 边界

当前 capture 已有：

- 来源 fingerprint 去重。
- text/link/file 三入口最终统一进入 `IngestionPipeline`。
- parent note + child chunk note。
- Unstructured-backed chunk drafts。
- chunk quality score / retrievable 标记。
- review card。
- chunk-level graph sync 状态和 durable worker queue 入队。

当前仍有限制：

- 上传文件当前先经 `inspect_artifact` 变成文本化上下文，再进入 capture pipeline；PDF/Word/HTML 的原生页码、坐标、表格结构还没有完整贯穿到最终问答证据层。
- graph sync 是 capture 后置环节，长文按 chunk budget 标记 pending/skipped 并入队；当前已有同步 drain 入口，但还没有独立 worker daemon。
- chunk 质量分已进入 chunk note，但版本化更新、复杂版面保真和来源 metadata 自动抽取还不是主链路能力。

### Ask 边界

当前 ask 已有：

- workflow-step 化的 `retrieve / compose / verify`。
- `AskRunContext` 承载三阶段中间状态。
- query understanding + retrieval plan。
- graph / structural / local / web 多源召回。
- EvidenceItem 归一。
- RRF fusion。
- candidate enrichment。
- heuristic / LLM rerank 可插拔。
- 可选句级 evidence compression。
- ContextPack 预算控制。
- verifier + retry + optional contrastive retrieval + web fallback。

当前仍有限制：

- ask context artifact 已落在通用 `workflow_artifacts` 表，但当前只把 ask 三阶段大对象作为 `kind="ask_run_context"` 使用；还没有把所有 workflow step I/O 全量纳入同一 artifact 规范。
- rerank、MMR、多样性、压缩和反证检索仍有提升空间。
- claim grounding 主要是启发式检查，复杂蕴含判断仍需要更强 verifier。

## 面试表述

可以这样说：

> 当前 capture 和 ask 都是 step projection workflow。capture 由固定 `WorkflowSpec` 投影：文本是 `capture_text` 单步写入，链接是 `capture_url -> capture_text`，文件是 `inspect_artifact -> capture_text`，底层最终统一进入 `IngestionPipeline` 做 fingerprint 去重、parent note、Unstructured chunk、child notes、review 和 worker queue graph sync。ask 由固定 `WorkflowSpec` 投影出 `ask-retrieve -> ask-compose -> ask-verify`，复用 LangGraph 的 step execution、checkpoint、事件和前端 steps。retrieve 阶段负责 query understanding、多源召回、证据归一、RRF/补全/压缩/rerank 和 ContextPack artifact；compose 阶段只基于 ContextPack 生成答案；verify 阶段做校验、retry、可选反证补充和必要时 web fallback。
