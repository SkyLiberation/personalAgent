from .metrics import (
    ordered_subsequence,
    reference_recall,
    response_contains,
    resume_success,
    thread_continuity,
)


def test_ordered_subsequence_allows_intermediate_events():
    assert ordered_subsequence(["a", "noise", "b"], ["a", "b"]) == 1.0
    assert ordered_subsequence(["b", "a"], ["a", "b"]) == 0.0


def test_reference_recall_scores_missing_history():
    assert reference_recall([0, 2], [0, 1]) == 0.5
    assert reference_recall([], []) == 1.0


def test_response_contains_is_case_insensitive():
    assert response_contains("DNS resolves names", ["dns", "names"]) == 1.0
    assert response_contains("DNS", ["DNS", "IP"]) == 0.5


def test_resume_requires_same_run_and_terminal_completion():
    assert resume_success("resume", "r1", "r1", "ready", True) == 1.0
    assert resume_success("resume", "r2", "r1", "ready", True) == 0.0
    assert resume_success("resume", "r1", "r1", "clarify", False) == 0.0


def test_thread_continuity_rejects_forked_or_missing_thread():
    assert thread_continuity(["t1", "t1"], True) == 1.0
    assert thread_continuity(["t1", "t2"], True) == 0.0
    assert thread_continuity(["t1", ""], True) == 0.0
