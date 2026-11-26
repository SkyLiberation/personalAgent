# Skill 的发现、加载与上下文

Runtime 在启动时读取部署配置的技能目录。主模型先在 Step Context 看到当前会话可用的名称和描述，再按任务需要调用 `tool_load_skill`。成功的正文随原调用进入工具历史，后续请求按历史可见性和容量重建。下文描述运行时行为，仓库维护任务使用的上下文管理方法见[上下文索引](README.md)。

## 1. 部署与可见范围

| 来源 | 安装位置与绑定 |
| --- | --- |
| 工程级 `project` | `PERSONAL_AGENT_SKILL_SCOPES.projects` 将绝对工程根绑定到认证主体与 `session_id`。 |
| 用户级 `user` | `PERSONAL_AGENT_SKILL_SCOPES.users` 将绝对主目录绑定到认证主体，供该主体跨会话使用。 |
| 部署打包 `bundled` | `PERSONAL_AGENT_SKILL_ROOT` 指定实例级只读目录。仓库随包目录为 `src/personal_agent/bundled_skills`，启用时显式配置。 |

工程级和用户级绑定要求主体已配置 Web 认证密钥。已认证的 Web 会话依次查工程级、用户级、部署打包。其他入口只查部署打包。工程根和用户主目录内部依次查 `.dsh/skills`、`.agents/skills`。同名项以优先级最高的定义为准，再检查 `disable-model-invocation: true`。若胜出项禁止模型调用，该名称从目录移除，下级同名项不会递补。[部署配置](../env.md) · [作用域 ADR](../adr/0057-conversation-skill-scope.md) · [目录合并实现](../../src/personal_agent/application/conversation/skills.py#L68-L94)

每个技能安装为 `<name>/SKILL.md`。扫描读取根目录的直接子目录中的 `SKILL.md`，文件采用 UTF-8，最大 64 KiB。YAML frontmatter 的 `name` 必须与目录名相同，`description` 及其后的 Markdown 正文均需非空。加载器校验目录和技能文件的链接限制。Runtime 启动时固定清单和正文，文件变更在重启后生效。存在工程级或用户级绑定时，Journal 保存作用域目录摘要。恢复或继续已有会话时若摘要变化，Runtime 要求新建会话。该摘要记录目录作用域，正文更新仍遵循启动快照。[文件加载](../../src/personal_agent/infra/skill_files.py) · [会话作用域校验](../../src/personal_agent/application/conversation/service.py#L571-L580)

## 2. 模型请求与工具回执

1. **注册和筛选。** 配置中存在可由模型调用的技能时，组合根注册只读工具 `load_skill`，主模型看到的调用名是 `tool_load_skill`。是否展示由 `skills` 工具组、`skills:read` 权限、当前会话可见目录、目标阶段、执行控制和预算共同决定。[组合根](../../src/personal_agent/orchestration/runtime.py#L430-L437) · [工具准入](../../src/personal_agent/tools/load_skill.py) · [Conversation 工具列表](tool.md#conversation-的本地工具)
2. **披露目录。** 工具可用时，主请求末尾的 Step Context 以 `user` 消息携带 `<available_skills>`，每项只有 `name` 和 `description`。固定工具描述要求用户点名或任务明确匹配时先按名加载。参数 Schema 只声明 `name` 的形状，随会话变化的目录留在 Step Context。[请求构造](../../src/personal_agent/application/conversation/service.py#L2417-L2441) · [工具说明](../../src/personal_agent/kernel/prompt_templates/skills.py)
3. **按名执行。** 模型以 `{"name":"<技能名>"}` 调用。工具用派发携带的认证主体、会话和入口重新查同一目录，成功的内部结果含 `name`、`instructions`、`source`。名称不可用时返回“该技能不可用。请核对当前会话技能目录中的准确名称。”[加载实现](../../src/personal_agent/tools/load_skill.py#L12-L38)
4. **回送正文。** 主循环把完整 Markdown 放入 `<skill_instructions>`，在下一次请求以 `tool` 消息和原 `tool_call_id` 配对。技能提供执行说明，引用的配套文件和命令由模型通过获准工具处理。Runtime 按既有规则决定工具权限、Goal、核验与交付。模型按用户原话判断是否满足技能例外，证据不足时采用技能的默认规则。[正文渲染](../../src/personal_agent/application/conversation/interaction_projection.py#L101-L109) · [模型消息配对](../../src/personal_agent/infra/structured_model.py#L309-L327)

### 2.1 随包脚本

已有 Bash 执行许可且工具组启用时，成功加载技能会准备该技能包 `scripts/` 下的普通文件，包括同目录依赖。Runtime 保存确切字节。原工具回执在正文前通过 `<skill_resources>` 提供容器内的只读资源根。普通模式与任务工作区使用 `/workspace/skills/<name>/<摘要>`，共享工作区使用 `/run/personal-agent-inputs/skills/<name>/<摘要>`。相同名称和文件内容得到相同目录。目录按 Bash 相对路径规则校验，文件总量沿用现有 64 MiB 输入上限。[资源读取](../../src/personal_agent/infra/skill_files.py#L87-L117) · [不可变发布](../../src/personal_agent/application/conversation/skills.py#L50-L70)

模型用该资源根解析相对路径，随后单独提交 `tool_bash` 命令，例如用容器内的 Python 运行 `<资源根>/scripts/report.py`。Bash 从当前任务已提交的加载回执冻结输入。一次批次中同时提交的新加载与 Bash 调用仍以该批开始前已提交的资源为准。命令执行、授权、超时和恢复继续走 Bash 的原契约。资源准备失败时，回执明确报告技能脚本不可用。[Bash 输入选择](../../src/personal_agent/application/conversation/journal.py#L808-L853) · [设计与验证](../adr/0058-skill-script-resources.md)

## 3. 重复调用与提醒

| 调用情形 | 回执与反馈 |
| --- | --- |
| 同一批或不同步骤，用不同合法 ID 读取同一技能 | 每个获准并成功执行的调用都从进程目录取正文，产生自己的完整回执。多个回执可以同时保留在模型历史中。 |
| 同一批出现相同调用 ID | 原生动作协议拒绝该批次。 |
| 当前运行内再次使用已提交的调用 ID | 准入返回 `duplicate_action_id`，本次调用未执行。 |
| 当前用户轮次的可见历史中，连续第 3、5、8 次成功加载同名技能 | 原正文回执照常返回。Runtime 在触发批次的工具结果之后附加独立的 `system` 提醒，供模型查看最近回执并判断下一步。 |

提醒按可见原生回执的调用顺序推导，计数以本次用户轮次为界。不同技能、其他动作、工具调用失败或拒绝以及用户补充输入都会断开这段连续计数。每次成功加载仍经过正常权限和工具预算。[同批准入](../../src/personal_agent/application/conversation/service.py#L3077-L3118) · [同批调用 ID 校验](../../src/personal_agent/application/conversation/model_actions.py#L576-L582) · [已提交 ID 校验](../../src/personal_agent/application/conversation/service.py#L3218-L3244) · [提醒投影](../../src/personal_agent/application/conversation/model_history.py#L208-L322)

## 4. 历史裁剪、摘要与重读

- **目录按当前请求生成。** 加载工具仍可用时，名称和描述会再次进入 Step Context。目录披露独立于旧工具历史，已加载正文沿普通原生工具回执接续。
- **旧正文可先被裁剪。** 上下文达压时，符合条件的旧回执超过 8,192 个 Unicode 码点，可只保留前 4,096 和后 1,024 个码点，并标明省略量。最近两次已结算主决策受保护。此处计量的是渲染后的工具回执。工作摘要读取相同的短版及原调用 ID，已有的 `<skill_resources>` 仍在回执头部。[裁剪实现](../../src/personal_agent/application/conversation/history_tool_pruning.py) · [摘要取材](../../src/personal_agent/application/conversation/history_compaction_source.py)
- **摘要覆盖后，旧调用、回执及提醒退出模型请求。** 工作摘要概括旧交互，完整技能正文可以从 Journal 和覆盖该回执的历史快照追溯。当前读搜工具可用时，Runtime 按快照提供原件定位。技能仍可见时，模型也可以按名称重新加载。重复提醒按当前可见历史重新推导。[历史压缩规则](context-management.md#1-历史压缩) · [快照原件定位](agent-loop.md#31-压缩后如何定位工具原件)

单次回执大小和历史裁剪分别检查。技能文件可达 64 KiB，但序列化后的工具回执超过 50 KiB 会走通用外置。技能的原生渲染仍要求 `data` 中有完整正文，因此该边界可能使下一次主请求构造失败。这是源码可见的实现限制，已有实发样本未覆盖超长技能。[回执上限](tool.md#1-触发条件) · [外置处理](../../src/personal_agent/application/conversation/service.py#L3491-L3553) · [技能渲染](../../src/personal_agent/application/conversation/interaction_projection.py#L101-L109)

### 4.1 与 DeepSeek Harness 的压缩对照

固定提交 `4b399c39a6d1479cd84ca591b4d7c88e24d38a96`。DeepSeek Harness 在步前按当前作用域生成 Skill 目录，目录被摘要遮蔽后重新发布。成功加载的正文和资源信息属于普通工具结果，适用统一裁剪和摘要范围，最近保留区间内按原调用配对。其摘要从当前可见历史投影取材，已裁剪的结果以短版进入摘要；原事件继续保留，后续需要完整正文时可以按名重载。[目录恢复](https://github.com/deepseek-ai/deepseek-harness/blob/4b399c39a6d1479cd84ca591b4d7c88e24d38a96/packages/skill/tool-skill/src/index.ts#L224-L260) · [裁剪及原件来源](https://github.com/deepseek-ai/deepseek-harness/blob/4b399c39a6d1479cd84ca591b4d7c88e24d38a96/packages/compaction/compaction-tool-result-pruner/src/index.ts#L129-L175) · [摘要取材](https://github.com/deepseek-ai/deepseek-harness/blob/4b399c39a6d1479cd84ca591b4d7c88e24d38a96/packages/compaction/compaction-basic/src/region.ts#L540-L569)

正式 Web 对照确认，本工程主请求已将 Skill 回执从 35,500 个码点裁为 5,148 个，但工作摘要请求又从 Journal 送入正文中段 `XFER-72C9E6AD`。对应 Skill 回执在摘要请求中也缺少原生 `<skill_resources>`。改动限定在工作摘要的 Skill 取材。Conversation 重用原生 Skill 回执渲染与已提交的裁剪边界，并带原调用 ID，Journal 继续拥有完整回执及裁剪记录。摘要覆盖、原件读取、目录、技能权限和随包脚本沿现有入口。仅当经过真实回执的摘要及后续主请求满足下述判据时，记为该路径验证通过。[原件同输入回放](../../.tmp/skill-compaction-parity-20261125/replay-summary-before.json) · [实际摘要请求](../../.tmp/skill-compaction-parity-20261125/baseline-reload-fixed/sdk/bb3329d1e04b4267a7f165ae97dbfb1e.http.request.json)

用正式 Web 入口和真实模型运行同一项 `line-report` 分批核对任务，在隔离部署缩小声明上下文窗口以触发已有达压规则。使用同一长 Skill 的首部、正文中段和结尾，以及同包脚本输出核对实际结果。基线与目标各一个会话，固定任务、包、模型和窗口，单轮至多 12 个主决策、12 次工具调用及 200,000 tokens。按 SDK 原文确认已裁剪的工具结果仍配对，基线摘要重新出现中段原文，目标摘要只使用短版。压缩后的主请求应保留当前目录、移除被覆盖的旧配对，并可恢复原件及按名重读。用户结果按最终返回的包内核对信息和脚本实出评分。服务中断或未触发时分别保留实际结果与未到达阶段。

首个基线在受限窗口的 Goal 模式先执行了脚本并裁剪 Skill 回执，随后因容量拒绝中断，未到达摘要。比较沿用 LongDS 隔离装配的正式 Web 入口，使用相同的主循环和历史压缩。首轮问题明确仅需执行 `scripts/report.py` 并报告合计。直接模式使用独立基线和目标身份。随后确认带脚本的技能跨轮重载会遇到 Artifact 发布键冲突，按资源 ADR 修复后复跑原比较，摘要实现保持基线版本。[首个基线响应](../../.tmp/skill-compaction-parity-20261125/baseline/turn-01.response.json) · [裁剪后的实发回执](../../.tmp/skill-compaction-parity-20261125/baseline/sdk/db8dc286edfb460b9d9f6ffdf39238cf.http.request.json) · [跨轮重载修复](../adr/0058-skill-script-resources.md#决定与取舍)

对照两组均实际运行脚本并得到合计 318，第二轮均成功加载了技能。目标摘要请求带有裁剪标记、原调用 ID、尾码和资源根，省略的中段没有重新进入模型。两组第二轮均收到容量拒绝。基线接受了摘要检查点，目标未激活检查点。以下诊断对两组真实归档的第二轮状态和模型产出的摘要分别重建候选主请求，检查缩减与既有硬容量，并定位目录、原件和配对；该诊断无需新增实发请求。[基线第二轮响应](../../.tmp/skill-compaction-parity-20261125/baseline-reload-fixed/turn-02.response.json) · [目标实发摘要请求](../../.tmp/skill-compaction-parity-20261125/target/sdk/7cde7761bc4748c981e42ecaa0c385fa.http.request.json) · [目标第二轮响应](../../.tmp/skill-compaction-parity-20261125/target/turn-02.response.json)

复盘发现 48,500 窗口的主请求最多容纳 15,732 个估算输入 tokens。按归档真实摘要重建的候选主请求，基线约 17,710，目标约 15,966。两者均超过硬上限。目标候选还比原主请求多 41 个估算 tokens。补充的 51,500 窗口目标运行再次把短回执发给摘要模型。两版主请求均在硬容量内，候选仍比原请求多 12 个估算 tokens，未达到严格缩小条件。两条目标运行均在第二轮结束，第三轮未执行。候选主请求回放确认均保留目录、当前轮新回执和旧回执的原件定位，并移除旧回执的原生配对。[候选主请求回放](../../.tmp/skill-compaction-parity-20261125/replay-continuation.json) · [补充运行实发摘要](../../.tmp/skill-compaction-parity-20261125/target-headroom/sdk/cbec70db0184483bbd27df5af75ab96d.http.request.json) · [补充运行响应](../../.tmp/skill-compaction-parity-20261125/target-headroom/turn-02.response.json)

在同一条真实历史的确定性回放中，工作摘要历史材料从 43,717 个码点降至 12,855。短回执仍含原调用 ID、资源根、明确的省略标记和正文尾部。快照摘要与完整原文保持一致。实发请求的结论限于摘要输入和跨轮重载，压缩后的真实模型续跑及三轮用户结果尚未验证通过。[同输入回放结果](../../.tmp/skill-compaction-parity-20261125/replay-summary-after.json)

## 5. 随包技能

| 技能 | 适用场景与正文 |
| --- | --- |
| `longds-bench` | LongDS 配对启用任务级持久 Bash。随包保留上游技能原文与 `pysession.py`。运行器只委托模型用该脚本分析当前轮，并接管题目投递、内核清理与隔离评分。上游原文中的数据准备和自评分命令属于原独立工作流。[技能原文](../../src/personal_agent/bundled_skills/longds-bench/SKILL.md) · [运行器交接](../../evals/longDS/skill_session.py) · [沙箱契约](../adr/0056-bash-workspace.md#longds-任务级持久-bash) |

## 6. 实发请求示例

正式 Web Conversation 的中文回执核对任务要求先同批读取两个 `review-goal-after-update`，再逐步重读。以下是同一用户轮次内 MiniMax-M3.1-Flash 主循环的消息位置。各请求开头的 `messages[0]` 是系统规则，`messages[1]` 是用户原话，`messages[2]` 是 Goal 上下文。表中位置从 0 开始，省略重复出现的历史消息。

| 出站请求 | 与 Skill 相关的消息 |
| --- | --- |
| 同批加载前，第 2 步 | `messages[3]`（`user`）列出目录，包括 `"name": "review-goal-after-update"`。[实发请求](../../.tmp/skill-repeat-contract-20261125/web-target/sdk/9e147be736f14d27ae3ad1f944f3996e.http.request.json) |
| 同批加载后，第 3 步 | `messages[3]`（`assistant`）有两个参数相同的 `tool_load_skill`，两个 ID 不同。`messages[4]`、`messages[5]`（`tool`）各自配对并返回完全相同的 1,106 字符正文。`messages[6]`（`user`）仍是含摘要的 Step Context。[实发请求](../../.tmp/skill-repeat-contract-20261125/web-target/sdk/21597a2289a1435c8ff3bd98137bbd6a.http.request.json) |
| 第 3 次加载后，第 4 步 | `messages[6]`（`assistant`）单独重读，`messages[7]`（`tool`）返回正文，`messages[8]`（`system`）以“[Runtime 重复调用提醒] 你已连续 3 次用相同参数加载技能 `review-goal-after-update`。”开头，`messages[9]`（`user`）仍含目录。[实发请求](../../.tmp/skill-repeat-contract-20261125/web-target/sdk/0dab78b05aed48b88788aa7fcbcb8dc9.http.request.json) |
| 第 5 次加载后，第 6 步 | `messages[11]`（`assistant`）重读，`messages[12]`（`tool`）返回正文，`messages[13]`（`system`）提示已连续 5 次，`messages[14]`（`user`）仍含目录。[实发请求](../../.tmp/skill-repeat-contract-20261125/web-target/sdk/32b5a8f289904e8ca27f21d5747296d5.http.request.json) |

该样本确认同批正文配对及第 3、5 次提醒的位置。第 8 次和历史压缩分支按源码核对。模型额外读取一次，最终答复未准确确认提醒位置。工程级覆盖、用户级回落、主体隔离及作用域恢复限制见独立评测记录。[重复调用验证](../optimization/to_verify/conversation-loop-boundaries.md#skill-重复加载的回执对照) · [作用域评测](../problems/Skill-Use-Bench/SF03_t1_merge_unordered.md#工程级与用户级技能验证)

另一个正式 Web 样本加载 `line-report` 后，主模型在配对的 `messages[4]` 工具回执中收到“Bash 中的只读技能资源根目录为 `/workspace/skills/line-report/……`。”模型随后用目录中的 `scripts/report.py` 汇总同目录数据。实际 Bash 退出码为 0，交付回复含合计 318 和运行标记 `149fa1ff11ece605`。执行清单中的两份文件摘要均与安装原件一致。[资源根实发请求](../../.tmp/skill-script-resources-20261125/target/sdk/bed1f3a0015d4619a207a5058eb7a336.http.request.json) · [目标报告](../../.tmp/skill-script-resources-20261125/target/report.json)
