"""Unit and functional tests for codealign analyze CLI command."""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from codealign.cli import app
from codealign.git.repository import GitRepoInfo

runner = CliRunner()


@pytest.fixture
def mock_repo_with_graph(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    """Create a mock repository with initialized .codealign and graph.json."""
    repo_root = tmp_path / "test_repo"
    repo_root.mkdir()

    repo_info = GitRepoInfo(
        root=repo_root,
        branch="main",
        head_sha="0123456789abcdef0123456789abcdef01234567",
        is_dirty=False,
    )
    monkeypatch.setattr("codealign.commands.analyze.get_git_repo_info", lambda: repo_info)

    # Setup .codealign/
    codealign_dir = repo_root / ".codealign"
    out_dir = codealign_dir / "graphify-out"
    out_dir.mkdir(parents=True)

    config_content = """[repository]
name = "test_repo"

[graphify]
graph_file = "graphify-out/graph.json"
"""
    (codealign_dir / "config.toml").write_text(config_content, encoding="utf-8")

    # Sample graph with UserService.getProfile
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
                "id": "fn_show_user",
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
                "source": "fn_show_user",
                "target": "m_get_profile",
                "relation": "calls",
                "source_file": "src/controllers/UserController.ts",
                "source_location": "L25",
            },
        ],
    }
    (out_dir / "graph.json").write_text(json.dumps(graph_data), encoding="utf-8")

    # Create plan.md
    plan_path = repo_root / "plan.md"
    plan_text = """# Add Redis Caching
1. Update `UserService.getProfile()`.
2. Review `src/services/UserService.ts`.
3. Add `NonExistentClass.method()`.
"""
    plan_path.write_text(plan_text, encoding="utf-8")

    return repo_root, plan_path


def test_analyze_command_terminal(mock_repo_with_graph: tuple[Path, Path]) -> None:
    """Verify human-readable terminal output from codealign analyze."""
    _, plan_path = mock_repo_with_graph
    result = runner.invoke(app, ["analyze", str(plan_path)])

    assert result.exit_code == 0
    assert "CodeAlign Plan Analysis" in result.stdout
    assert "RESOLVED REFERENCES" in result.stdout
    assert "UserService.getProfile()" in result.stdout
    assert "src/services/UserService.ts:42" in result.stdout
    assert "Callers:" in result.stdout
    assert "src/controllers/UserController.ts:25 (showUser)" in result.stdout
    assert "UNRESOLVED REFERENCES" in result.stdout
    assert "NonExistentClass.method()" in result.stdout


def test_analyze_command_json(mock_repo_with_graph: tuple[Path, Path]) -> None:
    """Verify machine-readable JSON output from codealign analyze --format json."""
    _, plan_path = mock_repo_with_graph
    result = runner.invoke(app, ["analyze", str(plan_path), "--format", "json"])

    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["plan_title"] == "Add Redis Caching"
    assert data["summary"]["resolved_count"] == 2
    assert data["summary"]["unresolved_count"] == 1

    resolved_symbols = [r["symbol"] for r in data["resolved"]]
    assert "UserService.getProfile" in resolved_symbols
    assert "src/services/UserService.ts" in resolved_symbols

    # Verify caller information is present in JSON
    method_entry = next(r for r in data["resolved"] if r["symbol"] == "UserService.getProfile")
    assert len(method_entry["callers"]) == 1
    assert method_entry["callers"][0]["symbol"] == "showUser"
    assert method_entry["callers"][0]["file_path"] == "src/controllers/UserController.ts"


def test_analyze_missing_plan_file(mock_repo_with_graph: tuple[Path, Path]) -> None:
    """Verify error when specified plan file does not exist."""
    repo_root, _ = mock_repo_with_graph
    missing = repo_root / "nonexistent.md"
    result = runner.invoke(app, ["analyze", str(missing)])
    assert result.exit_code == 1
    assert "Error:" in result.output
    assert "not found" in result.output


def test_analyze_uninitialized_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify helpful error message when running analyze in an uninitialized repo."""
    repo_root = tmp_path / "uninit_repo"
    repo_root.mkdir()
    plan_path = repo_root / "plan.md"
    plan_path.write_text("# Plan\nTouch `file.py`\n", encoding="utf-8")

    repo_info = GitRepoInfo(
        root=repo_root,
        branch="main",
        head_sha="123456",
        is_dirty=False,
    )
    monkeypatch.setattr("codealign.commands.analyze.get_git_repo_info", lambda: repo_info)

    result = runner.invoke(app, ["analyze", str(plan_path)])
    assert result.exit_code == 1
    assert "Run 'codealign init' first" in result.output


def test_analyze_command_escaped_underscores(
    mock_repo_with_graph: tuple[Path, Path],
) -> None:
    """Verify codealign analyze resolves references with escaped underscores."""
    repo_root, _ = mock_repo_with_graph
    out_dir = repo_root / ".codealign" / "graphify-out"
    graph_path = out_dir / "graph.json"
    graph_data = json.loads(graph_path.read_text(encoding="utf-8"))
    graph_data["nodes"].extend(
        [
            {
                "id": "f_repo",
                "label": "repository.py",
                "source_file": "src/codealign/git/repository.py",
                "source_location": "L1",
                "file_type": "code",
            },
            {
                "id": "fn_get_repo_info",
                "label": "get_git_repo_info()",
                "source_file": "src/codealign/git/repository.py",
                "source_location": "L47",
                "file_type": "code",
                "_callable": True,
            },
            {
                "id": "f_test_git",
                "label": "test_git.py",
                "source_file": "tests/test_git.py",
                "source_location": "L1",
                "file_type": "code",
            },
        ]
    )
    graph_path.write_text(json.dumps(graph_data), encoding="utf-8")

    plan_path = repo_root / "test-plan.md"
    plan_path.write_text(
        r"""# Improve Git Repository Detection
1. Update `get\_git\_repo\_info()` in `src/codealign/git/repository.py`.
2. Add tests for Git repository detection in `tests/test\_git.py`.
""",
        encoding="utf-8",
    )

    result = runner.invoke(app, ["analyze", str(plan_path)])
    assert result.exit_code == 0
    assert "RESOLVED REFERENCES (3)" in result.stdout
    assert "src/codealign/git/repository.py:47" in result.stdout
    assert "tests/test_git.py:1" in result.stdout
    assert "UNRESOLVED REFERENCES" not in result.stdout
