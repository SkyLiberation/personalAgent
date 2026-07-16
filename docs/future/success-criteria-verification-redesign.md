# 成功标准与验证体系重构设计

## 定位

本文定义 Agent 如何从用户目标形成成功标准，如何把标准绑定到可执行验证器，以及如何依据真实 outcome 完成 Goal 和 Task。

本设计解决的不是“再增加几个验收字段”，而是建立以下闭环：

```text
用户目标
  -> 有明确来源的 SuccessCriterion
  -> 有确定语义的 AcceptanceSpec
  -> 独立 CriterionEvaluator
  -> 带证据和版本的 CriterionResult
  -> VerificationReport
  -> CompletionReport
```

当前实现已经把 `SuccessCriterion`、`EvidencePolicy`、`VerificationGap`、`VerificationReport` 和 `CompletionReport` 建模为领域对象，也表达了 criterion 的来源与修改权限。这套业务语义应继续保留；目标模型会删除可从 provenance 推导的重复字段，并重构标准的生成边界和执行语义。

本文不提供兼容层、旧字段双写、数据迁移或渐进式 adapter。落地时直接删除无效 fallback、裸字符串 acceptance contract 和基于字段名称猜测 receipt 的实现。

## 结论

目标设计遵守五条原则：

1. `user_explicit`、`model_derived`、`contract_derived` 只表达标准来源，不代替成功判定逻辑；
2. `contract_derived` 只能从结构化契约确定性生成运行时底线，不能补写开放的业务语义；
3. `model_derived` 负责把开放目标转化为任务特有的语义 rubric，但不能降低用户标准或安全底线；
4. 每条 criterion 必须绑定一个类型化 `AcceptanceSpec` 和唯一 evaluator，禁止只有描述而没有可执行语义；
5. runtime acceptance 与 agent quality eval 分离：前者决定当前任务能否完成，后者评估版本质量、轨迹、成本和回归。

最终职责分布如下：

```text
TaskAnalyzer
  提取 user_explicit criteria
  生成 model_derived semantic criteria

GoalGraphCompiler
  校验 criteria provenance
  生成 contract_derived baseline criteria
  固化 TaskContract revision

CriterionEvaluator
  按 AcceptanceSpec 验证单条 criterion

GoalVerifier
  聚合 Goal 范围内的 CriterionResult

CompletionVerifier
  只根据 Goal verification、required criteria、approval 和 policy 决定 Task 完成

AgentEvalRunner
  使用数据集、轨迹和多次 trial 评估 Agent 版本，不参与单次任务事实所有权
```

## 当前问题

### `source` 被当成了标准本身

当前 `SuccessCriterion.source` 支持：

```text
user_explicit | contract_derived | model_derived
```

但 `source` 只回答“标准从哪里来”，不能回答：

- 什么证据可以让它通过；
- 使用哪个 evaluator；
- evaluator 需要哪些输入；
- 判定失败后如何修复；
- 是否验证最终环境状态。

来源、义务和判定必须分离：

| 概念 | 回答的问题 |
| --- | --- |
| `source` | 谁提出或生成了标准 |
| `required` | Goal 完成是否必须满足 |
| `mutability` | 哪个受控流程可以修订标准 |
| `acceptance` | 什么可观察事实构成成功 |
| `evaluator_ref` | 谁以哪个版本执行判定 |
| `CriterionResult` | 本次判定的状态、证据与理由 |

### TaskAnalyzer 没有逐条保留 criterion 来源

当前 `GoalDraft.success_criteria` 是 `list[str]`。TaskAnalyzer 可以根据语义自行生成内容，但 Compiler 使用“列表是否非空”判断它是否为 `user_explicit`。因此模型推导的标准可能被错误标记为用户明确要求。

错误推断是：

```text
goal.success_criteria 非空
  -> user_explicit
```

正确做法是 TaskAnalyzer 对每条 criterion 显式输出来源和依据，Compiler 只验证、映射和固化，不重新猜来源。

### 通用 fallback 没有业务成功语义

当前缺少 criteria 时生成：

```python
f"完成目标：{goal.description}"
```

该描述只是重复 Goal，没有形成独立、可验证的断言。普通结果的确定性检查又近似为“存在非空 answer 或 tool result”，因此无法区分：

```text
产生了输出
```

与：

```text
成功完成了用户目标
```

这个 fallback 必须删除。Compiler 只能生成结构性 baseline；缺失的业务语义标准必须来自用户、模型推导或澄清。

### `acceptance_contract` 是裸字符串而非可执行契约

当前常见值包括：

```text
UserVisibleResult
VerifiedAnswer
MutationReceipt
```

除 Mutation 分支外，Verifier 主要根据 `EvidencePolicy` 和是否存在结果进行判断，并没有通过统一 dispatch 将 acceptance 类型绑定到独立 evaluator。新增字符串不会受到穷尽检查，也不能保证存在执行实现。

### Mutation 只验证“像 receipt”

