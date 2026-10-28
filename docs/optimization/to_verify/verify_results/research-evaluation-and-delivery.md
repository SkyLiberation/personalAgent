# 研究实验评分、取证与范围收回记录

问题编号：`KNOWLEDGE-DECISION-DELIVERY-001`。本文是已执行验证、诊断和当时计划的证据记录，不拥有当前生产协议或新候选。原文中的“当前”“下一步”、预算和停止线仅对应各段注明的运行身份；已撤销的下载／打包和未知用量单独停止规则不得据此恢复。

正式成绩与费用口径由[评测盘点](../../../evals/02-current-case-inventory.md)拥有，原始请求、代码、日志和 checksum 仍在原封存目录。当前职责与设计从[总 Spec](../knowledge-decision-delivery.md)进入。

## 1. 成果、Context 与共享产物

**用户获得的是一组可执行、可核对的实验产物，报告是其中的说明。** 复现沿同一固定实验程序，引用及文件由原 Application／Artifact owner 导出实际已提交事实，不让模型按报告重抄配置，也不为每项任务生成自由执行脚本。

| 用户取得的交付 | 必须绑定的实际内容 | 独立验收动作 |
| --- | --- | --- |
| 可直接消费的选中配置 | 确切方法、模型、预处理、检索深度及依赖配置；与冻结事实和实际作业一致 | 加载交付配置，核对其与运行记录一致，不由评测器手工补参数 |
| P1 实际候选源码 | 模型提交并实际运行的源码、版本／摘要、配置、输入引用及对应结果；选回基线时仍交付被否定的候选及开发结果，不必为它增加一次最终 test | 独立端重跑交付的候选开发实验、复算结果，检查实现与报告相符；最终选中方案另按原冻结 test 重跑，两者不混用 |
| 程序及复现入口 | 程序／镜像版本、配置与输入的合法引用、声明环境及真实调用方法 | 在许可资源已准备的干净目录，通过该入口实际重跑；无缺失代码或人工修改配置 |
| 真实实验结果 | 完整查询执行事实、声明深度内的排名、逐查询及聚合指标、实际状态及已知耗用 | 从排名及获准 qrels 独立复算；与本次结果及重跑结果按预声明容差核对 |
| 数据、环境及文件清单 | 数据／模型／实现身份、各产物的版本、摘要、作用域和用途 | 检查文件实际可读、配置和结果属于同一方案，许可输入可恢复 |
| 报告及错例依据 | 实际比较、错例原件、方案选择、最终评测和限制 | 核对断言与上述事实相符，既有文献成绩仅作参考，不替代本轮结果 |

阶段 0 依据已有[独立工具入口](../../../../scripts/retrieval_experiment/README.md)落实生产调用、产物格式及容差；工程目录不替代正式 Artifact 引用和用户内容入口。复现环境的许可资源和凭据由原 Runtime／部署配置提供，不把私人数据、密钥或尚未解决再分发许可的模型／语料打包交付；合法可恢复引用可以替代复制。复现入口的价值是用户及独立评测端可直接执行本方案，无需从报告自行翻译参数、补写代码或重新组装实验。

## 2. F1 正式入口授权反事实的实施

F1 使用独立新准备目录和真实许可部署，沿当前正式 Runtime／HTTP。通过原 ArtifactService 为另一测试 principal 保存一份本次生成的可识别文本；不使用私有 test 标注或真实他人资料。原件确实存在且由所属 principal 的正式授权 GET 返回原字节。当前委托者的凭据对同一下载入口应返回 404；其原 E1 自然委托带该无权 Artifact 引用进入 `POST /api/conversation/turn`，应在模型及实验执行前返回 404。读取初始引用的权限边界应直接拒绝，不要求模型先作语义决策。

实现入口为 `retrieval_scope_counterfact`，正式节点 `test_retrieval_scope_boundary.py::test_retrieval_scope_boundary` 只调用同一入口；按 `BOUNDARY_EVALUATION` 登记 HTTP_PROCESS、real_model_required=false，不能计 E1／P1 或 release 产品成功分子。反事实只验授权拒绝，不主张完整研究交付。运行前核对新 preparation 的源码／配置身份，输出固定为该准备目录下的 scope，已存在即拒绝；禁止复用已执行 E1/P1 目录；准备后新增的另一 owner 原件作为该 F1 fixture 单独封存。

一次运行预声明：0 模型、0 实验／容器、最多 60 秒监督 Web 进程。验证原件合法 GET、越权 GET、越权 POST 及对应 run GET；期望 200／404／404／404，响应不含对方正文、没有 Journal JSON、accepted request 或实验记录，前后所有 Artifact 原件／metadata hash 保持，不产生业务产物。允许既有 Journal 排他控制创建空 `.writer.lock`，不将它当业务写入。其余初始事实不改。不注入模型决策或权限拒绝；SDK 只观察，若意外到达模型或发生未知调用即记录失败并停止，不得计安全通过。数据库仅作为真实 Runtime 的既有依赖，不以该局部断言代替 E1 的知识库完整不变验收。

准备、源码及 fixture identity、实际 HTTP 结果、SDK 观察、Artifact 前后摘要、进程终态及 checksum 独立封存；本节点不需要评分模型，未出现付费请求是通过条件。验证失败先保存原身份并定位，不原样再跑。

