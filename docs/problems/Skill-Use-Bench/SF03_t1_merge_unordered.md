# Skill-Use-Bench 的 PDF 合并对照

## 用例与判据

使用上游 `SF03_t1_merge_unordered`，固定提交 `1a80e93479e1a9f5ce4be2e27550edaf7f9d6ffc`。原题要求合并五份 PDF。技能 `pdftk-server` 给出文件排序、处理批量、命名和页数核验规则。[公开原题](https://github.com/JinyiHan99/Skill-Use-Bench/blob/1a80e93479e1a9f5ce4be2e27550edaf7f9d6ffc/benchmark/pdftk-server/tasks/t1_merge_unordered.yaml) · [上游评分](https://github.com/JinyiHan99/Skill-Use-Bench/blob/1a80e93479e1a9f5ce4be2e27550edaf7f9d6ffc/benchmark/pdftk-server/rubrics/rubric_t1_merge_unordered.yaml)

本 Agent 走正式 Conversation HTTP，DeepSeek Harness 走 SDK。每组均从独立新会话并行各跑一次，使用 `MiniMax-M3.1-Flash`、原题文本、相同 PDF 字节和同一禁网 Linux 镜像。任务提示不包含技能正文。DeepSeek 装配原生技能目录和加载工具。本 Agent 从未注册技能的基线开始，再部署同一份技能。评分器、评分配置和对方轨迹保持不可达。

先核对是否触发技能，再按上游规则评分。把最终 PDF 独立交付的文件状态、完整性和页序一并记录。若结果证明本 Agent 的技能能力存在缺口，先记录首个实际差异，再根据 DeepSeek 的技能发现和加载链限定改动范围。

## 结果

文件交付以原件、实际输出、上游 PDF 校验和逐页布局文本为准。`SF` 是上游技能遵循分。`Task` 是上游独立的轨迹判分，要求合并成功且最终产物生成后无后续错误。Rubric 的模型评分项使用项目配置的 `mimo-v2.6-pro`，上游默认模型为 `gpt-5`。Windows 评分入口只替换 POSIX 正则超时为外层进程超时，保留评分规则。

| 运行配置 | Agent | 技能触发 | SF | Task | PDF 交付 |
| --- | --- | --- | ---: | ---: | --- |
| 无技能基线 | 本 Agent | 未注册 | 不适用 | 0 | 926 页，按原题列举顺序 |
| 无技能基线 | DeepSeek Harness | 是 | 1.000 | 0 | 926 页，字母顺序及命名正确 |
| 首版技能回执，评测核验覆盖 | 本 Agent | 是 | 0.253 | 1 | 926 页，按原题列举顺序 |
| 首版技能回执，评测核验覆盖 | DeepSeek Harness | 是 | 1.000 | 0 | 926 页，字母顺序及命名正确 |
| Markdown 技能回执，评测核验覆盖 | 本 Agent | 是 | 0.793 | 1 | 926 页，按原题列举顺序 |
| Markdown 技能回执，评测核验覆盖 | DeepSeek Harness | 是 | 1.000 | 0 | 926 页，字母顺序及命名正确 |
| Markdown 技能回执，默认产品核验 | 本 Agent | 是 | 0.914 | 1 | 926 页，字母顺序及命名正确 |
| Markdown 技能回执，默认产品核验 | DeepSeek Harness | 是 | 1.000 | 0 | 926 页，字母顺序及命名正确 |

文件校验确认上表各份 PDF 的逐页布局文本、页尺寸及旋转都与原件对应。五份输入 PDF 和原题附带说明的 SHA-256 未变化。本检查覆盖可提取文本和页面几何，未做逐页像素或对象比对。DeepSeek 的 `Task=0` 包含最终产物生成后的工具超时或命令错误。独立产物检查仍通过。本 Agent 首版确实执行了多行 PDFtk 合并命令，上游正则未匹配该步骤，并把探测 `qpdf` 是否安装识别为禁用工具使用。表格保留上游原分。

最终一组两边都交付了 `merged_nist_cybersecurity_framework.pdf`。本 Agent 的实际 Bash 回执显示用 `pdftk dump_data` 核验 926 页，`r5` 正则仍未匹配该命令。`r6` 匹配了第一次尝试的 `/tmp/pdftk_workspace`，最终它在共享工作目录完成分批。DeepSeek 在指定目录分批，但产物生成后的额外核对出现空间不足、超时和 `uncompress` 参数错误，导致本次 `Task=0`。

## 技能加载与排序差异

基线请求已经确认能力差异。DeepSeek 在会话目录中展示 `pdftk-server`，第 1 个工具调用为 `skill({"name":"pdftk-server"})`，回执含完整正文，随后才调用 Bash。本 Agent 第一个允许工具执行的实际请求含 `tool_bash` 和对话控制动作，缺少技能摘要和加载动作，随后直接检查文件和工具环境。

DeepSeek 的 `skill-filesystem` 在本次配置从受信任的 `bundledSkillDir` 查找文件。`tool-skill` 投影摘要，按模型提交的名称查找并加载正文，把正文关联到原调用返回。采用对照见[本 Agent 技能设计](../../context/skill.md)。[目录装配](https://github.com/deepseek-ai/deepseek-harness/blob/2e39e70496aa02986ca6a820c5d497e816b69d7e/packages/skill/skill-filesystem/src/index.ts#L253-L271) · [模型调用与返回](https://github.com/deepseek-ai/deepseek-harness/blob/2e39e70496aa02986ca6a820c5d497e816b69d7e/packages/skill/tool-skill/src/index.ts#L84-L167)

首次接入后，第 2 步加载技能，第 3 步收到正文。第 4 步模型已读到规则，仍把用户列举文件的顺序解释成指定顺序，随后以列举顺序分批合并。有效 Goal 只要求完整保留五份文件，没有排序约束。这次偏差出在模型判断技能例外的条件。

第二版使用独立 Markdown 回执呈现完整技能，要求模型按技能执行，并用用户原话判断是否满足技能所列例外。用相同原题再对照一对新运行，确认模型选择及真实执行，保留首次偏差。此判据只验收同题的技能执行能力，单次命中只支持本次观察。[DeepSeek 目录加载提示](https://github.com/deepseek-ai/deepseek-harness/blob/2e39e70496aa02986ca6a820c5d497e816b69d7e/packages/skill/tool-skill/src/index.ts#L264-L286)

第二版仍把列表当成排序要求。这次第 1 步提交的 Goal 验收条件确实写入了 `in the listed order`，第 3 步模型把已生效的 Goal 当成了选择顺序的依据。共享评测脚手架关闭了项目默认开启的 Goal 和答复核验。单独以项目默认 flags 建立新的一对运行，核对真实 Goal 是否仍带入无依据的排序约束，再看实际合并顺序和输出。保留前三对的原始结果和核验配置。

默认核验运行中，本 Agent 的初始 Goal 只要求合并五份文件、输出到当前目录并保全内容，核验工具判定通过。`tool_load_skill` 与最初的 PDF 只读检查同批提交，完整技能正文在第一次合并前进入模型请求。模型随后按字母顺序用 PDFtk 以 4+1 分批，交付 `merged_nist_cybersecurity_framework.pdf`。初次分批失败的回执指出，之前工具调用创建的 `/tmp/pdftk_workspace` 不可用。模型把中间文件改放共享工作目录，在校验最终 926 页后清理。产物命名与页序达到技能要求，固定临时目录的使用仍有差异。此样本未触发 Goal 驳回，不能单独证明开关消除了排序误判。

## 运行证据

- 无技能基线。[原始运行](../../../.tmp/skill-use-bench-20261123-pair-baseline/run.json) · [评分与文件校验](../../../.tmp/skill-use-bench-20261123-grade-baseline/grade.json)
- 首版技能回执。[原始运行](../../../.tmp/skill-use-bench-20261123-pair-native/run.json) · [评分与文件校验](../../../.tmp/skill-use-bench-20261123-grade-native/grade.json)
- Markdown 技能回执与评测核验覆盖。[原始运行](../../../.tmp/skill-use-bench-20261123-pair-final/run.json) · [评分与文件校验](../../../.tmp/skill-use-bench-20261123-grade-final/grade.json)
- 本 Agent 默认核验。[运行身份](../../../.tmp/skill-use-bench-20261123-pair-product/run.json) · [调用轨迹](../../../.tmp/skill-use-bench-20261123-pair-product/personal-agent/turn-001.trace.json) · [本 Agent 的 PDF](../../../.tmp/skill-use-bench-20261123-pair-product/personal-agent/artifacts/merged_nist_cybersecurity_framework.pdf) · [DeepSeek 的 PDF](../../../.tmp/skill-use-bench-20261123-pair-product/deepseek-harness/artifacts/merged_nist_cybersecurity_framework.pdf) · [评分与文件校验](../../../.tmp/skill-use-bench-20261123-grade-product-native-receipts/grade.json)

默认核验运行保存了项目源码快照、实际装配、DeepSeek SDK 提交、运行时及技能插件的 SHA-256。最终评分使用本 Agent 原生 Bash 回执格式，包括退出码。早期归档保留各自的评分投影。四组每组各运行一次，结论限于这一道公开英文用例。复现命令见[评测入口](../../../evals/Skill-Use-Bench/README.md)。

Ruff 导入检查、依赖层检查和本报告的本地链接检查通过。`check_dev_spec.py` 报告现有文档 `docs/agentRef/context-engineering.md` 引用的 2026-10-18 源码清单不在本地。

## 工程级与用户级技能验证

2026-11-23 复用同一公开原题，以默认产品核验配置并行运行两个本 Agent 样本。两边使用同一份上游技能原件。工程样本同时安装在项目 `.dsh/skills` 和用户 `.agents/skills`，用户样本只安装在用户 `.agents/skills`。两条真实出站请求的会话目录均只有一个 `pdftk-server`，实际工具回执返回的完整正文与原件一致，并按原调用 ID 进入后续请求。[作用域 ADR](../../adr/0057-conversation-skill-scope.md)

| 配置 | 实际技能来源 | 作用域通过 | SF | Task | 独立文件校验 |
| --- | --- | --- | ---: | ---: | --- |
| 工程级与用户级同名 | `project` | 是 | 0.793 | 1 | 926 页，按题面列举顺序，默认命名未通过 |
| 仅用户级 | `user` | 是 | 1.000 | 1 | 926 页，字母顺序及命名正确 |

两份 PDF 的逐页文本、页尺寸和旋转均与原件对应，输入文件哈希未变化。工程级样本确实选择了正确来源，随后模型采用了题面列举顺序。该样本的 `Task=1` 与确定性页序校验结果均按各自判据保留。工程和用户样本分别记录 25 和 22 次模型请求。此组沿用上一轮 DeepSeek 源码和原始轨迹作为参照。

以公开运行的身份、会话、已提交轮次和同一技能原件回放作用域边界。工程级同名优先、本人跨会话回落用户级、不同租户同一 `user_id` 拒绝、撤回工程绑定后恢复拒绝、高优先级禁用遮蔽和同一身份经其他渠道访问拒绝，六项均通过。启动检查确认缺少 Web 认证的作用域配置被拒绝，配置有效密钥的服务可就绪。离线回放和启动检查覆盖随后增加的权限分支。[作用域回放](../../../.tmp/skill-use-scope-20261123-boundary-v4/report.json) · [认证启动检查](../../../.tmp/skill-use-scope-20261123-auth-smoke/report.json)

- 工程级与用户级同名。[原始运行](../../../.tmp/skill-use-scope-20261123-project/run.json) · [评分与校验](../../../.tmp/skill-use-scope-20261123-grade-project/grade.json)
- 仅用户级。[原始运行](../../../.tmp/skill-use-scope-20261123-user/run.json) · [评分与校验](../../../.tmp/skill-use-scope-20261123-grade-user/grade.json)