当前 `_looks_like_receipt()` 通过检查 `note_id`、`run_id`、`updated` 等字段推测 mutation 成功。这只能证明 provider 返回了某类结果，不能证明：

- operation 与 `MutationIntent` 一致；
- target 与 `ResourceSelector` 一致；
- approval 对应本次 invocation；
- 外部状态确实发生了预期变化；
- retry 没有产生重复副作用。

Mutation 必须验证 typed receipt，并在 provider 支持时执行 postcondition read-back。不能再通过任意字典 key 推测成功。

### Runtime acceptance 与 Agent eval 混在同一语义空间

当前 `VerificationReport` 用于阻塞或完成当前 Goal，这是 runtime acceptance。Agent 版本是否善于选工具、是否绕路、是否回归、成本是否可接受，则属于 quality eval。

两者共享 trace 和 grader 基础设施是合理的，但不能共享事实所有权：

```text
Runtime acceptance
  对一次真实运行作完成判定
  结果进入 TaskRuntimeProjection

Agent quality eval
  对 Agent/Prompt/Model/Tool 版本作统计评估
  结果进入 EvalRun，不写回 TaskRuntimeProjection
```

## 设计目标

### 必须实现

- 每条 criterion 都有可靠 provenance；
- 每条 required criterion 都有可执行 acceptance；
- Compiler 生成的标准完全由结构化输入确定；
- 开放语义由独立 semantic evaluator 判断；
- Mutation 以真实 outcome 而非自然语言声明完成；
- `inconclusive` 产生可执行的 remediation，而不是被当成通过；
- Goal 与 Task 的完成判定是确定性聚合；
- evaluator 身份、版本、输入证据和判定理由可审计；
- 支持离线回归和在线抽样评估，但不污染 runtime aggregate。

### 不在本轮设计中

- 不实现任意布尔表达式或规则 DSL；
- 不允许运行时动态加载未知 evaluator 代码；
- 不要求固定工具调用顺序作为任务成功条件；
- 不让模型直接修改已固化 TaskContract；
- 不为所有质量维度设计复杂权重系统；
- 不把人类评审结果伪装成确定性系统事实；
- 不把 Eval dataset、trial 或聚合分数保存进 TaskContract。

## 核心不变量

### Criterion 不变量

1. `criterion_id` 在一个 TaskContract revision 内唯一且稳定；
2. `source=user_explicit` 必须携带至少一个用户消息引用；
3. `source=model_derived` 必须携带生成它的 analyzer 版本；
4. `source=contract_derived` 必须携带明确 derivation rule；
5. `required=True` 的 criterion 必须拥有非空、受支持的 `AcceptanceSpec`；
6. 一个 `AcceptanceSpec.kind` 必须恰好解析到一个 evaluator；
7. evaluator 未注册、版本不匹配或输入缺失时 fail closed，返回 `inconclusive`；
8. Planner、Executive 和 provider 不能直接新增、删除或修改 criterion；
9. 同一 TaskContract revision 内所有 criterion definition 不可变；
10. description 用于人类解释，判定不得只依赖 description 字符串。

### 完成不变量

1. required criterion 全部 `passed`，Goal 才能成为 `verified`；
2. 任一 required criterion 为 `failed` 或 `inconclusive`，Goal 不得进入 `verified`；
3. Mutation Goal 没有通过 `MutationOutcomeAcceptance` 时不得完成；
4. 有待审批 invocation 时 Task 不得完成；
5. `degraded` 不能由 Agent 自行选择，必须由用户或显式 policy decision 接受；
6. optional criterion 失败不阻塞完成，但必须保留在 VerificationReport；
7. CompletionVerifier 不重新执行语义判断，只聚合已经提交的 Goal `VerificationReport` 事实。

## 目标领域模型

### CriterionDraft

TaskAnalyzer 输出逐条结构化 draft：

```python
class CriterionDraft(BaseModel):
    description: str
    required: bool = True
    provenance: UserCriterionProvenance | ModelCriterionProvenance
    acceptance: CriterionAcceptanceDraft
```

Analyzer 使用的 draft acceptance 同样是封闭联合类型：

```python
CriterionAcceptanceDraft = Annotated[
    EvidenceCoverageDraft
    | ArtifactConformanceDraft
    | SemanticRubricDraft,
    Field(discriminator="kind"),
]
```

三个 draft 只包含 Analyzer 能从用户语义中得到的字段：

```python
class EvidenceCoverageDraft(BaseModel):
    kind: Literal["evidence_coverage"]
    minimum_source_count: int
    citation_required: bool
    freshness_required: bool
    source_authority: Literal["any", "primary", "official"]


class ArtifactConformanceDraft(BaseModel):
    kind: Literal["artifact_conformance"]
    media_type: str
    schema_ref: str | None = None


class SemanticRubricDraft(BaseModel):
    kind: Literal["semantic_rubric"]
    rubric: str
    subject: Literal["response", "artifact", "evidence_set"]
```

