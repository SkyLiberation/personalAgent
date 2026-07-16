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
    ) -> ContextInventory:
        item = ContextItem(
            item_id=ref_id,
            category="observation",
            kind=kind,
            provenance=provenance,
            trust="untrusted",
            summary=summary[:2000],
            payload=payload or {},
            admission="candidate",
        )
        return envelope.with_items(item)


__all__ = ["ContextAdmission"]
