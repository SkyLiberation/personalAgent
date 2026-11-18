# ADR 0012：图检索返回可追溯证据

2026-07-31 决定。图检索的证据边界沿用。2026-08-12 起，最终成文由 Conversation 负责，独立 Ask 链退出。[现行 Graph 边界](../topics/retrieval-reasoning.md#graph-边界)

## 背景与决定

早期读路径将服务方合成的自由答案标成 `graph_answer` 证据。Orion 用例中，服务方没有给出来源，答案仍断言已经发布。另一次探测发现未知 provider 配置被静默改绑，工具返回的关系事实却没有转换成可用证据。

Graph provider 拥有检索及事实来源坐标，统一检索层将有绑定的 fact、edge、episode 或 note 归一为证据，Conversation 负责最终答案及适用核验。只有合成文本而无可追溯来源时，结果保持缺证。未知 provider 显式拒绝。复用已有 Graph 与 Evidence 接口，删除把自由答案注册成证据的旁路。

## 历史验证

旧 Ask 入口的隔离边界检查证明，无来源的 provider 答复被剔除，可定位的关系事实仍进入证据，非法 provider 显式失败。验证属于当时组件和应用边界。现行检索资源和证据结果由[检索专题](../topics/retrieval-reasoning.md)维护。
