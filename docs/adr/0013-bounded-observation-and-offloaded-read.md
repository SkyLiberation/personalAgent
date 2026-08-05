# ADR 0013: 单次 Observation 的上下文边界与卸载重读

- 状态：Accepted
- 日期：2026-07-31
- 影响范围：`ConversationService` 的 Observation 装配、`read_action_output` 能力、回合终止判据
- 相关：[ADR 0010](0010-runtime-owned-interaction-verification.md)（同一形状：结构性不变量不交给 prompt 措辞）

## Goal / Current Incorrect Behavior / Expected User-visible Result

用户目标：让 Agent 读一个真实的大文件（GitHub `torvalds/linux` 的 `MAINTAINERS`），回答
其中某个条目登记的邮件列表地址，以及该地址在文件里的真实行号。

改动前的错误行为：一次 `github.get_file_contents` 返回 **1,940,197 字符**，整段直接进入
LLM Context，该回合提交 **776,720 tokens**，是声明上限 `max_total_tokens=32,000` 的 **24 倍**。
上限存在但对单次超大返回不成立。

期望的用户可见结果：同一输入下拿到逐字正确的地址和真实行号，且提交用量不被单次返回击穿。

## Business Expansion or Proven Constraint / Out of Scope

已证明约束：**一次工具返回的体积不受任何生产机制约束时，回合预算只是一个声明。**

Out of scope：跨回合的总量上限（`max_total_tokens` 按回合起点对已提交用量判定，本 ADR
不改这个语义）；模型对「读哪一段」的选择权；摘要式压缩（见下方被拒方案）。

## Baseline / Executed Result / Root Cause

E21 从正式 HTTP 入口 `/api/conversation/turn` 以用户自然表达执行，未泄漏内部能力名。

| 轮次 | 观察到的行为 | 根因 |
| --- | --- | --- |
| baseline | 单次 payload 1,940,197 字符，提交 776,720 tokens | 无单次 Observation 边界 |
| 加边界后 | 重读窗口 `splitlines` 只有 19 行，单行长 1,740,066 字符，任何 offset 都取不到目标 | 卸载物是 `json.dumps` 结果，`\n` 被转义成两字符，行号不存在 |
| 修 escaping 后 | 关键词命中只返回 `29500 'XFS FILESYSTEM'`，模型据此答 29500（真实行号 29502） | 命中行无上下文，节标题回答不了标题下面的内容 |
| 加上下文后 | 模型反问「你要哪个分支的 MAINTAINERS」，未重读；自己的 Observation 里已有 SHA `0d7987278c07` | 回合可以在持有未读证据时以提问收尾 |

四个根因是四个独立缺陷，每一个都由实际执行暴露，不是推断。

## Decision Ownership / Fact Owner and Write Path

| 事实 | Owner | 写入口 |
| --- | --- | --- |
| 一次 Observation 能进入 Context 的体积 | `observation_bounds` | `bound_observation_payload` |
| 被卸载文本的形态（原始串 vs 序列化） | `observation_bounds` | `select_offload_text` |
| 某个窗口的内容 | `observation_bounds` | `excerpt_payload_text` |
| 卸载物的身份与归属 | `ArtifactPort` | `write_generated`（`producer_key` 幂等） |
| 重读时的 principal 与 scope | `ConversationService` | 回合已解析的请求身份 |
| 「读哪一段」 | 模型 | `read_action_output` 的 `keyword` / `start_line` |
| 「未读完能否以非 answer 收尾」 | `ConversationService` | `_unread_offloaded_resource` |

`read_action_output` 投影为能力但在 Service 内执行，因为卸载物属于本次交互：写它的
principal 和 scope 是回合解析出的请求身份，模型既不知道也不得断言。先例是
`_KNOWLEDGE_SAVE_CAPABILITY`。

## Referenced Industry Mechanism

- **分页而非摘要**（A 级）：Claude Code / OpenAI Codex 的文件读取工具都返回带行号的窗口
  加总行数，让模型自己翻页，而不是替它压缩。摘要会把「第 29502 行」这类事实先丢掉。
