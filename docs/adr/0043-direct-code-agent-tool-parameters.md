# ADR 0043：模型工具直接声明业务参数

2026-10-24 决定。原生函数参数直接使用各工具的业务参数。专用 Python 的参数设计后来由 Bash 替换。[现行 Bash 决定](0056-bash-workspace.md)

## 背景与决定

LongDS 第三轮先漏 `program_ref`，收到反馈后又漏 `input_files`，两次未执行。候选采用 Code Agent 的直接代码和可选文件绑定，去除内部程序引用及互斥来源。Artifact、Command、Receipt 仍负责绑定确切输入和执行事实。[原 Python 规格与对照](../optimization/to_verify/python-data-analysis-tool.md#37-code-agent-直接参数的接入与验证2026-10-24)

模型端 `function.parameters` 直接声明业务形状，去除原统一 `arguments: object` 包装和检索工具的 `payload_field` 映射。原生 API 自带的 `function.arguments` 字符串承载保持。各具体动作分别声明调用参数，解码生成既有内部请求，业务准入保持。声明 `strict=false` 时，类型检查和授权仍在本地契约执行。[输入与错误](../topics/tools.md#输入结果与错误) · [旧映射与回放](../optimization/to_verify/conversation-loop-boundaries.md#315-显式业务载荷映射的审查候选)

## 历史验证与迁移

固定 Python 参数阶段 10/10，正式两轮均交付，仍有引用参数拒绝，官方答案评分 0/2。原配置 Journal 根为空，旧评测按原身份保存，新请求使用新声明。通用直接参数决定保留，Python 专用消费者随 Bash 切换退出。
