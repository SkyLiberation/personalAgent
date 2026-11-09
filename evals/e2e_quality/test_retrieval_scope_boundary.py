"""F1 正式 HTTP 授权反事实；独立显式准备，不进入产品完成分子。"""
import os
from pathlib import Path

import pytest

from evals.product_baselines.retrieval_scope_counterfact import run

pytestmark = pytest.mark.integration


def test_retrieval_scope_boundary():
    preparation = os.getenv("PERSONAL_AGENT_RETRIEVAL_SCOPE_PREPARATION")
    output = os.getenv("PERSONAL_AGENT_RETRIEVAL_SCOPE_OUTPUT")
    if not preparation or not output:
        pytest.skip("F1 须显式提供独立准备和未使用的输出目录")
    assert run(Path(preparation).resolve(), Path(output).resolve()).passed
