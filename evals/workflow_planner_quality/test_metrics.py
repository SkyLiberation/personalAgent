from __future__ import annotations

from .metrics import (
    dependency_edge_f1,
    dependency_map_exact,
    dependency_node_accuracy,
)


def test_dependency_map_exact():
    assert dependency_map_exact({"b": ["a"]}, {"b": ["a"]}) == 1.0
    assert dependency_map_exact({"b": []}, {"b": ["a"]}) == 0.0


def test_dependency_node_accuracy():
    assert dependency_node_accuracy(
        {"a": [], "b": ["a"]},
        {"a": [], "b": ["a"]},
    ) == 1.0
    assert dependency_node_accuracy(
        {"a": [], "b": []},
        {"a": [], "b": ["a"]},
    ) == 0.5


def test_dependency_edge_f1():
    assert dependency_edge_f1({}, {}) == 1.0
    assert dependency_edge_f1({"b": ["a"]}, {"b": ["a"]}) == 1.0
    assert dependency_edge_f1({"b": ["a"], "c": ["a"]}, {"b": ["a"]}) == 0.6667
