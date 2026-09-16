"""Request-local materialization of committed Conversation execution inputs."""

from __future__ import annotations

from collections.abc import Iterable

from personal_agent.application.capture.web_source import (
    WEB_SOURCE_FORMAT,
    WebReadOutput,
)
from personal_agent.application.conversation.models import (
    ActionObservation,
    InteractionInput,
)

READ_ACTION_OUTPUT_CAPABILITY = "read_action_output"
READ_ARTIFACT_CAPABILITY = "read_artifact"
SEARCH_ACTION_OUTPUT_CAPABILITY = "search_action_output"
ARTIFACT_OUTPUT_CAPABILITIES = frozenset({READ_ACTION_OUTPUT_CAPABILITY, READ_ARTIFACT_CAPABILITY, SEARCH_ACTION_OUTPUT_CAPABILITY})


def materialize_interaction_inputs(
    inputs: Iterable[InteractionInput],
) -> tuple[InteractionInput, ...]:
    """Project committed observations into the smallest lossless model view.

    The journal remains canonical and unchanged. Once an oversized observation
    has an application-owned resource reference, repeatedly sending its lossy
    head/tail excerpt adds input cost but cannot prove the omitted fact. The
    model needs the reference, source index, and omission metadata to choose an
    exact window through ``read_artifact``. Captured, failed, and merely
    discovered sources must remain distinguishable without loading the body.
    Read windows are already bounded evidence and remain visible verbatim.

    ``web_search`` stores both result rows and audit evidence in the canonical
    ToolArtifact. Those collections repeat the same title, URL, and snippet.
    The model sees ``data.results`` once; the journal retains full evidence for
    attribution and Completion.
    """

    materialized: list[InteractionInput] = []
    for item in inputs:
        if not isinstance(item, ActionObservation):
            materialized.append(item)
            continue
        if item.capability_id == "web_search":
            data = item.payload.get("data")
            evidence = item.payload.get("evidence")
            results = data.get("results") if isinstance(data, dict) else None
            if isinstance(results, list) and isinstance(evidence, list):
                result_urls = {
                    str(result.get("url", ""))
                    for result in results
                    if isinstance(result, dict) and result.get("url")
                }
                evidence_urls = {
                    str(candidate.get("url") or candidate.get("source_id") or "")
                    for candidate in evidence
                    if isinstance(candidate, dict)
                    and (candidate.get("url") or candidate.get("source_id"))
                }
                if evidence_urls.issubset(result_urls):
                    item = item.model_copy(update={
                        "payload": {
                            key: value
                            for key, value in item.payload.items()
                            if key != "evidence"
                        },
                    })
        retrieval = item.payload.get("retrieval")
        if (
            item.capability_id in ARTIFACT_OUTPUT_CAPABILITIES
            or not isinstance(retrieval, dict)
            or not isinstance(retrieval.get("resource_ref"), dict)
        ):
            materialized.append(item)
            continue
        compact_payload = {
            key: value
            for key, value in item.payload.items()
            if key in {"ok", "error", "error_kind", "status"}
        }
        compact_payload.update({
            "observation_excerpt_removed": True,
            "retrieval": retrieval,
        })
        data = item.payload.get("data")
        if isinstance(data, dict) and data.get("format") == WEB_SOURCE_FORMAT:
            source_output = WebReadOutput.model_validate(data)
            # 只卸载正文；已提交的来源和抓取 Provider 仍是决策所需事实。
            # 空正文由 omission 标记和同一 retrieval ref 明确解释，不代表未抓取。
            compact_payload["data"] = source_output.model_copy(
                update={"source_text": ""},
            ).model_dump(mode="json")
        materialized.append(item.model_copy(update={"payload": compact_payload}))
    return tuple(materialized)


def select_visible_successful_observations(
    inputs: Iterable[InteractionInput],
    *,
    excluded_capability_ids: frozenset[str] = frozenset(),
) -> tuple[ActionObservation, ...]:
    """Select successful execution facts from the canonical visible projection.

    Callers may use non-emptiness to decide whether grounded execution facts
    exist. Relevance, sufficiency, goal satisfaction, and completion remain
    semantic decisions outside this selector.
    """

    return tuple(
        item
        for item in materialize_interaction_inputs(inputs)
        if isinstance(item, ActionObservation)
        and item.status == "succeeded"
        and item.capability_id not in excluded_capability_ids
    )


__all__ = [
    "READ_ACTION_OUTPUT_CAPABILITY",
    "materialize_interaction_inputs",
    "select_visible_successful_observations",
]
