from __future__ import annotations

from personal_agent.kernel.config import Settings
from tests.note_factory import make_note

from evals.galileo_ragbench.adapter import (
    corpus_to_notes,
    relevance_by_query,
    sentence_note_id,
)
from evals.galileo_ragbench.loader import GalileoExample, GalileoSentence, _row_to_example
from evals.galileo_ragbench.runner import (
    ProductionSupportSentenceStrategy,
    SharedEvidenceSelectorSentenceStrategy,
    get_strategy,
    run_galileo_ragbench,
)


def _example() -> GalileoExample:
    return GalileoExample(
        query_id="covidqa_test_1",
        question="Which virus is cleared?",
        dataset_name="covidqa_test",
        subset="covidqa",
        split="test",
        documents=("Title: Doc A Passage: Alpha virus background. Beta is cleared.",),
        sentences=(
            GalileoSentence(key="0a", text="Title: Doc A", document_index=0),
            GalileoSentence(key="0b", text="Alpha virus background.", document_index=0),
            GalileoSentence(key="0c", text="Beta is cleared by antiviral response.", document_index=0),
        ),
        relevant_sentence_keys=("0b", "0c"),
        utilized_sentence_keys=("0c",),
    )


def test_row_to_example_parses_sentence_labels():
    row = {
        "id": "42",
        "question": "What is supported?",
        "dataset_name": "covidqa_test",
        "documents": ["Doc zero", "Doc one"],
        "documents_sentences": [
            [["0a", "Doc zero title"], ["0b", "Doc zero evidence"]],
            [["1a", "Doc one title"]],
        ],
        "all_relevant_sentence_keys": ["0b", "1a"],
        "all_utilized_sentence_keys": ["0b"],
        "response": "answer",
        "adherence_score": True,
        "relevance_score": 0.5,
        "utilization_score": 1.0,
        "completeness_score": 0.25,
    }

    example = _row_to_example(row, subset="covidqa", split="test")

    assert example.query_id == "covidqa_test_42"
    assert example.documents == ("Doc zero", "Doc one")
    assert [sentence.key for sentence in example.sentences] == ["0a", "0b", "1a"]
    assert example.sentences[2].document_index == 1
    assert example.relevant_sentence_keys == ("0b", "1a")
    assert example.utilized_sentence_keys == ("0b",)


def test_adapter_maps_relevant_and_utilized_sentence_notes():
    example = _example()

    notes = corpus_to_notes([example])
    relevant = relevance_by_query([example], mode="relevant")
    utilized = relevance_by_query([example], mode="utilized")

    assert any(note.id.endswith("_doc_0") for note in notes)
    assert sentence_note_id(example.query_id, "0c") in {note.id for note in notes}
    assert relevant[example.query_id] == {
        sentence_note_id(example.query_id, "0b"),
        sentence_note_id(example.query_id, "0c"),
    }
    assert utilized[example.query_id] == {sentence_note_id(example.query_id, "0c")}


def test_galileo_runner_profiles_are_registered():
    keyword = get_strategy("galileo_keyword_sentence")
    lexical_doc_first = get_strategy("galileo_doc_first_lexical")
    external = get_strategy("galileo_external_sentence_embedding")
    open_like = get_strategy("galileo_open_like_doc_first_fusion")
    profile = get_strategy("galileo_profile_sentence_embedding")
    support = get_strategy("galileo_production_support_sentence")
    shared = get_strategy("galileo_shared_evidence_selector")
    shared_embedding = get_strategy("galileo_shared_embedding_evidence_selector")
    shared_policy = get_strategy("galileo_shared_evidence_policy_selector")

    assert keyword.name == "galileo_keyword_sentence"
    assert lexical_doc_first.name == "galileo_doc_first_lexical"
    assert external.name == "galileo_external_sentence_embedding"
    assert open_like.name == "galileo_open_like_doc_first_fusion"
    assert profile.name == "galileo_profile_sentence_embedding"
    assert isinstance(support, ProductionSupportSentenceStrategy)
    assert isinstance(shared, SharedEvidenceSelectorSentenceStrategy)
    assert isinstance(shared_embedding, SharedEvidenceSelectorSentenceStrategy)
    assert isinstance(shared_policy, SharedEvidenceSelectorSentenceStrategy)
    assert shared.external_embedding is False
    assert shared_embedding.external_embedding is True
    assert shared_policy.use_policy_selector is True


def test_galileo_profile_runner_records_sentence_level_metrics(monkeypatch):
    example = _example()
    sent_0b = sentence_note_id(example.query_id, "0b")
    sent_0c = sentence_note_id(example.query_id, "0c")

    class FakeStore:
        last_retrieval_debug = {"result_count": 3}

        def find_similar_notes(self, user_id, query, limit=10, filters=None):
            return [
                make_note(id=sent_0c, user_id=user_id, content="Beta is cleared."),
                make_note(id="galileo_covidqa_test_1_doc_0", user_id=user_id, content="Document"),
                make_note(id=sent_0b, user_id=user_id, content="Alpha background."),
            ]

    def fake_load_examples(**kwargs):
        return [example]

    def fake_new_eval_store(settings, examples):
        notes = corpus_to_notes(examples)
        return FakeStore(), notes

    monkeypatch.setattr("evals.galileo_ragbench.runner.load_examples", fake_load_examples)
    monkeypatch.setattr("evals.galileo_ragbench.runner._new_eval_store", fake_new_eval_store)

    results = run_galileo_ragbench(
        strategy_names=[
            "galileo_keyword_sentence",
            "galileo_production_support_sentence",
            "galileo_shared_evidence_selector",
            "galileo_shared_evidence_policy_selector",
            "galileo_profile_sentence_embedding",
            "galileo_open_like_doc_first_fusion",
        ],
        num_queries=1,
        settings=Settings(postgres_url="postgresql://unused"),
    )

    keyword = results[0].as_dict()
    support = results[1].as_dict()
    shared = results[2].as_dict()
    shared_policy = results[3].as_dict()
    profile = results[4].as_dict()
    open_like = results[5].as_dict()

    assert keyword["strategy_config"]["retrieval_backend"] == "lexical"
    assert support["strategy_config"]["production_support_reranker"] is True
    assert support["strategy_config"]["doc_first_enabled"] is False
    assert support["strategy_config"]["slot_refine_enabled"] is False
    assert support["utilized_metrics"]["recall_1"] == 1.0
    assert shared["strategy_config"]["shared_evidence_selector"] is True
    assert shared["strategy_config"]["doc_first_enabled"] is False
    assert shared["metrics"]["recall_1"] == 0.5
    assert shared_policy["strategy_config"]["shared_policy_selector_enabled"] is True
    assert shared_policy["strategy_config"]["doc_first_enabled"] is False
    assert profile["strategy_config"]["strategy_profile"] == "galileo_ragbench"
    assert profile["strategy_config"]["doc_first_enabled"] is False
    assert profile["metrics"]["recall_1"] == 0.5
    assert profile["utilized_metrics"]["recall_1"] == 1.0
    assert open_like["strategy_config"]["strategy_profile"] == "open_ragbench"
    assert open_like["strategy_config"]["doc_first_enabled"] is True
