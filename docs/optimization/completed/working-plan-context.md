# 计划工具历史与压缩接续

Toolathlon `academic-pdf-report` 第 7 次请求后接纳工作清单。第 8 次保留了完整的原生计划回执，首条 System Prompt 仍新增 769 字符的计划副本。原轨迹第 7 次命中 21,755 / 22,880 token，第 8 次降到 128 / 23,469。[原轨迹分析](../../../.tmp/step-budget-20261116/remaining-prefix-audit.json)

主循环沿用 DeepSeek Harness 的原生计划交换与摘要接续方式。Conversation 投影在实际发送计划工具回执时确认当前版本。没有同版本回执时，从 Journal 的清单派生 Step Context 接续信息。覆盖计划交换的压缩摘要保留未完成事项、当前进度和下一步。Journal 拥有计划状态，Admission 处理计划更新和准入。[现行上下文契约](../../context/agent-loop.md) · [DeepSeek 的摘要模板](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/compaction/compaction-basic/src/summarizer.ts#L35-L74)

## 固定输入的 MiniMax 缓存对照

对同一用例的第 7 至 8 次真实出站请求做两组重放。每组先发第 7 次，再测第 8 次。均使用 `MiniMax-M3.1-Flash`、同一接口、256 token 输出上限及原始工具定义和消息历史。两组第 8 次请求的唯一差异是首条 System Prompt 的动态计划副本。

| 第 8 次请求 | 命中 token | 输入 token | 命中率 |
| --- | ---: | ---: | ---: |
| 保留首条系统提示中的计划副本 | 128 | 23,469 | 0.55% |
| 由原生计划回执传递 | 22,548 | 23,242 | 97.01% |

[四次 MiniMax 回包用量](../../../data/e2e_traces/toolathlon/plan-context-1116/minimax-usage.json) · [固定输入布局校验](../../../data/e2e_traces/toolathlon/plan-context-1116/cache-layout.json)

## 同一用例的压缩接续

从第 11 次决策后已封存的真实 Journal 恢复输入。正式压缩器生成并激活覆盖到第 7 次决策的检查点，移出原计划交换。重新加载文件 Journal 后，主请求尾部保留计划第 1 版、一项进行中和三项待办。当前附带的下一步是继续查找论文 arXiv ID。真实 MiniMax 解码为正常继续动作，选择用 arXiv API 查找 `AutoML-Agent`，与进行中工作项一致。压缩前的中英文离线投影也确认了原生回执配对及前缀稳定。独立反事实覆盖计划版本领先于可见回执、且尚未选定下一步的分支。

这次验收覆盖压缩生成、持久 Journal 重载和真实模型选出后续动作。整例 Excel 交付和后续工具执行沿用独立评测。后续真实轨迹再出现计划变化改写首条系统提示，或覆盖原回执后失去当前进度时，重新打开对应问题。

[压缩后的 MiniMax 实发请求](../../../data/e2e_traces/toolathlon/plan-context-1116/stage-04/sdk/ae52c72ebf554c749b9b971aba6fa014.http.request.json) · [检查点与实际后续动作](../../../data/e2e_traces/toolathlon/plan-context-1116/stage-04/result.json)
