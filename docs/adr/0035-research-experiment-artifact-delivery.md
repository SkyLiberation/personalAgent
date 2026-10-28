# ADR 0035：研究实验与交付复用原事实入口

## 背景与决定

正式自然委托已到达生产 HTTP 入口与真实模型，合法 SciFact 材料和环境说明已被消费，但实发请求的完整工具面没有实验提交能力。E1 原用户结果 0/1、超时及未知消费保持；同轨迹局部缺口和准入范围由[唯一研究 Spec](../optimization/to_verify/verify_results/research-experiment.md#t0-同轨迹局部准入复审)拥有。本决定记录必要的跨模块、权限、持久执行及完成边界；不代表实现或产品验收已通过。

在原 Runtime 装配一个检索实验 Application 和一个受治理业务工具，经 typed Port 调用唯一工程引擎。模型选择开发实验、提出及实现候选、解释真实错例并决定冻结；代码校验权限、身份、冻结和不变量。当前部署固定许可材料、模型、镜像和额度，不建立通用环境注册中心、交互 Shell 或后台作业平台。P1 程序扩展按其正式轨迹另行准入。

## 事实归属与防护

ArtifactService 继续拥有原始字节、不可变引用、元数据和完整 producer 绑定；模型草稿 create／patch、机器实验产物、报告发布使用同一 owner。读取、搜索、修改和执行消费同一确切快照与坐标。内部摘要统一为 UTF-8 原字节 SHA-256，模型不提供 owner、路径、producer 或摘要。新上传身份绑定认证主体及完整不可变描述，避免不同主体覆盖。

当前任务可读集合只投影正式初始引用和已提交的 typed 来源；只读材料不自动获得草稿修改或实验用途。Gateway 传播实际 typed ExecutionScope／调用身份，工具拒绝缺失或伪造 context。可读、可改、开发执行与冻结后最终评分分别检查；私有 test 标签只交受信 scorer，不向模型或候选环境授权。

原 InteractionTrace／Journal 保存变更工具派发前的不可变已接受请求和后续执行事实。请求含 action_id、scope、完整 typed payload 及摘要；同身份异 payload 拒绝。单宿主同 run 排他，进入后刷新磁盘，职责内字段沿同一 latest 提交，不能由外层旧副本覆盖结果。Artifact 的局部 producer 恢复和 Conversation 的调用前接受分别履责，不互相替代。

真实 v10 检查点已证明接受记录早于同批模型费用、已接纳 Plan 和 Context 的完整提交。最小修正由 Conversation 在正常动作的 Plan／continue 准入后、工具接受前，复用原完整 `_commit` 保存这些已发生事实；失败不继续派发，后续写完整值并保留 latest 业务事实，不重复累加本次模型费用。等待审阅前的 planning_safe 分支无法执行这两个 write_local 工具，不能提前保存未准入 Plan。设计与同轨零模型验收由[唯一 Spec](../optimization/to_verify/verify_results/research-experiment.md#2-决策状态先于持久接受)拥有；不新增费用账本、状态或恢复来源，也不将此项计作 E2 通过。

实验 Command 在 Docker 操作前固定输入、稳定作业身份、deadline 和额度；原身份对账，未知不得盲目重启或按零耗用释放。runner 负责实际停止与终态，Gateway 不以线程取消冒充停止，也不叠加自动实验重试。任务墙钟和累计执行额度由受信部署分别显式提供，不采用统一900秒默认；Trace 固定原绝对截止，恢复不顺延。模型可在剩余预算内继续多轮读取、搜索及实验，单次诊断的观察次数不成为产品上限。正式采集监督只读绑定同一截止，启动与收尾单列；Windows包装进程不能替代实际解释器终态。该次1小时验收的具体配置与验证见[长任务预算与诊断范围](../optimization/to_verify/verify_results/research-experiment.md#长任务预算与诊断范围)，尚不构成完成证据。E2 仍只承诺已提交成果、无在途写入边界的同 run 恢复，多宿主和任意中断自动成功不在本决定内。

研究稿件沿原 owner；实验用例从冻结与真实结果导出机器交付清单，正式 CLI 消费同一清单。确定性 validator 检查执行、冻结、文件、版本和权限，语义核验不能推翻这些事实。2026-10-21 的 [ADR 0037](0037-experiment-submission-first-delivery.md)替换本实验首轮的批准前置：实际 SubmittedFinal 持久后独立检查引用及文件，以 submission_ref／Manifest v2 发布确切正文；齐备才允许 Final 完整成功。报告发布只属交付，不能反向成为研究来源。

绑定实验部署的 run 由模型显式请求 prepare_final 从动作阶段进入研究；读过正文不单独决定准备时机。研究内部修订和已批准稿恢复仍沿原路径，普通 Web 保留既有触发，预算及完成门禁不变。该修正依据冻结 v1 的真实阶段轨迹及独立 critic，不声称修复 Provider 或已证明成本收益。候选执行说明公开固定 I/O，失败诊断只发布当前命令的有界捕获；限制从 Artifact canonical metadata 经窄只读 Port 恢复。Web 在原资源项外投影下载 URL，不把 URL 或日志变成新的权限、执行或评分事实。

## 复杂度与替代方案

新增结构均服务本次真实消费者：Artifact 快照／补丁及回执供模型源码和用户下载；业务实验请求／结果供工具和外层引擎；原 Journal 的接受记录供派发与恢复；机器清单供 Completion 和 CLI 复现。不设第二份实验、权限或剩余额度总账，不复制原评分／沙箱实现，也不让 src 导入 scripts。

仅扩固定算法枚举不能满足 P1 自行实现；完整 Shell 引入任意命令、依赖和进程会话，超过本例。模型手写复现 Shell 会重新拼参数并可能偏离已运行事实，因此采用从原事实导出的清单。新预算平台或分布式 outbox 不能解决本例尚未验证的收益，首版不采用。外部执行边界比较由[Spec](../optimization/to_verify/knowledge-decision-delivery.md#5-扩展机制与开源取舍)引用，不替代真实失败依据。

## 既有数据与验证

当前默认 data 有 0 份上传 sidecar、6 份普通生成报告，原字节摘要／长度 5/6 一致；一份 CRLF 报告只有转换 LF 后才符合旧登记。初次 text-mode 检查会标准化换行，6/6 结论已撤回；新 owner 保留原件并明确拒绝损坏，不静默修复用户数据。历史未知 execution_scope 如实表达，不借默认值授权当前任务，不作为草稿或执行事实。缺完整 producer 绑定的历史请求不能猜测重放。新写者统一新契约，无独立可写镜像或兼容业务双轨；历史证据不批量改写。

该次验证顺序见[完整落地 Implementation Plan](../optimization/to_verify/verify_results/research-experiment.md#32-完整落地-implementation-plan)：T2a 先核对工程迁移行为，T1／T2 接通正式执行和当前来源，T3 验文件及同稿完成，T4 核对实际容量和用量，随后 E1／P1、授权／终态／发布反事实及 E2 原样恢复。独立评分、原字节下载、完整排名复算与干净复现缺一不能宣布对应用户结果完成。未知消费不计零，E3 未自然触发记未覆盖。

以上生产接入及 target 尚未验收。新事实如显示越权、混版、重复副作用、未知被当成功或完整交付不可达，停止受影响路径并按最早责任修正，不恢复无权限的任意文件／执行入口。长期责任决定不设置虚构到期日。
