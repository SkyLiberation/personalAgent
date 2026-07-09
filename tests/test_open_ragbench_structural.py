from __future__ import annotations

from personal_agent.kernel.config import Settings
from tests.note_factory import make_note
from personal_agent.kernel.query_understanding import QueryUnderstanding, RetrievalFilters, RetrievalPlan

from evals.open_ragbench.loader import RAGBenchDoc, RAGBenchQuery
from evals.open_ragbench.runner import (
    AskPipelineStrategy,
    BenchmarkContext,
    BenchmarkRunResult,
    DATASET_AGNOSTIC_PROFILE,
    DocFirstExternalLlmScoreRerankStrategy,
    DocFirstExternalLlmTopMRerankStrategy,
    DocFirstFusionStrategy,
    HighAccuracySemanticSelectorStrategy,
    HighAccuracySemanticPolicySelectorStrategy,
    GALILEO_RAGBENCH_PROFILE,
    OPEN_RAGBENCH_PROFILE,
    RuntimeAskStrategy,
    SharedEvidenceSelectorStrategy,
    StructuralRetrieverStrategy,
    _EvidenceSelectionPolicy,
    _EvidenceSelectionJudgment,
    _NoteScoreItem,
    _apply_semantic_policy,
    _build_structural_index,
    _blend_v2_and_semantic_selector,
    _blend_fusion_and_llm_scores,
    _high_accuracy_ask_settings,
    _blend_fusion_and_llm_ranks,
    _combined_semantic_selector_score,
    _combined_llm_note_score,
    _cosine_similarity,
    _enrich_eval_snapshot,
    _normalize_open_ragbench_query,
    _semantic_selector_trigger_reason,
    _refine_same_doc_sections,
    resolve_retrieval_strategy_profile,
    _section_passages,
    _summarize_diagnostics,
    get_strategy,
    run_open_ragbench,
    list_strategy_names,
)
from evals.open_ragbench.metrics import RetrievalReport
from evals.shared_evidence_selector import EvidenceUnit, SharedEvidenceSelectorConfig, select_shared_evidence


def _context() -> BenchmarkContext:
    return BenchmarkContext(
        settings=Settings(),
        graphiti_user_id="test",
        reset_graphiti=True,
        graphiti_manifest_path=None,
        graphiti_note_mode="parent_sections",
        graphiti_continue_on_ingest_error=False,
    )


def test_structural_is_registered():
    assert "structural" in list_strategy_names()
    assert "doc_first_section" in list_strategy_names()
    assert "doc_first_fusion" in list_strategy_names()
    assert "doc_first_external_fusion" in list_strategy_names()
    assert "doc_first_external_fusion_normalized" in list_strategy_names()
    assert "doc_first_external_fusion_normalized_latex" in list_strategy_names()
    assert "doc_first_external_fusion_normalized_yes_no" in list_strategy_names()
    assert "doc_first_external_fusion_normalized_yes_no_compact" in list_strategy_names()
    assert "doc_first_external_fusion_normalized_yes_no_guarded" in list_strategy_names()
    assert "doc_first_external_fusion_normalized_yes_no_article" in list_strategy_names()
    assert "doc_first_external_fusion_yes_no_query_fusion" in list_strategy_names()
    assert "doc_first_external_fusion_section_refine" in list_strategy_names()
    assert "doc_first_external_llm_topm_rerank" in list_strategy_names()
    assert "doc_first_external_llm_score_rerank" in list_strategy_names()
    assert isinstance(get_strategy("structural"), StructuralRetrieverStrategy)


def test_ask_pipeline_eval_variants_are_registered():
    names = list_strategy_names()

    assert "ask_pipeline" in names
    assert "ask_pipeline_no_rewrite" in names
    assert "ask_pipeline_local_only" in names
    assert "ask_pipeline_no_planner" in names
    assert "ask_retrieve_no_workspace" in names
    assert "ask_retrieve_support" in names
    assert "ask_retrieve_high_accuracy" in names
    assert "ask_retrieve_shared_evidence_selector_lexical" in names
    assert "ask_retrieve_shared_evidence_selector" in names
    assert "ask_retrieve_shared_evidence_policy_selector" in names
    assert "ask_retrieve_open_profile" in names
    assert "ask_retrieve_galileo_profile" in names
    assert "ask_retrieve_dataset_agnostic_profile" in names
    assert "ask_retrieve_high_accuracy_section_refine" in names
    assert "ask_retrieve_high_accuracy_passage_refine" in names
    assert "ask_retrieve_high_accuracy_semantic_selector" in names
    assert "ask_retrieve_high_accuracy_semantic_selector_all_queries" in names
    assert "ask_retrieve_high_accuracy_semantic_selector_triggered_only" in names
    assert "ask_retrieve_high_accuracy_semantic_policy_selector" in names
    assert "ask_retrieve_llm_rerank" in names
    assert "ask_retrieve_external_embedding" in names
    assert "ask_retrieve_external_llm_rerank" in names
    assert "ask_retrieve_workspace" in names
    assert "ask_retrieve_workspace_forced_claim_sensitive" in names
    assert "ask_retrieve_workspace_evidence_only" in names
    assert "current_runtime_ask" in names
    assert isinstance(get_strategy("ask_pipeline"), AskPipelineStrategy)
    assert isinstance(get_strategy("ask_pipeline_no_rewrite"), AskPipelineStrategy)
    assert isinstance(get_strategy("ask_pipeline_local_only"), AskPipelineStrategy)
    assert isinstance(get_strategy("ask_pipeline_no_planner"), AskPipelineStrategy)
    assert isinstance(get_strategy("current_runtime_ask"), RuntimeAskStrategy)
    assert get_strategy("ask_retrieve_support").name == "ask_retrieve_support"
    assert get_strategy("ask_retrieve_external_llm_rerank").name == "ask_retrieve_external_llm_rerank"
    high_accuracy = get_strategy("ask_retrieve_high_accuracy")
    assert isinstance(high_accuracy, DocFirstFusionStrategy)
    assert high_accuracy.external_embedding is True
    assert high_accuracy.query_normalization_mode == "yes_no_guarded"
    assert high_accuracy.section_refine is True
    assert high_accuracy.section_refine_mode == "passage_embedding"
    assert high_accuracy.section_refine_weight == 0.02
    shared_lexical = get_strategy("ask_retrieve_shared_evidence_selector_lexical")
    shared_embedding = get_strategy("ask_retrieve_shared_evidence_selector")
    shared_policy = get_strategy("ask_retrieve_shared_evidence_policy_selector")
    assert isinstance(shared_lexical, SharedEvidenceSelectorStrategy)
    assert isinstance(shared_embedding, SharedEvidenceSelectorStrategy)
    assert isinstance(shared_policy, SharedEvidenceSelectorStrategy)
    assert shared_lexical.external_embedding is False
    assert shared_embedding.external_embedding is True
    assert shared_embedding.profile == DATASET_AGNOSTIC_PROFILE
    assert shared_policy.use_policy_selector is True
    assert shared_policy.profile == DATASET_AGNOSTIC_PROFILE
    open_profile = get_strategy("ask_retrieve_open_profile")
    galileo_profile = get_strategy("ask_retrieve_galileo_profile")
    agnostic_profile = get_strategy("ask_retrieve_dataset_agnostic_profile")
    assert isinstance(open_profile, DocFirstFusionStrategy)
    assert isinstance(galileo_profile, DocFirstFusionStrategy)
    assert isinstance(agnostic_profile, DocFirstFusionStrategy)
    assert open_profile.profile == OPEN_RAGBENCH_PROFILE
    assert open_profile.doc_first_enabled is True
    assert open_profile.section_refine is True
    assert galileo_profile.profile == GALILEO_RAGBENCH_PROFILE
    assert galileo_profile.doc_first_enabled is False
    assert galileo_profile.section_refine is False
    assert agnostic_profile.profile == DATASET_AGNOSTIC_PROFILE
    assert agnostic_profile.doc_first_enabled is False
    high_accuracy_refine = get_strategy("ask_retrieve_high_accuracy_section_refine")
    assert isinstance(high_accuracy_refine, DocFirstFusionStrategy)
    assert high_accuracy_refine.section_refine is True
    assert high_accuracy_refine.query_normalization_mode == "yes_no_guarded"
    passage_refine = get_strategy("ask_retrieve_high_accuracy_passage_refine")
    assert isinstance(passage_refine, DocFirstFusionStrategy)
    assert passage_refine.section_refine_mode == "passage_embedding"
    assert passage_refine.section_refine_weight == 0.02
    semantic_selector = get_strategy("ask_retrieve_high_accuracy_semantic_selector")
    assert isinstance(semantic_selector, HighAccuracySemanticSelectorStrategy)
    assert semantic_selector.top_m == 10
    assert semantic_selector.selector_weight == 0.0005
    assert semantic_selector.trigger_mode == "all_queries"
    selector_all = get_strategy("ask_retrieve_high_accuracy_semantic_selector_all_queries")
    selector_triggered = get_strategy("ask_retrieve_high_accuracy_semantic_selector_triggered_only")
    assert isinstance(selector_all, HighAccuracySemanticSelectorStrategy)
    assert isinstance(selector_triggered, HighAccuracySemanticSelectorStrategy)
    assert selector_all.trigger_mode == "all_queries"
    assert selector_triggered.trigger_mode == "triggered_only"
    assert selector_all.preserve_top_k == 0
    assert selector_triggered.preserve_top_k == 5
    policy_selector = get_strategy("ask_retrieve_high_accuracy_semantic_policy_selector")
    assert isinstance(policy_selector, HighAccuracySemanticPolicySelectorStrategy)
    assert policy_selector.confidence_threshold == 0.7
    assert policy_selector.preserve_top_k == 5


