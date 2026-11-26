# ADR 0058 · 从 Skill 回执定位并执行随包脚本

## 问题与依据

用户需要模型按已安装技能运行随包脚本。当前 `tool_load_skill` 回执提供正文和来源，Bash 输入由会话 Journal 从已授权资源冻结。待验证的缺口是同一技能的相对脚本路径无法由正文接续到执行环境。[技能现状](../context/skill.md) · [Bash 输入契约](0056-bash-workspace.md)

DeepSeek Harness 固定于 `4b399c39a6d1479cd84ca591b4d7c88e24d38a96`。本地技能 Provider 返回已选择目录的 `resourceBase`。`skill` 将目录放入工具回执的 `<skill_resources>`，模型据此消解相对路径。Bash 按执行策略独立运行模型提交的命令。其本地 Linux 默认沙箱可从宿主机文件树读取。本工程的 Bash 用独立 Docker 容器和明确的输入挂载，采用可用资源根与相对路径约定。[资源根生成](https://github.com/deepseek-ai/deepseek-harness/blob/4b399c39a6d1479cd84ca591b4d7c88e24d38a96/packages/skill/skill-filesystem/src/index.ts#L211-L232) · [回执表达](https://github.com/deepseek-ai/deepseek-harness/blob/4b399c39a6d1479cd84ca591b4d7c88e24d38a96/packages/skill/skill/src/index.ts#L173-L200) · [Shell 执行](https://github.com/deepseek-ai/deepseek-harness/blob/4b399c39a6d1479cd84ca591b4d7c88e24d38a96/packages/shell/tool-bash/src/index.ts#L524-L543) · [本地沙箱](https://github.com/deepseek-ai/deepseek-harness/blob/4b399c39a6d1479cd84ca591b4d7c88e24d38a96/packages/sandbox/sandbox-local/src/profiles.ts#L16-L35)

## 决定与取舍

只处理已配置的胜出技能包中的 `scripts/` 及其普通随包文件。保留相对路径，使脚本可以读取同目录数据。技能加载器选择资源来源，Artifact 保存不可变字节，Conversation 从已提交且仍可访问的加载回执派生只读文件清单。沿用 `tool_bash` 的授权、已冻结输入快照、Docker 挂载及恢复。回执披露脚本实际可用的容器目录。命令仍由模型按用户要求提交。通过复用只读输入，避免给容器扩大宿主机目录可见范围或引入新的执行工具。加载与同批 Bash 的先后取决于已提交回执，刚加载的脚本可供下一次 Bash 请求使用。

基线通过正式 Web 入口加载了 `line-report`，后继请求携带正文及 `tool_bash`，回执缺少资源根。Bash 先后检查工作区和容器文件树，未取得包内 `report.py`。运行随后在模型请求处返回 504，整例无答复。已取得的真实阶段确认缺口位于 Skill 与执行输入的交接。[后继实发请求](../../.tmp/skill-script-resources-20261125/baseline/sdk/3fe3ea08a3d04d49ab3bb8c2fca9d602.http.request.json) · [入口响应](../../.tmp/skill-script-resources-20261125/baseline/turn.response.json)

应用边界在成功读取正文后，按当前 Bash 许可取得所选技能的脚本文件。文件适配器按现有 Bash 相对路径约束检查正常文件和目录，拒绝链接、路径碰撞和超出既有输入上限的包。每次读取成功后以路径与内容摘要定位不可变副本。重复加载同一版本的资源根稳定。Journal 只在当前任务的完成回执中选择这些副本，普通、任务及共享工作区沿用同一只读清单。资源准备失败时返回技能资源错误。撤回时停止生成及消费加载回执的脚本输入，已冻结 Bash Command 仍沿用自身的文件引用。

后续压缩对照在第二轮重读同一技能时收到 HTTP 500。首轮接受的 Artifact 发布键只含内容路径，新轮次尝试用同一键发布不同的 `ExecutionScope`。原 Artifact 记录重放复现了该不可变绑定冲突。发布键同时绑定轮次执行 ID 和资源路径，同轮重试可取得同一引用，跨轮创建各自获准的引用。容器路径仍按内容寻址，历史已冻结命令继续按原引用读取。验收用同一原件检查两个轮次、同轮重试及不同主体，再由 Web 压缩对照消费第二次加载回执。[正式入口响应](../../.tmp/skill-compaction-parity-20261125/baseline-isolated/turn-02.response.json) · [原件重放](../../.tmp/skill-compaction-parity-20261125/replay-before/report.json) · [压缩对照](../context/skill.md#41-与-deepseek-harness-的压缩对照)

## 验证计划

固定一个中文用户任务和不随请求披露输出的本地技能包。用户要求模型用技能自带脚本汇总包内数据并返回总数和运行标记。脚本读取同一 `scripts/` 下的输入文件。采用正式 Web Conversation、已配置真实模型、独立会话 Bash 执行许可、现有固定 Linux 镜像和普通 Goal 模式。先跑一条基线，取得加载后的实发请求、真实 Bash 结果和最终答复。基线允许证明脚本不可达，不能用模型自述替代执行证据。

差异成立后，用相同任务和配置跑一条目标。通过条件为实际命令执行原包脚本，回执及最终答复中的结果与固定原件一致。检查资源根随工具回执发送，Bash 输入中的脚本和数据摘要与原件逐字节一致。另以现有装配验证已选技能与同名低优先级来源、其他主体的 scope 隔离，资源保持只读。每条真实运行至多 12 次主决策、12 次工具调用、200,000 tokens，出现服务错误或任务截止即停止。没有到达加载或执行边界时保留该结果。

## 验收结果

2026-11-25，正式 Web 目标用例通过。MiniMax-M3.1-Flash 在同一工具回执中收到容器资源根及技能原文，随后用 `tool_bash` 运行原包 Python 脚本。两次 Bash 命令均退出 0。原件、Artifact 与执行清单中的 `report.py`、`data.txt` 摘要一致，脚本 stdout 和用户答复均包含合计 318 和标记 `149fa1ff11ece605`。本次 9 个模型请求、37,268 tokens。离线对照验证工程级同名优先、其他主体仅可见打包版、跨主体访问 Artifact 被拒。只读证据来自真实目录回执和生产挂载选项。共享卷本轮核对了路径和投影源码。[目标报告](../../.tmp/skill-script-resources-20261125/target/report.json) · [实发回执](../../.tmp/skill-script-resources-20261125/target/sdk/bed1f3a0015d4619a207a5058eb7a336.http.request.json) · [摘要与作用域对照](../../.tmp/skill-script-resources-20261125/scope-replay-v2/report.json)

跨轮重载修复后，正式 Web 对照的第二轮通过了资源发布并进入摘要。原件回放确认三种执行作用域各自发布两份引用，同轮重试重用引用，容器内路径一致。后续摘要容量验收单独记录。[修复后回放](../../.tmp/skill-compaction-parity-20261125/replay-after/report.json) · [压缩对照](../context/skill.md#41-与-deepseek-harness-的压缩对照)
