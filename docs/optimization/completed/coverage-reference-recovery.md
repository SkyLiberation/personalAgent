# Coverage 无效引用的有界恢复

问题编号：`RESEARCH-COVERAGE-REFERENCE-BINDING-001`。局部引用合法性恢复已关闭；完整用户结果见[移除复核验收](../to_verify/normative-context-acquisition.md)。

局部两例 **2/2**，五模块已原样迁入生产，依赖与 lint 通过。新正式 target 原结果 0/1：在来源修订阶段耗尽原产品预算，Coverage 未到达；没有复现或否定本局部修复，也不能称正式验收通过。新真实修复一次通过，27,566 tokens、89.05 秒、未知零；原失败与旧错误输出保持，见[资格密封](../../../.tmp/coverage-reference-recovery-20261015/REPORT.json)及[生产迁移](../../../.tmp/coverage-reference-production-integration-20261015/REPORT.json)。第二次修复额度本次未消耗，不能声称实际进行了两次纠正。

## 已证明问题与责任

正式中文 HTTP 用例已完成七条 Source，自动反馈复核零次，但 Coverage 第二份输出使用实际未返回的引用 `d8:1`，最终 HTTP 422、无答案、独立评分未运行。原 Product E2E 0/1 保持，见[密封失败](../../../.tmp/source-direct-feedback-production-target-20261014/REPORT.json)。原生请求 0075／0077 和 SDK 响应 0076／0078 属同一完整真实阶段；第一次有 37 项引用对象形状错误，唯一结构恢复修正了形状，却新增不存在的坐标。不能归为 Source 分类失败，也不能把无效引用静默删除或映射为另一个坐标。

引用解析由 Application 的 canonical resolver 拥有；Model Port 仅执行 typed 输出校验与既有有界修复。当前引用存在性在 Port 修复结束后才检查，因此模型没有收到这项确定性反馈。Schema 形状与实际坐标范围是不同约束，形式合法不能替代可绑定。

## 已采用方案

Coverage 构造时，用同一实际 source_material 的可见坐标建立临时输出校验类型，字段和 JSON Schema 与 canonical `ResearchCoverageReport` 相等。只在引用叶节点调用现有坐标 resolver，拒绝未返回、缺行或扩大的部分行引用；不改变报告内容、不决定语义类别或 covered 状态。通过后恢复 canonical 类型，临时校验类型不持久化。

结构与引用错误共用 Model Port 的一套修复循环。请求内部增加 `max_output_repairs`，默认一次保持原操作，本例 Coverage 固定最多两次纠正：已证实的形状纠正和其后新出现的坐标纠正，总物理上限三次。没有 SDK／服务重试、额外应用层重试或反馈复核；超限仍确定性拒绝。该字段只控制调用预算，不进入模型业务输出，也不新增业务字段、分类、状态或配置。移除它则只能扩大所有操作的恢复上限，或另建重试 owner，成本更高。共享修复模板删除“唯一一次”的固定数量陈述，仍要求本次完整修复、遵守 typed 契约与数据边界。

参考两份 A 级机制：[PydanticAI 输出校验与 ModelRetry](https://pydantic.dev/docs/ai/core-concepts/output/)、[LangChain structured output 错误反馈](https://docs.langchain.com/oss/python/langchain/structured-output)。只采用将确定性输出错误交回模型、有明确预算的方式；不引入框架、业务降级或语义复审。是否可用仍由本项目真实输入验证。

## 已确定验收与边界

隔离候选 `.tmp/coverage-reference-recovery-20261015/`，生产与配置保持，原失败封印不变。

- `CVR1`：完整原 Coverage 阶段，初始 SDK 请求与原请求相等时，只复用真实第一份原生输出；后续修复模板已变，第二份必须重新调用真实 MiMo，不能把旧第二份输出替代新请求的决定。旧第二份无效坐标另作零调用反事实，必须在 typed 校验中拒绝。现有同一循环最多再实际生成两份报告，保留完整原始输入、模型、thinking、480 秒、Schema 和 canonical 判断。新报告须引用全部可绑定，覆盖冻结原项并保持实质覆盖说明；无效旧报告不得进入 ResearchReview。
- `CVR2`：此前第十四版完整研究的真实合法 Coverage 响应，原完整输入逐值恢复，零付费回放。Schema 和业务消息保持，合法单行、连续范围、覆盖状态及说明不得改变，也不产生修复请求。
- 两例一次，最多两新增物理请求、120,000 新已知 tokens、1,200 秒；服务、协议、语义或预算失败停止，不追加成功采样。真实初始输出的旧成本不重复记为新支出，旧第二份输出只作反事实，不作为新链路的前置决定。

局部通过后原样迁入生产，执行依赖、lint、文档与契约检查，再在新代码身份下运行同一正式中文 HTTP target 一例一次。产品仍为 32 模型轮、48 工具、2,000,000 tokens、单调用 480 秒、HTTP 7,200 秒，独立评分另限 200,000。原失败不改写；正式用户结果单独计分。若本方案引入回归或相同坐标约束在既定有界纠正后仍失败，停止受影响生产准入并复审，不扩大修复预算。

## 重新打开条件

仅当新的真实 E2E 或真实阶段产物复现未返回引用仍被接纳、未能进入既定恢复或合法引用被误拒时重新打开。未到达 Coverage 的预算失败由[输入成本复审](../to_verify/research-input-budget.md)拥有，不追加本局部稳定性门槛。
