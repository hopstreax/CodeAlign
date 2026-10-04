"""Graphify output loader and validator."""

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class GraphValidationResult:
    """Outcome of validating a Graphify graph.json artifact."""

    graph_path: Path
    node_count: int
    edge_count: int
    is_valid: bool
    error_message: str | None = None


def load_and_validate_graph(graph_path: Path) -> GraphValidationResult:
    """Validate that graph.json exists, is valid JSON, and has nodes and edges arrays.

    Does not construct heavy in-memory models; verifies schema integrity and counts.
    """
    if not graph_path.is_file():
        return GraphValidationResult(
            graph_path=graph_path,
            node_count=0,
            edge_count=0,
            is_valid=False,
            error_message=f"Graph artifact does not exist: {graph_path}",
        )

    try:
        with open(graph_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as exc:
        return GraphValidationResult(
            graph_path=graph_path,
            node_count=0,
            edge_count=0,
            is_valid=False,
            error_message=f"Failed to parse graph JSON: {exc}",
        )

    if not isinstance(data, dict):
        return GraphValidationResult(
            graph_path=graph_path,
            node_count=0,
            edge_count=0,
            is_valid=False,
            error_message="Graph JSON root must be an object",
        )

    nodes = data.get("nodes")
    # NetworkX serializes edges as either "links" or "edges" depending on version
    edges = data.get("links") if "links" in data else data.get("edges")

    if not isinstance(nodes, list):
        return GraphValidationResult(
            graph_path=graph_path,
            node_count=0,
            edge_count=0,
            is_valid=False,
            error_message="Graph JSON missing valid 'nodes' array",
        )

    if not isinstance(edges, list):
        return GraphValidationResult(
            graph_path=graph_path,
            node_count=len(nodes),
            edge_count=0,
            is_valid=False,
            error_message="Graph JSON missing valid 'links' or 'edges' array",
        )

    return GraphValidationResult(
        graph_path=graph_path,
        node_count=len(nodes),
        edge_count=len(edges),
        is_valid=True,
    )
