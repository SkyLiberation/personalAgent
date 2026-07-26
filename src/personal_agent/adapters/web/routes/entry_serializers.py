from __future__ import annotations

import json

def chunk_answer(answer: str, chunk_size: int = 40):
    for i in range(0, len(answer), chunk_size):
        yield answer[i:i + chunk_size]


def sse_event(event: str, payload: dict[str, object]) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
