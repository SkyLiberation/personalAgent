# 选证输出按真实研究状态呈现合法契约

问题编号：`RESEARCH-SELECTION-STATE-CONTRACT-001`。空稿Schema曾允许answered及空claim_ids，实际Python校验拒绝，原正式入口503。该窄问题已通过局部反事实和正式消费；完整用户结果由[评测登记](../../evals/02-current-case-inventory.md#2026-10-08-选证状态修复后的正式入口结果)拥有。

## 机制与责任

Runtime按canonical当前稿是否存在选择同一父契约的当次Schema。初始两个typed子类型复用原字段与校验，只允许ready、needs_evidence、delivery_check及空claim_ids；已有稿保持原Schema，answered仍绑定当前claim。模型拥有选证、缺口及后续动作，Runtime不改写输出。所有消费者继续接受ResearchEvidenceSelection父契约，没有新增阶段、模型调用、存储或备用路径。selector v7记录Schema变化，Prompt正文保持。当前权威调用见[ADR 0032](../../adr/0032-conversation-research-claims.md)。

## 决定性证据与适用范围

[原输入审计](../../../.tmp/research-selection-state-contract-20261008/baseline-input-audit.json)逐字重建两份正式无稿请求，确认SDK与Python不变量不一致；旧无效响应仍被拒绝。[局部资格](../../../.tmp/research-selection-state-contract-20261008/local-audit.json)3/3真实状态通过，包含两个空稿和一个实际8-claim状态。已有稿业务messages和Schema逐字保持，仅版本标识变化。两次其他格式错误沿原恢复完成；实际选证续接由模型自行发起两次真实工具读取和搜索并得到原文。4个逻辑操作、6次完成SDK，113,242 tokens，未知0。条件续接属于Offline Eval。

三个模块逐字迁入，全部261源文件与隔离身份相同。[正式检查点](../../../.tmp/research-selection-state-target-20261008/selection-state-checkpoint.json)核对3次无稿SDK请求与对应canonical快照、Schema及合法输出，真实写作者随后创建4条claim并进入来源、覆盖、汇总及两次最终核验。原503已解除。该正式样本完整用户结果0/1，独立失败是非规范性章节限定未被取证；它没有否定初始状态契约，不将局部成立改成整份交付通过。

## 失败尝试与重新打开条件

旧Schema正常响应和一次恢复继续返回answered及空身份，实际入口拒绝。新局部样本仍出现一次状态拼写、一次额外键，现有单次恢复成功；不主张Schema保证任意模型输出合法。若无稿请求再次暴露answered或可生成claim身份、已有稿Schema被收窄、父契约消费者不接受实际输出，或Runtime改写状态掩盖拒绝，重新打开本问题。
