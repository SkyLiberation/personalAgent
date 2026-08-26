from evals.e2e_quality.container_resources import (
    docker_size_bytes,
    docker_stats_payload,
    normalize_docker_stats,
    summarize_docker_stats,
)


def test_docker_size_bytes_preserves_binary_and_decimal_units() -> None:
    assert docker_size_bytes("3.5GiB") == round(3.5 * 1024**3)
    assert docker_size_bytes("250MB") == 250_000_000


def test_docker_stats_payload_removes_windows_terminal_refresh_sequences() -> None:
    assert docker_stats_payload(
        '\x1b[H{"CPUPerc":"2.5%","PIDs":"10"}\x1b[K\n'
    ) == {"CPUPerc": "2.5%", "PIDs": "10"}
    assert docker_stats_payload("\x1b[K\n") is None


def test_docker_resource_summary_preserves_samples_and_peak_values() -> None:
    first = normalize_docker_stats(
        {
            "Name": "researcher",
            "CPUPerc": "25.5%",
            "MemPerc": "50.0%",
            "MemUsage": "3GiB / 8GiB",
            "PIDs": "90",
        },
        elapsed_seconds=1.2345,
    )
    second = normalize_docker_stats(
        {
            "Name": "researcher",
            "CPUPerc": "75.5%",
            "MemPerc": "62.5%",
            "MemUsage": "5GiB / 8GiB",
            "PIDs": "120",
        },
        elapsed_seconds=2.3456,
    )

    summary = summarize_docker_stats(
        (first, second),
        container="researcher",
    )

    assert summary["captured"] is True
    assert summary["sample_count"] == 2
    assert summary["max_cpu_percent"] == 75.5
    assert summary["max_memory_bytes"] == 5 * 1024**3
    assert summary["memory_limit_bytes"] == 8 * 1024**3
    assert summary["max_memory_percent"] == 62.5
    assert summary["max_pids"] == 120
    assert summary["samples"] == [first, second]
