# 持续研究 P1/P2 目标设计

## 文档定位

一次性研究、周期订阅、durable worker、独立投递任务、事件聚类、来源可信度、个人知识关联和用户反馈已经落地，不再作为 future 内容重复描述。当前事实分别由
[当前核心架构](../summary/core-architecture-current-state.md)、
[research_once workflow](../workflow/research-once-workflow.md) 和
[Research环境配置](../env.md#research--定时情报简报) 持有。

本文只保留尚未落地的持续研究 P1/P2 范围。运行时遵守
[Capability-first Knowledge Agent Runtime](adaptive-agent-runtime-design.md)：普通问答使用 `InteractionRun`，研究业务生命周期由 `ResearchRun`、`ResearchSubscription` 和 `Delivery` 各自拥有，外部 Agent 委托由 `ChildAgentRun` 拥有，不创建镜像这些领域状态的通用 Durable Task。知识 Claim 和 Evidence 的语义抽取由
[语义生命周期抽取](semantic-lifecycle-extraction-redesign.md) 独占设计，本文不复制其 Model。

## 1. P1：来源与验证增强

### 目标结果

用户收到的每条重要更新能够区分：

- 官方一手来源；
- 相互独立的二手来源；
- 多篇转载形成的伪多源；
- 尚未获得独立证实的单一声明；
- 对既有事件的补充、修订或反转。

### 最小能力

1. 增加面向新闻和原始页面的 typed read tools，但仍通过 Gateway 执行；
2. Source canonicalization 识别相同 URL、canonical URL、转载链和内容指纹；
3. 来源独立性由结构化特征与模型语义判断共同形成，代码不以域名数量冒充独立来源数量；
4. 官方来源优先级是 ranking policy，不等于内容自动为真；
5. claim-level verification 只消费 admitted EvidenceRef，不直接消费搜索摘要；
6. 同一事件的新信息形成 revision/supersedes 关系，不覆盖旧事件和旧简报；
7. 趋势判断必须引用多个时间窗口，单次尖峰不能直接生成长期趋势结论。

### 所有权

| 事实 | Owner |
| --- | --- |
| 原始抓取内容和locator | Artifact/Evidence store |
| URL归一、内容指纹、转载候选 | Source canonicalization projection |
| 来源独立性语义判断 | typed model proposal + admission result |
| 事件revision关系 | Research event lifecycle |
| 用户可见的重要性与个人相关性 | Digest decision/output |
| 长期知识Claim | Knowledge lifecycle，不由Research重复保存 |

### E2E先行

P1实现前必须新增以下冻结来源用例：

1. 三个不同域名转载同一新闻，只计算为一个原始来源链；
2. 官方changelog与媒体摘要冲突时，同时保留证据和冲突状态，不静默合并；
3. 只有单一匿名来源时，简报显式标记未独立证实；
4. 后续官方修订产生新的event revision，旧简报仍可回放；
5. 含prompt injection的页面不能成为verification evidence；
6. Claim抽取失败不回滚已经完成的Artifact/Evidence摄取。

每个用例必须断言 canonical source、Evidence admission、event revision和最终digest，不以自然语言关键词匹配代替。

## 2. P2：事件触发与持续追踪

### 目标结果

用户可以对主题、实体或事件建立持续追踪：重要变化即时提醒，普通变化进入定时简报，无变化时不制造更新。

### 最小能力

- RSS、官方changelog、GitHub release和论文源等结构化connector；
- tracked entity / event / topic subscription；
- 即时提醒与定时摘要的确定性投递策略；
- 安静时段、通知优先级和每日打扰预算；
- follow-up subscription继承明确的topic/entity引用，不复制整份旧ResearchRun；
- connector cursor、ResearchRun和delivery attempt分别拥有各自状态；
- 断开、重启和重复事件到达时不重复研究或投递。

### 不变量

1. Connector只产生外部观察，不能直接生成已验证Claim；
2. 同一source event的重复到达由canonical event identity去重；
3. 即时提醒是投递策略，不改变事件可信度；
4. 用户暂停subscription后不得创建新ResearchRun，已dispatch的外部调用按Journal恢复；
5. 投递失败只重试投递，不重新搜索和重新生成digest；
6. 安静时段推迟发送，不修改事件发生时间；
7. 用户批准外部credential/acquisition不等于connector已经可用。

### E2E先行

1. 同一GitHub release通过poll和webhook重复到达，只形成一个event和一次投递；
2. 进程在event admitted后、delivery前终止，重启后复用同一digest；
3. 安静时段的重要事件进入pending delivery，到窗口开放后发送一次；
4. 普通事件合并进下一次digest，不触发即时通知；
5. subscription暂停后connector仍回调，不创建新的ResearchRun；
6. connector缺少credential时进入typed auth/acquisition required，不选择相似provider；
7. follow-up追踪引用原entity/event ID，旧运行内容不被复制成新的事实owner。

## 3. 明确不做

- 不建设通用网页爬虫或绕过登录、付费墙；
- 不把所有外部文本默认写入长期知识库；
- 不让模型自由创建无限subscription、查询或通知；
- 不为Research另建一套Artifact、Evidence、Claim、Gateway或Journal；
- 不为每次只读搜索创建完整Durable Task；
- 不以来源数量、相似度或模型置信度冒充事实真实性；
- 不在没有对应release E2E前预建connector抽象和多级投影。

## 4. 完成定义

P1/P2只有在以下条件同时满足时才从future移出：

1. 冻结来源和真实provider用例分别通过；
2. source、event、subscription、run、delivery各有唯一owner；
3. crash/retry不会重复外部调用、研究或投递；
4. Evidence admission与Claim lifecycle仍由各自权威模块负责；
5. 新connector没有引入通用raw dict、裸identity或provider fallback；
6. 当前事实文档和运维文档完成更新，本文删除而不是保留“已落地”章节。
