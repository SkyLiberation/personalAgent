# 自建 Golden Set 设计

> 状态:设计稿(待评审) · 数据来源口径:**手工标注真实场景** · 创建于 2026-06-22

## 1. 背景与问题

当前工程的评估资产分三层,真正"属于自己"的金标几乎为零:

| 层 | 位置 | 性质 | 缺口 |
| --- | --- | --- | --- |
| 公开 RAG 基准 | [evals/multihoprag/](../evals/multihoprag/)、[evals/open_ragbench/](../evals/open_ragbench/) | 借来的外部数据集,只测检索 IR 指标 | 非本工程领域数据,与真实 capture/note 语义脱节 |
| 自建 RAG 金标 | [evals/rag_quality/cases.json](../evals/rag_quality/cases.json) | 唯一的自建 golden set,口径完整(检索 + grounding) | **仅 5 条**;reference run 是测试里[手搓的 fixture](../evals/rag_quality/test_rag_quality_gate.py),非真实管线产出 |
| 其它 Agent 能力 | 无 | — | router 意图分类、orchestration 全流程、replanner、workflow 等**无任何金标** |

结论:除 5 条 RAG 用例外,**Agent 的行为决策(路由、编排、端到端任务结果)没有一个用项目自己场景标注的金标**。本文定义一套统一的 golden set 口径、目录结构、标注规范与门禁策略,作为后续逐步落地的依据。

## 2. 设计原则

1. **复用已验证的口径,不另起炉灶。** [evals/rag_quality](../evals/rag_quality/) 的 `RagEvalCase → RunOutput → scorer → baseline.json` 四段式已跑通,新能力的金标沿用同一形状:`Case`(标注)→ `RunOutput`(可打分投影)→ `scorer`(纯函数指标)→ `baseline.json`(回归门禁地板)。
2. **标注与管线解耦。** scorer 只消费 thin 投影(`RunOutput`),从不直接吃 `AskRunContext`/runtime,保证离线、无 DB、无 LLM 可复现,且可用手搓 fixture 单测。新增能力必须保持这一边界。
3. **门禁是地板,不是目标。** `baseline.json` 里每个指标是"不得低于"的回归地板。降地板需评审理由;升地板即棘轮式提质。
4. **真实场景优先。** 所有 case 的 `question`/`input` 来自真实领域(个人知识/笔记)手工标注,而非合成模板。先小批量(每能力 20–30 条)跑通门禁,再考虑脚本扩充。

## 3. 三个金标口径(scope)

"golden set" 对本工程不是单一概念,至少有三种互不相同的标注口径。三者独立交付,优先级如下。

### 3.1 RAG 质量金标(扩充现有)

- **口径**:`{question → gold_evidence_ids, reference_answer, gold_claim_verdicts, claims_needing_contrast}`,即现有 [dataset.py](../evals/rag_quality/dataset.py) 的 `RagEvalCase`。
- **指标**(已实现,见 [metrics.py](../evals/rag_quality/metrics.py)):recall@5 / ndcg@5 / context_precision / answer_relevance / faithfulness / claim_accuracy / contrastive_coverage。
- **缺口**:仅 5 条。需扩到 30–50 条,补齐场景矩阵:
  - 单跳精确命中 / 多跳召回(已有雏形)
  - 含矛盾证据、需对比证据翻转判定
  - 无答案 / 证据不足(应 `not_found` 而非编造)
  - 中文长文 chunk 折叠回 parent 的召回
  - 同义改写、跨 note 概念聚合
- **reference run 来源**:当前是测试内手搓 fixture。**改进项**:用 `runner.replay_contexts` 回放真实序列化 `AskRunContext`,让金标对的是真实管线产出而非理想 fixture(见 §6)。

### 3.2 Router 意图金标(新建)

- **口径**:`{entry_input → expected_outcome ("ready"|"clarify"), expected_intents (有序), expected_clarification_fields?}`。对齐 [router.py](../src/personal_agent/agent/router.py) 的 `RouterOutput` 契约。
- **指标**:
  - `outcome_accuracy` —— ready/clarify 判定正确率
  - `intent_set_f1` —— 多目标意图集合的 F1(顺序无关)/ 或有序 Kendall-tau(若顺序有语义)
  - `clarify_precision` —— 该追问时确实追问、不该追问时不打扰
- **现状**:仅有 [tests/test_router.py](../tests/test_router.py) 的契约单测(校验 pydantic 约束),**无回归金标**。
- **标注难点**:意图边界主观,需在标注规范里固化"何时算 clarify"的判据(见 §5)。

### 3.3 Orchestration 端到端金标(新建)

