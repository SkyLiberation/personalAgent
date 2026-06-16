# 控制论视角下的能力差距与演进方向

## 来源

- 原文：《如何看待由 OpenClaw 作者引发的 "Loop 工程" 讨论？》（知乎回答）
- 链接：https://www.zhihu.com/question/2048003050531558553/answer/2049537011460182357
- 抓取日期：2026-06-16（知乎反爬，经 CDP 连真实 Chrome 抓取；脚本见 `.claude/skills/zhipu-code-plan-refresh/zhihu-fetch.mjs`）
- 文章主旨：AI Coding 正沿 Prompt → Context → Loop → Goal Engineering 演进，其终点是 Kubernetes 早已走过的控制论（Desired State → Observe → Diff → Act → Repeat 的调谐循环）。
- 相关实现记录：跨 run 反思回注闭环见 `docs/interview/13-loop-engineering-and-control-theory.md`。

## 这份文档的定位

这不是 bug 列表，也不是重构计划，而是一次**用外部理论框架反向审视架构**的记录。参照对象是「Loop Engineering / 把 AI Coding 类比 Kubernetes 控制论」的讨论，核心论点是：

```text
Prompt Engineering → Context Engineering → Loop Engineering → Goal Engineering
Agent Capability = Model × Context × Loop × Evaluation
```

文章的核心断言：决定 Agent 上限的不是模型，而是 **Goal（目标能否形式化）** 和 **Evaluation（完成能否机器判定）**；一切「自动化逼近目标」的系统最终都会回到控制论——目标清晰、状态可观测、反馈准确。

本项目（个人知识库 Agent）用这套框架自评，结论分三类：
- **已达标**：状态外置、声明式 spec、admission 式策略门、跨 run 反思闭环（刚实现）。
- **场景性偏离**：单次执行而非调谐循环——这是知识库 QA 场景决定的合理选择，不强行对齐。
- **真实差距**：Evaluation 偏窄、Goal 未显式形式化、缺全局成本阀——这才是值得演进的方向。

下面只展开第三类，并给出每项的现状证据、目标形态、演进路径。

---

## 差距一：Evaluation 偏窄——验证只有「确定性下限」，缺「语义上限」

### 现状

`AnswerVerifier`（`src/personal_agent/agent/verifier.py`）是纯确定性规则校验器，不调用任何 LLM：
- 引用合法性（孤儿引用检测）
- 证据充分性计分（match/citation 数量加权）
- claim 级 grounding（词汇 overlap / 中文 n-gram 集合交集）
- 兜底措辞检测（字符串匹配）

这套设计的优点正是控制论看重的：**机器可判定、零幻觉、可重复**，接近 K8s 的 `observed == desired`。这是它的价值，不应否定。

### 差距

文章把 Evaluation 列为天花板。当前 verify 是一道「下限闸门」——能卡住「引用造假、无证据支撑、纯兜底话术」这类明显不合格答案；但抓不住：
- **语义对但用词不同**：答案正确，词汇 overlap 低，被误判证据不足。
- **引用合法但推理错误**：每句都挂了 [E1]，但结论从证据推不出来。
- **遗漏关键信息**：答案没错，但漏了证据池里的重要约束。

这三类正是文章说的「测试通过 ≠ 真正修复」在 QA 场景的投影。

### 目标形态

把 Evaluation 做成**分层验证矩阵**，而非单层规则：

```text
Layer 1 (已有)  确定性规则：引用合法性 + 证据充分性 + grounding 下限
Layer 2 (缺)    语义判定：独立 LLM-judge 评估「答案是否被证据支撑、是否回答了问题」
Layer 3 (缺)    离线基准：evals/ 的 multihoprag/open_ragbench 跑分作为回归基线
```

### 演进路径与关键权衡

- **Layer 2 必须用独立模型**，不能复用生成端的 `OPENAI_MODEL`——这是 maker/checker 的精髓（模型给自己打分太宽容）。可复用 config 已有的分模型能力（如 `planner` 用专用端点的模式）。
- **LLM-judge 自身会错**：文章明确警告「谁来监督监督者」。因此 Layer 2 不应替代 Layer 1，而是叠加——确定性规则先卡硬门槛，LLM-judge 只在规则通过后做语义复核，且其否决需要可解释理由进审计。
- **成本**：每次 ask 多一次 LLM 调用。应作为可配开关（参照 `reflection_replay` 的做法），高价值场景开、普通问答关。

涉及文件：`agent/verifier.py`、`agent/runtime_ask.py`（verify 调用处）、`core/config.py`（新增 judge 模型配置 + 开关）、`evals/`（基线）。

---

## 差距二：Goal 未显式形式化——「完成」的标准藏在代码里，没有声明出来

### 现状

文章认为 AI Coding 最大的问题是 **Goal 说不清**（「优化支付系统」无法机器判定）。本项目在这点上有**天然优势**：知识库 QA 的「完成」远比编码任务好定义——检索到证据、引用锚定、grounding 达标。

但这个 Goal 目前是**隐式的**——它分散在 verifier 的计分逻辑、ContextPack 的预算门控、prompt 的约束里，没有一个地方把「这次 ask 算成功的标准是什么」声明成可读、可调的结构。

### 差距

文章设想的终态是 Goal 被声明成形式化指标：

```yaml
goal:
  citation_grounded: true       # 每个关键结论有可溯源证据
  evidence_sufficiency: >= 0.6  # 证据充分性分数
  no_fallback: true             # 不是兜底话术
evaluation:
  layers: [deterministic, semantic_judge]
```

