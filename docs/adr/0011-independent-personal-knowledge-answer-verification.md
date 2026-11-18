# ADR 0011：Personal Knowledge 证据选择与回答验证边界

2026-07-31 决定，2026-08-12 由 Conversation 的 grounded answer 链路替换。独立 `/api/knowledge/ask`、`EvidenceGroundedAnswer` 和专用回答核验已退出。[现行读取和回答流程](../workflow/capture-ask-model-flow.md)

## 历史决定

B04 对同一业务主体返回两个互相矛盾的日期，却把答案标为 `supported`。当时的回答组装器按已选择的证据计算语义结论。此外，旧 Ask 检索曾间接生成并核验一份随后丢弃的临时答案，再把该答案的结论投影到单条证据。

当时的修复是把只读证据选择、成文和答案级语义核验拆开，选中材料交给最终回答的所有者，核验读取当前问题、确切草稿和可见证据。替代了按数量推导支持结论的 coverage judge，保留知识事实的单一写入口。Conversation 接管后沿用职责分离。

## 历史证据

- B04 基线 `20260731T063040.820774Z-16696-c3646c8a` 复现错误支持。E20 改造前归档 `20260731T063538.487874Z-48204-345f5a84` 缺少独立核验。
- E20 改造后归档 `20260731T064446.108938Z-8804-52b29d3c` 识别冲突。E02 与 E20 对照归档 `20260731T065454.238105Z-51564-b8d1436c` 中，普通回答为 `passed/supported`，冲突回答为 `needs_revision/conflicted`。
- 后续 ASK-001A/B 验收迁移后的个人知识与多来源回答，按新入口及运行身份报告。[历史评测盘点](../evals/02-current-case-inventory.md)
