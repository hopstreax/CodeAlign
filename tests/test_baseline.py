"""Unit and functional tests for Implementation Baseline generation and CLI command."""

import json
from pathlib import Path

from typer.testing import CliRunner

from codealign.analysis.graph_index import GraphIndex
from codealign.analysis.plan_parser import parse_plan_text
from codealign.analysis.resolver import resolve_plan
from codealign.baseline.generator import generate_baseline
from codealign.cli import app
from codealign.git.repository import GitRepoInfo

runner = CliRunner()

FIXTURE_GRAPH_DATA = {
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
            "id": "file_redis_config",
            "label": "redis.ts",
            "source_file": "src/config/redis.ts",
            "source_location": "L1",
            "file_type": "code",
        },
        {
            "id": "cls_user_repo",
            "label": "UserRepository",
            "source_file": "src/repositories/UserRepository.ts",
            "source_location": "L5",
            "file_type": "code",
            "_callable": True,
            "_callable_class": True,
        },
        {
            "id": "method_find_by_id",
            "label": ".findById()",
            "source_file": "src/repositories/UserRepository.ts",
            "source_location": "L25",
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
    ],
    "links": [
        {"source": "cls_user_service", "target": "method_get_profile", "relation": "method"},
        {"source": "fn_show_user", "target": "method_get_profile", "relation": "calls"},
        {"source": "method_get_profile", "target": "method_find_by_id", "relation": "calls"},
    ],
}


def test_baseline_generation_valid_plan(tmp_path: Path) -> None:
    """Verify baseline generation from a structured implementation plan."""
    plan_text = """# Add Redis caching to user profiles

## Goal

Add Redis caching for user profile lookups.

## Implementation

1. Update `UserService.getProfile()`.
2. Add Redis configuration in `src/config/redis.ts`.
3. Invalidate cache when profiles change.
4. Add tests for cache hits and invalidation in `tests/test_cache.py`.
"""
    parsed_plan = parse_plan_text(plan_text, path=tmp_path / "plan.md")
    index = GraphIndex.from_dict(FIXTURE_GRAPH_DATA)
    analysis = resolve_plan(parsed_plan, index)

    repo_info = GitRepoInfo(
        root=tmp_path,
        branch="feature/redis",
        head_sha="abcdef1234567890",
        is_dirty=False,
    )

    baseline = generate_baseline(parsed_plan, analysis, repo_info=repo_info)

    assert baseline.schema_version == "0.1.0"
    assert baseline.repository.name == tmp_path.name
    assert baseline.repository.branch == "feature/redis"
    assert baseline.repository.commit == "abcdef1234567890"

    # Intent assertions
    assert baseline.intent.title == "Add Redis caching to user profiles"
    assert baseline.intent.goal == "Add Redis caching for user profile lookups."
    assert len(baseline.intent.steps) == 4
    assert "Update `UserService.getProfile()`." in baseline.intent.steps

    # Evidence assertions
    assert len(baseline.evidence.resolved) == 2  # UserService.getProfile() and src/config/redis.ts
    assert len(baseline.evidence.unresolved) == 1  # tests/test_cache.py not in graph

    # Expectations assertions
    expected_paths = {f.path for f in baseline.expectations.expected_files}
    assert "src/services/UserService.ts" in expected_paths
    assert "src/config/redis.ts" in expected_paths
    assert "tests/test_cache.py" in expected_paths

    # Expected tests
    test_paths = {t.path for t in baseline.expectations.expected_tests}
    assert "tests/test_cache.py" in test_paths


def test_evidence_vs_expectation_separation(tmp_path: Path) -> None:
    """CRITICAL: Verify Graphify callers/callees are kept in evidence and NOT in expectations."""
    plan_text = """# Cache Optimization
1. Modify `UserService.getProfile()`.
"""
    parsed_plan = parse_plan_text(plan_text, path=tmp_path / "plan.md")
    index = GraphIndex.from_dict(FIXTURE_GRAPH_DATA)
    analysis = resolve_plan(parsed_plan, index)

    baseline = generate_baseline(parsed_plan, analysis, repo_root=tmp_path)

    # In evidence:
    method_evidence = next(
        r for r in baseline.evidence.resolved if r.symbol == "UserService.getProfile"
    )
    # Caller: showUser() in UserController.ts
    assert any(c["symbol"] == "showUser" for c in method_evidence.callers)
    # Callee: .findById() in UserRepository.ts
    assert any(c["symbol"] == ".findById" for c in method_evidence.callees)

    # In expectations:
    expected_paths = {f.path for f in baseline.expectations.expected_files}
    # Target file must be expected:
    assert "src/services/UserService.ts" in expected_paths
    # Callers and callees MUST NOT be in expectations:
    assert "src/controllers/UserController.ts" not in expected_paths
    assert "src/repositories/UserRepository.ts" not in expected_paths

    expected_symbol_names = {s.name for s in baseline.expectations.expected_symbols}
    assert "UserService.getProfile" in expected_symbol_names
    assert "showUser" not in expected_symbol_names
    assert ".findById" not in expected_symbol_names
    assert "UserRepository.findById" not in expected_symbol_names


