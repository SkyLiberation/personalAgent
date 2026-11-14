"""Read explicit ASCII decimal integer spellings at a typed input boundary."""

from __future__ import annotations

import re


POSITIVE_DECIMAL_PATTERN = r"[1-9][0-9]*"
_POSITIVE_DECIMAL = re.compile(POSITIVE_DECIMAL_PATTERN)
_SIGNED_DECIMAL = re.compile(rf"-?(?:0|{POSITIVE_DECIMAL_PATTERN})")


def read_decimal_integer(
    value: object, *, max_digits: int | None = None, positive: bool = False,
) -> int | None:
    """Return the integer for an accepted string, or None for other representations."""
    if not isinstance(value, str):
        return None
    if max_digits is not None and len(value.removeprefix("-")) > max_digits:
        return None
    pattern = _POSITIVE_DECIMAL if positive else _SIGNED_DECIMAL
    return int(value) if pattern.fullmatch(value) else None