def test_retrieval_strategy_profile_resolver_selects_dataset_profiles():
    assert resolve_retrieval_strategy_profile(benchmark="open_ragbench") == OPEN_RAGBENCH_PROFILE
    assert resolve_retrieval_strategy_profile(benchmark="galileo_ragbench") == GALILEO_RAGBENCH_PROFILE
    assert resolve_retrieval_strategy_profile(task_type="cross_doc_question") == DATASET_AGNOSTIC_PROFILE


def test_shared_evidence_selector_adds_existing_parent_companion_only():
    units = [
        EvidenceUnit(id="parent", text="Parent context about antiviral clearance.", kind="document"),
        EvidenceUnit(id="child", text="Antiviral response clears the virus.", parent_id="parent", kind="section"),
        EvidenceUnit(id="orphan", text="Antiviral response details.", parent_id="missing", kind="section"),
    ]

    selected = select_shared_evidence(
        "Which response clears the virus?",
        units,
        limit=3,
        config=SharedEvidenceSelectorConfig(),
    )

    assert "child" in selected.ranked_ids
    assert "parent" in selected.ranked_ids
    assert "missing" not in selected.ranked_ids


def test_shared_evidence_selector_filters_low_information_headers_with_fallback():
    units = [
        EvidenceUnit(id="title", text="Title: Virus study", kind="sentence"),
        EvidenceUnit(id="evidence", text="The antiviral response clears the virus effectively.", kind="sentence"),
    ]

    selected = select_shared_evidence(
        "Which response clears the virus?",
        units,
        limit=2,
        config=SharedEvidenceSelectorConfig(),
    )
    fallback = select_shared_evidence(
        "Virus study",
        [EvidenceUnit(id="title", text="Title: Virus study", kind="sentence")],
        limit=2,
        config=SharedEvidenceSelectorConfig(),
    )

    assert selected.ranked_ids == ["evidence"]
    assert selected.diagnostics["low_information_unit_count"] == 1
    assert fallback.ranked_ids == ["title"]


def test_high_accuracy_profile_uses_external_embedding():
    settings = Settings(
        openai=Settings().openai.model_copy(update={"embedding_model": "legacy-model"})
    )

    updated = _high_accuracy_ask_settings(settings)

    assert updated.embedding_provider == "openai"
    assert updated.openai.embedding_model == "BAAI/bge-m3"
    assert updated.ask.local_retrieval_limit >= 12


def test_doc_first_fusion_strategy_is_registered():
    assert isinstance(get_strategy("doc_first_fusion"), DocFirstFusionStrategy)
    external = get_strategy("doc_first_external_fusion")
    assert isinstance(external, DocFirstFusionStrategy)
    assert external.external_embedding is True
    normalized = get_strategy("doc_first_external_fusion_normalized")
    assert isinstance(normalized, DocFirstFusionStrategy)
    assert normalized.external_embedding is True
    assert normalized.normalize_query is True
    latex_only = get_strategy("doc_first_external_fusion_normalized_latex")
    assert isinstance(latex_only, DocFirstFusionStrategy)
    assert latex_only.query_normalization_mode == "latex"
    yes_no_only = get_strategy("doc_first_external_fusion_normalized_yes_no")
    assert isinstance(yes_no_only, DocFirstFusionStrategy)
    assert yes_no_only.query_normalization_mode == "yes_no"
    yes_no_compact = get_strategy("doc_first_external_fusion_normalized_yes_no_compact")
    assert isinstance(yes_no_compact, DocFirstFusionStrategy)
    assert yes_no_compact.query_normalization_mode == "yes_no_compact"
    yes_no_guarded = get_strategy("doc_first_external_fusion_normalized_yes_no_guarded")
    assert isinstance(yes_no_guarded, DocFirstFusionStrategy)
    assert yes_no_guarded.query_normalization_mode == "yes_no_guarded"
    yes_no_article = get_strategy("doc_first_external_fusion_normalized_yes_no_article")
    assert isinstance(yes_no_article, DocFirstFusionStrategy)
    assert yes_no_article.query_normalization_mode == "yes_no_article"
    yes_no_fusion = get_strategy("doc_first_external_fusion_yes_no_query_fusion")
    assert isinstance(yes_no_fusion, DocFirstFusionStrategy)
    assert yes_no_fusion.query_normalization_mode == "yes_no_fusion"
    assert yes_no_fusion.query_expansion_weight == 0.5
    section_refine = get_strategy("doc_first_external_fusion_section_refine")
    assert isinstance(section_refine, DocFirstFusionStrategy)
    assert section_refine.external_embedding is True
    assert section_refine.section_refine is True
    controlled = get_strategy("doc_first_external_llm_topm_rerank")
    assert isinstance(controlled, DocFirstExternalLlmTopMRerankStrategy)
    scored = get_strategy("doc_first_external_llm_score_rerank")
    assert isinstance(scored, DocFirstExternalLlmScoreRerankStrategy)


