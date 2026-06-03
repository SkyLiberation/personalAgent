"""LangExtract-backed lightweight pre-extraction layer.

This package implements the *first layer* of the two-tier ingestion design:
extract section topic / core entities / graph_worthy routing signal from raw
documents. The heavy entity-relation-fact extraction stays on graphiti.

Wired into capture through ``run_capture_flow()`` and ``preextract_node``.
"""

from .schemas import SectionMap, SectionRecord
from .service import PreExtractService

__all__ = ["SectionMap", "SectionRecord", "PreExtractService"]
