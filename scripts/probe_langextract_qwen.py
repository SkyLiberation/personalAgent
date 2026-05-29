"""qwen3-coder-flash + LangExtract compatibility probe.

Aliyun DashScope's qwen3-coder-flash claims to support OpenAI-style
`response_format = json_schema`, so LangExtract's *default* schema-constrained
path should work without disabling `use_schema_constraints`. This probe runs
both modes and prints what each returns.

Credentials: reuses EMBEDDING_API_KEY / EMBEDDING_BASE_URL from .env (those
already point at DashScope's OpenAI-compatible endpoint).

Usage:
    python scripts/probe_langextract_qwen.py
"""
from __future__ import annotations

import os
import sys
import traceback

from dotenv import load_dotenv

import langextract as lx
from langextract.factory import ModelConfig


SAMPLE = (
    "LangGraph 的 checkpoint 用于在中断后恢复 GraphState；它和长期记忆不同, "
    "长期记忆走独立的 store。Postgres 持久化 checkpoint 和 store, 但二者表分开。"
)

PROMPT = (
    "Extract section topic, core entities, and whether this passage is "
    "graph-worthy (contains decisions, dependencies, definitions, causes, "
    "or contrasts). Respond as JSON."
)

EXAMPLES = [
    lx.data.ExampleData(
        text=(
            "FastAPI 的 dependency injection 通过 Depends() 实现, 它在请求生命周期内 "
            "缓存依赖结果, 这区别于普通函数调用。"
        ),
        extractions=[
            lx.data.Extraction(
                extraction_class="section",
                extraction_text=(
                    "FastAPI 的 dependency injection 通过 Depends() 实现, 它在请求生命周期内 "
                    "缓存依赖结果, 这区别于普通函数调用。"
                ),
                attributes={
                    "topic": "FastAPI dependency injection 缓存机制",
                    "entities": ["FastAPI", "Depends"],
                    "graph_worthy": True,
                    "reason": "包含定义和对比",
                },
            )
        ],
    )
]

MODEL_ID = "qwen3-coder-flash"


def _run(label: str, cfg: ModelConfig, *, schema: bool) -> None:
    print(f"\n[probe:{label}] schema_constraints={schema}")
    try:
        result = lx.extract(
            text_or_documents=SAMPLE,
            prompt_description=PROMPT,
            examples=EXAMPLES,
            config=cfg,
            use_schema_constraints=schema,
            fence_output=None if schema else True,
        )
    except Exception:
        print(f"[probe:{label}] EXCEPTION:")
        traceback.print_exc()
        return

    extractions = getattr(result, "extractions", None) or []
    print(f"[probe:{label}] OK, extractions={len(extractions)}")
    for i, ex in enumerate(extractions):
        print(f"  [{i}] class={ex.extraction_class}")
        try:
            text_preview = ex.extraction_text[:80]
            print(f"      text={text_preview!r}".encode("ascii", errors="replace").decode("ascii"))
        except Exception:
            print("      text=<unprintable>")
        try:
            print(f"      attributes={ex.attributes}".encode("ascii", errors="replace").decode("ascii"))
        except Exception:
            print(f"      attributes_keys={list(ex.attributes.keys()) if ex.attributes else []}")
        print(f"      char_interval={getattr(ex, 'char_interval', None)}")


def main() -> int:
    load_dotenv(override=True)
    api_key = os.getenv("EMBEDDING_API_KEY") or os.getenv("DASHSCOPE_API_KEY")
    base_url = os.getenv("EMBEDDING_BASE_URL") or "https://dashscope.aliyuncs.com/compatible-mode/v1"

    print(f"[probe] base_url={base_url}")
    print(f"[probe] model={MODEL_ID}")
    print(f"[probe] api_key={'set' if api_key else 'MISSING'}")

    if not api_key:
        print("[probe] missing DashScope api_key, abort")
        return 2

    cfg = ModelConfig(
        model_id=MODEL_ID,
        provider="openai",
        provider_kwargs={
            "api_key": api_key,
            "base_url": base_url,
        },
    )

    _run("schema-on", cfg, schema=True)
    _run("schema-off", cfg, schema=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