def test_controlled_llm_blend_keeps_fusion_candidate_boundary():
    ranked = _blend_fusion_and_llm_ranks(
        ["a", "b", "c"],
        ["external", "c", "b"],
        limit=3,
        llm_weight=0.01,
    )

    assert ranked == ["a", "b", "c"]
    assert "external" not in ranked


def test_score_llm_blend_is_weak_and_bounded():
    ranked = _blend_fusion_and_llm_scores(
        ["a", "b", "c"],
        {"external": 1.0, "c": 1.0, "b": 0.1},
        limit=3,
        llm_weight=0.02,
    )

    assert ranked == ["a", "c", "b"]
    assert "external" not in ranked


def test_score_llm_blend_can_require_high_confidence():
    unchanged = _blend_fusion_and_llm_scores(
        ["a", "b", "c"],
        {"c": 0.91, "b": 0.90},
        limit=3,
        llm_weight=0.08,
        score_threshold=0.9,
        confidence_margin=0.15,
    )
    promoted = _blend_fusion_and_llm_scores(
        ["a", "b", "c"],
        {"c": 0.95, "b": 0.50},
        limit=3,
        llm_weight=0.08,
        score_threshold=0.9,
        confidence_margin=0.15,
    )

    assert unchanged == ["a", "b", "c"]
    assert promoted == ["c", "a", "b"]


def test_combined_llm_note_score_penalizes_background():
    direct = _combined_llm_note_score(_NoteScoreItem(
        id="a",
        direct_answer_score=0.9,
        section_specificity=0.8,
        doc_relevance=0.9,
        background_penalty=0.0,
    ))
    background = _combined_llm_note_score(_NoteScoreItem(
        id="b",
        direct_answer_score=0.6,
        section_specificity=0.2,
        doc_relevance=0.9,
        background_penalty=0.8,
    ))

    assert direct > background
    assert 0.0 <= background <= 1.0


def test_semantic_selector_score_and_blend_are_gated():
    strong = _EvidenceSelectionJudgment(
        candidate_id="c",
        direct_answer_score=5,
        section_specificity=5,
        evidence_sufficiency="sufficient",
        answer_type_match="definition",
        should_be_primary_evidence=True,
    )
    weak = _EvidenceSelectionJudgment(
        candidate_id="b",
        direct_answer_score=2,
        section_specificity=1,
        evidence_sufficiency="background",
        answer_type_match="unclear",
        should_be_primary_evidence=False,
    )

    assert _combined_semantic_selector_score(strong) == 1.0
    assert _combined_semantic_selector_score(weak) < 0.3

    unchanged = _blend_v2_and_semantic_selector(
        ["a", "b", "c"],
        {"c": strong},
        limit=3,
        selector_weight=0.003,
        score_threshold=1.1,
        confidence_margin=0.0,
    )
    promoted = _blend_v2_and_semantic_selector(
        ["a", "b", "c"],
        {"external": strong, "c": strong, "b": weak},
        limit=3,
        selector_weight=0.003,
        score_threshold=0.7,
        confidence_margin=0.0,
    )

    assert unchanged == ["a", "b", "c"]
    assert promoted == ["c", "a", "b"]
    assert "external" not in promoted


def test_semantic_selector_can_require_confidence_margin():
    first = _EvidenceSelectionJudgment(
        candidate_id="b",
        direct_answer_score=5,
        section_specificity=5,
        evidence_sufficiency="sufficient",
        should_be_primary_evidence=True,
    )
    close = _EvidenceSelectionJudgment(
        candidate_id="c",
        direct_answer_score=4.8,
        section_specificity=5,
        evidence_sufficiency="sufficient",
        should_be_primary_evidence=True,
    )

    ranked = _blend_v2_and_semantic_selector(
        ["a", "b", "c"],
        {"b": first, "c": close},
        limit=3,
        selector_weight=0.003,
        score_threshold=0.7,
        confidence_margin=0.12,
    )

    assert ranked == ["a", "b", "c"]


def test_semantic_selector_can_preserve_original_top_k_set():
    outside_top5 = _EvidenceSelectionJudgment(
        candidate_id="f",
        direct_answer_score=5,
        section_specificity=5,
        evidence_sufficiency="sufficient",
        should_be_primary_evidence=True,
    )
    inside_top5 = _EvidenceSelectionJudgment(
        candidate_id="b",
        direct_answer_score=5,
        section_specificity=5,
        evidence_sufficiency="sufficient",
        should_be_primary_evidence=True,
    )

    ranked = _blend_v2_and_semantic_selector(
        ["a", "b", "c", "d", "e", "f"],
        {"b": inside_top5, "f": outside_top5},
        limit=6,
        selector_weight=0.003,
        score_threshold=0.7,
        confidence_margin=0.0,
        preserve_top_k=5,
    )

    assert ranked[0] == "b"
    assert set(ranked[:5]) == {"a", "b", "c", "d", "e"}
    assert ranked[5] == "f"


def test_semantic_policy_application_is_guarded():
    ranked = ["a", "b", "c", "d", "e", "f"]

    no_op, reason = _apply_semantic_policy(
        ranked,
        _EvidenceSelectionPolicy(should_intervene=False, action="no_op"),
        limit=5,
        confidence_threshold=0.7,
        preserve_top_k=5,
    )
    assert no_op == ["a", "b", "c", "d", "e"]
    assert reason == "no_op"

    low_confidence, reason = _apply_semantic_policy(
        ranked,
        _EvidenceSelectionPolicy(
            should_intervene=True,
            action="promote_primary_evidence",
            primary_candidate_id="c",
            confidence=0.3,
        ),
        limit=5,
        confidence_threshold=0.7,
        preserve_top_k=5,
    )
    assert low_confidence == ["a", "b", "c", "d", "e"]
    assert reason == "low_confidence"

    promoted, reason = _apply_semantic_policy(
        ranked,
        _EvidenceSelectionPolicy(
            should_intervene=True,
            action="reorder_within_top5",
            primary_candidate_id="c",
            confidence=0.9,
        ),
        limit=5,
        confidence_threshold=0.7,
        preserve_top_k=5,
    )
    assert promoted == ["c", "a", "b", "d", "e"]
    assert reason == "applied_reorder_within_top_k"

    outside_top5, reason = _apply_semantic_policy(
        ranked,
        _EvidenceSelectionPolicy(
            should_intervene=True,
            action="reorder_within_top5",
            primary_candidate_id="f",
            confidence=0.9,
        ),
        limit=5,
        confidence_threshold=0.7,
        preserve_top_k=5,
    )
    assert outside_top5 == ["a", "b", "c", "d", "e"]
    assert reason == "candidate_outside_preserved_top_k"


