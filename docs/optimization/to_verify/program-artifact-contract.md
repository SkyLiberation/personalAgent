# 共享程序产物读写契约 Spec

问题编号：`KNOWLEDGE-DECISION-DELIVERY-001`。本文拥有模型源码及 JSON 工作产物的写入、不可变快照、坐标 patch 与生产关联契约；读搜与 Python 执行仍分别沿现有工具及[Python Spec](python-data-analysis-tool.md)。受限实验与长程语义按各自需求消费同一 Artifact 能力，不另建状态库。总体关系见[总 Spec](knowledge-decision-delivery.md)。

## 1. 程序产物读写工具契约

**复用 `read_artifact`，新增一个带 `create`／`patch` 两种操作的 `write_artifact`；不另建程序文件系统或版本仓库。** 当前 [ArtifactService](../../../src/personal_agent/application/artifacts/service.py)已有 owner／scope 校验、文本读取及内部 `write_generated()`，但生成文件名／媒体类型固定 Markdown。现行 [读取准入](../../../src/personal_agent/application/conversation/service.py)仅接受本交互外置观察中的确切引用；不能因为底层 `read_text()` 能读取文本，就声称新创建的程序已经可被模型重读。2026-10-20 源码坐标及摘要见[本轮审计](../../../.tmp/program-artifact-tools-20261020/source-manifest.json)。以下契约现已注册并接入；本段保留初始审计来源，当前完成范围以 [完整落地 Implementation Plan](verify_results/research-experiment.md#32-完整落地-implementation-plan) 为准。

| 操作 | 模型提交 | Runtime／Artifact owner 产生的结果 |
| --- | --- | --- |
| `read_artifact` | 保留 `resource_id`、`start_line`、`limit`、`start_column`，引用必须是当前有权读取的确切产物 | 当前引用、`content_digest`、行号／列号、实际返回正文、`next_read` 及完整源文的 `eof_position`；保留单条输出上限，不将分页结束解释成全文已读 |
| `write_artifact.create` | `operation="create"`、`filename`、`content_type`、`content`；正文为本次新生成文本，首版支持 Python 源码和 JSON 配置 | 不可变文本快照的 `resource_ref`、媒体类型、字节数和服务端计算的 `content_digest`；文件名仅是显示／导出名称，不能含目录或决定存储路径 |
| `write_artifact.patch` | `operation="patch"`、`base_resource_id`、非空 `edits`；每项为 `range={start:{line,column},end:{line,column}}` 与 `new_text`，不提交 `old_text`、旧全文或自算 hash | 从旧快照恢复原文，一次校验及应用全部修改；新快照沿用其文件名／媒体类型，返回新引用、来源引用、字节数／digest 及有界变更摘要，旧产物不改写 |

`create`／`patch` 使用由 `operation` 区分的严格 typed union，混入其他分支字段或未知字段即拒绝。程序和配置仍使用现有 `ResourceRef` 身份，`program_ref` 只是执行参数中对同一引用的用途约束，不建立第二种独立可写程序身份。MIME、单次正文／补丁字节、修改数及输出上限由准备阶段公开的能力约束限定，服务端校验真实 UTF-8 字节，模型不决定资源上限。

读取元数据及正文由同一 Artifact owner 返回为 typed 文本快照，分页只是该快照的投影；不能仅从现有 `read_text()` 的裸字符串推断版本或由读取窗口拼回权威源码。新写入统一以确切 UTF-8 字节计算内容摘要，补丁同时检查新增文本和修改后产物的总字节上限。读、搜索、修改及执行共同消费该 owner 的原文与身份。

范围按原文的 Unicode 码点、1 起计的行列定位，与现有读取的 `start_column`／`line_length` 一致，采用左闭右开区间；例如 `[18:1, 20:1)` 替换第 18、19 行，保留第 20 行。起止相同表示插入，`new_text=""` 表示删除。所有范围都针对同一个 `base_resource_id`，不得越界、重叠或在同一位置重复插入；先全部校验，再按原位置一次应用，任一项无效则整次零写入。Runtime 从原始文本计算位置并保留未修改字节，不模糊匹配、不自动缩进或补写模型未提交的代码。

追加使用读取结果的 `eof_position` 作为相同起止点；空文本为 `(1,1)`，有末尾换行时为下一行第 1 列，否则为末行末字符后的列。该坐标从同一确切源文派生，不由分页片段猜测，也不允许在 Unicode 码点或 CRLF 换行内部切开。

下列为调用顺序示意，`v1`／`v2` 是返回的完整 typed 引用的人读简称，不是模型拼出的路径或版本号：

```text
write_artifact(create, filename="fusion.py", content_type="text/x-python", content=新代码) → v1
read_artifact(resource_id=v1.resource_id, start_line=15, limit=10) → 当前片段及坐标
write_artifact(patch, base_resource_id=v1.resource_id, edits=[{range:[18:1,20:1), new_text:新实现}]) → v2
受控 Python 执行(program_ref=v2, input_result_refs=实际输入结果) → 真实结果
```

此处执行示意对应检索实验中的程序引用协议；通用 `execute_python` 使用直接 code／input_files，文件 ID 简化由 [Python Spec §3.8](python-data-analysis-tool.md#38-文件选择只提交现有-id2026-10-24)拥有，不把两种执行契约混写。

每次创建／修改成功即提交可独立执行的快照，不另设“保存”调用。`base_resource_id` 已锁定版本，不增加模型填写的 `expected_revision` 或可变“最新文件”表。由旧引用派生新分支是合法操作；两个并发修改可以得到不同快照，不相互覆盖，研究模型明确选择要执行的引用。冻结记录继续绑定原引用，随后创建新版本不会替换冻结源码；最终交付从同一引用恢复确切字节。首版一个源码产物对应一个单文件程序，依赖及配置沿既有输入提供。

写工具通过原工具治理到 Artifact Application／Service，owner、执行作用域、producer 身份和 digest 由 Runtime／原 owner 绑定，模型不提交路径、owner 或存储键。仅当前任务授权创建的程序／配置草稿可作为修改目标；材料、受信驱动、评分器及研究正式稿仍按各自 owner 管理。写入成功只表示源码被保存，不表示语法、实验或研究通过；手写结果 JSON 也不产生执行／评分事实。失败回执按原反馈链给出无权限、引用不可用、范围无效、超额度或写入失败，保留原文，不猜测修复后默认成功。

创建目标由 Artifact owner 按原执行身份和内容确定后绑定适用写集合；`patch` 的读集合是 `base_resource_id`，写集合是新快照，不能把派生操作声明成对旧文件原地修改。该身份绑定在代码内完成，不增加一次模型“准备写入”调用，Proposal、Command 和成功回执仍各按原协议承担职责。

读取准入须同步由“仅外置观察引用”扩展为从获准输入、owner 已提交的写入／实验回执及恢复事实派生的当前可读引用集合，并用于读、搜索和 Context 投影；不从模型文字、程序 stdout 或任意 JSON 键收集“引用”。底层仍复核 principal／owner、用途及版本，不能放开到同用户全部文件。该集合是原事实的投影，不是新的持久注册表。

写入按原持久执行边界绑定适用 Command／稳定 producer：同一已接受请求重试返回同一快照；核对的是完整请求，包括操作、文件名、媒体类型、正文或 base／edits、用途及来源绑定，不只比较内容摘要。当前 `write_generated()` 的 producer 短路仅核对正文摘要，不能原样作为新写工具的重试契约。内容和元数据提交完成后才返回成功，提交后响应丢失沿原身份恢复引用，不生成假回执。

P1 不强制模型先读再改或必须修改多次，一次正确生成也可完成原请求。创建、补丁、后续可读及执行同一版本的能力按实际到达分别报告；若 P1 未发生修改，使用其真实阶段输入进行源码范围、版本／权限、批量原子性和提交后恢复的 Offline Eval，不能仅靠最终报告反推编辑能力。开源的工具分组及未采用的字符串替换方式见[外部读写比较](../../agentRef/tool-execution-and-safety.md#8-文本读写与修改入口)。

**本轮共享产物实施契约（T1，实施前固定）。** `application/artifacts/models.py` 唯一定义 `ArtifactRecord`、`ArtifactTextSnapshot`、`TextPosition`／`TextRange`／`TextEdit`、`CreateArtifact`／`PatchArtifact`、`ArtifactWriteReceipt` 和用户下载资源项。原 `ArtifactService` 扩展 `read_snapshot()`、`write_draft()` 和机器产物发布，`read_text()` 只投影同一快照正文；不增加第二份存储。sidecar 读取使用 typed record，正文摘要由 owner 按 UTF-8 计算并在读取时复核，文件名／MIME、字节数、用途、执行作用域和来源绑定均从该 owner 恢复。现有 `write_generated()` 的全部生产者同步采用确切 UTF-8 摘要，删除 canonical JSON 摘要的双口径。

| 契约 | 固定行为与必要消费者 |
| --- | --- |
| 新程序及配置 | `write_artifact` 的 `request` 为严格 create／patch union。create 仅接受 `text/x-python` 的 `.py` 或 `application/json` 的 `.json`；filename 为最多 120 个字符的安全显示名，不含路径、控制字符或响应头分隔。单份草稿及一次补丁新增正文各最多 65,536 UTF-8 字节，补丁最多 32 项；Runtime 不修正文或 JSON 语法，实际执行另验 |
| 上传身份 | 上传身份绑定认证 owner、filename、MIME 和确切原字节，不再只由 filename／bytes 生成全用户共用身份；跨用户同名同内容互不覆盖，同用户不同不可变描述形成不同快照。重复同一请求只复用完整一致记录，不覆写已绑定 owner／描述 |
| 坐标与读取 | 保持现有 Python `splitlines` 的逻辑行语义，owner 保留全部换行原字节并提供唯一位置映射；CRLF 是完整换行单位。末尾换行的 EOF 为下一行第 1 列，空文为 `(1,1)`；读取恰在 EOF 返回空页且无续页。read／search／patch 共同消费该映射，读取窗口附同一快照 digest 和 EOF，不靠片段重组 |
| 多项补丁 | 所有范围针对同一 base；非空范围不得交叠，同点不得重复插入，插入不得位于替换范围内部。允许相邻替换及边界插入：插入在替换起点时位于替换文字前，在终点时位于其后；按原位置从后向前应用，输入 edits 顺序不改变结果。先验证全部范围及最终字节额度，再提交一个新快照，失败零写入 |
| 可信调用身份 | Gateway 在 `RunnableConfig.configurable["__personal_agent_gateway_context"]` 传现有 typed `ToolGatewayContext`，并携带由当前初始资源及已提交事实投影的 `allowed_resource_refs`；工具函数只接受该实际 typed 对象，缺失即拒绝。`write_artifact`／`inspect_artifact` 不接收模型填写的 user／owner／producer；不能从引用内的 owner 自我授权 |
| 稳定提交 | Artifact owner 将真实 principal、执行 scope、稳定 tool_call_id 及完整已接受 request 绑定 producer，完整请求含操作、filename／MIME、正文或 base／edits、用途及来源。跨进程同 producer 排他；先持久化不可变 producer 绑定，再原子提交正文及 canonical metadata，齐备后返回成功。响应丢失或部分提交只按同请求补齐；同 producer 不同 payload 拒绝。producer 绑定和正文元数据各有单一职责，不保存独立可写内容镜像 |
| 已有产物保护 | 默认 data 有 0 份上传 sidecar、6 份普通 generated 报告。原字节复核 5/6 摘要及长度一致；`artg_bb8a7eeb887bd783dd92` 登记 3,285 bytes、实为 3,313 bytes，28 处 CRLF 转 LF 后才符合旧摘要。保留原件并明确拒绝其完整性，不静默标准化或改登记值；初次以 read_text 核对产生的 6/6 结论撤回。历史记录没有 execution_scope 或完整 producer 请求，其未知 scope 如实表达，不填当前 run；只读历史不能作为草稿或实验执行事实。缺完整绑定的旧 producer 拒绝重放，新写入绑定实际 scope／用途，不由外部报告名字推导权限，历史证据不批量改写 |
| 当前任务权限 | 初始材料由正式 `input_artifact_refs` 字段传入并校验 owner／版本，保存到原 InteractionTrace；同 run 恢复必须与原字段相同。新草稿只能由本任务的成功写回执进入可改集合，patch 同时复核原记录的 execution_id 及草稿用途。只读材料、实验结果、受信程序及正式报告不能作为草稿修改 |
| 来源及读取链 | 保留现有成功观察中已提交的 typed `retrieval.resource_ref` 绑定，并加入初始 typed 资源、成功写回执、实验产物回执和原恢复事实，形成当前可读集合，供 read／search、source_reading、citations 和 Context 共用。初始材料以 owner 元数据形成只读来源，本地无 URL 不等于执行结果；写入／实验回执用具名 typed 输出，不扫描任意 JSON 或模型正文。文本快照允许 text/*、application/json 及 application/x-ndjson 严格 UTF-8 解码，二进制原件走原字节／inspect，不有损转换或将提取文本冒充原件。发布后的报告只属交付集合，不能反向成为研究来源 |
| 用户文件入口 | 新增不入库的 Artifact 上传与按确切 ID／revision 下载；认证主体由现有 Web 边界取得，owner 不由 URL 决定，返回登记 MIME、安全 filename 和原字节。用户可下载自己获准的 Artifact，不以模型当前工作集代替用户权限；模型读取仍受本任务集合约束。`ConversationTurnView` 返回同一 owner 产生的 typed 交付资源项 |

新增的类型、调用字段和文件入口仅服务本次真实写入、读取、执行及用户下载消费者；没有通用文件系统、可变 latest、程序仓库或新的授权总账。机器产物发布继续受信，不复用模型草稿写入口来伪造执行事实。T1 静态与真实阶段检查覆盖字节／坐标、同身份不同请求、部分提交、跨用户／跨任务和并发写；E1／P1／F1／F3 再验其生产消费，目前已实现但未完成这些整体验收。


## 2. 消费者与状态

受限实验、[Python 分析](python-data-analysis-tool.md)和[长程语义候选](longtask-semantic-consistency.md)使用同一原件能力。跨 run 的 JSON 工作记录按读取旧原件、创建增量记录处理；本契约不因此扩张跨 run patch 权限。写入及读取事实不证明内容语义正确，实际验证范围见[研究实验记录](verify_results/research-experiment.md)。
