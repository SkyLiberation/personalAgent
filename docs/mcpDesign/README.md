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
  infra/mcp.py                  调整协议客户端和会话关闭
  tools/mcp.py                  保留单工具映射与结果转换
  orchestration/
    mcp_bindings.py             新增按配置连接、发现和绑定的装配入口
    service.py                  持有并关闭 MCP 连接资源
    runtime.py                  消费已绑定的工具并注册
  adapters/
    web/context.py              服务退出时关闭资源
    cli/main.py                 CLI 和 worker 退出时关闭资源
  kernel/config_models.py       复用 MCPConfig、MCPServerConfig、MCPToolConfig

deploy/mcp/                     有实际生产部署时存放对应配置
evals/
  Toolathlon/
    runner.py                   新增用例环境、产品 HTTP 交互和评分适配
    cases/                      固定任务、上游版本、映射及评分入口
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

区分启动或握手错误、配置或 Schema 不匹配、准入拒绝、远端工具错误，以及执行结果未知。环境配置错误由 Runner 归为环境失败。工具错误进入现有反馈链。写调用超时或断线时，在能够从权威终态确认结果之前按未知处理。连接恢复可以重新握手。重发写操作必须满足该工具的幂等或状态核对契约，产品执行仍使用原授权与执行事实。

### 5.3 选择 Toolathlon 传输