def test_semantic_selector_trigger_detects_ambiguous_same_doc_candidates():
    assert _semantic_selector_trigger_reason([
        "ragbench_doc_sec_0",
        "ragbench_doc",
        "ragbench_doc_sec_1",
        "ragbench_other_sec_0",
    ]) == "all_queries"
    assert _semantic_selector_trigger_reason([
        "ragbench_doc",
        "ragbench_doc_sec_4",
        "ragbench_other_sec_0",
    ], mode="triggered_only") == "parent_top_with_specific_sections"
    assert _semantic_selector_trigger_reason([
        "ragbench_doc_sec_0",
        "ragbench_doc_sec_4",
        "ragbench_other_sec_0",
    ], mode="triggered_only", query_text="How does it work?") == "background_top_with_specific_sections"
    assert _semantic_selector_trigger_reason([
        "ragbench_doc_sec_4",
        "ragbench_doc_sec_5",
        "ragbench_other_sec_0",
    ], mode="triggered_only", query_text="How does it work?") is None


def test_open_ragbench_query_normalization_expands_latex_and_yes_no():
    normalized = _normalize_open_ragbench_query(
        r"Does effective temperature \\( T^* \\) relate to temperatures \\( T_c \\) and \\( T_h \\)?"
    )

    assert "\\(" not in normalized
    assert "$" not in normalized
    assert "effective temperature" in normalized
    assert "relate to temperatures" in normalized
    assert "T^*" in normalized
    assert normalized.lower().count("effective temperature") == 2


def test_open_ragbench_query_normalization_modes_are_separable():
    query = r"Does effective temperature \\( T^* \\) relate to temperatures?"

    latex_only = _normalize_open_ragbench_query(query, expand_yes_no=False)
    yes_no_only = _normalize_open_ragbench_query(query, clean_latex=False)

    assert "\\(" not in latex_only
    assert latex_only.lower().count("effective temperature") == 1
    assert "\\(" in yes_no_only
    assert yes_no_only.lower().count("effective temperature") == 2


def test_open_ragbench_compact_yes_no_body_removes_weak_leading_terms():
    compact = _normalize_open_ragbench_query(
        "Does the generic transitivity of an idempotent type imply that it equals its inverse?",
        clean_latex=False,
        compact_yes_no_body=True,
    )
    dummy_it = _normalize_open_ragbench_query(
        "Is it necessary for an agent to consider dependencies?",
        clean_latex=False,
        compact_yes_no_body=True,
    )

    assert compact.endswith(
        "generic transitivity of an idempotent type imply that it equals its inverse"
    )
    assert dummy_it.endswith("necessary for an agent to consider dependencies")


def test_open_ragbench_article_yes_no_body_keeps_dummy_it():
    article = _normalize_open_ragbench_query(
        "Does the generic transitivity of an idempotent type imply that it equals its inverse?",
        clean_latex=False,
        strip_yes_no_article=True,
    )
    dummy_it = _normalize_open_ragbench_query(
        "Is it acceptable for conditions to be generic or arbitrary restrictions?",
        clean_latex=False,
        strip_yes_no_article=True,
    )

    assert article.endswith(
        "generic transitivity of an idempotent type imply that it equals its inverse"
    )
    assert dummy_it.endswith("it acceptable for conditions to be generic or arbitrary restrictions")


def test_open_ragbench_guarded_yes_no_skips_math_and_necessity_modal():
    math_query = r"Does the Block RPCholesky algorithm approximate matrix $\\boldsymbol{A}$?"
    necessity_query = "Is it necessary for an agent to consider dependencies?"
    ordinary_query = "Does Atomas aim to improve efficiency in retrieval tasks?"

    assert _normalize_open_ragbench_query(
        math_query,
        clean_latex=False,
        compact_yes_no_body=True,
        guard_yes_no_body=True,
    ) == math_query.strip(" ?")
    assert _normalize_open_ragbench_query(
        necessity_query,
        clean_latex=False,
        compact_yes_no_body=True,
        guard_yes_no_body=True,
    ) == necessity_query.strip(" ?")
    assert _normalize_open_ragbench_query(
        ordinary_query,
        clean_latex=False,
        compact_yes_no_body=True,
        guard_yes_no_body=True,
    ).endswith("Atomas aim to improve efficiency in retrieval tasks")


def test_structural_ranks_matching_section_or_parent():
    docs = {
        "paper-a": RAGBenchDoc(
            doc_id="paper-a",
            title="Redis cache architecture",
            abstract="This paper studies cache design.",
            sections=[
                "Redis stores hot order data and reduces database pressure.",
                "Unrelated deployment notes.",
            ],
        ),
        "paper-b": RAGBenchDoc(
            doc_id="paper-b",
            title="Payment user interface",
            abstract="This paper studies visual design.",
            sections=["Buttons and colors are evaluated."],
        ),
    }
    queries = [
        RAGBenchQuery(
            query_id="q1",
            query_text="How does Redis reduce database pressure for orders?",
            query_type="abstractive",
            relevant_doc_id="paper-a",
            relevant_section_idx=0,
            answer="Redis stores hot order data.",
        )
    ]

    rankings, relevance = StructuralRetrieverStrategy().evaluate(queries, docs, limit=3, context=_context())

    assert rankings[0][0] == "q1"
    assert rankings[0][1][0] in relevance["q1"]


def test_same_doc_section_refine_promotes_direct_answer_candidate_only():
    docs = {
        "paper-a": RAGBenchDoc(
            doc_id="paper-a",
            title="Redis cache architecture",
            abstract="This paper studies cache design.",
            sections=[
                "# 1 Introduction\nThis section gives background about cache systems and database pressure.",
                "# 2 Result\nWe show Redis stores hot order data and reduces database pressure for orders.",
                "# 3 Appendix\nUnrelated deployment notes.",
            ],
        ),
        "paper-b": RAGBenchDoc(
            doc_id="paper-b",
            title="Payment user interface",
            abstract="This paper studies visual design.",
            sections=["Buttons and colors are evaluated."],
        ),
    }
    graph = _build_structural_index(docs)

    refined = _refine_same_doc_sections(
        "How does Redis reduce database pressure for orders?",
        [
            "ragbench_paper-a_sec_0",
            "ragbench_paper-a",
            "ragbench_paper-b_sec_0",
            "ragbench_paper-a_sec_1",
        ],
        graph,
        limit=4,
        top_docs=1,
        secondary_weight=0.01,
    )

    assert refined[0] == "ragbench_paper-a_sec_1"
    assert "ragbench_paper-a_sec_2" not in refined


def test_passage_helpers_are_bounded_and_cosine_is_normalized():
    text = "First sentence answers the query. " * 80

    passages = _section_passages(text, max_chars=120, overlap_chars=20)

    assert len(passages) > 1
    assert all(len(passage) <= 160 for passage in passages)
    assert _cosine_similarity([1.0, 0.0], [1.0, 0.0]) == 1.0
    assert _cosine_similarity([1.0, 0.0], [0.0, 1.0]) == 0.0
    assert _cosine_similarity([1.0], [1.0, 0.0]) == 0.0


