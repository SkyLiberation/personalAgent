"""Context admission helpers used by bounded executors.

Task interpretation and control decisions live in ``goal_graph_compiler`` and
``executive``. This module deliberately contains no pattern selector or plan
compiler.
"""

from __future__ import annotations

from personal_agent.runtime.contracts.task import ContextInventory, ContextItem, TaskContract
class ContextAdmission:
    @staticmethod
    def initial(task: TaskContract) -> ContextInventory:
        item = ContextItem(
            item_id=task.task_id,
            category="run",
            kind="task_contract",
            provenance="runtime",
            trust="runtime",
            summary=task.user_goal[:1000],
            payload={"revision": task.revision},
            admission="admitted",
        )
        return ContextInventory(items={item.item_id: item})

    @staticmethod
    def admit_observation(
        envelope: ContextInventory,
        *,
        ref_id: str,
        kind: str,
        provenance: str,
        summary: str,
        payload: dict[str, object] | None = None,
        taint_source: str | None = None,
    ) -> ContextInventory:
        from personal_agent.governance.guardrails import get_content_guard

        guard = get_content_guard()
        verdict = guard.sanitize_untrusted(summary)
        inspection = (
            guard.sanitize_untrusted(taint_source)
            if taint_source is not None else verdict
        )
        taint = {"external_content"}
        if "untrusted_injection" in inspection.categories:
            taint.add("instruction")
        observation_payload = dict(payload or {})
        guard_categories = tuple(dict.fromkeys((
            *verdict.categories,
            *inspection.categories,
        )))
        if guard_categories:
            observation_payload["guard_categories"] = list(guard_categories)
        item = ContextItem(
            item_id=ref_id,
            category="observation",
            kind=kind,
            provenance=provenance,
            trust="untrusted",
            taint=frozenset(taint),
            summary=verdict.text[:2000],
            payload=observation_payload,
            admission="candidate",
        )
        return envelope.with_items(item)


__all__ = ["ContextAdmission"]
