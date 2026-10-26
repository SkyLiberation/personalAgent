# personalAgent 文档索引

本项目构建的是一套可信 Agent Runtime：模型负责开放语义 Proposal，Admission/Policy 负责
确定性准入，Gateway/Executor 产生执行事实，Verifier 判断语义满足，Completion Gate 依据
required result contract 关闭用户目标。普通用户只面对一套目标入口；request-local Interaction 和
确定性领域 Use Case 是内部执行语义。没有需求 baseline 的第二套后台调查循环已撤回。

当前系统分层、目标责任链和代码地图统一从[工程架构入口](architecture/README.md)阅读；
[当前核心架构](architecture/core-architecture-current-state.md)说明 LLM/确定性边界、Capability/MCP/A2A、知识与运行时事实，
[横切机制](architecture/cross-cutting.md)说明 AOP 思路下的显式组合。后续设计与开发按 [ARC](devSpec/architecture-ownership.md#8-架构基线与持续演进)维护这一框架。
用例状态、归档数据和发布证据限制由[当前评测用例盘点](evals/02-current-case-inventory.md)维护；验证优化的过程与经验集中在 [optimization](optimization/README.md)，不再只保存在会话或仓库外报告中。

## 目录分工

| 目录 | 定位 |
| --- | --- |
| [`AGENTS.md`](AGENTS.md) | `docs/**` 的目录级文档治理入口；继承根主规范并链接中文写作与权威索引 |
| [`chinese-writing-spec.md`](chinese-writing-spec.md) | 所有工程文档和对用户回答的表达规范；拥有设计 Spec 结构、需求追溯、证据措辞和存量迁移门禁 |
| [`devSpec/`](devSpec/README.md) | 根 `AGENTS.md` 与 `CLAUDE.md` 按任务渐进披露的开发、设计、测试、文档和发布细则 |
| [`agentRef/`](agentRef/README.md) | 按组件组织的外部机制检索与分级参考；不定义本工程现状、路线或采用结论 |
| [`experience/`](experience/README.md) | 已发生问题的快速识别与排查经验；标明适用范围、原始证据和结论边界，不替代生产契约或正式评测 |
| [`architecture/`](architecture/README.md) | 现行全局架构、代码地图与横切机制的权威正文；作为后续设计和开发的框架基线 |
| `topics/` | 当前入口、运行系统、工具、记忆、上下文、检索与验收的权威专题 |
| `workflow/` | 端到端执行链路与 Governed Procedure 说明 |
| `summary/` | 明确标注身份的历史架构审计；现行架构进入 `architecture/`，指标报告进入 `evals/` |
| `interview/` | 面试材料：只组织已有事实并链接权威来源；补充规则见 `interview/00-writing-spec.md` |
| `mermaid/` | 工具与记忆的依赖图；正文契约由对应专题拥有 |
| `future/` | 尚未闭环的准入项；状态收敛与退出见 [Future 规则](future/README.md) |
| [`optimization/`](optimization/README.md) | 按问题维护推进记录；未充分证明的方案保留在 [`to_verify/`](optimization/to_verify/README.md)；已解决问题固化在 [`completed/`](optimization/completed/README.md)，删除中间流水；不维护生产或发布状态 |
| `adr/` | 已接受决策、迁移与退出条件，以及有保留价值的候选取舍记录 |
| `evals/` | 执行结果、测量报告、评测证据与发布限制；入口见 [评测体系](evals/README.md) |
| [`ablation/`](ablation/README.md) | 隔离机制消融的规格、结果与适用边界；不替代当前产品契约和正式发布证据 |
| 顶层文档 | API、部署、环境变量、提示词和主动知识能力等独立主题 |

## 文档书写原则

文档治理统一遵守[文档模块规范](AGENTS.md)，中文表达遵守[中文写作规范](chinese-writing-spec.md)。新增前先确认主题的权威文档，更新时核对当前代码与已执行证据，先删除过期和重复正文。

能力准入与设计证据见[开发细则](devSpec/README.md)，验证分工与单元测试停用边界见[QLT](devSpec/quality-security.md)。本索引只维护目录分工和主题入口。

## 按主题找权威文档

| 主题 | 权威文档 |
| --- | --- |
| 当前核心架构、代码地图与横切机制 | [工程架构入口](architecture/README.md) |
| 面经、JD 与工程证据对照的差距审视 | [2026-10-16 工程审视](summary/agent-engineering-gap-review-20261016.md)；当日分析快照，问题状态仍见 Future 队列 |
| 当前未解决问题与优化准入 | [future/design-optimization-backlog.md](future/design-optimization-backlog.md) |
| 优化推进过程与经验 | [optimization/README.md](optimization/README.md)；[研究回答来源支持记录](optimization/conversation-source-support.md) |
| 当前用例、机制证据与发布限制 | [当前评测用例盘点](evals/02-current-case-inventory.md) |
| Structured output Provider capability 隔离 | [adr/0007-structured-output-transport-capability.md](adr/0007-structured-output-transport-capability.md) |
| 入口/传输层（Web / CLI / Feishu） | [topics/entry.md](topics/entry.md) |
| 工具声明、曝光与执行结果 | [topics/tools.md](topics/tools.md) |
| 策略观测、审计隔离与技术横切 | [topics/observability-governance.md](topics/observability-governance.md)、[architecture/cross-cutting.md](architecture/cross-cutting.md)、[ADR 0034](adr/0034-runtime-policy-audit-isolation.md) |
| Memory 与知识事实边界 | [topics/memory.md](topics/memory.md) |
| Context 收集、过滤与物化 | [topics/context-engineering.md](topics/context-engineering.md)、[ADR 0030：文档坐标引用](adr/0030-document-line-citation-identity.md) |
| Retrieval 与证据推理 | [topics/retrieval-reasoning.md](topics/retrieval-reasoning.md) |
| Verification 与 Completion | [topics/verification-and-completion.md](topics/verification-and-completion.md)、[ADR 0018](adr/0018-bind-semantic-verification-to-execution-evidence.md)、[ADR 0020](adr/0020-require-conversation-source-support-verification.md)、[ADR 0021](adr/0021-separate-document-absence-from-reading-coverage.md)、[ADR 0022：引用试接入与撤回](adr/0022-conversation-owned-citations-and-support-repair.md)、[ADR 0023：原生分段引用候选](adr/0023-native-answer-segments-and-visible-citations.md)、[ADR 0027：模型取证充分性](adr/0027-model-owned-evidence-sufficiency.md)、[ADR 0028：引用来源绑定](adr/0028-preserve-citation-source-binding.md)、[ADR 0029：核验单元绑定](adr/0029-bind-verifier-feedback-to-input-unit.md) |
| Conversation 动作、Final 与运行时重试边界 | [topics/runtime.md](topics/runtime.md)、[ADR 0017](adr/0017-separate-action-selection-from-final-delivery.md)、[ADR 0019](adr/0019-bind-feedback-to-decision-turn.md)、[ADR 0025：可修订计划进度](adr/0025-revisable-plan-progress.md)、[ADR 0031：完整基稿修订](adr/0031-complete-final-revisions.md) |
| 单次 Observation 的上下文边界与卸载重读 | [ADR 0013](adr/0013-bounded-observation-and-offloaded-read.md)、[ADR 0024：正文搜索读取与引用](adr/0024-plain-source-tools-and-inline-citations.md)、[ADR 0026：查询与来源证据分离](adr/0026-separate-query-facts-from-cited-evidence.md) |

当前行为由生产代码及上表对应的权威正文核对：`architecture/` 说明全局责任与代码位置，专题拥有详细契约，workflow 说明具体用例的信息流，Mermaid 只投影这些事实。候选、历史审计和评测归档按各自身份解释；能力结果与发布资格由评测文档拥有。

## 业务与委派链路

| 阅读目标 | 文档 |
| --- | --- |
| delete_knowledge（高风险删除 + HITL） | [workflow/delete-knowledge-workflow.md](workflow/delete-knowledge-workflow.md) |
| Conversation 内确认后保存知识 | [adr/0006-conversation-governed-knowledge-save.md](adr/0006-conversation-governed-knowledge-save.md) |
| 一次性及订阅 Research 的业务执行 | [workflow/research-once-workflow.md](workflow/research-once-workflow.md) |
| Conversation 委派外部 GPT Researcher | [workflow/gpt-researcher-a2a-workflow.md](workflow/gpt-researcher-a2a-workflow.md) |
| 主动知识闭环（gap 提问 / 巩固 / 简报） | [proactive-knowledge-loop.md](proactive-knowledge-loop.md) |

## 运维与参考

| 主题 | 文档 |
| --- | --- |
| HTTP API | [api.md](api.md) |
| 部署 | [deploy.md](deploy.md) |
| 环境变量 | [env.md](env.md) |
| LLM 提示词职责与源码入口 | [llm-prompts.md](llm-prompts.md) |
| 评测分层、E2E 与发布证据 | [evals/README.md](evals/README.md) |
| Golden Set 设计 | [golden-set-design.md](golden-set-design.md) |
| 优秀智能体能力组件参考 | [agentRef/README.md](agentRef/README.md) |
| Review digest | [review-digest.md](review-digest.md) |

> 各子目录另有更细的索引：[workflow/README.md](workflow/README.md)、[interview/INDEX.md](interview/INDEX.md)。
