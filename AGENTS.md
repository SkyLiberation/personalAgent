# 整体规范
任何代码修改开始前，必须遵守以下规则：

1. 每个事实只能有一个权威所有者和一个写入口。

2. 派生值默认不持久化。 能从 canonical state 确定性计算出的字段，不得加入 checkpoint、数据库 Model 或跨节点 State。

3. 禁止为了兼容旧调用方而同时保留新旧业务字段。 本规范覆盖的重构默认允许修改全部调用方。

4. 禁止 singular/plural 双轨状态。 例如 current_action 与 current_actions 不得同时作为可写状态存在。

5. 禁止字段级镜像 Model。 两个业务 Model 若大部分字段相同且需要双向转换，必须重新确定 canonical Model，而不是补 converter。

6. Definition、Command、Event、Runtime Projection、View 必须分清。 不得在同一 Model 中混装不可变定义、频繁可变状态、事件日志和展示字段。

7. 禁止使用空字符串、裸字符串或 raw dict 绕过身份、作用域、授权和状态边界。

8. 新增 validator 不能用于维持两个副本的一致。 如果 validator 的主要职责是同步重复字段，应删除重复字段。

9. 删除优先于兼容。 能替换旧模型时，不得新增 alias、fallback、双写和无期限 deprecated 字段。

10. 不要机械地将所有状态事件化。 只有需要恢复、审计、重放或长生命周期一致性的核心 aggregate 才使用完整 Event + Projection。

若无法明确某个字段的 owner、来源和写入规则，不得直接编码；应先完成“事实与所有权分析”。

## Agentic 决策与确定性管控

以下规则用于防止 Runtime、Compiler、Validator、Procedure 和 Orchestration 逐步演化成隐藏的业务规则引擎。详细目标设计见
[`docs/future/agentic-decision-deterministic-control-redesign.md`](docs/future/agentic-decision-deterministic-control-redesign.md)。

11. 模型负责开放世界中的语义决策：解释目标、提出 Goal/Plan、选择下一动作、填写业务参数、选择上下文与恢复策略、生成最终答复。模型输出永远是 Proposal，不是权限、事实或完成证明。

12. 确定性代码负责封闭世界中的管控，以及从已接受契约、版本化 policy 和已提交事实中机械推导唯一结果。它可以解析 canonical identity、编译 mandatory route、绑定语义等价 provider、计算 ready frontier 和控制状态；每次推导必须有 typed `DerivationRecord`，不得新增 intent、target、payload 或 requested result contract。

13. Validator/Admission 必须只接受或拒绝 Proposal，不得通过补字段、拼接 description/constraints、改写 payload、替换 Goal 或生成 Plan 来“修复”模型提案。拒绝必须产生 `DecisionFeedback`，明确 mutable/immutable fields、required repairs、revision scope 和 disposition；Admission rejection 不是 Observation。

14. 禁止确定性业务 fallback。模型不可用或提案连续不合法时，只允许 fail closed、暂停、请求外部输入/能力获取、等待环境变化、执行已冻结命令、唯一控制状态转换，或在同一 ExecutionCommandDigest 上做幂等技术重试；不得生成替代计划、查询、写入内容或业务答复。

15. `AcceptedIntent` 必须逐字冻结 Proposal 的业务语义；`ResolvedExecutionCommand` 是持久化、不可覆盖、只缩权的 immutable derived contract。Confirmation 绑定 AuthorizationDigest，Grant/Journal/Receipt 绑定 ExecutionCommandDigest。Command 重新解析必须创建 superseding command，不得覆盖旧 Command。

16. Procedure 只封装稳定事务不变量，例如 prepare、confirm、commit、receipt、compensate/reconcile；不得决定业务 payload、替 Agent 选择目标或在失败后猜测替代路径。mandatory Procedure 不能创造 intent，但可以把已接受 intent 编译到 policy 唯一合法的 route。

17. 确定性检查只能验证系统能够机械证明的关系。`DerivationRecord` 只允许 rule/version、source/output digest、封闭 uniqueness kind 和 typed invariant results；不得用自然语言断言、字符串包含、相似度或排名冒充语义保持与唯一性。

18. 模型 Verifier 不得推翻确定性执行事实，确定性 receipt 也不得冒充 Goal 成功。Execution fact、semantic Goal verification、Task completion 必须分层；任何 required report 缺失时 Completion fail closed。

19. Context 按 visibility、requirement-driven retrieval、model semantic selection、budget materialization 四阶段处理。Capability 只有完整满足 `CapabilityEquivalenceClass` 才能确定性绑定；Frontier 只有 DAG/priority/policy 唯一确定时才能直接选择。存在语义分叉时由模型或外部权威决定。

20. 任何新增确定性分支必须标注 Decision Ownership Taxonomy，并回答唯一性来自哪些 accepted fields、policy 和 facts。测试至少覆盖 accepted、denied、受限 revision、外部输入/能力获取、跨阶段循环、双 digest、replay 不重算 Command，以及管控层没有静默改写 Proposal。
