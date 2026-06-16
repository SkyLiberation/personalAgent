# Loop 工程与控制论视角下的自检

这篇不对应某个固定模块，而是借一个外部框架反过来审视本项目：把 AI Coding 类比成 Kubernetes 控制论的「Loop Engineering」讨论（Prompt Engineering → Context Engineering → Loop Engineering → Goal Engineering，核心公式 `Agent Capability = Model × Context × Loop × Evaluation`）。

用这个框架对照本项目，结论分两类：有些维度是**主动的反向选型**（场景决定，不是落后），有些是**真实的断点**（零件齐了但没接线）。下面按面试可能追问的角度逐条讲清楚，所有结论都来自代码实证，不是概念套用。

---

### 1. ask 的 verify 是「独立 checker 模型」还是「自己给自己打分」？

都不是。`AnswerVerifier`（`src/personal_agent/agent/verifier.py`）**完全不调用 LLM**，是一段纯确定性的规则校验器：

- 引用合法性：每个 citation 是否指向真实存在的 note，统计孤儿引用。
- 证据充分性打分：match 数量、citation 数量、web/episode 来源加权。
- 兜底措辞检测：字符串匹配 `_fallback_signals`。
- claim 级 grounding：用词汇 overlap / 中文 n-gram 集合交集判断答案句子是否被证据支撑，连否定词错配都用关键词匹配。

构造时无参数（`runtime.py` 里 `self._verifier = AnswerVerifier()`），`core/config.py` 里也没有任何 verifier 专属模型配置。verify 不达标触发的重新生成，用的是**和首次生成完全相同的那个 LLM**（`OPENAI_MODEL`）。

**为什么这样选，而不是上 LLM-as-judge：**

「Loop 工程」那篇文章主张 maker/checker 分离要用独立（更强）模型当裁判，但它自己也承认「裁判本身会错、谁来监督监督者」。本项目走的是另一条路——把 checker 做成**确定性 sensor**（对应 Fowler/Böckeler 的反馈控制：测试、类型检查、lint 这类机器可判定信号），而不是 LLM 裁判。

这条路的好处正是控制论最看重的：**机器可判定、零幻觉、可重复**，接近 K8s 的 `observed == desired`。代价是覆盖面窄：词汇 overlap 抓不住「语义对但用词不同」，也抓不住「引用合法但推理链错误」。

**面试口径：** verify 不是用来「评价答案好不好」的智能裁判，而是用来「卡住明显不合格答案」的确定性闸门——引用必须真实、必须有证据支撑、不能是兜底话术。它是 Evaluation 的下限保障，不是上限。语义级评判目前不在 verify 里做，而是放在 evals 模块离线验证。

---

### 2. 能不能「重启一个 session、状态不丢、接着跑」？

能，而且这是本项目和普通 request-response Agent 拉开差距的地方。控制论里「Controller 可以随时被杀掉，因为状态在 etcd」——本项目把这条做到了：

- **持久化是强制的**：`orchestration_graph.py` 里 `build_entry_orchestration_graph` 如果 checkpointer 为 None 直接 `raise ValueError`，不允许无持久化运行；用的是 LangGraph `PostgresSaver` + `setup()`。
- **thread_id 确定性可重建**：`_new_thread_id` 返回 `f"{user_id}:{session_id}"`，同一 user+session 再进来定位到 Postgres 里的同一条 checkpoint 链。
- **interrupt → resume 闭环**：HITL 确认用 `interrupt(confirm_payload)` 挂起；`resume_entry()` 用同一个 thread_id 重建 config，`graph.invoke(Command(resume=resume_value), config)` 从断点续跑。
- **状态可旁路读取**：`get_run_snapshot` 直接遍历 checkpointer 重建 `AgentGraphState`，`list_run_history` 读历史 checkpoint，连接断开还能自愈重建。

**恢复边界要说清楚：** 是 **checkpoint 边界（节点级）**。已落盘的节点状态不丢，但不会重放某个节点内部执行到一半的瞬时内存态——LangGraph 从最近一个完成的 checkpoint 重新进入该节点。这和 K8s reconcile 的粒度一致，是合理的工程取舍，不是 bug。

