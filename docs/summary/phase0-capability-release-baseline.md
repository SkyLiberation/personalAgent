# Phase 0 能力目录与发布基线

本文记录 Phase 0 落地后的当前事实。目标能力语义仍由
[`adaptive-agent-runtime-design.md`](../future/adaptive-agent-runtime-design.md) 定义；
机器可执行的 E/C 映射由
[`release_gate.py`](../../evals/e2e_quality/release_gate.py) 唯一拥有。

## 当前结论

截至 2026-07-23，当前工作树的可信原生产品能力基线为空，可信组合强能力基线也为空。
这不是说仓库没有实现，而是说当前还没有新产品语义下的 E01–E13/C01–C04 release
catalog 条目和同 revision 通过 trace；工作树本身也处于 dirty revision。

因此 Conversation、Capture、Grounded Ask、Knowledge Lifecycle、Review、Knowledge
Maintenance、Research、Scheduled Intelligence 目前均为 `unverified`/capability
acceptance。Personal Research Analyst、Continuous Knowledge Steward、Personalized
Learning Agent、Expert Collaboration Agent 同样不得作为发布能力声明。

旧 catalog 中的 E01–E15 证明的是 Task/Plan/Governance/Recovery 等架构边界，E16/E17
是 MCP/A2A Profile 证据。它们已经通过 `EvidenceClaimKind` 与产品能力证据分开，不能
因为编号相同或对象可连接而授信原生产品能力。

## 事实与所有权

| 事实 | Canonical owner / 唯一写入口 | Phase 0 处理 |
| --- | --- | --- |
| 本地 Tool 定义 | `AgentRuntime._register_tools` → `ToolExecutor.register` | 从实际 registry 派生，不维护第二份 Tool 表 |
| MCP 远端名称/schema | MCP `tools/list` discovery | 只报告 discovery 事实 |
| MCP 本地名称、风险、权限、出域 | `MCPConfig` / Host policy | 与远端声明分开 |
| A2A 当前 profile | `AgentGateway.register` 后的 `SubagentProfile` | 当前 GPT Researcher 为本地 adapter profile，不冒充 Agent Card discovery |
| 配置是否启用 | `Settings` | 与实现存在、provider health 分开 |
| Provider 当前健康 | 实时 credential/health observation | 未观察时固定为 `not_observed` |
| Release eligibility | `evidence_catalog.py` | `claim_kind` 与 `release_eligible` 共同判定 |
| 同 revision 实际通过 | trace `manifest.json`、`summary.json`、trace envelope 和 checksum | dirty、commit 不同、skip、失败、无 trace 或 checksum 错误均 fail closed |
| 发布能力基线 | `release_gate.py` 派生投影 | 不进入数据库、checkpoint 或 Runtime capability state |

`src/personal_agent/capabilities/inventory.py` 只消费上述 canonical sources，返回 typed
`RuntimeCapabilityInventory`。`GET /api/capabilities/inventory` 暴露当前进程事实；它
不会根据配置开启或曾经 discovery 成功推断 provider 仍健康，也不包含 Release trust。

## 当前实现与配置清单

本地 Tool 组装当前包括以下无条件注册组：

- Artifact/Knowledge read：`inspect_artifact`、`graph_search`、`list_recent_notes`、
  `get_note`、`find_similar_notes`；
- Capture/Lifecycle：`capture_text`、`delete_note`、`restore_note`、`update_note`、
  `supersede_note`、`mark_note_deprecated`、`mark_notes_conflicted`；
- Maintenance/Review：`consolidate_knowledge`、`review_digest`、
  `inspect_knowledge_gaps`；
- Scheduled Research 管理：subscription list/update/pause/resume/run-now、run list、
  digest read、feedback、save event；
- Operations：worker queue inspect/retry、workflow run inspect；
- Enterprise：已配置 raw wiki roots 时生成对应只读 Tool，并注册统一
  `enterprise_knowledge_search`。

`capture_url`、`capture_upload` 只有注入 `CaptureService` 时注册；`web_search` 只有 API
key 存在时注册；MCP Tool 只有 Host 启用 server、mapping 存在且真实 discovery 成功时
注册。具体进程的权威列表必须读取 inventory API，不能从本段反推。

本次 `Settings.from_env()` 快照：

| 扩展 | 实现 | 配置 | discovery / provider |
| --- | --- | --- | --- |
| Web Search | 有 adapter | API key 已配置 | health 未观察 |
| Raw Wiki | 有 adapter | `D:\mySoft\workspace\personalWiki\raw` 存在 | 本地文件源，运行调用结果未观察 |
| MCP | 有通用 adapter | `enabled=false`，0 server | 未 discovery |
| GPT Researcher A2A | 有 adapter | `enabled=false` | 未注册 profile，provider 未观察 |

## Release Gate

机器声明目录绑定：

| 原生能力 | 最低证据 | 当前 |
| --- | --- | --- |
| Conversation | E01 | `unverified` |
| Capture | E08、E09 | `unverified` |
| Grounded Ask | E02、E03、E08 | `unverified` |
| Knowledge Lifecycle | E04、E10 | `unverified` |
| Review | E11 | `unverified` |
| Knowledge Maintenance | E12 | `unverified` |
| Research | E05 | `unverified` |
| Scheduled Intelligence | E13 | `unverified` |

C01–C04 分别绑定四项组合声明，并额外要求其依赖的全部原生能力先可信。基础 E 系列全部
通过也不能替代任一 C 系列。

门禁只接受同时满足以下条件的交集：

1. catalog 条目具有正确 `claim_kind` 且 `release_eligible=true`；
2. 不含 test double，走真实 HTTP 进程和场景要求的真实依赖；
3. manifest commit 等于目标 revision，manifest 与目标工作树均为 clean；
4. summary `exit_status=0`，具体 test outcome 为 `passed`，不是 skip；
5. 对应用例至少有一个 passed trace envelope；
6. archive run identity 一致且全部 JSON checksum 有效。

执行：

```powershell
uv run python -m evals.e2e_quality.release_gate --trace-root data/e2e_traces
```

当任一原生或组合声明不可信时命令返回非零。完整产品 E2E 尚未加入 catalog 前，
`--e2e-require-complete-matrix` 也会在 pytest 收集阶段列出缺少的 E01–E13，而不是运行
旧架构用例后误报完整。

## 决策所有权

Inventory 是确定性 Runtime Projection：唯一性来自已注册 Tool、accepted MCP config、
registered Agent profiles 和 application assembly facts。它不新增 semantic intent。

Release gate 是确定性 Admission：唯一性来自目标 revision、catalog metadata、archive
checksum、manifest identity 和 test outcome。它只接受或拒绝发布声明；缺证据时返回
typed reason，不补 catalog、不重写 trace、不使用 Runtime availability 兜底。

