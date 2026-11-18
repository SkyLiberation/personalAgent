# MiniMax 主循环缓存命中骤降

核对日期为 2026-11-16。用例运行于 `MiniMax-M3.1-Flash` 的 `api.minimax.cn/v1/chat/completions` 接口。

相邻请求命中率骤降时，先找实际发送请求的首处前缀差异。MiniMax 公开的匹配顺序依次是系统提示、工具定义和会话消息。首条 `system`、历史之前的其他 `system` 消息和工具 Schema 都值得逐项核对。差异发生在请求构造时，由上下文组装链解释。 [MiniMax 缓存说明](https://platform.minimax.io/docs/api-reference/text-prompt-caching#important-notes) · [主循环上下文模式](../context/agent-loop.md)

## 排查方法

1. 绑定同一会话的相邻实发 HTTP 请求和原始 MiniMax 回包。用 `usage.prompt_tokens_details.cached_tokens / usage.prompt_tokens` 计算 OpenAI 兼容接口的命中率，缺少用量的请求记为未知。
2. 对比首条 `system`、完整工具定义与顺序，再按角色和顺序对比 `messages`。重点检查所有位于原生工具历史前的区块，包括用户附件、用户原话、当前目标和压缩后的原件定位。旧布局还要检查「执行输入」。记录首次差异的位置、内容和产生者。末尾追加工具回执或更新本步预算时，核对前面已有消息能否逐字接续。
3. 把发生变化的内容追到权威事实及模型消费者。按当前适用范围区分阶段切换、必要压缩、重复投影和运行时数值。相同路径或资源 ID 已出现在配对回执时，继续核对回执是否也给出了可用的读取方式。
4. 验证缓存影响时，用同一相邻请求做单变量对照。每组先发送上一请求建立缓存，再读下一请求的服务端实际用量。固定模型、端点、输出上限及其余输入。另核对必要的路径、引用、权限和调用配对。独立整例用量用于观察整条轨迹。 [实际输入审计](../devSpec/context-memory-retrieval.md#12-system-prompt-与-context-的设计及问题分析)

## 已验证的历史案例

| 首处变化 | 处理与固定输入验证 |
| --- | --- |
| `academic-pdf-report` 首条系统提示持续刷新预算和剩余秒数。 | 实时预算移到原生工具历史之后的 Step Context。第 59 次测量请求由 **0.08%** 升至 **99.34%**。 [预算对照及实发用量](../optimization/to_verify/conversation-loop-boundaries.md#319-对话预算治理的装配边界) |
| `academic-pdf-report` 首次创建计划后，首条系统提示重复发送工具回执里的清单。 | 通过原生计划工具回执接续。当前版本的回执被覆盖时，由 Step Context 恢复进度。第 8 次测量请求由 **0.55%** 升至 **97.01%**。 [计划接续和缓存实测](../optimization/completed/working-plan-context.md) |
| `notion-hr` 在历史前的「执行输入」重发候选稿和 29 个引用。候选版本与 ID 的变化改写了前缀。 | 原生提交保留候选及反馈。历史覆盖原提交时使用恢复投影。第 17 次测量请求由 **0.11%** 升至 **99.10%**。 [主循环的候选稿去重](../context/agent-loop.md#22-结果失败后持续修复) |
| `filter-low-selling-products` 把新原件 ID 追加到四个工具参数的 `enum`。 | 正式链路改为在对应回执提供文件路径，Runtime 校验当前任务的访问权限。保留原消息、只移除枚举的对照中，第 18 次测量请求由 **0.11%** 升至 **95.00%**。 [会话文件契约与枚举消融](../context/tool.md) |

## 复跑仍出现的前缀变化

同一滞销商品用例经正式 Web 入口复跑。64 次主请求的累计命中率为 **79.08%**，其中 10 次低于 10%。以下请求序号均指该次运行的主请求，证据来自 HTTP 实发和原始 MiniMax 回包。 [逐请求审计](../../data/e2e_traces/toolathlon/woo-6afad3e7/cache-and-file-audit.json)

| 位置 | 实际差异与用量 | 责任边界 |
| --- | --- | --- |
| 首条 System Prompt 和工具定义 | 第 2 到 3 次请求由目标维护切入业务执行，工具由 3 个变为 96 个，首条系统提示同时新增工具说明。第 3 次为 **128 / 26,359（0.49%）**。63 对相邻请求中，首条系统提示与工具定义各只在此处变化。 | 目标状态切换改变了实际可用能力。这次有明确的阶段边界。 |
| 原生历史前的「执行输入」 | 第 **8、10、14、43、48** 次的首处差异都在第三条消息。该 `system` 消息新增了 `program.py` 材料。工具定义一致，命中率分别为 **0.28%、0.26%、0.13%、0.16%、0.08%**。 | `trace_resource_refs` 汇集 Python 命令和回执中的文件引用，`_append_artifact_sources` 将引用加入材料。主请求把材料渲染为「执行输入」，放在已保留的工具历史之前。 [资源投影](../../src/personal_agent/application/conversation/artifact_sources.py) · [请求组装](../../src/personal_agent/application/conversation/service.py) |
| 历史压缩 | 第 41 次第三条消息的开头变为「已压缩工具结果的原件定位」，命中 **185 / 72,578（0.25%）**。第 42 次复用新历史，命中 **97.19%**。 | 压缩替换了已覆盖历史，随后请求可复用重建后的前缀。 [压缩与原件定位](../context/agent-loop.md#31-压缩后如何定位工具原件) |

### 第 13 到 14 次请求的原文核对

两次请求的前三条消息依次是首条 `system`、用户原话、`system`「执行输入」。原生工具历史在后面。第三条消息开头一致，下面只摘开头首条材料。

```text
## 执行输入
可读材料 `program.py`，共 186 字节，resource_id 为 `artg_4291a7efe1e0808aada49c472fa6fde3`，可用 file_path artifacts/artg_4291a7efe1e0808aada49c472fa6fde3 读取正文。
```

第 13 次调用了 `tool_execute_python`。该调用的结果随第 14 次请求在工具历史中回传，结果的 `program_ref.resource_id` 已含 `artg_bce53ebc4002e4437e2529db631855f2`。第 14 次请求还在更前面的「执行输入」末尾追加了多条 Python 文件记录。以下是首条新增材料，其中包含同一资源的可读路径。

```text
可读材料 `program.py`，共 1321 字节，resource_id 为 `artg_bce53ebc4002e4437e2529db631855f2`，可用 file_path artifacts/artg_bce53ebc4002e4437e2529db631855f2 读取正文。
```

相邻命中量从 **25,088 / 93,269** 降为 **128 / 94,890**。第 48 次还同时带入一个新的会话工具原件，工具 Schema 仍一致，第一处差异同样是前置的 Python 材料。 [第 13 次实发](../../data/e2e_traces/toolathlon/woo-6afad3e7/run/filter-low-selling-products/personal/sdk/b3a969df5383499491b23ca18fb58314.http.request.json) · [第 14 次实发](../../data/e2e_traces/toolathlon/woo-6afad3e7/run/filter-low-selling-products/personal/sdk/287c2ab49bb94d3b95a6424028175580.http.request.json)

前置 Python 材料的首处差异已确认。主循环现行布局及验收由[上下文模式](../context/agent-loop.md#33-移除主请求的前置执行输入)维护。独立缓存收益仍须固定输入对照。该历史复跑中第 2、4 次也有低命中，当时首处变化在历史后的预算与新增交换处，服务端原因待核实。 [逐请求审计](../../data/e2e_traces/toolathlon/woo-6afad3e7/cache-and-file-audit.json)