def test_ask_pipeline_ablation_reuses_planner_cache(monkeypatch):
    calls: list[str] = []

    docs = {
        "paper-a": RAGBenchDoc(
            doc_id="paper-a",
            title="Redis cache architecture",
            abstract="This paper studies cache design.",
            sections=["Redis stores hot order data and reduces database pressure."],
        )
    }
    queries = [
        RAGBenchQuery(
            query_id="q1",
            query_text="How does Redis reduce database pressure for orders?",
            query_type="abstractive",
            relevant_doc_id="paper-a",
            relevant_section_idx=0,
            answer="Redis stores hot order data.",
        )
    ]

    def fake_load_benchmark(*, num_queries, seed, corpus_mode):
        return queries, docs

    def fake_plan_retrieval(question, conversation_context, settings):
        calls.append(question)
        return (
            QueryUnderstanding(
                needs_personal_memory=True,
                query_rewrite="redis hot order cache",
                filters=RetrievalFilters(),
            ),
            RetrievalPlan(
                sources=["local"],
                parallel=False,
                query="redis hot order cache",
                sub_queries=[],
                filters=RetrievalFilters(),
            ),
        )

    class FakeStore:
        def find_similar_notes(self, user_id, query, limit=8, filters=None):
            return [
                make_note(
                    id="ragbench_paper-a_sec_0",
                    user_id=user_id,
                    title="Redis",
                    content="Redis stores hot order data.",
                    summary="Redis stores hot order data.",
                    parent_note_id="ragbench_paper-a",
                )
            ]

    def fake_new_eval_store(settings, docs, user_id="ragbench_eval"):
        return FakeStore(), []

    monkeypatch.setattr("evals.open_ragbench.runner.load_benchmark", fake_load_benchmark)
    monkeypatch.setattr("personal_agent.planning.query_planner.plan_retrieval", fake_plan_retrieval)
    monkeypatch.setattr("evals.open_ragbench.runner._new_eval_store", fake_new_eval_store)

    results = run_open_ragbench(
        strategy_names=["ask_pipeline_local_only", "ask_pipeline_no_rewrite"],
        num_queries=1,
        settings=Settings(postgres_url="postgresql://unused"),
        graphiti_manifest_path=None,
    )

    assert calls == ["How does Redis reduce database pressure for orders?"]
    assert results[0].diagnostics[0]["planner"]["cache_hit"] is False
    assert results[1].diagnostics[0]["planner"]["cache_hit"] is True


def test_diagnostic_summary_aggregates_raw_ranks():
    result = BenchmarkRunResult(
        strategy="s",
        description="d",
        report=RetrievalReport(
            num_queries=1,
            mrr=1.0,
            recall_1=1.0,
            recall_3=1.0,
            recall_5=1.0,
            recall_10=1.0,
            ndcg_5=1.0,
            ndcg_10=1.0,
        ),
        elapsed_seconds=0.0,
        num_docs=1,
        num_queries=1,
        corpus_mode="relevant",
        diagnostics=[
            {
                "expected_note_ids": ["ragbench_doc_sec_0", "ragbench_doc"],
                "ranked_ids": ["ragbench_doc_sec_0"],
                "raw_vector_top20_ids": ["ragbench_doc_sec_0"],
                "raw_lexical_top20_ids": [],
                "merged_top20_ids": ["ragbench_doc_sec_0"],
                "expanded_top20_ids": ["ragbench_doc_sec_0", "ragbench_doc"],
                "miss_type": "hit",
            }
        ],
        diagnostic_summary=_summarize_diagnostics([
            {
                "expected_note_ids": ["ragbench_doc_sec_0", "ragbench_doc"],
                "ranked_ids": ["ragbench_doc_sec_0"],
                "raw_vector_top20_ids": ["ragbench_doc_sec_0"],
                "merged_top20_ids": ["ragbench_doc_sec_0"],
                "expanded_top20_ids": ["ragbench_doc_sec_0", "ragbench_doc"],
                "miss_type": "hit",
            }
        ]),
    )

    payload = result.as_dict()

    assert payload["diagnostic_summary"]["miss_type_counts"] == {"hit": 1}
    assert payload["diagnostic_summary"]["raw_vector"]["section_recall_1"] == 1.0


def test_strategy_version_and_config_are_serialized(monkeypatch):
    docs = {
        "paper-a": RAGBenchDoc(
            doc_id="paper-a",
            title="Redis cache architecture",
            abstract="This paper studies cache design.",
            sections=["Redis stores hot order data and reduces database pressure."],
        )
    }
    queries = [
        RAGBenchQuery(
            query_id="q1",
            query_text="Does Redis reduce database pressure?",
            query_type="yes_no",
            relevant_doc_id="paper-a",
            relevant_section_idx=0,
            answer="Yes.",
        )
    ]

    class FakeStore:
        embedding_provider = "openai"
        embedding_model = "BAAI/bge-m3"
        embedding_api_key = "configured"
        last_embedding_provider = "openai_compatible"
        last_embedding_model = "BAAI/bge-m3"
        last_embedding_original_dimensions = 1024
        last_embedding_output_dimensions = 1024
        last_embedding_index_dimensions = 1024
        last_embedding_used_fallback = False
        last_embedding_fallback_reason = None
        last_retrieval_debug = {
            "raw_vector_ids": ["ragbench_paper-a_sec_0"],
            "merged_ids": ["ragbench_paper-a_sec_0"],
            "result_count": 1,
        }

        def find_similar_notes(self, user_id, query, limit=8, filters=None):
            return [
                make_note(
                    id="ragbench_paper-a_sec_0",
                    user_id=user_id,
                    title="Redis",
                    content="Redis stores hot order data.",
                    summary="Redis stores hot order data.",
                    parent_note_id="ragbench_paper-a",
                )
            ]

    def fake_load_benchmark(*, num_queries, seed, corpus_mode):
        return queries, docs

    def fake_new_eval_store(settings, docs, user_id="ragbench_eval"):
        return FakeStore(), []

    monkeypatch.setattr("evals.open_ragbench.runner.load_benchmark", fake_load_benchmark)
    monkeypatch.setattr("evals.open_ragbench.runner._new_eval_store", fake_new_eval_store)

    result = run_open_ragbench(
        strategy_names=["ask_retrieve_high_accuracy"],
        num_queries=1,
        settings=Settings(postgres_url="postgresql://unused"),
        graphiti_manifest_path=None,
    )[0].as_dict()

    config = result["strategy_config"]
    diag = result["diagnostics"][0]
    assert result["strategy_version"] == "high_accuracy_v2"
    assert config["doc_first_enabled"] is True
    assert config["doc_first_weight"] == 0.2
    assert config["embedding_dim"] == 1024
    assert config["query_expansion_mode"] == "yes_no_guarded"
    assert config["section_refine_enabled"] is True
    assert config["section_refine_mode"] == "passage_embedding"
    assert config["section_refine_weight"] == 0.02
    assert diag["strategy_version"] == "high_accuracy_v2"
    assert diag["strategy_config"]["query_expansion_mode"] == "yes_no_guarded"


