# ADR 0012: Graph Retrieval 只返回可追溯证据

> **状态：部分 Superseded（2026-08-12）。** “Graph/provider 结果必须带可追溯 evidence binding”仍有效；其中以 `AskService.execute_ask()` 为产品入口的描述已失效。当前最终回答 owner 是 Conversation，历史 eval-only Ask chain 已删除。

- 状态：Accepted
- 日期：2026-07-31
- 影响范围：Ask GraphRetriever、Graphiti、graph_search Tool、Graph Provider 配置

## Goal / Current Incorrect Behavior / Expected User-visible Result

用户询问个人知识中的业务状态时，Ask 只能依据可追溯的 graph fact、edge、episode、note 或 citation
回答。Graph provider 只返回 synthesized answer、没有来源锚点时，系统必须返回证据不足，不能把该
answer 升级为事实。

改造前 `GraphAskResult` 同时包含 retrieval facts 和 `answer`。`graph_result_to_evidence()` 会把
`answer` 转成 `EvidenceItem(source_id="graph_answer")`；Ask 随后把它当作 graph fact 再生成和验证
最终答案。Microsoft GraphRAG Adapter 还会把 CLI 生成答案逐行拆成 `relation_facts`，形成第二条
同类写入口。

首轮改造后又发现两个同源问题：`graph_search` Tool 复制了 evidence converter，却遗漏只有
`relation_facts` 的合法结果；`AskConfig.graph_provider` 接受任意字符串，Runtime 遇到未知值会
静默改绑 Graphiti。

## Business Expansion or Proven Constraint / Out of Scope

已证明约束：provider candidate answer 不是 Execution Fact 或 Evidence，不能在没有 source binding
时进入 EvidenceEngine。

Out of Scope：实现 Microsoft GraphRAG source/citation parser、替换 GraphRAG Provider、增加通用
Evidence Admission Agent、修改 Graphiti 的事实检索算法。Microsoft GraphRAG 没有目标 E2E 和
source binding，因此本次删除生产 Adapter/配置，而不是保留不可用能力壳。

## Simplest Baseline E2E / Executed Result / Root Cause

Persona：查询个人知识中 Orion 发布状态的用户。

Given：允许替代的外部 Graph provider 只返回
“Orion 已经完成生产发布，所有租户默认启用”，不返回 citation、edge、episode、note 或 fact ref。

When：从 `AskService.execute_ask()` 输入自然问题“Orion 的发布状态是什么？”。

Then：改造前最终答案包含该无来源结论，citations 为空，但 `evidence_refs` 包含
`source_id=graph_answer`。命令：

```text
.\.venv\Scripts\python.exe -m pytest -q tests/test_graph_ask_boundary.py
```

baseline 实际结果：`1 passed in 1.01s`。根因是 provider answer 被 normalization 层重新分类为
graph fact，绕过了 evidence 来源约束。

补充 baseline：

- 从 `ToolExecutor.invoke_direct("graph_search")` 输入“Orion 的发布状态是什么？”，Provider 返回
  非空 `relation_facts`；改造前 Tool `data` 有事实但 `evidence_count=0`；
- `AskConfig(graph_provider="typo-provider")` 后执行同一自然问题，Runtime 实际调用 Graphiti
  `1` 次并返回其结论；环境配置被静默改写。

## Target E2E and Counterfactuals

相同入口和输入必须：

- 不返回 provider 的无来源结论；
- 明确表示找不到足够依据；
- citations 为空；
- 不产生 `graph_answer` evidence；
- 有 fact/edge/episode/note refs 的 Graphiti 路径仍正常进入 EvidenceEngine。
- Graph Search Tool 的 relation fact 通过 canonical converter 进入 evidence；
- 未知或已移除的 Provider 值在配置加载阶段 fail closed，不能改绑 Graphiti。

改造前目标断言实际失败于 unsupported answer 仍出现在最终回答。改造后边界 E2E 与 contract test
均通过。

## Decision Ownership / Fact Owner and Write Path

| 事实或决策 | Owner | 唯一入口 |
| --- | --- | --- |
| Graph query execution | Graph provider Adapter | `retrieve()` |
| Graph fact/edge/episode refs | Graph provider / graph store | `GraphRetrievalResult` |
| Provider synthesized answer | Provider candidate output | 不属于 retrieval contract |
| Evidence normalization | EvidenceEngine | `graph_result_to_evidence()` |
| Ask 最终回答 | Ask compose stage | unified ContextPack |
| Ask 回答是否满足目标 | Ask Verifier | verify stage |

## Required Production Capabilities and Missing-capability Delivery

- Graphiti 已能返回 fact、edge、episode 和 citation refs，继续启用。
- Structural/local retriever 已能返回 note/citation，继续启用。
- Microsoft GraphRAG CLI 只能取得 synthesized answer，缺少 source-grounded retrieval contract；
  其生产 Adapter、Settings/env、Runtime 装配和 eval CLI 选项已删除。重新引入前必须先实现
  source/citation binding、contract test 和 live E2E。

## Complexity Added, Removed and Rejected Alternatives

Added：无新运行层；`GraphRetrievalResult` 增加 `extra=forbid` 契约门禁。

Removed：

- `GraphAskResult.answer` 和 `graph_provider_answer` evidence projection；
- Microsoft GraphRAG answer-to-facts 字符串拆分；
- Microsoft GraphRAG 的无效生产 Adapter、配置、Runtime 装配和 eval answer projection；
- retrieval 阶段 `AgentState.answer` 派生值；
- 无生产消费者的 graph/local/web 专用 compose 方法及三个 Prompt；
- Graph/Structural provider 的误导性 `ask()` 命名。
- `graph_search` Tool 内重复的 fact/edge/hit converter；
- 未知 Graph Provider 到 Graphiti 的静默 fallback 和两个 Provider alias。

拒绝保留 `candidate_answer` 字段：没有生产消费者，且会继续混装 Proposal 与 Evidence。拒绝把
GraphRAG answer 标成低分 evidence：降低分数不能建立来源真实性。

## Removed Legacy Path / Risks

全部调用方迁移为 `GraphRetrievalResult` 和 `retrieve()`，不保留 alias 或兼容双轨。

当前生产 Graph Provider 只有 `graphiti`、`structural` 和 `hybrid`。Microsoft GraphRAG 历史结果
保留为无效 answer projection 的评测记录，不再形成生产选择面。Graphiti、structural、local、
personal knowledge 和 web 路径不受此删除影响。

## Executed Verification / Net Complexity / Remaining Risk

- baseline：`1 passed in 1.01s`；
- 改造前 target：按预期失败，unsupported answer 仍出现在最终回答；
- 首轮 Graph/Evidence/Prompt 聚焦回归：`29 passed in 2.44s`；
- Graph Tool/Provider 删除后的聚焦回归：`40 passed`；
- 首轮全量 `tests/`：`721 passed in 251.01s`；
- 当前全量 `tests/`：`720 passed, 4 warnings in 236.23s`；
- 全仓 Ruff：通过；
- package DAG：`packages=14 edges=53`、无 cycle/forbidden edge。

生产代码净删除约 300 行，主要来自三个 source-specific compose 分支、Prompt 和 retrieval answer
projection；没有新增运行层、持久化模型或兼容入口。

Microsoft GraphRAG 不属于当前生产能力，不构成当前实现的剩余风险或可用性声明。它只有在新的
baseline、source binding contract 和 live E2E 同时成立后才能重新进入设计。
