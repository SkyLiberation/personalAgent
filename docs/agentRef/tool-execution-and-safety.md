# 工具执行与安全能力参考

**成熟的工具能力不是“模型能调用函数”，而是能力发现、动作准入、最小权限执行、执行事实和失败恢复的完整边界。** 沙箱限制能触达什么，审批决定当前动作能否越界，两者不能互相替代。

本页只拥有外部工具执行与安全机制比较；资料等级、固定提交与采用边界见[参考索引](README.md)。

## 1. 代表机制

| 实现 | 突出能力 | 安全边界 |
| --- | --- | --- |
| Codex | [Approvals and security](https://learn.chatgpt.com/docs/agent-approvals-security)把 sandbox mode 与 approval policy 分开；工具、MCP、规则和 Skill 脚本可有不同权限 | 沙箱是操作系统强制的资源边界；审批是具体动作的授权边界，受保护目录继续限制写入 |
| Claude Code | [Hooks](https://code.claude.com/docs/en/hooks)覆盖 `PreToolUse`、权限请求、失败、子级和会话事件，可用命令或策略判断阻止动作 | Hook 可以拒绝或补充 Context，但不能把模型判断冒充底层隔离；权限模式仍单独生效 |
| OpenHands | [Runtime architecture](https://docs.openhands.dev/openhands/usage/architecture/runtime)以 Action → ActionExecutor → Observation 明确请求和结果；[Security](https://docs.openhands.dev/sdk/guides/security)把 confirmation policy 与 security analyzer 分开 | `AlwaysConfirm`、`NeverConfirm`、`ConfirmRisky` 决定审批；风险分析器不自动改变确认策略；DockerWorkspace 的实际装配、默认限制及生命周期见本文 §6，不由使用 Docker 推定全部隔离生效 |
| Gemini CLI | [Sandbox](https://github.com/google-gemini/gemini-cli/blob/3c311beac2e78336816dd4a123db39743f9fbf85/docs/cli/sandbox.md)在命令受限时请求一次性的目录或网络扩权；Plan Mode 另有只读策略 | 扩权必须显示所需资源并逐次批准；计划态既有批准不应自动扩张成实现态权限 |
| DeepSeek Harness | [Capability seams](https://github.com/deepseek-ai/deepseek-harness/blob/b150a551b8d465e31e418e1b2eaf5e79bbb7d28e/docs/capability-seams.md)把工具注册、guarded execution pipeline、沙箱策略、审批与文件系统 Provider 分成 seam | seam 允许替换实现，但权限、审批、沙箱与执行结果仍需各自 owner |

## 2. 可复用的执行分层

1. **能力投影**只暴露当前主体、scope 和会话允许的工具子集。
2. **Proposal**保留模型选择的工具与原始参数，不携带执行成功含义。
3. **准入**确定性检查类型、权限、风险、幂等与是否需要用户批准。
4. **隔离执行**在最小文件、网络、凭据和进程权限内产生 Observation 或 Receipt。
5. **结果处理**区分拒绝、暂时失败、执行失败与成功，不以空值或 fallback 伪装成功。

## 3. 机制比较时必须追问

- 权限由身份与 scope 决定，还是仅靠 Prompt 提醒模型不要调用。
- 批准绑定原始动作、参数摘要和时效，还是批准后允许模型改写 payload。
- 只读、可重试动作与不可逆副作用是否采用不同执行协议。
- 安全分析器失败时是 fail closed、请求人工判断还是静默放行。
- 工具结果是否成为可审计执行事实，是否与语义验证和 Completion 分离。

personalAgent 的正式执行契约仍以[智能体决策与受治理执行](../devSpec/agentic-execution.md)和[测试、评估、观测与安全](../devSpec/quality-security.md)为准。

## 4. 工具粒度、通用性与按需暴露

2026-10-19 核对三个独立开源实现的 43 个固定源码／示例文件，均为 A 级机制证据，见[统一来源及 SHA-256](../../.tmp/tool-design-review-20261019/source-manifest.json)与[核查范围](../../.tmp/tool-design-review-20261019/source-review.json)。未运行第三方项目、模型或测试；源码只能证明相应配置下的机制，不证明本工程工具过多、收益或最佳工具数量。

| 实现 | 实际装配与模型消费 | 粒度及披露边界 |
| --- | --- | --- |
| DeepAgents `fd3e64ab6b605450bed5a2c22ef2ec84cd40542e` | [`create_deep_agent`](https://github.com/langchain-ai/deepagents/blob/fd3e64ab6b605450bed5a2c22ef2ec84cd40542e/libs/deepagents/deepagents/graph.py#L894)装配 Filesystem middleware，并接受调用者领域 tools；最终交给 `create_agent`。Filesystem 实际提供 `ls/read_file/write_file/edit_file/delete/glob/grep/execute` 八类候选操作 | [`tools=`](https://github.com/langchain-ai/deepagents/blob/fd3e64ab6b605450bed5a2c22ef2ec84cd40542e/libs/deepagents/deepagents/middleware/filesystem.py#L2020)可排除工具；[请求过滤](https://github.com/langchain-ai/deepagents/blob/fd3e64ab6b605450bed5a2c22ef2ec84cd40542e/libs/deepagents/deepagents/middleware/filesystem.py#L3333)移除后端不支持的执行／删除。默认是 StateBackend，不是 Shell。显式配置 skill tools／resolver 后，[SkillsMiddleware](https://github.com/langchain-ai/deepagents/blob/fd3e64ab6b605450bed5a2c22ef2ec84cd40542e/libs/deepagents/deepagents/middleware/skills.py#L1338)才依据已读技能披露并允许调用相应工具；普通传入 tools 不自动全部延迟加载 |
| OpenHands SDK `6530325e9dd0ea1b6b4f1994d7dab52764cfc3f1` | [`AgentBase._initialize`](https://github.com/OpenHands/software-agent-sdk/blob/6530325e9dd0ea1b6b4f1994d7dab52764cfc3f1/openhands-sdk/openhands/sdk/agent/base.py#L571)解析调用者工具列表、过滤并加入默认工具；[LLM 调用](https://github.com/OpenHands/software-agent-sdk/blob/6530325e9dd0ea1b6b4f1994d7dab52764cfc3f1/openhands-sdk/openhands/sdk/agent/agent.py#L790)消费该 Agent 的 `tools_map`，不是全部注册表。[示例](https://github.com/OpenHands/software-agent-sdk/blob/6530325e9dd0ea1b6b4f1994d7dab52764cfc3f1/examples/01_standalone_sdk/01_hello_world.py#L16)选择 Terminal、FileEditor、TaskTracker | [FileEditorAction](https://github.com/OpenHands/software-agent-sdk/blob/6530325e9dd0ea1b6b4f1994d7dab52764cfc3f1/openhands-tools/openhands/tools/file_editor/definition.py#L29)把同类文件操作放入一个明确操作协议；[invoke_skill](https://github.com/OpenHands/software-agent-sdk/blob/6530325e9dd0ea1b6b4f1994d7dab52764cfc3f1/openhands-sdk/openhands/sdk/tool/builtins/invoke_skill.py#L90)按名称返回技能正文，不为每份任务知识注册领域算法工具。编码产品的 Terminal 适用性不能直接外推到业务写入 |
| Gemini CLI `ed96faedfd5571f055c44f2c9509d62321d1138d` | [`Config.createToolRegistry`](https://github.com/google-gemini/gemini-cli/blob/ed96faedfd5571f055c44f2c9509d62321d1138d/packages/core/src/config/config.ts#L3980)按配置创建工具；[`getFunctionDeclarations`](https://github.com/google-gemini/gemini-cli/blob/ed96faedfd5571f055c44f2c9509d62321d1138d/packages/core/src/tools/tool-registry.ts#L663)再按有效工具、模式、资源和主 Agent 配置形成声明；`GeminiClient` 将这些声明送入模型 | 无 MCP 资源时不展示资源读取工具，计划模式切换只展示适用入口；[`activate_skill`](https://github.com/google-gemini/gemini-cli/blob/ed96faedfd5571f055c44f2c9509d62321d1138d/packages/core/src/tools/activate-skill.ts#L111)返回选中技能正文和资源。工具注册、当前披露与执行权限不能视为同一事实，也不能据此声称所有业务工具都会自动按任务检索 |

这些实现支持“稳定可组合操作、可选业务工具、明确装配和条件披露”的组合，不支持所有任务都改用一个万能 Shell。Skill 可以承载方法、脚本和资源，但必须有实际执行后端；增加一份 `SKILL.md` 不会产生执行能力。技能加载也不天然只读：上述 Gemini 版本会加入技能资源目录，OpenHands 支持动态 shell 内容，采纳时须核对真实行为。

Anthropic 的[工具设计文章](https://www.anthropic.com/engineering/writing-tools-for-agents)是 B 级官方经验：避免机械映射每个 API，围绕明确工作目的设计操作，减少重叠并控制返回内容；不主张所有工具都做成通用原语。其[Tool Search API 契约](https://platform.claude.com/docs/en/agents-and-tools/tool-use/tool-search-tool)允许先延迟披露 Schema，再通过搜索展开；完整定义仍发送给 API，不能把模型 Context 减少解释为请求体也只剩少数定义。厂商数量阈值和性能结果不转作本工程门槛。

对本工程的取舍由[主循环工具设计](../optimization/to_verify/conversation-loop-boundaries.md#工具粒度和模型可见面的收敛)拥有。采用时分别回答：是否复用已有操作、是否需要独立业务授权或状态契约、当前请求为什么需要看到、返回内容是否支持下一步、减少名称是否只是把复杂度藏进参数。模型工具面的收益须用实际请求、错误及用户结果验证，不以框架采用数量或命名方式证明。

## 5. 固定程序执行可复用的库

2026-10-19 核对两个独立开源库的正式调用链，取得 9 个文件并走读相关关键片段；固定版本、文件及 SHA-256 见[源码清单](../../.tmp/experiment-runner-libraries-20261019/source-manifest.json)。Docker 取本轮查询到的官方发布版 `7.2.0`（2026-07-09 发布），psutil 使用与官方 stable 文档对应的 `v7.2.2` tag；psutil 的 GitHub `releases/latest` 返回 404，按 tag 固定，不宣称它提供了对应 GitHub Release。未安装库、调用 Docker Engine 或运行第三方程序。

| 库及固定身份 | 实际调用链与能力 | 不能直接归给库的职责 |
| --- | --- | --- |
| Docker SDK for Python，pip 包 `docker`；`docker/docker-py@5ad5327fba623897ee9a527d7eee1b01703e0726`（`7.2.0`） | [`ContainerCollection.create()`](https://github.com/docker/docker-py/blob/5ad5327fba623897ee9a527d7eee1b01703e0726/docker/models/containers.py#L914)转换参数并调用 Engine create，再按 ID inspect；`Container.start/stop/wait` 委托 [API](https://github.com/docker/docker-py/blob/5ad5327fba623897ee9a527d7eee1b01703e0726/docker/api/container.py#L1187)。[HostConfig](https://github.com/docker/docker-py/blob/5ad5327fba623897ee9a527d7eee1b01703e0726/docker/types/containers.py#L264)把内存、CPU、只读根目录、进程数及挂载等变为 Engine 参数，实际强制由 Engine／宿主执行 | SDK 是 Engine 客户端，不是独立沙箱或持久作业系统。`wait(timeout)` 是请求超时；任务截止、停止后的确认、状态未知对账、输入授权、结果及清理仍由调用方负责 |
| psutil；`giampaolo/psutil@9eea97dd6f1d16ea33f5144c8925f1ce7a0688e1`（`v7.2.2`） | [`Process.children()`](https://github.com/giampaolo/psutil/blob/9eea97dd6f1d16ea33f5144c8925f1ce7a0688e1/psutil/__init__.py#L950)遍历父子关系，`terminate/kill/wait` 委托平台实现；[`wait_procs()`](https://github.com/giampaolo/psutil/blob/9eea97dd6f1d16ea33f5144c8925f1ce7a0688e1/psutil/__init__.py#L1569)分别返回已退出及仍存活进程。`rlimit` 仅在 Linux／FreeBSD 暴露 | 可辅助标准库 `subprocess` 管理与监测本地进程，不提供完整文件／网络隔离。递归进程列表是快照，祖先进程消失可能漏掉后代；Windows 上不能把它视为同等硬额度或进程容器 |

该 Docker SDK 的 [`run()`](https://github.com/docker/docker-py/blob/5ad5327fba623897ee9a527d7eee1b01703e0726/docker/models/containers.py#L875)捕获镜像缺失后自动 pull；要求预备固定镜像的调用方应显式 create 并处理缺失，而非无条件照搬该便捷调用。`from_env()` 在本版本默认还可跟随 CLI context，实际运行端应从部署配置明确绑定 Engine 端点。自动删除会影响事后 inspect／产物恢复，是否删除须按真实消费者决定；仅设置客户端超时不产生服务端任务 TTL。

这两条调用链提供的是不同层次的复用，不证明本工程必须容器化每个工具，也不证明容器约束已在目标环境生效。[研究 Spec 的 runner 设计](../optimization/to_verify/knowledge-decision-delivery.md#执行隔离与沙箱的最小边界)拥有本例推荐、装配、生命周期及验收；此处仅记录外部事实和限制。

## 6. 开源 Agent 的运行隔离装配

2026-10-19 固定三个项目的源码身份，取得并校验 69 个相关源码／配置文件，走读实际装配、执行及停止分支；范围及 SHA-256 见 [OpenHands 清单](../../.tmp/runtime-isolation-practices-20261019/openhands/source-manifest.json)、[Gemini CLI 清单](../../.tmp/runtime-isolation-practices-20261019/gemini/source-manifest.json)、[OpenSandbox 清单](../../.tmp/runtime-isolation-practices-20261019/opensandbox/source-manifest.json)。以下是 A 级机制证据，未安装或运行这些项目，不证明目标环境的隔离效果或本工程收益。

| 项目及固定身份 | 实际调用链与隔离单位 | 可借鉴机制及适用限制 |
| --- | --- | --- |
| OpenHands SDK `v1.55.1`，`5fa4dea24c52fe3ac53fa4e3e67a1376b72189e2` | [`DockerWorkspace`](https://github.com/OpenHands/software-agent-sdk/blob/5fa4dea24c52fe3ac53fa4e3e67a1376b72189e2/openhands-workspace/openhands/workspace/docker/workspace.py#L151)在宿主创建容器，容器内启动 agent-server；[`RemoteWorkspace`](https://github.com/OpenHands/software-agent-sdk/blob/5fa4dea24c52fe3ac53fa4e3e67a1376b72189e2/openhands-sdk/openhands/sdk/workspace/remote/base.py#L164)经 HTTP 调 bash／file API，[BashEventService](https://github.com/OpenHands/software-agent-sdk/blob/5fa4dea24c52fe3ac53fa4e3e67a1376b72189e2/openhands-agent-server/openhands/agent_server/bash_service.py#L267)按命令 ID 保存事件并启动进程；workspace 可以执行多条命令 | 环境生命周期与命令身份、输出事件分开；管理权限在创建端，工作负载消费服务接口。但本次 DockerWorkspace 启动分支仅显式设置 `nofile`，CPU／内存／进程数、只读根目录及出网白名单未在此落实；挂载、转发环境变量和网络来自配置，不能作为本例最小权限模板 |
| Gemini CLI `3c311beac2e78336816dd4a123db39743f9fbf85`；该源码包为 nightly，非稳定发布版 | CLI 的 [`loadSandboxConfig`](https://github.com/google-gemini/gemini-cli/blob/3c311beac2e78336816dd4a123db39743f9fbf85/packages/cli/src/config/sandboxConfig.ts#L43) → [`start_sandbox`](https://github.com/google-gemini/gemini-cli/blob/3c311beac2e78336816dd4a123db39743f9fbf85/packages/cli/src/utils/sandbox.ts#L383)会把整个 CLI 放入所选环境。另一条 Core 路径由 [factory](https://github.com/google-gemini/gemini-cli/blob/3c311beac2e78336816dd4a123db39743f9fbf85/packages/core/src/services/sandboxManagerFactory.ts#L22)创建平台 manager，再包装 Shell 命令；两条路径不能合并为默认同时生效的隔离 | Linux [bwrap 参数](https://github.com/google-gemini/gemini-cli/blob/3c311beac2e78336816dd4a123db39743f9fbf85/packages/core/src/sandbox/linux/bwrapArgsBuilder.ts#L34)实际落实 namespace、新会话、只读绑定及按 Policy 开放的写入／网络。CLI 容器分支则默认挂工作目录、用户配置及 tmp，传入模型凭据，网络默认开启，未默认加入 CPU／内存／进程数硬额度；整个 Agent 的需求不能直接转作实验程序权限 |
| OpenSandbox `release-1.1.0`，`b1a29cf93a823a95913f7943010febb3f29de05c`；仅核查 Docker／Linux 分支 | `Sandbox.create()` → lifecycle API → Docker service → [`container_ops`](https://github.com/opensandbox-group/OpenSandbox/blob/b1a29cf93a823a95913f7943010febb3f29de05c/server/opensandbox_server/services/docker/container_ops.py#L362)创建容器；CommandsAdapter → execd 的 [`Controller.Execute`](https://github.com/opensandbox-group/OpenSandbox/blob/b1a29cf93a823a95913f7943010febb3f29de05c/components/execd/pkg/runtime/ctrl.go#L79)在环境内运行命令。环境 TTL、命令 deadline 和客户端连接分别管理 | 资源和安全配置真正传入 Docker HostConfig，SDK 自身不强制隔离。[Docker 网络配置](https://github.com/opensandbox-group/OpenSandbox/blob/b1a29cf93a823a95913f7943010febb3f29de05c/server/opensandbox_server/config.py#L986)默认 `host`；配置网络策略时才走支持的 [egress sidecar 分支](https://github.com/opensandbox-group/OpenSandbox/blob/b1a29cf93a823a95913f7943010febb3f29de05c/server/opensandbox_server/services/docker/docker_service.py#L810)，host 模式拒绝该策略，不能称默认限制出网 |

停止、清理与恢复还需分别核对，不能由同名 API 推定保证相同：

1. **请求取消不等于确认终态。** OpenHands 的 [`stop_bash_command`](https://github.com/OpenHands/software-agent-sdk/blob/5fa4dea24c52fe3ac53fa4e3e67a1376b72189e2/openhands-agent-server/openhands/agent_server/bash_service.py#L439)对进程组执行 SIGTERM、等待及 SIGKILL；返回 `True` 表示命令 ID 已知，即使最终等待超时也只记录错误。OpenSandbox 的 [interrupt](https://github.com/opensandbox-group/OpenSandbox/blob/b1a29cf93a823a95913f7943010febb3f29de05c/components/execd/pkg/runtime/interrupt.go#L53)也存在信号交付后的异步退出。调用方仍须消费实际退出／运行状态，不能将响应成功写成作业已停止。
2. **命令停止与环境回收不是同一步。** OpenHands 的 [cleanup](https://github.com/OpenHands/software-agent-sdk/blob/5fa4dea24c52fe3ac53fa4e3e67a1376b72189e2/openhands-workspace/openhands/workspace/docker/workspace.py#L369)执行 `docker stop` 后未检查返回码便清空 ID；Gemini CLI 的 `--rm` 只处理容器退出后的删除，本次 wrapper 分支未见按主容器 ID 停止并 inspect 的闭环。OpenSandbox 的 [`close()`](https://github.com/opensandbox-group/OpenSandbox/blob/b1a29cf93a823a95913f7943010febb3f29de05c/sdks/sandbox/python/src/opensandbox/sandbox.py#L424)只关闭客户端 transport，`kill()` 才请求释放远端环境。以上均不能由客户端不再等待推定后端资源已释放。
3. **TTL 的执行者和恢复事实决定保障范围。** OpenSandbox 的 [Docker TTL](https://github.com/opensandbox-group/OpenSandbox/blob/b1a29cf93a823a95913f7943010febb3f29de05c/server/opensandbox_server/services/docker/docker_service.py#L280)由 server 进程内 Timer 调度，启动时[扫描容器与到期元数据重建](https://github.com/opensandbox-group/OpenSandbox/blob/b1a29cf93a823a95913f7943010febb3f29de05c/server/opensandbox_server/services/docker/docker_service.py#L425)，有重启恢复机制，但 server 离线期间不能保证准时销毁；[续期元数据持久化失败](https://github.com/opensandbox-group/OpenSandbox/blob/b1a29cf93a823a95913f7943010febb3f29de05c/server/opensandbox_server/services/docker/docker_service.py#L1304)仅记 warning。OpenHands 的存活容器 pause／resume 也不等于崩溃后持久作业恢复。

这三种实现共同支持：先明确隔离单位，由受信控制端创建实际受限环境，再通过命令身份、输出和终态管理执行。不同点在于整个 Agent、长期 workspace 和单次执行的边界。本工程基线及模型候选程序的采用范围由[研究 Spec](../optimization/to_verify/knowledge-decision-delivery.md#执行隔离与沙箱的最小边界)拥有；可编程执行的追加比较见下一节。外部实现的缺省权限、停止返回值及 TTL 名称不直接成为本工程保证。

## 7. 模型生成程序的实际执行链

2026-10-20 核对两个独立 A 级实现，范围为受控编程及反馈消费。smolagents 新取得 3 个源码文件，OpenHands 复用并逐文件复核此前 7 个源码的 SHA-256；分别见[smolagents 固定清单](../../.tmp/programmable-experiment-tool-20261020/smolagents-source-manifest.json)和[OpenHands 复用清单](../../.tmp/programmable-experiment-tool-20261020/openhands-reused-sources.json)。未运行第三方程序、模型、容器或测试，不据源码主张本工程效果。

| 固定实现 | 实际装配、执行及反馈 | 采用与限制 |
| --- | --- | --- |
| smolagents `v1.22.0`，`f68ee35967da5c9051a0a9d94af6ac9ca06dafc2` | [`CodeAgent.create_python_executor`](https://github.com/huggingface/smolagents/blob/f68ee35967da5c9051a0a9d94af6ac9ca06dafc2/src/smolagents/agents.py#L1576)按配置装配 Local／Docker 等执行器；[`_step_stream`](https://github.com/huggingface/smolagents/blob/f68ee35967da5c9051a0a9d94af6ac9ca06dafc2/src/smolagents/agents.py#L1613)物化 memory、调用模型、解析代码并执行，再将日志／结果或错误放回步骤。Docker 分支在 [`DockerExecutor`](https://github.com/huggingface/smolagents/blob/f68ee35967da5c9051a0a9d94af6ac9ca06dafc2/src/smolagents/remote_executors.py#L341)启动 Jupyter Gateway 容器、建立 kernel，经 WebSocket 执行 | 借鉴“模型生成计算逻辑 → 独立执行器 → 真实反馈进入后续决策”；不把本地解释器或 import 名单当物理沙箱。不复制持久 kernel、动态 pip 安装、`final_answer` 控制终止或其默认权限；它们不能代替本工程独立评分、Completion 和已提交成果恢复 |
| OpenHands SDK `6530325e9dd0ea1b6b4f1994d7dab52764cfc3f1` | [`AgentBase._initialize`](https://github.com/OpenHands/software-agent-sdk/blob/6530325e9dd0ea1b6b4f1994d7dab52764cfc3f1/openhands-sdk/openhands/sdk/agent/base.py#L571)装配选定工具；[`Agent._execute_action_event`](https://github.com/OpenHands/software-agent-sdk/blob/6530325e9dd0ea1b6b4f1994d7dab52764cfc3f1/openhands-sdk/openhands/sdk/agent/agent.py#L1499)分派模型动作到 [`ToolDefinition.__call__`](https://github.com/OpenHands/software-agent-sdk/blob/6530325e9dd0ea1b6b4f1994d7dab52764cfc3f1/openhands-sdk/openhands/sdk/tool/tool.py#L623)及实际 executor，再产出 ObservationEvent／错误。FileEditor 写代码，Terminal 的 create 装配 TerminalExecutor，后者调用 Session 执行 | 借鉴源码产物和执行动作分开、共用编辑／执行能力以及实际错误反馈；不把整个工具目录暴露给每次任务，不照搬通用 Shell／长期 session、并发默认值或 workspace 权限。会话内状态不直接作为本工程可恢复事实 |

上述源码支持可编程执行的可实现性，不支持“只要能写代码就具有研究收益”的结论。本工程推荐的最小范围、评分边界、唯一 owner、源码冻结及 P1 验收由[研究 Spec](../optimization/to_verify/knowledge-decision-delivery.md#模型怎样构造并验证候选)拥有；独立比较仍须给固定流程相同的模型、编程能力及预算。

## 8. 文本读写与修改入口

2026-10-20 在 §4 的固定源码基础上复核以下两个独立 A 级实现，实际读取文件及摘要见[本轮来源清单](../../.tmp/program-artifact-tools-20261020/source-manifest.json)，完整装配身份仍见[原始清单](../../.tmp/tool-design-review-20261019/source-manifest.json)。未运行第三方程序或模型，不据此主张本工程收益。

| 实现 | 模型参数到实际消费者 | 采用与差异 |
| --- | --- | --- |
| OpenHands SDK `6530325e9dd0ea1b6b4f1994d7dab52764cfc3f1` | [`FileEditorAction`](https://github.com/OpenHands/software-agent-sdk/blob/6530325e9dd0ea1b6b4f1994d7dab52764cfc3f1/openhands-tools/openhands/tools/file_editor/definition.py#L29)以 command 区分 view／create／str_replace／insert／undo_edit，create 接收 file_text，str_replace 接收 old_str／new_str；Tool.create 装配 FileEditorExecutor，沿原工具分派执行 | 采用明确操作分支、结构化参数及独立文件写入口；本工程不用宿主绝对路径和旧字符串重抄定位，改用确切 Artifact 引用及行列范围，也不增加独立 undo：可以选择旧不可变快照 |
| DeepAgents `fd3e64ab6b605450bed5a2c22ef2ec84cd40542e` | `create_deep_agent` 装配 Filesystem middleware，后者的 [`_create_write_file_tool`](https://github.com/langchain-ai/deepagents/blob/fd3e64ab6b605450bed5a2c22ef2ec84cd40542e/libs/deepagents/deepagents/middleware/filesystem.py#L2304)验证路径及 write 权限后调用 backend.write；[`_create_edit_file_tool`](https://github.com/langchain-ai/deepagents/blob/fd3e64ab6b605450bed5a2c22ef2ec84cd40542e/libs/deepagents/deepagents/middleware/filesystem.py#L2395)验证后将 old_string／new_string 交给 backend.edit | 采用模型工具、权限检查和实际存储后端分开；本工程复用现有 Artifact owner，已有读取独立保留，新增一个严格 create／patch 写工具。按当前引用保真要求不采用旧字符串替换，也不引入第二套可变文件状态 |

两个项目展示不同工具分组，不决定最佳工具数量。本工程的不可变引用、批量范围修改、可读集合投影、幂等及执行绑定由[唯一候选契约](../optimization/to_verify/knowledge-decision-delivery.md#程序产物读写工具契约)定义；这些差异须按本工程真实输入和 P1 阶段验收，不能转计外部实现的能力。