TaskAnalyzer 可以把“至少两个官方来源”输出成 `EvidenceCoverageDraft`，把“输出 Markdown”输出成 `ArtifactConformanceDraft`，把“说明关键调用链”输出成 `SemanticRubricDraft`。它不能生成 `ResultPresenceAcceptance` 或 `MutationOutcomeAcceptance`，因为这两类运行时底线归 Compiler 所有。

约束：

- `provenance.kind=user_explicit` 必须能回指用户消息；
- `provenance.kind=model_derived` 必须携带 analyzer model/prompt version；
- TaskAnalyzer 不得输出 `contract_derived`；
- 确定性要求必须输出结构化 draft，不能只埋在 description 中；
- 一个 draft 只表达一个可独立判断的维度；
- “准确、完整、优秀”这类无独立 rubric 的形容词不能直接成为 criterion。

### SuccessCriterion

固化后的定义：

```python
class SuccessCriterion(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    criterion_id: str
    description: str
    required: bool
    provenance: CriterionProvenance
    acceptance: AcceptanceSpec

    @property
    def source(self) -> CriterionSource:
        return self.provenance.kind

    @property
    def revision_authority(self) -> CriterionRevisionAuthority:
        return revision_authority_for(self.provenance.kind)
```

`source` 与修改权限都能从 provenance 唯一推导，因此不再作为可写字段重复保存。需要查询来源的调用者使用只读 property；需要保护 criterion 的 validator 使用 `revision_authority`。这延续“一个事实只有一个权威所有者”的项目规范。

`evidence_policy` 不再作为所有 criterion 的通用旁路字段。证据覆盖本身就是一条可执行 criterion，进入 `EvidenceCoverageAcceptance`。这样 Verifier 不需要同时解释 acceptance string 和额外 policy。

### CriterionProvenance

```python
class UserCriterionProvenance(BaseModel):
    kind: Literal["user_explicit"]
    message_refs: tuple[str, ...]


class ModelCriterionProvenance(BaseModel):
    kind: Literal["model_derived"]
    analyzer_id: str
    analyzer_version: str
    prompt_version: str


class ContractCriterionProvenance(BaseModel):
    kind: Literal["contract_derived"]
    rule_id: Literal[
        "response_presence_v1",
        "evidence_coverage_v1",
        "artifact_conformance_v1",
        "mutation_outcome_v1",
    ]
    input_revision: int


CriterionProvenance = Annotated[
    UserCriterionProvenance
    | ModelCriterionProvenance
    | ContractCriterionProvenance,
    Field(discriminator="kind"),
]

CriterionRevisionAuthority = Literal[
    "user_only",
    "compiler_only",
    "analyzer_only",
]
```

这里不使用一个包含大量 optional 字段的 provenance 对象，避免无效状态组合。

### AcceptanceSpec

本轮只支持五种封闭 acceptance，不建立任意扩展 DSL：

```python
AcceptanceSpec = Annotated[
    ResultPresenceAcceptance
    | EvidenceCoverageAcceptance
    | ArtifactConformanceAcceptance
    | MutationOutcomeAcceptance
    | SemanticRubricAcceptance,
    Field(discriminator="kind"),
]
```

#### ResultPresenceAcceptance

```python
class ResultPresenceAcceptance(BaseModel):
    kind: Literal["result_presence"]
    result_kind: Literal["response", "artifact"]
    non_empty: bool = True
```

只验证结果存在、类型正确和可读取，不判断开放语义质量。

#### EvidenceCoverageAcceptance

```python
class EvidenceCoverageAcceptance(BaseModel):
    kind: Literal["evidence_coverage"]
    minimum_source_count: int
    citation_required: bool
    freshness_required: bool
    source_authority: Literal["any", "primary", "official"] = "any"
```

来源数量、引用存在、freshness 和已有 Evidence metadata 中的来源权威级别可以确定验证。矛盾检查是独立的开放语义 criterion，使用 `SemanticRubricAcceptance(subject="evidence_set")`，不得隐藏在 EvidenceCoverageEvaluator 内部。

#### ArtifactConformanceAcceptance

```python
class ArtifactConformanceAcceptance(BaseModel):
    kind: Literal["artifact_conformance"]
    media_type: str
    schema_ref: str | None = None
    must_be_readable: bool = True
    must_be_persisted: bool = True
```

如果用户没有指定 schema，Compiler 只能要求 Artifact 存在、可读、类型正确，不能虚构内容结构。

#### MutationOutcomeAcceptance

```python
class MutationOutcomeAcceptance(BaseModel):
    kind: Literal["mutation_outcome"]
    operations: tuple[str, ...]
    selector: ResourceSelector
    confirmation_required: bool
    receipt_required: bool = True
    postcondition: PostconditionSpec
```

`PostconditionSpec` 只表达可读取的最终状态断言，例如：

```text
resource_exists
resource_absent
field_equals
revision_changed
provider_confirmed
```

若 provider 无法 read-back，只能返回 `inconclusive` 或由明确 policy 接受较弱的 provider confirmation，不能自动降级为成功。

