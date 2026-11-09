# MiMo工具引用参数修复与task2完整验证

2026-10-28。机制由[引用投影固化方案](../../completed/tool-schema-reference-projection.md)拥有，先行规格与用户调整保存在`.tmp/tool-schema-ref-20261028/approved-spec-installed.md`。引用投影后原段已交付4/34轮、Pro评分3/4，第5轮因意图阶段criterion长度约束停止；4次写文件均成功且request为对象。长度阻塞已按[完整字符串承载](../../completed/intent-criterion-length.md)关闭，接续又交付3轮且评分3/3，第8轮服务方过滤后停止，两段累计6/7正确，完整task2未完成。

## 问题、采用方案与参考

四份历史MiMo响应把`tool_write_artifact.request`输出成JSON字符串；原Schema为两个对象的`oneOf + $ref`，本地拒绝路径为`$.request / schema_oneOf`。外层function.arguments本来就是JSON字符串，不属于错误；错误是外层解码后，内层request仍为字符串。原反馈完整带回被拒参数与Schema，仍发生同形错误，不能归为反馈没有送达。

参考[LangChain的Pydantic工具出站转换](https://github.com/langchain-ai/langchain/blob/b15a385cb1aa4507b86a3ba1e6430748b0c4ae4b/libs/core/langchain_core/utils/function_calling.py#L121)及[AutoGen的BaseTool Schema](https://github.com/microsoft/autogen/blob/004749e6b7102c8fd317b9b1499ce5807223c278/python/packages/autogen-core/src/autogen_core/tools/_base.py#L114)，采用出站引用展开与原typed执行校验分责。[OpenCode的通用工具Schema处理](https://github.com/anomalyco/opencode/blob/6b1bc48148085411e33a4358aab9dabfcdc04aa4/packages/ai/src/protocols/utils/tool-schema.ts#L61)补根对象类型，其普通OpenAI路径保留inputSchema；因此不能概括为所有优秀框架都删除ref。固定源码26份及调用链保存在`.tmp/tool-schema-ref-20261028/references/`。

生产落点是现有`MiMoPolicy.prepare_tools`。对缺type的直接对象参数，先确认纯本地defs引用、无环、无ref兄弟字段及作用域变化，再复用既有LangChain helper展开，并在联合全部为object时补显式object。保留defs、discriminator及业务约束；其他Schema保持。没有改ToolArgs、参数层级、Prompt或其他Provider，没有入站json.loads修复、额外重试或新依赖。托管Token Plan后端身份尚未知，公开parser只提供机制旁证，不能写成服务端根因确证。

## 实际阶段验证与停止身份

两份输入逐字恢复原第4轮首次失败及消费真实拒绝后的完整StoredModelRequest，完整SDK参数先与原件相等；保留全部消息、原生历史、18个动作、Flash thinking、32768输出、max_output_repairs=0。阶段调用不执行任何业务工具。

| 身份与已执行量 | 结果 | 物理请求／已知tokens／未知 |
| --- | --- | --- |
| B：只补type，1项 | request仍为字符串，原canonical拒绝；其余9项未执行，候选撤回 | 1／51,268／0 |
| C：一次有限内联诊断 | 原生write request为object，原canonical通过；只支持继续验证 | 1／55,821／0 |
| C：原10项计划，执行9项 | 两上下文各4份write通过；第9项合法直接execute_python，目标未覆盖，第10项未执行；原passed=false保持 | 9／521,045／0 |
| C：评测复审后的固定2项补充，执行1项 | 首项再次合法直接执行，依停止条件结束；第二项未执行，原passed=false保持 | 1／51,726／0 |

合计12次物理请求、679,860已知tokens、未知0、工具执行0、模型耗时合计约1,219.142秒。C正式组及补充的10次实际动作全部canonical合法，其中8次目标调用均为对象、2次非目标不能计作write参数通过或失败；一次探索诊断单列，不补入8份目标分子。原自然请求没有保存文件义务，直接执行是合法路径，独立`review-sampling.md`确认原每次必须写文件的限制过严。

用户随后明确“8次成功已经足够，开始完整测试”。该指令取代原各上下文5份的准入数量，生产接入依据为现有各4份、共8份目标成功；不是将原停止组改成10/10，也没有继续采样凑数。B失败、各组原件与seal均保持。

## 生产装配与工程证据

`audit-c.json`以21份实际SDK请求、234份工具Schema核对只改变目标request，原defs与discriminator保持；原字符串仍拒绝、两个完整历史合法对象仍可通过当前WriteArtifactArgs。派生的编码Pointer、ref兄弟、远程、循环和混合类型反事实均保持原Schema；字面量example不被递归改写。它是实际接口审计，不是模型结果或单元测试。

生产`mimo.py`与已验证C的纯函数AST相同，仅helper改成私有名并接入原prepare_tools。`production-audit.json`的21份实际envelope逐份等于候选投影，输入未被修改，shared encoder与Adapter逐字保持。独立`review-production.md`无Critical／Important；旧状态文字已同步。生产Schema长度仍进入最终wire容量检查。

Ruff的F401／F811／F821检查及分层检查通过，仍为14包／43边、无循环及禁止边。候选新增三个有界纯helper及常量，无Port、业务字段、状态、模型阶段或依赖；生产只改现有MiMo模块。未新增、维护或运行单元测试。

## 最新task2完整测试

当前生产源码、evals及pyproject共3,753文件冻结到`.tmp/rf28/code/`，`identity.json`绑定全部字节。独立启动脚本`.tmp/task2-ref-full-20261028/full.py`使用原LongDS v1.1英文task2的34轮、原CSV、固定Docker镜像和正式HTTP；新conversation及许可，生成Flash thinking enabled、最新英文Markdown资源394条、direct/none、无搜索。旧baseline及partial不重跑、不覆盖；不同模型／Prompt的旧成绩不能用作单变量收益。

新归档`.tmp/rt28/`，启动launcher PID31136、实际worker PID33100。每轮10M／40次决策，原60M活动上限携入2,175,041已知tokens及4次历史未知的4,131,072管理预留，新许可剩余53,693,887。这里包含既有英文运行、Markdown smoke和本轮引用诊断的实际费用，不清零历史未知。

原生成于约12:03停止并封存：请求5轮、交付4轮、后续29轮未执行，33次物理请求、1,361,450已知tokens／未知1、3,194.25秒。第5轮首次返回业务Markdown；一次纠正返回JSON，但707字符criterion超过500上限，入口502，未进入主决策或执行。两次API均200／stop、合计38,924tokens，不属于本轮write参数字符串化。原停止与同轨来源坐标错误由`.tmp/task2-intent-block-20261028/audit.json`定位；后者未被长度修复宣称解决。

MiMo Pro只评分实际四轮：3/4正确，轮次1、2、4通过、3失败；新增评分14,725tokens，1M共享账本累计251,986／未知0，组为`reference-projection-full-01-34`。最终`.tmp/rt28/final.json`、原seal及前四轮结果保持。原计划的两次独立中英smoke未执行；完整task2仍未完成，不计发布。用户随后授权取消单项长度上限并从原第5轮接续，新source及采集身份分别为`.tmp/il28/code/`、`.tmp/ir28/c/`；不重新生成或评分前四轮，不把不同源码分段当作同版本完整消融。

接续于北京时间19:42:20启动、约20:35停止，实际worker PID33428，原第5轮的新run为`irun_7300fd445d4b405a8af068a8108f5764`。实际intent请求criterion Schema无maxLength且minLength=1、仍只允许一次结构纠正。500份canonical文件复制核对通过，同会话、原53,693,887许可与截止保持。新段交付第5—7轮，Pro评分3/3；第8轮先超时、同请求技术重试后返回content_filter，后26轮未执行。服务方未返回命中片段或规则，具体触发内容未确定；审计为`.tmp/task2-content-filter-20261028/audit.json`。

新段39次物理请求、3,452,710已知tokens／未知1，3188.438秒；新评分16,362，Pro共享账本268,348／未知0。两段累计交付7/34、正确6/7；全部生成活动累计6,989,201已知／未知6。原件为`.tmp/ir28/final.json`及封存捕获。新段出现2次request字符串拒绝及6次对象接纳，因此原8/8局部证据不能推广为已经消除整任务的同类错误；本次仅留证，不追加MiMo补丁。用户随后要求[切回MiniMax重新执行](../prompt-language-selection.md#12-切回-minimax-后重新执行-task22026-10-28)，旧答案与评分不重跑。
