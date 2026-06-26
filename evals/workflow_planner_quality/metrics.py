"""WorkflowPlanner-specific metric primitives."""

from __future__ import annotations


def dependency_map_exact(
    predicted: dict[str, list[str]],
    expected: dict[str, list[str]],
) -> float:
    return 1.0 if _normalize(predicted) == _normalize(expected) else 0.0


def dependency_node_accuracy(
    predicted: dict[str, list[str]],
    expected: dict[str, list[str]],
) -> float:
    """Fraction of expected nodes whose dependency list matches exactly."""
    if not expected:
        return 1.0
    normalized_predicted = _normalize(predicted)
    normalized_expected = _normalize(expected)
    hits = sum(
        normalized_predicted.get(node, []) == dependencies
        for node, dependencies in normalized_expected.items()
    )
    return round(hits / len(normalized_expected), 4)


def dependency_edge_f1(
    predicted: dict[str, list[str]],
    expected: dict[str, list[str]],
) -> float:
    predicted_edges = _edges(predicted)
    expected_edges = _edges(expected)
    if not predicted_edges and not expected_edges:
        return 1.0
    if not predicted_edges or not expected_edges:
        return 0.0
    true_positive = len(predicted_edges & expected_edges)
    if true_positive == 0:
        return 0.0
    precision = true_positive / len(predicted_edges)
    recall = true_positive / len(expected_edges)
    return round(2 * precision * recall / (precision + recall), 4)


def _normalize(mapping: dict[str, list[str]]) -> dict[str, list[str]]:
    return {
        str(key): [str(value) for value in values]
        for key, values in sorted(mapping.items())
    }


def _edges(mapping: dict[str, list[str]]) -> set[tuple[str, str]]:
    return {
        (str(node), str(dependency))
        for node, dependencies in mapping.items()
        for dependency in dependencies
    }