#### SemanticRubricAcceptance

```python
class SemanticRubricAcceptance(BaseModel):
    kind: Literal["semantic_rubric"]
    rubric: str
    subject: Literal["response", "artifact", "evidence_set"]
    evaluator_profile: str
```

只用于 `user_explicit` 或 `model_derived` criterion。rubric 必须单维度、可判定，并允许 evaluator 返回 `inconclusive`。

### CriterionEvaluationRequest

Evaluator 不接收整个可变 checkpoint，只接收有界请求：

```python
class CriterionEvaluationRequest(BaseModel):
    task_ref: TaskRef
    goal_ref: GoalRef
    criterion: SuccessCriterion
    result_refs: tuple[ArtifactRef, ...]
    evidence_refs: tuple[EvidenceRef, ...]
    mutation_receipts: tuple[MutationReceipt, ...]
    runtime_snapshot_ref: RuntimeSnapshotRef
```

模型 evaluator 使用的文本或证据内容由 ContextProjection 在调用边界临时物化，不写入 request 或 checkpoint。

### CriterionResult

```python
class CriterionResult(BaseModel):
    criterion_id: str
    status: Literal["passed", "failed", "inconclusive"]
    assertion_results: tuple[AssertionResult, ...]
    evidence_refs: tuple[str, ...]
    evaluator_ref: EvaluatorRef
    reason_code: str
    confidence: float | None = None
```

确定性 evaluator 不伪造 confidence；semantic evaluator 必须返回 confidence 或校准档位。`reason_code` 使用封闭 taxonomy，用户可见说明由 presentation 层生成。

## 标准生成流程

### 第一步：TaskAnalyzer 提取用户显式标准

只有能够定位到用户消息的要求才能标记为 `user_explicit`。

例如用户说：

```text
根据官方资料分析当前架构，输出 Markdown，并说明模块职责和关键调用链。
```

TaskAnalyzer 输出：

```text
user_explicit:
  - 使用官方资料
  - 输出 Markdown Artifact
  - 说明模块职责
  - 说明关键调用链
```

TaskAnalyzer 可以规范化表述，但不能扩张义务。例如“说明关键调用链”不能被改成“给出所有函数级调用关系”。

### 第二步：TaskAnalyzer 补充模型语义标准

当 Goal 是开放语义结果且用户没有给出足够可判定维度时，TaskAnalyzer 生成最小充分的 `model_derived` criteria。

例如：

```text
Goal：解释缓存穿透

model_derived:
  - 说明缓存穿透的定义
  - 说明请求绕过缓存并落到后端的成因
  - 给出至少一种与成因对应的治理方式
```

生成约束：

- 只拆出完成 Goal 所必需的维度；
- 不引入用户未要求的格式、篇幅或研究范围；
- 无法可靠形成 rubric 时输出 clarification；
- 不生成工具、provider、执行路径或并行策略；
- 每条 criterion 独立，避免一个 evaluator 同时判断多个模糊维度。

### 第三步：GoalGraphCompiler 生成 contract baseline

Compiler 只执行封闭映射：

| 输入条件 | 生成的 `contract_derived` criterion |
| --- | --- |
| `result_contract=response` | `ResultPresenceAcceptance(response)` |
| `result_contract=artifact` | `ArtifactConformanceAcceptance` |
| 资源要求 `search/verify` 且没有更强的等价标准 | 最低 `EvidenceCoverageAcceptance` |
| 存在 canonical mutation operation | `MutationOutcomeAcceptance` |

Compiler 不再生成：

```text
完成目标：{goal.description}
```

也不再把所有非空 `goal.success_criteria` 视为 `user_explicit`。

### 第四步：Compiler 校验覆盖而非补写语义

每个 Goal 必须满足：

```text
至少一个 contract baseline

开放语义 Goal：
  至少一个 user_explicit 或 model_derived semantic criterion
```

如果一个 `response` Goal 只有 `ResultPresenceAcceptance`，说明系统只知道“要返回文字”，不知道什么内容算成功。此时 Compiler 必须拒绝编译并要求 TaskAnalyzer 重新分析或澄清，不能用通用 fallback 掩盖缺失。

## 来源与修改权限

`source` 不直接决定是否 required，也不直接决定 evaluator，但 provenance 决定修改权限和冲突解释。

| 来源 | 当前 revision 内 | 跨 revision | 冲突规则 |
| --- | --- | --- | --- |
| `user_explicit` | 不可变 | 仅用户 steering 可修订 | 不能被模型弱化或删除 |
| `contract_derived` | 不可变 | Compiler 根据新 contract 重建 | 安全和真实性底线不可豁免 |
| `model_derived` | 不可变 | Analyzer proposal 可修订 | 不得扩大用户目标或覆盖用户标准 |

目标模型删除持久化的 `mutability`，改为从 provenance 派生 revision authority：

```text
user_explicit    -> user_only
contract_derived -> compiler_only
model_derived    -> analyzer_only
```

