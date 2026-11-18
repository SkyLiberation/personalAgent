# ADR 0055 统一 Conversation 答复提交

状态为采用，2026-11-15。生产实现、定向复跑与批次结果各按实际证据登记。

## 问题与依据

`canvas-list-test` 的真实复跑在成功读网页后开放 claim 选证工具，并从普通提交的枚举移除 `answer`。用户要求交付两份 CSV，网页工具的回执把答复变成了需要先选证和建立论断的流程。`find-alita-paper` 已下载评分接受的 PDF，随后两次选证参数被拒，未交付答复。LongDS Netflix Task 2 前两轮直接输出正文，引用列表为空，两次都通过独立的回答核验。用户决定移除 Conversation claim 模块并重跑 Toolathlon。[Canvas 实发请求](../../.tmp/ta-py2-1115/canvas-list-test/personal/product-data/interaction_runs/irun_f8bec9ac90cd44a1/7c10d7a574f2485f9f10a7d0244ef7ef/request.json) · [PDF 轨迹说明](../problems/toolathlon/research-loop-problems.md#goal计划和证据动作) · [LongDS 运行配置](../../.tmp/one-loop-ld/configuration.json)

## 需求和实现规格

| 需求 | 行为 |
| --- | --- |
| ANSWER-1 | Conversation 以完整正文或 `control_submit_final` 交付同一类 `FinalMessage`。在用户目标和计划允许交付时，读取网页不会移除普通答复入口。已发送的候选稿、模型反馈和最终正文仍由 Journal 记录。 |
| ANSWER-2 | 中英文主请求只说明统一的提交方式。普通答复默认直接输出正文。需设置限制、失败状态或绑定已读取的来源时使用结构化提交。引用可空，提交的坐标由 Runtime 核对。对答复的语义核验仍由现行结果核验开关控制。 |
| ANSWER-3 | 删除 Conversation claim 的选证、建稿、修订、核验、恢复、Schema、Prompt 和 writer 配置，包括正式评测入口的消费者。独立的研究实验交付检查、订阅研究和知识库论断继续使用其各自契约。 |
| ANSWER-4 | 升级后，同一数据目录下仍能开启新会话。Journal 按所有者和会话定位快照，再读取适用的业务 Schema。旧会话按原版本归档，续跑请求得到明确的版本不兼容结果。 |
| EVAL-1 | LongDS、Toolathlon 和后续新增的 Conversation 结果采集评测共用 `evals/conversation_http.py` 启动正式 Web 应用、检查就绪并提交 Conversation HTTP 请求。各数据集只拥有材料准备、运行调度、归档和上游评分适配。 |
| EVAL-2 | 本轮两套评测均使用 `goal_verification=false`、`answer_verification=false`。归档记录两项开关及 `unverified_flow_capture`，独立评分按各数据集的契约记录。生产核验按部署配置装配，默认开启。 |

Conversation 继续拥有模型循环、候选状态、适用核验及最终交付。复用已有直接答复的 Schema、解码和引用校验，AgentRuntime 在原装配点传入核验功能开关。普通正文的终态是 `answer`，结构化接口继续支持 `answer`、`limitation` 与 `failed`。工具回执和 Artifact 归原生产者所有，主模型直接据其写作。取消依据成功网页回执切换写作契约的条件及相应持久状态，可使同一交付职责只有一条正式路径。旧归档以原版本读取，新的评测从新会话开始。此前运行不可跨版本恢复，原路径以源码和配置归档为回退点。

## 验收

- **协议与上下文。** 先以已有 Canvas 和 GDP 实发请求固定旧行为。检查新请求继续提供正常答复，网页成功后也不声明旧选证工具与提示。检查中文和英文均说明引用是可选的，非法坐标仍由原校验拦截。执行源码导入、依赖和 Prompt 注册检查。
- **持久边界。** 使用封存的旧 Canvas 快照做只读回放，验证同目录可选择新会话，且读取旧会话时给出冲突。两边均不改写旧快照。
- **定向复跑。** 复用 `canvas-list-test` 与 `gdp-cr5-analysis` 的原题、环境与官方评分。分别记录正式答复、用户产物、评分和用量。Canvas 还核对网页读取后允许直接答复。未到达的阶段和失败保留原结果。
- **共享入口。** 核对两个数据集都经共用启动器启动正式 Web 应用，提交 Turn 并归档实际两项核验开关。现行路径为 `/api/conversation/turns`。原定向验证用原题和封存材料，记录实际候选、答复、用量及开关；关闭语义核验的采集标记为 `unverified_flow_capture`。[共用运行说明](../evals/04-running-and-release.md#conversation-评测共用入口)
- **批次复跑。** 按[上次清单](../../.tmp/tac1114/inventory.json)的 96 题重跑 personalAgent，沿用[上次归档身份](../../.tmp/tac1114/runs/identity.json)中的 MiniMax-M3.1-Flash、上游版本、官方评分器、64 轮、128 次工具调用、800 万 token 及 1,200 秒等待。定向实发请求确认新协议后，可并行调度独立环境。共享服务等定向运行结束后再串行调度。只纳入同源码和配置身份的结果。历史官方结果提供参照，Canvas 的官方参照使用已完成的评测材料隔离复跑。Google Cloud 和 Snowflake 的 12 题保持暂缓。分别报告有效评分、答复、用量和环境失败。批次证据只覆盖本次配置。

## 实施与证据

生产侧已删除 claim 路径和写作切换配置，中英文 Prompt 均声明统一提交及可选引用。LongDS 和 Toolathlon 共用正式 HTTP 评测链路；新增会话评测遵守[评测入口规范](../../evals/AGENTS.md#2-canonical-owner-与写入口)。旧 Canvas 快照与新 LongDS 快照的只读回放确认，同目录可打开新会话、旧会话恢复显式冲突，原始文件校验和保持一致。

LongDS 定向验证两轮均返回正式答复，实际发送 7 次模型请求，记录 142,063 token。两类语义核验均关闭，未运行独立评分。共享启动器按记录确认真实 Web 进程已经退出。[LongDS 采集报告](../../.tmp/td1115/ld-pilot/report.json)

Toolathlon 定稿批次已封存 96 题。`find-alita-paper` 验证网页读取后仍能直接交付。最新的评分、正式答复和阻塞项见[运行结果](../problems/toolathlon/agent-comparison.md#运行结果)。定向调试报告保留原运行版本，可作为启动和路由检查，批次分子只取定稿源码指纹的运行。
