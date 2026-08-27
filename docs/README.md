# personalAgent 文档索引

本项目构建的是一套可信 Agent Runtime：模型负责开放语义 Proposal，Admission/Policy 负责
确定性准入，Gateway/Executor 产生执行事实，Verifier 判断语义满足，Completion Gate 依据
required result contract 关闭用户目标。普通用户只面对一套目标入口；request-local Interaction 和
确定性领域 Use Case 是内部执行语义。没有需求 baseline 的第二套后台调查循环已撤回。

当前系统分层、框架不变量、目标责任链、LLM/确定性边界、Capability/MCP/A2A、知识与运行时事实
统一见 [summary/core-architecture-current-state.md](summary/core-architecture-current-state.md)。
用例状态、归档数据和证据限制只在[当前端到端用例盘点](evals/02-current-case-inventory.md)维护，不再复制到架构摘要或生产风险文档。

## 目录分工

| 目录 | 定位 |
| --- | --- |
| [`AGENTS.md`](AGENTS.md) | `docs/**` 的目录级文档治理入口；继承根主规范并链接中文写作与权威索引 |
| [`chinese-writing-spec.md`](chinese-writing-spec.md) | `docs/` 全目录的中文语法、术语、证据措辞和存量迁移门禁 |
| [`devSpec/`](devSpec/README.md) | 根 `AGENTS.md` 与 `CLAUDE.md` 按任务渐进披露的开发、设计、测试、文档和发布细则 |
| `topics/` | 分层设计文档（按能力域拆分：任务分析、工具、记忆、检索、可观测/治理等） |
| `workflow/` | 端到端执行链路与 Governed Procedure 说明 |
| `summary/` | 系统级综述（LLM 决策 vs 确定性流程的全局视角） |
| `interview/` | 面试材料：项目讲稿、请求走查、能力轴、Memory 架构、证据口径与速答；补充规则见 `interview/00-writing-spec.md` |
| `mermaid/` | Model / Layer 依赖类图 |
| `future/` | 未来能力与优化设想 |
| `adr/` | 已接受的跨模块架构决策、baseline、迁移和退出条件 |
| 顶层散文档 | API、部署、环境变量、评测、检索策略等独立主题 |

## 文档书写原则

**所有新增文档和被修改的段落都必须遵守[中文工程文档统一规范](chinese-writing-spec.md)。** 存量文档先清理冗余和过期内容，再按目录分批迁移；尚未进入迁移批次，不代表可以继续新增不符合规范的文字。

文档必须基于当前代码和已落地能力书写，而不是把讨论中的新想法直接追加成补丁式段落。更新架构文档前，先确认对应模块、测试和运行链路的真实职责；如果代码和文档不一致，应优先判断是代码需要调整、文档需要修正，还是需要同时修改两者。

写文档时遵守以下约束：

- **单一事实源**：不要在多个文档或多个层次重复维护同一份流程拓扑、工具契约或治理规则。
  Conversation Proposal、领域事实、执行事实和发布证据必须分别指向其 canonical owner。
- **按现有能力组织**：章节应围绕已经存在的模块边界和能力边界展开，不以旧类名或理想化
  框架目录反推当前能力。
- **避免补丁式写法**：不要在原文后面堆叠“注意 / 但是 / 其实”来修补前文。若原结构表达不准确，应重写相关小节，让最终文档读起来像一版一致的设计说明。
- **不要路径先行**：架构文档不要在开头罗列一串文件路径。文档应先解释层级、职责、关键组件和协作关系；组件名本身足以引导读者在当前目录结构中定位代码。只有在 API、部署、故障排查这类需要精确操作的文档里，才把具体路径作为必要信息出现。
- **区分现状和未来**：已落地能力写在 `topics/`、`workflow/` 或顶层权威文档；未来设想写入 `future/` 或明确标注为演进方向，不能把目标状态写成当前能力。
- **先 baseline E2E 后目标能力**：每个 Agent 能力的新增、优化或修复，必须先从正式入口实际执行同一用户目标的最简单生产 baseline，证明失败来自当前产品行为；随后才定义目标 E2E 和 Golden Set。baseline 未失败就停止，实现后必须验证用户结果、关键反事实和核心回归。组件文档只描述已被代码和执行证据支撑的能力。
- **测试新增克制**：不能因为每次小改动随意新增单测。新增测试必须服务于清晰的工程边界：新增或修复 Agent 能力边界、复现 golden set / 线上问题并提供可定位信号、保护安全/副作用/权限/幂等不变式、或锁定容易误合并/误路由的核心决策点。纯重构、实现细节调整、已被上层 golden set 清楚覆盖且定位足够明确的变化，不应再额外堆叠单测。
- **语义判断归模型，确定性事实归代码**：涉及开放世界的目标理解、候选选择、答案组织和动态
  修订时，模型产生 typed Proposal；Admission 只接受或拒绝，模型不可用时 fail closed 或请求
  用户输入。权限、流程真源、工具执行、状态迁移、幂等和审计由确定性系统负责。