def test_semantic_selector_strategy_records_judgments_and_rank_delta(monkeypatch):
    docs = {
        "paper-a": RAGBenchDoc(
            doc_id="paper-a",
            title="Redis cache architecture",
            abstract="This paper studies cache design.",
            sections=[
                "# 1 Introduction\nBackground about cache systems.",
                "# 2 Result\nRedis stores hot order data and reduces database pressure.",
            ],
        )
    }
    queries = [
        RAGBenchQuery(
            query_id="q1",
            query_text="How does Redis reduce database pressure?",
            query_type="abstractive",
            relevant_doc_id="paper-a",
            relevant_section_idx=1,
            answer="Redis stores hot order data.",
        )
    ]
    fixed_v2 = [
        "ragbench_paper-a_sec_0",
        "ragbench_paper-a_sec_1",
        "ragbench_paper-a",
    ]

    class FakeStore:
        embedding_provider = "openai"
        embedding_model = "BAAI/bge-m3"
        embedding_api_key = "configured"
        last_embedding_provider = "openai_compatible"
        last_embedding_model = "BAAI/bge-m3"
        last_embedding_original_dimensions = 1024
        last_embedding_output_dimensions = 1024
        last_embedding_index_dimensions = 1024
        last_embedding_used_fallback = False
        last_embedding_fallback_reason = None
        last_retrieval_debug = {
            "raw_vector_ids": fixed_v2,
            "merged_ids": fixed_v2,
            "result_count": 3,
        }

        def find_similar_notes(self, user_id, query, limit=8, filters=None):
            return [
                make_note(
                    id="ragbench_paper-a_sec_0",
                    user_id=user_id,
                    title="Intro",
                    content="Background about cache systems.",
                    parent_note_id="ragbench_paper-a",
                ),
                make_note(
                    id="ragbench_paper-a",
                    user_id=user_id,
                    title="Redis paper",
                    content="This paper studies cache design.",
                ),
                make_note(
                    id="ragbench_paper-a_sec_1",
                    user_id=user_id,
                    title="Result",
                    content="Redis stores hot order data and reduces database pressure.",
                    parent_note_id="ragbench_paper-a",
                ),
            ]

    class FakeResponse:
        def __init__(self, value):
            self.value = value
            self.model = "fake-semantic-model"
            self.retry_attempts = 1
            self.retry_errors = ["transient"]

    class FakeModelClient:
        def generate(self, request):
            return FakeResponse(type("Value", (), {
                "judgments": [
                    _EvidenceSelectionJudgment(
                        candidate_id="ragbench_paper-a_sec_1",
                        direct_answer_score=5,
                        section_specificity=5,
                        evidence_sufficiency="sufficient",
                        answer_type_match="method",
                        should_be_primary_evidence=True,
                        rationale="Directly answers.",
                    ),
                    _EvidenceSelectionJudgment(
                        candidate_id="ragbench_paper-a_sec_0",
                        direct_answer_score=1,
                        section_specificity=1,
                        evidence_sufficiency="background",
                        answer_type_match="unclear",
                        should_be_primary_evidence=False,
                    ),
                ]
            })())

    def fake_load_benchmark(*, num_queries, seed, corpus_mode):
        return queries, docs

    def fake_new_eval_store(settings, docs, user_id="ragbench_eval"):
        notes = FakeStore().find_similar_notes(user_id, "", limit=3)
        return FakeStore(), notes

    monkeypatch.setattr("evals.open_ragbench.runner.load_benchmark", fake_load_benchmark)
    monkeypatch.setattr("evals.open_ragbench.runner._new_eval_store", fake_new_eval_store)
    monkeypatch.setattr(
        "evals.open_ragbench.runner._refine_same_doc_sections_by_passage_embedding",
        lambda *args, **kwargs: fixed_v2,
    )
    monkeypatch.setattr(
        "personal_agent.infra.structured_model.build_structured_model_client",
        lambda config, observability: FakeModelClient(),
    )

    result = run_open_ragbench(
        strategy_names=["ask_retrieve_high_accuracy_semantic_selector"],
        num_queries=1,
        settings=Settings(postgres_url="postgresql://unused"),
        graphiti_manifest_path=None,
    )[0].as_dict()

    diag = result["diagnostics"][0]
    assert result["strategy_version"] == "high_accuracy_v2_semantic_selector_all_queries_v1"
    assert result["strategy_config"]["llm_rerank_mode"] == "semantic_selector"
    assert result["strategy_config"]["semantic_selector_trigger_mode"] == "all_queries"
    assert diag["ranked_ids"][0] == "ragbench_paper-a_sec_1"
    assert diag["semantic_selector_trigger_mode"] == "all_queries"
    assert diag["semantic_selector_trigger_reason"] == "all_queries"
    assert diag["semantic_selector_response_model"] == "fake-semantic-model"
    assert diag["semantic_selector_retry_attempts"] == 1
    assert diag["semantic_selector_judgments"]["ragbench_paper-a_sec_1"]["combined_score"] == 1.0
    assert result["diagnostic_summary"]["semantic_selector"]["effect_counts"]["improved"] == 1
    assert result["diagnostic_summary"]["semantic_selector"]["trigger_mode_counts"]["all_queries"] == 1
    assert result["diagnostic_summary"]["semantic_selector"]["response_model_counts"] == {"fake-semantic-model": 1}


def test_semantic_selector_triggered_only_skips_stable_specific_top_rank(monkeypatch):
    docs = {
        "paper-a": RAGBenchDoc(
            doc_id="paper-a",
            title="Redis cache architecture",
            abstract="This paper studies cache design.",
            sections=[
                "# 1 Introduction\nBackground about cache systems.",
                "# 2 Setup\nSystem setup.",
                "# 3 Result\nRedis stores hot order data and reduces database pressure.",
                "# 4 Details\nImplementation details.",
            ],
        )
    }
    queries = [
        RAGBenchQuery(
            query_id="q1",
            query_text="How does Redis reduce database pressure?",
            query_type="abstractive",
            relevant_doc_id="paper-a",
            relevant_section_idx=2,
            answer="Redis stores hot order data.",
        )
    ]
    fixed_v2 = [
        "ragbench_paper-a_sec_2",
        "ragbench_paper-a_sec_3",
        "ragbench_paper-a",
    ]

    class FakeStore:
        embedding_provider = "openai"
        embedding_model = "BAAI/bge-m3"
        embedding_api_key = "configured"
        last_embedding_provider = "openai_compatible"
        last_embedding_model = "BAAI/bge-m3"
        last_embedding_original_dimensions = 1024
        last_embedding_output_dimensions = 1024
        last_embedding_index_dimensions = 1024
        last_embedding_used_fallback = False
        last_embedding_fallback_reason = None
        last_retrieval_debug = {
            "raw_vector_ids": fixed_v2,
            "merged_ids": fixed_v2,
            "result_count": 3,
        }

        def find_similar_notes(self, user_id, query, limit=8, filters=None):
            return [
                make_note(
                    id="ragbench_paper-a_sec_2",
                    user_id=user_id,
                    title="Result",
                    content="Redis stores hot order data and reduces database pressure.",
                    parent_note_id="ragbench_paper-a",
                ),
                make_note(
                    id="ragbench_paper-a_sec_3",
                    user_id=user_id,
                    title="Details",
                    content="Implementation details.",
                    parent_note_id="ragbench_paper-a",
                ),
                make_note(
                    id="ragbench_paper-a",
                    user_id=user_id,
                    title="Redis paper",
                    content="This paper studies cache design.",
                ),
            ]

    class FailingModelClient:
        def generate(self, request):
            raise AssertionError("triggered-only should skip stable specific top ranks")

    def fake_load_benchmark(*, num_queries, seed, corpus_mode):
        return queries, docs

    def fake_new_eval_store(settings, docs, user_id="ragbench_eval"):
        notes = FakeStore().find_similar_notes(user_id, "", limit=3)
        return FakeStore(), notes

    monkeypatch.setattr("evals.open_ragbench.runner.load_benchmark", fake_load_benchmark)
    monkeypatch.setattr("evals.open_ragbench.runner._new_eval_store", fake_new_eval_store)
    monkeypatch.setattr(
        "evals.open_ragbench.runner._refine_same_doc_sections_by_passage_embedding",
        lambda *args, **kwargs: fixed_v2,
    )
    monkeypatch.setattr(
        "personal_agent.infra.structured_model.build_structured_model_client",
        lambda config, observability: FailingModelClient(),
    )

    result = run_open_ragbench(
        strategy_names=["ask_retrieve_high_accuracy_semantic_selector_triggered_only"],
        num_queries=1,
        settings=Settings(postgres_url="postgresql://unused"),
        graphiti_manifest_path=None,
    )[0].as_dict()

    diag = result["diagnostics"][0]
    summary = result["diagnostic_summary"]["semantic_selector"]
    assert result["strategy_version"] == "high_accuracy_v2_semantic_selector_triggered_only_preserve_top5_v1"
    assert result["strategy_config"]["semantic_selector_trigger_mode"] == "triggered_only"
    assert result["strategy_config"]["semantic_selector_preserve_top_k"] == 5
    assert diag["semantic_selector_trigger_mode"] == "triggered_only"
    assert diag["semantic_selector_preserve_top_k"] == 5
    assert diag["semantic_selector_trigger_reason"] is None
    assert diag["semantic_selector_skipped_reason"] == "no_semantic_ambiguity"
    assert diag["semantic_selector_judgments"] == {}
    assert summary["triggered_queries"] == 0
    assert summary["skipped_counts"]["no_semantic_ambiguity"] == 1
    assert summary["trigger_mode_counts"]["triggered_only"] == 1
    assert summary["preserve_top_k_counts"]["5"] == 1


