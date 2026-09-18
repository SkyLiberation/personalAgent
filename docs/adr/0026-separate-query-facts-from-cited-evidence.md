# ADR 0026：查询执行事实与来源证据分离

**状态：查询与来源交接局部保留；本轮整体 Context 行为接入撤回，产品验收失败。** 日期：2026-09-17。问题与取舍见[取证第 115 节](../optimization/evidence-acquisition.md#115-完整查询交接与-context-重组的正式接入验证)，参数丢失问题已[独立固化](../optimization/completed/query-execution-handoff.md)。

## 问题与决定

成功搜索的结果缺少实际查询条件，不能区分不同关键词产生的相同零匹配结果。`WebSearchArgs` 迁入 Application 捕获契约，`WebSearchOutput` 复用它返回参数；`SourceSearchResult` 复用原本地参数契约。唯一写入者仍是原执行函数，不从摘要或实验日志重建查询，不增加查询表。

`CitableInput.executed_query` 是请求内投影。来源引用及 Verifier 的引用恢复排除查询参数，保留原正文、身份、版本与坐标；超大网页搜索保存完整结果 JSON，查询只留在有界执行元数据。既有 Context 物化路径直接消费该投影。

本轮试接入的历史 user 消息、当前反馈 system 分区、被拒稿移动、重复读取指引裁剪、能力条件 Prompt 与扩源指导已从生产撤回。相关 Prompt、`interaction_prompt`、`_decide` 消息构造和原测试从本轮开始前的工作树归档恢复，保留用户原有 Plan、正文、引用、门禁与修订优化。候选代码和原始失败仅封存在 `.tmp`，没有生产 flag、fallback 或双轨。

## Complexity Justification

保留部分没有新增服务、Port、状态机、表或运行循环。参数模型通过迁移及继承复用唯一约束；新增一个纯来源投影函数和请求内 typed 字段，均由现有执行、Context 与引用消费者使用。Context 候选的两个临时容器及新增消息组装函数已删除。最终行数与类型变化见[变更审计](../../.tmp/query-context-integration-20260917/change-review.json)。

## External Mechanism Comparison

两项独立 A 级实现按固定源码核对：[Gemini CLI `geminiChat.ts`](https://github.com/google-gemini/gemini-cli/blob/3c311beac2e78336816dd4a123db39743f9fbf85/packages/core/src/core/geminiChat.ts)保留带参数调用与响应配对；[OpenHands 0.59.0 `conversation_memory.py`](https://github.com/OpenHands/OpenHands/blob/0.59.0/openhands/memory/conversation_memory.py)按动作与观察组织消息。固定源码及校验和见[来源档案](../../.tmp/query-history-reference-20260917/sources.json)。采纳执行参数与结果关联，不复制完整历史图、查询缓存或第二循环；外部机制不证明本工程语义收益。

## 证据、取舍与退出

修改前与历史正式 v2 的 489 个代码／测试／配置文件一致；五项参数 Contract 的旧实现反例保留。候选修正后 244 项相关检查通过，研究消费者补查 26 项通过；撤回 Context 后实际执行的相关检查为 230 项通过。这些不能相加当成独立产品样本。

首轮因遗漏已有整体候选的两段指引而人工终止，没有自然终态；一次有界修正后原正式用例为 **1 failed**，HTTP 2185.878 秒、pytest 2194.53 秒，四稿分别经历三次覆盖拒绝和一次引用支持拒绝，最终返回未经请求的知识保存确认。没有知识写入，没有完整答案，也没有进入后置评分；53 个决策回合、54 次工具调用、2,194,884 已记录 tokens，完整供应商成本未知。

查询和引用保真反事实在正式记录上通过；Context 候选实际发生扩源与新正文读取，却未形成完整修订。保存准入代码未变，原“读和问不授权写或存”规则未遗漏，但无法排除整体 Context 对误选动作的因果责任，按 EVD 撤回该行为候选，不追加第二轮局部提示补丁。此前受控整体候选的扩源和原缺项修订收益仍保留，不能以本轮原始失败抹去历史事实。

原运行身份、原始响应、确定性准入反事实和取舍见[最终审计](../../.tmp/query-context-integration-20260917/formal-target-v2/final-audit.json)。最终保留组合未再运行完整 E2E；本轮不声明产品完成、可合并或可发布。下一步优先核对证据不足时的正常交付与模型结束取证决策，当前条件见[活动设计](../future/conversation-verification-false-positive.md#3-条件候选与因果准入顺序)；保存误路由的因果边界另行审计。本 ADR 没有改变现有覆盖门禁。

若保留部分丢失查询身份或污染引用证据，重新打开对应局部问题；Context 重新准入必须补齐当前失败边界、误路由反事实及原用户结果。候选失败不恢复旧参数丢失，不否定此前已成立的正文和循环机制。
