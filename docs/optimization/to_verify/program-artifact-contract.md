# 共享程序产物读写契约 Spec

问题编号：`KNOWLEDGE-DECISION-DELIVERY-001`。本文拥有模型源码及 JSON 工作产物的写入、不可变快照、精确文本编辑和生产关联契约。受限实验与长程语义消费同一 Artifact 能力。总体关系见[总 Spec](knowledge-decision-delivery.md)。

## 1. 程序产物读写工具契约

### 模型编辑工具

LongDS NYC Task 1 的真实请求中，模型通过 Bash 读取和修改 `/work` 脚本。旧专用编辑工具接收 Artifact 的行列范围，无沙箱文件入口。采用 DeepSeek Harness 固定版本的 `edit(file_path, old_string, new_string, replace_all=false)` 作为统一模型编辑入口，保留精确匹配、歧义拒绝和可选全量替换。LongDS 对照当时使用 Bash，专用编辑器的效果需单独验证。[本 Agent 对照记录](../../problems/longds/2026-11-18-nyc-restaurants-task1.md) · [DeepSeek edit 源码](https://github.com/deepseek-ai/deepseek-harness/blob/2e39e70496aa02986ca6a820c5d497e816b69d7e/packages/fs/tool-fs/src/edit.ts#L78)

| 路径 | 可见性与实际写入 | 成功结果 |
| --- | --- | --- |
| `artifacts/<id>` | 当前具备草稿写入能力。Artifact 从可读集合解析确切引用，复核主体、当前执行和草稿用途，继承文件名和类型后保存新快照。 | 新路径、来源引用、内容摘要、字节数和替换次数。 |
| `/tmp/<file>` | 仅在具备 Bash 和当前任务工作区许可时声明。Conversation 将参数派发给已获准 Bash 执行链，接受记录绑定确定性编辑程序。该程序在非 root 任务容器内读取现有 UTF-8 普通文件，验证后同目录原子写回。拒绝符号链接、父目录穿越和工作区之外的路径。 | 原路径、替换次数及 Bash 回执中的退出状态。 |

本次继续采用 DeepSeek 固定版本的换行与观察策略。文件和两个替换参数统一以 LF 比较，写回使用文件原来的主导换行风格。Artifact 的路径已绑定不可变快照，仍由 Artifact owner 检查。可变的 `/tmp` 需要先用 `tool_read_file` 观察当前版本。Bash 执行适配器随任务容器保存路径对应的内容摘要，使用专用读取和编辑的成功回执更新版本。在同一容器内，写入前由冻结的编辑程序复核当前字节摘要。未经读取或文件已被其他命令改写时返回重读提示。版本由运行器绑定，模型只填写文件路径和替换文本。读取与编辑只对可用任务容器声明。[换行实现](https://github.com/deepseek-ai/deepseek-harness/blob/2e39e70496aa02986ca6a820c5d497e816b69d7e/packages/fs/fs-local/src/fsio.ts#L849) · [DeepSeek 观察策略](https://github.com/deepseek-ai/deepseek-harness/blob/2e39e70496aa02986ca6a820c5d497e816b69d7e/packages/fs/fs-observation-policy/src/index.ts#L130)

模型请求沿 DeepSeek 的分工组织。读取工具说明说明路径、行范围和续读坐标，编辑说明写清先读、字面匹配和 `replace_all` 的选择。版本摘要是运行器数据。读回执向模型提供原文、行号和续读位置，成功编辑提供更新后的路径或 Artifact 引用，拒绝回执提供原因和重读指引。工具结果通过同一调用 ID 进入下一次请求。DeepSeek 的界面 diff 元数据与模型使用的结果正文分别生成。验收覆盖实际出站工具声明、读取回执、编辑成功反馈、陈旧文件拒绝和重读后的写入，并用 LongDS 真实脚本回放跨换行匹配。[DeepSeek 读取投影](https://github.com/deepseek-ai/deepseek-harness/blob/2e39e70496aa02986ca6a820c5d497e816b69d7e/packages/fs/tool-fs/src/read.ts#L68) · [消息适配](https://github.com/deepseek-ai/deepseek-harness/blob/2e39e70496aa02986ca6a820c5d497e816b69d7e/packages/llm/llm-pi-ai/src/context.ts#L24)

`old_string` 必须非空且与 `new_string` 不同。换行转换后按原文从左到右匹配非重叠的精确文本，保留空格和缩进。默认只接受恰好一次匹配。传 `replace_all: true` 时替换所有匹配，空 `new_string` 删除匹配。零匹配、默认模式下匹配多次、权限不足、编码无效或超额度均拒绝写入。Artifact 限额为 65,536 字节，`/tmp` 使用任务沙箱的命令与工作区额度。

验收使用 NYC Task 1 已落盘脚本阶段和实际任务容器，验证工具声明、替换后的完整脚本和下一轮可见性。Artifact 使用正式草稿写入和读取边界验证基稿保留、派生正文及引用。反例覆盖零匹配、多匹配、全量替换、无权限、只读来源和异常路径。采用固定源码及实际模型调用验证可达性；公开数据集整例成绩单独记录。

精确编辑初版的 Artifact 持久恢复及边界回放已通过。迁入 `/tmp` 后，两轮正式 HTTP 验证确认两类文件可编辑，任务脚本可跨轮继续使用。[初版编辑记录](../../problems/longds/2026-11-18-nyc-restaurants-task1.md#专用文本编辑工具的定向验证) · [单目录验证](../../problems/longds/2026-11-18-nyc-restaurants-task1.md#任务沙箱单目录验证)

### Artifact 工具与快照

| 操作 | 模型提交 | Runtime／Artifact owner 产生的结果 |
| --- | --- | --- |
| `tool_read_file` | `file_path`、`start_line`、`limit`、`start_column`，路径指向当前有权读取的确切产物 | 当前引用、`content_digest`、行号／列号、实际返回正文、`next_read` 及完整源文的 `eof_position` |
| `tool_create_artifact` | `filename`、`content_type`、`content`，正文为新生成文本 | 不可变文本快照的 `resource_ref`、媒体类型、字节数和服务端计算的 `content_digest`。文件名用于显示和导出 |
| `tool_edit` | 本节精确文本编辑声明 | 从授权快照恢复原文并派生新快照。 |

Conversation 根据调用名和当次声明校验，将 Artifact 创建和编辑分别构造成 `CreateArtifact` 和 `EditArtifact`。两者共用 `WriteArtifactArgs.request`、Journal、Gateway 和 Artifact 写入入口。程序和配置使用现有 `ResourceRef` 身份。

读取元数据及正文由同一 Artifact owner 返回为 typed 文本快照。分页和阅读坐标只是该快照的投影。新写入统一以确切 UTF-8 字节计算内容摘要，编辑检查替换文本和结果的字节上限。读、搜索、修改及执行消费同一 owner 的原文与身份。

下列为调用顺序示意，`v1`／`v2` 是返回的完整 typed 引用的人读简称，不是模型拼出的路径或版本号：

```text
tool_create_artifact(filename="fusion.py", content_type="text/x-python", content=新代码) → v1
tool_read_file(file_path="artifacts/<v1.resource_id>", start_line=15, limit=10) → 当前片段
tool_edit(file_path="artifacts/<v1.resource_id>", old_string=原实现, new_string=新实现) → v2
受控 Python 执行(program_ref=v2, input_result_refs=实际输入结果) → 真实结果
```

此处执行示意对应检索实验中的程序引用协议；通用 `execute_python` 使用直接 code／input_files，文件 ID 简化由 [Python Spec §3.8](python-data-analysis-tool.md#38-文件选择只提交现有-id2026-10-24)拥有，不把两种执行契约混写。

每次创建或修改成功即提交可独立执行的快照。Artifact 路径锁定版本。两个基于同一旧引用的修改可以得到不同快照，模型明确选择要执行的引用。冻结记录继续绑定原引用，最终交付从同一引用恢复确切字节。

写工具通过原工具治理到 Artifact Service。Runtime 与原 owner 绑定主体、执行作用域、producer 身份和摘要。只有当前执行授权创建的草稿可编辑，材料、受信驱动、评分器及研究正式稿仍按各自 owner 管理。保存回执记录写入事实，实验和评分使用各自执行结果。

创建目标由 Artifact owner 按原执行身份和内容绑定。编辑的读集合是确切基稿，写集合是新快照。Proposal、Command 和成功回执沿原协议承担职责。

读取准入须同步由“仅外置观察引用”扩展为从获准输入、owner 已提交的写入／实验回执及恢复事实派生的当前可读引用集合，并用于读、搜索和 Context 投影；不从模型文字、程序 stdout 或任意 JSON 键收集“引用”。底层仍复核 principal／owner、用途及版本，不能放开到同用户全部文件。该集合是原事实的投影，不是新的持久注册表。

写入按原持久执行边界绑定 Command 和稳定 producer。同一已接受请求重试返回同一快照。核对完整请求，包括操作、创建参数或编辑参数、用途及来源绑定。内容和元数据提交完成后返回成功，响应丢失时沿原身份恢复引用。

P1 可直接创建正确脚本。创建、编辑、后续读取及执行同一版本按实际到达分别报告。

**共享产物实现契约。** `application/artifacts/models.py` 定义记录、快照、读取范围、创建和编辑请求、写入回执和用户下载资源项。Artifact Service 拥有读取、草稿写入和机器产物发布。读取时按 owner 元数据恢复文件名、类型、用途、执行作用域和来源，并用确切 UTF-8 字节复核正文摘要。

| 契约 | 固定行为与必要消费者 |
| --- | --- |
| 新程序及配置 | 创建和编辑归一为 `write_artifact` 的 typed 请求。Python、JSON 和 Markdown 采用匹配的媒体类型和后缀。文件名为最多 120 个字符的安全显示名。单份草稿最多 65,536 UTF-8 字节。程序执行另验 |
| 上传身份 | 上传身份绑定认证 owner、filename、MIME 和确切原字节，不再只由 filename／bytes 生成全用户共用身份；跨用户同名同内容互不覆盖，同用户不同不可变描述形成不同快照。重复同一请求只复用完整一致记录，不覆写已绑定 owner／描述 |
| 坐标与读取 | 读搜使用 Python `splitlines` 的逻辑行语义。CRLF 是完整换行单位。末尾换行的 EOF 为下一行第 1 列，空文为 `(1,1)`。读取恰在 EOF 返回空页且无续页，读取窗口附同一快照 digest 和 EOF |
| 可信调用身份 | Gateway 在 `RunnableConfig.configurable["__personal_agent_gateway_context"]` 传现有 typed `ToolGatewayContext`，并携带由当前初始资源及已提交事实投影的 `allowed_resource_refs`；工具函数只接受该实际 typed 对象，缺失即拒绝。`write_artifact`／`inspect_artifact` 不接收模型填写的 user／owner／producer；不能从引用内的 owner 自我授权 |
| 稳定提交 | Artifact owner 将真实 principal、执行 scope、稳定 tool_call_id 及完整已接受 request 绑定 producer。跨进程同 producer 排他。先持久化不可变 producer 绑定，再原子提交正文及 canonical metadata，齐备后返回成功。响应丢失或部分提交只按同请求补齐，同 producer 不同 payload 拒绝 |
| 已有产物保护 | 默认 data 有 0 份上传 sidecar、6 份普通 generated 报告。原字节复核 5/6 摘要及长度一致；`artg_bb8a7eeb887bd783dd92` 登记 3,285 bytes、实为 3,313 bytes，28 处 CRLF 转 LF 后才符合旧摘要。保留原件并明确拒绝其完整性，不静默标准化或改登记值；初次以 read_text 核对产生的 6/6 结论撤回。历史记录没有 execution_scope 或完整 producer 请求，其未知 scope 如实表达，不填当前 run；只读历史不能作为草稿或实验执行事实。缺完整绑定的旧 producer 拒绝重放，新写入绑定实际 scope／用途，不由外部报告名字推导权限，历史证据不批量改写 |
| 当前任务权限 | 初始材料由 `input_artifact_refs` 字段传入并校验 owner 和版本，保存到 InteractionTrace。同 run 恢复必须与原字段相同。新草稿由本任务的成功写回执进入可改集合，编辑复核原记录的 execution_id 和草稿用途 |
| 来源及读取链 | 保留现有成功观察中已提交的 typed `retrieval.resource_ref` 绑定，并加入初始 typed 资源、成功写回执、实验产物回执和原恢复事实，形成当前可读集合，供 read／search、source_reading、citations 和 Context 共用。初始材料以 owner 元数据形成只读来源，本地无 URL 不等于执行结果；写入／实验回执用具名 typed 输出，不扫描任意 JSON 或模型正文。文本快照允许 text/*、application/json 及 application/x-ndjson 严格 UTF-8 解码，二进制原件走原字节／inspect，不有损转换或将提取文本冒充原件。发布后的报告只属交付集合，不能反向成为研究来源 |
| 用户文件入口 | 新增不入库的 Artifact 上传与按确切 ID／revision 下载；认证主体由现有 Web 边界取得，owner 不由 URL 决定，返回登记 MIME、安全 filename 和原字节。用户可下载自己获准的 Artifact，不以模型当前工作集代替用户权限；模型读取仍受本任务集合约束。`ConversationTurnView` 返回同一 owner 产生的 typed 交付资源项 |

新增的类型、调用字段和文件入口仅服务本次真实写入、读取、执行及用户下载消费者；没有通用文件系统、可变 latest、程序仓库或新的授权总账。机器产物发布继续受信，不复用模型草稿写入口来伪造执行事实。T1 静态与真实阶段检查覆盖字节／坐标、同身份不同请求、部分提交、跨用户／跨任务和并发写；E1／P1／F1／F3 再验其生产消费，目前已实现但未完成这些整体验收。


## 2. 消费者与状态

受限实验、[Python 分析](python-data-analysis-tool.md)和[长程语义候选](longtask-semantic-consistency.md)使用同一原件能力。跨 run 的 Artifact 工作记录按读取旧原件、创建增量记录处理。写入及读取形成执行事实。研究实验的验收范围见[研究实验记录](verify_results/research-experiment.md)。