所有 revision 仍必须经过 proposal、Validator 和 revision CAS。Goal decomposition 产生的 model criterion 也属于 `analyzer_only` 受控修订，Planner 不能直接写入。

## Evaluator 架构

### 端口

```python
class CriterionEvaluator(Protocol):
    @property
    def ref(self) -> EvaluatorRef: ...

    def evaluate(
        self,
        request: CriterionEvaluationRequest,
    ) -> CriterionResult: ...
```

### 固定映射

```text
result_presence      -> ResultPresenceEvaluator
evidence_coverage    -> EvidenceCoverageEvaluator
artifact_conformance -> ArtifactConformanceEvaluator
mutation_outcome     -> MutationOutcomeEvaluator
semantic_rubric      -> SemanticRubricEvaluator
```

使用封闭 `match` 或构造期 registry 均可，但必须满足：

- 启动时校验所有 AcceptanceSpec kind 有且只有一个 evaluator；
- evaluator 版本固定进入结果；
- 未知 kind 不回退 generic evaluator；
- evaluator 异常返回 `inconclusive/evaluator_unavailable`；
- semantic evaluator 不能把确定性失败升级为通过。

### 确定性与语义组合

每条 criterion 尽量只绑定一个 evaluator。需要同时做结构和语义判断时，拆为两条 criterion，而不是在一个超级 evaluator 中隐藏多个门槛。

例如研究回答：

```text
criterion A contract_derived / EvidenceCoverageEvaluator
  检查引用、来源数量、新鲜度

criterion B model_derived / SemanticRubricEvaluator
  检查回答是否解释核心机制

criterion C user_explicit / SemanticRubricEvaluator
  检查是否比较用户指定的两个方案
```

### Semantic evaluator 隔离

Semantic evaluator 必须：

- 使用与执行模型隔离的调用上下文；
- 只接收 Goal、单条 rubric、结果和允许的 evidence；
- 不接收 Planner 的自我评价或“任务已经完成”声明；
- 不推断缺失证据；
- 对证据不足返回 `inconclusive`；
- 输出结构化 assertion result；
- 记录 model、prompt、rubric 和 calibration profile 版本。

运行时默认单次判定以控制成本。多 judge、重复采样和人工校准属于 EvalRunner；只有高风险 profile 才可在 runtime 使用双 evaluator 或人工 review。

## Goal 与 Task 完成判定

### GoalVerifier

GoalVerifier 只负责：

1. 读取 Goal 引用的 criterion definitions；
2. 为每条 criterion 构造有界 evaluation request；
3. 调用对应 evaluator；
4. 保存完整 CriterionResult；
5. 根据 required criteria 确定 Goal `VerificationReport.status`；
6. 为失败或不确定项生成 VerificationGap。

聚合规则：

```text
required 全部 passed
  -> VerificationReport.passed

任一 required failed
  -> VerificationReport.failed

没有 failed，但至少一个 required inconclusive
  -> VerificationReport.inconclusive
```

`failed` 表示已有充分证据证明不满足；`inconclusive` 表示缺少证据、evaluator 不可用或环境无法验证。两者的 remediation 不同。

### VerificationGap

标准 reason taxonomy 至少包括：

```text
result_missing
evidence_missing
evidence_stale
semantic_mismatch
artifact_unreadable
artifact_schema_mismatch
approval_missing
receipt_missing
receipt_scope_mismatch
postcondition_failed
postcondition_unverifiable
evaluator_unavailable
```

每类 gap 映射到有限 remediation：

```text
acquire_evidence
regenerate_result
repair_artifact
request_approval
retry_mutation
read_back_state
request_user_clarification
escalate_human_review
```

Executive 只能选择 remediation class，不能更改失败标准。

### CompletionVerifier

CompletionVerifier 不再重新读取 answer、tool result 或自然语言 criterion。它只读取：

```text
TaskContract revision
GoalRuntimeState.verification
pending approvals
terminal Goal status
policy decisions
```

Task 完成规则：

```text
所有 required Goal verified
AND 所有 required criterion passed
AND 没有 pending approval
AND 没有未决 critical gap
  -> completed
```

`degraded` 必须有显式 `DegradationAcceptanceDecision`，记录接受者、被豁免 criterion、理由和 task revision。模型不能仅因预算耗尽自动降级成功。

```python
class DegradationAcceptanceDecision(BaseModel):
    task_ref: TaskRef
    waived_criterion_ids: tuple[str, ...]
    authority: Literal["user", "policy"]
    reason: str
    decided_at: datetime
```

该 Decision 是一次已授权事实，不修改原 criterion，也不能把 Mutation 安全底线加入 waived 集合。

## Mutation outcome 验证

### Typed MutationReceipt

```python
class MutationReceipt(BaseModel):
    receipt_id: str
    invocation_id: str
    provider_id: str
    operation: str
    selector: ResourceSelector
    idempotency_key: str | None
    provider_revision: str | None
    committed_at: datetime
    result_ref: str | None
```

