# MiniMax：required 不能默认保证工具调用

核对：2026-10-25；范围：`MiniMax-M3.1-Flash`／`api.minimax.cn`，2026-10-24 历史链路。

**结论：该链路不能依赖 `required` 保证工具调用。** 两次历史请求均声明 `required`，原始响应却均为普通正文、`tool_calls=0`、`finish_reason=stop`。

- **识别信号**：声明 `required` 后仍返回正文，本地报 `provider_action_missing`；先核对实际出站与原始响应，不只加强 Prompt。
- **证据边界**：缺少历史 HTTP 出站抓包，具体失效环节未确认，不能外推为 MiniMax 全系列明确不支持；指定函数模式未验证。
- **容易混淆**：`required` 只要求调用任意可用工具，不指定 `submit_final`；本地拒绝正文不代表服务端强制生成生效。

详细过程、参数语义及后续排查见[Loop Spec §17.6](../optimization/to_verify/conversation-loop-schema.md#176-工具选择参数的语义与历史有效性)；原件、两次响应及校验和见[历史审计](../../.tmp/tool-choice-boundary-20261025/required-history-audit.json)。当前主循环仍使用 `auto`，本文不改变生产策略。
