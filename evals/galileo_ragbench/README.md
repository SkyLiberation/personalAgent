# Galileo RAGBench Eval Runner

This runner evaluates sentence-level evidence retrieval on Galileo RAGBench.
It intentionally keeps Open RAGBench paper/section assumptions behind explicit
strategy profiles so doc-first priors can be ablated instead of treated as a
default RAG behavior.

## No-DB lexical smoke

Runs without Postgres or embedding credentials:

```powershell
uv run python -m evals.galileo_ragbench.runner --subset covidqa --split test --num-queries 30 --strategy galileo_keyword_sentence --strategy galileo_doc_first_lexical --output evals/galileo_ragbench/results/covidqa_lexical_30q.json
```

Strategies:

- `galileo_keyword_sentence`: dataset-agnostic sentence lexical baseline.
- `galileo_shared_evidence_selector`: shared non-doc-first evidence selector
  over sentence units, using IDF/BM25-like lexical support, support cues, lexical
  RRF, low-information title/header filtering, and optional parent context
  companions when parent units are present.
- `galileo_doc_first_lexical`: Open-like document-first lexical ablation.

The runner reports both `metrics` for `all_relevant_sentence_keys` and
`utilized_metrics` for `all_utilized_sentence_keys`.

## Embedding/profile eval

Requires a configured Postgres URL and the normal embedding settings:

```powershell
uv run python -m evals.galileo_ragbench.runner --subset covidqa --split test --num-queries 30 --strategy galileo_external_sentence_embedding --strategy galileo_shared_embedding_evidence_selector --strategy galileo_open_like_doc_first_fusion --strategy galileo_profile_sentence_embedding --strategy galileo_shared_evidence_policy_selector --output evals/galileo_ragbench/results/covidqa_embedding_30q.json
```

Strategies:

- `galileo_external_sentence_embedding`: sentence-only embedding baseline.
- `galileo_shared_embedding_evidence_selector`: shared evidence selector using
  embedding-ranked candidates plus lexical/support scoring.
- `galileo_open_like_doc_first_fusion`: embedding retrieval fused with an
  Open-like document-first sentence prior.
- `galileo_profile_sentence_embedding`: Galileo profile with doc-first and
  same-doc slot refinement disabled.
- `galileo_shared_evidence_policy_selector`: shared evidence selector with an
  LLM support/utilization policy step and bounded ranking intervention.
