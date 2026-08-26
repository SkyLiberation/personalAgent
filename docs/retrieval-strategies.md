# 检索策略入口

**当前检索设计只由 [Retrieval 与证据推理](topics/retrieval-reasoning.md)维护。** 本页保留旧链接的可达性，不再复制 Graphiti 策略、旧 Ask 链路、启发式排序细节或历史评测结果。

## 当前边界

检索是 Conversation 中由模型选择的只读证据动作，不是隐藏的 Router、Planner 或回答生成器。生产链路依次执行权限范围过滤、需求召回、语义选择和预算物化；所有来源统一转换为有出处的证据对象，再由同一个回答责任主体组织最终回复。

以下事实分别由对应文档维护：

- 当前检索、图谱事实和回答边界见 [Retrieval 与证据推理](topics/retrieval-reasoning.md)；
- Memory、权威事实和检索投影的差异见 [Memory 与知识事实边界](topics/memory.md)；
- Context 的过滤、选择与物化顺序见 [Context 工程](topics/context-engineering.md)；
- 已执行用例及其证据等级见 [当前端到端用例盘点](evals/02-current-case-inventory.md)。

历史策略名称、旧目录路径和未达到当前准入要求的候选应从 Git 历史或评测归档复核，不能从本页推导当前生产行为。
