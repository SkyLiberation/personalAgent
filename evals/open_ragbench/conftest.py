"""Pytest configuration for Open RAG Benchmark evaluations."""
from __future__ import annotations

import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--num-queries",
        type=int,
        default=None,
        help="Number of queries to evaluate (default: all text-source queries)",
    )
    parser.addoption(
        "--ragbench-seed",
        type=int,
        default=42,
        help="Random seed for query subsampling (default: 42)",
    )
    parser.addoption(
        "--corpus-mode",
        choices=("relevant", "full"),
        default="relevant",
        help=(
            "Corpus candidate pool: 'relevant' loads only docs for sampled queries; "
            "'full' loads the full arxiv split (default: relevant)"
        ),
    )


@pytest.fixture(scope="session")
def ragbench_config(request: pytest.FixtureRequest) -> dict:
    return {
        "num_queries": request.config.getoption("--num-queries"),
        "seed": request.config.getoption("--ragbench-seed"),
        "corpus_mode": request.config.getoption("--corpus-mode"),
    }


@pytest.fixture(scope="session")
def benchmark_data(ragbench_config: dict):
    """Download and parse the dataset once per test session."""
    from .loader import load_benchmark

    return load_benchmark(
        num_queries=ragbench_config["num_queries"],
        seed=ragbench_config["seed"],
        corpus_mode=ragbench_config["corpus_mode"],
    )
