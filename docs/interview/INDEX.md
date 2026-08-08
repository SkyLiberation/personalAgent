# personalAgent 面试材料索引

本目录只描述截至 2026-08-03 已落地并有代码或 E2E 证据的当前架构，不把未来设计写成当前事实。
尚未证明的用户场景只能放在明确标记的“待验证场景/证据缺口”中，不能进入当前能力矩阵或发布声明。
所有文档遵守 [面试文档规范](00-writing-spec.md)。

面试时先讲一句话：

> personalAgent 构建的是一套可信 Agent Runtime：模型负责开放语义 Proposal，确定性系统负责
> Admission、权限和执行，执行系统产生事实，Verifier 与 Completion Gate 关闭用户目标。普通用户
> 只描述目标；Conversation 按目标约束选择 request-local 能力、具体领域 Use Case 或 durable
> Investigation Project。框架统一责任链和权力边界，不把内部执行语义暴露成三种模式。

最重要的当前边界：Conversation 已能通过粗粒度 Application Capability 完成 exact-span 保存、
canonical 知识读取、确认式删除和 durable investigation handoff。E14 覆盖保存，E22 覆盖删除的
确认前零副作用、scope 和 replay，E23 覆盖只保存 ProjectReference 并从原 Project API 查询。
它们不证明订阅变更、冲突核对后保存、跨实例协调或 commit/Receipt crash window。Investigation Project 已有生产
Domain/Application/PostgreSQL 路径、当前 LT diagnostics 和 IP01 live target 报告交付；完整
clean-revision release matrix、跨 Provider 组合矩阵和重复运行方差仍未闭合。
package DAG gate 已于 2026-07-30 转为 PASS（原 FAIL 的
`unknown_packages = context, skills, verification` 是三个已删除包的 `__pycache__` 残骸造成的
假阳性，非真实违规）。但仍**不存在 A 级（clean matching revision）证据**——原因换成了
archive 与工作树 dirty，见 [05 证据与发布](05-evidence-and-release.md)。

## 文档结构

| 文档 | 角色 | 什么时候看 |
| --- | --- | --- |
| [00 规范](00-writing-spec.md) | 写作与举证纪律 | 新增或修改本目录任何文档前 |
| [01 项目介绍](01-project-story.md) | 讲稿与白板顺序 | 准备开场 30 秒 / 2 分钟 / 5 分钟 |
| [02 请求走查](02-request-walkthroughs.md) | 八条真实请求的生产路径 | 面试官问「一个请求怎么跑」 |
| [03 能力轴](03-capability-axes.md) | **主文档**：12 轴理念、Visibility 分层、实现、证据、边界 | 深度技术讨论；按岗位选三轴深讲 |
| [04 知识与领域 Workflow](04-knowledge-and-domain-workflows.md) | 知识域与固定事务细节 | 面试官深挖知识模型或 Command 链 |
| [05 证据与发布](05-evidence-and-release.md) | 证据编号、archive、Personal Knowledge 未证明边界、分级、release gate | 任何涉及「测过没有」的问题 |
| [06 追问速答](06-qa-and-tradeoffs.md) | 现场答话稿 | 临场速查；不展开实现细节 |

事实上下游关系：03 是理念与举证的主文档，01/02 是它的入口，04 是细节延伸，05 是证据权威源，
06 只做速答并链回 03/05。**证据编号与 archive 只在 05 定义**，其他文档引用时必须与 05 一致。

## 建议阅读顺序

0. [面试文档规范](00-writing-spec.md)
   - 每个设计单元必答 D1-D5，其中「不这样做会出现哪个具体故障」是硬门槛；
   - 外部实践只作理念对照不作背书；顶层协议与 wire format 不得混讲；
   - 证据分 A-D 级，措辞与编号口径固定。

1. [项目介绍与面试讲稿](01-project-story.md)
   - 项目解决什么问题；
   - 六条不变量各自阻止的具体故障；
   - 一套目标责任链、三类内部执行语义与不合并事实 owner 的理由；
   - 30 秒、2 分钟、5 分钟介绍稿与白板顺序。

2. [从真实请求理解架构](02-request-walkthroughs.md)
   - 直接回答、查知识、MCP、A2A、保存、删除、周期研究、动态长调查各自怎么跑；
   - 什么是固定产品操作；
   - Agent 当前如何选择能力，哪些操作尚不能从 Conversation 进入。

3. [Agent 能力轴](03-capability-axes.md)（主文档）
   - 12 条能力轴的自评矩阵；
   - 每轴的问题本质、常见做法失效点、本项目选择、证据与边界；
   - Agent loop 顶层协议（所有权链）与 wire format 的分层；
   - 决策所有权速查表；
   - 按岗位选三轴深讲的建议与全程口径纪律。

4. [知识、领域 Workflow 与 Durable Project](04-knowledge-and-domain-workflows.md)
   - Artifact、Evidence、Claim、KnowledgeItem 的关系与 fact owner 表；
   - Ask/Save 分离、correction 的 supersede 语义；
   - Delete/Restore Command；
   - Research、Subscription、Worker、Digest、Delivery；
   - ResearchRun 与 Investigation Project 的生命周期边界。

5. [证据、E2E 与发布资格](05-evidence-and-release.md)
   - 用例编号与 archive 的权威定义；
   - Release E2E 如何映射架构，LT diagnostics 为什么只是诊断证据；
   - 为什么对象存在和数据库新增不能替代 E2E；
   - 当前 dirty revision 与 package DAG gate 状态。

6. [高频追问速答与取舍](06-qa-and-tradeoffs.md)
   - 定位、治理、知识验证、取舍四组共 30 个速答；
   - 与 RAG Bot、Workflow、LangGraph、现代 Agent Harness 的关系；
   - 当前缺口、一周优先级与失败定位清单。

## 权威事实源

- [当前核心架构](../summary/core-architecture-current-state.md)
- [Phase 0 能力与发布基线](../summary/phase0-capability-release-baseline.md)
- [Durable Investigation Project 当前实现](../summary/durable-investigation-project-current-state.md)
- [未来设计索引](../future/README.md)
- [可信 Agent Runtime 演进与收敛](../future/trusted-agent-runtime-evolution.md)
- [E2E catalog](../../evals/e2e_quality/evidence_catalog.py)

若本目录与上述文档或生产代码冲突，应以生产代码、E2E catalog 和同 revision 的执行证据为准。