Receipt 必须由 provider adapter 根据 provider 原始响应构造，不能由 LLM 生成。

### Postcondition verification

MutationOutcomeEvaluator 执行：

```text
1. confirmation 与 invocation 匹配
2. receipt 与 invocation、operation、selector 匹配
3. idempotency 约束满足
4. 调用只读 probe 获取最终状态
5. 对照 PostconditionSpec
6. 生成 assertion results
```

示例：

```text
删除资源
  -> receipt.operation == delete
  -> receipt.selector == requested selector
  -> read-back 返回 resource_absent

更新字段
  -> receipt.operation == update
  -> read-back.field == expected value
  -> revision 与执行前不同
```

没有 read-back 能力的 provider 必须在 Capability 中显式声明 verification strength：

```text
postcondition | provider_confirmation | unverifiable
```

高风险 mutation 不接受 `unverifiable`。低风险 provider confirmation 是否可接受由 policy 决定，不由 Evaluator 猜测。

## Runtime acceptance 与 Agent quality eval

### Runtime acceptance

目标是回答：

```text
当前这一次任务现在是否完成？
```

特征：

- 使用当前 TaskContract revision；
- 结果进入 TaskRuntimeProjection；
- required criterion 是硬门槛；
- 不运行多次 trial；
- 失败产生 remediation；
- 延迟和成本必须适合在线路径。

### Agent quality eval

目标是回答：

```text
这个 Agent/Model/Prompt/Tool 版本整体表现如何？
```

至少分为：

```text
Outcome eval
  最终结果和环境状态是否正确

Final response eval
  回答是否准确、相关、清晰、忠实于证据

Single-step eval
  工具选择和参数是否正确

Trajectory eval
  是否存在越权、无效循环、遗漏必要审批或明显浪费

Operational eval
  延迟、成本、重试、provider failure 和恢复能力
```

EvalRun 使用独立模型：

```python
class EvalRunDefinition(BaseModel):
    suite_id: str
    agent_version: str
    model_config_ref: str
    prompt_versions: tuple[str, ...]
    trial_count: int


class EvalTrialResult(BaseModel):
    case_id: str
    trial_id: str
    grader_results: tuple[EvalGraderResult, ...]
    trace_ref: str
    outcome_ref: str | None
```

它引用运行 trace 和 artifacts，但不能修改 runtime VerificationReport。

### Grader 策略

遵守以下顺序：

1. 能用代码、schema、数据库状态、测试或静态分析验证时，不使用 LLM；
2. 开放语义使用单维度 rubric 的 model grader；
3. model grader 必须通过人工样本校准；
4. 高价值或高风险 case 使用人工抽检；
5. quality eval 多次 trial，regression eval 目标接近全通过；
6. 优先评价 outcome，不强制唯一正确轨迹；
7. trajectory grader 关注非法动作、必要动作、成本和恢复，不匹配完整固定序列。

## 模块职责与代码布局

### `planning/task_analyzer.py`

保留：

- 用户目标理解；
- GoalDraft；
- user/model criterion draft；
- clarification。

删除：

- `success_criteria: list[str]`；
- 依赖 Compiler 猜测 criterion 来源的输出。

### `planning/task_compiler.py`

保留：

- GoalGraphDefinition 编译；
- dependency 编译；
- contract baseline 编译；
- provenance 与 acceptance 完整性校验。

删除：

- `完成目标：...` fallback；
- `bool(goal.success_criteria)` 到 `user_explicit` 的推断；
- acceptance 裸字符串拼装；
- 基于任意 operation 文本的本地 mutation taxonomy。

### `runtime/contracts/task.py`

增加：

- `CriterionDraft` 对应的正式 provenance 值对象；
- discriminated `AcceptanceSpec`；
- typed evaluator ref；
- typed mutation receipt/postcondition；
- 完整 `CriterionResult`。

所有 definition/value object 保持 frozen。

### `verification/`

将当前 `planning/verification.py` 的职责迁出 Planning，形成高内聚模块：

```text
personal_agent/verification/
  evaluators.py       固定 AcceptanceSpec evaluator
  goal.py             GoalVerifier
  completion.py       CompletionVerifier
  semantic.py         SemanticRubricEvaluator adapter
  mutation.py         MutationOutcomeEvaluator
```

不保留 `planning.verification` 兼容导出。

### Orchestration

Orchestration 只负责：

- 收集 result/evidence/receipt refs；
- 调用 GoalVerifier；
- 接收 VerificationGap；
- 让 Executive 选择 remediation；
- 调用 CompletionVerifier；
- 持久化事件与 projection。

不得在 `_executive.py` 内重新实现 criterion 判定或 receipt 推测。

### Eval

新增独立包：

```text
personal_agent/evals/
  suites.py
  runner.py
  graders.py
  reports.py
```

第一阶段只需要支持本地 fixture suite 和现有 execution trace，不接入外部平台。

## 端到端示例

用户请求：

```text
根据两个官方来源分析当前 Agent 架构，输出 Markdown 文档，
必须说明模块职责和关键调用链。
```