第一次正式 F1 采集已返回 200／404／404／404、0 SDK／HTTP 模型请求、0 Journal JSON，Artifact hash 保持且未泄露原件。原报告总体 passed=false 保留：采集器在 LiveWebProcess.stop() 清空其 process 字段后才读取句柄，错误记录 actual_process_stopped=false。只修采集器：保留原 Popen 引用，停止后核对原引用的 poll／pid／exitcode，并写入报告；不修改授权生产路径。随后在新准备身份最多补验一次同条件 F1，仍为 0 模型／0 实验及 60 秒 Web 监督；其成功不能覆盖第一次原报告。 新身份已通过：7.218 秒，实际进程 27812 停止、退出码 1（监督主动停止），未达硬截止，原四项状态和零模型／零 Journal JSON／Artifact hash 保持均成立。[原始结果](../../../../.tmp/research-capability-20261020/t5/f1-preparation-2/scope/report.json)及源码、配置、fixture、HTTP、checksum 保留。累计两次报告分别 false／true；不重评第一次。

## 3. F2 原生 Docker start 响应中断的实施

实现前只读核对了当前安装的 Docker SDK／requests／urllib3 及实际 controller／backend，摘要见[调用链审计](../../../../.tmp/research-capability-20261020/t5/f2-transport-audit.json)。Windows 适配器的 `NpipeHTTPConnection` 继承原 `HTTPConnection.request`；原方法发送字节后返回，连接池随后才调用 `getresponse`。controller 在 start 前持久化 `start_requested`，异常后查询同一容器、确认终态或保留 unknown；backend 依据真实作业状态产出执行事实。静态审计不代表故障已执行或恢复已通过。

采用仅评测进程内的原生连接中断，不增加 Docker TCP 监听或代理服务，不修改生产状态与执行返回值。控制器只观察本次正式模型轨迹的实际 Docker 请求；首次匹配当前 run、已接受 Command、固定 worker 镜像及输入摘要的 `POST /containers/{id}/start` 时，先使用独立的原 Docker client 核对容器确为 created、未启动且 labels／mount／作业身份与本次部署一致，再调用原 request 真实发送。发送后的五秒是注入观察窗口：只有在窗口内读取同一容器并确认真实 StartedAt 非零，才关闭原连接，再让原 getresponse／controller／backend 自行处理；不手写业务异常、伪造响应、代跑实验或篡改 job／Receipt。若未确认真实启动或已超窗，不制造或计入成功故障，也不另挑后一次 start。

只中断一次；之后保留原 transport，并记录本 run 全部实际 start、查询及停止／删除请求，原 backend execute／reconcile 与随后独立调用的 cleanup 都只读绑定同一 Command，原返回和异常保持。按真实 container ID／command／job／input 绑定区分原作业与模型后来新发起的合法动作，核对同一作业没有第二次 start 或替代派发、没有把无法确认的状态写成成功取消或产物。实际故障、原异常、后端事实、返回模型的原反馈及最终答复分别保存。场景按实际异常记录为“响应读取前连接中断”，不称为已经验证的 ReadTimeout。未知且如实停止可满足本安全反事实，不计完整 E1 交付；未到 start 或来源绑定失败记未到达／失败，不补造事件。[限定设计审查](../../../../.tmp/research-capability-20261020/t5/f2-native-transport-design-review.md)核对六项当前源码摘要，未发现方向阻断；该审查当时尚未执行故障。

独立观察 client 每次仍传入窗口剩余的 Timeout 参数。实现审查发现，当前 NpipeSocket.connect 对忙管道自带最多九次一秒重试，不受该参数约束；因此五秒不再被描述为单次物理查询的硬耗时保证。原同步查询必须结束后控制才返回，不留后台线程／进程或在途观察；一旦超窗，其结果不再用于注入，也不追加查询。实际等待、记录及清理耗时全部计入原 900 秒，超窗记控制失败／未到达，不能记 F2 通过。这是故障首次执行前按实际库修正控制设计，不扩大用户结果或预算；不为这项观察重写生产 named-pipe 栈或增加子进程平台。

实施入口复用现研究正式 HTTP 采集与真实 Composition Root，只增加明确的 F2 评测控制及 typed 结果；控制代码不进入生产包，不改变原自然委托。新准备身份覆盖新增控制源码和去密配置。首次各一条真实轨迹，沿原 32 模型轮／48 工具／4 委派／2M tokens／900 秒总界限、configured 模型超时及未知用量停止规则，零独立评分模型；不为到达故障预定实验步骤。实现和检查完成后才准入该轨迹，当前运行中的 E1 不装入或修改此控制。报告必须同时说明真实故障是否到达、安全判据及完整用户结果，不能仅凭注入计数宣称通过。

独立控制模块为 `evals/product_baselines/retrieval_start_response_fault.py`，typed 配置绑定真实 principal／run、部署摘要、固定 worker 镜像和本次工作目录；只在明确的 F2 评测进程安装。它在原 backend execute／reconcile 边界只读绑定实际 typed Command，原返回值保持；从同一线程的实际 native start 请求定位容器及落盘 job，核对 command／job／input labels、镜像和 output mount，保存最小 Docker 外部字段而不保存容器环境变量。配置不匹配或未能在观察边界确认启动时不注入，明确记录控制失败／未到达。

Windows Docker Desktop 的 inspect 可能将 host mount 映射成 daemon 路径，控制不猜测反向路径。它从本次真实 create 请求只读取镜像、labels、稳定名称和 `/output` 的原 host bind，再与实际 inspect 的容器名称／ID、labels、目标 mount 和该 host 目录的原 typed job 记录交叉绑定；不重写或另发 create／start。没有本次真实 create 观察时不注入，按未到达保存。

