"""Intercept OpenAI Chat Completions calls and dump what LangExtract actually sends.

Monkey-patches openai.OpenAI's chat.completions.create at module load, before
LangExtract initializes its client, so every outbound request body is captured
and printed without contacting the real endpoint (or, optionally, after).

This is the lightweight alternative to mitmproxy on Windows — same observation,
no proxy configuration.

Usage:
    python scripts/probe_extract_request_capture.py            # records and re-raises (no real call)
    python scripts/probe_extract_request_capture.py --live     # records AND lets the real call run
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent

SAMPLE = (
    "LangGraph 的 checkpoint 用于在中断后恢复 GraphState；它和长期记忆不同, "
    "长期记忆走独立的 store。Postgres 持久化 checkpoint 和 store, 但二者表分开。"
)


_CAPTURED: list[dict] = []


class _StopAfterCapture(Exception):
    """Sentinel: signals the wrapper captured the request without forwarding."""


def install_interceptor(*, live: bool) -> None:
    import openai

    original = openai.resources.chat.completions.Completions.create

    def wrapper(self, *args, **kwargs):
        # Snapshot the call params; deepcopy via JSON to strip non-serializable.
        snapshot = {
            "model": kwargs.get("model"),
            "response_format": kwargs.get("response_format"),
            "temperature": kwargs.get("temperature"),
            "max_tokens": kwargs.get("max_tokens"),
            "messages_count": len(kwargs.get("messages") or []),
            "first_message_role": (
                (kwargs.get("messages") or [{}])[0].get("role") if kwargs.get("messages") else None
            ),
            "system_prompt_preview": "",
            "user_prompt_preview": "",
        }
        for msg in kwargs.get("messages") or []:
            content = msg.get("content", "")
            if msg.get("role") == "system":
                snapshot["system_prompt_preview"] = content[:200]
            elif msg.get("role") == "user" and not snapshot["user_prompt_preview"]:
                snapshot["user_prompt_preview"] = content[:200]
        _CAPTURED.append(snapshot)

        if live:
            return original(self, *args, **kwargs)
        raise _StopAfterCapture()

    openai.resources.chat.completions.Completions.create = wrapper


def main() -> int:
    live = "--live" in sys.argv
    load_dotenv(override=True)

    api_key = os.getenv("PERSONAL_AGENT_EXTRACT_API_KEY") or os.getenv("EMBEDDING_API_KEY")
    base_url = os.getenv(
        "PERSONAL_AGENT_EXTRACT_BASE_URL",
        "https://dashscope.aliyuncs.com/compatible-mode/v1",
    )
    model_id = os.getenv("PERSONAL_AGENT_EXTRACT_MODEL", "qwen3-coder-flash")

    if not api_key:
        print("[capture] missing api_key — abort")
        return 2

    install_interceptor(live=live)

    from personal_agent.kernel.config import LangExtractConfig
    from personal_agent.application.extract.service import PreExtractService

    cfg = LangExtractConfig(
        api_key=api_key,
        base_url=base_url,
        model_id=model_id,
        max_char_buffer=6000,
        extraction_passes=1,
        max_workers=1,
        min_doc_chars=10,
        fallback_on_error=False,
    )
    svc = PreExtractService(cfg)

    print(f"[capture] live={live} model={model_id}")
    try:
        sm = svc.extract(SAMPLE)
        if live:
            print(f"[capture] live extraction returned {len(sm.sections)} sections")
    except _StopAfterCapture:
        print("[capture] dry-run: request captured, no API call made")
    except Exception as exc:
        print(f"[capture] EXC during extraction: {type(exc).__name__}: {exc}")

    print(f"\n=== captured {len(_CAPTURED)} request(s) ===")
    for i, snap in enumerate(_CAPTURED):
        print(f"\n[req {i}] model={snap['model']} temp={snap['temperature']}")
        rf = snap["response_format"]
        if isinstance(rf, dict):
            print(f"[req {i}] response_format.type = {rf.get('type')!r}")
            if rf.get("type") == "json_schema":
                schema_block = rf.get("json_schema", {})
                print(f"[req {i}] response_format.json_schema.name = {schema_block.get('name')}")
                print(f"[req {i}] response_format.json_schema.strict = {schema_block.get('strict')}")
                schema_dict = schema_block.get("schema", {})
                print(
                    f"[req {i}] response_format.json_schema.schema TOP keys = "
                    f"{list(schema_dict.keys())}"
                )
                # Dump the full schema for archival.
                schema_dump = REPO_ROOT / "log" / "probe_request_schema.json"
                schema_dump.parent.mkdir(parents=True, exist_ok=True)
                schema_dump.write_text(
                    json.dumps(rf, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                print(f"[req {i}] full json_schema dumped to {schema_dump}")
        else:
            print(f"[req {i}] response_format = {rf!r}")
        print(f"[req {i}] system_prompt_preview = {snap['system_prompt_preview']!r}")
        print(f"[req {i}] user_prompt_preview   = {snap['user_prompt_preview']!r}")

    return 0 if _CAPTURED else 1


if __name__ == "__main__":
    sys.exit(main())
