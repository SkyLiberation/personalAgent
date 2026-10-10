# 生产 Prompt 模块规范

> 适用于 `src/personal_agent/kernel/prompt_templates/**`，补充根 [AGENTS.md](../../../../AGENTS.md)的模板约束。修改模板前阅读 [COD 通用契约](../../../../docs/devSpec/code-structure.md#6-生产-prompt-是版本化代码契约)和 [CTX 输入审计](../../../../docs/devSpec/context-memory-retrieval.md#12-system-prompt-与-context-的设计及问题分析)；仅整理本文时按 DOC 检查。本文拥有注册、序列化和版本规则。

## 1. 唯一注册与生产消费

生产 Prompt 定义为 `PromptSpec`，使用稳定的职责名称，由 `personal_agent.kernel.prompts` 唯一注册。调用方从注册表取得正文与版本，并写入请求及 Trace；不复制模板、另写版本或保留新旧 fallback。

本模块只拥有指令与输入序列化，不拥有业务事实、权限、执行、状态迁移、预算或完成判断。评测 Prompt 遵守 COD 的通用性要求，但不因此注册为生产能力。

## 2. 结构与输入边界

动态区块使用稳定结构并明确数据与指令边界；来源、角色、可信范围及成功标准按 COD 和 CTX 表达。不是所有自然语言正文都必须转换为 JSON，结构化边界也不能替代语义说明。

已有文字的引用与恢复职责由 [COD 文本引用规则](../../../../docs/devSpec/code-structure.md#21-已有文字通过引用传递)拥有；序列化保留当前合法引用、可读原文和来源对应关系。

只有明确的行为保持迁移才要求实际发送字节不变。修复已知语义缺陷按产品变更取得证据、更新版本，不能同时声称保持字节。

## 3. 版本与验证

改变模板正文、字段语义、示例或输入构造契约时更新 `PromptSpec.version`；动态任务数据变化不等于模板版本变化。

静态检查与适用 Offline Eval 核对注册、版本、实际输入往返、输出 schema 和消费链。字节保持声明以实际请求对照为依据；语义变更按 COD 运行真实模型评测及适用 target E2E。未获准候选删除生产正文、旁路和专用版本，必要诊断与有效证据按归档规则保留。
