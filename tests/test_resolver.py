"""Unit tests for resolving plan references and formatting evidence."""

from codealign.analysis.graph_index import GraphIndex
from codealign.analysis.plan_parser import parse_plan_text
from codealign.analysis.resolver import resolve_plan


def test_resolve_plan_success() -> None:
    """Verify successful grounding of files, classes, methods, and functions."""
    graph_data = {
        "nodes": [
            {
                "id": "f_user",
                "label": "UserService.ts",
                "source_file": "src/services/UserService.ts",
                "source_location": "L1",
                "file_type": "code",
            },
            {
                "id": "cls_user",
                "label": "UserService",
                "source_file": "src/services/UserService.ts",
                "source_location": "L10",
                "file_type": "code",
                "_callable": True,
                "_callable_class": True,
            },
            {
                "id": "m_get_profile",
                "label": ".getProfile()",
                "source_file": "src/services/UserService.ts",
                "source_location": "L42",
                "file_type": "code",
                "_callable": True,
            },
            {
                "id": "fn_controller",
                "label": "showUser()",
                "source_file": "src/controllers/UserController.ts",
                "source_location": "L18",
                "file_type": "code",
                "_callable": True,
            },
        ],
        "links": [
            {
                "source": "cls_user",
                "target": "m_get_profile",
                "relation": "method",
                "source_file": "src/services/UserService.ts",
                "source_location": "L42",
            },
            {
                "source": "fn_controller",
                "target": "m_get_profile",
                "relation": "calls",
                "source_file": "src/controllers/UserController.ts",
                "source_location": "L25",
            },
        ],
    }

    index = GraphIndex.from_dict(graph_data)
    plan_text = """# Add Redis Caching
1. Touch `src/services/UserService.ts`.
2. Update `UserService.getProfile()`.
3. Check `UserService` class.
"""
    plan = parse_plan_text(plan_text)
    result = resolve_plan(plan, index)

    assert len(result.resolved) == 3
    assert len(result.unresolved) == 0

    # 1. File reference
    f_res = next(r for r in result.resolved if r.kind == "file")
    assert f_res.file_path == "src/services/UserService.ts"
    assert len(f_res.symbols_in_file) == 2

    # 2. Method reference
    m_res = next(r for r in result.resolved if r.kind == "method")
    assert m_res.symbol == "UserService.getProfile"
    assert m_res.file_path == "src/services/UserService.ts"
    assert m_res.line == 42
    assert len(m_res.callers) == 1
    assert m_res.callers[0].symbol == "showUser"
    assert m_res.callers[0].file_path == "src/controllers/UserController.ts"

    # Terminal output check
    term = result.format_terminal()
    assert "RESOLVED REFERENCES" in term
    assert "UserService.getProfile()" in term
    assert "src/services/UserService.ts:42" in term
    assert "showUser" in term

    # JSON output check
    d = result.to_dict()
    assert d["summary"]["resolved_count"] == 3
    assert d["summary"]["unresolved_count"] == 0
    assert len(d["resolved"]) == 3


def test_resolve_plan_unresolved_references() -> None:
    """Verify clear error explanations for unknown files, symbols, and missing methods."""
    graph_data = {
        "nodes": [
            {
                "id": "cls_existing",
                "label": "ExistingClass",
                "source_file": "src/existing.py",
                "source_location": "L5",
                "file_type": "code",
                "_callable": True,
                "_callable_class": True,
            }
        ],
        "links": [],
    }

    index = GraphIndex.from_dict(graph_data)
    plan_text = """# Unresolved Plan
1. Touch `src/missing_file.py`.
2. Update `UnknownClass.missingMethod()`.
3. Update `ExistingClass.absentMethod()`.
4. Call `unknownFunction()`.
"""
    plan = parse_plan_text(plan_text)
    result = resolve_plan(plan, index)

    assert len(result.resolved) == 0
    assert len(result.unresolved) == 4

    unresolved_reasons = {u.reference: u.reason for u in result.unresolved}
    assert "not found in codebase graph" in unresolved_reasons["src/missing_file.py"]
    assert "Class 'UnknownClass' not found" in unresolved_reasons["UnknownClass.missingMethod()"]
    assert (
        "method 'absentMethod()' does not exist"
        in unresolved_reasons["ExistingClass.absentMethod()"]
    )
    assert "not found in codebase graph" in unresolved_reasons["unknownFunction()"]

    term = result.format_terminal()
    assert "UNRESOLVED REFERENCES" in term
    assert "ExistingClass.absentMethod()" in term
