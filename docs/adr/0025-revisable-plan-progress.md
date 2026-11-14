# ADR 0025：将可修订的 Plan 进度与执行、交付事实分开

- 状态：局部机制已接入；真实入口诊断主动停止、未交付，完整产品验收未通过
- 日期：2026-09-16
- 问题与证据：[拒稿恢复循环 §108](../optimization/revision-feedback-loop.md#108-plan-生命周期整体修正)
- 前序：[ADR 0016](0016-separate-plan-control-from-action-execution.md)、[ADR 0017](0017-separate-action-selection-from-final-delivery.md)

## 2026-11-11 修订：可读写的进度清单

现有调用在每次修改时要求完整回传清单，新建清单还默认进入用户审阅。两者把持续记录进度和等待用户合在同一个操作中。选用[归档原生计划调用](../../.tmp/ns27/c/sdk/b0f351c763b54cb4a7c798eef1112519.candidate.response.json)核对既有完整提交的兼容性。

采用 Hermes 的读写方式和规则落点。空参数读取当前清单，提交 `steps` 默认替换当前清单，`merge: true` 按步骤 ID 更新和追加。常规创建和更新继续执行。工具描述说明何时维护、如何更新、何时等待。当前计划由 Journal 恢复并直接进入主请求，压缩后只投影待办和进行中项。新读写回执绑定调用当时的完整清单和版本，沿原生工具消息投影。业务进度和工具执行事实各自保持原身份。[Hermes 读写](https://github.com/NousResearch/hermes-agent/blob/f19432adb7ac4aa2920797a7d092d3987012d4b2/tools/todo_tool.py#L26) · [Hermes 压缩后的清单](https://github.com/NousResearch/hermes-agent/blob/f19432adb7ac4aa2920797a7d092d3987012d4b2/agent/conversation_compression.py#L2980)

产品继续提供可审阅计划。模型依据用户要求选择 `wait_for_user`，适用的审阅阶段由 Runtime 校验。保留计划 ID、已提交的执行绑定、最终答案验收和已接纳交付后的计划结算。调用方可继续传原交互模式字段，普通清单的推进统一使用工具参数。

验收先回放既有原生调用，再核对空参数读取、替换、合并、重复读取与写入、同批执行、显式等待、拒绝及压缩后的主请求。以实际请求核对双语工具说明和当轮声明。离线检查只证明确定性路径，模型选用清单的频率和整例用户结果另行验证。

本轮中英文离线回放通过归档调用、空清单、版本化回执、替换与合并、压缩后活动项投影、同批执行及中断续跑检查。显式审阅在同一运行重试时返回原待审计划。一次真实原生决策选择了 `control_working_plan`，提交 6 项和 `wait_for_user: true`，共 3,965 tokens。本次真实请求验证了明确要求审阅时的单次工具选择，完整 Product E2E 尚未执行。[离线回放](../../.tmp/local-tool-schema-doc-20261111/replay_working_plan.py) · [真实请求检查](../../.tmp/local-tool-schema-doc-20261111/live_plan_check.json)

## 1. 失败与统一责任边界

正式研究用例在模型把三项进度全部标记完成后，连续三个有效读取或搜索提议被
`working_plan_terminal` 拒绝，最终未交付。此前自然语言最小对照仅通过 1/2 状态，
不能解决状态约束。本候选恢复根规范“Plan 只表达工作状态，执行与完成分别判定”的边界。

模型拥有可修订的步骤进度；Conversation Admission 唯一接纳修订。执行网关拥有不可改写的
ActionObservation。Journal 中已接纳的 answer 才是最终交付事实。步骤 completed 不得同时充当
工具禁用条件、不可修订证明和新计划审阅边界。相关约束必须在同一候选中替换，否则恢复链仍受旧约束阻塞。

## 2. 整体决定与生产链

正式 Conversation 入口 → ConversationService → Plan Admission / Journal → 原执行网关 →
prepare_final → FinalMessage → 原 Verification / Completion。

1. 步骤可因新证据或拒稿反馈重开、修订；历史快照和执行事实保持原样。
2. Admission 保留步骤 ID 唯一、最多一个活动项、等待审阅不得执行。删除“无活动项或全部完成
   则禁止工具”的分支。执行系统有 canonical 活动项时关联它，否则记录空关联，不猜测步骤。
3. 同一未交付任务的 Plan 修订保持身份，不因 completed 重开新计划；新计划边界通过同一身份、
   会话范围内的已接纳 answer 查询确定，不由 goal 文字相似度或步骤状态判断。
4. 进度完成不自动调用 Final、不自动通过 Verifier。拒稿后模型可以直接补证或重开步骤；
   仅通过原答案门禁才交付。新计划的现行审阅规则见本页修订。
5. 模型输入以中文说明当前进度、可修订性与交付区别，统一替换矛盾的不可重开指令。
   保留来源读取、引用、缺项分类、权限与预算约束。

上述决定替代 EXE §2.1 的强制活动项执行门禁、§2.2 将拒稿描述成步骤必为未完成的措辞，
以及 ADR 0016 对应历史迁移规则。根规范的 FinalMessage 验收边界保持不变。

## 3. 外部机制比较

已核对的两个独立 A 级源码及构造、消费者和生命周期比较集中在
[§106](../optimization/revision-feedback-loop.md#106-plan-完成状态与继续执行的源码对照)。

- Gemini CLI，提交 `3c311beac2e78336816dd4a123db39743f9fbf85`，
  `packages/core/src/tools/write-todos.ts` 与 `scheduler/scheduler.ts`：进度可替换，普通工具不受全部完成门禁控制。
- OpenHands，0.59.0，提交 `d39f7ae0e66174c50bdc714304fed4078b5e3b72`，
  `tools/task_tracker.py`、`runtime/base.py` 与 `tools/finish.py`：任务列表更新和显式结束分离。

只采纳职责分离；不复制其持久文件、控制器、工具数量，也不据此宣称本工程有效。

## 4. Complexity Justification 与排除项

复用当前 Plan、执行网关、Journal 和最终交付相位；只增加对既有已交付事实的查询消费者，
不增加持久字段、状态、Agent、循环、权限、预算或配置。删除终止 Plan 工具门禁、完成步骤不可改写
分支和按步骤完成重建 Plan 的推导。现有执行关联与历史档案保留，不作存储 Schema 迁移。

未采用：自动把第一个步骤重开、工具成功自动完成、全部步骤完成自动 Final、靠补提示维持旧门禁、
扩大预算或复写失败分类。这些方案不能建立同一清楚的责任边界。

## 5. 证据、迁移与退出

整体候选作为一个责任边界修复验证，不把多条独立随机模型轨迹当作消融。先执行旧快照的确定性
反事实，再验证重开、无活动项执行、审阅、跨进程恢复、拒稿后补证、合法 Final 和执行事实保持。
真实模型最小样本验证实际动作选择，原正式研究用例固定中文用户目标与原断言，首次运行不挑选重跑。

若修订破坏身份范围、用户审阅、执行事实或 Final 验收，撤回对应候选；若原失败仍发生在本责任
边界，停止局部叠补并重新审查整体设计。检查点后独立语义错误保留为产品阻塞，不否定已成立的
Plan 机制；任何局部通过均不等于产品完成。具体预声明与实测结果由 §108 单一维护。已执行 203 项回归、两条真实模型决策和正式链中 completed 状态下三次成功补证；原样本因五稿重复同一无据缺项句主动停止，不能作为 E2E 通过。
