from __future__ import annotations

import json

from personal_agent.application.conversation.observation_bounds import (
    MAX_OBSERVATION_PAYLOAD_CHARS,
    bound_observation_payload,
    excerpt_payload_text,
    select_offload_text,
    serialized_length,
)


def _mcp_file_payload(body: str) -> dict[str, object]:
    """The shape a real MCP file read returns: the body repeated under ``raw``."""

    content = [
        {"type": "text", "text": "successfully downloaded text file"},
        {"type": "resource", "resource": {"text": body, "uri": "repo://o/r/MAINTAINERS"}},
    ]
    return {
        "ok": True,
        "data": {"content": content, "raw": {"content": content}, "provider": "mcp"},
    }


def test_small_payload_passes_through_untouched() -> None:
    payload = {"ok": True, "data": {"text": "short"}}
    bounded = bound_observation_payload(payload)
    assert bounded.payload is payload
    assert not bounded.is_bounded
    assert bounded.omitted_chars == 0


def test_single_huge_string_is_bounded_and_reports_omission() -> None:
    payload = {"ok": True, "data": {"text": "x" * 2_000_000}}
    bounded = bound_observation_payload(payload)
    assert bounded.is_bounded
    assert serialized_length(bounded.payload) <= MAX_OBSERVATION_PAYLOAD_CHARS
    assert bounded.original_chars > 2_000_000 - 1
    assert bounded.omitted_chars > 0
    assert "characters omitted" in bounded.payload["data"]["text"]


def test_bounding_keeps_head_and_tail_not_head_only() -> None:
    text = "HEAD" + ("m" * 500_000) + "TAIL"
    bounded = bound_observation_payload({"text": text})
    kept = bounded.payload["text"]
    assert kept.startswith("HEAD")
    assert kept.endswith("TAIL")


def test_many_medium_strings_are_bounded_too() -> None:
    payload = {"ok": True, "items": [{"body": "y" * 5_000} for _ in range(400)]}
    assert serialized_length(payload) > MAX_OBSERVATION_PAYLOAD_CHARS
    bounded = bound_observation_payload(payload)
    assert bounded.is_bounded
    assert serialized_length(bounded.payload) <= MAX_OBSERVATION_PAYLOAD_CHARS
    # structure had to be given up, but status stays readable
    assert bounded.payload["ok"] is True
    assert bounded.payload["excerpt_is_serialized_text"] is True


def test_shapes_that_defeat_per_string_bounding_still_fit() -> None:
    shapes = (
        {"items": ["z" * 300 for _ in range(5_000)]},
        {str(index): "w" * 500 for index in range(2_000)},
        {"nested": [[{"k": "v" * 400} for _ in range(50)] for _ in range(50)]},
        {"deep": {"a": {"b": {"c": ["q" * 450 for _ in range(3_000)]}}}},
    )
    for payload in shapes:
        bounded = bound_observation_payload(payload)
        assert serialized_length(bounded.payload) <= MAX_OBSERVATION_PAYLOAD_CHARS
        assert bounded.omitted_chars > 0


def test_non_string_leaves_survive_bounding() -> None:
    payload = {"n": 7, "flag": False, "none": None, "big": "z" * 100_000}
    bounded = bound_observation_payload(payload)
    assert bounded.payload["n"] == 7
    assert bounded.payload["flag"] is False
    assert bounded.payload["none"] is None


def test_excerpt_finds_keyword_late_in_the_payload() -> None:
    lines = [f"line {index}" for index in range(10_000)]
    lines[9_600] = "linux-xfs@vger.kernel.org"
    excerpt = excerpt_payload_text("\n".join(lines), keyword="xfs")
    assert excerpt.total_lines == 10_000
    assert excerpt.matched_lines == (9_601,)
    assert (9_601, "linux-xfs@vger.kernel.org") in excerpt.lines
    assert excerpt.next_start_line is None


def test_keyword_hit_arrives_with_the_lines_around_it() -> None:
    """A section header must be able to answer a question about the lines under it."""

    text = "\n".join([
        *(f"filler {index}" for index in range(100)),
        "XFS FILESYSTEM",
        "M:\tsomebody <somebody@example.org>",
        "L:\tlinux-xfs@vger.kernel.org",
        "S:\tSupported",
        *(f"tail {index}" for index in range(100)),
    ])
    excerpt = excerpt_payload_text(text, keyword="XFS FILESYSTEM")
    numbered = dict(excerpt.lines)
    assert excerpt.matched_lines == (101,)
    assert numbered[101] == "XFS FILESYSTEM"
    # the address three lines under the header is what the goal actually needed
    assert numbered[103] == "L:\tlinux-xfs@vger.kernel.org"
    assert min(numbered) == 99 and max(numbered) == 105


