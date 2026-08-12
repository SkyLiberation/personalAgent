# 从四类用户请求理解生产路径

> **请求按“谁拥有结果和生命周期”分组，不按 Tool 名或代码包分组。** Conversation 是统一自然语言入口，但可以调用其他 Application 或创建 Aggregate；这四类路径不是互斥产品模式。

## 1. 统一路由原则

```text
用户自然表达
  -> FinalMessage / Clarification / Limitation
  -> ContinueTurn(actions)
       -> Admission
       -> Application-owned action -> 唯一 Use Case / Aggregate
       -> Tool / MCP action         -> ToolGateway
       -> Agent delegation          -> AgentGateway
  -> committed Observation
  -> 下一模型回合或结束
```

**模型选择“要做什么”，确定性代码只检查是否允许以及如何提交事实。** 关键词无法区分“不要保存”“解释删除”和“删除它”，因此不能成为开放语义 Router；Admission 也不能补 `note_id`、替换 Goal 或静默换 Tool。

## 2. Conversation：直接回答与 grounded answer

**没有执行需要时直接回答；需要个人或外部证据时，先取得真实 Observation 再生成最终答案。**

| 用户表达 | 当前路径 | 关键反事实 |
| --- | --- | --- |
| “SLO 错误预算是什么？” | 模型直接 FinalMessage | 不伪造 Task、Command、Receipt |
| “根据我的记录，项目是哪天上线的？” | scope-filtered personal evidence 预取 → 回答 | 不读取其他 principal；不把回答写成 Claim |
| “结合我的项目记录和 OpenAI 官方资料回答” | personal evidence → 模型按需 web Tool → 综合回答 | 外部内容不获得控制权；只返回一个最终答案 |
| “读取这个大文件中的地址和行号” | Tool Observation → ResourceRef → 有界重读 | 不把全文永久复制进每轮 Context |

`ASK-001A`、`ASK-001B` 的关键设计是**最终回答只有 Conversation 一个 owner**。Personal Knowledge 负责可见证据和 Claim 生命周期，Web Tool 负责外部执行事实；所有来源汇入同一 answer contract。

## 3. 受治理事务：保存、删除与恢复

**需要确认、幂等或跨请求恢复的副作用才形成 immutable Command；普通读取不承担这套成本。**

### 显式保存

```text
自然语言保存请求
  -> 模型选择 exact user-authored span
  -> Application admission 校验 message/source index
  -> immutable SaveCommand + CommandDigest
  -> confirmation 绑定 principal、scope、command
  -> KnowledgeService 唯一写入口
  -> Receipt 引用实际 Claim
```

Admission 只验证模型选择的 span 确实来自对应 user message，不把整条控制指令、assistant candidate 或模型总结写入长期知识。

### 删除与恢复

```text
DeleteCommand --confirm--> delete event + Receipt
              --reject--> terminal rejection, no side effect

RestoreCommand --confirm--> restore event + Receipt
```

Restore 是新动作，不覆盖旧删除事实。相同 digest replay 返回已有结果；跨 principal/scope、错误 command ref 或参数重绑定均 fail closed。领域迁移归 KnowledgeLifecycleService，通用确认入口不能直接改写知识状态。

## 4. 固定长期流程：ResearchRun

**依赖固定、结果契约稳定的长期工作由领域 Workflow/状态机拥有，不需要模型动态重排每个 Activity。**

```text
Subscription -> Scheduler -> ResearchRun -> Digest -> Delivery -> Feedback
```

模型可以完成检索与总结，但 `running/completed/partial/limitation/failure`、来源要求和 Delivery exactly-once 由 Research Application 控制。Provider `ok`、Run `running` 或发送成功都不能单独代表研究目标完成。

## 5. 动态长任务：InvestigationProject

**只有下一步依赖新 Observation，并且任务需要跨进程或用户轮次持续推进时，才使用 Project。**

```text
Conversation / Project API
  -> immutable Project definition
  -> PlanProposal -> PlanAdmission -> AcceptedPlanVersion
  -> deterministic ready set
  -> governed Tool / Agent execution
  -> evidence admission
  -> semantic verification
  -> CompletionReport + ArtifactRef
```

Conversation 创建后只保存 scoped `ProjectReference`。后续 turn 从 Project owner 预取有界的 plan/progress projection；模型可以直接回答进度，也可以提议 `steer_investigation_project`，Application 再绑定真实 project identity 与当前 plan version。读取 projection 不推进状态，steering 不修改冻结 SubGoal，恢复不重复已提交 child action。

`PLAN-001` 从正式 Conversation 验证了同项目读取、调整和 Web 重启恢复，同时断言没有创建第二个 Project 或 Plan 副本。它证明这条纵向切片，不代表所有长请求都需要 Project。

## 6. Owner 总表

| 用户目标 | 长期事实 owner | 正式入口 | Conversation 的角色 |
| --- | --- | --- | --- |
| 直接回答、证据问答、MCP、Agent 委托 | Conversation Interaction | Conversation API | 拥有交互与最终消息 |
| 保存、删除、恢复知识 | Knowledge Application | Conversation + Knowledge/lifecycle API | 选择能力并进入同一写入口 |
| 订阅、周期研究、投递 | Research Application | Research API + Scheduler/Worker | 不逐轮接管状态 |
| 动态跨进程调查 | InvestigationProject | Conversation / Project API + Worker | 创建并持有 scoped reference |

代码入口见 [Conversation routes](../../src/personal_agent/adapters/web/routes/conversation.py)、[Knowledge routes](../../src/personal_agent/adapters/web/routes/knowledge.py)、[Notes routes](../../src/personal_agent/adapters/web/routes/notes.py) 和 [Investigation routes](../../src/personal_agent/adapters/web/routes/investigation_projects.py)。证据强度以[证据与发布](05-evidence-and-release.md)为准。
