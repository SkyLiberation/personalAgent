# CTXAgent Marathon 对照

## 用例与验收

用 CTXAgent 论文公开版的 `marathon:0` 验证长会话的自动压缩及压缩后的任务接续。固定发布提交 `77ec7a9e9127e3258b035af32dc7f13730979902`，保留 212 轮的英文顺序、练习材料、临时文件出现与清理时点，以及上游评分。公开运行中 Claude Code 在 200k 窗口下触发过自动压缩。本次使用当前 1M 窗口，是否达到压缩线由实测决定。[上游用例与评分源码](https://github.com/MatthiasHBusch/CTXAgent/tree/77ec7a9e9127e3258b035af32dc7f13730979902/bench)

本 Agent 走正式 Conversation HTTP，DeepSeek Harness 走固定版本 SDK。两边各建一次新会话，使用同一 MiniMax 端点、Linux 工具镜像和相同的 Bash 可达工作区。工作区彼此隔离且禁网。路径按 Linux 沙箱渲染。只发布上游允许的题面、说明、stub、公开练习测试以及到期前的临时文件。SciCode 目标值、题源的参考解、探针答案和评分结果留在独立环境。

分别报告实际交付、未提交和执行限制。按上游检查程序、事实回忆和持续指令。记录单次输入峰值、摘要与达压裁剪以及后续评分。公开原题评分和自动压缩事件各自保留。评测适配复用现有 HTTP、Bash 授权和 SDK，无生产逻辑改动。

## 运行结果

2026 年 11 月 23 日，已准备 212 轮。构题产物包含 118 道语言练习、50 个 SciCode 小步骤、21 个延迟回忆探针、11 次临时文件读取及 12 轮事实或指令设定。轮次类型顺序与发布轨迹逐轮一致。[准备清单](../../../.tmp/marathon-20261123-materials-v3/source.json)

双方各执行一次真实模型试次。评分容器最初无法执行 Go 生成的测试二进制。将评分工作区设为可执行后，以双方前 8 轮的实际答复和代码复核，各有 7 个计分项通过，覆盖 JavaScript、Python、Go、SciCode 和临时文件读取。采集终止后使用修正后的容器对封存答复和工作区执行上游评分。[本 Agent 评分预检](../../../.tmp/marathon-20261123-grader-preflight/personal.exec.score.json) · [DeepSeek 评分预检](../../../.tmp/marathon-20261123-grader-preflight/deepseek.exec.score.json) · [运行计划](../../../.tmp/marathon-20261123-run/plan.json)

本 Agent 在第 69 轮首次自然触发历史摘要。该轮摘要前后相邻两次主请求输入分别为 799,525 和 50,227 tokens。DeepSeek Harness 在第 208 轮首次自然触发摘要，前后相邻的主请求输入分别为 799,829 和 181,350 tokens。两边都在同一轮继续执行并正常交付。[本 Agent 第 69 轮](../../../.tmp/marathon-20261123-run/personal/turn-069.trace.json) · [DeepSeek 第 208 轮](../../../.tmp/marathon-20261123-run/deepseek/turn-208.json)

第 77 轮要求回忆第 27 轮临时文件中出现的 `run_id`。本 Agent 在第 69 轮摘要后仅凭会话完成回忆，探针通过上游评分。第 77 轮轨迹记录的工具调用数为 0。[探针评分](../../../.tmp/marathon-20261123-grader-preflight/post-summary-probes.json) · [第 77 轮原始轨迹](../../../.tmp/marathon-20261123-run/personal/turn-077.trace.json)

DeepSeek Harness 交付了全部 212 轮，21 个回忆探针通过 20 个。第 212 轮要求回忆第 122 轮的临时文件。第 122 轮回答包含正确值，第 208 轮压缩替换了该轮两条包含正确值的事件，摘要未保留它。第 212 轮未调用工具，回答缺少正确值，官方判为 0 分。[DeepSeek 探针评分](../../../.tmp/marathon-20261123-grader-preflight/deepseek-probes.json) · [建立事实](../../../.tmp/marathon-20261123-run/deepseek/turn-122.json) · [摘要事件](../../../.tmp/marathon-20261123-run/deepseek/turn-208.json) · [末轮答复](../../../.tmp/marathon-20261123-run/deepseek/turn-212.json)

本 Agent 提交 144 轮，交付 141 轮。第 127 轮返回 `failed`。第 143 轮达到 1,000 万单轮 token 额度并返回 `limitation`。该轮第 18 步的原生 Bash 调用已随模型响应记入历史，执行入口未接受该调用，历史中也没有工具结果或拒绝记录。第 144 轮在构造第一个模型请求前返回 HTTP 409。只读重放原始第 143 轮轨迹复现同一错误，模型调用和工具派发均为 0。现有接续接口依赖同一段原生历史，第 145–212 轮未提交。[第 143 轮轨迹](../../../.tmp/marathon-20261123-run/personal/turn-143.trace.json) · [第 144 轮 HTTP 事件](../../../.tmp/marathon-20261123-run/personal/turn-144.sse) · [只读重放结果](../../../.tmp/marathon-20261123-grader-preflight/history-replay.json) · [历史重放要求](../../../src/personal_agent/application/conversation/model_history.py#L289)

### 对照结果

| 指标 | 本 Agent | DeepSeek Harness |
| --- | ---: | ---: |
| 提交 / 交付 | 144 / 141 | 212 / 212 |
| 上游计分项通过 | 122 / 133 | 178 / 200 |
| 共同有效计分项通过 | 122 / 130 | 120 / 130 |
| 已知模型 tokens | 209,877,440 | 259,950,844 |
| 单次输入峰值 tokens | 805,646 | 799,829 |
| 生成阶段耗时 | 2 小时 0 分 39 秒 | 1 小时 13 分 14 秒 |
| 压缩摘要触发轮次 | 69、100、127 | 208 |
| 跨摘要回忆探针通过 | 6 / 6 | 0 / 1 |
| 持续指令检查通过 | 214 / 214 | 356 / 356 |
| 未提交 | 68 | 0 |
| 评分器异常 | 0 | 0 |
| 采集停止状态 | 第 144 轮 HTTP 409 | 完成 212 轮 |

[本 Agent 逐轮评分](../../../.tmp/marathon-20261123-official-scores/personal/scores.json) · [DeepSeek Harness 逐轮评分](../../../.tmp/marathon-20261123-official-scores/deepseek/scores.json) · [原采集报告](../../../.tmp/marathon-20261123-run/comparison.json) · [评分汇总](../../../.tmp/marathon-20261123-official-scores/comparison.json)

计分轮若未交付按上游的运行失败规则记为 0 分。共同有效分数只统计双方均有有效计分结果的 130 项。未提交轮次单独记录。用量回读包含 DeepSeek 的独立摘要请求。
