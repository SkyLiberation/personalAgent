# LLM Prompt 与决策边界

Prompt Registry 拥有可复用的版本化模板；业务事实、权限、执行结果和完成结论由各自责任主体拥有。模板与版本的唯一源码是 [kernel/prompt_templates/](../src/personal_agent/kernel/prompt_templates)，调用方通过 [kernel/prompts.py](../src/personal_agent/kernel/prompts.py)读取 `PromptSpec`。本文按职责提供阅读入口，不复制版本清单或模板正文。

## 当前模板与消费者

| 模板组 | 消费者与输出责任 |
| --- | --- |
| `structured.system`、`structured.repair.system` | JSON Object Adapter 的传输与有限结构修复；调用方 Pydantic 类型拥有输出 Schema |
| `conversation.action` | Conversation 的原生动作相位；模型选择可见动作，Admission/Gateway 拥有准入与执行 |
| `conversation.working_plan.description`、`conversation.prepare_final.description` | 原生控制动作；工作清单进度与最终提交分别表达 |
| `conversation.plan_context`、`conversation.requirements` | 从当前清单及冻结验收条件物化只读 Context |
| `conversation.final` | 普通最终提交；完整稿或基于当前基稿的修订交给核验及 Completion |
| `conversation.research.evidence_selection`、`conversation.research.writer` | 研究模型选择实际原文并生成、编辑或撤回当前论断；Runtime 保护版本、坐标与编辑范围 |
| `conversation.research.support`、`conversation.research.coverage` | 分别判断来源支持与原用户事实覆盖，反馈绑定实际输入版本 |
| `conversation.research.synthesis`、`conversation.research.faithfulness`、`conversation.research.final_verification` | 独立汇总、具体来源归属、修订比较、忠实性与最终交付验收 |
| `interaction_verification.*` | 普通整稿核验；实际主体、条件、强度和否定范围与已提交原文对照 |
| `web_search.description`、`web_read.description` | 工具的发现与正文读取契约；选择与回答来自当前用户任务 |
| `conversation.read_artifact.description`、`conversation.search_output.description` | 实际正文坐标、读取覆盖、搜索续页及超长行边界 |
| `answer_generation.system` | `RuntimeLlmClient` 的文本调用，不承担 Conversation 的独立完成判断 |
| `evidence_rerank.system/user` | 显式装配的 LLM reranker 只排序已有 evidence ID |
| `graphiti.custom_extraction` | Graphiti 抽取适配；知识准入仍由 Personal Knowledge 拥有 |

Conversation 的主要消费者位于 [service.py](../src/personal_agent/application/conversation/service.py)、[model_actions.py](../src/personal_agent/application/conversation/model_actions.py)及 [research.py](../src/personal_agent/application/conversation/research.py)。分层与实际模型请求的构造边界见 [Runtime](topics/runtime.md)、[Context](topics/context-engineering.md)与[核验专题](topics/verification-and-completion.md)。注册项是否被消费须从调用链核实，注册本身不代表生产接入。

## 研究相位的协作

选证按原用户问题、冻结条件和全部实际已返回资料判断信息需求；写作者消费本轮所选原文，准入检查新增引用坐标并保护未改字段。创建、修订或撤回后的当前集合由运行系统组织来源支持及覆盖核验，旧版本报告只在实际输入身份仍适用时复用。

覆盖检查判断原问题是否已有实质答案；呈现、自检和交付条件由最终核验判断。研究集合通过后，独立汇总消费原论断、引用及确定性来源 URL 投影，按具体说明保留来源归属。Runtime 从最终段落的引用恢复逐段原文与来源 URL，现有最终核验对照实际指代及具体页面支持关系，继续验收忠实性和整体交付。修订时从最近适用拒绝 Receipt 恢复旧稿及失败反馈，以同研究版本、同原项和上一实际稿约束输入；汇总保持有据数量与范围，最终核验逐项检查原错误修复、全部语义变化及正文、总结的一致性。实际请求差异与待验证效果由[修订比较候选](optimization/to_verify/final-revision-comparison.md)拥有。局部修订涉及前文来源变化时，写作者将受影响的相邻指代句纳入修订范围；多来源共同支持的内容保留全部相关引用。当前停用的拆分及独立文档缺项分类分别按 [ADR 0033](adr/0033-claim-deletion-and-document-absence-pause.md)保留历史身份；完整机制见 [ADR 0032](adr/0032-conversation-research-claims.md)，正式结果由[评测盘点](evals/02-current-case-inventory.md)拥有。

## 修改与验收

Prompt 的版本、typed 输出、实际消费者和变更门禁由 [Prompt 模块规范](../src/personal_agent/kernel/prompt_templates/AGENTS.md)与 [COD](devSpec/code-structure.md#6-生产-prompt-是版本化代码契约)拥有。模板、结构解析与静态检查只证明相应边界；语义效果按 [EVD](devSpec/change-evidence.md)选择真实失败输入的 Offline Eval 与受影响 E2E，历史 `tests/` 只读保留。

尚未迁入 Registry 的领域 extraction 或 grounding 指令由实际构造方拥有；触及时按同一规范收敛。Prompt 的历史自检、Plan 生命周期和拒稿恢复实验仍保留在各具体问题记录中，不从模板存在或版本提高推导产品通过。
