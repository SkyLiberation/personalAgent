# 面试文档规范

本目录所有文档（含后续新增）必须遵守本规范。它只约束写法与举证口径，不新增架构事实。

## 1. 优先级与事实源

1. 生产代码、[E2E catalog](../../evals/e2e_quality/evidence_catalog.py)、同 revision 的执行证据；
2. [当前核心架构](../summary/core-architecture-current-state.md)、
   [Phase 0 能力与发布基线](../summary/phase0-capability-release-baseline.md) 等 summary；
3. 本目录文档。

低优先级与高优先级冲突时，改本目录文档，不改结论口径。未来设计只能出现在「下一步」类小节，
并显式标注未落地。

## 2. 每个设计单元必答五问

任何一个「我们这样设计」的段落，必须能回答：

| # | 问题 | 不合格的样子 |
| --- | --- | --- |
| D1 | 它解决的第一性问题是什么 | 只说用了什么技术、什么模式 |
| D2 | 不这样做会出现哪个具体故障 | 「更清晰」「更优雅」「解耦」 |
| D3 | 实现在哪里（代码位置与判据） | 只有概念名词，无法指认 |
| D4 | 理念从哪来，与外部实践的异同 | 「业界都这么做」 |
| D5 | 证据是什么，边界在哪 | 只讲优点 |

D2 是硬门槛：**说不出被阻止的具体故障，就是为了设计而设计。**「解耦」「可扩展」不是故障名，
「Admission 补参数后语义 owner 变成 if/else，Golden Set 覆盖不到」才是。

D5 是另一个硬门槛：只能讲优点、说不出边界的设计，说明理解仍停在术语层。

排版沿用 [03 能力轴](03-capability-axes.md) 的四段结构（问题本质 / 常见做法与失效 / 本项目选择 /
证据与边界），D4 可并入前两段。段名可按主题调整，五问不可缺。

## 3. D4 的写法：理念对照，不是权威背书

引用外部实践（Claude Code / Agent SDK、OpenAI Agents、LangGraph、MCP、A2A、Deep Research 类
harness、各家 structured output 规范）时必须写清三件事：

1. **对照的是哪一层**：控制流所有权、context 策略、工具治理还是传输格式；
2. **本项目相同点**；
3. **本项目不同点及原因**——通常来自单用户 / 单进程 / 无 sandbox 这类真实约束。

禁止两种写法：

- **权威背书**：「XX 也这么做，所以正确」。外部实践是同类问题的另一组解，不是判据。
- **抄袭式对齐**：把没有实现的机制写成本项目理念（例如 compaction、两阶段工具发现、sandbox）。
  没做就归入边界，并说明为什么当前不做。

反向也要成立：本项目与主流做法**不同**的地方（object-root envelope、Ask 只读、no God Task、
删掉无消费者的 Plan）必须给出约束层面的理由，不能只说「我们选择了另一条路」。

## 4. 协议层与传输层必须分开

顶层协议（所有权链）与 wire format（JSON schema、envelope 形状）是两层，任何段落不得混讲：

- 顶层协议：`User Goal + Context + Observation -> Model Proposal -> Admission / Policy ->
  Governed Execution -> Execution Fact -> Verification -> Completion`，规定每类事实的 owner；
- wire format：当前 `AgentTurnDecision` object-root envelope，是 Provider 适配结果，可替换。

Provider 兼容性取舍（如放弃 root union）只能写在传输层，**不得冒充顶层框架理念**。

## 5. 证据分级与措辞

| 级别 | 含义 | 允许的措辞 |
| --- | --- | --- |
| A | 正式入口 E2E，clean matching revision | 「已证明」 |
| B | 正式入口 E2E，但 dirty revision 或覆盖窄 | 「有 E2E 证据，覆盖限于……」 |
| C | 诊断运行、单测、对象存在、DB 有记录 | 「有实现与诊断证据，不构成发布资格」 |
| D | 仅设计或推理 | 「设计如此，未被证据闭合」 |

规则：

- 引用 E2E 用固定编号（E01、E14、L01、LT01-LT13、IP01）与 baseline id，不写「测试都过了」；
- C 级不得升格为「已验证」；测试通过 ≠ 发布资格，发布资格只能由 clean matching revision 的
  release archive 派生；
- 反证与正证同等重要：写清哪条断言证明了「不该发生的事没发生」（确认前零写入、不伪造
  CompletionReport、预算耗尽不拼替代答案）。

## 6. 不得虚构历史

只能陈述本项目真实发生过的事故与 baseline。行业通病（正则解析控制流、模型自述当完成）若本项目
没有对应 baseline，必须写成「被拒绝的行业实现路径」，不能说成本项目历史故障。

## 7. 形式约定

- 中文正文；协议名、类名、字段名、disposition 值保留英文原文；
- 代码位置一律用可点击相对链接：`[models.py:72](../../src/personal_agent/application/conversation/models.py#L72)`；
- 每篇开头一段说明用途 + 事实源优先级；
- 新增文档按 `NN-topic.md` 命名，并在 [INDEX.md](INDEX.md) 的阅读顺序中登记要点；
- 结构图用 ```text 块，不用 ASCII 艺术；
- 篇内避免重复整段架构描述，改为链接到已有章节。

## 8. 自查清单

提交前逐条过：

- [ ] 每个设计单元答满 D1-D5；
- [ ] 每个「所以我们这样设计」都能指出被阻止的具体故障（D2）；
- [ ] 外部实践只作对照，未作背书；未实现的机制未被写成理念；
- [ ] 顶层协议与 wire format 没有混讲；
- [ ] 每条证据标注级别，编号与 baseline 可查；
- [ ] 每个主题都有边界段，且不是套话；
- [ ] 无虚构历史事故；
- [ ] 与 summary/生产代码无冲突，INDEX 已更新。
