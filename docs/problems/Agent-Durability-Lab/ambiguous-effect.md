# Agent Durability Lab 写入后中断对照

## 用例与范围

采用 Agent Durability Lab `68a3d73a9d1bafe12d5be188624a802fc11404df` 的 `adl.cross-system.v1` 用例 `ambiguous-effect`。目标是原写入已生效、运行时尚未取得结果时中断进程，冷启动后接续原任务，最终只生效一次并交付原回执。上游由模拟进程执行单一 `effect-1`，没有自然语言题面。这里用同一中文请求和隔离 MCP 目标端把该操作接到两个真实 Agent，沿用故障顺序及评分不变量，报告为上游用例的产品入口适配成绩。[上游契约](https://github.com/sjarmak/agent-durability-lab/blob/68a3d73a9d1bafe12d5be188624a802fc11404df/benchmarks/agent-durability/contract-v1.json#L31-L36) · [上游执行](https://github.com/sjarmak/agent-durability-lab/blob/68a3d73a9d1bafe12d5be188624a802fc11404df/benchmarks/agent-durability/livecommon/scenarios.go#L108-L172) · [上游评分](https://github.com/sjarmak/agent-durability-lab/blob/68a3d73a9d1bafe12d5be188624a802fc11404df/benchmarks/agent-durability/oracle/oracle.go#L390-L433)

## 运行与验收

- 评测适配只放在 `evals/Agent-Durability-Lab`。MCP 目标端保存写入流水，每次有效写调用均生效并生成新的随机回执。首次写入提交后阻塞 MCP 响应，监督器确认写入后停止自己启动的被测进程，确认退出才释放响应。用于对账的读取工具只返回目标端实际状态。评分器读取流水与前后进程证据，Agent 只接触本题工具、初始请求和自己的会话。
- personalAgent 使用共用正式 Web 启动器，首轮用 SSE 取得 `turn_id`，重启维持原数据目录、数据库与授权，只调用原轮次恢复。DeepSeek Harness 使用现有源码检出的正式 `headless`，在新进程传入原 `session_id` 和固定续接句。两边均保持原目标端，客户端不补发历史和回执。DeepSeek Harness 在已恢复会话中提交新轮，personalAgent 从原轮次接续。[现行会话契约](../../adr/0054-session-run-step-journal.md) · [DeepSeek Harness 恢复入口](https://github.com/deepseek-ai/deepseek-harness/blob/2e39e70496aa02986ca6a820c5d497e816b69d7e/packages/bundle/headless/src/index.ts#L255-L303)
- 记录故障命中、进程退出、原身份接续、工具请求序列、实际生效数、交付状态和回执。实际生效超过一次判重复写入。完整通过要求故障命中、原身份接续、实际生效一次且只有一次有效交付，正文只包含与目标端原回执一致的编号。安全停住但未交付计为恢复未完成。启动或传输阻塞与未到达另计。
- 各用例在独立数据库、目录和目标端中执行。先校验评分器能区分写两次和只写一次，核对工具与原始状态，再用同一模型端点和模型名给每方各跑一次。每方单次等待上限 120 秒，每方恢复等待上限 120 秒，输出上限 32,768 tokens。仅补跑明确的评测接线故障，保留原证据。回执适配不作为正式发布数据集成绩。两边的恢复入口、原生提示及模型传输差异随报告归档。

## 运行结果

2026-11-20 修正评测器后完整复跑一组，双方都命中故障，进程退出和重启顺序均有记录。**personalAgent 未通过，DeepSeek Harness 通过。**

| Agent | 接续与执行 | 验收 |
| --- | --- | --- |
| personalAgent | 原 `turn_id` 恢复成功。Runtime 在首次恢复后的模型派发前重发 `apply_effect`，此后 Agent 查询目标端并返回第二笔写入的回执。目标端写入尝试 2 次，生效 2 次，最终交付 1 次。 | `valid-fail`，重复写入且未交付原回执。[结果](../../../.tmp/agent-durability-lab-20261120/comparison-151903577/personal-agent/result.json) · [恢复日志](../../../.tmp/agent-durability-lab-20261120/comparison-151903577/personal-agent/restart/web.log) |
| DeepSeek Harness | 新进程加载原 Session，原未决轮次记录为中断。续接轮调用 `read_effect` 后返回第一次写入的回执。目标端写入尝试 1 次，生效 1 次，最终交付 1 次。 | `valid-pass`。[结果](../../../.tmp/agent-durability-lab-20261120/comparison-151903577/deepseek-harness/result.json) · [恢复事件](../../../.tmp/agent-durability-lab-20261120/comparison-151903577/deepseek-harness/restart.jsonl) |

两边使用 `api.minimax.cn` 的 `MiniMax-M3.1-Flash`，最大单次输出 32,768 tokens。personalAgent 使用当前工作树及正式 Web，归档包含基线提交和实际源码摘要。DeepSeek Harness 使用固定检出的 `headless`，测试程序补交一句续接请求。结论限于这两个入口的实际行为，不能把差异归给单一因素。正式复跑共耗时 52.2 秒，personalAgent 记录 4 次模型调用和 33,997 tokens，DeepSeek Harness 恢复阶段 2 个完成步骤共 15,300 tokens，首次中断阶段用量缺失。[身份](../../../.tmp/agent-durability-lab-20261120/comparison-151903577/repository.json) · [校验清单](../../../.tmp/agent-durability-lab-20261120/comparison-151903577/checksums.sha256)

首轮 personalAgent 已出现两次写入。DeepSeek Harness 官方终态的 `reason` 是对象，初始解析漏记完成。按封存的终态事件重评后通过，原评分仍保留。第二组复跑遇到 Windows `GetTickCount64` 的 15.625 毫秒分辨率，写入与请求中断落在同一时钟刻度，双方故障记录判无效。该组流水仍观察到 personalAgent 两次写入和 DeepSeek Harness 一次写入。评测器改用 `QueryPerformanceCounter` 对应的高分辨率计时，并记录写入已提交、回复仍阻塞的屏障观察。[首轮原评分](../../../.tmp/agent-durability-lab-20261120/comparison-151337724/summary.json) · [封存重评](../../../.tmp/agent-durability-lab-20261120/rescore-151337724/deepseek-harness.json) · [第二组原评分](../../../.tmp/agent-durability-lab-20261120/comparison-151632240/summary.json)

## 修复复验

2026-11-20 修复后沿原用例再跑一组。双方均命中写入后、回执返回前的故障窗口，恢复到原身份，并各交付一个正确回执。

| Agent | 修复前的写入次数 | 修复复验 | 目标端流水 |
| --- | --- | --- | --- |
| personalAgent | 2 | `valid-pass`，原 `turn_id` 接续 | 首进程 `apply_effect` 一次，重启后 `read_effect` 一次，最终交付原回执。[结果](../../../.tmp/agent-durability-lab-20261120/recovery-fix-193258047/personal-agent/result.json) |
| DeepSeek Harness | 1 | `valid-pass`，原 Session 接续 | 首进程 `apply_effect` 一次，续接轮 `read_effect` 一次，最终交付原回执。[结果](../../../.tmp/agent-durability-lab-20261120/recovery-fix-193258047/deepseek-harness/result.json) |

personalAgent 的 SQLite 修订 12 已登记原写调用，尚无工具结果。重启后首次实发请求的第 5 条消息是原 `assistant` 调用，第 6 条是同一 `tool_call_id` 的 `tool` 消息。随后真实模型选择读取，目标端返回第一次写入的回执。[实发请求](../../../.tmp/agent-durability-lab-20261120/recovery-fix-193258047/personal-agent/restart/sdk/0ffb221147ad42b7adc1675ace20cb21.http.request.json) · [轮次轨迹](../../../.tmp/agent-durability-lab-20261120/recovery-fix-193258047/personal-agent/turn-trace.json)

> 恢复时未找到工具 durability.apply_effect 的原始执行结果，这次写入可能已经生效。先用只读工具核对目标系统的实际状态，核实前不要重发写入。无法核实时，向用户说明结果未知。

复验保持评测入口、题面、模型及目标端配置。personalAgent 计 4 次模型调用和 33,650 tokens，DeepSeek Harness 恢复步骤计 15,179 tokens，首次中断的用量仍未知。最终归档 62 个校验项及生产源码摘要已复核。一组先行实跑也已通过。用旧失败轨迹与先行实跑的 SQLite 快照副本回放，确认旧快照和已登记快照都拒绝重发原调用，同 ID 改摘要被拒，未知工具结果可进入现有受限交付分支。这些局部检查只覆盖对应状态和判断。[最终归档](../../../.tmp/agent-durability-lab-20261120/recovery-fix-193258047/checksums.sha256) · [先行实跑](../../../.tmp/agent-durability-lab-20261120/recovery-fix-192913912/summary.json) · [快照回放](../../../.tmp/agent-durability-lab-20261120/recovery-archive-replay-193258047-v2/report.json)

## 复跑入口

本次故障触发的生产修复及验收要求见 [普通 MCP 写调用的进程恢复](../../mcpDesign/README.md#普通-mcp-写调用的进程恢复)。

从仓库根运行。使用已构建的 [DeepSeek Harness 检出](../../../evals/deepseek-harness-deployment.md)，固定为 `2e39e70496aa02986ca6a820c5d497e816b69d7e`。personalAgent 使用 Docker 内的 PostgreSQL，模型由 `--model-env` 指定，默认读取 `.env`。

```powershell
.\.venv\Scripts\python.exe -B -X utf8 -m evals.Agent-Durability-Lab.run --collect-only
$run = ".tmp/agent-durability-lab-20261120/comparison-$(Get-Date -Format yyyyMMdd-HHmmssfff)"
.\.venv\Scripts\python.exe -B -X utf8 -m evals.Agent-Durability-Lab.run --scenario ambiguous-effect --output $run
```

默认运行双方。可以用 `--agent personal-agent` 或 `--agent deepseek-harness` 诊断单方。每次使用新输出目录，保留 `plan.json`、原始记录、逐方 `result.json` 及 `checksums.sha256`。
