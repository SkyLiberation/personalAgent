# ADR 0038：按用户授权提前接入历史压缩

- 状态：Accepted，实施例外；自然压力与产品验收未覆盖
- 日期：2026-10-21
- 例外复审／删除日期：2026-11-21；届时未取得所声明真实压力证据，删除未验收的生产压缩路径，保留原容量拒绝及原始证据
- 唯一设计：[主循环 §3.11](../optimization/to_verify/conversation-loop-boundaries.md#311-context-压力与压缩)

## 依据与授权

已有真实研究请求未触发容量拒绝，新 E1 的最大 estimated 输入为 524,658；不能据此证明历史压缩必要或有效。用户在本会话明确选择“授权 ADR 例外先实现压缩”，允许先接入机制，把自然压力验收记为未覆盖。本例外只放宽压缩实现前的自然压力 baseline，不放宽权限、原文、计量、恢复和完成契约，也不授权伪造 E3。

## 实施切片与责任

在 Conversation 的具名 Context 协作者接入主决策／Final 和研究选证的旧执行历史。初始用户要求保持完整；核验所需原文、当前稿、最新反馈、最近仍在消费的动作、未终态动作及 Artifact 目录保持。先从完整 typed 输入建立原引用和引用编号，再让旧历史退出本轮投影，避免改变 canonical 引用。意图提取没有可替换执行历史；来源核验的必需原文不使用本机制缩减，仍由原末端 guard 接受或明确拒绝。

`HistoryCompactionCheckpoint` 只保存原 run、Journal revision、原始覆盖区间及 digest、实际替换条目的 typed key、只读历史快照引用及 digest、工作摘要、Prompt／响应身份和前检查点 digest。原 Journal 唯一拥有输入及预算，Artifact 唯一拥有快照字节。原件按原序确定性导出；模型只生成非权威工作摘要，原文身份、覆盖与授权由代码绑定。

只有原末端 `context_capacity_exceeded` 才自动生成摘要；其他拒绝保持。摘要本身复用同一模型 Port、容量、deadline 和累计用量准入，不挂工具。单批装不下时只缩小待覆盖的安全旧区间，再由同一 guard 检查；不改变原模型窗口。费用先提交，按新的预期 Journal revision 原子激活检查点。后次压缩消费上一摘要及新增旧单元，不叠加全部摘要；无新增覆盖、摘要为空／截断、来源失效或额度不明时明确停止。

每次请求及恢复重新核对来源摘要、主体、scope 和快照字节。最新检查点引用纳入现有读／搜索合法集合，读取再次核权；历史原件和读取反馈标为工作上下文，不取得论文来源或新事实资格。模型需要旧原文时使用原有读取工具。

## 验收、限制与撤回

本次真实阶段 Offline 固定：复制新 E1 revision 70 的完整 Journal 和原件；只允许一次摘要生成及一次实际摘要消费请求（研究选证契约），不执行业务动作。每个逻辑调用仅允许原客户端已有的一次格式修复，物理请求最多四次；新增已知消费上限 1,000,000 tokens，未知消费立即停止。沿用原绝对 deadline 2026-10-21T12:26:53.802788Z，不延长原验证授权；单请求 timeout 取剩余时间与 90 秒的较小值，调用前再次检查。直接调用真实阶段协作者验证 ADR 实现，不通过缩窗制造触发，不宣称这是自然 E3 或原用户结果通过。原件摘要、恢复及后续实际请求分开记录。

2026-10-21 实际首个摘要响应触发停止线：输入 105,081、输出 8,192（均为 reasoning）、合计 113,273 tokens，finish_reason=length；一次物理请求，没有可激活正文，后续消费与恢复未执行。SDK `LengthFinishReasonError` 在流式收尾抛出，绕过现行 typed 用量异常链。对应最早责任为 Provider SDK 适配：收回异常携带的原 completion，结构化／动作两条路径均将 length 终态作为 `StructuredOutputFailure`，不修复重试、不执行截断内容；可取得的 usage 沿原失败费用链提交。SDK 在部分流式场景未把最后 chunk 的 usage 写入 completion 时，保留 unknown 并停止新增调用，不能推算成完整计量。本笔原始异常文本含完整 usage，可独立审计对账；这不代表修正后已实测所有截断路径。先做此确定性异常修正及零模型工程核对，本轮不新增付费样本，也不增加摘要输出额度以追求通过。该修正不代表摘要后续消费已验证。

既定通过条件要求实际摘要连续进入后续请求，并检查同 run 检查点恢复、原件读取、费用不重复及安全停止；2026-10-21 该轮未到达摘要激活，不能记这些条件通过。[实际原件审计](../../.tmp/ctx-compact-20261021-1/export-audit.json)只证明 95 项原始输入的按序导出及 296,851 字节保真、真实摘要输入的 35 个旧单元来自原件、近期动作／反馈保护和异主体读取拒绝；508 原采集文件保持。用量[事后对账](../../.tmp/ctx-compact-20261021-1/report.json)消费真实 SDK 异常中的已观察计数，通过原 Journal 用量合并入口补齐副本费用，明确不是原失败流程已自动计费成功。没有自然压力、整例续跑或重复压缩的部分分别记未覆盖。

自然 C6／E3 仍按原设计验收。当前研究报告的统计错误独立保留，压缩不被用来修复或掩盖它。实现不新增数据库、通用 middleware、记忆平台、摘要 Judge 或生产开关；任务权限保持；2026-10-22 仅摘要请求级覆盖 thinking，详见[主循环 NS 设计](../optimization/to_verify/conversation-loop-boundaries.md#非思考摘要的局部修正2026-10-22)。

失败阶段沿原语义区分：`StructuredOutputFailure` 属于 `provider_structured_decode`，已观察完整 usage 不因外层 transport 分支被改为 unknown；只有 `ModelInvocationUnavailable` 属于 `provider_request`。缺失 usage 的结构化失败仍由 canonical 用量合并置 incomplete，不补零。该区别适用于摘要，与既有普通请求一致。

## 整体复审与当前状态

该切片只新增一个具名 Context 协作者和检查点／摘要类型，复用原模型 Port、Artifact、Journal 和读取工具。模型仍决定工作摘要及后续行动，代码只保护事实、权限、引用、费用与覆盖进展；没有引入研究策略或第二个任务事实 owner。2026-10-21 首次摘要截断暴露启用 thinking 与 8K 输出组合未产出正文。2026-10-22 依用户新授权仅关闭摘要 thinking，局部已验证完整生成、主决策消费及检查点重建；摘要仍沿用旧报告错误，不宣称语义保真。实际用例与限制由[当前评测盘点](../evals/02-current-case-inventory.md#2026-10-22-非思考摘要的局部验证)拥有。原研究报告统计错误独立归模型成文责任，继续按研究 Spec 的真实完整输入和预声明次数处理，不以压缩补丁或额外核验器掩盖。

[独立实现审查](../../.tmp/context-compression-research-20261021/compaction-implementation-review.md)中当前选证原文、inspect 证据旁路、最新核验反馈及失败阶段分类四项 Important 已修正并静态闭合，无未闭合 Critical／Important。Ruff F401／F811／F821、依赖 DAG、规范路由／本地链接与 `git diff --check` 通过；未运行单元测试。代码已接入，非思考摘要的局部生成、消费及恢复成立；自然 C6／E3 仍未覆盖，摘要语义保真及产品发布未取得通过。例外到期前仍须满足前述撤回条件。

相对本次 E1 的封存源码，[增量清单](../../.tmp/context-compression-research-20261021/implementation-accounting.json)覆盖九个生产文件：新增两个文件，增加 388 行、删除 20 行、净增 368 行；不把此前研究切片混入本次复杂度。新增维护面是一个协作者和 typed 派生检查点，不新增业务工具、配置开关、数据库或第三方依赖。最终源码与实际失败阶段分别封存；最终版本包含截断修正，不能冒充原失败请求发生时的通过版本。

实际从仓库根执行以下命令，均 exit 0：

```powershell
.\.venv\Scripts\python.exe -B -m ruff check --select F401,F811,F821 src scripts
.\.venv\Scripts\python.exe scripts/check_layers.py
.\.venv\Scripts\python.exe scripts/check_dev_spec.py
git -c core.safecrlf=false diff --check
```

依赖检查为 14 包／43 边、零环及零越层；规范路由为 69／69、目录覆盖 9／9，根入口逐字同步。上述为 2026-10-21 的静态检查记录。2026-10-22 的局部消费与恢复证据独立保存，不替代自然压力、长期任务和完整发布验收。原付费截止和本次截断停止线均已到达，未继续调用模型。
