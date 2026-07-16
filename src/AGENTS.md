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