先按 Toolathlon 的 Time 配置，以其锁定的 `mcp-server-time==0.6.2` 为首个候选，在隔离环境启动独立 stdio Server，并核对 `convert_time` 的发现和调用结果。由启动侧解析工作目录和变量。[Time 配置](https://github.com/hkust-nlp/Toolathlon/blob/9be8d8fe07a497b18ee61e3f2ae694e9797f39eb/configs/mcp_servers/time.yaml) · [依赖版本](https://github.com/hkust-nlp/Toolathlon/blob/9be8d8fe07a497b18ee61e3f2ae694e9797f39eb/pyproject.toml#L82)

仅在用例确需复用聚合网关时处理旧式 HTTP+SSE。该网关通过 `GET /sse` 给出 `/messages` 地址，调用结果通过原 SSE 会话返回。现有 `http` 实现对单一地址发 POST 并读取响应体。候选是在通用协议层引入经验证的旧式 SSE 支持，或在评测环境提供兼容端点。先用现有客户端确认首个不兼容的协议边界，再用 V6 验收选定的适配。[网关路由](https://github.com/hkust-nlp/Toolathlon/blob/9be8d8fe07a497b18ee61e3f2ae694e9797f39eb/scripts/decoupled/container_tool_gateway.py#L344) · [MCP 传输规范](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports)

网关现有远端调用配置了一次异常重试。写入用例若走该网关，先验证下游幂等、权威状态核对或评测部署能关闭该重试。文件移动回包丢失时，重新读取源与目标状态供后续判断，自动重发之前需要上述依据。[网关调用实现](https://github.com/hkust-nlp/Toolathlon/blob/9be8d8fe07a497b18ee61e3f2ae694e9797f39eb/scripts/decoupled/container_tool_gateway.py#L319)

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

原 Toolathlon 任务镜像中的文件 Server 为 `2025.7.1`。真实探测中，`move_file` 覆盖了已存在的目标，与工具声明不符。先在原任务镜像内以只读挂载替换运行时，验证修复行为。正式评测构建独立的 Filesystem 镜像，固定 Filesystem Server `2.2.0` 及其所需的 Node.js `24.22.2`。构建固定 slim 基础镜像的摘要，并校验 Node.js 官方归档的 SHA-256。Server 负责在写入前拒绝覆盖。评测侧拥有镜像配方和样本工作区，复用现有 stdio 客户端及探测入口。当前对话运行器只开放 Time 的转换工具。[上游修复](https://github.com/modelcontextprotocol/servers/pull/4630)

独立镜像验证复用原任务镜像的冲突和跨目录探测。一次运行检查两个隔离样本，其中一个带已有目标文件。冲突必须返回目标已存在，源文件与原目标内容均保留。另用一个独立工作区核对 `list_directory`、`create_directory` 和 `move_file` 的入参，以及目标为空时能完成移动。任一检查失败即停止采用该镜像。验证只启动真实文件 Server，无模型调用。通过后将镜像作为 V4 的文件 Server 环境，产品写入授权和完整任务评分分别按以下步骤验证。

Toolathlon 的 `arrange-workspace` 配置包含文件系统、终端、PDF、Excel 和若干宿主辅助动作。其预处理将初始档案展开到工作区，评分器对比最终目录和文件路径集合。首个写入候选以同一份初始档案运行中文改编任务，向用户提供同一目标目录结构。上游文件 Server 配置使用未固定版本的 npm 包。V4 前先选定并锁定实际包版本，核对列举、创建目录和移动文件所需的工具、Schema、覆盖行为及副作用，再固定映射。[上游任务配置](https://github.com/hkust-nlp/Toolathlon/blob/9be8d8fe07a497b18ee61e3f2ae694e9797f39eb/tasks/finalpool/arrange-workspace/task_config.json) · [文件 Server 配置](https://github.com/hkust-nlp/Toolathlon/blob/9be8d8fe07a497b18ee61e3f2ae694e9797f39eb/configs/mcp_servers/filesystem.yaml) · [预处理](https://github.com/hkust-nlp/Toolathlon/blob/9be8d8fe07a497b18ee61e3f2ae694e9797f39eb/tasks/finalpool/arrange-workspace/preprocess/main.py) · [目录评分](https://github.com/hkust-nlp/Toolathlon/blob/9be8d8fe07a497b18ee61e3f2ae694e9797f39eb/tasks/finalpool/arrange-workspace/evaluation/check_local.py)

1. Runner 启动任务环境并放入初始文件。用户经 `POST /api/conversation/turn` 提交“请按下面的目录结构整理我的工作区文件”，附上任务提供的目标结构。
2. 真实模型读目录、判断文件归属、选择移动动作，并根据真实回执决定后续动作和交付。首个切片只采用现行 Policy 能按真实风险和任务作用域合法准入的写入。执行前沿正式入口核对所需 Command、用户授权及确认是否可达。如果工具需要确认而现行入口无法承接，停止 V4 并记录阻塞。Runner 的配置只提供环境和任务身份，用户授权来自正式交互。
3. 产品按自身完成契约交付。评分器独立检查目录和文件路径集合。必要隔离反例检查其他工作区和评分资料不可读写。对移除移动映射的控制组，记录未提供移动能力、工具拒绝或零写入的实际证据。模型报告完成与真实终态单独计分。

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

## 8. 实施顺序、迁移与状态

已迁移 Web、CLI、worker 和仍构造 `AgentService` 的仓库脚本。批量工厂已删除。连接装配决定记录在[连接生命周期 ADR](../adr/0051-mcp-client-lifecycle.md)。评测启动和证据查看见[评测运行说明](../evals/04-running-and-release.md)。

V1 的正式工具 API 返回东京 10:00。移除映射并向父进程注入无效旧配置后，实际盘点为空，直接调用被拒绝，工具容器未运行。真实对话按两个预算组分别封存。12,000 tokens 组调用 Time 成功，交付在核验预算门禁停止。采用仓库默认预算的独立样本自主调用 Time 并回答东京上午 10 点，实际模型 3 次、15,423 tokens。该样本的用户答复和评测器关闭故障分别计分，关闭由修正后的确定性场景验证。

正式 HTTP 的确定性运行覆盖正常调用、移除映射、第二个 Server 缺少工具、重名和断线五个场景，均符合判据。断线反事实中，旧版本的正式工具 API 超时且容器被隐式重启。目标版本拒绝继续派发，重启宿主后重新握手并成功调用。报告分别位于运行目录的 `final-baseline-disconnect` 和 `target-final-*`。

V2 的独立真实协议与组合根探测中，旧客户端断线后拒绝继续派发，容器没有被隐式重启。新客户端握手成功，正常关闭后容器退出。第二个 Server 缺少映射工具时，前后两个容器都被回收。报告为运行目录的 `target-protocol-composition.json`。

V3 使用锁定 Toolathlon 镜像，在两个各自挂载单一样本目录的容器运行真实文件 Server。两个样本均成功读取自己的标记，越界读取与移动均被拒绝，原文件内容保持。对应报告为运行目录的 `filesystem-boundary/report.json`。该证据只覆盖服务端工作区隔离。升级后的专用镜像复验通过。两个样本的越界读写均被拒绝，同名目标的移动返回 `Destination already exists`，源和原目标内容保持。独立样本确认了列目录、创建目录、移动的参数和正常移动的文件终态。对应归档为 `.tmp/toolathlon-filesystem-upgrade-20261109-210601-534/acceptance.json`，以镜像摘要区分原镜像和升级镜像。V4 的产品写入授权和完整用户任务仍待验证。V5 与 V6 的比较目标或选定传输仍待触发。

实施前使用独立 Time Server 复核了 MCP 客户端边界。按上游锁定版本构建后，`tools/list` 返回两个工具，`convert_time` 返回东京 10:00。停止真实 Server 后，旧客户端启动了新进程，仍沿用已初始化状态，随后调用超时。V2 因而分别断言旧实例拒绝继续派发，以及显式重新装配完成新握手。镜像构建采用上游锁文件的 Time Server 依赖闭包，评测启动代码随套件保存。

| 顺序 | 变更与验证 | 迁移或退出 |
| --- | --- | --- |
| 1 | 固定 Time Server 版本和启动配置，先用现有入口取得 V1 与适用 V2 的基线证据。 | 如果现有配置已经满足连通，首个外部 Server 以配置接入。 |
| 2 | 按 MCP-02 的实际证据移动连接所有权，迁移 Web、CLI、worker 及受影响的 `AgentService` 调用方。执行 V1 和 V2，核对实际依赖。 | 删除原 `build_mcp_tools()` 批量装配与公开导出，统一关闭入口。适用时按 REL 记录跨模块所有权调整。 |
| 3 | 在评测侧落实独立环境、显式映射和归档，执行 V3。在合法写入可达后，先用现行机制取得 V4 基线，再决定是否需要生产改动。 | 改编用例在自己的身份下报告。若已有能力足以满足结果，按现有路径收敛。 |
| 4 | 只有选定任务要求聚合网关，才按 V6 决定和验收传输。如果同工具对照成为正式目标，再按 V5 启用通用能力限制。 | 条件未满足时保持方案为候选。必要的传输、授权或部署边界变更按 REL 记录。 |

本 Spec 的实施准入由[变更证据](../devSpec/change-evidence.md#7-强制开发与设计流程)和[迁移与完成门禁](../devSpec/migration-release.md)管理。涉及能力投影实际改动时，先审计真实请求与构造链，再同步[上下文契约](../devSpec/context-memory-retrieval.md)。落地后更新现行架构、工具及配置正文。本文保持候选方案和需求追溯的唯一入口，实际结果进入既有评测盘点。