**面试口径：** 这正是「状态外置」理念的落地——Agent 的执行现场不在内存、不在对话历史里，而在 Postgres checkpoint 里。进程崩溃、换机器、用户关掉窗口再回来，只要 thread_id 一致就能接着跑。

---

### 3. 失败时生成的「反思」，下一次会用上吗？（当前的真实断点）

不会。这是目前最实在的一个缺口，要诚实承认。

写入这半条链是通的：`episodic_memory.py` 的 `build_reflection_candidate`，在 episode `outcome` 为 `failed`/`cancelled` 或有 error 时，确定性地生成一条 `memory_type="reflection"`、`status="candidate"` 的 `MemoryItem`，经 `add_memory_item` 落到 Postgres `memory_items` 表。

但**读回这半条链是断的**：

- replan 不读它：`replanner.py` 的 `replan()` 入参只有当前 run 的 `original_steps / failed_step / error / observations / intent`，prompt 里没有任何 memory/reflection 检索。
- 下一次 ask 也不读它：`runtime_ask.py` 检索的是 `search_episodes(...)`，SQL `FROM memory_episodes`——只查 episodes 表，反思候选在 `memory_items` 表，不在检索范围内。
- 接口写好了却没接线：`facade.py` 的 `list_memory_items` / `search_memory_items`、`core/evidence.py` 的 `memory_items_to_evidence`（注释明确写「Convert procedural/reflection long-term memory to evidence」）——全仓只有测试引用，生产代码零调用。证据系统甚至给 `reflection` 预留了 source_type 和权重 0.11，就差最后一根线。

**用控制论的话说：** 这相当于 K8s controller 写了 status 子资源，但下一轮 reconcile 不去读它。文章那句「一个没有 status 的 controller 是半成品」，本项目的情况是「写了 status，但 reconcile 没消费它」。所以目前只到「失败 → 记录反思」，没有形成「失败 → 反思 → 下次改进」的 Reflexion 闭环。

**为什么不假装它已经闭环：** 反思候选是确定性模板生成、`confidence=0.5` 的 candidate，直接无条件回注有反向风险（错误的反思会污染后续决策——文章也点过「模型有时会错误诊断自己，越改越差」）。要接线，正确做法是先有筛选/置信门槛和评测，而不是先连上。这也是它目前停在 candidate 状态、没接线的原因。

**面试口径：** 这是已知缺口，零件（生成、存储、检索接口、evidence 转换、权重）都在，缺的是「带门槛地回注 + 对应 eval」。这是把项目从「单次执行」往「跨 run 自我改进」推进的最低成本、最高杠杆的一步。

---

### 4. 一句话总结：本项目在控制论谱系的位置

用 `Agent Capability = Model × Context × Loop × Evaluation` 四个维度自评：

- **Context**：最强项。分层 prompt、滑动窗口 + 摘要、ContextPack 预算门控、状态外置 Postgres。
- **Goal**：隐藏优势。知识库 QA 的「完成」（检索到证据 + 引用锚定 + 支撑度达标）远比「优化支付系统」好形式化。文章认为 AI Coding 最大难题是 Goal 说不清，而本项目所在领域天然 Goal 清晰。
- **Loop**：最弱、但**是场景决定的反向选型**。本项目是 request → 声明式 workflow 投影 → 图执行 → response 的单次执行，不是 K8s 式「丢弃上下文、从持久状态重读、和目标 diff、不收敛再来一轮」的 reconciliation loop。知识库问答大多单轮可完成，不强求长程调谐。零件（episodic memory、reflection、replan）都在，只是没接成跨 run 闭环（见第 3 点）。
- **Evaluation**：方向对（确定性 verify + evals/ + multihoprag/open_ragbench benchmark），但 verify 偏窄（确定性规则，缺语义/推理层评判）。文章认为这才是天花板所在。

**收口：** 本项目是一个 Context 和 Goal 都很强、状态外置已达 Loop Engineering 水准、但跨 run 的 Loop 闭环尚未合拢、Evaluation 偏窄的单 Agent。它不是在追「自由 ReAct / 多 Agent」的热闹，而是把可恢复、可校验、可审计的工程边界做扎实——这与文章「能用 workflow 别上 agent、复杂度只在确实需要时才加」的主张是一致的。

---

[← 返回索引 INDEX.md](INDEX.md)
