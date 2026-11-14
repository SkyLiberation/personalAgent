# Windows 模型原件归档路径压缩

`quantitative-financial-analysis` 收到模型 HTTP 200 后，对话在 `application_persistence` 阶段返回 HTTP 500。同机用另一份封存的 Toolathlon 真实响应复现了 263 字符的路径在 `os.replace` 触发 `WinError 3`。当前配置的 `data/interaction_runs` 在切换前有 0 份快照，历史归档按原版本查阅。[原运行报告](../../../.tmp/ta-notion-mcp-1112/remaining-notion/quantitative-financial-analysis/report.json) · [Windows 复现](../../../.tmp/pa-path-1113/baseline.json)

| 需求 | 接入与验证结果 |
| --- | --- |
| `ARCHIVE-1` 原输出根长度下可保存完整响应 | 现有文件 Journal 直接在运行目录下以完整调用 ID 建目录，保留 `request.json`，按十进制序号写 `0.json`、`1.json` 等。同长目录回放实际响应，正式响应路径从 263 减至 198 字符，请求路径 204 字符，临时路径 209 字符。写入字节与原件一致。 |
| `ARCHIVE-2` 原件与恢复语义保持 | 完整尝试 ID 保存在响应原件和 Trace 引用中。Journal 经原锁和原子重命名写入，读取时按连续整数序号恢复并核对身份及摘要。用真实快照重开后，引用和字节一致。缺号、重复尝试、同序号不同内容均被拒绝。补记已写入但未提交引用的响应时，只计费一次。 |
| `ARCHIVE-3` 评测消费者跟随新布局 | 两处 Toolathlon 请求采集共用文件定位，回放读到了相同请求摘要。LongDS 路径预检按新布局估算最长临时文件，同机接受浅目录并拒绝超长目录。 |

局部验收用一组真实归档回放，回放未调用模型。随后在与原运行等长的输出目录下重跑 `quantitative-financial-analysis`，对话返回 HTTP 200，20 份模型响应均写入 198 字符的路径。整例评分结果见[问题记录](../../problems/toolathlon-verifierd.md#工具参数和错误恢复)。后续真实样本若再因归档长度失败，以新的路径和失败边界重新定位。[回放报告](../../../.tmp/pa-path-1113/report.json) · [Journal 实现](../../../src/personal_agent/application/conversation/journal.py)
