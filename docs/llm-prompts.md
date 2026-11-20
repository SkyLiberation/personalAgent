# LLM Prompt 与决策边界

Prompt Registry 拥有可复用的版本化模板；业务事实、权限、执行结果和完成结论由各自责任主体拥有。模板与版本的唯一源码是 [kernel/prompt_templates/](../src/personal_agent/kernel/prompt_templates)，调用方通过 [kernel/prompts.py](../src/personal_agent/kernel/prompts.py)读取 `PromptSpec`。本文按职责提供阅读入口，不复制版本清单或模板正文。

## 当前模板与消费者

| 模板组 | 消费者与输出责任 |
| --- | --- |
| `structured.system`、`structured.repair.system` | JSON 输出的 Schema 说明与有界修复；具体承载由请求指定，意图提取使用 `prompted_json`，其他已迁移的内部 typed 能力使用原生输出工具 |
| `conversation.interaction_intent` | `derive_interaction_intent` 的初次判断与后台来源修订共用正文／版本；提取相位和显式条件，区分当前任务与响应后后台要求，原消息仍拥有完整目标 |
| `conversation.action` | Conversation 的原生消息／动作相位；可见正文或动作均由同一循环解释，Admission/Gateway 拥有准入与执行 |
| `conversation.working_plan.description`、`conversation.answer.submit_description`、`conversation.answer.citation_repair` | 计划进度、带沟通状态和可选引用的原生提交，以及实际坐标校验失败后的修复反馈 |
| `structured.native_tool.repair.system` | 原生typed输出的有界修复，继续调用本次输出工具修正参数；JSON消费者仍使用原`structured.repair.system`，不混用承载 |
| `conversation.plan_context`、`conversation.plan.recovery`、`conversation.requirements` | 物化计划工具回执、Step Context 的计划接续信息及冻结验收条件 |
| `conversation.history_compaction` | HistoryCompactor 将闭合旧历史生成工作摘要，原 Journal／Artifact 保留事实与原文；当前接入及真实消费的证据边界见 [Context](topics/context-engineering.md#整体窗口与历史增长的当前边界) |
| `conversation.context.budget`、`conversation.time_budget_snapshot`、`conversation.low_budget_warning` | 在主决策末尾的 Step Context 展示当次额度、适用的剩余秒数和低余额提醒。预算组件执行硬停止。 |
| `interaction_verification.*` | 普通整稿核验；实际主体、条件、强度和否定范围与已提交原文对照 |
| `web_search.description`、`web_read.description` | 工具的发现与正文读取契约；选择与回答来自当前用户任务 |
| `conversation.read_artifact.description`、`conversation.search_output.description` | 实际正文坐标、读取覆盖、搜索续页及超长行边界 |
| `python_execution.description`、`python_execution.parameter.*` | Python 工具及参数说明；解释完整源码、可选输入文件绑定、实际输出和失败边界，具体程序来自当前任务 |
| `answer_generation.system` | `RuntimeLlmClient` 的文本调用，不承担 Conversation 的独立完成判断 |
| `evidence_rerank.system/user` | 显式装配的 LLM reranker 只排序已有 evidence ID |
| `graphiti.custom_extraction` | Graphiti 抽取适配；知识准入仍由 Personal Knowledge 拥有 |

Conversation 的主要消费者位于 [interaction_prompt.py](../src/personal_agent/application/conversation/interaction_prompt.py)、[service.py](../src/personal_agent/application/conversation/service.py)及 [model_actions.py](../src/personal_agent/application/conversation/model_actions.py)。分层与实际模型请求的构造边界见 [Runtime](topics/runtime.md)、[Context](topics/context-engineering.md)与[核验专题](topics/verification-and-completion.md)。注册项是否被消费须从调用链核实。

## 答复提交与领域交付

中英文 `conversation.action` 指示模型在目标就绪后直接输出普通 Markdown 答复，所用来源可链接实际获取的 URL。明确无法继续时，单独调用 `control_report_turn_status` 报告限制或失败。两种输入由 Runtime 恢复为同一类候选，适用反馈沿原主循环接续。[ADR 0055](adr/0055-unified-conversation-answer.md)

部署绑定的检索实验由领域提示说明提交与文件检查，沿同一输入协议交回候选。领域范围见 [ADR 0037](adr/0037-experiment-submission-first-delivery.md)。

## 修改与验收

Prompt 的版本、typed 输出、实际消费者和变更门禁由 [Prompt 模块规范](../src/personal_agent/kernel/prompt_templates/AGENTS.md)与 [COD](devSpec/code-structure.md#6-生产-prompt-是版本化代码契约)拥有。模板、结构解析与静态检查只证明相应边界；语义效果按 [EVD](devSpec/change-evidence.md)选择真实失败输入的 Offline Eval 与受影响 E2E，历史 `tests/` 只读保留。

尚未迁入 Registry 的领域 extraction 或 grounding 指令由实际构造方拥有；触及时按同一规范收敛。Prompt 的历史自检、Plan 生命周期和拒稿恢复实验仍保留在各具体问题记录中，不从模板存在或版本提高推导产品通过。
