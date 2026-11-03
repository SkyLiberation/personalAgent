# 工程经验与快速排查

本目录保存已发生问题的识别线索、处理经验和证据边界，帮助后续快速定位。同一问题的生产契约、候选设计和正式评测继续由原权威正文拥有；这里提供简要判断及链接，不建立第二份运行状态。

维护时尽量精简，只保留适用范围、关键结论、识别信号和必要的证据边界；过程、日志及完整分析优先引用原记录，不重复展开。

| 症状或检索词 | 适用范围 | 经验记录 |
| --- | --- | --- |
| `json_object`、整数变字符串、`int`／`string`、数字字符串、严格校验 | 只能使用 JSON mode，读取契约允许将整数字符串无损解析为内部整数；未取得本工程运行验证 | [整数字符串的读取边界转换](json-object-integer-string.md) |
| `MiniMax`、`tool_choice=required`、强制工具调用、返回正文、`provider_action_missing` | `MiniMax-M3.1-Flash`／`api.minimax.cn`，2026-10-24 历史失败，2026-10-25 核对 | [required 不能默认可靠生效](minimax-tool-choice-required.md) |

定位 LLM 决策错误时，从 [LLM 决策排障 skill](../../.agents/skills/troubleshoot-llm-decisions/SKILL.md)按失败边界选择处理方法。
