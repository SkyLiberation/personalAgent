# ADR 0014：自然语言入口调用既有领域能力

2026-08-03 决定。Conversation 从用户目标选择业务能力，领域 Application 仍拥有事实、权限、确认和恢复。[现行正式入口与对话主链](../architecture/core-architecture-current-state.md#3-正式入口与对话主链)

## 背景与决定

真实入口曾在未读取个人知识时返回澄清，在用户要求先确认删除时只回复文字，并在后台调查请求中提议未注册的能力。缺口是正式入口缺少可用业务动作或明确的能力边界。

模型提议读取或准备删除。Admission 核对工具、作用域和绑定目标，再调用各自的领域用例。读取由 Personal Knowledge 提供有作用域的证据。删除在已有生命周期入口冻结 Command，确认后执行并以 Receipt 留证。显式 API 与自然语言入口共享领域写入。增加专用业务能力的成本限定在真实调用面，避免复制生命周期或交给模型重排事务。[删除流程](../workflow/delete-knowledge-workflow.md)

原后台 Project handoff 随 [ADR 0015](0015-withdraw-investigation-project.md)退役。周期研究仍由其自身服务负责。

## 历史验证

L01 与 E22 的历史运行 `20260803T152242.957743Z-388-d0850c85` 验证了作用域内读取和受治理删除。E23 的历史运行 `20260803T151935.921382Z-27308-be5eadbf` 只证明当时的 Project 创建和引用；该机制后续撤回。E24 是两条旧研究机制的边界诊断。以上运行属于原工作树，不作为当前发布证据。[评测盘点](../evals/02-current-case-inventory.md)
