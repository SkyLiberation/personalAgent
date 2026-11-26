"""Encode a committed Turn revision and rebuild its full trace on a cold read."""

from collections.abc import Iterable
from datetime import datetime
import json
from math import copysign
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from personal_agent.application.conversation.errors import ConversationOperationConflict
from personal_agent.application.conversation.models import ConversationMessage, InteractionTrace


_REVISION_FIELDS = {"messages", "revision"}


class _SequenceUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start: int = Field(ge=0)
    items: list[JsonValue]


class _RevisionDelta(BaseModel):
    model_config = ConfigDict(extra="forbid")

    format: Literal["turn-delta-v1"] = "turn-delta-v1"
    base_revision: int = Field(ge=1)
    fields: dict[str, JsonValue]
    sequences: dict[str, _SequenceUpdate]


def encode_revision(trace: InteractionTrace, previous: InteractionTrace | None) -> str:
    if previous is None or (previous.final_message is None and trace.final_message is not None):
        return trace.model_dump_json(exclude={"messages"})

    fields: list[str] = []
    starts: dict[str, int] = {}
    suffixes: dict[str, tuple[object, ...]] = {}
    for name in InteractionTrace.model_fields:
        if name in _REVISION_FIELDS:
            continue
        old, new = getattr(previous, name), getattr(trace, name)
        if old is new:
            continue
        if isinstance(old, tuple) and isinstance(new, tuple):
            start = min(len(old), len(new))
            for index, (left, right) in enumerate(zip(old, new)):
                if not _same_value(left, right):
                    start = index
                    break
            if start == len(old) == len(new):
                continue
            starts[name] = start
            suffixes[name] = new[start:]
        elif not _same_value(old, new):
            fields.append(name)

    values = trace.model_copy(update=suffixes).model_dump(mode="json", include=set(fields) | starts.keys())
    delta = _RevisionDelta(
        base_revision=previous.revision,
        fields={key: values[key] for key in fields},
        sequences={key: _SequenceUpdate(start=start, items=values[key]) for key, start in starts.items()},
    )
    return delta.model_dump_json()


def _same_value(left, right) -> bool:
    # Tool payloads can contain JSON values that compare equal in Python but serialize differently.
    if left is right:
        return True
    if type(left) is not type(right):
        return False
    if isinstance(left, BaseModel):
        return _same_value(vars(left), vars(right)) and _same_value(left.model_extra, right.model_extra)
    if isinstance(left, dict):
        return left.keys() == right.keys() and all(_same_value(value, right[key]) for key, value in left.items())
    if isinstance(left, (list, tuple)):
        return len(left) == len(right) and all(_same_value(a, b) for a, b in zip(left, right))
    if isinstance(left, datetime):
        return left.isoformat() == right.isoformat()
    if isinstance(left, float) and left == right == 0.0:
        return copysign(1.0, left) == copysign(1.0, right)
    return left == right


def decode_revision(
    rows: Iterable[tuple[int, str]], *, revision: int, messages: tuple[ConversationMessage, ...],
) -> InteractionTrace:
    deltas: list[_RevisionDelta] = []
    expected = revision
    for number, payload in rows:
        if number != expected:
            break
        data = json.loads(payload)
        if "format" not in data:
            base = InteractionTrace.model_validate({**data, "messages": messages})
            if base.revision != number:
                break
            if not deltas:
                return base
            facts = base.model_dump(mode="json", exclude={"messages"})
            for delta in reversed(deltas):
                _apply_delta(facts, delta)
            return InteractionTrace.model_validate({**facts, "revision": revision, "messages": messages})
        delta = _RevisionDelta.model_validate(data)
        if delta.base_revision != number - 1:
            break
        deltas.append(delta)
        expected = delta.base_revision
    raise ConversationOperationConflict("轮次修订链不完整")


def _apply_delta(facts: dict[str, JsonValue], delta: _RevisionDelta) -> None:
    if ((delta.fields.keys() | delta.sequences.keys()) & _REVISION_FIELDS
            or delta.fields.keys() & delta.sequences.keys()):
        raise ConversationOperationConflict("轮次修订字段冲突")
    facts.update(delta.fields)
    for name, update in delta.sequences.items():
        source = facts.get(name)
        if not isinstance(source, list) or update.start > len(source):
            raise ConversationOperationConflict("轮次修订序列起点不合法")
        source[update.start:] = update.items
