# 网页发现与指定来源读取分离

本文维护 `CONVERSATION-RESEARCH-STOP-001` 中工具分离机制尚未闭环的收益主张。准入状态由[优化队列](design-optimization-backlog.md)拥有，工具契约由[Context 专题](../topics/context-engineering.md#网页来源正文保留与重读)拥有，实际结果见[评测记录](../evals/02-current-case-inventory.md#网页发现与指定来源读取分离候选)。

## 目标与准入依据

原正式用例 `CONVERSATION-RESEARCH-DELIVERY-001/tool-protocol-explicit-review` 要求中文比较正文、官方来源支持及准确的保证范围，用户未指定工具、查询、次数或措辞。原轨迹反复搜索以取得同一正文，当时工具只能附带抓取前两个搜索结果，无法直接读取已知 URL。该失败支持拆分发现与读取的机制候选，尚不能证明工具分离会在原预算下完成交付。

本项属于新运行机制的收益主张，保留原定正式入口消融和用户结果验收。固定 Context 中的零命中只证明该查询的局部负结果，不能证明全文缺项、证据充分或预算不足。历史轨迹与诊断见[取证记录](../optimization/evidence-acquisition.md)。

## 外部机制比较

以下是候选形成时已核对的参考，支持职责分离的可行性，不证明本工程的质量或成本收益。

| 参考与核对身份 | 采用的机制 | 未采用的部分 |
| --- | --- | --- |
| [Hermes 网页工具](https://hermes-agent.nousresearch.com/docs/user-guide/features/web-search)，2026-09-04 | 搜索发现来源，读取选定 URL，保留可重读原文 | 多 Provider 回退、缓存及固定截断比例；本工程提取层不使用 LLM 摘要 |
| Gemini CLI 固定提交的 [web-search.ts](https://github.com/google-gemini/gemini-cli/blob/3c311beac2e78336816dd4a123db39743f9fbf85/packages/core/src/tools/web-search.ts) 与 [web-fetch.ts](https://github.com/google-gemini/gemini-cli/blob/3c311beac2e78336816dd4a123db39743f9fbf85/packages/core/src/tools/web-fetch.ts) | 搜索与抓取分开，来源内容按不可信输入处理 | 辅助模型、实验开关、回退链和 private-IP 实现；不主张授权等价 |

## 未闭环的因果主张与边界

待证主张是：模型直接选择 URL 后，减少为抓取而重复搜索，并在原预算内交付原用户结果。能调用 URL、保存正文或读到窗口，只证明对应执行阶段。

比较变量是模型可调用的发现／抓取契约；必要的参数、返回类型、描述和装配迁移属于同一机制。模型、Verifier、个人知识工具、预算判定及其他 Context 机制保持各自身份；配置扩容、主内容提取、缓存、重排或强制停止不得混入该机制的消融。

模型选择来源、窗口、证据充分性与交付时机。抓取层产生来源执行事实，Conversation 管理物化与读取授权，`ArtifactService` 保存卸载正文。局部正确与完整交付分别验收。

## 后续修正的准入边界

来源覆盖、旧稿传播、最终稿支持关系及评分器错误分别按最早责任处理，不借工具分离叠加 Context 或 Verification 补丁。既有[根因结论](C:/pae/root-cause-synthesis-20260908/conclusion.md)、[正文定位对照](C:/pae/read-navigation-system-20260905/conclusion.md)和[取证记录](../optimization/evidence-acquisition.md)按原身份解释；后续方案的准入由 [EVD](../devSpec/change-evidence.md#7-强制开发与设计流程)拥有。

候选须同时保护证据充分时的完整回答和缺证据时的如实限定。来源原文、模型旧结论和修订反馈保持可区分；关键词未命中不能升级为全文缺项，真实引文不能自动支持相邻结论。不得通过注入理想中间稿、固定工具顺序、强制 Final 或降低原用户要求制造通过。

按既定推进顺序，先核对宽预算样本的交付质量，再为成本优化定义独立比较。运行配置见[对话预算](../env.md#对话运行预算)；不同配置与随机轨迹分别报告，宽预算通过不代替原预算修复或工具分离收益。

## 剩余证据与停止条件

| 剩余项 | 验收与证据边界 |
| --- | --- |
| 原目标与反馈边界 | [验收条件边界修复](../evals/02-current-case-inventory.md#验收条件不再推导改稿任务的边界修复)及[修订链与提取验证](../evals/02-current-case-inventory.md#既有修订链与验收标准提取的离线验证)分别保持原结论。局部 Plan、进入 Final 或单次改稿正确不能替代原预算完整交付 |
| 工具分离的独立贡献 | 正式入口执行 target-minus-mechanism 对照，固定原用户输入、初始事实、模型、配置与独立评分器，源码差异只属于该机制。工具局部检查和两条随机轨迹不证明确定性收益 |
| 原用户结果 | 正式链连续完成原中文比较正文、官方引用支持及未扩大保证范围；保留原失败和必要反事实，不注入中间结果 |

局部消费须由模型自主选择 URL，并在后继请求中实际消费正文或精确窗口；索引存在不算消费。已有[窗口核对](C:/pae/web-read-contract-offline-20260904/audit/20260904T155835.866223Z-12436-4ebb276c/read-contract-window-audit.1.trace.json)只支持其离线范围。

报告用户交付、错误保证、代码与配置身份、实际消费、Agent／评分器 tokens、延迟及 Provider 失败。用户结果须通过，错误保证为零；成本用于诊断，不增设任意比例或调用次数门槛。

新 live 样本按[运行与发布](../evals/04-running-and-release.md)先做收集、影响路由和单样本成本登记，预声明模型轮数、工具次数及 tokens，遵守既有超过 60 秒停止新增样本规则。服务失败、输出不完整和语义失败分别归因；同一阻塞一次有界修正后仍复现，按 EVD 停止叠补并复审。已有局部事实不因独立后续失败而撤销。

## 准入收敛

本项不预建层、Port、表、缓存、Provider 或模型阶段。新增结构须另有失败依据、唯一 owner、真实消费者、删除反事实和验证顺序。

机制通过后，将现行事实迁入专题、取舍固化到优化记录或 ADR，删除过期候选正文；原用户结果按队列既定条件关闭。只成立局部机制时，剩余问题独立保留，不将工具拆分完成写成研究交付完成。
