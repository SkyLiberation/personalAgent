# MCP 客户端与 Toolathlon 评测接入 Spec

> 状态：连接生命周期、显式映射及 Time 评测运行器已实现。文件 Server 的工作区边界已执行真实探测。验收进度与证据边界见[实施状态](#8-实施顺序迁移与状态)。现行契约见[工具专题](../topics/tools.md)和[MCP 配置](../env.md#mcp-工具接入)。

## 1. 目标、范围与依据

用现有的生产工具链接入 Toolathlon 的 MCP Server，并允许后续独立增加 Server 和评测套件。新增同协议 Server 主要改部署配置和工具映射。新增评测主要改该套件的环境、输入和评分。外部工具仍经过现有对话入口、能力投影、准入、执行、核验与完成链路。产品应用层通过既有工具 Port 消费能力。

| 已确认的事实 | 对设计的影响 |
| --- | --- |
| `build_mcp_tools()` 同时创建客户端、发现工具和构造工具。客户端由工具闭包持有，现行 Web 关闭入口未调用 MCP 客户端的 `close()`。 | 将连接资源交给组合根管理，处理装配失败与正常退出。[工具工厂](../../src/personal_agent/tools/mcp.py) · [Web 关闭入口](../../src/personal_agent/adapters/web/context.py) |
| 当前 stdio 客户端启动子进程时复制宿主环境。历史受控探针的 9 个已执行样本都把授权目录外的标记带入模型可见 Observation。 | 工具权限和进程权限分别验收。该探针结果用于定位边界风险，真实 Server 的隔离效果由新运行确认。[客户端](../../src/personal_agent/infra/mcp.py) · [历史用例盘点](../evals/02-current-case-inventory.md) |
| 现有评测通过子进程配置注入测试 MCP。通用 Web 启动辅助以宿主环境的副本为起点。 | 复用启动和 HTTP 交互，Toolathlon 的环境由套件从显式输入生成。[启动辅助](https://github.com/SkyLiberation/personalAgent/blob/b2c34d90e5476a78282b9884e8edc947509525af/evals/e2e_quality/test_release_user_outcomes.py) · [治理评测](https://github.com/SkyLiberation/personalAgent/blob/b2c34d90e5476a78282b9884e8edc947509525af/evals/e2e_quality/test_governance_and_budget.py) |
| 关闭外部 MCP 后，Conversation 仍会投影本地工具、自有知识与 Artifact 动作，以及已装配的子智能体。现有回答测试模式只移除澄清动作并调整提示词。 | 区分环境隔离与同工具条件对照。仅当后者成为正式目标时，扩展通用能力限制。[能力投影](../../src/personal_agent/application/conversation/service.py) · [回答测试模式](../topics/runtime.md#回答测试模式) |

首个切片选择 Toolathlon 已配置的独立 stdio Time Server，验证接线与隔离。后续用 `arrange-workspace` 推演文件写入任务。该用例来自公开基准，其在本工程中的接入身份和产品发布资格分别判定。当前待验证的前提包括固定版本的 Server 在目标环境可启动、现行治理能合法承接样本写入、评测过程可以读取完整真实结果。

## 2. 需求与行为规格

| 编号 | 触发条件 | 必须产生的结果 | 验收 |
| --- | --- | --- | --- |
| MCP-01 | 部署启用一个已支持协议的 Server，声明若干工具 | 正式入口只获得显式映射且通过现行权限检查的能力。必需工具缺失、配置冲突或发现失败时，装配返回明确错误。 | V1、V2 |
| MCP-02 | 部分启动失败、已连接 Server 退出，或 Web、CLI、worker 正常退出 | 组合根关闭会话并回收本应用启动的子进程。连接丢失时报告不可用，显式重新装配从新会话握手开始。 | V2 |
| MCP-03 | 运行 Toolathlon 或现有夹具套件 | 每次运行只装配该用例声明的外部连接和工具映射。模型、工具进程和评分器各自取得最小所需权限。样本之间的数据和副作用隔离。 | V3 |
| MCP-04 | 从正式入口执行含外部写入的基准任务 | 模型自主选择已准入动作，产品完成正常核验与交付。评测器独立读外部终态。拒绝调用无对应副作用，未知写入结果有明确归因。 | V4 |
| MCP-05 | 正式要求按同工具条件比较不同智能体 | 用例显式声明可比较的业务工具和辅助能力。实际模型曝光与调用准入消费同一份部署限制。差异可追溯，结果按配置分组。 | V5，条件项 |
| MCP-06 | 选定用例依赖 Toolathlon 聚合网关 | 在正式评测前通过所选传输完成握手、发现、调用、错误归因和关闭。 | V6，条件项 |

## 3. 架构分析

### 3.1 责任与依赖

| 责任主体 | 拥有的事实或决定 | 直接消费者 |
| --- | --- | --- |
| MCP Server | 远端工具名、远端 Schema、调用返回和外部系统状态 | `infra/mcp.py`，以及按独立权限读取终态的评测器 |
| 部署配置 | 稳定的 `server_id`、连接位置、凭据引用、运行隔离和显式工具映射。映射负责本地名、权限范围、副作用及结果契约。 | `AgentService` 装配和能力盘点 |
| 组合根 | 每个启用 Server 的客户端、连接生命周期和已装配工具 | `AgentRuntime`、Web、CLI 和 worker 的退出入口 |
| Conversation 与治理层 | 业务动作可见性、当前身份和资源范围下的准入、执行审计、用户结果核验 | 模型、执行网关和用户交付 |
| 评测套件 | 上游任务版本、初始环境、用例输入、工具配置、评分及证据身份 | 评测运行器、评分器和既有证据归档 |

`orchestration` 依赖 `infra` 和 `tools`。Application 沿现有 [`InteractionToolPort`](../../src/personal_agent/application/conversation/ports.py) 调用治理能力。评测通过 HTTP 驱动产品。Toolathlon 的 YAML、SDK、任务包和评分器都留在产品包外。保持 [`check_layers.py`](../../scripts/check_layers.py) 的现行允许边。连接和能力盘点是运行时状态，评测通过既有归档保存可复查证据。

### 3.2 参考机制与取舍

| 源码依据 | 本工程采用 |
| --- | --- |
| Gemini CLI 固定提交 `3c311be`。宿主初始化时创建 Manager，Manager 创建并连接各 Server 客户端。发现经筛选后进入工具注册表。退出时宿主调用 `stop()`，由 Manager 逐个关闭。 | 采用宿主显式持有连接和按配置绑定工具的做法。借用 Python 的资源栈表达所有权，现有注册表、Policy 和运行机制继续承担治理。[装配](https://github.com/google-gemini/gemini-cli/blob/3c311beac2e78336816dd4a123db39743f9fbf85/packages/core/src/config/config.ts#L1441) · [连接与发现](https://github.com/google-gemini/gemini-cli/blob/3c311beac2e78336816dd4a123db39743f9fbf85/packages/core/src/tools/mcp-client-manager.ts#L435) · [筛选](https://github.com/google-gemini/gemini-cli/blob/3c311beac2e78336816dd4a123db39743f9fbf85/packages/core/src/tools/mcp-client.ts#L1208) · [退出](https://github.com/google-gemini/gemini-cli/blob/3c311beac2e78336816dd4a123db39743f9fbf85/packages/core/src/config/config.ts#L3957) |
| Toolathlon 固定提交 `9be8d8f`。拆分模式在容器内准备环境、启动任务网关，宿主执行模型循环，容器读取结果评分。网关按任务选择 Server，并会附加 `claim_done`。 | 采用任务环境与智能体执行的进程边界。评测适配层把宿主执行接到 personalAgent 的正式 HTTP 入口，按显式工具映射选择远端能力，产品以自身的交付契约收尾。[拆分运行脚本](https://github.com/hkust-nlp/Toolathlon/blob/9be8d8fe07a497b18ee61e3f2ae694e9797f39eb/scripts/run_single_decoupled.sh#L815) · [网关装配](https://github.com/hkust-nlp/Toolathlon/blob/9be8d8fe07a497b18ee61e3f2ae694e9797f39eb/scripts/decoupled/container_tool_gateway.py#L287) |

比较三种落点。只改部署配置足以先验证一个已支持协议的 Server，成本最低，但产品进程主动关闭连接的责任仍未闭合。把 Toolathlon 自己的客户端和循环嵌入产品会带来第二套工具执行和完成语义。候选方案在完成接线诊断后，将生命周期装配和工具映射分开。等具体任务证明需要某种新传输，再增加对应实现。服务器数量本身不足以证明热更新、连接池或插件框架的收益。

## 4. 目录与改动边界

```text
src/personal_agent/
  application/conversation/
    workspace_changes.py        冻结清单、保存决定与回执
  governance/                   评估部署规则、复核派发与审计
  infra/mcp.py                  调整协议客户端和会话关闭
  tools/mcp.py                  保留单工具映射与结果转换
  orchestration/
    mcp_bindings.py             新增按配置连接、发现和绑定的装配入口
    workspace_changes.py       绑定工作区专用写入端口
    service.py                  持有并关闭 MCP 连接资源
    runtime.py                  消费已绑定的工具并注册
  adapters/
    web/context.py              服务退出时关闭资源
    cli/main.py                 CLI 和 worker 退出时关闭资源
  kernel/config_models.py       复用 MCPConfig、MCPServerConfig、MCPToolConfig

deploy/mcp/                     有实际生产部署时存放对应配置
evals/
  Toolathlon/
    runner.py                   独立环境、Time 接线与生命周期
    workspace_case.py           工作区用户确认、文件样本与上游评分
toolServer/Toolathlon/           独立上游 checkout 或评测容器来源
```

| 后续变化 | 修改入口 |
| --- | --- |
| 同协议新增 Server | 对应部署或用例的连接配置与映射 |
| Server 新增写工具 | 对应工具映射、授权及副作用契约，增加有实际意义的结果和拒绝判据 |
| 新增传输 | `infra/mcp.py` 与连接配置类型，按实际复杂度决定是否拆文件 |
| 上游任务包或评分格式变化 | `evals/Toolathlon/` |
| 新评测套件 | `evals/<suite>/`。已有两个实际消费者时可抽取共用进程与 HTTP 辅助，保留各自环境构造和评分 |

生产部署沿用 `PERSONAL_AGENT_MCP_SERVERS` 解析入口。若使用独立部署文件，由启动侧读入并传给该入口。评测生成的配置属于本次运行，生产默认装配从自己的部署输入构造。上游 checkout 以提交固定，第三方 Python 或 Node 依赖和镜像留在独立评测环境。生产镜像只装配生产源码与依赖，构建上下文排除上游 checkout。

## 5. 装配、权限与失败契约

### 5.1 装配与关闭

1. `AgentService` 解析唯一的 `MCPConfig`，创建资源栈并调用 `bind_mcp_tools`。先检查启用配置中的 Server 标识和映射键。只连接具有有效映射的启用 Server，连接资源一经取得即登记关闭。
2. 客户端握手并发现远端工具。`build_mcp_tool()` 消费客户端、远端定义与本地映射，产生现有治理工具及其能力元数据。`AgentRuntime` 注册前校验本地名称与已有工具及本批次无冲突。整套 Runtime 装配成功后对外接收请求，发现或装配失败则关闭已取得的连接。首个切片把显式启用的 Server 都视为必需。
3. Web lifespan、CLI 命令和 worker 共享 `AgentService.close()`。先停止消费或等待在途运行收尾，再关闭客户端。Web 若在服务创建后、lifespan 接管前装配失败，创建方也负责关闭。实现时沿全部 `AgentService` 构造点迁移显式持有资源的调用方，含运维脚本和评测辅助。
4. 连接以实际配置、凭据和隔离环境为界。首个切片在一个产品实例内，每个 Server 使用一个连接。握手完整成功后才标记就绪。发现进程退出或会话失效后，当前客户端报告不可用，显式重启产品实例时以新客户端重新握手。当前 stdio 实现会补起进程而沿用初始化状态和队列，迁移时移除该隐式重启行为。关闭需等待子进程退出，评测容器和账号由 Runner 回收。V2 同时检查客户端进程与实际 Server 的退出。

### 5.2 从发现到用户交付

```text
任务配置 → MCPConfig → 远端发现 + 本地映射 → ToolExecutor
用户请求 → Conversation → EffectiveCapabilities → 实际模型动作声明
模型提议 → Admission → ToolGateway → MCP 工具 → Observation
模型提交 FinalMessage → 适用的 Verification → Completion → 用户结果
评测器 → 独立读取最终答复和任务工作区 → 评分
```

远端工具名和 Schema 属于发现事实。映射以 `server_id` 与 `remote_name` 绑定能力，并声明本地名称、权限范围、风险、副作用和结果契约。临时端口、进程 ID 与会话 ID 只标识运行实例。MCP 注解是服务提供方声明，宿主按本地治理配置决定权限。返回值在映射层校验并经现有 Observation 流程交回。具体 ToolCall 的授权、确认、Command 和 Receipt 由现有链按适用条件产生。[MCP Tools 规范](https://modelcontextprotocol.io/specification/2025-11-25/server/tools) · [受治理执行细则](../devSpec/agentic-execution.md)

本地映射可用 `model_integer_string_fields` 指定哪些已发现的顶层整数字段允许按标准十进制写法读取模型字符串。这个约定随可见能力封存到当次模型动作定义，由对话动作解码消费。模型 Schema、直接工具入口和远端工具参数仍沿各自的原有契约。首个采用点、输入边界和验收见[显式允许的整数表示](../context/runtime-feedback.md#显式允许的整数表示)。

区分启动或握手错误、配置或 Schema 不匹配、准入拒绝、远端工具错误，以及执行结果未知。环境配置错误由 Runner 归为环境失败。工具错误进入现有反馈链。写调用超时或断线时，在能够从权威终态确认结果之前按未知处理。连接恢复可以重新握手。重发写操作必须满足该工具的幂等或状态核对契约，产品执行仍使用原授权与执行事实。

#### 5.2.1 工具策略决定与派发门禁

V4 的真实反例中，Policy 已返回 `require_confirmation`，网关仍派发了 `move_file`。网关还把业务参数 `confirmed` 传入 Policy，调用方可以用同一个字段跳过规则。修复恢复通用派发边界。`PolicyEngine` 负责规则、优先级和风险判断，`ToolGateway` 通过 `PolicyEvaluator` 消费决定并记录审计，只有 `allow` 可进入域名、限流和执行。`deny`、`require_confirmation` 和 `require_escalation` 统一返回权限失败，工具派发次数为零。业务 payload 中的 `confirmed` 不能提供授权证据，审计中的确认状态也不由该参数推导。

工具和子 Agent 复用同一高风险确认判据及决定流程，保留各自现有规则 ID、反馈和生效范围。网关删除依赖通用工具自行预览的隐式放行，以及依赖参数自报确认的 grant 检查和无消费者的旧确认引用字段。旧通用幂等写入由同一自报确认字段触发，随该授权路径删除。历史查询继续读取原审计和账本，已确认业务动作的幂等仍由具体 Application 持有。原有授权范围、域名、限流、超时和重试继续由网关处理。普通 ToolCall 入口当前没有通用待确认 Command 的合法写入和恢复消费者，对需确认的工具明确返回不可派发。文件整理的正向可写流程需要业务确认入口后再验收。[责任边界 ADR](../adr/0052-tool-policy-dispatch-gate.md)

验收复用真实 Filesystem Server 和正式工具 HTTP 入口。只读挂载上提交原始移动、附带 `confirmed=true` 的同一移动、部署规则拒绝的建目录及正常列目录，各执行一次。记录 MCP stdio 实收请求、策略日志和文件终态。前两项应得到 `require_confirmation`，第三项应为部署拒绝，三项都应为零远端调用。正常列目录应返回原文件，所有文件摘要保持不变。基线同一正式入口实测原始移动到达 Server，附带确认字段的调用获 Policy 放行后被适配器拒绝。目标失败则保留封存并停止开放正向写入。该检查不调用模型。知识确认使用独立业务入口核对原 Command 与 Receipt，整套 Toolathlon 评分保持独立。

#### 5.2.2 身份、入口与能力可见性

入口从已认证的调用者和自身渠道构造策略输入。Web 对话、直接工具 API、CLI 和飞书执行入口消费 `entry_access`。配置的允许名单仅约束入口，显式拒绝优先。业务参数与渠道元数据分开传递。拒绝发生在模型调用及工具派发之前，Web 返回 403。入口白名单不应用于宿主内部工作流。

策略主体采用 `AuthenticatedPrincipal`，部署规则和策略审计使用 `tenant_id:user_id`。历史记忆存储仍以个人租户的裸用户键索引，在记忆边界转换为该租户的主体，资源归属与策略主体分别构造。外部数据和工具参数不能提供另一个策略主体。

在普通对话生成模型动作声明前，已注册工具与子 Agent 按相同主体、渠道和权限域检查部署拒绝规则。派发时以实际调用上下文再次判定。应用自有动作由各自的 Capability 及授权契约管理。投影保留可能获准的动作，不为投影写执行审计。[固定版本静态排除实现](https://github.com/google-gemini/gemini-cli/blob/3c311beac2e78336816dd4a123db39743f9fbf85/packages/core/src/policy/policy-engine.ts#L892)

在隔离 Time Server 和正式 Web 入口验证。用真实模型发送「请把纽约上午九点换算成东京时间」，归档实际请求的 `action_definitions`。基线配置拒绝 `time.convert_time` 时该能力仍出现在模型请求，目标应移除该能力而保留未拒绝的同源能力。显式直调被拒绝的工具应零远端调用。配置信任的主体与来源时，另一租户同名用户和伪造来源应在入口获 403，允许的主体保留读取能力。核对入口审计和真实远端调用。

主体键以第一个冒号分隔租户和用户。租户 ID 禁用冒号，用户 ID 保留原值。非法租户的认证配置在启动时拒绝，直接工具 HTTP 请求中的非法租户返回 422。启用主体名单时，CLI 使用部署默认主体，用户选项不能切换身份。飞书使用事件发送者身份并拒绝无发送者的事件。保留无主体名单时的渠道默认用户行为。合并前用原碰撞配置、合法主体对照、CLI 自报身份和飞书事件适配回放验证。

#### 5.2.3 工作区变更确认与接续

工作区变更由 Conversation 的文件工作区用例拥有。部署显式绑定认证主体、对话、单写者 POSIX 工作区和两种底层能力。模型一次提交有序的建目录与移动清单，用户在认证 Web 入口批准这一份冻结清单。每项派发前先持久化状态，独立保存终态。失败后停止后续执行，回执标明已执行范围。未决派发恢复为结果未知，同一绑定下冻结后续写入。完成后的回执以原模型调用的 Observation 继续原对话。底层写映射从普通 Registry 移出，由专用执行端口消费，使用同一网关与策略引擎重新判定。服务端的路径解析和目标存在检查依赖隔离、无符号链接、单写者工作区。

单文件目标使用「请把 /case/inbox/记录.txt 移到 /case/归档/记录.txt，完成后告诉我存放位置」。基线正式入口返回文字澄清，无可批准命令。目标比较源目标摘要和实际 MCP 请求，检查批准前、拒绝、跨用户、篡改、重放均无新增派发。该场景通过后才进入原始 22 文件 V4。V4 使用原始档案与独立评分器，记录确认次数、实际模型预算和最终用户交付。单文件通过只验收确认纵向切片。[工作区授权 ADR](../adr/0053-workspace-change-approval.md)

`PERSONAL_AGENT_WORKSPACE_CHANGES` 接收一个配置对象，字段为 `principal`、`conversation_id`、`workspace_ref`、`root`、`server_id`、`create_directory_tool` 和 `move_tool`。主体须已有 Web 认证密钥。两项写映射来自同一 stdio Filesystem Server，声明强制确认且禁用重试。用户拒绝、策略阻止和结果未知均以原回执结束本轮，明确保留已执行范围。已持久化的成功项在重启恢复时跳过。只有下一项从未进入派发才可继续。一次 80,000 tokens 单文件样本已执行并取得回执，后续模型核验耗尽预算。可复现用例预设 220,000 tokens，只影响本次独立评测环境。原样本路径和原始上游评分契约保持独立，中文请求将两条混用 ASCII 线条的 Work 子目录用统一树形线条表达。

部署须为实际工作区分配不可重用的 `workspace_ref`，并固定 stdio 命令的执行目标。替换 Server 实例或挂载目标时须变更绑定配置。可重新指向其他工作区的容器名或进程别名不满足此部署前提。Toolathlon 使用本次容器 ID 固定目标。

真实续跑显示，核验单独引用 `applied` 或单条路径时，无法还原完整执行事实。交互投影为每个操作生成单行证据，合并状态与该操作的完整路径。来源仍为冻结命令和已存回执。验收同时在续跑后重复提交原决定，要求拿到同一回执。

重复决定绑定原命令。用户拒绝后可在同一会话的新运行中重新请求相同清单并获得新确认。原拒绝回执保持不变。同一运行仍拒绝重复提交，未决或结果未知仍冻结部署绑定内的后续写入。复验检查新运行和新摘要，二次批准前远端写入为零。

#### 5.2.4 沿用上游输入 Schema

Toolathlon 的 `fetch.fetch_json` 曾在第二轮传入上游允许的 `Accept` 对象，仍被本地严格化封闭的请求头 Schema 拒绝。`filesystem.read_file` 也曾因省略上游允许缺省的 `tail` 被拒绝。[原始用例与轨迹](../problems/toolathlon-verified.md#预检受阻的-14-个用例重跑)

LangChain MCP 适配器把发现结果的 `inputSchema` 直接交给工具，并把调用参数送给 MCP 会话。MCP Server 声明输入约束并验证收到的调用。personalAgent 的 MCP 装配同样采用发现的 Schema。模型工具定义、动作解码、准入预检查和派发前校验消费这份契约。服务方工具声明使用 `strict: false`，保留上游的字段可选性和开放对象。权限、域名和确认仍由现有 ToolGateway 执行。[LangChain 装配与调用](https://github.com/langchain-ai/langchain-mcp-adapters/blob/52a4535f3eb4b98f386836e4d9b8c4cadf99afca/langchain_mcp_adapters/tools.py#L419-L485) · [MCP 工具规范](https://modelcontextprotocol.io/specification/2025-11-25/server/tools) · [OpenAI 工具严格模式](https://developers.openai.com/api/docs/guides/function-calling#strict-mode)

`fetch` 的 `headers` 可以省略，传入时按上游要求为对象，自定义键由上游的对象规则决定。`filesystem.read_file` 的 `head`、`tail` 可分别省略，未知字段和类型错误按上游 Schema 拒绝。运行时参数 Schema 重建和本地请求头名单从装配路径移除。适用的旧映射移除 `allowed_request_headers` 和 `use_upstream_input_schema`。

验收回放 `git-milestone` 的真实数组和对象两轮、`identify-all-songs` 的语言头以及 `profile-update-online` 省略 `tail` 的调用。合法原参数和自定义请求头应原样派发，非法类型及上游明确禁止的未知字段应在派发前被拒。通过正式入口与实际 MCP Server 检查 HTTP 实收请求头及文件读取范围。本轮证据限定到参数与派发链路，完整任务评分独立。

已核对上轮归档发现的 134 份不同工具 Schema。原始数组在回放中被拒，合法请求头对象及省略 `tail` 的参数通过。正式入口经真实 MCP Server 发送自定义头 `X-Example` 并成功读取指定首行。MiniMax 发出的自定义头也由目标 HTTP 服务回显。对话后续答复核验未通过，归档未形成最终答复。[轨迹回放](../../.tmp/mcp-upstream-contract-1111/replay.json) · [正式入口与模型验证](../../.tmp/mcp-upstream-contract-1111/verification.json)

### 5.3 选择 Toolathlon 传输

先按 Toolathlon 的 Time 配置，以其锁定的 `mcp-server-time==0.6.2` 为首个候选，在隔离环境启动独立 stdio Server，并核对 `convert_time` 的发现和调用结果。由启动侧解析工作目录和变量。[Time 配置](https://github.com/hkust-nlp/Toolathlon/blob/9be8d8fe07a497b18ee61e3f2ae694e9797f39eb/configs/mcp_servers/time.yaml) · [依赖版本](https://github.com/hkust-nlp/Toolathlon/blob/9be8d8fe07a497b18ee61e3f2ae694e9797f39eb/pyproject.toml#L82)

仅在用例确需复用聚合网关时处理旧式 HTTP+SSE。该网关通过 `GET /sse` 给出 `/messages` 地址，调用结果通过原 SSE 会话返回。现有 `http` 实现对单一地址发 POST 并读取响应体。候选是在通用协议层引入经验证的旧式 SSE 支持，或在评测环境提供兼容端点。先用现有客户端确认首个不兼容的协议边界，再用 V6 验收选定的适配。[网关路由](https://github.com/hkust-nlp/Toolathlon/blob/9be8d8fe07a497b18ee61e3f2ae694e9797f39eb/scripts/decoupled/container_tool_gateway.py#L344) · [MCP 传输规范](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports)

网关现有远端调用配置了一次异常重试。写入用例若走该网关，先验证下游幂等、权威状态核对或评测部署能关闭该重试。文件移动回包丢失时，重新读取源与目标状态供后续判断，自动重发之前需要上述依据。[网关调用实现](https://github.com/hkust-nlp/Toolathlon/blob/9be8d8fe07a497b18ee61e3f2ae694e9797f39eb/scripts/decoupled/container_tool_gateway.py#L319)

#### 5.3.1 聚合网关接入验证

`find-alita-paper` 的上游网关已连接三个真实 Server。现行 MCP HTTP 客户端向 `/sse` 发送初始化 POST 得到 405，向 `/mcp` 发送同一请求得到 404。先在独立评测归档中验证 stdio 到旧式 SSE 的协议转接。转接仅交付请求和响应，既有 ToolGateway 继续拥有准入、审计与执行结果。上游任务环境拥有文件事实，独立上游评分器拥有结果判据。

首个样本固定上游题面、模型环境和评分源码。仅映射任务所需的已核实读工具以及写入隔离工作区的工具，沿正式 Web 对话入口运行一次。先确认能力发现和零副作用的列目录调用，再启动模型。记录实际文件、最终答复与上游评分。该样本在原任务范围内验证传输和接入，可用工具及外部服务通过预检后才安排后续批次。

本地文件任务预检复用上游预处理和聚合网关。每个任务独立创建容器，只挂载题面、任务配置、预处理、输入夹具和运行依赖。评分程序和参考工作区由另一个进程消费，工具容器无宿主 Docker 套接字。进入正式对话前核对已连接 Server 与任务声明一致，以及工具的实际输入和副作用。未通过预检的任务记录具体依赖并保持未执行。

已通过评测转接验证列目录、检索、下载和移动文件。后续样本的网关启动、用户答复和上游评分分别见[扩展评测问题记录](../problems/toolathlon-verified.md)。

#### 5.3.2 校园步行路线使用 SerpApi

`upenn-campus-route` 的评分器通过 `google_map` 查六个校园地点之间的步行路线。Google Cloud 项目尚未开通结算。SerpApi 已对评分器中的书店到博物馆返回步行路线，距离 692 米、耗时 568 秒。[上游评分器](https://github.com/hkust-nlp/Toolathlon/blob/9be8d8fe07a497b18ee61e3f2ae694e9797f39eb/tasks/finalpool/upenn-campus-route/evaluation/main.py) · [SerpApi 路线契约](https://serpapi.com/google-maps-directions-api)

首轮接入该用例依赖的 `maps_directions`。评测侧复用上游的工具名、参数和路线结果结构，在独立容器内使用任务镜像已带的 MCP SDK 提供 SSE 服务。SerpApi 提供路线数据，适配器将距离、耗时和导航步骤转换为现有工具结果，评分器仍使用原有条件计算路线。网关和评分器在本次评测网络内使用同一份 `google_map` 配置覆盖，密钥只注入路线服务容器。没有指定出行方式时沿用上游默认驾车。服务请求失败、无匹配路线或缺少评分所需数据时返回工具错误。[上游路线工具](https://github.com/modelcontextprotocol/servers-archived/blob/main/src/google-maps/index.ts)

验收固定为 `upenn-campus-route` 的书店到博物馆真实输入。先检查网关发现 `maps_directions` 且正式工具入口可以派发，再用原评分器的取步行时间函数读取相同路线。两端均须取得上游提供的距离和耗时。未定义的出行方式在派发前返回参数错误。若运行整例，固定上游题面、评分器与现有对话预算，保留模型生成的路线文件和评分。评分器构建矩阵最多发出 30 次有向路线查询。供应商变化随报告记录，结果属于 SerpApi 条件下的定向评测。

2026-11-12 的定向运行中，正式工具入口与原评分器均取得 568 秒的步行耗时，非法出行方式被拒绝。真实对话生成五段路线的 JSON 文件，上游评分器通过 SerpApi 完成 30 次路线查询并通过文件评分。对话请求在 600 秒时超时，未取得最终答复，整例未通过。[路线预检](../../.tmp/ta-serpapi-1112/run-ef9790/upenn-campus-route/maps-preflight.json) · [运行报告](../../.tmp/ta-serpapi-1112/run-ef9790/upenn-campus-route/report.json)

#### 5.3.3 SerpApi 地点与距离矩阵

`trip-itinerary-generator` 的上游评分器按巴黎景点名称调用 `maps_search_places`，通过结果中的 `place_id` 调用 `maps_place_details`，并对行程中的相邻景点调用 `maps_distance_matrix`。真实 SerpApi 查询确认埃菲尔铁塔以单个地点结果返回，包含 Google Place ID，详情按星期给出营业时间。东京车站的星巴克查询返回多个地点，新加坡公交与洛杉矶驾车样本返回路线。[巴黎评分入口](https://github.com/hkust-nlp/Toolathlon/blob/9be8d8fe07a497b18ee61e3f2ae694e9797f39eb/tasks/finalpool/trip-itinerary-generator/evaluation/maps_api.py) · [SerpApi 地点契约](https://serpapi.com/maps-place-results)

沿用评测专用的 `google_map` 服务和凭据边界。地点搜索保留供方顺序并读取单地点或列表结果。列表中的营业状态是摘要，评分所需的营业时间从详情读取，按周一到周日输出。距离矩阵对每个有向起终点查询已接入的路线 API，按原顺序输出距离米数和耗时秒数。明确的无路线记为对应元素失败。服务拒绝或响应契约错误作为工具错误。单次矩阵最多 100 对，遵循旧 Google 距离矩阵 Web 服务的请求上限。新加坡用例要求列出沿途站点，路线步骤在供方返回上下车站时按顺序附带站名。[Google 距离矩阵限制](https://developers.google.com/maps/documentation/distance-matrix/usage-and-billing) · [SerpApi 路线契约](https://serpapi.com/google-maps-directions-api)

使用巴黎原评分器的地点和距离函数验收已核实景点的地点 ID、周一与周二营业时间，以及相邻景点的步行距离。用真实的东京、新加坡和洛杉矶查询检查地点搜索、公交和驾车输入。东京上游评分器中的模拟地图结果仍按上游版本解释。此阶段验收地图依赖，整例评分及 Notion、邮件等其他服务按各用例实际运行状态记录。

2026-11-12 的容器预检发现四项工具。巴黎原评分器读取七个景点的营业时间及埃菲尔铁塔到卢浮宫的步行距离。四个矩阵元素与逐对路线的距离和耗时一致，超过上限的请求被拒绝。东京地点搜索、新加坡沿途站点、洛杉矶驾车和宾大步行回归均通过。一次复验中原评分器收到无法按 JSON 读取的地点详情，同一适配器版本再次执行通过。[最终预检报告](../../.tmp/ta-serpapi-tools-1112/run-16b2fd/report.json) · [失败记录](../../.tmp/ta-serpapi-tools-1112/run-ce19c0/probe.stderr)

## 6. 现有测试工具与 Toolathlon 隔离

| 类别 | 装配规则 |
| --- | --- |
| 测试专用 MCP 和探针 | `governance_budget_mcp`、`tool_discovery_scale_mcp`、`local_mcp_filesystem_probe` 等归现有用例。当前工作树已清理这批夹具。历史证据按原身份保留，未来同类夹具由用例配置注入本套件进程。 |
| 运维诊断工具 | 按真实调用者划分。以 `inspect_worker_queue` 为例，其当前声明为 `public_agent`。若要调整到运维入口，先核对真实消费者和授权，以独立改动验收。 |
| 产品工具和已授权子智能体 | 产品工具面评测按固定部署装配。同工具条件对照按任务限制额外的业务能力，两类运行分别记录。 |
| Toolathlon 本地辅助能力 | 从上游任务配置逐项核对与产品的对应关系，完成、计划、核验和历史处理由相应宿主承担。把差异写入比较身份。 |

Runner 为每个样本建立独立的工作区、产品进程、端口、会话和输出目录。数据库及外部应用用专用实例或经核对能隔离读写的命名空间与账号。若外部服务状态只能串行重置，重置成功后才能启动下一样本。Runner 从明确清单生成环境变量。

| 配置项 | 首轮评测值 |
| --- | --- |
| `PYTHON_DOTENV_DISABLED` | `1` |
| `PERSONAL_AGENT_MCP_SERVERS` | 完整替换为当前用例声明的 Server 和工具映射 |
| `PERSONAL_AGENT_GITHUB_MCP_ENABLED`、`PERSONAL_AGENT_NOTION_MCP_ENABLED`、`PERSONAL_AGENT_GPT_RESEARCHER_A2A_ENABLED` | `false` |
| Web 搜索、额外执行部署、渠道与调度器 | 省略可选搜索凭据和额外执行部署配置，显式关闭渠道与调度器 |
| 模型和存储配置 | 使用本次样本实际依赖的配置与凭据 |

首轮 stdio 评测使用隔离容器。Runner 预建保留 stdin、无 TTY 的 Server 容器并记录容器 ID，产品通过 `docker start -ai <container-id>` 连接标准输入输出。容器显式配置环境和挂载，产品的模型与数据库凭据留在产品进程。Time 容器无需任务挂载或网络，文件任务仅挂载当前样本工作区并关闭网络。文件移动的源和目标都受容器权限约束。评分器、标准答案和其他样本目录由 Runner 在容器外持有。产品退出后 Runner 按容器 ID 回收 Server，封存证据后清理工作区。[Docker 启动参数](https://docs.docker.com/reference/cli/docker/container/start/)

### 6.1 同工具条件对照

先实施独立环境、显式 MCP 映射和实际工具面记录。正式要求同工具条件对照时，由组合根注入一份通用部署能力限制，套件持有具体清单。普通用户请求没有选择该部署限制的权力。使用稳定能力身份，对 MCP 以 Server 与远端工具身份映射到 canonical 工具名，对本地工具和子智能体分别声明。

Conversation 在 `EffectiveCapabilities` 投影处将部署限制与既有身份、资源及政策求交集。这个交集同时供能力说明和实际动作声明使用。调用准入消费同一限制，覆盖直接由 Application 提供的业务动作，以及涉及同一受限能力的委派或间接入口。工具结果读取与适用的计划、核验、完成控制按实际职责列入对应关系。面向评测的部署限定测试身份和正式任务入口。若允许其他工具执行 API，实际执行同样检查其适用范围。

启动时检查 `/api/capabilities/inventory` 中的 Server 和注册映射。运行中保存实际模型请求的动作声明，并按阶段与同一限制核对。一个动作当轮还受既有策略和阶段条件影响，因此检查允许集合及当轮应出现的动作。执行审计用于判断拒绝是否早于远端调用。两项结果分别归档。

## 7. 场景推演与验收

### 7.1 文件整理场景

原 Toolathlon 任务镜像中的文件 Server 为 `2025.7.1`。真实探测中，`move_file` 覆盖了已存在的目标，与工具声明不符。先在原任务镜像内以只读挂载替换运行时，验证修复行为。正式评测构建独立的 Filesystem 镜像，固定 Filesystem Server `2.2.0` 及其所需的 Node.js `24.22.2`。构建固定 slim 基础镜像的摘要，并校验 Node.js 官方归档的 SHA-256。Server 负责在写入前拒绝覆盖。评测侧拥有镜像配方和样本工作区，复用现有 stdio 客户端及工作区确认入口。[上游修复](https://github.com/modelcontextprotocol/servers/pull/4630)

独立镜像验证复用原任务镜像的冲突和跨目录探测。一次运行检查两个隔离样本，其中一个带已有目标文件。冲突必须返回目标已存在，源文件与原目标内容均保留。另用一个独立工作区核对 `list_directory`、`create_directory` 和 `move_file` 的入参，以及目标为空时能完成移动。任一检查失败即停止采用该镜像。验证只启动真实文件 Server，无模型调用。通过后将镜像作为 V4 的文件 Server 环境，产品写入授权和完整任务评分分别按以下步骤验证。

Toolathlon 的 `arrange-workspace` 配置包含文件系统、终端、PDF、Excel 和若干宿主辅助动作。其预处理将初始档案展开到工作区，评分器对比最终目录和文件路径集合。首个写入候选以同一份初始档案运行中文改编任务，向用户提供同一目标目录结构。上游文件 Server 配置使用未固定版本的 npm 包。V4 前先选定并锁定实际包版本，核对列举、创建目录和移动文件所需的工具、Schema、覆盖行为及副作用，再固定映射。[上游任务配置](https://github.com/hkust-nlp/Toolathlon/blob/9be8d8fe07a497b18ee61e3f2ae694e9797f39eb/tasks/finalpool/arrange-workspace/task_config.json) · [文件 Server 配置](https://github.com/hkust-nlp/Toolathlon/blob/9be8d8fe07a497b18ee61e3f2ae694e9797f39eb/configs/mcp_servers/filesystem.yaml) · [预处理](https://github.com/hkust-nlp/Toolathlon/blob/9be8d8fe07a497b18ee61e3f2ae694e9797f39eb/tasks/finalpool/arrange-workspace/preprocess/main.py) · [目录评分](https://github.com/hkust-nlp/Toolathlon/blob/9be8d8fe07a497b18ee61e3f2ae694e9797f39eb/tasks/finalpool/arrange-workspace/evaluation/check_local.py)

1. Runner 启动任务环境并放入初始文件。用户经 `POST /api/conversation/turn` 提交“请按下面的目录结构整理我的工作区文件”，附上任务提供的目标结构。
2. 真实模型读目录、判断文件归属并提出变更。Runner 核对冻结清单符合测试用户授权的范围，以用户身份通过正式入口确认。产品逐项执行，模型根据真实回执决定后续动作和交付。Runner 在容器外保留评分器与标准结果。
3. 产品按自身完成契约交付。评分器独立检查目录和文件路径集合。必要隔离反例检查其他工作区和评分资料不可读写。对移除移动映射的控制组，记录未提供移动能力、工具拒绝或零写入的实际证据。模型报告完成与真实终态单独计分。

V4 恢复验证先执行两个独立样本。其一在只读挂载的临时工作区，以 `POST /api/tools/{name}/execute` 请求一个声明需要确认的移动，省略确认字段。若在工具网关拒绝或暂停，远端应无执行。若返回来自文件 Server 的只读错误，则判为网关已派发且确认边界未成立。其二展开上游真实档案，只映射 `list_directory`，以正式对话入口提交原题的中文表达和原始目录目标。核对未映射移动能力、前后文件摘要和上游目录评分。该对照应保持工作区原状。独立记录对话是否明确交代限制、实际模型请求和用量。两组各一次，模型对照使用现行默认预算。出现未授权派发即停止开放可写工作区，保留只读对照证据。 若 Windows 在保存模型响应原件时因输出路径超长失败，只缩短工作树内的归档目录，保留原失败身份，以同一输入、映射、模型和预算进行一次有界复验。

`move_file` 一次只接受一对路径。初始档案的 22 个文件都需要移动，早期直接逐文件调用已超过 Runtime 默认的 12 次工具调用上限。正式确认后的批量派发由工作区服务执行。模型的后续取证和答复仍消费[用例对话预算](../evals/04-running-and-release.md#对话预算)。

### 7.2 验收矩阵

| 用例 | 固定输入与触发 | 通过条件与证据边界 |
| --- | --- | --- |
| V1 只读接线 | 固定 Time Server 版本和模型。先通过既有受治理工具执行 API 确定性调用真实 Server，再用正式对话入口问“上海上午 9 点是东京几点？”。配对组移除 `convert_time` 映射。 | 确定性调用返回东京上午 10 点并有真实远端调用证据。对话按答复内容单独评分，模型未选工具时路径检查点记未到达。对照组映射不可见、直接调用被拒绝且后端零调用。两组答对都不构成接入收益证据。 |
| V2 装配与退出 | 用真实 Server 分别验证第二个必需 Server 装配失败、已连接 Server 中途退出、产品正常退出。中途退出后显式重启产品。 | 配置异常阻止接收任务，已取得资源回收。中途退出报告不可用并停止在旧客户端上派发，显式重启完成新握手。正常退出后客户端与实际 Server 都已回收。保持行为的改动对照既有 Server 映射、实际工具声明和调用结果。 |
| V3 运行隔离 | 在已有测试夹具环境下启动 Toolathlon Runner。两个样本分别使用不同的随机标记及工作区，另在作用域外放置控制文件。以真实 Server 执行确定性的越界读取和写入探测。 | 实际配置、进程和请求中只有本次声明的外部工具。探测请求到达 Server 的隔离边界并被拒绝，两个样本互不可访问对方文件，控制文件保持原状。模型请求、执行记录及文件状态分别核对。 |
| V4 写入与用户结果 | 按 §7.1 执行文件整理，固定上游初始档案、映射、权限、模型和评分版本。 | 正常组获得与评分契约相符的文件和目录终态，并通过产品的适用交付门禁。移除移动能力后无相应写入。若写路径存在断线后状态不确定的分支，先证明无需或禁止自动重发，或证明已核对状态再恢复。评分成功与副作用控制分别记录。 |
| V5 同工具条件对照 | 固定同一任务，声明工具、辅助动作和差异。用真实模型请求核对投影，另对清单外业务工具执行一个适用的拒绝控制。 | 当轮动作与声明及阶段条件一致。清单外调用拒绝且后端零执行，适用的间接入口同样受约束。比较报告披露产品控制动作与上游的差异。 |
| V6 网关兼容 | 用所选上游版本启动真实网关，针对拟用端点完成连接、发现、只读调用、失败和关闭。 | 端到端协议交换、错误归因和清理均可核对。通过后才引入依赖此传输的写用例。该项是传输证据。 |

每个用例在执行前固定入口、命令、样本、预算、停止条件与归档身份。首轮接线和隔离以一个正常样本及表中必要反事实为范围，写入用例独立预声明。按[评测模块规范](../../evals/AGENTS.md)保存上游提交、Server 版本或镜像摘要、脱敏配置、请求与动作声明、外部状态、评分版本、预算和结果。缺失 Server、泄漏、评分资料曝光或评分不可用时，停止依赖该环境的样本并按最早责任归因。用户结果、协议检查点和隔离检查点单独报告。正式发布资格由现有证据目录和门禁判断。

### 7.3 PDF 资料与文件交付验证

固定上游提交，选取 `imagenet` 和 `detect-revised-terms` 各一个样本。使用 `imagenet` 官方中文题面，并按 `detect-revised-terms` 的详细英文题面保留实质变更、引用原文和完整对应条文的条件。真实请求从 Conversation Web 入口进入。模型沿用当前 Toolathlon 配置的直接回答，关闭 Claim 和模型核验。

PDF Server 使用上游任务镜像中已缓存的 `pdf-tools-mcp==0.1.4` 和上游锁修复包装脚本。仅映射元信息、读取、搜索及其分页。Filesystem Server 读取只读原件，写入独立的空输出目录。该目录仅用于本轮新文件交付。标准文件和评分脚本留在工具容器外。初始文件摘要、模型实际工具声明、远端调用和输出文件分别归档。

首轮验收中两个用例依次各运行一次，单例 220,000 tokens，`imagenet` 最多 24 次工具调用，`detect-revised-terms` 最多 40 次。复验按[现行预算入口](../evals/04-running-and-release.md#对话预算)记录实际生效值。先完成真实发现、代表性 PDF 读取及原件写入拒绝探测，再调用模型。模型须生成 `survey.tex` 或 `revised_terms.csv` 并交付。上游评分器独立判定，额外输出、原件变化、环境错误和未到达阶段分别报告。比较身份记录输出挂载位置与本地辅助工具差异。

首轮 imagenet 轨迹中的模板读取工具同时声明可空的 head 和 tail。模型先提交字符串，修复时又省略 tail，触发重复无效动作停止。保留首轮归档，允许一次有界复验，仅将模板读取映射切换为同一 Filesystem Server 的 read_multiple_files。固定题面、原件、模型、预算、输出路径和评分器，核对是否产生合规的模板调用与实际文件交付。

法律条款评分器沿用原始源码。它的通用导入依赖宿主缺少的 termcolor 和上游全局配置。评分改在上游镜像的离线环境执行，加载上游示例配置。只复评本次已封存的产物，评分启动问题无需重跑模型。

两例的实际模型请求均采用直接回答，未进入 Claim 或模型核验。三次运行的 PDF 读取和只读探针通过，原件摘要保持。

- `imagenet` 首轮因模板工具参数连续不合规而停止，归档为 `.tmp/pi-013618/`。切换模板读取映射后，模型成功读取模板和论文。读取 `2212.09748v2.pdf` 第 6 至 7 页后，Web 返回 500，未生成 `survey.tex`。上游评分失败，归档为 `.tmp/pr-013921/`。真实 PDF Server 离线复现该响应含 6 个 NUL 字符，PostgreSQL 转为 JSONB 时返回 `22P05`。同批另一份 PDF 响应无 NUL，JSONB 写入对照通过，见 `.tmp/pdf-nul-probe/`。
- `detect-revised-terms` 发起 9 次模型调用，实际消费 233,829 tokens。运行达到 220,000 tokens 门禁后返回 `limitation`，未生成 CSV。上游评分器在独立容器报告缺少文件。原运行和离线评分归档为 `.tmp/pd-013711/`。

法律条款用例按用户要求扩大单例总 token 预算至 800,000，保留 40 次工具调用上限。旧样本在 9 次模型调用后仍处于取证阶段，本次为长材料与累计对话预留预算。从独立工作区重跑一次，固定原题、模型、原件、初始映射和上游评分器。继续用直接回答，关闭 Claim 和模型核验。若再触发同一预算门禁，保留失败并停止追加样本。

800,000 tokens 组在第 8 个主循环后停止，实际消费 308,373 tokens、使用 20 次工具调用。该轨迹触发主循环轮数上限，评分器确认缺少 CSV，归档为 `.tmp/pt-103328/`。该运行已保存终态。以新样本复验轮数预算，将上限由 8 提至 24，保留 800,000 tokens、40 次工具调用及其他条件。本组各一次，达到任何有效停止条件后按实际结果记录。

24 轮复验完成 18 轮、19 次模型调用和 30 次工具调用。第 18 轮模型响应计量后累计 856,213 tokens，其中输入 840,074 tokens，触发 800,000 tokens 门禁。未生成 CSV，独立评分确认缺少文件。题面、模型、初始文件摘要、工具映射及评分器摘要与原样本一致。复验归档为 `.tmp/pu-103645/`。

用户明确要求继续提额。以新样本运行同一法律条款用例，总 token 预算为 2,000,000，主循环上限 36 轮，工具调用上限 64 次。上一轮后段多次请求累计输入超过 84 万 tokens，扩大三个运行额度以观察更长的完整取证与交付。固定题面、模型、工具映射、初始文件、评分器和关闭 Claim 与模型核验的配置。单例运行，按实际停止条件和独立文件评分记录结果。

2,000,000 tokens 复验完成 29 轮、33 次模型调用和 53 次工具调用。实际消费 2,096,829 tokens，其中输入 2,057,838 tokens。第 29 轮响应计量后触发总 token 门禁，轮数和工具调用额度仍有余量。上游评分确认缺少 CSV。固定输入及评分器摘要与上一轮一致，归档为 `.tmp/pw-104232/`。

## 8. 实施顺序、迁移与状态

已迁移 Web、CLI、worker 和仍构造 `AgentService` 的仓库脚本。批量工厂已删除。连接装配决定记录在[连接生命周期 ADR](../adr/0051-mcp-client-lifecycle.md)。评测启动和证据查看见[评测运行说明](../evals/04-running-and-release.md)。

V1 的正式工具 API 返回东京 10:00。移除映射并向父进程注入无效旧配置后，实际盘点为空，直接调用被拒绝，工具容器未运行。真实对话按两个预算组分别封存。12,000 tokens 组调用 Time 成功，交付在核验预算门禁停止。采用仓库默认预算的独立样本自主调用 Time 并回答东京上午 10 点，实际模型 3 次、15,423 tokens。该样本的用户答复和评测器关闭故障分别计分，关闭由修正后的确定性场景验证。

正式 HTTP 的确定性运行覆盖正常调用、移除映射、第二个 Server 缺少工具、重名和断线五个场景，均符合判据。断线反事实中，旧版本的正式工具 API 超时且容器被隐式重启。目标版本拒绝继续派发，重启宿主后重新握手并成功调用。报告分别位于运行目录的 `final-baseline-disconnect` 和 `target-final-*`。

V2 的独立真实协议与组合根探测中，旧客户端断线后拒绝继续派发，容器没有被隐式重启。新客户端握手成功，正常关闭后容器退出。第二个 Server 缺少映射工具时，前后两个容器都被回收。报告为运行目录的 `target-protocol-composition.json`。

V3 使用锁定 Toolathlon 镜像，在两个各自挂载单一样本目录的容器运行真实文件 Server。两个样本均成功读取自己的标记，越界读取与移动均被拒绝，原文件内容保持。对应报告为运行目录的 `filesystem-boundary/report.json`。该证据只覆盖服务端工作区隔离。升级后的专用镜像复验通过。两个样本的越界读写均被拒绝，同名目标的移动返回 `Destination already exists`，源和原目标内容保持。独立样本确认了列目录、创建目录、移动的参数和正常移动的文件终态。对应归档为 `.tmp/toolathlon-filesystem-upgrade-20261109-210601-534/acceptance.json`，以镜像摘要区分原镜像和升级镜像。V4 的产品写入授权和完整用户任务仍待验证。V5 与 V6 的比较目标或选定传输仍待触发。

V4 准入探针使用 `d2dfc26` 和真实 Filesystem Server，向正式工具 API 提交未确认的高风险移动。Policy 返回 `require_confirmation`，ToolGateway 仍调用了通用 MCP 映射。文件 Server 返回 `EROFS`，样本保持原状。网关把待确认决定交给工具自行生成预览，而通用 MCP 工具直接派发且没有预览契约。正向可写样本停在 Command 与确认边界。原始证据在 MCP 工作树 `.tmp/toolathlon-arrange-v4-20261109-212931-726/approval/`。[网关策略处理](../../src/personal_agent/governance/gateway.py) · [MCP 映射](../../src/personal_agent/tools/mcp.py)

派发门禁修复已复验。相同探针在基线与修复版本上使用相同镜像、映射和请求。修复后的远端实收仅一次 `list_directory`，两次移动与拒绝域的建目录均为零次，三项拒绝的错误类型均为 `permission`，审计没有将自报确认记为已确认，工作区内容一致。基线、同脚本目标与最终带审计断言的复验分别为 `.tmp/gate-red-223556/`、`.tmp/gate-green-223756/`、`.tmp/gz-224428/`。真实 Time 对话继续通过，正式工具审计记录模型调用，答复为东京上午 10 点。知识删除 HTTP 回归确认无确认时返回 409，确认后取得原 Command 对应的 Receipt，重复确认返回同一 Receipt。报告分别为 `.tmp/gt-223900/` 和 `.tmp/gk-223948/`。

身份与投影对照中，基线跨租户同名用户经直调获 200，目标获 403。配置拒绝的 `time.convert_time` 从 4 次模型动作声明降为零，合法的 `time.get_current_time` 继续出现。伪造来源、SSE 被拒入口和启用主体白名单时的未认证直调均获 403。个人租户记忆读取正常，参数切换用户和跨租户读取均被拒绝。证据位于 `.tmp/pol-b/`、`.tmp/pol-t/` 和 `.tmp/pol-final/`。派发探针最终复验为 `.tmp/wg-final/`。

合并复核中，原碰撞配置使两个不同 Web 主体均调用真实 Time Server。目标拒绝该配置启动，合法对照为 200，非授权主体为 403，非法请求租户为 422。CLI 自报主体在入口拒绝。飞书事件回放以实际发送者区分允许、拒绝和无身份事件，覆盖适配及策略阶段。复验归档为 `.tmp/mi-red/`、`.tmp/mi-green/`、`.tmp/mf-red/` 和 `.tmp/mf-green/`。文件拒绝复验使用原会话的新运行，得到同一清单的新确认摘要，远端零写入，见 `.tmp/mr-red/` 和 `.tmp/mr-green/`。

工作区单文件批准、拒绝和断连各一个样本通过，归档为 `.tmp/wg-a/`、`.tmp/wg-r/` 和 `.tmp/wg-u/`。批准组实际移动一次，源目标内容摘要相同，答复交付确切位置。拒绝和断连组无远端写入，分别持久化 `rejected` 与 `unknown`，续跑返回对应的用户结果。三个样本均在续跑后重复提交同一决定并得到原回执。独立进程重放已完成的真实快照时，并发决定一项返回原回执，一项获运行锁冲突 409，后续重试返回原回执，MCP 实收为零。空数据库的并发审计初始化复验无 DDL 竞争异常，归档为 `.tmp/wg-rep2/`。

V4 完整样本 `.tmp/wg-f/` 在一次正式批准后执行 16 项建目录和 22 项移动，22 份文件内容摘要保持。上游评分器确认 18 个目录正确，20 个文件位置匹配。`cv-gboeing.pdf` 与 `exam.xlsx` 的分类与评分标准不一致，评分退出 1。产品答复达到 12 次工具调用门禁后返回 `limitation`，模型实际消费 92,107 tokens。授权与执行检查通过，完整任务评分和最终交付未通过。

2026-11-10，主工作区 `54f5b49` 以独立进程重跑完整样本。本次配置使用直接回答，关闭目标与回答模型核验。7 次实发模型请求只有意图提取和主循环，实际消费 73,056 tokens。用户收到 `answer`，正式确认与 38 项写入通过。上游评分仍退出 1，18 个目录全部匹配，22 个文件内容摘要保持，`cv-gboeing.pdf` 与 `exam.xlsx` 的位置偏差复现。证据位于主工作区 `.tmp/mt-010327/`。该运行同时改变回答方式和核验开关，结果按独立配置记录。

V4 只读对照在真实初始档案上展开 22 个文件。正式工具 API 能列出 `/case`，未映射的移动被拒绝。真实对话的 5 次模型请求均未暴露移动，工具审计记录 3 次目录读取成功和 2 次拒绝或失败，其中容器根目录 `/` 读取被隔离边界拒绝。前后路径和内容摘要一致，上游评分器按未整理状态退出 1。对话因默认 32,000 tokens 门禁返回 `limitation`，实记 38,291 tokens，未生成交付答复。正向样本未运行。复验归档为 MCP 工作树 `.tmp/v4r-213257/readonly/`。

只读准备曾因脚手架误写文件数而提前停止，未调用模型。按实际 22 个文件运行后，首个模型响应因 Windows 归档路径超长未保存，对话返回 `application_persistence`。原失败保留在 MCP 工作树 `.tmp/toolathlon-arrange-readonly-20261109-213042-762/`。同样的原子写入在 276 字符路径复现 WinError 3，缩短到 242 字符后成功。复验只更换输出路径，原题、模型、映射、镜像和预算保持一致。

实施前使用独立 Time Server 复核了 MCP 客户端边界。按上游锁定版本构建后，`tools/list` 返回两个工具，`convert_time` 返回东京 10:00。停止真实 Server 后，旧客户端启动了新进程，仍沿用已初始化状态，随后调用超时。V2 因而分别断言旧实例拒绝继续派发，以及显式重新装配完成新握手。镜像构建采用上游锁文件的 Time Server 依赖闭包，评测启动代码随套件保存。

| 顺序 | 变更与验证 | 迁移或退出 |
| --- | --- | --- |
| 1 | 固定 Time Server 版本和启动配置，先用现有入口取得 V1 与适用 V2 的基线证据。 | 如果现有配置已经满足连通，首个外部 Server 以配置接入。 |
| 2 | 按 MCP-02 的实际证据移动连接所有权，迁移 Web、CLI、worker 及受影响的 `AgentService` 调用方。执行 V1 和 V2，核对实际依赖。 | 删除原 `build_mcp_tools()` 批量装配与公开导出，统一关闭入口。适用时按 REL 记录跨模块所有权调整。 |
| 3 | 在评测侧落实独立环境、显式映射和归档，执行 V3。在合法写入可达后，先用现行机制取得 V4 基线，再决定是否需要生产改动。 | 改编用例在自己的身份下报告。若已有能力足以满足结果，按现有路径收敛。 |
| 4 | 只有选定任务要求聚合网关，才按 V6 决定和验收传输。如果同工具对照成为正式目标，再按 V5 启用通用能力限制。 | 条件未满足时保持方案为候选。必要的传输、授权或部署边界变更按 REL 记录。 |

本 Spec 的实施准入由[变更证据](../devSpec/change-evidence.md#7-强制开发与设计流程)和[迁移与完成门禁](../devSpec/migration-release.md)管理。涉及能力投影实际改动时，先审计真实请求与构造链，再同步[上下文契约](../devSpec/context-memory-retrieval.md)。落地后更新现行架构、工具及配置正文。本文保持候选方案和需求追溯的唯一入口，实际结果进入既有评测盘点。
