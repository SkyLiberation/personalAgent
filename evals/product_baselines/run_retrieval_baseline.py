"""Run one predeclared formal baseline with safe existing-database binding."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import sys
from urllib.parse import urlsplit, urlunsplit

from personal_agent.kernel.config import Settings


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", required=True, choices=("e1", "p1"))
    parser.add_argument("--output-root", required=True, type=Path)
    args = parser.parse_args()
    root = args.output_root.resolve()
    root.mkdir(parents=True, exist_ok=False)
    settings = Settings.from_env()
    parsed = urlsplit(settings.postgres_url or "")
    if not parsed.username or not parsed.password:
        raise ValueError("需要既有本机评测数据库凭据")
    # Keep the exact encoded credentials; never print this URL.
    auth = parsed.netloc.rsplit("@", 1)[0]
    database = urlunsplit((parsed.scheme, auth + "@127.0.0.1:16432", "/personal_agent_test", parsed.query, ""))
    os.environ.update({
        "PERSONAL_AGENT_E2E_POSTGRES_URL": database,
        "PERSONAL_AGENT_REQUIRE_LIVE_E2E": "true",
        "PERSONAL_AGENT_E2E_MODEL_PROFILE": "configured",
        "PERSONAL_AGENT_E2E_MODEL_TIMEOUT_SECONDS": "120",
        "PERSONAL_AGENT_E2E_TRACE_DIR": str(root / "e2e"),
        "PERSONAL_AGENT_PRODUCT_EVIDENCE_DIR": str(root / "product"),
    })
    node = f"evals/product_baselines/test_retrieval_experiment_001.py::test_retrieval_experiment_formal_baseline[{args.case}]"
    files = [Path(__file__), Path(__file__).with_name("retrieval_baseline.py"),
             Path(__file__).with_name("retrieval_http_server.py"), Path(__file__).with_name("test_retrieval_experiment_001.py")]
    invocation = {"started_at": datetime.now(timezone.utc).isoformat(), "argv": sys.argv,
                  "node": node, "case": args.case, "samples": 1, "deadline_seconds": 900,
                  "budget": settings.interaction_loop.model_dump(),
                  "source_sha256": {str(path): sha256(path.read_bytes()).hexdigest() for path in files}}
    (root / "invocation.json").write_text(json.dumps(invocation, ensure_ascii=False, indent=2), encoding="utf-8")
    import pytest

    raise SystemExit(pytest.main([node, "-q", "-s"]))


if __name__ == "__main__":
    main()
