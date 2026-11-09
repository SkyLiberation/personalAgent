# MiMo对象参数的有限引用展开

`TOOL-SCHEMA-REFERENCE-001`；2026-10-28。有限引用展开已接入现有MiMo策略，两份真实完整阶段各4个目标调用、共8/8对象参数通过。用户明确接受这8次成功作为阶段准入，原10项目标计划与补充组的停止报告不回写。完整task2另以新身份运行，结果由[验证记录](../to_verify/verify_results/tool-schema-reference.md)拥有；局部修复不代表业务答案正确率或发布通过。

## 问题与采用方案

此前4份真实`tool_write_artifact`响应在外层arguments解码后，内层request仍是JSON字符串，原canonical在`$.request / schema_oneOf`拒绝。该参数由oneOf引用CreateArtifact与PatchArtifact，直接节点没有type。Schema本身合法，但MiMo服务实际返回不兼容的承载。原反馈已完整送达，不能简单归为没有提醒；托管后端具体解析实现仍未知。

现由`infra/model_providers/mimo.py`在最终出站工具声明中展开有限对象引用：仅对function直接参数中缺type的对象引用／联合，先验证纯本地defs引用、无环、无ref兄弟字段及作用域变化，再使用既有LangChain helper。展开后直接为object，或oneOf／anyOf每支都显式object时采用，并为后者补object。编码Pointer、远程、循环、混合类型等不支持形式保持原Schema；defs及const／enum／default／examples不被当作待展开材料遍历。

保留definitions、discriminator及全部业务约束，不再次strictify。原ToolArgs、canonical模型及本地校验仍拥有参数语义；字符串继续拒绝，不自动json.loads后执行。没有改参数层级、Prompt、工具选择、权限、重试、费用或恢复事实。该投影深拷贝出站声明，不修改共享输入；实际容量检查消费最终wire。

## 参考与责任

[LangChain的Pydantic工具转换](https://github.com/langchain-ai/langchain/blob/b15a385cb1aa4507b86a3ba1e6430748b0c4ae4b/libs/core/langchain_core/utils/function_calling.py#L121)及[AutoGen的BaseTool](https://github.com/microsoft/autogen/blob/004749e6b7102c8fd317b9b1499ce5807223c278/python/packages/autogen-core/src/autogen_core/tools/_base.py#L114)在出站展开引用，执行仍消费原typed模型。本工程采用这一职责分工，没有照搬可放宽循环或覆盖ref兄弟约束的通用展开。[OpenCode通用工具处理](https://github.com/anomalyco/opencode/blob/6b1bc48148085411e33a4358aab9dabfcdc04aa4/packages/ai/src/protocols/utils/tool-schema.ts#L61)补根对象，普通OpenAI路径可保留原Schema；不能概括为优秀框架统一去ref。26份固定源码与完整调用链见原始参考归档。

实现只在现有MiMoPolicy.prepare_tools接入，工厂及公共编码器不新增品牌分支；其他Provider保持。Application、Journal和ToolArgs仍拥有canonical合同及执行事实。无新Port、业务字段、状态、配置、依赖或模型阶段，仅在现有模块增加三个纯helper及有界guard常量。当前技术装配由[横切架构](../../architecture/cross-cutting.md#2-模型调用的实际组合)拥有。

## 决定性证据与接入

先行规格及用户变更后的版本保存在`.tmp/tool-schema-ref-20261028/approved-spec-installed.md`。输入来自原task2首次失败及消费真实拒绝后的完整StoredModelRequest；原完整SDK参数先与封存一致，仅候选Schema投影改变，消息、18个动作、原生历史、Flash thinking及max_output_repairs=0保持。该阶段没有执行业务工具。

| 证据 | 已验证边界 |
| --- | --- |
| 真实目标调用8/8 | 两份原上下文各4次，原生write request均为object并通过原canonical；用户接受此数量，不计一次探索诊断或非目标动作 |
| 全部C正式组及补充动作10/10合法 | 8次write加2次合法直接execute；后两次不计write参数通过，原计划停止与未执行保持 |
| 实际Schema审计 | 21份SDK、234份工具Schema，只有目标request变化；原字符串拒绝，两个完整合法历史对象接受，unsupported及literal反事实保持 |
| 生产接入 | helper AST与已验证C相同，21份实际envelope等于候选；shared encoder与Adapter字节保持，独立审查无Critical／Important |
| 当前正式入口 | 新完整34轮task2已启动，冻结当前3,753文件、原英文输入和数据；结果独立报告，不提前计为完整通过 |

新完整任务保持direct/none、Flash thinking、英文Markdown和无搜索。旧baseline及partial不重跑，Pro评分使用原1M共享账本及既有资格。原计划尚未执行的两次独立中英保存／执行smoke由本次用户要求的完整task2代替，没有中文新E2E成绩。工程检查、费用、启动身份与最终原件由验证记录拥有。

## 失败尝试及评测纠正

只补直接type的B在真实首项仍返回字符串，原canonical拒绝，候选未接入；另发现其编码Pointer推导风险，但真实失败不含该形式，不能作为本次失败原因。该结果否定补type单独足够的主张，不否定等价展开方向。

C单次有限内联诊断通过后，原10项组执行9项：8项目标成功，第9项合法直接执行而未覆盖write，第10项未执行。独立复审确认自然请求没有另存程序义务，原每次必须写文件的评测限制过严；固定两次补充的首项再次合法直接执行，按停止条件结束，另一项未执行。未继续采样；用户随后接受现有8份目标结果。原组及补充passed=false保持，不改写10/10、不隐藏额外物理请求，也不声称动作选择稳定率。

本轮阶段总计12次物理、679,860已知tokens、未知0、业务执行0，包括B、一次独立诊断及两个C身份。原件、校验和、候选及审查均保留，详细分项只由验证记录拥有。

## 重新打开条件

后续新的真实E2E或其完整中间产物在已支持闭包内再次返回字符串request，或发现投影改变原Schema接受集合时，封存实际请求、响应及代码，按最早责任重新打开。合法改用其他工具、不同业务答案错误或未覆盖Schema形式不推翻已成立的对象承载边界；新问题按其真实责任单独处理。
