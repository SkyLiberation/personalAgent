"""Progressively loaded skills and provider-neutral plan macros."""

from __future__ import annotations

from personal_agent.kernel.contracts.agentic import PlanMacro, Skill, SkillApplicability, TaskSpec


class SkillCatalog:
    def __init__(self) -> None:
        self._skills = {
            "code-investigation": Skill(
                skill_id="code-investigation",
                description="Locate code evidence, bind it to revisions, and explain call paths.",
                applicability=SkillApplicability(semantic_domains=("codebase",)),
                instructions="Prefer repository-grounded evidence, inspect callers and tests, and bind claims to files or revisions.",
                verifier_profile="code_evidence",
                output_contracts=("EvidencePack", "VerificationReport"),
                eval_contract="code_evidence_traceability",
            ),
            "evidence-research": Skill(
                skill_id="evidence-research",
                description="Research with source diversity, contradiction checks, and citation quality.",
                applicability=SkillApplicability(
                    semantic_domains=("knowledge", "workspace", "project", "web", "external_research"),
                ),
                instructions="Track claims to sources, seek counter-evidence, and expose unresolved uncertainty.",
                verifier_profile="evidence",
                output_contracts=("EvidencePack", "VerificationReport"),
                eval_contract="evidence_coverage",
            ),
            "knowledge-curation": Skill(
                skill_id="knowledge-curation",
                description="Admit durable knowledge with conflict, expiry, and provenance checks.",
                applicability=SkillApplicability(outcome_kinds=("knowledge_change",)),
                instructions="Separate claims from evidence and require admission plus confirmation before durable writes.",
                verifier_profile="memory_admission",
                output_contracts=("KnowledgeStateReceipt",),
                eval_contract="memory_admission",
            ),
            "decision-support": Skill(
                skill_id="decision-support",
                description="Compare options while exposing assumptions and evidence gaps.",
                applicability=SkillApplicability(
                    semantic_domains=("conversation", "knowledge", "codebase", "workspace", "project"),
                ),
                instructions="Separate facts, assumptions, options, and uncertainty; do not make high-risk decisions for the user.",
                verifier_profile="evidence",
                output_contracts=("VerificationReport",),
                eval_contract="decision_quality",
            ),
        }

    def descriptions(self) -> tuple[dict[str, str], ...]:
        return tuple({"skill_id": item.skill_id, "description": item.description} for item in self._skills.values())

    def get(self, skill_id: str) -> Skill:
        return self._skills[skill_id]

    def candidates(self, task: TaskSpec) -> tuple[Skill, ...]:
        domains = {item.semantic_domain for item in task.resource_requirements}
        result = []
        for skill in self._skills.values():
            applies = skill.applicability
            if domains.intersection(applies.semantic_domains) or task.outcome_kind in applies.outcome_kinds:
                result.append(skill)
        return tuple(result)


class PlanMacroCatalog:
    def __init__(self) -> None:
        self._macros = {
            "evidence_answer": PlanMacro(
                macro_id="evidence_answer",
                description="Acquire evidence, form claims, verify coverage, and present an answer.",
                recommended_goal_kinds=("evidence_answer",),
                verifier_profile="evidence",
                stop_conditions=("all_required_claims_traceable",),
            ),
            "investigation": PlanMacro(
                macro_id="investigation",
                description="Explore hypotheses, seek counter-evidence, and verify a conclusion.",
                recommended_goal_kinds=("investigation",),
                verifier_profile="evidence",
                stop_conditions=("hypothesis_supported_or_rejected",),
            ),
            "knowledge_change": PlanMacro(
                macro_id="knowledge_change",
                description="Prepare, verify, confirm, and commit a durable knowledge change.",
                recommended_goal_kinds=("protocol",),
                verifier_profile="memory_admission",
                stop_conditions=("mutation_receipt_present",),
            ),
            "delegated_research": PlanMacro(
                macro_id="delegated_research",
                description="Delegate a bounded research subgoal and independently verify its artifact.",
                recommended_goal_kinds=("delegate",),
                verifier_profile="evidence",
                stop_conditions=("delegated_artifact_verified",),
            ),
        }

    def for_goal_kind(self, goal_kind: str) -> PlanMacro | None:
        return next(
            (macro for macro in self._macros.values() if goal_kind in macro.recommended_goal_kinds),
            None,
        )


__all__ = ["PlanMacroCatalog", "SkillCatalog"]