- **和测试/代码同步**：如果文档声明某个模块不承担某职责，代码和测试也应体现这个边界。架构级约束优先沉到 CI 门禁；Procedure contract、Capability scope 和 trajectory eval 分别验证确定性拓扑、授权边界与开放策略质量。

## 按主题找权威文档

| 主题 | 权威文档 |
| --- | --- |
| 当前核心架构与主链接入状态 | [summary/core-architecture-current-state.md](summary/core-architecture-current-state.md) |
| 当前优化准入与后台调查撤回 | [future/design-optimization-backlog.md](future/design-optimization-backlog.md) |
| 当前用例、机制证据与发布限制 | [evals/02-current-case-inventory.md](evals/02-current-case-inventory.md) |
| Phase 0 历史边界与当前证据入口 | [summary/phase0-capability-release-baseline.md](summary/phase0-capability-release-baseline.md) |
| Structured output Provider capability 隔离 | [adr/0007-structured-output-transport-capability.md](adr/0007-structured-output-transport-capability.md) |
| 入口/传输层（Web / CLI / Feishu） | [topics/entry.md](topics/entry.md) |
| Memory 与知识事实边界 | [topics/memory.md](topics/memory.md) |
| Context 收集、过滤与物化 | [topics/context-engineering.md](topics/context-engineering.md) |
| Retrieval 与证据推理 | [topics/retrieval-reasoning.md](topics/retrieval-reasoning.md) |
| Verification 与 Completion | [topics/verification-and-completion.md](topics/verification-and-completion.md) |
| 单次 Observation 的上下文边界与卸载重读 | [adr/0013-bounded-observation-and-offloaded-read.md](adr/0013-bounded-observation-and-offloaded-read.md) |

**当前架构只以上表的 canonical 文档和生产代码为事实源。**其他 topic、workflow、mermaid 与评测
归档是专题说明或 paired evidence，不得反向定义主链、能力状态和发布资格。

## 关键业务 Procedure

| Procedure / 链路 | 文档 |
| --- | --- |
| delete_knowledge（高风险删除 + HITL） | [workflow/delete-knowledge-workflow.md](workflow/delete-knowledge-workflow.md) |
| Conversation 内确认后保存知识 | [adr/0006-conversation-governed-knowledge-save.md](adr/0006-conversation-governed-knowledge-save.md) |
| research_once（evidence-driven research loop） | [workflow/research-once-workflow.md](workflow/research-once-workflow.md) |
| gpt_researcher_a2a（GPT Researcher A2A 外部研究 Agent） | [workflow/gpt-researcher-a2a-workflow.md](workflow/gpt-researcher-a2a-workflow.md) |
| 主动知识闭环（gap 提问 / 巩固 / 简报） | [proactive-knowledge-loop.md](proactive-knowledge-loop.md) |

## Future 设计

| 主题 | 文档 |
| --- | --- |
| Future 范围与退出规则 | [future/README.md](future/README.md) |
| 当前未解决问题、准入状态与架构评审入口 | [future/design-optimization-backlog.md](future/design-optimization-backlog.md) |

## 运维与参考

| 主题 | 文档 |
| --- | --- |
| HTTP API | [api.md](api.md) |
| 部署 | [deploy.md](deploy.md) |
| 环境变量 | [env.md](env.md) |
| LLM 提示词清单 | [llm-prompts.md](llm-prompts.md) |
| 评测分层、E2E 与发布证据 | [evals/README.md](evals/README.md) |
| Golden Set 设计 | [golden-set-design.md](golden-set-design.md) |
| 生产风险与优化准入 | [production-risk-optimization-plan.md](production-risk-optimization-plan.md) |
| Review digest | [review-digest.md](review-digest.md) |

> 各子目录另有更细的索引：[workflow/README.md](workflow/README.md)、[interview/INDEX.md](interview/INDEX.md)。
