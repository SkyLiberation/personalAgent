# 研究参数范围由当前可见输入派生

**已成立 `CLAIM-ARGUMENT-SCOPE-001` 的范围交接：研究写作实发 Schema 携带当前可见引用目录、当前 claim 与片段身份。** 范围从 canonical 输入即时派生；引用是否合法仍由唯一 binder 和研究准入判定。

## 问题与机制

历史请求只返回 `d1:1-44`、`d2:1-35`，参数 Schema 却允许任意 `dN`，模型提交了九处未返回引用。2026-10-01 审计确认先前接入概述过宽，现行生产写作还在使用静态 Schema；本轮补齐生产投影。

`research_submission_type` 在 Conversation 唯一研究请求构造点消费本轮 `CitableInput.citations`：文档号进入引用格式范围，完整行合并为实际连续区间，缺行保持分开，部分行按原样列出；Schema 描述给出当前行范围。当前 canonical claims 生成 claim ID 枚举，同一[片段投影](claim-fragment-addressing.md)生成编辑 ID 枚举。新作用域类型继承 canonical submission 契约；JSON Schema 是本次 Provider 参数说明，运行时继续按现行 typed 契约解码。

引用目录物化本轮选择与当前集合已绑定引用的可见坐标，不建立可写副本，不枚举全部子区间。Runtime binder 检查实际窗口、连续行完整性与部分行精确坐标，研究准入核对新增引用的本轮选择、完整资源版本及 claim 身份；拒绝沿现有 DecisionFeedback 恢复路径返回模型。准入与解析不猜测目标或补造引用。

## 证据、依赖与验证

正式入口、装配和模型不变，`service.py` 在物化本轮所选及现有绑定原文后立即构造范围类型；Adapter 将其 Schema 放入真实请求。新增持久目录、Port、模型及网络调用为 0。旧静态写作请求选择点被替换；业务契约继续由同一研究模块拥有。

| 证据 | 成立判据 |
| --- | --- |
| [历史失败与目录回放](../../../.tmp/claim-constraints-recovery-20260922/replay-report.json) | 对应历史资料的未返回文档范围被排除，合法目录与实际输入一致；属于当时条件局部证据。 |
| [本轮真实 v5 回放](../../../.tmp/research-convergence-integration-20261001/fragment-replay.json) | 当前 claim/片段枚举对齐，合法坐标保持可用，未知文档被 Schema 范围排除。 |
| [实际 Provider 请求审计](../../../.tmp/research-convergence-integration-20261001/target/writer-view-audit.json) | 每轮范围从实际已选正文派生，与当前集合及地址同步。 |

证据限定为范围投影、正式消费和运行校验；原用户结果与调用指标由[评测登记](../../evals/02-current-case-inventory.md#2026-10-01-重试计量与研究设计接入)拥有。

## 依据与失败尝试

2026-09-22 核对 [OpenAI 参数范围官方指导](https://developers.openai.com/api/docs/guides/function-calling#best-practices-for-defining-functions)、[Anthropic Schema 契约](https://platform.claude.com/docs/en/agents-and-tools/tool-use/define-tools)及 [Gemini CLI replace 运行检查](https://geminicli.com/docs/tools/file-system/#replace-edit)。本工程采纳已知身份进入参数说明及执行侧最终校验。

历史隔离候选的 JSON 模式仍出现空目录下编造引用和动作字段混用；这些实发违规被拒绝后恢复，说明运行检查和反馈必须保留。2026-09-28 的宽泛接入状态已按本轮源码及实发请求纠正。

若范围漏掉本轮合法坐标、跨越未返回缺行、枚举与当前集合不同步，或投影建立可写目录，则重新打开本问题。