### TaskAnalyzer

```text
user_explicit:
  C1 使用官方来源
  C2 至少两个来源
  C3 输出 Markdown
  C4 说明模块职责
  C5 说明关键调用链

model_derived:
  C6 说明关键架构取舍
```

### Compiler

```text
contract_derived:
  C7 Artifact 存在、可读取、media type 为 text/markdown
  C8 evidence source count >= 2 且 citation_required
```

注意：C2 和 C8 语义重复时不能生成两条不同事实。Compiler 应把用户标准映射成 `EvidenceCoverageAcceptance(minimum_source_count=2)` 并保留 `user_explicit` provenance，而不是再追加一个 contract duplicate。Contract baseline 只补缺失不变量。

### Execution

Planner 的 step 通过 `supports_criterion_ids` 表示它计划覆盖哪些 criterion，但该声明不是完成证据。

### Verification

```text
C1 EvidenceCoverageEvaluator -> passed
C2 EvidenceCoverageEvaluator -> passed
C3 ArtifactConformanceEvaluator -> passed
C4 SemanticRubricEvaluator -> passed
C5 SemanticRubricEvaluator -> inconclusive
C6 SemanticRubricEvaluator -> passed
C7 ArtifactConformanceEvaluator -> passed
```

因为 C5 required 且 inconclusive：

```text
Goal status != verified
VerificationGap = semantic_mismatch/key_call_chain
remediation = regenerate_result
```

Agent 修订 Artifact 后重新验证 C5；所有 required criteria passed 后 Goal 才 verified。

## 去重规则

Compiler 不能为了来源不同而保留语义重复 criterion。去重依据是规范化 acceptance，而不是 description 文本。

```text
用户要求：至少两个来源
EvidenceRequirement.minimum_source_count = 2

结果：一条 user_explicit EvidenceCoverageAcceptance(2)
而不是 user_explicit + contract_derived 两条重复标准
```

优先级：

```text
user_explicit > model_derived > contract_derived
```

这里的优先级只决定等价标准保留哪个 provenance。安全 policy 不是 criterion source，不参与该覆盖关系；例如 mutation confirmation 不能被用户 criterion 删除。

## 实施阶段

### Phase 1：修正 criterion ownership 和 provenance

改动：

- `GoalDraft.success_criteria` 改为 `criteria: list[CriterionDraft]`；
- TaskAnalyzer prompt 明确 user/model 来源规则；
- 添加 message refs 和 analyzer refs；
- Compiler 删除非空列表即 user explicit 的判断；
- 删除通用 fallback；
- Compiler 对开放语义 Goal 缺少 semantic criterion 时 fail closed。

验收：

- 模型推导标准不会被标成 user explicit；
- 每条 user explicit criterion 可回指用户消息；
- 简单开放问题至少有一个 semantic criterion；
- Analyzer 无法定义标准时进入 clarify。

### Phase 2：类型化 AcceptanceSpec 和 evaluator

改动：

- 用 discriminated union 替换 `acceptance_contract: str`；
- 把 `EvidencePolicy` 转化为 `EvidenceCoverageAcceptance`；
- 实现 result、evidence、artifact 三个 deterministic evaluator；
- 重写 GoalVerifier 为逐 criterion dispatch；
- CriterionResult 记录 evaluator ref 和 assertions。

验收：

- 每种 acceptance 都有唯一 evaluator；
- 未注册类型无法构造或启动；
- evaluator 异常不会误判通过；
- 普通非空但不相关回答不能仅凭 presence 完成开放语义 Goal。

### Phase 3：独立语义验证

改动：

- 实现 SemanticRubricEvaluator；
- 建立有界 verification ContextProjection；
- 增加 rubric prompt/version；
- 保存 confidence、reason code 和 calibration profile；
- 建立最小人工标注 fixture 校准集。

验收：

- 执行模型声明“已完成”不会影响 grader；
- 缺证据返回 inconclusive；
- 单个 rubric 不同时评价多个独立维度；
- 人工 fixture 上的 false-pass 达到项目设定门槛。

### Phase 4：Mutation outcome verification

改动：

- 所有 mutation provider 返回 typed MutationReceipt；
- 删除 `_looks_like_receipt()`；
- Capability 声明 verification strength；
- 实现 postcondition probe 和 MutationOutcomeEvaluator；
- approval、receipt、selector、operation、idempotency 全链关联。

验收：

- 只有 `updated=True` 的字典不能通过；
- receipt target 或 operation 不一致时 failed；
- provider 声称成功但 read-back 未变化时 failed；
- 无法 read-back 的高风险 mutation 不得 verified；
- retry 不产生重复副作用。

### Phase 5：Completion 与 degraded 语义收敛

改动：

- CompletionVerifier 只聚合 verification facts；
- 增加显式 DegradationAcceptanceDecision；
- `failed` 与 `inconclusive` 分别映射 remediation；
- 删除 orchestration 内重复完成判断。

验收：