当前这些标准是硬编码的魔法数（如 evidence 权重 0.11、char_budget 5000、verify 阈值），调一次要改代码、跑测试。**Goal 没有成为一等公民。**

### 目标形态

把「ask 成功判据」从代码里提取成**声明式 Goal spec**，挂到现有的 WorkflowSpec 体系下（项目已有声明式 workflow 注册表，这是天然的落点）：
- 每个意图（ask / delete / solidify）声明自己的 success criteria。
- verifier 读这份 spec 做判定，而非内置魔法数。
- 调整判据 = 改 spec，不改代码——和 K8s 改 `replicas:3` 一样。

### 演进路径与关键权衡

- **不要过度形式化**：知识库 QA 的 Goal 比编码简单，但仍有主观成分（「答得好」难完全量化）。Goal spec 应覆盖可机器判定的部分（引用、充分性、兜底），主观部分留给 Layer 2 的 LLM-judge，不强求全量化。
- **复用现有 WorkflowSpec**：不新建体系。在 `workflow.py` 的步骤声明里扩展 success_criteria 字段，让 verifier 消费。
- **渐进**：先把 verifier 现有的魔法数抽成命名常量/config，再升级为 per-intent spec。

涉及文件：`agent/workflow.py`（WorkflowSpec 扩展）、`agent/verifier.py`（读 spec）、`core/config.py`。

---

## 差距三：缺全局成本阀——单步有界，但整个 run 没有总预算兜底

### 现状

文章把「成本失控」列为 Agent 四大硬伤之一：「没有显式预算限制，Agent 可以无限探索下去。」本项目有**局部**的界：
- ReAct 迭代 cap = 5
- 步骤 max_retries
- replan 上限
- 检索 char_budget / max_items

### 差距

这些都是**单点**的界，缺一个**贯穿整个 entry run 的总预算阀**：
- 一个 run 里多次 replan + 多步 ReAct + 多源检索 + verify 重试，累计 LLM 调用次数 / token / 墙钟时间没有统一上限。
- 极端情况（反复 replan 又反复失败）下，单 run 成本无硬顶。

文章的对照是 K8s 的 requeue + 指数退避 + 明确终止条件：「一个没有终止条件的循环不是工程系统，是资源泄漏。」

### 目标形态

在 `AgentGraphState` 上挂一个 **run-level budget**，在图的关键节点（每次 LLM 调用、每次 replan、每步执行）做累计校验，触顶则优雅终止（返回部分结果 + 说明），而非继续探索：

```text
RunBudget:
  max_llm_calls        # 整个 run 的 LLM 调用上限
  max_tokens           # 累计 token 上限（用现有 trace 统计）
  max_wall_seconds     # 墙钟时间上限
  max_replans          # 整个 run 的 replan 总次数（区别于单步 retry）
```

### 演进路径与关键权衡

- **可观测性已就绪**：`core/observability.py` 已有 `RunMetrics` 在统计调用/token，成本阀可复用这套计数，不用新建埋点。
- **优雅降级而非硬杀**：触顶时应走「salvage compose」路径（replanner 已有这个启发式），给用户一个基于已有信息的部分回答 + 明确说明「因预算限制提前终止」，而不是抛错。
- **默认宽松**：阀值默认设高，仅作失控兜底，不影响正常 run；可 config 调。

涉及文件：`agent/orchestration_models.py`（RunBudget 字段）、`orchestration_nodes/`（节点校验）、`core/observability.py`（复用计数）、`core/config.py`。

---

## 不予对齐的范式偏离（场景决定，非差距）

为避免后续误读，明确记录两处**主动选择不对齐**文章的地方：

### 1. 单次执行 vs Reconciliation Loop

文章的 Loop 是 K8s 式调谐：每轮丢弃上下文、从持久状态重读、和目标 diff、不收敛再来一轮。本项目是 `request → 声明式 workflow 投影 → 图执行 → response` 的单次执行。

**为何不对齐**：知识库 QA 大多单轮可完成，不存在「需要反复调谐直到收敛」的长程任务。强行套调谐循环只会增加复杂度和成本，违背文章自己「能用 workflow 别上 agent」的主张。跨 run 的学习已通过反思回注闭环覆盖（见 `docs/interview/13`），不需要把单次 ask 也改成循环。

### 2. 多 Agent 团队（Maker/Checker/Reviewer 分立进程）

文章设想 Agent A 编码、B 测试、C review 的多 agent 控制平面。本项目是单 Agent + 分层子图 + PolicyEngine（admission 式策略门）。

**为何不对齐**：单 Agent 内部的模块化分工（router / step / react 子图 + policy）已覆盖职责分离的核心价值，且共享一个可恢复的 checkpoint。多 agent 的进程隔离、邮箱通信、worktree 隔离是为大型并行编码任务设计的，对个人知识库 QA 是过度工程。文章也强调「不到万不得已别上多 agent」。

---

## 优先级建议

按「价值 / 成本」排序，给未来迭代一个参考次序：

1. **差距三（成本阀）** —— 成本最低（复用 RunMetrics），直接消除「无限探索」硬伤，安全性收益明确。
2. **差距一 Layer 2（独立 LLM-judge）** —— 中等成本，直接提升 Evaluation 上限，是文章认为的天花板所在。
3. **差距二（Goal 形式化）** —— 成本最高、收益偏长期，建议在 Layer 2 落地后再做，因为 Goal spec 需要 Evaluation 分层先成型才有意义。

三者共同指向文章的同一句话：**当 Goal 和 Evaluation 被定义清楚，模型只是可替换组件。** 本项目已经把 Context、状态外置、跨 run 反思做扎实，下一阶段的杠杆在 Evaluation 与 Goal。
