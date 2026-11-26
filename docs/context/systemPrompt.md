# Conversation 主循环的 System Prompt

Conversation 主模型的首条 `system` 消息由主决策模板、当前任务的工作规则和按配置启用的提示组成。工具名称和参数定义位于请求的 `tools`，用户消息、当前目标和执行回执沿各自的消息路径进入请求。本文说明主决策请求 `agent_interaction_turn` 的组成。各核验任务的独立提示见[模型任务上下文索引](README.md)。

## 首条系统消息的组成

`ConversationService._build_decision_request()` 先计算本步可用工具，再构造首条系统消息。运行时将下列区块拼成一条 `system` 消息，顺序和出现条件如下。[请求构造](../../src/personal_agent/application/conversation/service.py) · [主模板渲染](../../src/personal_agent/application/conversation/interaction_prompt.py)

| 顺序 | 区块 | 内容与出现条件 |
| --- | --- | --- |
| 1 | 主决策模板 `conversation.action` | 始终使用。说明交付、原生工具调用、输入边界、工具执行、证据和当前能力。展开顺序见下一节。 |
| 2 | 当前任务的工作规则 | 启用 Goal 时追加 `conversation.analysis.task`。关闭 Goal 时追加 `conversation.analysis.direct_task`，根据用户原话、适用历史和实际结果继续工作。 |
| 3 | 无人值守提示 `conversation.test_mode` | 回答测试模式开启时追加。说明可由工具弥补的信息缺口应继续处理，无法推进时报告限制或失败。模式同时影响可用工具。 |

中英文共享区块名称和构造顺序。Runtime 按部署语言从 Prompt Catalog 选取正文，各模板独立版本化。[中文 Conversation 模板](../../src/personal_agent/kernel/prompt_templates/conversation.py) · [英文 Conversation 模板](../../src/personal_agent/kernel/prompt_templates/en/conversation.py) · [测试模式模板](../../src/personal_agent/kernel/prompt_templates/result_feedback.py)

### 主决策模板内部顺序

| 区块 | 职责 |
| --- | --- |
| 目标与输出 | 说明何时调用工具、何时交付完整 Markdown，以及如何用状态工具报告限制或失败。 |
| 研究交付要求 | 运行绑定检索实验部署时插入 `conversation.research_entry.explicit`，说明实验、材料冻结和报告交付的协作方式。 |
| 原生动作协议 | 要求按本次声明的名称和参数调用工具。 |
| 输入边界与验收 | 说明如何使用用户原话、计划、工具回执和拒绝反馈。普通会话根据回答核验开关插入相应说明。绑定检索实验部署时使用该入口的研究交付要求。 |
| 工具执行边界 | 说明使用可见能力、根据拒绝反馈修复，以及如何区分计划、权限和执行事实。 |
| 取证与读取 | 说明如何获得和使用实际证据，如何理解预览、截断和续读。 |
| 运行数据 | 插入当前能力的选择约束，例如计划审阅前允许使用的工具、可能写入的动作和委派允许的范围。 |

运行数据从本步最终动作声明和有效能力构造。部署装配、权限、工具组、目标阶段、执行控制或预算使可用动作变化时，这段文字可能随之变化。工具参数类型、必填项及具体调用方式由各自的工具声明提供。[能力规则投影](../../src/personal_agent/application/conversation/model_actions.py) · [当前工具契约](tool.md#当前本地工具列表)

个人知识与委派的调用说明由各自的工具描述承载。工具关闭或当前阶段未声明时，这些说明随工具一起退出请求。复用 LongDS Task 3 同一步历史检查正式请求构造。关闭这些能力时，首条系统消息由 12,008 字节缩至 9,771 字节，9 项业务和控制工具声明逐项一致。启用知识和委派时，中英文请求均从对应工具描述提供调用说明。[清理前的实发请求](../../.tmp/nyc3u-1120/c/sdk/2efc03d42dd442e5bfe5b4026af033b0.http.request.json) · [三组请求回放](../../.tmp/longds-tool-guidance-20261121/report.json)

目标维护的通用操作说明由 `submit_goal_patch` 的工具描述和参数 Schema 承载，覆盖每轮开始、执行中修订、任务选择、引用与接受条件。当前目标、可选任务和待澄清事项是 Runtime 提供的状态。LongDS 封存请求的待维护与已接受阶段回放确认，工具可见条件与补丁 Schema 一致。另核对了中英文在两种目标核验配置下的工具描述，三份原补丁均能绑定跨轮引文。[原始首步请求](../../.tmp/nyc3u-1120/c/sdk/85e6d359c0004c1f8923b38c12a5431d.http.request.json) · [目标工具回放](../../.tmp/longds-goal-tool-description-20261121/report.json)

## 其他输入的位置

| 内容 | 所在位置 |
| --- | --- |
| 用户原话 | 原话沿 `user` 消息接续。模型通过[附件访问入口](tool.md#会话附件)发现和读取用户上传的文件。 |
| 当前目标与任务选择 | 装配 Goal 时，Runtime 用有标题的 `user` 消息提供当前目标。需要维护且本步声明目标动作时追加任务选择。关闭模式沿用普通用户历史。 |
| 已有决策与回执 | Provider Adapter 按历史位置接续 `assistant` 调用和配对的 `tool` 回执。工具定义单独序列化到请求的 `tools`。 |
| 本步计划恢复与技能目录 | 有接续信息或可用技能目录时，用请求末尾的 `user` 消息承载。 |
| 压缩恢复与运行反馈 | 需要定位压缩覆盖的原件时，Runtime 可追加独立的 `system` 消息。未随原生交换接续的拒绝原件，以及 Adapter 投影的部分运行反馈，也可占用独立的 `system` 消息。 |

首条系统消息中的能力约束可以随可用动作变化。目标正文和步骤接续信息由后续消息承载。配置和可用能力相同的相邻步骤可以接续原有前缀。缓存实际命中率由服务方用量单独记录。[主循环接续顺序](agent-loop.md) · [Provider 序列化](../../src/personal_agent/infra/structured_model.py) · [反馈位置](runtime-feedback.md#1-反馈进入-context-的位置)

## LongDS 请求示例

Task 3 首步使用英文模板和无人值守模式。回放生成的 `messages[0]` 以这段实际正文开头，其余系统指令省略。

```text
## Goal and output

Advance the necessary work for the user's current goal and ultimately deliver a complete result.
……
```

该历史样本的 `messages[1]` 是原题。后续 `user` 消息提供当前目标、任务选择和本步预算。首步的 `tools` 只有目标补丁和状态报告。第 34 轮第 5、6 步使用同一工具集，离线回放核对了两步预算不同、首条系统消息及工具定义逐字一致。[首步系统消息](../../.tmp/longds-system-prompt-audit-20261121/turn01-step1.system.txt) · [三步构造回放](../../.tmp/longds-system-prompt-audit-20261121/report.json)