- required criterion 未通过时 Task 无法完成；
- 预算耗尽不会自动变成 degraded success；
- user/policy 接受降级可完整审计；
- replay 产生相同 CompletionReport。

### Phase 6：Agent quality eval

改动：

- 建立 outcome、final response、single-step、trajectory fixture suite；
- 支持多次 trial 和按 grader 聚合；
- 记录 model/prompt/tool/evaluator 版本；
- 将 production failure 转成 regression case；
- 增加人工抽检和 model grader calibration 工作流。

验收：

- 新版本能与基线比较成功率、成本和延迟；
- regression suite 接近全通过；
- trajectory eval 不强制唯一工具顺序；
- grader failure 可与 agent failure 区分；
- EvalRun 不修改任何 TaskRuntimeProjection。

## 测试设计

### 静态边界测试

- 禁止 `acceptance_contract: str` 回归；
- 禁止 `完成目标：` fallback 回归；
- 禁止 `_looks_like_receipt` 或通过任意 dict key 判断 mutation；
- 禁止 Compiler 通过 criteria 非空判断 `user_explicit`；
- 禁止 Verification 重新放回 Planning 模块；
- 禁止 runtime checkpoint 保存 EvalRun。

### 单元测试

- 每个 AcceptanceSpec 的构造不变量；
- provenance discriminator 与必填引用；
- Compiler baseline 映射；
- equivalent criterion 去重；
- evaluator exception -> inconclusive；
- Goal/Task 聚合 truth table；
- degraded acceptance authority。

### 集成测试

- 普通 response：presence 通过、semantic failed，Goal 不完成；
- evidence response：来源数量不足，生成 acquire evidence gap；
- artifact：文件存在但 schema 错误，Goal 不完成；
- mutation：receipt 存在但 postcondition 失败，Goal 不完成；
- steering：用户修订 criterion 后产生新 Task revision，旧 verification 不可复用；
- decomposition：model-derived child criterion 不改变 parent user criterion；
- replay：相同 definitions + events 得到相同 completion。

### Eval fixtures

至少建立四组：

```text
response_semantics
evidence_grounding
artifact_conformance
mutation_outcome
```

每组同时包含：

- 明确成功 case；
- 明确失败 case；
- 证据不足的 inconclusive case；
- 容易欺骗朴素 grader 的 adversarial case；
- 多种合法执行路径得到同一 outcome 的 case。

## 删除清单

落地完成后以下行为必须不存在：

- `goal.success_criteria or [f"完成目标：..."]`；
- 非空 criteria 自动标记 `user_explicit`；
- `SuccessCriterion.acceptance_contract: str`；
- GoalVerifier 内部通过大段 `if acceptance_contract == ...` 拼装隐式规则；
- `_looks_like_receipt(dict)`；
- 非空 answer 自动代表开放语义 Goal 成功；
- semantic evaluator 缺失时保留确定性 false-pass；
- CompletionVerifier 重新检查 answer/tool_results；
- Agent 自行选择 degraded success；
- EvalRun 与 TaskRuntimeProjection 双写状态。

## 落地后的完成定义

本设计只有在以下条件全部满足时才算完成：

1. criteria provenance 从 TaskAnalyzer 到 TaskContract 全链可靠；
2. contract baseline 全部来自封闭 derivation rules；
3. 每条 required criterion 有类型化 acceptance 和唯一 evaluator；
4. 开放语义没有 generic fallback；
5. Mutation 以 typed receipt 和 postcondition 验证；
6. Goal 与 Task 完成规则只有一个权威实现；
7. runtime acceptance 与 agent eval 使用独立 aggregate；
8. 静态、单元、集成和 eval fixture 测试全部通过；
9. `core-architecture-current-state.md` 更新为落地后的当前事实；
10. 删除所有旧实现和兼容导出。

## 行业实践依据

- [OpenAI Agents SDK](https://openai.github.io/openai-agents-python/)：以 Agent、Tool、Handoff、Guardrail、Session 和 Tracing 组成轻量运行时，output guardrail 承担在线输出校验；
- [OpenAI Evals](https://developers.openai.com/api/docs/guides/evals)：将 testing criteria 与具体 grader、dataset 和 ground truth 绑定；
- [Anthropic: Demystifying evals for AI agents](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents)：区分 transcript 与 outcome，组合 code/model/human grader，强调确定性 outcome verification、模型 grader 校准和多 trial；
- [LangSmith Agent Evaluation](https://docs.langchain.com/langsmith/evaluation-approaches)：区分 final response、single step 和 trajectory evaluation，并说明固定轨迹匹配的脆弱性；
- [Google Agents CLI Evaluation](https://google.github.io/agents-cli/guide/evaluation/)：分别评估 final response quality、tool use quality、trajectory、hallucination、grounding 和 safety。

这些资料用于校验设计方向，不直接决定本项目领域模型。本项目保留一项更强的运行时能力：SuccessCriterion 的来源、修改权限、Goal 绑定和完成门禁都是 TaskContract 的正式组成部分。
