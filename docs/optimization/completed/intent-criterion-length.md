# 用户验收标准的完整字符串承载

`INTENT-CRITERION-LENGTH-001`；2026-10-28。已删除criterion的500字符上限，原707字符完整返回经正式typed解析通过；新第5轮实际请求已消费无maxLength的Schema。该确定性长度问题关闭，意图语义与完整task2成绩分别判断。

## 问题与采用方案

原task2第5轮首次返回业务Markdown，一次纠正后产生合法JSON，其中11组用户映射被完整写成707字符criterion，触发原500上限；入口502，主决策及工具执行均未发生。API两次200／stop，原件及同轨输入审计位于`.tmp/task2-intent-block-20261028/audit.json`。长度限制没有业务或下游消费者依据，原`ReviewCriteria.criteria`本来就接受完整字符串。

现仅在`application/conversation/interaction_intent.py`将criterion的`Field(min_length=1, max_length=500)`改为`Field(min_length=1)`。沿用工程已有的非空字符串契约及Pydantic字段机制，无新抽象、依赖、字段、状态或模型阶段。500上限删除，不换成另一个数字，不截断或机械拆项。模板正文、模型、Provider策略、输出32,768及一次结构纠正保持；模型输出仍受原预算约束。中英及其他Provider共用此Application契约，未增加Provider专有分支。

## 责任、接入与决定性证据

Conversation通过原`derive_interaction_intent`及Model Port产生提议；`ReviewRequirement`拥有typed形状，Admission解释来源，`ReviewCriteria`和Journal冻结标准及实际事实，下游核验消费完整字符串。当前行为见[核验专题](../../topics/verification-and-completion.md)。无需移动模块或新增写入口。

先行规格及实施状态快照保存在`.tmp/criterion-length-20261028/approved-spec-and-state.md`，执行计划与回放原件保存在同目录。已确定需求与验收如下：

| 需求 | 实际证据及限定 |
| --- | --- |
| CRL-1 完整标准不受500字符误拒 | 同轨707字符返回在旧契约拒绝、新契约通过；原文字及source结构逐字保持，Schema差异只有该maxLength删除 |
| CRL-2 原拒绝与历史身份保护 | 五轮共7份完整物理返回从4份接受变为5份接受；原四份合法JSON保持，两份Markdown仍拒绝，派生空criterion仍拒绝。旧StoredModelRequest与新Schema不符仍拒绝restore，不嫁接新类型 |
| CRL-3 实际接续消费 | 当前源码3,753文件冻结至`.tmp/il28/code/`；新第5轮实际StoredModelRequest已无maxLength且minLength=1、max_output_repairs=1。新段经正式HTTP启动，API200；用户结果继续由完整任务独立验收 |

回放只使用原完整输入及响应，不调用模型或执行工具；这是确定性校验修复，按方案推进技能不适用十次语义判断门槛，不主张语义正确率改善。`before.json`、`after.json`、`scope-audit.json`及`launch-audit.json`保留具体来源与身份。源码相对上一冻结版本只含此字段删除及evals规范文字更新，Prompt、Adapter及Provider字节保持。

## 原任务接续与边界

500份canonical文件逐字复制核对，前四轮对话、文件、Command、Receipt和3/4原评分保持；旧失败run不改写。新会话轮次沿同一conversation与原许可，以新run重新提交原第5轮；原53,693,887授权及到期不变，累计3,536,491已知及5次历史未知仍保留，60M活动管理余额51,299,669。恢复脚本只请求5—34轮，停止封存后仅评分实际新答复，沿原Pro资格及1M账本（此前251,986／未知0）。

新段于北京时间19:42:20启动，实际worker PID33428，归档`.tmp/ir28/c/`。它与旧段明确分源码身份，不作为同版本完整消融。完整运行、官方业务评分及后续独立阻塞由[验证记录](../to_verify/verify_results/tool-schema-reference.md)拥有；原首响职责偏移与source6／8错误没有被本长度删除宣称解决。

独立审查无Critical／Important；Ruff、14包／43边分层、规范及本地链接检查通过，未维护或运行单元测试。生产规模为单行替换、删除一个约束，无新增生产单元。权限、未决执行、原终态、429、服务失败或预算停止均保留，不自动重采样。

## 重新打开条件

新的真实输入仍因验收标准长度被不合理拒绝，或发现存在未迁移的同职责500上限时，封存原件并重新打开。JSON格式、来源绑定、标准语义或业务计算的独立失败按各自责任处理，不回滚已成立的完整字符串承载。
