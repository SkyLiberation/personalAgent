from personal_agent.core.llm_telemetry import collect_llm_usage, record_llm_usage


def test_collect_llm_usage_accumulates_calls_and_tokens():
    with collect_llm_usage() as totals:
        record_llm_usage(
            latency_ms=10,
            input_tokens=20,
            output_tokens=5,
            total_tokens=25,
        )
        record_llm_usage(latency_ms=7, input_tokens=3, output_tokens=2)

    assert totals.call_count == 2
    assert totals.latency_ms == 17
    assert totals.input_tokens == 23
    assert totals.output_tokens == 7
    assert totals.total_tokens == 30


def test_record_without_collector_is_noop():
    record_llm_usage(latency_ms=10, total_tokens=100)
