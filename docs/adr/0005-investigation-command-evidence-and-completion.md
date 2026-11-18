# ADR 0005：Investigation 的执行、证据与完成责任

2026-07-27 决定，2026-08-26 随 [ADR 0015](0015-withdraw-investigation-project.md)退出。

## 原决定

旧后台 Project 分离外部执行准入、不可变 Command、执行回执、证据接纳、语义核验和最终交付。Gateway 拥有执行事实，Project 拥有版本化成员与结果，Verifier 判断语义满足，Completion 检查所需证据及覆盖。授权与执行用原摘要绑定，恢复按已提交事实继续。回执成功不直接推动任务完成。

## 历史验证

B03 归档 `20260728T123013.176272Z-42316-76b47a9c` 已执行但无法推进修复；后续 IP01 还暴露反馈按事件重复计数、服务异常和修复跨主题选证。后者按 [ADR 0008](0008-investigation-repair-lineage-and-local-retry.md)修复，IP01 存在一次真实通过；后续更宽的正式组仍未交付，独立产品生命周期退出。各运行身份和逐次结果保留在[原记录](https://github.com/SkyLiberation/personalAgent/blob/345c62679a6c1f6a4c70980c868f55b5dee95fef/docs/adr/0005-investigation-command-evidence-and-completion.md)。

执行、核验与完成的分离原则继续由[现行核验专题](../topics/verification-and-completion.md)说明。
