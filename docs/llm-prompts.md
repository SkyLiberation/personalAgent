# LLM Prompt 与决策边界

Prompt Registry 拥有可复用的版本化模板；业务事实、权限、执行结果和完成结论由各自责任主体拥有。模板与版本的唯一源码是 [kernel/prompt_templates/](../src/personal_agent/kernel/prompt_templates)，调用方通过 [kernel/prompts.py](../src/personal_agent/kernel/prompts.py)读取 `PromptSpec`。本文按职责提供阅读入口，不复制版本清单或模板正文。

## 当前模板与消费者

| 模板组 | 消费者与输出责任 |
| --- | --- |
| `structured.system`、`structured.repair.system` | JSON 输出的 Schema 说明与有界修复；具体承载由请求指定，意图提取使用 `prompted_json`，其他已迁移的内部 typed 能力使用原生输出工具 |
| `conversation.interaction_intent` | `derive_interaction_intent` 的初次判断与后台来源修订共用正文／版本；提取相位和显式条件，区分当前任务与响应后后台要求，原消息仍拥有完整目标 |
| `conversation.action` | Conversation 的原生消息／动作相位；可见正文或动作均由同一循环解释，Admission/Gateway 拥有准入与执行 |
| `conversation.working_plan.description`、`conversation.answer.direct.delivery`、`conversation.research_entry.explicit` | 计划进度、普通 assistant 正文及带沟通／引用属性的原生提交；业务身份由 Runtime 绑定 |
| `structured.native_tool.repair.system` | 原生typed输出的有界修复，继续调用本次输出工具修正参数；JSON消费者仍使用原`structured.repair.system`，不混用承载 |
| `conversation.research_delivery_policy` | claims 选证／写作的适用操作和同稿出口，不引入第二循环 |
| `conversation.plan_context`、`conversation.requirements` | 从当前清单及冻结验收条件物化只读 Context |
| `conversation.history_compaction` | HistoryCompactor 将闭合旧历史生成工作摘要，原 Journal／Artifact 保留事实与原文；当前接入及真实消费的证据边界见 [Context](topics/context-engineering.md#整体窗口与历史增长的当前边界) |
| `conversation.time_budget_snapshot` | 有运行截止时，向主决策说明输入构造时的剩余秒数；无截止不注入，硬停止仍由运行系统执行 |
| `conversation.research.support` | 一次检查当前完整 claims、实际最终回答与原用户目标；八类反馈交给原研究模型，空报告绑定当前输入 |
| `interaction_verification.*` | 普通整稿核验；实际主体、条件、强度和否定范围与已提交原文对照 |
| `web_search.description`、`web_read.description` | 工具的发现与正文读取契约；选择与回答来自当前用户任务 |
| `conversation.read_artifact.description`、`conversation.search_output.description` | 实际正文坐标、读取覆盖、搜索续页及超长行边界 |
| `python_execution.description`、`python_execution.parameter.*` | Python 工具及参数说明；解释完整源码、可选输入文件绑定、实际输出和失败边界，具体程序来自当前任务 |
| `answer_generation.system` | `RuntimeLlmClient` 的文本调用，不承担 Conversation 的独立完成判断 |
| `evidence_rerank.system/user` | 显式装配的 LLM reranker 只排序已有 evidence ID |
| `graphiti.custom_extraction` | Graphiti 抽取适配；知识准入仍由 Personal Knowledge 拥有 |

Conversation 的主要消费者位于 [service.py](../src/personal_agent/application/conversation/service.py)、[model_actions.py](../src/personal_agent/application/conversation/model_actions.py)及 [research.py](../src/personal_agent/application/conversation/research.py)。分层与实际模型请求的构造边界见 [Runtime](topics/runtime.md)、[Context](topics/context-engineering.md)与[核验专题](topics/verification-and-completion.md)。注册项是否被消费须从调用链核实，注册本身不代表生产接入。

## 研究相位的协作

普通外部研究选证读取原会话、冻结验收项、当前研究及实际返回资料，选择下一步取证或写作；初稿 Schema 不允许声明已有 claim 回答。研究 writer 负责 claims 与最终回答，已有段落用当前 aN 引用由 Runtime 恢复，改写段落才生成新文字。准入原子检查版本和引用，claims 修改未同时提供新回答时清空旧回答。

部署绑定的检索实验由 `conversation.research_entry.explicit` 说明原生提交与文件检查，不进入下述 claims 及语义核验链；引用绑定保留。领域范围见 [ADR 0037](adr/0037-experiment-submission-first-delivery.md)，模型协议按 [ADR 0045](adr/0045-native-intent-loop-and-recorded-model-output.md)。

统一核验实际完整版本的来源支持、回答与 claims 的一致性，以及仅基于最终回答的目标满足。缺失回答由 Runtime 拦截；有发现则原研究模型修订或补证，无发现则 Completion 检查当前版本和确切正文后交付。旧 Coverage、synthesis、研究 Final 及反向重开均已删除；普通回答保持原核验路径。当前职责由[核验专题](topics/verification-and-completion.md)拥有，规格和验证边界见[统一 Spec](optimization/to_verify/research-goal-coverage.md#2026-10-15-sourcecoverage-与-final-合并设计)。

## 修改与验收

Prompt 的版本、typed 输出、实际消费者和变更门禁由 [Prompt 模块规范](../src/personal_agent/kernel/prompt_templates/AGENTS.md)与 [COD](devSpec/code-structure.md#6-生产-prompt-是版本化代码契约)拥有。模板、结构解析与静态检查只证明相应边界；语义效果按 [EVD](devSpec/change-evidence.md)选择真实失败输入的 Offline Eval 与受影响 E2E，历史 `tests/` 只读保留。

尚未迁入 Registry 的领域 extraction 或 grounding 指令由实际构造方拥有；触及时按同一规范收敛。Prompt 的历史自检、Plan 生命周期和拒稿恢复实验仍保留在各具体问题记录中，不从模板存在或版本提高推导产品通过。