- **命中行带上下文**（A 级）：ripgrep `--context`，`BurntSushi/ripgrep`
  `crates/core/flags/defs.rs` 中 `-A/-B/-C` 的定义。本工程取 before=2 / after=4，
  因为 `MAINTAINERS` 的条目形状是节标题后紧跟数行 `L:` / `M:` / `F:`。
- **未采纳**：外部实现常见的「按 token 数截断 + 提示已截断」。它不给可寻址的重读入口，
  被截掉的事实在任何 offset 都取不回来，正是 baseline 第二轮的失败形态。

## Canonical Models

一个卸载物一个 `ResourceRef`，`resource_id` 是它的身份。窗口 payload 回带
`resource_id`，使「这个远端输出读过没有」成为对 inputs 的纯函数判定，不需要在回合里另
存一份已读集合。

`retrieval` 只在 Observation 被界定时出现，字段是 `omitted_chars`、`original_chars`，加上
`resource_ref` + `read_more`，或卸载失败时的 `unavailable_reason`。卸载失败可见而不静默。

## Affected Modules and Dependency Direction

`application/conversation/observation_bounds.py`（新增，无外部依赖）
← `application/conversation/service.py` → `ArtifactPort`。方向仍指向内层，Domain 未被触及。

## Complexity Added, Removed and Rejected Alternatives

新增：一个模块（界定 + 卸载文本选择 + 窗口）、一个 Service 内能力、一条终止判据。

净复杂度需要如实记录：**本次没有删除既有生产路径**，因为这条路径之前不存在。改动过程中
被否决并在落地前移除的是一版注册工具形态的 `read_action_output`——它从模型参数接收
`user_id`，等于把身份交给模型断言，被 Service 内执行的形态取代。它从未进入提交历史，
不计作删除项。

被拒方案：

- **摘要压缩**：把行号这类事实在进入 Context 前就丢掉，与用户目标直接冲突。
- **提高 `max_total_tokens`**：把上限改成能容纳 776,720，等于取消上限。
- **在 prompt 里要求模型读完再收尾**：ADR 0010 已证明结构性不变量不能靠措辞执行。
- **为已读资源另建持久化投影**：窗口 payload 回带 `resource_id` 后可由 inputs 推导，
  持久化派生值违反 §2.3。

终止判据只否决出口，不否决结论：未读完时 `clarification_required` / `limitation` /
`failed` 被 typed `DecisionFeedback`（`offloaded_output_unread`，`repairable_fields=
("disposition","message")`）拒绝；读完之后同样的 `limitation` 直接放行——「远端输出里
没有」是模型的判断，「没看就收尾」不是。只对 `succeeded` 的 Observation 生效：失败调用
被卸载的错误文本不是任何人在找的证据。

## Verification and Remaining Risk

| 命令 | 结果 |
| --- | --- |
| `pytest tests/test_observation_bounds.py tests/test_conversation_interaction.py -q` | 47 passed |
| `pytest evals/e2e_quality/test_release_user_outcomes.py -k e21 -q` | passed；重读窗口命中 15 处，返回 `{"line": 29502, "text": "L:\tlinux-xfs@vger.kernel.org"}`，模型答 29502 |
| `python scripts/check_layers.py` | OK，无新增边 |
| `pytest tests/ -q` | 751 passed，1 error（`notion` MCP initialize 超时，环境） |

同一 1,940,197 字符输入上：单次 payload 1,940,197 → 12,138 字符；提交 tokens
776,720 → 26,424。

剩余风险：before=2 / after=4 是按 `MAINTAINERS` 的条目形状取的，对上下文更长的格式可能
不够；`MAX_EXCERPT_LINES` 之内命中窗口整块给或整块不给，命中极密集时靠 `next_start_line`
续读。E21 多次实测存在运行间差异（模型可能选择先答再验），该判据只保证未读完不能以非
answer 收尾，不保证模型必然重读。
