from __future__ import annotations

import pytest

from evals.e2e_quality.conftest import (  # noqa: F401
    clean_e2e_database,
    server_temp_dir,
)
from evals.product_baselines.evidence import (
    ProductEvidenceRecorder,
    product_evidence_output_root,
)
from evals.product_baselines.promotion_plugin import (  # noqa: F401
    pytest_addoption,
    pytest_collection_modifyitems,
    pytest_configure,
    pytest_runtest_makereport,
    pytest_sessionfinish,
    pytest_unconfigure,
)
from evals.e2e_quality.test_release_user_outcomes import live_web_process  # noqa: F401
from tests.conftest import (  # noqa: F401
    clean_postgres_business_tables,
    postgres_url,
    temp_dir,
)


@pytest.fixture
def product_evidence_recorder() -> ProductEvidenceRecorder:
    return ProductEvidenceRecorder(product_evidence_output_root())
