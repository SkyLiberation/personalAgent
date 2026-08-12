# 面试文档写作规范

> **每节先给判断，再给 owner、机制和证据边界。** 面试材料只解释当前成立的设计，不按开发时间记录探索过程，也不替 future 文档保存候选方案。

## 1. 事实源与唯一职责

**事实核对顺序是：生产代码/机器 catalog/执行证据 → current-state summary → topic/workflow/ADR → interview → future。**

本目录的解释 owner 固定如下：

- `01`：项目定位与总责任链；
- `02`：用户请求的生产路径；
- `03`：跨业务 Agent 机制；
- `04`：领域事实与生命周期；
- `05`：证据强度、测量与发布状态；
- `06`：短答，只链接前五篇，不复制第二套解释。

## 2. 一节只回答一个判断

**合格小节通常只需三类信息：**

1. **为什么重要**：阻止什么用户错误或工程失控；
2. **谁负责**：事实 owner、决策 owner 和唯一写入口；
3. **证明到哪里**：E2E/contract 坐标与不能外推的范围。

禁止无信息过渡、同义收尾、代码目录流水账和“先有设计、后找理由”的叙事。一个表能讲清时，不再用长段重复。

## 3. 术语必须分层

| 术语 | 含义 |
| --- | --- |
| Framework Protocol | Proposal/Observation/Feedback 等跨业务权力契约 |
| Runtime Mechanism | Model、Gateway、Queue、Journal、Trace 等技术执行机制 |
| Application Capability | 用户可理解、可验收的业务动作及其结果契约 |
| Product Aggregate | 拥有独立长期业务事实和生命周期的对象 |
| Interface / Projection | 协议转换或只读展示，不是第二写入口 |

Tool、MCP、Agent 是执行资源；Workflow 是 Capability 内的固定编排；Project 是 Aggregate。相同的 tool-shaped wire format 不代表相同业务 owner。

默认使用“权威事实”“事实 owner”“唯一写入口”。`canonical` 只用于代码/协议原名或 digest 的确定性规范化输入，不作为泛化形容词。

## 4. 证据决定措辞

| 证据 | 可以说 | 不可以说 |
| --- | --- | --- |
| 正式入口 E2E archive | 该输入下用户结果和反事实成立 | 所有场景成立 |
| clean matching revision 的完整 release gate | 当前目标 revision 满足发布证据门槛 | 未覆盖需求天然可靠 |
| Unit/Contract/Integration | 指定不变量或组合协议成立 | 用户目标已满足 |
| 代码/设计/外部参考 | 存在某实现或候选机制 | 本工程结果已改善 |

精确数量、archive 和发布结论只在 `05` 展开。未实际执行时使用“代码设计为”“仍需验证”，不得写“已验证”。

## 5. 发现真实问题时

- 文档写错或过期：核对权威源后直接整体修正；
- 产品行为疑似不足：在 future 以 `A0` 记录待执行 baseline，不增加答辩话术；
- 纯工程约束：记录可量化工程基线和行为保持 E2E，不编造失败产品场景；
- baseline 不成立或目标已经落地：从 future 移除，按当前事实重写 interview。

## 6. 提交前审计

- 每节第一段是否已经回答结论；
- 同一机制是否被多个文件完整复述；
- 是否还引用退出 catalog 的用例、已移除入口或零消费者对象；
- Capability、Tool、Workflow、Project 是否被错误并列；
- “通过、恢复、隔离、完成、可发布”是否都有相称证据；
- 链接、代码路径和 Mermaid 是否仍能解析。
