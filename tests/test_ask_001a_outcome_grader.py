from hashlib import sha256
from pathlib import Path

from evals.e2e_quality.ask_001a_outcome import (
    ASK_001A_GRADER_VERSION,
    Ask001AControlDataset,
    grade_ask_001a_answer,
)


_CONTROLS = (
    Path(__file__).resolve().parents[1]
    / "evals"
    / "e2e_quality"
    / "ask_001a_outcome_controls.json"
)
_CONTROL_SHA256 = "d1525a001d411e41406570ef31c3b53cf7900892015b2804c7173a734650d915"


def test_ask_001a_outcome_grader_accepts_variants_and_rejects_missing_sources() -> None:
    payload = _CONTROLS.read_bytes()
    assert sha256(payload).hexdigest() == _CONTROL_SHA256
    controls = Ask001AControlDataset.model_validate_json(payload)
    assert controls.grader_version == ASK_001A_GRADER_VERSION

    observed = {
        case.case_id: grade_ask_001a_answer(
            answer=case.answer,
            expected_passages=controls.expected_passages,
        ).passed
        for case in controls.cases
    }

    assert observed == {
        case.case_id: case.expected_passed
        for case in controls.cases
    }