def test_semantic_policy_selector_records_policy_and_rank_delta(monkeypatch):
    docs = {
        "paper-a": RAGBenchDoc(
            doc_id="paper-a",
            title="Redis cache architecture",
            abstract="This paper studies cache design.",
            sections=[
                "# 1 Introduction\nBackground about cache systems.",
                "# 2 Result\nRedis stores hot order data and reduces database pressure.",
            ],
        )
    }
    queries = [
        RAGBenchQuery(
            query_id="q1",
            query_text="How does Redis reduce database pressure?",
            query_type="abstractive",
            relevant_doc_id="paper-a",
            relevant_section_idx=1,
            answer="Redis stores hot order data.",
        )
    ]
    fixed_v2 = [
        "ragbench_paper-a_sec_0",
        "ragbench_paper-a_sec_1",
        "ragbench_paper-a",
    ]

    class FakeStore:
        embedding_provider = "openai"
        embedding_model = "BAAI/bge-m3"
        embedding_api_key = "configured"
        last_embedding_provider = "openai_compatible"
        last_embedding_model = "BAAI/bge-m3"
        last_embedding_original_dimensions = 1024
        last_embedding_output_dimensions = 1024
        last_embedding_index_dimensions = 1024
        last_embedding_used_fallback = False
        last_embedding_fallback_reason = None
        last_retrieval_debug = {
            "raw_vector_ids": fixed_v2,
            "merged_ids": fixed_v2,
            "result_count": 3,
        }

        def find_similar_notes(self, user_id, query, limit=8, filters=None):
            return [
                make_note(
                    id="ragbench_paper-a_sec_0",
                    user_id=user_id,
                    title="Intro",
                    content="Background about cache systems.",
                    parent_note_id="ragbench_paper-a",
                ),
                make_note(
                    id="ragbench_paper-a_sec_1",
                    user_id=user_id,
                    title="Result",
                    content="Redis stores hot order data and reduces database pressure.",
                    parent_note_id="ragbench_paper-a",
                ),
                make_note(
                    id="ragbench_paper-a",
                    user_id=user_id,
                    title="Redis paper",
                    content="This paper studies cache design.",
                ),
            ]

    class FakeResponse:
        def __init__(self, value):
            self.value = value
            self.model = "fake-policy-model"
            self.retry_attempts = 0
            self.retry_errors = []

    class FakeModelClient:
        def generate(self, request):
            return FakeResponse(type("Value", (), {
                "policy": _EvidenceSelectionPolicy(
                    should_intervene=True,
                    ambiguity_type="direct_answer_vs_background",
                    action="reorder_within_top5",
                    primary_candidate_id="ragbench_paper-a_sec_1",
                    confidence=0.91,
                    rationale="Result section directly answers.",
                )
            })())

    def fake_load_benchmark(*, num_queries, seed, corpus_mode):
        return queries, docs

    def fake_new_eval_store(settings, docs, user_id="ragbench_eval"):
        notes = FakeStore().find_similar_notes(user_id, "", limit=3)
        return FakeStore(), notes

    monkeypatch.setattr("evals.open_ragbench.runner.load_benchmark", fake_load_benchmark)
    monkeypatch.setattr("evals.open_ragbench.runner._new_eval_store", fake_new_eval_store)
    monkeypatch.setattr(
        "evals.open_ragbench.runner._refine_same_doc_sections_by_passage_embedding",
        lambda *args, **kwargs: fixed_v2,
    )
    monkeypatch.setattr(
        "personal_agent.infra.structured_model.build_structured_model_client",
        lambda config, observability: FakeModelClient(),
    )

    result = run_open_ragbench(
        strategy_names=["ask_retrieve_high_accuracy_semantic_policy_selector"],
        num_queries=1,
        settings=Settings(postgres_url="postgresql://unused"),
        graphiti_manifest_path=None,
    )[0].as_dict()

    diag = result["diagnostics"][0]
    summary = result["diagnostic_summary"]["semantic_policy"]
    assert result["strategy_version"] == "high_accuracy_v2_semantic_policy_selector_v1"
    assert result["strategy_config"]["llm_rerank_mode"] == "semantic_policy_selector"
    assert diag["ranked_ids"][0] == "ragbench_paper-a_sec_1"
    assert diag["semantic_policy_response_model"] == "fake-policy-model"
    assert diag["semantic_policy"]["action"] == "reorder_within_top5"
    assert diag["semantic_policy_applied_reason"] == "applied_reorder_within_top_k"
    assert summary["response_model_counts"] == {"fake-policy-model": 1}
    assert summary["action_counts"] == {"reorder_within_top5": 1}
    assert summary["effect_counts"]["improved"] == 1


def test_diagnostic_summary_counts_final_drop_reasons():
    enriched = _enrich_eval_snapshot({
        "expected_note_ids": ["ragbench_doc_sec_0", "ragbench_doc"],
        "ranked_ids": ["ragbench_other_sec_0"],
        "context_dropped_evidence_ids": ["ragbench_doc_sec_0"],
        "context_dropped_evidence_reasons": [
            {"source_id": "ragbench_doc_sec_0", "drop_reason": "char_budget"}
        ],
    })
    summary = _summarize_diagnostics([
        {
            "expected_note_ids": ["ragbench_doc_sec_0", "ragbench_doc"],
            "ranked_ids": ["ragbench_other_sec_0"],
            "raw_vector_top20_ids": ["ragbench_doc_sec_0"],
            "merged_top20_ids": ["ragbench_doc_sec_0"],
            "expanded_top20_ids": ["ragbench_doc_sec_0"],
            "context_dropped_evidence_ids": ["ragbench_doc_sec_0"],
            "context_dropped_evidence_reasons": [
                {"source_id": "ragbench_doc_sec_0", "drop_reason": "char_budget"}
            ],
            "miss_type": "budget_or_mmr_drop",
            "final_drop_reason": "char_budget_drop",
        }
    ])

    assert enriched["final_drop_reason"] == "char_budget_drop"
    assert summary["final_drop_reason_counts"] == {"char_budget_drop": 1}


