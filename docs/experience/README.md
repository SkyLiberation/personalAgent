# 工程经验与快速排查

按症状查已发生问题的适用范围、处理方法及证据。详细分析、运行记录和现行契约链接到各自正文。

| 症状或检索词 | 适用范围 | 经验记录 |
| --- | --- | --- |
| `json_object`、整数变字符串、`int`／`string`、数字字符串、严格校验 | 只能使用 JSON mode，读取契约允许将整数字符串无损解析为内部整数；未取得本工程运行验证 | [整数字符串的读取边界转换](json-object-integer-string.md) |
| `MiniMax`、`tool_choice=required`、强制工具调用、返回正文、`provider_action_missing` | `MiniMax-M3.1-Flash`／`api.minimax.cn`，2026-10-24 历史失败，2026-10-25 核对 | [required 不能默认可靠生效](minimax-tool-choice-required.md) |
| MiniMax、Prompt 缓存、缓存命中骤降、System Prompt、前置执行输入、工具 Schema | 主循环的相邻实发请求与原始用量 | [MiniMax 主循环缓存命中骤降](minimax-prompt-cache-prefix.md) |

定位 LLM 决策错误时，从 [LLM 决策排障 skill](../../.agents/skills/troubleshoot-llm-decisions/SKILL.md)按失败边界选择处理方法。