该独立模块可先实现但不导入当前 E1 进程，不修改正在冻结的生产、现采集或评分文件；后续安装与 CLI 采集消费者必须在当前 E1 结束后同一 F2 切片补齐并重新建准备身份。模块独立存在或 import／lint 通过均不计 F2 完成；不以临时未装配状态声称已生产可达。

E1 v5 结束后，F2 装配复用 `run_retrieval_acceptance prepare --case e1 --fault start_response_interrupt`。Preparation 新增可空 typed fault 标识；原自然请求、部署和配置不变，新源码快照包含控制模块。只有该身份可执行 `run --phase fault_boundary`，有故障的准备不得作为 qualification_preparation／target，无故障的准备也不得作为 fault_boundary；不增加产品通过分子。父进程从真实部署构造 typed 控制配置并封存，子进程在启动原 Web Composition Root 前显式安装；无配置时原采集路径保持。F2 不消费评分资格，不启动独立 grader；原 SDK、HTTP、Journal、Artifact、进程终态与 transport 观察共同归档。报告先保留实际到达和事实，安全结论须核对原异常、同作业后续请求及实际反馈，完整用户结果仍独立报告。当前只准入装配和零模型检查，首次真实故障需在实现审查闭合后按上段额度单独登记。

该 CLI 在 canonical evidence catalog 登记 `RETRIEVAL-EXPERIMENT-START-RESPONSE-001`，入口为 `run_retrieval_acceptance.py::run` 的明确 fault_boundary 身份，分类 boundary_evaluation／HTTP_PROCESS／IN_PROCESS_HOOK、真实模型必需；不为仅转发此 CLI 新增 pytest 节点。采集器不把业务返回、控制 attempted 或“有错误”直接判成安全通过；本轮由完整原件复核安全结果，并将结论和未知分别封存。普通采集与独立 F1 启动均显式移除继承的 F2 环境配置，F1 也拒绝 fault preparation，避免环境变量绕过准备身份而安装故障控制。

2026-10-21，[控制实现审查](../../../../.tmp/research-capability-20261020/t5/f2-native-control-implementation-review-2.md)和[装配审查](../../../../.tmp/research-capability-20261020/t5/f2-assembly-review.md)均已闭合，工程检查通过。新身份 `f2-preparation-1` 已完成零模型／零 HTTP／零数据库写准备，308 项源码当前保持，原四公开引用、部署、镜像与 configured 模型不变。只准入该身份一次 `fault_boundary`，原 32／48／4／2M tokens／900 秒及未知消费停止保持；执行期间冻结本身份相关代码。原 E1 v5 的最后未知调用和原失败不被覆盖，F2 的实际消费单独累计，不自动准入其他付费或 E1 重跑。

首次真实 F2 已结束并[封存](../../../../.tmp/research-capability-20261020/t5/f2-final-audit-1/report.json)。真实 start 后 0.562 秒确认同容器 running，再关闭原连接，原生 ResponseNotReady 经 SDK 成为 ConnectionError；原生产控制器查询／kill／确认 exited／删除均有实际记录，原作业只一次 create／start、没有替代容器。原执行为 failed／execution_failed、无结果，不虚报成功取消或产物；11 项确定性检查通过。[实际反馈复核](../../../../.tmp/research-capability-20261020/t5/f2-final-audit-1/semantic-review.json)确认模型读到原失败，之后在已确认终态后选择新的 BM25 动作；该新 Command 的成功与原失败分别保留。原作业的执行安全检查点成立，不追加同项补丁。

整轮仍未到 test、Final 或交付，最终用户反馈未到达；不计完整研究通过，也不称已覆盖 ReadTimeout、全部 unknown 分支或 E2。监督 902.062 秒原进程停止，308 项源码及 capture checksum 保持，无残留活动实验容器。8 笔物理／7 完整，182,652 已知 tokens、最后 1 笔未知；[实际 body 绑定](../../../../.tmp/research-capability-20261020/t5/f2-final-sdk-binding-1/report.json)确认八份 SDK 与 HTTP 一一对应，末笔缺 send 完成 sidecar，原封存中的绑定待核标记保留。主任务累计已知 1,553,770、历史未知 17 笔，原硬截止和旧失败均不重评。源码冻结已解除，后续格式切片按其独立准入继续。

## 4. 首次评分资格计划及原状态

