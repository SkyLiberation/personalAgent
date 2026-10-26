# ADR 0043：采用 Code Agent 的直接执行参数

状态：接受；生产接口已接入，固定真实参数阶段10/10通过；正式两轮均交付，仍有引用参数拒绝，官方答案评分0/2，未取得完整研究或发布通过。

## 问题与依据

接入完整原生历史后，真实 LongDS 第三轮先漏 program_ref，收到配对拒绝后又漏 input_files，两个请求均未执行。固定失败输入、Code Agent 源码、架构分析及验收由 [Python Spec §3.7](../optimization/to_verify/python-data-analysis-tool.md#37-code-agent-直接参数的接入与验证2026-10-24)拥有。

## 决定与责任

模型提交完整 code 和可选 input_files，省略文件绑定表示空集合；删除模型侧 program_ref 与来源互斥协议。已有程序经只读文件绑定，用模型选择的标准 Python 代码运行。Artifact 继续拥有原字节，Command／Receipt 中的程序引用继续记录实际冻结和执行事实，权限与执行环境不扩大。

所有原生 function.parameters 直接使用 canonical 业务参数；同步迁移普通工具、Agent、控制动作及解码，不再增加统一 arguments 外壳或检索 action 的去壳／还原协议。保留标准 API 自身的 function.arguments JSON 字符串，它与被删除的业务包装不是同一层。

工具定义通过标准 strict 布尔值选择声明方式，Python 工具在 extras 中声明 strict=false，经 Registry、可见能力、ModelActionDefinition 传至 Adapter；其他工具默认继续 strict=true。可选值由唯一 typed 参数解析边界应用默认，不由 Admission 选择或补齐文件。strict=false 不关闭本地 Schema、授权与类型检查，structured response_format 保持原严格契约。

## 迁移、防护与退出

正式 Journal 根在实施前完整扫描为空；切换前重查全部保留快照，包含已结算记录。旧评测根及原始 SDK／Command／digest 保留原源码身份，只读；新验证使用空根。发现正式旧型记录时先处理其 REL 读取或迁移边界，禁止猜补或重写原始事实。没有兼容开关和第二套生产解析。

改动复用原 Tool Port、PythonExecutionService、Journal 与沙箱；净删除来源分支、payload_field 和统一包装构造。标准 strict 字段只传递工具声明，不引入通用策略层。实际输入、程序复用、原字节／manifest、恢复零重执行、拒绝及原生历史按唯一 Spec 验证；模型阶段按 baseline10／candidate10、原 low 配置及预声明预算执行。失败保留原生历史已成立机制，停止依赖流程，按 EVD 复审；接受 ADR 不代表工具漏参已修复或长任务已通过。
