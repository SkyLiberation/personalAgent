# ADR 0028：引用物化保留来源绑定

**状态：修复已接入目标代码，完整 E2E 未验收。** 日期：2026-09-18。局部证据见[问题记录](../optimization/citation-source-attribution.md)，剩余边界见[活动设计](../future/citation-source-binding.md)，准入由 [Future 队列](../future/design-optimization-backlog.md)拥有。

## 背景与决定

正式研究第十八稿的两条 OpenAI 引文已有来源，逐行引用到核验的转换却只保留正文。本次恢复已有的 Context 保真约束，模型仍只选择 `evidence_id`，不生成来源。

新增 `CitationSource` 保留完整 `ResourceRef`、已知来源 URL、行号和起始列。来源按可见成功执行记录中的资源身份、作用域与版本关联；未知 URL 为空，不按相同正文、最近来源或机构名猜测。完整观察继续保留工具结果中的来源，新增字段承载逐行引用位置。局部核验接收原文与来源；整稿和缺项输入也保留它们，去掉仅在局部有意义的编号。原文、覆盖、取证充分性及核验判据不变。

## 责任主体与复杂度

执行记录拥有来源事实，`source_metadata_by_resource` 统一派生资源元数据，供读取覆盖和引用物化复用。`materialize_cited_draft` 是引用投影写入口。正式路径仍是 `/api/conversation/turn`、原 Composition Root、Conversation 服务和原验证工具，没有新增装配、工具、存储或循环。投影按本次可见执行集合重建，不持久化第二份来源。

生产修改 4 个文件，新增 48 行、删除 18 行，净增 30 行；新增 1 个值对象和 1 个提取函数。旧的 `evidence_id → text` 转换及核验纯正文展平已替换。未采用模型复述来源、全文重读、搜索补偿或整体 Context 扩充，因为这些动作不能修复确定性投影丢失。

## 外部依据与边界

2026-09-18 核对两项 A 级公开契约：[Anthropic Citations](https://platform.claude.com/docs/en/build-with-claude/citations#how-citations-work)以文档索引、原文和位置保持关联；[MCP 2025-06-18 Embedded Resources](https://modelcontextprotocol.io/specification/2025-06-18/server/tools#embedded-resources)将 URI 与文本一并传递。前者由引用 API 消费文档指针，后者由客户端消费服务端资源内容。本工程仅采纳身份与内容共同传递，不移植生成、持久订阅或兼容机制。外部规范不能证明本工程收益，URL 不能替代事实支持或权限。

## 证据与退出条件

原正式失败和 Context 审计见[问题记录](../optimization/citation-source-attribution.md)。固定状态反事实恢复全部 5 个可能编号，旧函数丢失来源、新函数完整保留；不冒充恢复历史模型的唯一选择。生成端物化保持一致，相关 241 项测试通过。真实局部检查固定原段并补来源，另检查无据权限保证仍被拒绝。

本轮不重复长 E2E，不声明完整交付或发布。若出现来源错绑、原文改变、覆盖事实变化或放宽语义判据，撤回对应修改。独立引句协议、无据结论或修订不收敛分别归因，不追加补丁。
