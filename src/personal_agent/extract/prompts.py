"""Prompt + few-shot examples for the lightweight pre-extraction layer."""
from __future__ import annotations

import langextract as lx


PROMPT_DESCRIPTION = (
    "Extract one section record per coherent passage of the document. "
    "For each passage, fill: topic (<=20 chars), summary (<=120 chars), "
    "contains_entities (representative names, no pronouns), contains_relations "
    "(true if the passage states subject-verb-object connections), "
    "information_density (high/medium/low), graph_worthy (true ONLY when the "
    "passage contains decisions, dependencies, definitions, causes, tradeoffs, "
    "or contrasts; lists of links, table-of-contents, acknowledgements, "
    "boilerplate are graph_worthy=false), reason (<=30 chars justification). "
    "Use exact source spans for extraction_text. Respond as JSON."
)


EXAMPLES: list[lx.data.ExampleData] = [
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
                    "topic": "FastAPI DI 缓存机制",
                    "summary": "Depends() 在请求生命周期内缓存依赖结果, 区别于普通函数调用。",
                    "contains_entities": ["FastAPI", "Depends"],
                    "contains_relations": True,
                    "information_density": "high",
                    "graph_worthy": True,
                    "reason": "包含定义和对比",
                },
            )
        ],
    ),
    lx.data.ExampleData(
        text=(
            "目录\n1. 引言\n2. 安装\n3. 快速开始\n4. 进阶用法\n5. API 参考\n"
        ),
        extractions=[
            lx.data.Extraction(
                extraction_class="section",
                extraction_text=(
                    "目录\n1. 引言\n2. 安装\n3. 快速开始\n4. 进阶用法\n5. API 参考\n"
                ),
                attributes={
                    "topic": "目录",
                    "summary": "文档的章节列表。",
                    "contains_entities": [],
                    "contains_relations": False,
                    "information_density": "low",
                    "graph_worthy": False,
                    "reason": "纯目录无信息",
                },
            )
        ],
    ),
]
