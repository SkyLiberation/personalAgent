# 开发与设计细则索引

> 根 [AGENTS.md](../../AGENTS.md) 与 [CLAUDE.md](../../CLAUDE.md) 是逐字一致的规范入口。本目录拥有跨目录任务域细则，不能脱离根规范解释或放宽门禁。

## 1. 渐进式披露规则

读取顺序、任务分类和冲突处理由[根规范第 1 节](../../AGENTS.md#1-指令读取与渐进式披露)拥有。实际工作涉及哪些任务域，就读取哪些细则；评审规范时检查其正文与引用，不把所有出现的术语当作生产改动。

## 2. 细则与参考责任边界

根规范保留关键门禁与路由；下表各文档拥有详细正文。其他入口只保存必要摘要与链接。

| 入口 | 唯一主讲内容 |
| --- | --- |
| [EVD：变更证据与设计准入](change-evidence.md) | 基线、按实际影响选择证据与升级条件、探索边界、反事实、连续模型依赖链、失败归因、复杂度准入、外部机制比较与设计说明 |
| [ARC：架构边界与事实归属](architecture-ownership.md) | 分层、事实与决策归属、模型边界、派生缓存与投影、契约一致性与生产可达性 |
| [EXE：智能体决策与受治理执行](agentic-execution.md) | Proposal、Plan、Admission、执行、Verification、Completion、Command 与恢复协议 |
| [CTX：上下文、记忆与检索](context-memory-retrieval.md) | 实际模型输入审计、反馈表达、存储边界、能力投影与服务方等价绑定 |
| [COD：代码组织与实现约束](code-structure.md) | 类型与不变量、已有文字引用、职责与编排、错误、依赖注入、命名与通用 Prompt 契约 |
| [QLT：测试、评估、观测与安全](quality-security.md) | 验证方式、替身边界、Golden Set、E2E 阻塞、安全与审计 |
| [REL：迁移、ADR 与完成门禁](migration-release.md) | 兼容例外、迁移、ADR 与分类完成检查 |
| [DOC：文档模块规范](../AGENTS.md) | 文档事实治理、生命周期与检查 |
| [EVM：评测模块规范](../../evals/AGENTS.md) | 用例登记、比较身份、归档、历史证据复用、运行声明与成本控制 |
| [生产 Prompt 模块规范](../../src/personal_agent/kernel/prompt_templates/AGENTS.md) | `PromptSpec` 注册、序列化、版本与消费检查 |
| [REF：优秀智能体能力组件参考](../agentRef/README.md) | 外部机制检索坐标与证据范围，不拥有工程规则或采用结论 |

文档目录由[文档索引](../README.md)拥有，中文表达由[写作规范](../chinese-writing-spec.md)拥有，Future 与优化记录的生命周期分别由 [Future 索引](../future/README.md)和[优化索引](../optimization/README.md)拥有。

## 3. Codex 官方机制与本工程选择

2026-09-30 复核以下官方坐标；引用页面可能更新，未来采用时仍须核对目标版本。

| 官方坐标 | 官方机制 | 本工程选择 |
| --- | --- | --- |
| [Custom instructions with AGENTS.md](https://learn.chatgpt.com/docs/agent-configuration/agents-md) | 从项目根向当前工作目录发现指令，合并尺寸受 `project_doc_max_bytes` 限制，默认 32 KiB；就近文件后加载 | 根保存关键门禁，目录入口明确继承根规则；跨目录细则按任务显式读取，不假定启动时已加载所有子目录 |
| [Model guidance：Favor leaner prompts](https://developers.openai.com/api/docs/guides/latest-model#favor-leaner-prompts) | 减少重复指令，按任务暴露上下文和工具，用自身代表性任务核对变化 | 每项规则有正文归属，机械检查入口和引用；不将外部模型收益或文本压缩外推为本工程效果 |

32 KiB 与 200 行是本工程入口尺寸门禁，具体由 [DOC](../AGENTS.md#4-主文档与模块规范维护)拥有。官方默认字节上限可配置；工程检查不测量用户全局指令，也不代表实际模型 Context 总尺寸。`CLAUDE.md` 是项目的镜像入口，默认不属于 Codex 的文件发现链。Markdown 链接只提供坐标，显式阅读要求仍由根规范拥有。

## 4. 维护规则

- 修改前确认唯一正文归属。只有全局门禁、任务分类和路由进入根入口；详细规则进入任务细则，目录特有约束进入模块入口。
- 清理重复条款时保留必要摘要与有效链接；移动正文或改标题时同步所有引用，不建立“最新版”双轨。
- 路由、任务域或目录入口变化时，同步根表、本文责任表和受影响识别样本。样本验证真实任务边界，不能只为迎合关键词得分改写。
- 两个主入口不一致时先修复同步，再继续受影响实现；规范本身的清理不被这一问题阻止。
- 文档整理报告检查与尺寸变化，不制造产品失败，也不声称模型理解或产品质量得到提升。

## 5. 识别评测边界

[`recognition-cases.json`](recognition-cases.json)拥有固定任务与目录样本；[`scripts/check_dev_spec.py`](../../scripts/check_dev_spec.py)读取根路由表，检查首选细则定位、目录覆盖、主入口字节同步、尺寸、路由标题、本地目标存在性与代码围栏配对。

```powershell
.\.venv\Scripts\python.exe scripts/check_dev_spec.py
```

门槛是已登记样本全部命中、9 个任务域完整、入口一致且满足尺寸要求。样本总数以 JSON 为准，实际尺寸与链接数量以命令输出为准，不在规范重复维护历史快照。

脚本是固定关键词启发式检查，只证明这些样本能定位首选细则和目录入口，不能证明模型理解正文或完整识别任务域并集。报告命中数、样本数、准确率与误判，不把历史压缩基准当作本次治理收益。脚本不验证标题锚点、表格和 Mermaid；本次变更另按 [DOC](../AGENTS.md#5-提交前检查)检查适用结构及引用，不能把目标文件存在误报为锚点有效。
