# ADR 0030：以文档版本和原文位置标识引用

2026-09-18 决定，2026-09-22 扩展到全部生成端引用。现行语法与投影由[引用专题](../topics/context-engineering.md#可见证据的随文引用编号)维护。

## 背景与决定

正式研究第五稿提交不存在的 `e1698`，对应原文第 1698 行却有三个合法编号。重复读取可为同一位置产生不同身份，并要求模型在原文行与编号之间转换。改以文档版本和实际返回位置作为引用身份。

Journal 和 Artifact 拥有原始结果。文档别名只由本次可见集合派生，重复读取相同版本不重新编号。模型选单行、连续整行或实际返回的字符范围，由代码恢复原文与来源。校验拒绝缺失中间行、越界和同坐标内容冲突；部分返回只在其原范围内可引用。搜索摘要仍属于工具结果，未展示的原文不进入引用。复用原绑定器与执行记录，删除整条结果号和重复投影。

采用 OpenCode 与 Gemini CLI 以原文件坐标表达读取范围的方式，引用语法和授权由本工程决定。[OpenCode 固定读取实现](https://github.com/anomalyco/opencode/blob/v1.2.0/packages/opencode/src/tool/read.ts) · [Gemini CLI 固定读取实现](https://github.com/google-gemini/gemini-cli/blob/3c311beac2e78336816dd4a123db39743f9fbf85/packages/core/src/tools/read-file.ts)

## 验证边界

按用户要求，原改造只执行 Offline 验证。历史对照覆盖重复来源、快照和版本、同文档连续行、部分行及不可见范围。两个真实短样本分别消费网页正文和搜索结果。后续发现错绑、原文变化或可见性回归时，回放实际窗口和引用提交。[历史证据](../optimization/citation-coordinate-confusion.md) · [后续观察](../future/citation-coordinate-identity.md)
