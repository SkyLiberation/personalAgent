# ADR 0024：按正文行坐标搜索、读取和引用

2026-09-16 决定。网页正文按自然行保存和定位。文件与授权由[会话文件契约](../context/tool.md#会话文件替换决定)维护，引用编号由 [ADR 0030](0030-document-line-citation-identity.md)更新。

## 背景与决定

旧网页正文以 JSON 行保存字符片段，搜索会命中 URL 元数据，也会漏掉跨片段的连续词。现保留提取的原始正文，来源元数据留在外层；外置正文借用 Artifact 和会话文件。模型用 `grep_file` 定位，用 `read_file` 按同一坐标取回原件。绑定器按已返回窗口恢复正文和位置。

rg 适配器通过固定参数、有界输出与超时查询授权内容。进程控制与匹配事件到 `TextMatch` 字节区间的转换分开，复用原搜索 Port 与正式装配。适配器拆分的验收依据是 AST 语句对照、原语句顺序及行为保持检查；`find` 中进程控制语句由 4 处减为 0。[适配器源码](../../src/personal_agent/infra/artifact_ripgrep.py)

参考 OpenCode 和 Gemini CLI 的独立读搜及分页，以及 LlamaIndex 与 Haystack 的编号绑定。原版本、取舍、代码差异及验收由[取证记录 §103](../optimization/evidence-acquisition.md#103-正文行坐标统一与预编号引用联动)保留。

## 历史验证与退出

原中文任务到达 48 次工具调用上限，返回 `limitation`。同轨迹八稿合法绑定，29 次读搜实际返回的 1,275 行与原文一致。来源核验失败与读取证明保留各自结论。[引用历史反例](../optimization/answer-object-mismatch.md)

旧 `read_action_output` 的人工比较例外随会话文件切换退出。授权、原文、字节范围或来源绑定出现回归时，复验对应的确定性边界。
