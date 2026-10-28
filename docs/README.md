# personalAgent 文档索引

personalAgent 是个人知识智能体 Runtime。用户表达目标，系统协调模型、知识、工具和执行，并按结果契约交付答案。

理解现行系统从[工程架构](architecture/README.md)开始；开发规则从[根规范](../AGENTS.md)进入。查找未解决问题看 [Future 队列](future/design-optimization-backlog.md)，查找实际结果与证据限制看[评测盘点](evals/02-current-case-inventory.md)。

## 目录分工

| 目录 | 定位 |
| --- | --- |
| [`AGENTS.md`](AGENTS.md) | `docs/**` 的目录级文档治理入口；继承根主规范并链接中文写作与权威索引 |
| [`chinese-writing-spec.md`](chinese-writing-spec.md) | 所有工程文档和对用户回答的表达规范；拥有设计 Spec 结构、需求追溯、证据措辞和存量迁移门禁 |
| [`devSpec/`](devSpec/README.md) | 开发、设计、评测、文档和发布门禁；规范与项目 skill 统一从[根任务路由](../AGENTS.md#3-任务路由按识别信号读取细则)进入 |
| [`agentRef/`](agentRef/README.md) | 按组件组织的外部机制检索与分级参考；不定义本工程现状、路线或采用结论 |
| [`experience/`](experience/README.md) | 已发生问题的快速识别与排查经验；标明适用范围、原始证据和结论边界，不替代生产契约或正式评测 |
| [`architecture/`](architecture/README.md) | 现行全局架构、代码地图与横切机制的权威正文；作为后续设计和开发的框架基线 |
| `topics/` | 入口、运行系统、工具、记忆、上下文、检索与验收的详细契约，入口见下方主题表 |
| [`workflow/`](workflow/README.md) | 具体业务用例的信息流与固定执行流程 |
| `summary/` | 明确标注身份的历史架构审计；现行架构进入 `architecture/`，指标报告进入 `evals/` |
| [`interview/`](interview/INDEX.md) | 基于已有事实和证据的面试材料；写法见[目录规则](interview/00-writing-spec.md) |
| `mermaid/` | 工具与记忆的依赖图；正文契约由对应专题拥有 |
| `future/` | 尚未闭环的准入项；状态收敛与退出见 [Future 规则](future/README.md) |
| [`optimization/`](optimization/README.md) | 按问题维护过程与取舍；[待验证方案](optimization/to_verify/README.md)和[已解决问题](optimization/completed/README.md)各有索引 |
| `adr/` | 已接受决策、迁移与退出条件，以及有保留价值的候选取舍记录 |
| `evals/` | 执行结果、测量报告、评测证据与发布限制；入口见 [评测体系](evals/README.md) |
| [`ablation/`](ablation/README.md) | 隔离机制消融的规格、结果与适用边界；不替代当前产品契约和正式发布证据 |
| 顶层文档 | API、部署、环境变量、提示词和主动知识能力等独立主题 |

## 文档书写原则

文档治理见[文档模块规范](AGENTS.md)，表达与设计写法见[中文写作规范](chinese-writing-spec.md)。同一事实只维护一份正文，索引提供入口；现行说明、候选方案与历史证据按各自身份阅读。

## 按主题找权威文档

| 主题 | 权威文档 |
| --- | --- |
| 当前核心架构、代码地图与横切机制 | [工程架构入口](architecture/README.md) |
| 面经、JD 与工程证据对照的差距审视 | [2026-10-16 工程审视](summary/agent-engineering-gap-review-20261016.md)；当日分析快照，问题状态仍见 Future 队列 |
| 当前未解决问题与优化准入 | [future/design-optimization-backlog.md](future/design-optimization-backlog.md) |
| 优化推进过程与经验 | [优化索引](optimization/README.md) |
| 当前用例、机制证据与发布限制 | [当前评测用例盘点](evals/02-current-case-inventory.md) |
| 模型 Provider 参数与结构化输出 | [参数配置](env.md#provider-选择与参数绑定)、[模型调用组合](architecture/cross-cutting.md#2-模型调用的实际组合) |
| 入口/传输层（Web / CLI / Feishu） | [topics/entry.md](topics/entry.md) |
| 工具声明、曝光与执行结果 | [topics/tools.md](topics/tools.md) |
| 策略观测、审计与横切机制 | [观测与治理](topics/observability-governance.md)、[横切装配](architecture/cross-cutting.md) |
| Memory 与知识事实边界 | [topics/memory.md](topics/memory.md) |
| Context 收集、过滤与物化 | [topics/context-engineering.md](topics/context-engineering.md) |
| Retrieval 与证据推理 | [topics/retrieval-reasoning.md](topics/retrieval-reasoning.md) |
| Verification 与 Completion | [核验与交付](topics/verification-and-completion.md) |
| Conversation 动作、Final 与运行时重试 | [运行系统](topics/runtime.md) |
| Observation 卸载、原文重读与引用 | [工具](topics/tools.md)、[Context](topics/context-engineering.md) |

各专题链接相关 ADR，历史决定从正文追溯；能力结果与发布资格由评测文档拥有。

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
