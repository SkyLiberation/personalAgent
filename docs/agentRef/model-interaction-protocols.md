# 模型消息、Schema 与交付协议参考

2026-10-24 核对。本文记录实际源码机制，不定义 personalAgent 的现行行为；本工程采用决定由[Loop Schema 统一设计](../optimization/to_verify/conversation-loop-schema.md)拥有。固定提交仅证明该版本，不声明最新发布。源码和 SHA-256 见[参考清单](../../.tmp/loop-schema-redesign-20261024/source-manifest.json)。

## 1. 实际装配与消费链

| 来源 | 固定源码与实际调用链 | 已核实机制与边界 |
| --- | --- | --- |
| S1：smolagents | `huggingface/smolagents@96f33faaf028479119ec8d34507b47694cf14e34`；[工具定义](https://github.com/huggingface/smolagents/blob/96f33faaf028479119ec8d34507b47694cf14e34/src/smolagents/default_tools.py#L83)、[Agent](https://github.com/huggingface/smolagents/blob/96f33faaf028479119ec8d34507b47694cf14e34/src/smolagents/agents.py#L402)：`MultiStepAgent` 注入 FinalAnswerTool → run／步骤生成 → ToolCallingAgent 生成原生调用 → process_tool_calls → ActionOutput → FinalAnswerStep | `final_answer` 接收答案本身；不先发送空准备动作再调用 JSON 成文。参数校验与工具执行错误分开。它检查最终回答独占，但检查发生在工具处理之后；该顺序不满足本工程“混批先拒绝、零执行”的要求。CodeAgent 通过执行器的 final-answer 标记结束，不能把它解释为无需沙箱或执行事实。 |
| S2：Gemini CLI | `google-gemini/gemini-cli@cd1b45c2db0a5ea7b7fc3b67c1ba5879601d6005`；[client](https://github.com/google-gemini/gemini-cli/blob/cd1b45c2db0a5ea7b7fc3b67c1ba5879601d6005/packages/core/src/core/client.ts#L648) → [Turn.run](https://github.com/google-gemini/gemini-cli/blob/cd1b45c2db0a5ea7b7fc3b67c1ba5879601d6005/packages/core/src/core/turn.ts#L269) → Content／工具调用／Finished 事件；[文件工具](https://github.com/google-gemini/gemini-cli/blob/cd1b45c2db0a5ea7b7fc3b67c1ba5879601d6005/packages/core/src/tools/write-file.ts#L369)、[Todo 工具](https://github.com/google-gemini/gemini-cli/blob/cd1b45c2db0a5ea7b7fc3b67c1ba5879601d6005/packages/core/src/tools/write-todos.ts#L29) | 正文直接来自模型文本；文件内容由专用工具执行写入，计划由独立 Todo 操作维护。无 pending tools 时还有 next-speaker 检查，不能概括为收到任意文本便立即完成，更不能据此删除本工程 Completion。Todo 的完整列表和状态属于模型参数，执行结果与 UI 展示分别投影。 |
| S3：OpenHands SDK | `OpenHands/software-agent-sdk@6530325e9dd0ea1b6b4f1994d7dab52764cfc3f1`；[FinishAction](https://github.com/OpenHands/software-agent-sdk/blob/6530325e9dd0ea1b6b4f1994d7dab52764cfc3f1/openhands-sdk/openhands/sdk/tool/builtins/finish.py#L21) → 工具 Schema → response_dispatch → Agent 批次执行；[详细审计](../../.tmp/loop-schema-redesign-20261024/openhands-reference/report.json) | finish 的业务参数是 message，通用层另有可选 summary。原生调用、reasoning 和结果按真实 ID 重建。无工具文本也可 FINISHED；finish 后截断批次、等待保留工具结束；这些语义不能照搬为本工程的完成事实。参数错误、工具内部异常、Provider 暂时失败、运行错误分别处理，不把它们统一称为 HTTP 不可用。 |
| S4：LangChain | `langchain-ai/langchain@b15a385cb1aa4507b86a3ba1e6430748b0c4ae4b`；[create_agent 的策略装配](https://github.com/langchain-ai/langchain/blob/b15a385cb1aa4507b86a3ba1e6430748b0c4ae4b/libs/langchain_v1/langchain/agents/factory.py#L1066) → [OutputToolBinding](https://github.com/langchain-ai/langchain/blob/b15a385cb1aa4507b86a3ba1e6430748b0c4ae4b/libs/langchain_v1/langchain/agents/structured_output.py#L318) → 工具参数解析 → typed structured_response 或配对 ToolMessage 错误 | Provider 原生结构化输出与工具调用承载结构化数据是不同策略。后者把目标类型导出为输出工具，并在本地验证参数；不依赖正文恰好为 JSON。该输出工具不是业务副作用。错误恢复策略可配置，本工程仍须沿自己的有限次数、Journal 和费用规则，不能照搬任意重试。 |

四组源码均为 A 级参考，已读取装配及真实消费者。S1/S2 原件在本节清单的 `references/`；S3 的独立清单包含 51 份源码及 Git blob 校验。未执行第三方项目，不以其机制存在证明 personalAgent 改善。

## 2. Provider 与 HTTP 依据

[MiniMax M3.1 工具文档](https://platform.minimax.cn/docs/guides/text-m3-function-call)要求多轮工具调用保留完整 assistant 消息及存在的 reasoning 字段，结果按原 call ID 配对。它支持工具调用，不代表具有另一种 API 的全部结构化输出约束。

`MiniMax-AI/MiniMax-Provider-Verifier@6f8ac0fbd004e30f2dbfacbe343d2a63d4138f4d` 的[官方 M3 校验说明](https://github.com/MiniMax-AI/MiniMax-Provider-Verifier/blob/6f8ac0fbd004e30f2dbfacbe343d2a63d4138f4d/m3_format_check/docs/m3_text_cases.md#L111)明确记录 M3 暂不支持 `response_format=json_object`，相关项被跳过。当前 [M3.1 Chat Completions 页面](https://platform.minimax.cn/docs/api-reference/text-chat-openai)未列出 `response_format`。前一结论不能直接外推到 M3.1；现有资料足以否定“兼容 OpenAI 路径就可以默认假定 JSON 模式受服务端约束”的设计前提。本工程第 14 轮两份完整响应已经证明当次请求没有取得所需 JSON。

[RFC 9110 §15.6](https://www.rfc-editor.org/rfc/rfc9110.html#section-15.6)区分内部异常、无效上游响应、暂时不可用与上游超时。[FastAPI 错误处理](https://fastapi.tiangolo.com/tutorial/handling-errors/)支持由 Adapter 显式投影错误。对外 HTTP 状态和上游实际 HTTP 状态是两个事实，不得相互代填。

## 3. 可采用与需保留差异

参考共同支持原生消息／工具调用、直接携带答案、专用文件工具、最小业务参数，以及在本地验证模型输出。它们没有证明必须使用本工程当前的空准备动作、全局 Final union，或让模型回传 owner、scope、revision、digest。

终止分类的实际坐标不能遗漏：S3 [classify_response](https://github.com/OpenHands/software-agent-sdk/blob/6530325e9dd0ea1b6b4f1994d7dab52764cfc3f1/openhands-sdk/openhands/sdk/agent/response_dispatch.py#L54)优先tool_calls，其后是非空可见content，reasoning-only与empty另处置；[_handle_content_response](https://github.com/OpenHands/software-agent-sdk/blob/6530325e9dd0ea1b6b4f1994d7dab52764cfc3f1/openhands-sdk/openhands/sdk/agent/response_dispatch.py#L257)发MessageEvent并设置FINISHED。其critic仍可消费该事件；finish工具与正文并存，不支持“必须finish调用才是合法正文”的概括。S2 [无pending tools的下一发言者检查](https://github.com/google-gemini/gemini-cli/blob/cd1b45c2db0a5ea7b7fc3b67c1ba5879601d6005/packages/core/src/core/client.ts#L905)同样说明正文先是原生响应，是否继续与完成判断另有owner。

S4 OpenAI适配器的[_convert_delta_to_message_chunk](https://github.com/langchain-ai/langchain/blob/b15a385cb1aa4507b86a3ba1e6430748b0c4ae4b/libs/partners/openai/langchain_openai/chat_models/base.py#L554)把role解释成AIMessageChunk等类别，正文及工具参数另作增量；不能把结构角色按普通文本串接。其[function schema转换](https://github.com/langchain-ai/langchain/blob/b15a385cb1aa4507b86a3ba1e6430748b0c4ae4b/libs/core/langchain_core/utils/function_calling.py#L120)另有dereference_refs／去$defs步骤；这证明完整wire转换的具体机制，不独立证明本工程的字段类型失败由$defs造成。

本工程的确定性权限、原文引用、持久 Command、整批准入、核验及 Completion 有真实消费者，必须保留。保留内部 typed 模型不要求向模型暴露其全部字段；采用 message 正文也不允许把任意文本视为完成。统一设计须逐项说明这些适配的工程依据及反事实。

## 4. 终答入口与框架职责的组织

2026-10-25 针对普通正文与结束工具是否形成重复协议，重新读取 S1／S2／S3 的装配、响应分类及终止消费者。重新取得的四份源码、复用的三份固定源码及校验和见[本轮来源](../../.tmp/framework-finalization-analysis-20261025/source-manifest.json)，未执行第三方代码或发起模型请求。以下只说明固定版本的机制，不声称代表各项目最新发布或证明本工程收益。

| 实现 | 实际组织方式 | 对本问题的含义 |
| --- | --- | --- |
| S1 smolagents | `MultiStepAgent` 注入 `FinalAnswerTool`；`ToolCallingAgent._step_stream` 经 `process_tool_calls` 将 `final_answer` 结果标为 `ActionOutput.is_final_answer`，原主循环消费该标记；`CodeAgent` 从执行器取得对应标记 | 正常步骤以明确的最终动作交回答案，正文格式不是完成协议。达到最大步数的兜底生成另有路径，不能概括为所有终态都只允许工具。不能据此要求本工程再次强制 finish，旧第 17 轮已经否定该适配 |
| S2 Gemini CLI | `GeminiClient` 消费 `Turn.run`；Turn 分别产生 Content、工具调用和带 finish reason 的 Finished 事件；Client 在无 pending tools 等条件下执行可配置的 next-speaker 检查 | 正文、调用、回合结束是不同事实。外层决定是否继续，不能将一段文本或 Markdown 标题当作用户任务完成，也不必让模型输出内部结果大对象 |
| S3 OpenHands SDK | `AgentBase.include_default_tools` 可装配 FinishTool；`Agent` 混入 `ResponseDispatchMixin`，先按 tool_calls、可见 content、reasoning-only、empty 分类。无调用正文产生 MessageEvent 并设 FINISHED；FinishAction 携带 message，经实际动作执行和 finalize，在未被阻止、无继续细化时设 FINISHED | 固定实现确实允许两种结束表达；不是只提供 finish 工具。两路分别保留 MessageEvent／ActionEvent，Finish 路径还有细化与 Hook 条件，不能声称它们内部所有行为完全相同，也不能照搬其 FINISHED 为本工程 Completion |

三者没有要求模型同时完成空准备动作和第二次 JSON 成文。差异属于响应分派与终止策略，不支持单凭入口数量判断架构优劣。需要核对同一职责是否有重复契约、各表达承载什么业务意义，以及保存、恢复和完成是否有唯一 owner；本工程的取舍由[Loop Spec §17](../optimization/to_verify/conversation-loop-schema.md#17-终答入口的框架分析与职责收窄候选)拥有。