def test_unresolved_references_preserved(tmp_path: Path) -> None:
    """Verify unresolved references remain explicitly unresolved and don't assume create."""
    plan_text = """# Experimental Plan
1. Update `MissingClass.missingMethod()`.
2. Touch `src/new_module.py`.
"""
    parsed_plan = parse_plan_text(plan_text, path=tmp_path / "plan.md")
    index = GraphIndex.from_dict(FIXTURE_GRAPH_DATA)
    analysis = resolve_plan(parsed_plan, index)

    baseline = generate_baseline(parsed_plan, analysis, repo_root=tmp_path)

    assert len(baseline.evidence.unresolved) == 2
    unresolved_map = {u.reference: u for u in baseline.evidence.unresolved}

    assert "MissingClass.missingMethod()" in unresolved_map
    assert "not found" in unresolved_map["MissingClass.missingMethod()"].reason

    # Missing file without explicit create intent must NOT become action="create"
    expected_file_map = {f.path: f for f in baseline.expectations.expected_files}
    assert "src/new_module.py" in expected_file_map
    assert expected_file_map["src/new_module.py"].status == "unresolved"
    assert expected_file_map["src/new_module.py"].action == "unresolved"


def test_existing_explicit_file_expectation(tmp_path: Path) -> None:
    """Verify existing explicitly referenced file produces modify action and resolved status."""
    plan_text = "# Update Config\n1. Modify `src/config/redis.ts`.\n"
    parsed_plan = parse_plan_text(plan_text, path=tmp_path / "plan.md")
    index = GraphIndex.from_dict(FIXTURE_GRAPH_DATA)
    analysis = resolve_plan(parsed_plan, index)

    baseline = generate_baseline(parsed_plan, analysis, repo_root=tmp_path)

    expected_files = {f.path: f for f in baseline.expectations.expected_files}
    assert "src/config/redis.ts" in expected_files
    assert expected_files["src/config/redis.ts"].action == "modify"
    assert expected_files["src/config/redis.ts"].status == "resolved"


def test_missing_file_with_explicit_create_intent(tmp_path: Path) -> None:
    """Verify missing file with explicit create intent produces action='create'."""
    plan_text = "# New Tests\n1. Create `tests/test_new_feature.py`.\n"
    parsed_plan = parse_plan_text(plan_text, path=tmp_path / "plan.md")
    index = GraphIndex.from_dict(FIXTURE_GRAPH_DATA)
    analysis = resolve_plan(parsed_plan, index)

    baseline = generate_baseline(parsed_plan, analysis, repo_root=tmp_path)

    expected_files = {f.path: f for f in baseline.expectations.expected_files}
    assert "tests/test_new_feature.py" in expected_files
    assert expected_files["tests/test_new_feature.py"].action == "create"
    assert expected_files["tests/test_new_feature.py"].status == "expected"

    # Should also appear in expected_tests because it is a test file to create
    test_paths = {t.path for t in baseline.expectations.expected_tests}
    assert "tests/test_new_feature.py" in test_paths


def test_missing_file_without_explicit_create_intent(tmp_path: Path) -> None:
    """Verify missing file without explicit create intent remains unresolved, not create."""
    plan_text = "# Update Missing File\n1. Update `tests/test_nonexistent.py`.\n"
    parsed_plan = parse_plan_text(plan_text, path=tmp_path / "plan.md")
    index = GraphIndex.from_dict(FIXTURE_GRAPH_DATA)
    analysis = resolve_plan(parsed_plan, index)

    baseline = generate_baseline(parsed_plan, analysis, repo_root=tmp_path)

    expected_files = {f.path: f for f in baseline.expectations.expected_files}
    assert "tests/test_nonexistent.py" in expected_files
    # Must NOT be action="create"
    assert expected_files["tests/test_nonexistent.py"].action != "create"
    assert expected_files["tests/test_nonexistent.py"].status == "unresolved"

    # Must NOT appear in expected_tests because existence/creation is unresolved
    test_paths = {t.path for t in baseline.expectations.expected_tests}
    assert "tests/test_nonexistent.py" not in test_paths

    # Must appear in evidence.unresolved
    unresolved_refs = {u.reference for u in baseline.evidence.unresolved}
    assert "tests/test_nonexistent.py" in unresolved_refs


def test_repository_portability_no_absolute_root(tmp_path: Path) -> None:
    """Verify baseline.json contains no machine-specific local filesystem root path."""
    plan_text = "# Plan\n1. Modify `src/config/redis.ts`.\n"
    parsed_plan = parse_plan_text(plan_text, path=tmp_path / "plan.md")
    index = GraphIndex.from_dict(FIXTURE_GRAPH_DATA)
    analysis = resolve_plan(parsed_plan, index)

    repo_info = GitRepoInfo(
        root=tmp_path,
        branch="main",
        head_sha="deadbeef12345678",
        is_dirty=False,
    )
    baseline = generate_baseline(parsed_plan, analysis, repo_info=repo_info)

    data = baseline.to_dict()
    assert "root" not in data["repository"]
    assert data["repository"]["name"] == tmp_path.name
    assert data["repository"]["branch"] == "main"
    assert data["repository"]["commit"] == "deadbeef12345678"

    json_str = baseline.to_json()
    assert str(tmp_path) not in json_str


