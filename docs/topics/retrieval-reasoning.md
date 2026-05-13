# 检索与推理层说明

本文汇总当前项目检索与推理层的职责划分、当前能力、已知限制和后续改进方向。对应代码主要位于 [src/personal_agent/agent/runtime.py](../../src/personal_agent/agent/runtime.py)、[src/personal_agent/agent/verifier.py](../../src/personal_agent/agent/verifier.py) 和 [src/personal_agent/graphiti/store.py](../../src/personal_agent/graphiti/store.py)。

## 设计目标

检索与推理层负责让回答尽量基于个人知识库和图谱证据，而不是直接让 LLM 猜：

- 优先使用 Graphiti/Neo4j 图谱检索
- 图谱不可用时回退本地笔记检索
- 将图谱事实和笔记片段组织成证据
- 生成回答后进行 verifier 校验
- 低置信度时尝试自修正或标注不确定性

## 组件分层

### 1. `GraphitiStore`

代码位置：[store.py](../../src/personal_agent/graphiti/store.py)

作用：

- 判断 Graphiti 是否配置可用
- 将 note 同步为 graph episode
- 通过 Graphiti search 查询相关节点和关系
- 生成 relation facts、entity names、episode UUIDs
- 支持删除 episode

### 2. 本地检索

代码位置：[memory_store.py](../../src/personal_agent/storage/memory_store.py)

作用：

- 按用户列出本地 notes
- 基于简单 token 命中做相似检索
- 根据 graph episode UUID 反查 note

### 3. 回答生成

代码位置：[runtime.py](../../src/personal_agent/agent/runtime.py)

作用：

- 构造图谱回答 prompt
- 构造本地回答 prompt
- 注入 working memory 上下文
- 注入 citations、matches、relation facts 和 snippets

### 4. `AnswerVerifier`

代码位置：[verifier.py](../../src/personal_agent/agent/verifier.py)

作用：

- 校验 citation 是否指向真实匹配 note
- 计算 evidence score
- 识别兜底措辞
- 判断回答证据是否足够

## 当前能力

- 已支持 Graphiti + Neo4j 图谱检索
- 已支持图谱不可用时本地链路回退
- 已支持图谱 relation facts
- 已支持 note snippet citation
- 已支持 `relation_fact + snippet` 证据锚点
- 已支持回答后 verifier 校验
- 已支持低置信度自修正和不确定性标注
- 已支持删除目标解析时利用图谱 episode、本地相似检索、关键词和 recent citations

## 已知限制

### 1. ask 检索排序仍偏启发式

当前图谱结果和本地结果已经可用，但复杂问题下的 rerank、证据合并和多跳推理仍有提升空间。

### 2. 缺少公网网络搜索兜底

当个人知识图谱和本地记忆无法覆盖问题，且 LLM 不应直接回答时，当前还没有 `web_search` 工具参与检索链路。

### 3. verifier 是轻量规则校验

`AnswerVerifier` 主要基于 citation 有效性、匹配数量、图谱加分和兜底措辞计算 evidence score。它不是完整事实校验器，也不会深入判断关系事实是否逻辑一致。

### 4. 复杂推理能力仍有限

当前更擅长基于已有 note 和 graph facts 组织答案。跨多个实体、多个时间点、多条关系的推理仍需要更强的检索规划和证据组合。

## 演进方向

- 引入稳定 rerank 和评测样本
- 新增 `web_search` 作为个人知识不足时的外部检索兜底
- 将 evidence/citation 数据结构进一步统一
- 为 relation fact 和 snippet 建立更细粒度评测
- 增强多跳推理和证据链可视化

