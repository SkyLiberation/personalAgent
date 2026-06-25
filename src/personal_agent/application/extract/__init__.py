"""LangExtract-backed lightweight pre-extraction layer.

This package implements an optional section-level extraction (section topic /
core entities / graph_worthy routing signal) from raw documents.

NOTE: It is no longer wired into the capture pipeline. Capture-time structure
and chunking are owned by Unstructured (partition + chunk_by_title), and the
heavy entity-relation-fact extraction stays on graphiti. LangExtract's active
role in the live system is query understanding (see ``agent/query_planner.py``),
not Graphiti pre-extraction. This package is retained for tests/experiments.
"""

from personal_agent.application.extract.schemas import SectionMap, SectionRecord
from personal_agent.application.extract.service import PreExtractService

__all__ = ["SectionMap", "SectionRecord", "PreExtractService"]
