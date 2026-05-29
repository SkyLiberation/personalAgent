"""LangExtract-backed lightweight pre-extraction layer.

This package implements the *first layer* of the two-tier ingestion design:
extract section topic / core entities / graph_worthy routing signal from raw
documents. The heavy entity-relation-fact extraction stays on graphiti.

PR1 scope: schema + client + service. Not yet wired into the capture graph.
"""

from .schemas import SectionMap, SectionRecord
from .service import PreExtractService

__all__ = ["SectionMap", "SectionRecord", "PreExtractService"]
