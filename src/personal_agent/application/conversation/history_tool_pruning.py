"""Pressure-only projections of settled tool results."""

from collections.abc import Sequence

from personal_agent.kernel.prompt_registry import PromptCatalog

from .history_models import HistoryToolPruningBoundary
from .models import InteractionTrace


_THRESHOLD = 8_192
_HEAD = 4_096
_TAIL = 1_024
_RECENT_DECISIONS = 2


def active_tool_pruning(sources: Sequence[InteractionTrace]) -> dict[str, int]:
    source_refs = {source.interaction_run_ref for source in sources}
    boundaries: dict[str, int] = {}
    for source in sources:
        for boundary in source.history_tool_pruning:
            if boundary.run_ref in source_refs:
                boundaries[boundary.run_ref] = max(
                    boundaries.get(boundary.run_ref, 0), boundary.through_step,
                )
    return boundaries


def propose_tool_pruning(
    sources: Sequence[InteractionTrace],
) -> tuple[HistoryToolPruningBoundary, ...] | None:
    recorded = active_tool_pruning(sources)
    boundaries = dict(recorded)
    steps = [
        (source.interaction_run_ref, step.step_no)
        for source in sources
        for step in source.responded_steps
        if step.step_no is not None and step.consumed
    ]
    for run_ref, step_no in steps[:-_RECENT_DECISIONS]:
        boundaries[run_ref] = max(boundaries.get(run_ref, 0), step_no)
    if boundaries == recorded:
        return None
    return tuple(HistoryToolPruningBoundary(run_ref=run_ref, through_step=step)
                 for run_ref, step in boundaries.items())


def prune_history_tool_result(content: str, *, prompts: PromptCatalog) -> str:
    if len(content) <= _THRESHOLD:
        return content
    omitted = prompts.render("conversation.context.tool.omitted", count=len(content) - _HEAD - _TAIL)
    return f"{content[:_HEAD]}\n\n[… {omitted} …]\n\n{content[-_TAIL:]}"
