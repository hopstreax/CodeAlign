"""Unit tests for Graphify graph.json validation and loading."""

import json
from pathlib import Path

from codealign.graphify.loader import load_and_validate_graph


def test_load_valid_graph_with_links(tmp_path: Path) -> None:
    """Verify successful validation when graph uses 'links' edge key."""
    graph_path = tmp_path / "graph.json"
    content = {
        "directed": False,
        "nodes": [{"id": "n1", "label": "foo"}, {"id": "n2", "label": "bar"}],
        "links": [{"source": "n1", "target": "n2", "relation": "calls"}],
    }
    graph_path.write_text(json.dumps(content), encoding="utf-8")

    result = load_and_validate_graph(graph_path)
    assert result.is_valid is True
    assert result.node_count == 2
    assert result.edge_count == 1
    assert result.error_message is None


def test_load_valid_graph_with_edges(tmp_path: Path) -> None:
    """Verify successful validation when graph uses 'edges' edge key."""
    graph_path = tmp_path / "graph.json"
    content = {
        "nodes": [{"id": "n1"}],
        "edges": [{"source": "n1", "target": "n1", "relation": "self"}],
    }
    graph_path.write_text(json.dumps(content), encoding="utf-8")

    result = load_and_validate_graph(graph_path)
    assert result.is_valid is True
    assert result.node_count == 1
    assert result.edge_count == 1


def test_load_missing_graph_file(tmp_path: Path) -> None:
    """Verify handling of missing graph file."""
    graph_path = tmp_path / "nonexistent.json"
    result = load_and_validate_graph(graph_path)
    assert result.is_valid is False
    assert result.node_count == 0
    assert "does not exist" in (result.error_message or "")


def test_load_malformed_json(tmp_path: Path) -> None:
    """Verify handling of corrupt JSON syntax."""
    graph_path = tmp_path / "corrupt.json"
    graph_path.write_text("{not valid json", encoding="utf-8")

    result = load_and_validate_graph(graph_path)
    assert result.is_valid is False
    assert "Failed to parse graph JSON" in (result.error_message or "")


def test_load_invalid_root_type(tmp_path: Path) -> None:
    """Verify error when JSON root is not an object."""
    graph_path = tmp_path / "list_root.json"
    graph_path.write_text(json.dumps(["not", "an", "object"]), encoding="utf-8")

    result = load_and_validate_graph(graph_path)
    assert result.is_valid is False
    assert "root must be an object" in (result.error_message or "")


def test_load_missing_nodes_or_edges(tmp_path: Path) -> None:
    """Verify error when nodes or edges are absent or not lists."""
    graph_path = tmp_path / "missing_nodes.json"
    graph_path.write_text(json.dumps({"edges": []}), encoding="utf-8")

    result = load_and_validate_graph(graph_path)
    assert result.is_valid is False
    assert "missing valid 'nodes' array" in (result.error_message or "")
