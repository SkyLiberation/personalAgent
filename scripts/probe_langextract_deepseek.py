"""DeepSeek + LangExtract compatibility probe.

Runs a tiny extraction against the real DeepSeek OpenAI-compatible endpoint
configured in .env, prints whatever the library returns, and dumps any
exception with full traceback so we can see the failure mode.

Usage:
    python scripts/probe_langextract_deepseek.py
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


def main() -> int:
    load_dotenv(override=True)
    api_key = os.getenv("OPENAI_API_KEY")
    base_url = os.getenv("OPENAI_BASE_URL")
    model = os.getenv("OPENAI_SMALL_MODEL") or os.getenv("OPENAI_MODEL")

    print(f"[probe] base_url={base_url}")
    print(f"[probe] model={model}")
    print(f"[probe] api_key={'set' if api_key else 'MISSING'}")

    if not (api_key and base_url and model):
        print("[probe] missing env, abort")
        return 2

    cfg = ModelConfig(
        model_id=model,
        provider="openai",
        provider_kwargs={
            "api_key": api_key,
            "base_url": base_url,
        },
    )

    try:
        result = lx.extract(
            text_or_documents=SAMPLE,
            prompt_description=PROMPT,
            examples=EXAMPLES,
            config=cfg,
            use_schema_constraints=False,
            fence_output=True,
        )
    except Exception:
        print("[probe] EXCEPTION:")
        traceback.print_exc()
        return 1

    print("[probe] OK, result type:", type(result).__name__)
    extractions = getattr(result, "extractions", None) or []
    print(f"[probe] extractions count: {len(extractions)}")
    for i, ex in enumerate(extractions):
        print(f"  [{i}] class={ex.extraction_class}")
        print(f"      text={ex.extraction_text[:80]!r}")
        print(f"      attributes={ex.attributes}")
        char_interval = getattr(ex, "char_interval", None)
        print(f"      char_interval={char_interval}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