- **口径**:`{user_input → expected_step_sequence (类型/顺序), expected_terminal_outcome, expected_hitl_interrupts?}`。覆盖 entry → router → steps → HITL interrupt → resume 全流程。
- **指标**:
  - `step_sequence_match` —— 期望步骤序列的编辑距离 / 类型集合命中
  - `terminal_outcome_match` —— 终态产物是否符合期望
  - `hitl_trigger_accuracy` —— 该中断处确实触发 HITL
- **现状**:[evals/conftest.py](../evals/conftest.py) 已有真实 LangGraph + Postgres + stub router 的全流程 fixture,但**无标注金标集驱动**,只有零散 flow 测试。
- **依赖**:需运行 Postgres;门禁应分层——纯标注校验可离线,全流程跑归 nightly。

## 4. 目录结构

沿用 `evals/<capability>/` 的并列结构,每个能力一个自包含子包:

```
evals/
  rag_quality/        # 已存在,§3.1 扩充
    cases.json        # 金标(扩到 30–50 条)
    dataset.py        # Case / RunOutput 模型
    metrics.py        # 纯函数指标
    scorer.py         # Case×RunOutput → 报告
    baseline.json     # 回归地板
    runner.py         # 真实管线 → RunOutput 投影 + 回放 CLI
    test_*_gate.py    # 门禁测试
  router_quality/     # 新建,§3.2
    cases.json
    dataset.py        # RouterEvalCase / RouterRunOutput
    metrics.py
    scorer.py
    baseline.json
    runner.py
    test_router_gate.py
  orchestration_quality/   # 新建,§3.3
    cases.json
    ...(同形)
    test_orchestration_gate.py
```

**约定**:`cases.json` 一律 UTF-8;loader 用 `Path(...).read_text(encoding="utf-8")`(注意 Windows 默认 GBK,直接 `open()` 会炸中文)。

## 5. 标注规范(手工标注)

每个能力的 `cases.json` 是手工标注真实场景的产物。统一规则:

1. **来源真实**:`question`/`input` 取自真实个人知识/笔记场景,不用合成模板;PII 用占位符。
2. **稳定 id**:`<cap>-NNN` 形如 `rq-001`/`router-001`,新增追加不复用。
3. **每条带 `description`**:一句话说明该 case 想测什么场景(loader 忽略未知键,可自由加人读注释)。
4. **金标可判定**:
   - RAG:`gold_evidence_ids` 必须能在对应 corpus 中定位;`gold_claim_verdicts` 按答案中 claim 出现顺序对齐。
   - Router:`expected_outcome` 二选一;clarify 判据固化为——"缺少执行目标所必需的信息(对象/范围/时间)"才标 clarify,语气模糊但意图明确不标。
   - Orchestration:`expected_step_sequence` 标步骤**类型**而非具体文案,避免脆性。
5. **覆盖矩阵**:每能力的金标必须覆盖正例 + 反例(矛盾/无答案/不该追问),不能全是 happy path。
6. **评审**:金标变更走 PR review;新增/修改 case 需在 PR 描述里说明覆盖的新场景。

## 6. 门禁与运行策略

- **离线门禁(CI 必跑)**:scorer + baseline,纯函数无 DB/LLM。形如 [test_rag_quality_gate.py](../evals/rag_quality/test_rag_quality_gate.py) 的 `check_thresholds`。
- **真实管线回放(nightly / 手动)**:`runner.replay_contexts` 吃序列化 `AskRunContext`,让金标对真实产出;orchestration 全流程门禁需 Postgres,归此层。
- **evals/ 默认在 testpaths 外**,显式运行:`uv run pytest evals/rag_quality/test_rag_quality_gate.py -v`。
- **baseline 升降规则**:实际均值高于地板时,在评审中可上调地板(棘轮提质);下调地板必须在 `baseline.json` 的 `_comment` 里写明理由(现有文件已有先例)。

## 7. 落地顺序(建议)

1. **P0 — 扩充 RAG 金标(§3.1)**:风险最低,口径现成,只加数据 + 把 reference run 切到真实回放。立即可见提质。
2. **P1 — Router 意图金标(§3.2)**:离线、无需 DB,ROI 高;先固化 clarify 判据再标注。
3. **P2 — Orchestration 端到端金标(§3.3)**:依赖 Postgres 全流程,最重,放最后;复用 [evals/conftest.py](../evals/conftest.py) 现有 fixture。

## 8. 待确认问题

- RAG 金标的 corpus:是用 §3.1 提到的真实 note 快照,还是为金标单独维护一份小 corpus 固定下来?(影响 `gold_evidence_ids` 的稳定性)
- Router `intent` 顺序是否有语义?决定用集合 F1 还是有序指标。
- Orchestration `expected_step_sequence` 的粒度:到 node 级还是 step-type 级?