def test_diagnostic_summary_reports_doc_top1_section_gaps():
    summary = _summarize_diagnostics([
        {
            "query_id": "q1",
            "query_text": "which section answers?",
            "expected_note_ids": ["ragbench_doc_sec_4", "ragbench_doc"],
            "ranked_ids": [
                "ragbench_doc_sec_1",
                "ragbench_doc",
                "ragbench_doc_sec_2",
                "ragbench_doc_sec_4",
            ],
            "miss_type": "hit",
        },
        {
            "query_id": "q2",
            "query_text": "direct hit",
            "expected_note_ids": ["ragbench_doc2_sec_0", "ragbench_doc2"],
            "ranked_ids": ["ragbench_doc2_sec_0", "ragbench_doc2"],
            "miss_type": "hit",
        },
    ])

    gaps = summary["section_gap_analysis"]
    assert gaps["observed_queries"] == 2
    assert gaps["doc_top1_count"] == 2
    assert gaps["doc_top1_section_below_top3_count"] == 1
    assert gaps["doc_top1_section_below_top3_rate"] == 0.5
    assert gaps["doc_top1_gap_cases"][0]["query_id"] == "q1"
    assert gaps["same_doc_wrong_section_cases"][0]["same_doc_wrong_top5_ids"] == [
        "ragbench_doc_sec_1",
        "ragbench_doc_sec_2",
    ]


def test_final_drop_reason_splits_projection_shadow():
    enriched = _enrich_eval_snapshot({
        "expected_note_ids": ["ragbench_doc_sec_0", "ragbench_doc"],
        "ranked_ids": ["ragbench_doc_sec_1"],
        "context_selected_evidence_ids": ["ragbench_doc_sec_0"],
        "selected_match_ids": ["ragbench_doc_sec_1"],
    })

    assert enriched["final_drop_reason"] == "same_doc_projection_shadow"
    assert enriched["section_drop_reason"] == "same_doc_projection_shadow"


def test_section_drop_reason_tracks_parent_child_projection():
    enriched = _enrich_eval_snapshot({
        "expected_note_ids": ["ragbench_doc_sec_0", "ragbench_doc"],
        "ranked_ids": ["ragbench_doc"],
        "context_selected_evidence_ids": ["ragbench_doc_sec_0"],
    })
    summary = _summarize_diagnostics([enriched])

    assert enriched["final_drop_reason"] is None
    assert enriched["section_drop_reason"] == "parent_replaced_child"
    assert summary["section_drop_reason_counts"] == {"parent_replaced_child": 1}


def test_diagnostic_summary_aggregates_llm_score_rank_delta():
    summary = _summarize_diagnostics([
        {
            "query_id": "q1",
            "query_text": "rescued",
            "expected_note_ids": ["ragbench_doc_sec_0", "ragbench_doc"],
            "ranked_ids": ["ragbench_doc_sec_0", "other"],
            "fusion_before_llm_top20_ids": ["other", "ragbench_doc_sec_0"],
            "llm_scored_top20_ids": ["ragbench_doc_sec_0", "other"],
            "llm_score_values": {"ragbench_doc_sec_0": 0.95, "other": 0.1},
            "llm_rerank_model_configured": True,
            "llm_score_threshold": 0.9,
            "llm_score_confidence_margin": 0.15,
            "miss_type": "hit",
            "llm_score_rank_delta": {
                "fusion_any_rank": 2,
                "llm_scored_any_rank": 1,
                "final_any_rank": 1,
                "score_any_delta": 1,
                "final_any_delta": 1,
                "score_any_effect": "improved",
                "final_any_effect": "improved",
                "fusion_section_rank": 2,
                "llm_scored_section_rank": 1,
                "final_section_rank": 1,
                "score_section_delta": 1,
                "final_section_delta": 1,
                "score_section_effect": "improved",
                "final_section_effect": "improved",
            },
        },
        {
            "query_id": "q2",
            "query_text": "harmed",
            "expected_note_ids": ["ragbench_doc2_sec_12", "ragbench_doc2"],
            "ranked_ids": ["other", "ragbench_doc2_sec_12"],
            "fusion_before_llm_top20_ids": ["ragbench_doc2_sec_12", "other"],
            "llm_scored_top20_ids": ["other", "ragbench_doc2_sec_12"],
            "llm_score_values": {"ragbench_doc2_sec_12": 0.8},
            "llm_rerank_model_configured": True,
            "llm_score_threshold": 0.9,
            "llm_score_confidence_margin": 0.15,
            "miss_type": "hit",
            "llm_score_rank_delta": {
                "fusion_any_rank": 1,
                "llm_scored_any_rank": 2,
                "final_any_rank": 2,
                "score_any_delta": -1,
                "final_any_delta": -1,
                "score_any_effect": "harmed",
                "final_any_effect": "harmed",
                "fusion_section_rank": 1,
                "llm_scored_section_rank": 2,
                "final_section_rank": 2,
                "score_section_delta": -1,
                "final_section_delta": -1,
                "score_section_effect": "harmed",
                "final_section_effect": "harmed",
            },
        },
        {
            "query_id": "q3",
            "query_text": "Is this skipped?",
            "expected_note_ids": ["ragbench_doc3_sec_1", "ragbench_doc3"],
            "ranked_ids": ["ragbench_doc3_sec_1"],
            "fusion_before_llm_top20_ids": ["ragbench_doc3_sec_1"],
            "llm_score_skipped_reason": "query_type:yes_no",
            "llm_rerank_model_configured": True,
            "miss_type": "hit",
        },
    ])

    delta = summary["llm_score_rank_delta"]

    assert delta["observed_queries"] == 2
    assert delta["final_any_effect_counts"] == {"improved": 1, "harmed": 1}
    assert delta["mean_final_any_delta"] == 0.0
    assert delta["rescued_query_type_counts"] == {"other": 1}
    assert delta["harmed_query_type_counts"] == {"other": 1}
    assert delta["rescued_fusion_rank_bucket_counts"] == {"top3": 1}
    assert delta["harmed_fusion_rank_bucket_counts"] == {"top1": 1}
    assert delta["rescued_gold_section_bucket_counts"] == {"sec0": 1}
    assert delta["harmed_gold_section_bucket_counts"] == {"late_sec11_plus": 1}
    assert delta["rescued_cases"][0]["query_id"] == "q1"
    assert delta["harmed_cases"][0]["query_id"] == "q2"
    assert summary["llm_score_health"]["observed_queries"] == 3
    assert summary["llm_score_health"]["full_score_coverage_rate"] == 0.3333
    assert summary["llm_score_health"]["skipped_counts"] == {"query_type:yes_no": 1}
