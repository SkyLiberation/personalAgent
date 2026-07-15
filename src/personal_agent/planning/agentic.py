"""Context admission helpers used by bounded executors.

Task interpretation and control decisions live in ``goal_graph_compiler`` and
``executive``. This module deliberately contains no pattern selector or plan
compiler.
"""

from __future__ import annotations

from personal_agent.kernel.contracts.agentic import ContextEnvelope, ContextItem, TaskSpec
from personal_agent.skills import LoadedSkill


class ContextAdmission:
    @staticmethod
    def initial(task: TaskSpec, skills: tuple[LoadedSkill, ...] = ()) -> ContextEnvelope:
        return ContextEnvelope(
            run_context=(ContextItem(
                ref_id=task.task_id,
                kind="task_spec",
                provenance="runtime",
                trust_tier="runtime",
                summary=task.user_goal[:1000],
                payload={"revision": task.revision},
                admitted=True,
            ),),
            active_skill_ids=tuple(skill.manifest.skill_id for skill in skills),
        )

    @staticmethod
    def admit_observation(
        envelope: ContextEnvelope,
        *,
        ref_id: str,
        kind: str,
        provenance: str,
        summary: str,
        payload: dict[str, object] | None = None,
    ) -> ContextEnvelope:
        item = ContextItem(
            ref_id=ref_id,
            kind=kind,
            provenance=provenance,
            trust_tier="untrusted",
            summary=summary[:2000],
            payload=payload or {},
            admitted=False,
        )
        return envelope.model_copy(update={
            "untrusted_observations": (*envelope.untrusted_observations, item),
        })


__all__ = ["ContextAdmission"]
