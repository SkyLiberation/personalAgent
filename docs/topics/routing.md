# 意图识别与路由层说明

本文汇总当前项目意图识别与路由层的职责划分、当前能力、已知限制和后续改进方向。对应代码主要位于 [src/personal_agent/agent/router.py](../../src/personal_agent/agent/router.py) 和 [src/personal_agent/agent/entry_nodes.py](../../src/personal_agent/agent/entry_nodes.py)。

## 设计目标

路由层负责把来自 Web、CLI、飞书等入口的自然语言输入转成结构化的 `RouterDecision`，为后续 planner、runtime 和 executor 提供控制信号：

- 识别用户意图
- 判断是否需要检索、工具或规划
- 标记风险等级和确认要求
- 给 planner 提供候选工具
- 给前端和用户返回可理解的原因说明

## 组件分层

### 1. `RouterDecision`

代码位置：[router.py](../../src/personal_agent/agent/router.py)

作用：

- 表示一次入口请求的路由结果
- 为 planner 和 executor 提供控制字段

核心字段包括：

- `route`
- `confidence`
- `requires_tools`
- `requires_retrieval`
- `requires_planning`
- `risk_level`
- `requires_confirmation`
- `missing_information`
- `candidate_tools`
- `user_visible_message`

### 2. `DefaultIntentRouter`

代码位置：[router.py](../../src/personal_agent/agent/router.py)

作用：

- LLM 优先分类
- LLM 不可用、异常或返回未知 intent 时，回退到启发式分类
- 将 LLM 结果与默认控制字段合并，确保 `requires_tools / requires_retrieval / requires_planning / candidate_tools` 不缺失

### 3. `heuristic_entry_intent`

代码位置：[entry_nodes.py](../../src/personal_agent/agent/entry_nodes.py)

作用：

- 用规则兜底识别入口意图
- 识别文件、链接、问答、总结、删除、固化和直接回答等场景
- 保证无 LLM 环境下主流程仍可运行

## 当前支持的意图

- `capture_text`
- `capture_link`
- `capture_file`
- `ask`
- `summarize_thread`
- `delete_knowledge`
- `solidify_conversation`
- `direct_answer`
- `unknown`

## 当前状态摘要

当前 entry 入口已经不是单纯的 intent 分类。`DefaultIntentRouter` 会返回包含控制字段的 `RouterDecision`，后续 planner、validator、runtime 和 executor 都会读取这些字段决定是否检索、是否调用工具、是否进入计划执行、是否需要确认。

`direct_answer` 已作为低风险、无需检索、无需工具的独立分支接入，用于闲聊、问候、感谢、澄清性问题和简单说明。LLM 路由结果会与 `_default_router_decision()` 合并，确保 `requires_tools / requires_retrieval / requires_planning / candidate_tools` 等控制字段不会缺失。

## 当前能力

- 已具备结构化路由结果
- 已具备 LLM 优先、启发式兜底的分类链路
- 已具备文件类型优先路由
- 已具备 direct answer 独立低风险分支
- 已具备删除类高风险标记
- 已具备删除类确认要求
- 已具备候选工具字段
- 已能驱动 planner 是否进入 `requires_planning`
- `ask` 默认候选工具已包含 `graph_search / web_search`

## 已知限制

### 1. 路由和执行策略耦合仍偏静态

当前 `_default_router_decision()` 中的默认控制字段是硬编码映射。新增工具或新增 intent 时，需要同步维护路由默认值、planner 模板和工具注册。

### 2. `candidate_tools` 还不是完整工具选择策略

当前 `candidate_tools` 主要是提示性字段，不等同于严格的工具选择和排序策略。虽然 `ask` 已包含 `graph_search / web_search`，但工具优先级仍主要写在 runtime 的检索回退链路中：

```text
graph_search -> local memory -> web_search
```

### 3. 缺少澄清问答机制

`missing_information` 字段已存在，但当前流程还没有形成完整的“信息不足 -> 追问用户 -> 继续执行”的闭环。

### 4. LLM 分类置信度较粗

当前 LLM 分类默认 `confidence=0.8`，启发式规则也使用固定置信度。还没有基于输入复杂度、规则命中强度或历史误判做动态校准。

## 演进方向

- 为路由层新增更细粒度的工具优先级字段
- 补齐 `missing_information` 驱动的澄清流程
- 为路由结果建立评测集和误判回归样本
- 将 intent 默认控制字段从硬编码逐步迁移为可配置策略

