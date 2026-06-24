from __future__ import annotations

from personal_agent.application.document_partition import _coordinates


class TestCoordinatesExtraction:
    def test_extracts_bbox_from_element_metadata(self):
        element_meta = {
            "coordinates": {
                "points": [[0, 0], [0, 10], [20, 10], [20, 0]],
                "system": "PixelSpace",
                "layout_width": 600,
                "layout_height": 800,
            }
        }

        class _El:
            def __init__(self, meta):
                self.metadata = meta

            def to_dict(self):
                return self.metadata

        # element exposing metadata via .metadata.to_dict()
        class _Meta:
            def to_dict(self_inner):
                return element_meta

        el = _El(_Meta())
        coords = _coordinates({}, [el])
        assert coords is not None
        assert coords["system"] == "PixelSpace"
        assert coords["points"][2] == [20, 10]
        assert coords["layout_width"] == 600

    def test_prefers_chunk_level_coordinates(self):
        chunk_meta = {"coordinates": {"points": [[1, 1]], "system": "Rel"}}
        coords = _coordinates(chunk_meta, [])
        assert coords["system"] == "Rel"

    def test_none_when_absent(self):
        assert _coordinates({}, []) is None

    def test_ignores_coordinates_without_points(self):
        assert _coordinates({"coordinates": {"system": "PixelSpace"}}, []) is None
