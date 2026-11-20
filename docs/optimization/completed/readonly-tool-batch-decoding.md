# 只读工具批次按调用处理参数错误

2026-11-20 已实现并完成局部 Offline Eval。以前，一条工具参数拒绝会让同批合法读取也退出解码。现在，符合条件的读取分别处置，合法动作走原准入和预算，参数错误在原调用 ID 下反馈。

## 失败与责任

Toolathlon `student-interview` 第 10 步的真实响应同时请求搜索笔记、列出笔记和查询图谱。原声明下前两项参数合法，图谱调用违反 Schema，整批零分发。第 11 步按原参数重提并实际执行列出笔记。 `update-material-inventory` 第 20、21 步也各有一条合法的列出笔记被同批参数错误阻断。最早责任是 Conversation 的应用层动作解码。 [面试归档](../../../.tmp/tac1114/window-20261114-195121/student-interview/personal/report.json) · [库存归档](../../../.tmp/td1115/window-20261115-214408/update-material-inventory/personal/report.json)

## 采用方案

DeepSeek Harness 在 Base 装配原生执行器，使用当步工具集合派发。 `defineTool` 校验单个工具的参数，批处理把各自结果按原 ID 和顺序提交给会话。本工程借鉴逐调用处置，并使用现有 Capability Projection 确定适用范围。只有正式请求中已声明、当前只读、可安全重试且允许只读探索的普通工具满足条件。任一动作涉及控制、委派、写入或文件读取转入 Bash 时，继续执行原批次约束。未知名称、重复 ID、不可配对的响应和全无效批次也沿原拒绝出口。 [DeepSeek Harness 执行批次](https://github.com/deepseek-ai/deepseek-harness/blob/2e39e70496aa02986ca6a820c5d497e816b69d7e/packages/core/tools/src/batch.ts#L50-L104) · [单调用 Schema 校验](https://github.com/deepseek-ai/deepseek-harness/blob/2e39e70496aa02986ca6a820c5d497e816b69d7e/packages/core/tools/src/schema.ts#L578-L602) · [原 ID 回填](https://github.com/deepseek-ai/deepseek-harness/blob/2e39e70496aa02986ca6a820c5d497e816b69d7e/packages/core/tools/src/batch.ts#L252-L267)

应用层解码复用原始声明和严格校验。一个临时类型保留按调用顺序排列的合法 Proposal 或参数反馈。Conversation 通过原执行入口让合法成员通过 Admission 和预算，再把结果和参数拒绝一起提交至 Journal。原生历史投影继续按调用 ID 配对，使用已有字段诊断。工具和权限声明、持久格式、目标与计划前置条件沿用现有实现。 [动作解码](../../../src/personal_agent/application/conversation/model_actions.py) · [派发和提交](../../../src/personal_agent/application/conversation/service.py) · [模型可见反馈](../../context/runtime-feedback.md#1-反馈进入-context-的位置)

代码复核补充两个验收边界。若已记录的模型费用或运行截止使派发停止，原预算出口在结束本轮时同时提交每个 ID 的结果。参数错的调用保留自己的拒绝，其余调用记录预算拒绝。简短的纯类型修复也应保留该调用未执行的说明。用同一完整真实响应和已经用尽的提交预算核对前者，以仅产生类型诊断的变体核对后者。变体只作为确定性反例。

## 验收与边界

使用 `.venv\Scripts\python.exe .tmp/readonly-tool-batch-20261120/replay.py` 分别运行 `--expect whole` 和 `--expect partial`，输出到独立报告。完整的历史 Port 请求和 Provider 原回复通过原校验进入当前解码、应用准入、预算、结果提交与历史投影。只读知识数据库由记录型实现替代，校验调用身份与实际分发次数。原件 SHA-256 已随报告保存。模型调用与真实工具服务调用均为 0。 [回放脚本](../../../.tmp/readonly-tool-batch-20261120/replay.py) · [基线](../../../.tmp/readonly-tool-batch-20261120/baseline.json) · [最终目标](../../../.tmp/readonly-tool-batch-20261120/target-final.json)

三份真实混合响应在基线全部拒绝，合法动作分发为 0。目标分发 4 次合法读取，3 次错误图谱调用均零分发，并按原 ID 保留字段诊断。Journal 序列化后重读得到同样的调用、结果顺序和配对。历史合法重提及含写入混批分别沿原执行和拒绝路径。六个确定性反例均通过，包括工具不再可用、重复 ID、独占调用、工具次数耗尽、模型回复后总预算耗尽和纯类型错误反馈。审查前的候选在后两项分别出现历史缺失配对和未执行说明缺失，已修复并重跑。

局部结果证明合法只读调用可继续分发及配对。两道原题的整例评分沿用原归档。回放覆盖已提交 Journal 的重读，进程在提交前退出的恢复、整例效果、轮数和时延未验证。既有重复失败计数受同批成功与拒绝写入顺序影响。后续真实轨迹若再次出现同类独立读取被错误参数连带阻断，以新轨迹重新打开此项。