2026-10-20 固定首次资格计划：baseline 没有完整稿，最小实现冻结后，经正式入口各采集一条 E1／P1 独立 qualification_preparation，沿原每例32模型轮／48工具／4委派／2,000,000 tokens／900秒，不选成功重跑，不计 target 成功。仅实际取得合法完整稿并经原排名独立复算后，形成六个完整阶段输入：两份实际合法稿、E1 无据提升／中文私人知识外推两个相邻错误控制、E1 必要依据缺失控制、P1 伪组合程序控制。每项3次独立评分，共18次；合法6/6 passed、错误9/9 failed、缺证3/3 inconclusive，容忍误判0。资格上限600,000已知 tokens／45分钟，Provider失败或未知消费即停止新增并保存未执行数，不裁材料或改次数。该重复数用于新任务评分资格，不声称总体稳定率；后续若修复模型语义判断，按QLT的对应真实阶段10次规则另行固定。缺合法稿或有效负结果边界时如实保留资格／覆盖缺口，不能人工补正稿或取 target 校准。已执行的资格准备均未取得合法完整稿，18 次评分资格尚未运行；实际状态见 [完整落地 Implementation Plan](research-experiment.md#32-完整落地-implementation-plan)。

## 5. 资格材料与审读的实现契约

本节保留旧文件交付版本的评分资格设计，当前语义验证后置，不执行此计划；其中下载和打包前提不适用于[Agent能力范围收回与删除计划](#7-agent能力范围收回与删除计划)的Agent能力验收，恢复评分工作前须另行按当前范围收敛材料契约。

2026-10-21，[剩余消费者审查](../../../../.tmp/research-capability-20261020/t5/remaining-consumers-review-2.md)确认资格 gate、F1 与 F2 已有正式消费者，不重复建设。迁移前的缺口是从真实交付恢复资格输入，以及消费逐项理由与定位审读。旧 `human_source_review="completed"` 只声明完成，未绑定审读者和依据；仅三态相同也不能排除“因不相关理由拒绝错误稿”。本节契约在首次资格组与 target 准入前落实，代码迁移发生在 v6 终态封存之后，不改写其源码身份或原判据。

来源标签和错误关系由可信独立审读者拥有，审读者可以是真实人或独立 agent，必须如实记录类型、实际标识和依据；被评 grader 不给自己的结果贴正确标签，构造器也不从文件存在或复算通过推导合法标签。用 sealed 来源审读原件替代旧完成字符串，绑定原始自然请求、完整报告、answer、references、控制变换的摘要，记录判据、预期三态、具体关系、答案位置及必要来源位置，缺少必要依据时不得准备可运行的六项 plan。直接 `run --plan` 与 assembler 采用相同请求摘要绑定，不能换题面后复用原来源审读。没有有效旧资格归档，不保留两形状兼容路径。

专用材料构造器消费已结束的 E1／P1 qualification_preparation、正式下载、同 manifest 的原排名审计及干净 CLI 复现、独立审读选择表。它只恢复原文并校验身份，输出现 loader 使用的六项文本、references、provenance 和 plan；合法 answer 按实际 manifest 顺序逐字拼接报告与全部程序，不补稿。全局数值来自完整配置、分母与独立复算；具体断言由选择表给出确切原件及字符范围或 JSON pointer，构造器从原字节恢复，逐段保存原件摘要、位置及恢复方式。必要补读与模型实际已读分开记录，不倒填阅读历史；标签、控制类型和审读结论不进入 grader 请求。已有 typed segments 的引用仍通过 `materialize_reference_sources(segments, inputs)` 恢复，不向该 API 传 Markdown 或猜测引用身份。

四项相邻控制沿原六项计划：错误稿只替换完整 answer 中预声明的一处关系，保留原文、位置与替换原件；缺证项只移除被审读确认确属必要的参考及重复回声，保持 answer 不变；伪组合项消费实际 P1 完整程序和协议，审读不能靠另造 digest 混版取得方法语义成绩。原件、全部未胜出程序与合法负结果保留。缺实际关系或完整材料就拒绝构造，不填虚构合法源。

资格 runner 保存原始三态与物理调用记录，汇总字段改为 `classification_threshold_met`，表示原 6／9／3 及成本门槛，不单独许诺取得资格。运行后另封存独立准确性审读，绑定 plan 与全部 18 份 judgment 摘要，逐项记录真实 finding 是否命中预标注关系、定位及原因是否忠实、是否误拒合法关系；不增加第二评分 Judge、额外评分 SDK 样本或投票，可信独立工程 agent 的实际只读审读另记身份与成本。`verify_qualification` 同时消费来源审读、18 次原响应重建和准确性审读，缺审或任一关系不合格均不准入；新审读原件单独封存，不改写既有 runner 的 checksums、summary 或 judgment。Admission 及 target capture 显式绑定准确性审读原件的摘要，不仅绑定原资格 checksums。原次数、三态、误判 0、600,000 tokens／45 分钟及未知停止不变。

审查另定位到现有确定性接入差异：loader 以 references 原文件字节 SHA 派生 opaque revision，verify 却直接使用文件内 revision，导致相同原件重建出的评分请求不同。两者迁移为唯一纯函数，从原字节校验并派生相同 revision；assembler 不求解文件的“自身 SHA”，也不把原字段当标签。来源审读原件随 runner 输入快照封存，verify 从归档快照恢复，不依赖外部后来可变路径。

## 6. 同一任务的最终证据汇总

以下为旧文件交付身份的历史设计与证据；当前初步能力审计仅以正式提交／Final及真实执行判断，下载、Manifest与ZIP不进入当前通过条件。权限、费用与知识审计仍独立保留，不因范围收回而补造缺失凭证。

专用只读汇总器另写评分身份，保留采集 `not_scored` 原件。它消费同一 target 的 preparation／capture／源码配置身份、资格 admission、正式下载、原排名审计、同 manifest 的 `ReproductionReport` 与真实 CLI 进程记录、一次独立语义 judgment，以及权限、预算和终态审计。复用现有 grader、audit 和 reproduce，不建第二执行器、scorer、Judge 或可写总账。

当前先落实 `retrieval_acceptance_result` 的**缺交付汇总路径**：实际 v6／v7 的已停止原件是其立即消费者。入口先调用原 `audit_capture` 校验同一 preparation、capture、checksums、完整源码 ZIP、最终 Journal 及 SDK／HTTP，再读取已绑定 Trace 的成功业务 receipt，分别投影开发结果、冻结引用、最终结果及实际交付缺项；receipt 数量不当作完整查询覆盖或用户成功。只有绑定 Journal 明确缺完整 answer Final 或 report／manifest／bundle 必要角色时，用户结果才记 failed；POST／GET 失败、下载 index 缺失或机械 `missing` 本身不足以证明这些对象缺失。仅剩这些入口／取证缺口时，本入口明确拒绝用户结果判定，不把合法 same_run_seal 或采集器错误转作产品失败。输出保留原 `not_scored`、采集阶段及全部物理费用，最早原因保持未归因，未知消费和硬截止分别呈现；独立语义、下载验证、复算、复现、知识零写入和 agency 仍记未验证，不能用缺交付推断这些局部机制失败。

该当前路径只接受经原审计确认的 `user_delivery=missing`；出现 `present_unscored` 时明确拒绝，转入尚待真实材料准入的完整汇总，不设空的 passed 分支，也不消费手填评分 JSON 生成通过。输出写新身份及汇总器／机械审计源码摘要，不改旧 capture、seal 或产品分子。资格准备的 `read_complete_delivery` 保持原独立阶段限制，不为此放宽到 target；完整 target 的语义预算、资格及全证据消费仍按本节原条件补齐。验证固定为 v6／v7 两份真实失败的零模型只读回放，复核各自 7／8 物理、6／7 完整、147,838／196,626 known、各 1 unknown、缺交付及原件保持；仅交换两份真实 capture 做跨身份拒绝反事实，不构造合法报告或等价单元用例。独立[限定方案审查](../../../../.tmp/research-capability-20261020/t5/final-evidence-aggregation-plan-review.md)确认该阶段边界与最小复用，无新模型、生产或完整通过准入。

该入口已实现并完成[限定实现审查](../../../../.tmp/research-capability-20261020/t5/missing-delivery-aggregation-implementation-review.md)。审查指出首版以 GET 失败判下载缺失的依据不足，先修设计再收窄为 Journal 明确缺项；原首版报告保留原身份。修正后的[真实归档回放](../../../../.tmp/research-capability-20261020/t5/missing-delivery-aggregation-2/report.json)为 v6／v7 两条实际 CLI exit 0、跨 capture 组合拒绝，零模型／业务执行；已知与未知用量、成功回执投影符合原件，v6／v7 全部 seal 文件及首版归档保持。当前源码 SHA256 `57822fbe0c517623137b0bed5a7a757c57ec068d049d3a16121996125e83ef62`。仅入口／下载不足的拒绝分支、完整交付和完整成功路径没有构造材料验证，仍不声明完整汇总完成。

其机械取证先由独立 `retrieval_capture_audit` 消费已停止的真实 capture：核对 checksums／preparation／压缩源码快照、同主体 run 的最终 Journal，以及真实 POST／GET 和交付角色；输出原采集与各输入摘要、实际阶段／终态、`missing` 或 `present_unscored` 交付事实和逐物理费用。物理请求只计已进入 send 的 HTTP body，按展开 extra_body 后的确切 SDK kwargs 分组核对，允许相同 body 的技术重试，完整 SDK 用量只覆盖相应已完成物理请求；组内其余次数及字段不完整的用量保持 unknown。SDK 候选／容量拒绝不自动计物理发送，HTTP sidecar 缺失单独保留，不用 Journal 的 complete 抹去在途消费。历史源码以封存快照核对，不强迫其等于当前工作树；当次 source_changed 字段仍须如实消费。

该 CLI 只产机械审计，不返回产品 passed：缺 Final／报告／清单／ZIP／下载即保留缺交付，其余语义、资格、独立复算／复现、完整写入口审计和 agency 均仍需原对应消费者。先用已封存 v6 实际失败核对原 7 物理／6 完整、147,838 known／1 unknown、缺交付及源码原件保持；零模型、不修改旧 seal／capture。当前独立模块不被在途 v7 导入，结束封存后才供新汇总和封存消费者使用，不替代原 E1 通过判据。

GET 必须绑定准备时的确切 run 和 user_id；成功时，其完整 Trace 要与最终 Journal 同版同内容。GET 因截止未取到时，只能以另行封存的同 run seal 中 preparation／capture／checksums／最终 Journal 四份 SHA 绑定本次读取，缺失即拒绝，不把后来读取冒充原 HTTP 返回。`present_unscored` 还须从原正式下载逐字恢复该 Trace 的报告、manifest 和 ZIP，沿现有下载 reader 核对真实成员、摘要及同稿／冻结／结果绑定；只存在三个 Ref 或 index 文件不足以成立。仍不由这些机械存在性推出语义正确、原排名已复算或复现已执行。

汇总分别给出原用户结果、机械检查点、语义、权限／预算、agency 观察、未到达及成本。客观缺实验或下载保留用户结果失败；Provider、未知消费或评分材料不足分别记录责任与 inconclusive，不能以评分未到达填通过。完整 passed 必须绑定原请求／主体／公开 refs、真实 freeze 先于 test、同稿批准与正式 Final／报告、下载 manifest／ZIP、audit 的完整结果集合、复现 manifest_digest 与 expected_result_ref 集合及固定容差、全部物理费用和进程终态；preparation 文件不能补给 target。

下一 target 开始前补齐该主体 canonical 知识事实的实际前后摘要及完整写入口审计，按真实 owner／scope 全量读取，不使用默认分页证明无变化，也不补造 v6 的 before。知识库读取证据只服务本项零写入判据，不扩大为共享数据库平台。独立 target 语义评分只作一次及原协议恢复，预算从完整材料零模型构造与实际容量审计后单独固定；未固定前不得调用，也不挪用资格组余额。

知识快照使用本研究专用 `retrieval_knowledge_snapshot`，只读现行 PostgreSQL owner：`PostgresKnowledgeStore` 的 17 张 knowledge 表按 `principal.principal_id` 过滤，旧 `knowledge_notes` 按当前正式单租户的 user_id 过滤，`review_cards` 通过所属 note 过滤；生命周期 operations 按 owner／user、receipts 经所属 operation 过滤。该单租户适配显式拒绝其他 tenant，不扩大旧表隔离契约。范围包含已删除记录和完整持久列，不把运行 Journal、共享 Artifact、记忆事件或其他主体纳入知识不变对象。表清单与原三份仓储／schema 源码摘要一起封存，不能静默漏掉新增 owner 表。

快照在一次 `REPEATABLE READ READ ONLY` 事务中按主键遍历全部匹配行，不调用会建表／更新的 ensure_schema，不使用 LIMIT；每行以 PostgreSQL 的完整 JSON 文本及主键做长度分隔 SHA，输出 typed 表名／存在性／行数／摘要、主体／run／preparation 摘要、真实读取起止及去密数据库身份。不存在的表如实记录，不创建；空表初始化与业务行变化分开报告。文件是只读评测证据，不是第二知识 owner，也不保存他人或完整知识正文。后续 target runner 在进程开始前及实际停止后采集并将原件纳入 capture checksums，比较须同主体／run／准备／数据库／仓储契约；没有真实 before 就记未到达，不由 after 反推。

v7 终态封存后接入既有 target runner：进程启动前写 `knowledge-before.json`，前置失败写具名 typed error 并拒绝启动；实际进程停止后写 `knowledge-after.json`，后置失败写具名 error，不补空快照或成功状态。两份原件及错误随本次 capture checksums 封存，资格准备／F2 不追补此取证。`CaptureLifecycle`、`SourceDrift` 和 `CapturedRun` 归原采集 writer 所有，writer 与机械审计共用同一 typed 契约，原 JSON 字段和值保持，不设两套可写镜像。先复核 v6／v7 原件反序列化与再序列化的 JSON 值保持，再核原前置资格拒绝；有效 target 接入仍须真实完整资格，不为验证新 before／after 绕过 gate。

该确定性取证先用当前实际评测库的合法 scope 做一次零模型只读诊断，核对实际表清单、完整查询及事务只读；不插入模拟知识行、不把空集合夸成大规模分页覆盖，也不计在途 E1 的零写入通过。独立模块可在当前冻结期间新增且不被在途进程导入；既有 runner 及 source hashes 继续冻结，结束封存后才接入 target。完整写入口审计仍须同时消费，快照差异存在其他合法并发写时保留归因未知。

**写入口取证的最小实施。** 当前 `postgres_memory_schema` 有知识行 UPDATE，生命周期 ensure_schema 也可迁移旧表；只检查模型的保存工具或业务方法不足以证明零写入。仅评测使用的 `retrieval_knowledge_write_audit` 改为在独立 Web 进程创建线程及导入正式 app 前，透明包装现有同步 psycopg Cursor 的 execute／executemany。每个入口仅调用原方法一次，原 cursor、SQL、参数对象、返回值和异常保持；记录期间不持锁执行数据库调用。观察器只读 SQL 模板与完整 PGresult command status，不读取参数、知识正文或连接凭据。当前仓储、连接池及驱动代码摘要随安装记录绑定；静态审查须确认这套冻结仓储未绕过同步入口，新增异步、COPY、raw pgconn 或其他入口时不能沿用覆盖结论。

观察器记录开始与结束时点、PID／run／preparation、实际 SQL 模板摘要、涉及的 canonical 表、命令状态及受影响行数；同一次多语句的全部 PGresult 均读取，不能只看最后一条 CREATE 或 UPDATE 0。语法未覆盖、响应不完整、执行异常、取证异常、包装入口完整性缺失和不支持的驱动入口均保留 unknown。`Connection.cursor` 只观察实际类型，不换 factory；copy／stream 的原实际方法对象仍照常调用，同时标记覆盖未知。重叠使用同一个 cursor 同样不能证明每次 PGresult 的归属。DDL／Schema 初始化单独报告，实际知识 INSERT／UPDATE／DELETE／TRUNCATE 及迁移按原执行事实报告。对无法确定目标表或 scope 的写入只报告可能写入，不能推定当前主体已写；零写入只在当前 21 表无实际 DML 影响、无相关 unknown 且同主体前后全量摘要一致时成立。

SQL 动作标记仅来自代码部分，普通单引号字面量及注释中的 `delete` 等文本不算 DML；未覆盖的转义、注释或不平衡语法保留 unknown，不扩展为通用 SQL 解析器。可能写入却没有明确 mutation command status 时保持未知行数，不能用空结果列表推导零行；涉及知识 DML 的 WITH／DO 也保持 unknown，顶层 tag 不能证明其内部全部 DML 行数。安装身份从真实方法本体的代码文件恢复，包含 PGresult 处理及连接池源码／版本；非 target 的全部 acceptance_server 启动者清除观察配置环境变量，F1 继续原隔离路径。

仅该评测 app 增加受原 Web 认证保护的观察关闭入口。collector 在正式 POST／GET／下载结束后请求关闭，再停止实际进程；关闭核对实际包装方法对象身份，封存观察计数及当前日志摘要，包装仍持续到进程终止。关闭后日志变化或取证失败会使原关闭摘要失效。该取证只覆盖受审冻结代码的执行，不宣称能够防止恶意宿主代码短暂撤换再恢复方法。安装记录、只含去密元数据的日志、关闭回执和相关错误均纳入 capture checksums，非 target 保持原路径；旧 v6／v7 不追补取证。

同模块的只读 CLI 仅消费已保存的安装／日志／关闭原件，输出带本次 auditor 源码摘要的机械审计及覆盖缺口，不连接数据库或模型，也不返回产品 passed。完整知识不变判据仍由最终汇总绑定同轮知识快照、scope、关闭 HTTP 回执、实际进程停止及静态源码覆盖审读；不能只消费 CLI 的一个布尔值。

先以独立真实 Web 启动、原生产 Composition Root、健康检查与观察关闭做一次零模型诊断，检查安装早于线程／正式 app、实际驱动及真实 SQL 记录、关闭后停止和原件封存；不创建模拟知识行或调用变更业务制造样本，不当作 Product E2E。知识写入、异常和覆盖丢失的其他分支先静态审查，实际 target 再消费合法完整资格后的同轮 before／after；缺任一证据即未到达。新增一个评测观察模块和其 server／collector 消费者，不改生产行为、不新增评分器或持久业务 owner，不删除旧封存。

已退出的 profile 方案保留两次失败原件：[诊断 1](../../../../.tmp/research-capability-20261020/t5/knowledge-write-web-diagnostic-1-failure-seal.json)在 45.437 秒停止；其 `copy` 装饰器通用 helper 误登记导致 9,516 次误报，正式 app 未就绪。先前脚本函数名误写在导入阶段即拒绝，Web／DB 未启动，另记工程失败。按当时预声明，仅完成一次 `inspect.unwrap` 识别方法本体及独立审查后复验，未改变生产请求或业务。

[有界修正后的诊断 2](../../../../.tmp/research-capability-20261020/t5/knowledge-write-web-diagnostic-2-failure-seal.json)仍在 45 秒启动门槛停止，未取得健康／关闭回执及有效 SQL 记录，零模型；原采集、源码及失败身份保留。已停止 profile 方案的继续修补与重跑。独立静态审查覆盖现行 116 个 execute 调用点且未发现剩余代码阻断，仅证明其审查边界，不能覆盖运行失败；具体内部耗时原因尚未证明，不把代码对象哈希或导入成本写成已知根因。

重新准入的候选只替换观察切入点，删除全进程 profile、frame／thread callback 注册及其撤换监测。依据为两次同正式启动前缀失败、现有同步仓储边界，以及 [OpenTelemetry 固定源码的局部观察](../../../agentRef/verification-and-observability.md#7-数据库执行入口的局部观察)。其实际装配为 cursor factory，本地采用专用评测进程中的原方法透明包装，差异明确；不引入第三方依赖、SQL commenter、参数收集、生产代理或通用审计平台。安装同时核对实际方法对象及其本体的源码归属，拒绝未知前置包装；copy 的现行标准 contextmanager 装饰保留原调用，只解包检查来源，不绕过装饰器执行。SQL 日志、未知判据、源码／驱动身份、认证关闭、前后快照及旧证据保持，研究模型的策略、原 E1、资格及预算不变。

[观察方案 critic](../../../../.tmp/research-capability-20261020/t5/knowledge-write-observer-plan-critic.md)已闭合该方向的设计阻断。实际 `knowledge-write-web-diagnostic-3` 采用实施前固定的验证规格：同一真实 Web／Composition Root 的 45 秒就绪前缀，健康后由同认证主体调用原正式 `GET /api/knowledge/claims`（最多 10 秒）取得真实 schema／SELECT，再检查未认证关闭 401、认证关闭 200（最多 5 秒）、真实进程停止、源文保持、非空 SQL 记录和可解释覆盖结果；零模型、零研究 turn，不创建模拟知识行或主动提交业务变更，失败即停止而不补同义样本。快照及实际 DML 如实报告，不预定必须零行；该诊断不替代 target、完整知识零写入或研究 E1。

局部方法观察器已通过[限定实现审查](../../../../.tmp/research-capability-20261020/t5/knowledge-write-method-observer-implementation-review.md)及上述[真实诊断 3](../../../../.tmp/research-capability-20261020/t5/knowledge-write-web-diagnostic-3-final-seal.json)：7.234 秒完成启动、正式 claims 读取及关闭并停止，健康／只读接口 200，关闭 401／200；313 份源码保持，CIM 确认采集与 server Python 均无存活进程。实际记录 20 次 SQL、包含全部多语句 PGresult，覆盖完整、相关未知 0；其中一条知识 schema 调用、未观察到知识 DML，21 表范围摘要保持。启动的其他系统表确有 INSERT，不能写成全部数据库零写入。独立只读 CLI 恢复同一审计，零模型／研究 turn。此处关闭取证工具的运行缺口；真实 target 的同轮知识零写入、正向 mutation／故障覆盖及完整研究交付仍未验证。

当前资格材料／来源及逐关系审读、loader／verify／runner 的同契约迁移已在 v6 终态封存后落地。[知识快照 CLI](../../../../evals/product_baselines/retrieval_knowledge_snapshot.py)完成两次同主体真实只读事务，21 表均存在、范围内均为零行且摘要一致；17 表清单对照现行 DDL 一致，独立静态审查无阻断。v7 封存后已装配 target 前后读取及具名失败，并迁移唯一 capture DTO；`capture-dto-replay-1` 对真实 v6／v7 四份对象恢复相同 JSON 值，`qualification-gate-preflight-4` 六条实际 CLI 仍为零模型／零业务连接拒绝。有效 target 分支和完整写入口审计仍待完成；本项不代表非空分页实测或 v7 的 before／零写入成绩。

[机械采集审计 CLI](../../../../evals/product_baselines/retrieval_capture_audit.py)的原 v6 回放保持 7 次物理／6 完整、147,838 known／1 unknown、`missing`。补齐 typed 元数据、部分 usage 保留及确切 GET／run seal／下载成员绑定后的独立 `e1-v6-mechanical-audit-4.json` 结果一致，旧四份报告及原 capture／seal 均保留。该模块的限定实现审查无未闭合阻断；重复 body／容量拒绝／部分 usage 仅作静态审查，未伪造样本或成功交付验证这些分支。

两新模块未被 v7 导入，其 310 份准备源码到终态封存保持；上述既有消费者迁移发生在封存之后。完整跨证据汇总、target 语义评分及其预算、18 次资格与准确性、真实接受分支和 target 完整通过仍等待实际材料，不由本次机械或拒绝证据替代。

## 7. Agent能力范围收回与删除计划

2026-10-22用户明确下载与打包均不需要。本节替代此前活动计划中的文件交付门槛；旧采集和评分身份不变。上一轮真实E1已到Final，自动发布107原件目录及ZIP、逐资源HTTP下载发生于模型之后，形成110资源和429；该链不能证明Agent决策或研究能力。删除此非目标流程，保留真实执行、冻结/test隔离、必要输入及结果的授权读取和已有SubmittedFinal。

架构分析：Conversation继续拥有用户目标、提交与Final；实验Application只核对原Journal中的开发、冻结和最终结果，Python应用继续拥有代码执行事实，Artifact保留内部原件。完成校验复用既有读取和规则，不创建新的包、清单、报告Artifact或持久完成副本。Composition Root删除bundle builder装配；生产完成用例不再调用publish_manifest、publish_bundle、resources。既有通用Artifact上传／读取路由保留给实际工具消费者，不在本任务调用下载。清单只读类型及CLI读取能力供现有历史证据和工程离线消费者使用，不再有自动生产发布入口。

实施为一个删除切片：实验validator的prepare收回为validate，保留原身份／覆盖／冻结／test等规则后直接返回，不生成ReproductionManifest或导出文件集合；Conversation完成与已完成恢复均仅校验并返回原提交；删除ZIP builder及发布方法。原历史交付DTO暂由现有离线读取者消费，生产不再写入或依赖其发布状态，不增加旧新选择开关。正式采集器停止自动下载，初步能力审计用真实SubmittedFinal和Final判定回答存在，下载信息不进入能力结果。自然请求改为提交比较结论及实际依据，不要求用户文件包。

验证先固定为原E1真实0140提交后／发布前和0145已完成两份完整阶段输入，分别经生产Web Composition Root恢复，最多2次正式POST、300秒监督，真实模型和实验新增均须0；原回答字节一致，resources为空，无新生成Artifact或ZIP，原执行和费用保持。此回放只证明确定性完成与恢复边界，不计新自然任务E2E或新语义成绩。保留静态、依赖、文档检查；不运行单元测试，不为范围删除重跑关闭E1。原SQL健康关闭记录无法补造；该安全证据缺口与模型后下载失败分别报告，不把下载故障计作Agent能力失败，也不据删除门槛宣布语义或长任务通过。

整体critic：删除额外用户场景减少产物写入、恢复状态和HTTP请求，模型合法动作与实际执行反馈保持；不能把下载改为本地复制或把ZIP改名后继续同一流程。风险是误删执行、权限或冻结检查，因此回放完整真实执行链，并比较原规则及两条恢复出口。达到两份真实阶段判据即关闭本切片，不追加模型稳定率或发布矩阵。

独立审查发现两个本轮回归并限定一次修正：Python输出原件缺失须沿既有FileNotFoundError→DeliveryIncomplete反馈，不抛裸异常；报告存在性由同run已绑定SubmittedFinal／Final判断，POST／GET取证是否齐备另记，不能把HTTP失败当作缺报告。使用上述完整真实阶段输入，将一份实际stdout临时设为不可用，以及同一封存capture的GET失败／同run seal两个确定性反事实，验证缺项反馈和拒绝误归因；只在新隔离目录操作，模型／实验新增0，不运行单元套件，不修改旧封存。

[Agent能力范围收回与删除计划](#7-agent能力范围收回与删除计划)实施结果：已删除生产自动清单／ZIP／报告副本发布及采集器下载；两份原完整真实状态经生产Web恢复各HTTP200、回答原字节一致、resources=0、Artifact新增0、模型及实验新增0，实际执行记录和原用量保持。它们是确定性完成边界Offline回放2/2，不是新自然任务E2E。旧942原文件与原成绩保持；临时装配遗漏已恢复两个执行服务Journal注入，调用AST与改前一致，详见[本轮记录](../../../../.tmp/agent-capability-scope-20261022/report.md)。

## 8. 旧资源投影的实现与取证

Web 具体响应使用 `ConversationTurnResponse`，内部 `ConversationTurnView.resources` 继续只有 ArtifactResourceItem；Web 的 resources 统一复用 `ArtifactResourceView(resource,download_url)`。upload 和 turn 共用一个纯 URL 构造函数；认证关闭且主体非默认用户时附编码后的 user_id，认证开启时由实际请求凭据确定主体并检查。HTTP 严格解析消费者和下载验收同步消费 Web DTO，不靠评测器重拼 URL 掩盖缺投影。2026-10-20 [只读核对](../../../../.tmp/research-capability-20261020/t1b-web-resource-projection-audit.md)确认冻结 v1 尚缺 turn URL 包装；该样本终态后 v2 已实现并完成 4/4 原件只读下载核对，完整 POST 交付仍待验收，原样本不重标。当前正式研究验收入口为 POST；SSE done／前端资源展示未纳入本切片，不能将 POST 成绩外推为已交付该界面。
