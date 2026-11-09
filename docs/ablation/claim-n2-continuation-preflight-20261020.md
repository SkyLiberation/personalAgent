# N2 首稿的恢复预检

日期：2026-10-20。身份：`claim-n2-continuation-preflight-20261020-v1`。结论：**原状态和完整组反馈消费输入可以恢复；直接接续实验尚未就绪。** 新增被测模型、writer、评分器调用为 0，生产改动为 0，未执行 A4 或 A5。后续设计由[CLM-02](../optimization/to_verify/research-goal-coverage.md#clm-02-n2-恢复预检)拥有。

N2 是学校体育政策与公开调查任务；首稿指原归档的 `N2-first`。其来源为正式 `POST /api/conversation/turn`，运行 `irun_9e6a96d411cb4052`。本轮只读核对旧数据，并在隔离目录使用逐字相同的原源码执行确定性物化、准入和请求构造。

## 已实际核对

| 核对项 | 结果及边界 |
| --- | --- |
| 原文件身份 | 140 个本次消费的原归档文件哈希一致；262 个封存生产源码文件与原身份清单及 ZIP 一致 |
| 研究状态 | Journal 快照 5 包含研究版本 1、六条 claim 和五段回答；七个完整阶段输入字段与 `N2-first` 完全相同，包含会话、要求、两稿、原文和读取状态 |
| 首稿实际生成链 | 消费原选证响应和 writer 响应，经原选证坐标解析与版本准入，重建结果与快照中的研究版本逐字段相同；16 个选证坐标保持 |
| 原反馈后的消费者 | 从原 Journal 快照 7 构造下一次选证请求，其消息与实际 SDK `0011-request.json` 的两条业务消息一致，输出 Schema 一致；SDK 另有一条原适配器生成的 Schema 系统消息 |
| 完整组本次反馈 | 七条实际 finding 均通过原结构、定位和引用范围检查，原样进入同一选证消费者，反馈引用十条原文；下一请求已封存，未发送 |
| 移除组本次反馈 | 空报告保留独立消融版本。原完整契约的适用性检查拒绝复用该版本；本轮没有把它改写成完整组的通过记录 |
| 截断资料资源 | `artg_143d63e6e90ef8d62b16` 的 34,853 字节正文、摘要、owner 和版本可恢复，内容摘要与原记录一致；本轮检查文件没有使研究轨迹中的未读状态变成已读 |

可复查的[结果数据](claim-n2-continuation-preflight-20261020.json)、[完整组下一选证请求](../../.tmp/claim-n2-continuation-preflight-20261020/full-next-selection-request.json)、[完整组原报告](../../.tmp/claim-n2-continuation-preflight-20261020/full-report-origin.json)及[移除组原报告](../../.tmp/claim-n2-continuation-preflight-20261020/no_claim-report-origin.json)均已封存。协议检查通过不代表七条反馈语义全对；其中的答案问题、claim 独有问题、同步和未决项仍按[完整 AI 初审](claim-complete-review-20261020.md)分别解释。

## 直接续跑还缺什么

**必须恢复首次核验后的执行位置。** 原 `ConversationService.respond()` 读回 Journal 后，将局部变量 `finalization_pending` 初始化为 `False`；Journal 保存事实，没有保存这个进程内位置。直接恢复快照再调用 `respond()`，会先回到动作决策，不能当作原 writer 修订入口的精确接续。本轮已核对原源码及 Trace 字段，尚未实现隔离续跑驱动，也未检验新的恢复控制流。

**两臂须分别绑定核验契约。** 完整组为 `v36-preserve-execution-results`，移除组为 `v36-preserve-execution-results+ablation-no-claim-v1`。后续每版核验、报告适用性和完成判断都须消费本臂身份；只移除第一次输入，再使用生产完整组的后续核验，会改变比较变量。隔离实现需要保留这一区别。

**空报告不能直接计为交付。** 首稿已有一份尚未重读的截断资料。原完成检查会要求从本轮持有的资源读取窗口，模型再决定内容是否有用；该边界适用于两臂。原轨迹在研究版本 2 得到空报告后，仍被这道检查拦截并继续取证。本轮没有提前注入后期工具动作或其结果。

当前的 `research.py`、`service.py`、Journal、writer 和研究 Prompt 等消费者已经与历史源码不同。旧输入直接跑现行链不能作为原比较的同身份续验；详细差异路径保存在结果数据，均为本轮开始前已存在的工作树变化，本轮没有修改这些文件。

## 历史成本与可复用范围

只统计 SDK 中带 `kwargs` 的物理请求；26 个响应 ID 唯一，排除逻辑请求的重复日志，与原 Trace 和 receipt 总量一致。逐项见[物理调用账本](../../.tmp/claim-n2-continuation-preflight-20261020/physical-call-ledger.json)。

| 范围 | 物理调用 | 已知 tokens |
| --- | ---: | ---: |
| 原 N2 完整任务 | 26 | 1,319,578 |
| 首次原核验之后 | 20 | 1,127,833 |
| 首次选证—修订—复验周期，含一次结构恢复 | 4 | 186,426 |
| 本轮恢复预检 | 0 | 0 |

原整例耗时 3,338.313 秒，约 55.6 分钟；没有另行封存首次核验之后的独立墙钟耗时，该项保持未知。旧两臂首稿报告合计 230,986 tokens，属于已有核验成本，不冒充新续跑成本。

原生产首次报告有三条 finding，而本次完整组重放有七条。后续旧修订消费了原三条报告；**不能把那些真实修订拼接为消费七条报告后的 A4 成绩。** 后期原文、选证和模型输出也不作为新轨迹的预设结果。

下一步仍是基于同一初始事实，消费各臂实际反馈，经过真实修订与各臂复验，检查初始四个答案问题是否消除、九项原要求是否保留以及有无新增错误。独立人工复核、完整闭环收益、净成本和产品用户结果均未验证。预算和停止线在唯一 Spec 中列为候选上限，隔离驱动与执行身份完成前不启动 live 配对。

## 归档与检查

归档目录为 `.tmp/claim-n2-continuation-preflight-20261020/`。原源码解包保持逐字相同；最初直接从 ZIP 导入时无法解析 namespace 包，已保留零模型调用的探测记录，改用未经修改的解包源码后完成本轮核对。

```powershell
.\.venv\Scripts\python.exe -X utf8 .tmp/claim-n2-continuation-preflight-20261020/preflight.py
.\.venv\Scripts\python.exe -X utf8 .tmp/claim-n2-continuation-preflight-20261020/preflight.py verify
.\.venv\Scripts\python.exe -m ruff check --select F401,F811,F821 .tmp/claim-n2-continuation-preflight-20261020/preflight.py
```

第一条为已执行的封存命令，拒绝覆盖已有结果；日后复查使用第二条。原始文件由[来源清单](../../.tmp/claim-n2-continuation-preflight-20261020/source-checksums.json)核对，新增数据和脚本由[输出校验和](../../.tmp/claim-n2-continuation-preflight-20261020/checksums.json)保护。Ruff、归档校验、文档链接与锚点、空白检查及 `scripts/check_dev_spec.py` 均通过；工程规范检查为 69/69 条主路由、9/9 条目录路由。前次完整 AI 初审的八项数据与脚本校验和保持，旧成绩未改。未新增或运行单元测试、产品 E2E 或被测模型。
