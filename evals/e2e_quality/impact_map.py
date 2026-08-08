"""Change-to-live-evidence routing for day-to-day E2E validation.

The release catalog answers "which capability does this test prove".  This
module answers a different question: **given a diff, which live cases must be
re-run before the change has any support at all**.

The two are deliberately separate.  ``evidence_catalog`` is organised by
assertion focus and owns release eligibility; this map is organised by
production code location and owns nothing about release qualification.  A
selection produced here never upgrades evidence trust: it only narrows what is
worth spending a live run on while a change is still being made.

Fail closed.  A changed path that matches no rule yields
``full_matrix_required``, never an empty selection.  Silently returning "no
live needed" for an unrecognised path is the one failure mode this module
exists to prevent, because it would let an unsupported change look validated.

Two things this map structurally cannot see, both of which still require the
periodic full matrix:

1. prompt wording changes whose blast radius is a model behaviour shift rather
   than a code path (a tool ``description`` edit moves the model input
   distribution and changes ``capability_revision``, but which case regresses
   is not derivable from the diff);
2. provider-side model changes, where no file changes at all and this map
   correctly returns an empty selection for a link that may already be broken.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable

from evals.e2e_quality.evidence_catalog import EVIDENCE_CASES


class ImpactKind(str, Enum):
    CASES = "cases"
    FULL_MATRIX = "full_matrix"
    NO_IMPACT = "no_impact"


@dataclass(frozen=True, slots=True)
class ImpactRule:
    """One repo-path prefix and the live cases a change under it can break.

    ``rationale`` is required.  A rule whose reason cannot be stated is a guess,
    and a wrong guess here is worse than no rule: it produces a confident,
    too-small live selection.
    """

    path_prefix: str
    kind: ImpactKind
    case_ids: frozenset[str] = frozenset()
    rationale: str = ""

    def __post_init__(self) -> None:
        if not self.path_prefix:
            raise ValueError("impact rule requires a repo-relative path prefix")
        if not self.rationale:
            raise ValueError(f"impact rule {self.path_prefix!r} requires a rationale")
        if self.kind is ImpactKind.CASES and not self.case_ids:
            raise ValueError(
                f"impact rule {self.path_prefix!r} declares CASES but selects none; "
                "use FULL_MATRIX or NO_IMPACT explicitly"
            )
        if self.kind is not ImpactKind.CASES and self.case_ids:
            raise ValueError(
                f"impact rule {self.path_prefix!r} must not carry case_ids for {self.kind.value}"
            )


def _cases(path_prefix: str, rationale: str, *case_ids: str) -> ImpactRule:
    return ImpactRule(
        path_prefix=path_prefix,
        kind=ImpactKind.CASES,
        case_ids=frozenset(case_ids),
        rationale=rationale,
    )


def _full(path_prefix: str, rationale: str) -> ImpactRule:
    return ImpactRule(path_prefix=path_prefix, kind=ImpactKind.FULL_MATRIX, rationale=rationale)


def _none(path_prefix: str, rationale: str) -> ImpactRule:
    return ImpactRule(path_prefix=path_prefix, kind=ImpactKind.NO_IMPACT, rationale=rationale)


# Longest matching prefix wins, so a specific file may override its package.
IMPACT_RULES: tuple[ImpactRule, ...] = (
    # --- interaction loop: the widest blast radius in the repo -------------
    _full(
        "src/personal_agent/application/conversation/service.py",
        "Owns the turn loop, admission, budget and concurrency for every "
        "conversation-entry journey; a regression here is not confinable.",
    ),
    _cases(
        "src/personal_agent/application/conversation/models.py",
        "Wire contract for model output plus LoopBudgetPolicy; breaks typed "
        "parse for every loop case and the budget stop condition.",
        "E01", "E14", "E22", "E23", "L01", "L02", "L03", "L05", "L06",
    ),
    _cases(
        "src/personal_agent/application/conversation/review_admission.py",
        "Derives and freezes ReviewCriteria; only the review journey depends on it.",
        "L06",
    ),
    _cases(
        "src/personal_agent/application/conversation/observation_bounds.py",
        "Bounds how much of one observation enters the context and pages the "
        "offloaded remainder; only oversized-return journeys depend on it.",
        "E21",
    ),
    _cases(
        "src/personal_agent/application/conversation/verification_admission.py",
        "Admits verifier evidence refs for the runtime-owned verification path.",
        "L06",
    ),
    # --- capability projection: changes model input for every case ---------
    _full(
        "src/personal_agent/governance/registry.py",
        "Tool descriptions and schemas enter the prompt each turn and set "
        "capability_revision; also owns the concurrency-safety predicate.",
    ),
    _full(
        "src/personal_agent/governance/gateway.py",
        "Sole governed execution path: policy, scope, idempotency and audit.",
    ),
    _cases(
        "src/personal_agent/capabilities/contracts/interaction.py",
        "InteractionToolPort contract consumed by the loop's admission step.",
        "E01", "E19", "L01", "L02", "L05",
    ),
    _cases(
        "src/personal_agent/capabilities/contracts/verification.py",
        "Verification port contract for runtime-owned and answer-level verifiers.",
        "L06", "E20",
    ),
    _full(
        "src/personal_agent/capabilities/",
        "Capability resolution, admission and inventory decide what the model "
        "can see and select at all.",
    ),
    _full(
        "src/personal_agent/governance/",
        "Policy, guardrails, route and evidence admission are authorisation "
        "owners; every governed journey passes through them.",
    ),
    _cases(
        "src/personal_agent/application/conversation/",
        "Remaining conversation-loop package members.",
        "E01", "E14", "L01", "L02", "L03", "L05", "L06",
    ),
    # --- transport boundary: no case is independent of it ------------------
    _full(
        "src/personal_agent/infra/structured_model.py",
        "Sole OpenAI-compatible generation boundary; transport, retry owner "
        "and wall-clock deadline for every live case.",
    ),
    # --- specialists ------------------------------------------------------
    _cases(
        "src/personal_agent/agents/",
        "Child lifecycle, delegation grants, submission reservation and "
        "artifact index; only delegation journeys consume them.",
        "L04", "E17",
    ),
    # --- tools -------------------------------------------------------------
    _cases(
        "src/personal_agent/tools/interaction_verifier.py",
        "The verifier the runtime invokes before sending a reviewed answer.",
        "L06",
    ),
    _cases(
        "src/personal_agent/tools/mcp.py",
        "MCP discovery-to-mapping admission for every remote read.",
        "E16", "E18", "E19", "E21",
    ),
    _cases(
        "src/personal_agent/tools/mcp_capability.py",
        "MCP capability inventory: configuration vs discovery vs availability.",
        "E16", "E18", "E19", "E21",
    ),
    _full(
        "src/personal_agent/tools/base.py",
        "Tool governance metadata base; side_effects here drive both exposure "
        "and the concurrency predicate for all tools.",
    ),
    _cases(
        "src/personal_agent/tools/",
        "Individual tool implementations reachable from the model each turn.",
        "E01", "E02", "E12", "L01", "L02",
    ),
    # --- personal knowledge ------------------------------------------------
    _cases(
        "src/personal_agent/application/knowledge/answer_verifier.py",
        "Independent answer-level semantic assessment write path.",
        "E20",
    ),
    _cases(
        "src/personal_agent/application/knowledge/",
        "Canonical knowledge fact owner: claims, evidence, supersede/conflict.",
        "E02", "E08", "E10", "E12", "E20", "L01",
    ),
    _cases(
        "src/personal_agent/application/knowledge_lifecycle/",
        "Delete/restore commands, digests and receipt replay.",
        "E04", "E10", "E22",
    ),
    _cases(
        "src/personal_agent/application/capture/",
        "Multi-source ingestion into Artifact/Evidence.",
        "E03", "E09",
    ),
    _cases(
        "src/personal_agent/application/research/",
        "ResearchRun lifecycle, subscriptions and delivery.",
        "E05", "E13", "E24",
    ),
    _cases(
        "src/personal_agent/application/review/",
        "Review cards, digest subscription and scheduled delivery.",
        "E11", "E13",
    ),
    _cases(
        "src/personal_agent/application/investigation_project/",
        "Durable Project plan, budget ledger and completion gate.",
        "IP01", "E23", "E24",
    ),
    _cases(
        "src/personal_agent/domain/",
        "Project aggregate state machine and budget limits.",
        "IP01", "E23", "E24",
    ),
    _cases(
        "src/personal_agent/application/artifacts/",
        "Artifact write/read path behind ArtifactRef and digest checks.",
        "E03", "E09", "E20", "IP01",
    ),
    _cases(
        "src/personal_agent/application/extract/",
        "Structured extraction feeding evidence blocks.",
        "E09", "E12",
    ),
    _cases(
        "src/personal_agent/application/insight/",
        "Conflict, gap and backlink analysis bound to source claims.",
        "E12",
    ),
    _cases(
        "src/personal_agent/application/worker_queue.py",
        "Async worker queue behind research, delivery and project recovery.",
        "E05", "E13", "IP01", "E23", "E24",
    ),
    _cases(
        "src/personal_agent/application/",
        "Remaining Ask/RAG application helpers: chunking, rerank, entailment, "
        "evidence assembly and answer verification.",
        "E02", "E03", "E09", "E12",
    ),
    _cases(
        "src/personal_agent/planning/",
        "Query planning and memory admission ahead of retrieval.",
        "E02", "E12", "IP01", "E23",
    ),
    _cases(
        "src/personal_agent/runtime/",
        "Procedure runtime, scheduler, recovery and grants behind durable runs.",
        "E05", "E13", "IP01", "E23", "E24",
    ),
    _cases(
        "src/personal_agent/infra/a2a.py",
        "A2A protocol adapter for the real specialist.",
        "L04", "E17",
    ),
    _cases(
        "src/personal_agent/infra/mcp.py",
        "MCP client transport behind every remote read.",
        "E16", "E18", "E19", "E21",
    ),
    _full(
        "src/personal_agent/infra/runtime_llm.py",
        "Model client construction for the legacy runtime path.",
    ),
    _full(
        "src/personal_agent/infra/",
        "Remaining outbound adapters and package wiring at the infra boundary.",
    ),
    # --- legacy ask path: still the Ask/RAG entry -------------------------
    _cases(
        "src/personal_agent/orchestration/",
        "Legacy orchestration runtime still owns Ask/RAG compose and retrieval.",
        "E02", "E03", "E12",
    ),
    # --- entry boundary: every release case enters over HTTP ---------------
    _full(
        "src/personal_agent/adapters/web/",
        "The HTTP entry every release-eligible case is required to use.",
    ),
    _full(
        "src/personal_agent/api.py",
        "Application wiring for the web entry.",
    ),
    _full(
        "src/personal_agent/main.py",
        "Composition Root; selects adapters, transports and capability profile.",
    ),
    # --- prompt assets: model input distribution, blast radius unknowable --
    _full(
        "src/personal_agent/kernel/prompt_templates/",
        "Prompt wording changes the model input distribution; which case "
        "regresses is not derivable from the diff.",
    ),
    _full(
        "src/personal_agent/kernel/prompts.py",
        "Shared prompt assets; same unknowable blast radius as templates.",
    ),
    _full(
        "src/personal_agent/kernel/prompt_registry.py",
        "Prompt resolution; decides which wording each call receives.",
    ),
    _full(
        "src/personal_agent/orchestration/ask/prompts.py",
        "Ask-path prompt wording; overrides the orchestration package rule "
        "because model behaviour drift is not confinable to the Ask cases.",
    ),
    # --- persistence and config -------------------------------------------
    _full(
        "src/personal_agent/infra/storage/",
        "Canonical stores behind recovery, digest replay and scope isolation.",
    ),
    _full(
        "src/personal_agent/kernel/config",
        "Settings shape decides transports, capability profile and budgets.",
    ),
    _cases(
        "src/personal_agent/memory/",
        "Retrieval projections and short-term context assembly.",
        "E02", "E12", "L01",
    ),
    _cases(
        "src/personal_agent/execution/",
        "Invocation journal and outbox behind idempotent side effects.",
        "E04", "E10", "E13", "L03",
    ),
    _cases(
        "src/personal_agent/kernel/contracts/tool.py",
        "SideEffectType taxonomy drives exposure and concurrency safety.",
        "E19", "L02", "E14",
    ),
    _full(
        "src/personal_agent/kernel/",
        "Base layer shared by every package: models, projections, structured "
        "parse, observability and rate limiting.",
    ),
    _full(
        "src/personal_agent/__init__.py",
        "Root package definition.",
    ),
    # --- explicit no-impact: declared, not inferred ------------------------
    _none(
        "src/personal_agent/adapters/cli",
        "CLI adapter; release-eligible cases are required to enter over HTTP.",
    ),
    _none(
        "src/personal_agent/adapters/feishu",
        "Feishu adapter; release-eligible cases are required to enter over HTTP.",
    ),
    _none(
        "src/personal_agent/adapters/__init__.py",
        "Adapter package marker with no behaviour.",
    ),
    _none("src/personal_agent.egg-info", "Build metadata, not source."),
    _none(
        "evals/",
        "Offline golden-set harnesses; they measure quality distributions and "
        "do not change served behaviour.",
    ),
    # e2e_quality overrides the blanket evals/ rule: the harness IS the live run.
    _full(
        "evals/e2e_quality/conftest.py",
        "Collection, classification and live fixtures for every case.",
    ),
    _full(
        "evals/e2e_quality/trace_archive.py",
        "Archive writer whose output the release gate consumes.",
    ),
    _full(
        "evals/e2e_quality/investigation_harness.py",
        "Shared durable-project harness used across investigation cases.",
    ),
    _cases(
        "evals/e2e_quality/test_complex_loop_outcomes.py",
        "Assertions for the complex-loop journeys only.",
        "L01", "L02", "L03", "L04", "L05", "L06",
    ),
    _cases(
        "evals/e2e_quality/test_product_capability_outcomes.py",
        "Assertions for product and composite journeys.",
        "E01", "E02", "E03", "E04", "E05",
        "E08", "E09", "E10", "E11", "E12", "E13", "E14",
        "E20", "E22", "E23", "E24", "IP01",
    ),
    _cases(
        "evals/e2e_quality/test_release_user_outcomes.py",
        "External capability-profile assertions and shared live fixtures.",
        "E16", "E17", "E18", "E19", "E21",
    ),
    _none(
        "evals/e2e_quality/test_durable_investigation",
        "Scripted/frozen-port durable diagnostics; not live release evidence.",
    ),
    _none("docs/", "Documentation carries no production behaviour."),
    _none("tests/", "Unit and contract tests do not change production behaviour."),
    _none(
        "evals/e2e_quality/evidence_catalog.py",
        "Classification metadata; consistency is enforced at pytest collection.",
    ),
    _none(
        "evals/e2e_quality/release_gate.py",
        "Release projection reads archives; it cannot change live behaviour.",
    ),
    _none("evals/e2e_quality/impact_map.py", "This routing table itself."),
    _none("scripts/", "Developer utilities outside the served application."),
    _none("README.md", "Repository documentation."),
    _none("CLAUDE.md", "Agent working instructions."),
    _none("AGENTS.md", "Agent working instructions; identical to CLAUDE.md."),
    _none("pyproject.toml", "Dependency and tooling declaration; verified by Tier 1."),
)

_ALL_CASE_IDS = frozenset(case.case_id for case in EVIDENCE_CASES)
_LIVE_CASE_IDS = frozenset(
    case.case_id for case in EVIDENCE_CASES if case.real_model_required
)


@dataclass(frozen=True, slots=True)
class ImpactSelection:
    """What a diff requires before it has live support.

    ``full_matrix_required`` is not a severity label, it is a routing outcome:
    either a rule said so, or a path matched nothing.  Both mean this module
    declines to name a smaller safe subset.
    """

    case_ids: tuple[str, ...]
    full_matrix_required: bool
    unmapped_paths: tuple[str, ...]
    matched: tuple[tuple[str, str], ...]
    no_impact_paths: tuple[str, ...]

    @property
    def reasons(self) -> tuple[str, ...]:
        items: list[str] = []
        if self.unmapped_paths:
            items.append("unmapped_path")
        for path, prefix in self.matched:
            rule = _RULE_BY_PREFIX[prefix]
            if rule.kind is ImpactKind.FULL_MATRIX:
                items.append(f"full_matrix_rule:{prefix}")
        return tuple(dict.fromkeys(items))

    def pytest_k_expression(self) -> str:
        """Return a ``-k`` expression selecting exactly the routed cases."""
        if self.full_matrix_required or not self.case_ids:
            return ""
        names = sorted(
            case.test_name
            for case in EVIDENCE_CASES
            if case.case_id in set(self.case_ids)
        )
        return " or ".join(names)


_RULE_BY_PREFIX = {rule.path_prefix: rule for rule in IMPACT_RULES}


def _normalise(path: str) -> str:
    return path.replace("\\", "/").lstrip("./")


def match_rule(path: str) -> ImpactRule | None:
    """Return the longest-prefix rule for one repo-relative path."""
    candidate = _normalise(path)
    best: ImpactRule | None = None
    for rule in IMPACT_RULES:
        if candidate.startswith(rule.path_prefix) and (
            best is None or len(rule.path_prefix) > len(best.path_prefix)
        ):
            best = rule
    return best


def select_live_cases(changed_paths: Iterable[str]) -> ImpactSelection:
    """Route a diff to the live cases that must re-run.

    Fail closed: an unmatched path forces the full matrix rather than silently
    narrowing the selection.
    """
    case_ids: set[str] = set()
    unmapped: list[str] = []
    matched: list[tuple[str, str]] = []
    no_impact: list[str] = []
    full_matrix = False
    for raw_path in changed_paths:
        path = _normalise(raw_path)
        if not path:
            continue
        rule = match_rule(path)
        if rule is None:
            unmapped.append(path)
            full_matrix = True
            continue
        matched.append((path, rule.path_prefix))
        if rule.kind is ImpactKind.FULL_MATRIX:
            full_matrix = True
        elif rule.kind is ImpactKind.NO_IMPACT:
            no_impact.append(path)
        else:
            case_ids |= rule.case_ids
    if full_matrix:
        case_ids = set(_LIVE_CASE_IDS)
    return ImpactSelection(
        case_ids=tuple(sorted(case_ids)),
        full_matrix_required=full_matrix,
        unmapped_paths=tuple(dict.fromkeys(unmapped)),
        matched=tuple(matched),
        no_impact_paths=tuple(dict.fromkeys(no_impact)),
    )


def validate_impact_map() -> None:
    """Fail at import if the map references cases the catalog does not own."""
    duplicates = [
        rule.path_prefix for rule in IMPACT_RULES
        if sum(1 for item in IMPACT_RULES if item.path_prefix == rule.path_prefix) > 1
    ]
    if duplicates:
        raise ValueError(f"duplicate impact rule prefixes: {sorted(set(duplicates))}")
    referenced = {case_id for rule in IMPACT_RULES for case_id in rule.case_ids}
    unknown = referenced - _ALL_CASE_IDS
    if unknown:
        raise ValueError(
            "impact map references case ids absent from the evidence catalog: "
            + ", ".join(sorted(unknown))
        )
    scripted_only = referenced - _LIVE_CASE_IDS
    if scripted_only:
        raise ValueError(
            "impact map routes to cases that do not require a real model, so a "
            "live run cannot support them: " + ", ".join(sorted(scripted_only))
        )


validate_impact_map()


__all__ = [
    "IMPACT_RULES",
    "ImpactKind",
    "ImpactRule",
    "ImpactSelection",
    "match_rule",
    "select_live_cases",
    "validate_impact_map",
]
