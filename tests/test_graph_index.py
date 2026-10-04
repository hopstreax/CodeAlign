"""Unit tests for GraphIndex query capabilities using small fixtures."""

import pytest

from codealign.analysis.graph_index import GraphIndex


@pytest.fixture
def sample_graph_data() -> dict:
    """Fixture with a realistic small Graphify extraction."""
    return {
        "directed": False,
        "nodes": [
            {
                "id": "file_user_service",
                "label": "UserService.ts",
                "source_file": "src/services/UserService.ts",
                "source_location": "L1",
                "file_type": "code",
            },
            {
                "id": "cls_user_service",
                "label": "UserService",
                "source_file": "src/services/UserService.ts",
                "source_location": "L10",
                "file_type": "code",
                "_callable": True,
                "_callable_class": True,
            },
            {
                "id": "method_get_profile",
                "label": ".getProfile()",
                "source_file": "src/services/UserService.ts",
                "source_location": "L42",
                "file_type": "code",
                "_callable": True,
            },
            {
                "id": "fn_show_user",
                "label": "showUser()",
                "source_file": "src/controllers/UserController.ts",
                "source_location": "L18",
                "file_type": "code",
                "_callable": True,
            },
            {
                "id": "fn_redis_get",
                "label": "redisGet()",
                "source_file": "src/lib/redis.ts",
                "source_location": "L105",
                "file_type": "code",
                "_callable": True,
            },
        ],
        "links": [
            {
                "source": "cls_user_service",
                "target": "method_get_profile",
                "relation": "method",
                "source_file": "src/services/UserService.ts",
                "source_location": "L42",
            },
            {
                "source": "fn_show_user",
                "target": "method_get_profile",
                "relation": "calls",
                "source_file": "src/controllers/UserController.ts",
                "source_location": "L25",
            },
            {
                "source": "method_get_profile",
                "target": "fn_redis_get",
                "relation": "calls",
                "source_file": "src/services/UserService.ts",
                "source_location": "L50",
            },
        ],
    }


def test_get_symbols_in_file(sample_graph_data: dict) -> None:
    """Verify listing all symbols in a given file."""
    index = GraphIndex.from_dict(sample_graph_data)
    symbols = index.get_symbols_in_file("src/services/UserService.ts")

    assert len(symbols) == 2
    names = [s.name for s in symbols]
    assert "UserService" in names
    assert ".getProfile" in names or "getProfile" in names[1]

    # Verify line numbers
    lines = {s.name: s.line for s in symbols}
    assert lines["UserService"] == 10


def test_find_symbol_class_and_function(sample_graph_data: dict) -> None:
    """Verify symbol lookup for classes and functions."""
    index = GraphIndex.from_dict(sample_graph_data)

    cls_matches = index.find_symbol("UserService")
    assert len(cls_matches) == 1
    assert cls_matches[0].name == "UserService"
    assert cls_matches[0].file_path == "src/services/UserService.ts"
    assert cls_matches[0].line == 10
    assert cls_matches[0].kind == "class"

    fn_matches = index.find_symbol("showUser()")
    assert len(fn_matches) == 1
    assert fn_matches[0].file_path == "src/controllers/UserController.ts"
    assert fn_matches[0].line == 18


def test_find_method(sample_graph_data: dict) -> None:
    """Verify resolving Class.method dotted expressions."""
    index = GraphIndex.from_dict(sample_graph_data)

    method_matches = index.find_method("UserService", "getProfile()")
    assert len(method_matches) == 1
    assert method_matches[0].name == "UserService.getProfile"
    assert method_matches[0].file_path == "src/services/UserService.ts"
    assert method_matches[0].line == 42
    assert method_matches[0].kind == "method"


def test_get_callers_and_callees(sample_graph_data: dict) -> None:
    """Verify incoming and outgoing call graph queries."""
    index = GraphIndex.from_dict(sample_graph_data)

    # getProfile has caller showUser and callee redisGet
    callers = index.get_callers("method_get_profile")
    assert len(callers) == 1
    assert callers[0].symbol == "showUser"
    assert callers[0].file_path == "src/controllers/UserController.ts"
    assert callers[0].line == 25

    callees = index.get_callees("method_get_profile")
    assert len(callees) == 1
    assert callees[0].symbol == "redisGet"
    assert callees[0].file_path == "src/services/UserService.ts"
    assert callees[0].line == 50


def test_get_relationships(sample_graph_data: dict) -> None:
    """Verify incoming and outgoing relationships query."""
    index = GraphIndex.from_dict(sample_graph_data)
    rels = index.get_relationships("method_get_profile")
    assert len(rels) >= 2
    directions = {r.direction for r in rels}
    assert "incoming" in directions
    assert "outgoing" in directions
