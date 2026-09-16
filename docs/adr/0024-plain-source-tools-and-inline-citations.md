# ADR 0024：正文行坐标、独立搜索读取与随文引用

**状态：读取与引用局部检查点成立，保留工程接入；原正式用户结果失败。** 本决定按用户 2026-09-16 的明确要求替换旧片段坐标，并同步参考引用组件。过程由 [优化第 103 节](../optimization/evidence-acquisition.md#103-正文行坐标统一与预编号引用联动)拥有；引用历史反例由[对象与来源支持记录](../optimization/answer-object-mismatch.md)拥有。

## 背景与决定

旧来源正文以 JSON 行保存字符片段，搜索存储记录会命中 URL 元数据，也会漏掉跨片段的连续原词。旧 `oN:lL` 引用又要求模型区分观察序号和存储行号。确定性反例与历史真实引用失败分别保留，不能合并成模型唯一失败根因。

`WebReadOutput` 改为 `web-source-text-v2`，`source_text` 保存抓取服务给出的原始提取正文，来源 URL 与服务方保存在外层。Artifact 是卸载正文唯一存储，不额外保存拼接副本。`search_action_output` 使用 rg 定位同一正文的自然行；`read_artifact(resource_ref, start_line, limit)` 按同一坐标读取。超长行用可直接复用的 `next_read` 补充 `start_column`；部分返回不计作整行已读。

引用物化根据本次实际可见成功执行生成 `e1` 等单一编号，并直接附在观察或正文行旁。Conversation 只复制 `evidence_id`；代码从相同目录恢复原文。编号仅在当前可见输入内有意义，不是持久资源身份。原 `FinalMessage.segments`、多证据提交、未引用段落保留、非法引用拒绝及修订循环继续使用。自由字符串仍可能生成非法编号；简化编号不是供应商原生引用保证。

## 责任主体与生产路径

Artifact 拥有身份、作用域、版本和正文；Admission 只接受本次可见的准确资源引用。rg Adapter 通过固定参数、`shell=False`、授权正文标准输入运行，限制超时和输出，不接受模型指定命令、二进制或宿主路径。未新增通用 Shell 或操作系统沙箱；进程执行权限仍属于宿主部署边界。

Conversation 拥有查询、阅读范围、证据选择和答案。读取工具返回位置事实；`source_reading.py` 从实际窗口计算覆盖并集；`citations.py` 唯一拥有临时编号与还原；Verifier 继续核验答案和已提交证据，不检索全文、不代写答案。

正式路径为原 Conversation 入口、生产 Composition Root 中的 `RipgrepArtifactSearch`、现有 Artifact Port、Observation、Final、Verification 和 Completion。无新增 Agent、Planner、模型调用、持久化投影或独立完成判断。

## 外部机制比较

2026-09-16 核对以下 A 级源码；这些实现只支持机制选择，不替代本地验证。

| 固定实现 | 采纳机制 | 未采纳部分 |
| --- | --- | --- |
| [OpenCode v1.2.0 grep](https://github.com/anomalyco/opencode/blob/v1.2.0/packages/opencode/src/tool/grep.ts)、[read](https://github.com/anomalyco/opencode/blob/v1.2.0/packages/opencode/src/tool/read.ts) | 搜索返回行号，独立读取接受起始行与行数 | 任意目录入口、按修改时间排序、超长行截断后不能续读 |
| [Gemini CLI ripGrep](https://github.com/google-gemini/gemini-cli/blob/3c311beac2e78336816dd4a123db39743f9fbf85/packages/core/src/tools/ripGrep.ts)、[read-file](https://github.com/google-gemini/gemini-cli/blob/3c311beac2e78336816dd4a123db39743f9fbf85/packages/core/src/tools/read-file.ts) | 受控引擎调用、正文行范围、明确剩余内容 | 自动扩上下文、额外目录指令注入和通用沙箱平台 |
| [LlamaIndex v0.12.52 CitationQueryEngine](https://github.com/run-llama/llama_index/blob/v0.12.52/llama-index-core/llama_index/core/query_engine/citation_query_engine.py) | 先给来源编号，再要求生成器引用该编号 | 新增 RAG 检索、再次切片、把引用存在当作支持关系 |
| [Haystack v2.18.1 AnswerBuilder](https://github.com/deepset-ai/haystack/blob/v2.18.1/haystack/components/builders/answer_builder.py) | 输出引用索引确定性映射输入来源 | 无引用默认绑定全部、越界编号仅警告 |

## 复杂度说明（Complexity Justification）

新增正文窗口函数及 typed 参数，复用 Artifact、权限、Observation 和验证。删除网页 JSON 分片编码及搜索前重组/坐标回映；删除模型可见的 o/l 组合目录。长行范围是继续读取和覆盖计算所需的事实，不持久化派生覆盖。搜索 Port 隔离外部进程，生产装配有真实调用者；无新增表、配置开关、fallback 或双写。

相对本轮 `before.zip`，12 份生产文件净增 66 行，逐文件差异由归档 `changes.json` 拥有。该基准已包含第 102 节的 rg Adapter 与生产装配，不能把这个数字当成两轮总变更量。定向 227 项测试通过，覆盖原文、坐标、权限、引用和旧工具拒绝；完整用户结果单独判断。

## 旧读取保留例外与退出

用户明确要求保留旧读取工具，优先于默认删除旧实现规则。`read_action_output` 的代码和契约暂留，但不进入模型工具投影，Admission 拒绝该名称，失败时不自动回退。用途是本轮人工比较与原实现留存；不能把仅隐藏 schema 当成禁止调用。2026-09-30 为保留复核及计划移除日期；如用户继续要求保留，须更新本节边界与期限。旧历史日志保持只读；本轮使用新交互，不保证旧格式运行跨版本恢复。

## 证据、风险与撤回条件

独立 Contract 验证真实 rg、原文保真、位置衔接、长行恢复、零匹配、权限、旧工具拒绝、引用还原和部分覆盖；原中文 Product E2E 单独验收用户结果。具体执行记录与原失败完整保存于 [归档](../../.tmp/plain-source-tools-20260916)，预声明成本与停止条件见其中 `predeclaration.md`。

真实目标用例为 `1 failed`，自然达到 48 次工具调用上限并返回 `limitation`。同一轨迹八稿均通过答案引用绑定，29 次成功搜索或读取返回的 1,275 行与 Artifact 对应原文一致，另一次搜索分页越界明确失败。既有局部语义拒绝、覆盖拒绝和补读均被消费。保留这些机制，不因后置核验失败撤回已成立的确定性读取修复。缺项分类五次输出校验失败、两次来源支持拒绝和一次覆盖拒绝分别保留，不能把八次合法交接称为八个成功产品样本。

若新路径破坏权限、原文、位置或覆盖，修正对应确定性责任主体并先回跑反例。真实模型仍可能漏引、错引或生成无据结论；现有拒绝与修订继续执行，不因工具接通宣称语义问题解决。同责一次有界修正仍失败，停止叠加补丁并保留失败；其他独立失败按检查点分别归因。最终验收未通过前不声明可发布。