def test_baseline_json_serialization(tmp_path: Path) -> None:
    """Verify baseline JSON round-trip and terminal formatting."""
    plan_text = "# Simple Plan\n1. Modify `src/config/redis.ts`.\n"
    parsed_plan = parse_plan_text(plan_text, path=tmp_path / "plan.md")
    index = GraphIndex.from_dict(FIXTURE_GRAPH_DATA)
    analysis = resolve_plan(parsed_plan, index)

    baseline = generate_baseline(parsed_plan, analysis, repo_root=tmp_path)

    json_str = baseline.to_json()
    data = json.loads(json_str)

    assert data["schema_version"] == "0.1.0"
    assert "intent" in data
    assert "evidence" in data
    assert "expectations" in data

    # Test file writing
    out_file = tmp_path / "baseline.json"
    baseline.write_to_file(out_file)
    assert out_file.is_file()

    # Terminal report
    term = baseline.format_terminal(".codealign/baseline.json")
    assert "BASELINE GENERATED" in term
    assert "Simple Plan" in term
    assert ".codealign/baseline.json" in term


def test_deterministic_output(tmp_path: Path) -> None:
    """Verify baseline generation produces identical output for identical inputs."""
    plan_text = "# Deterministic Plan\n1. Update `UserService.getProfile()`.\n"
    parsed_plan = parse_plan_text(plan_text, path=tmp_path / "plan.md")
    index = GraphIndex.from_dict(FIXTURE_GRAPH_DATA)
    analysis = resolve_plan(parsed_plan, index)

    b1 = generate_baseline(parsed_plan, analysis, repo_root=tmp_path)
    b2 = generate_baseline(parsed_plan, analysis, repo_root=tmp_path)

    d1 = b1.to_dict()
    d2 = b2.to_dict()

    # Exclude generated_at timestamp for strict determinism check
    d1.pop("generated_at")
    d2.pop("generated_at")

    assert d1 == d2


def test_baseline_command_terminal_and_json(tmp_path: Path, monkeypatch) -> None:
    """Verify codealign baseline CLI command in terminal and JSON modes."""
    # Setup simulated git repo with .codealign and graph.json
    codealign_dir = tmp_path / ".codealign"
    codealign_dir.mkdir(parents=True)
    graph_path = codealign_dir / "graph.json"
    graph_path.write_text(json.dumps(FIXTURE_GRAPH_DATA), encoding="utf-8")

    plan_file = tmp_path / "plan.md"
    plan_file.write_text(
        "# Redis Plan\n1. Modify `src/config/redis.ts`.\n",
        encoding="utf-8",
    )

    repo_info = GitRepoInfo(
        root=tmp_path,
        branch="main",
        head_sha="1111222233334444",
        is_dirty=False,
    )
    monkeypatch.setattr("codealign.commands.baseline.get_git_repo_info", lambda: repo_info)

    # 1. Test terminal summary
    res_term = runner.invoke(app, ["baseline", str(plan_file)])
    assert res_term.exit_code == 0
    assert "BASELINE GENERATED" in res_term.stdout
    assert "Redis Plan" in res_term.stdout
    assert "src/config/redis.ts" in res_term.stdout
    assert (codealign_dir / "baseline.json").is_file()

    # 2. Test JSON format
    custom_out = tmp_path / "custom_baseline.json"
    res_json = runner.invoke(
        app,
        ["baseline", str(plan_file), "--format", "json", "--output", str(custom_out)],
    )
    assert res_json.exit_code == 0
    parsed = json.loads(res_json.stdout)
    assert parsed["schema_version"] == "0.1.0"
    assert parsed["intent"]["title"] == "Redis Plan"
    assert custom_out.is_file()


def test_baseline_missing_plan_and_uninitialized(tmp_path: Path, monkeypatch) -> None:
    """Verify error reporting for missing plan or uninitialized repository."""
    # Missing plan
    res_missing = runner.invoke(app, ["baseline", str(tmp_path / "nonexistent.md")])
    assert res_missing.exit_code == 1
    assert "Error: Implementation plan file not found" in res_missing.output

    # Uninitialized repo
    plan_file = tmp_path / "plan.md"
    plan_file.write_text("# Plan\n1. Step\n", encoding="utf-8")

    repo_info = GitRepoInfo(
        root=tmp_path,
        branch="main",
        head_sha="0000000000000000",
        is_dirty=False,
    )
    monkeypatch.setattr("codealign.commands.baseline.get_git_repo_info", lambda: repo_info)

    res_uninit = runner.invoke(app, ["baseline", str(plan_file)])
    assert res_uninit.exit_code == 1
    assert "Error: CodeAlign is not initialized" in res_uninit.output