def test_excerpt_line_range_reports_next_start_line() -> None:
    text = "\n".join(f"line {index}" for index in range(1_000))
    excerpt = excerpt_payload_text(text, start_line=1, max_lines=200)
    assert len(excerpt.lines) == 200
    assert excerpt.lines[0] == (1, "line 0")
    assert excerpt.next_start_line == 201
    tail = excerpt_payload_text(text, start_line=801, max_lines=200)
    assert tail.next_start_line is None


def test_excerpt_keyword_paging_serves_whole_hit_windows_and_resumes_after_them() -> None:
    """A hit's context is served whole or deferred; half a window misleads."""

    text = "\n".join("hit" if index % 10 == 0 else "miss" for index in range(60))
    first = excerpt_payload_text(text, keyword="hit", max_lines=8)
    assert [number for number, _ in first.lines] == [1, 2, 3, 4, 5]
    assert first.next_start_line == 2  # resume after the last hit served, not its context
    following = excerpt_payload_text(text, keyword="hit", start_line=2, max_lines=8)
    assert 11 in [number for number, _ in following.lines]
    assert following.next_start_line == 12
    last = excerpt_payload_text(text, keyword="hit", start_line=51, max_lines=8)
    assert 51 in [number for number, _ in last.lines]
    assert last.next_start_line is None


def test_excerpt_keyword_absent_returns_no_lines() -> None:
    excerpt = excerpt_payload_text("alpha\nbeta", keyword="gamma")
    assert excerpt.lines == ()
    assert excerpt.matched_lines == ()
    assert excerpt.next_start_line is None


def _maintainers_shaped_body(fact_line: str, *, total_lines: int = 20_000) -> str:
    """~1MB body with one fact line placed at ~96%, like the E21 MAINTAINERS read."""

    fact_at = int(total_lines * 0.96)
    lines = [f"F:\tdrivers/sample/file_{index}.c" for index in range(total_lines)]
    lines[fact_at] = fact_line
    return "\n".join(lines)


def test_offloaded_text_of_a_dominant_string_keeps_its_own_line_numbers() -> None:
    body = _maintainers_shaped_body("L:\tlinux-xfs@vger.kernel.org")
    payload = _mcp_file_payload(body)
    assert serialized_length(payload) > MAX_OBSERVATION_PAYLOAD_CHARS
    text = select_offload_text(payload)
    # Not a JSON dump: escaping "\n" would collapse the body into one line and make
    # every line number meaningless.
    assert text == body
    assert len(text.splitlines()) == 20_000


def test_a_fact_at_96_percent_survives_the_round_trip_into_one_observation() -> None:
    fact = "L:\tlinux-xfs@vger.kernel.org"
    payload = _mcp_file_payload(_maintainers_shaped_body(fact))
    excerpt_only = bound_observation_payload(payload)
    assert excerpt_only.is_bounded
    assert "linux-xfs" not in json.dumps(excerpt_only.payload, ensure_ascii=False)

    window = excerpt_payload_text(select_offload_text(payload), keyword="linux-xfs")
    reread = bound_observation_payload({
        "ok": True,
        "lines": [{"line": number, "text": text} for number, text in window.lines],
        "total_lines": window.total_lines,
    })
    # The window must still be readable after it is bounded as an observation:
    # a line number the model cannot see is a fact it cannot report.
    assert serialized_length(reread.payload) <= MAX_OBSERVATION_PAYLOAD_CHARS
    assert {"line": 19_201, "text": fact} in reread.payload["lines"]
    assert reread.payload["total_lines"] == 20_000


def test_offloaded_text_falls_back_to_serialization_without_a_dominant_string() -> None:
    payload = {"ok": True, "items": [{"body": "y" * 5_000} for _ in range(400)]}
    assert serialized_length(payload) > MAX_OBSERVATION_PAYLOAD_CHARS
    text = select_offload_text(payload)
    # No source line numbering exists to preserve here, so the shape is what pages.
    assert text.startswith("{")
    assert json.loads(text) == payload
