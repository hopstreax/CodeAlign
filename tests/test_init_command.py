"""Unit and functional tests for codealign init command."""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from codealign.cli import app
from codealign.git.repository import GitRepoInfo, NotAGitRepositoryError

runner = CliRunner()


@pytest.fixture
def mock_git_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Fixture providing a simulated Git repository environment."""
    repo_root = tmp_path / "mock_project"
    repo_root.mkdir()

    repo_info = GitRepoInfo(
        root=repo_root,
        branch="main",
        head_sha="0123456789abcdef0123456789abcdef01234567",
        is_dirty=False,
    )

    monkeypatch.setattr(
        "codealign.commands.init.get_git_repo_info",
        lambda path=None: repo_info,
    )

    return repo_root


def test_init_command_success(
    mock_git_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify first-time initialization with mocked Graphify extraction."""

    def mock_extract(repo_root: Path, output_dir: Path, executable: str | None = None) -> Path:
        target = output_dir / "graphify-out" / "graph.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(
                {
                    "nodes": [{"id": "n1"}, {"id": "n2"}, {"id": "n3"}],
                    "edges": [{"source": "n1", "target": "n2"}, {"source": "n2", "target": "n3"}],
                }
            ),
            encoding="utf-8",
        )
        return target

    monkeypatch.setattr(
        "codealign.commands.init.find_graphify_executable",
        lambda: "dummy-graphify",
    )
    monkeypatch.setattr(
        "codealign.commands.init.run_graphify_extraction",
        mock_extract,
    )

    result = runner.invoke(app, ["init", "--path", str(mock_git_repo)])
    assert result.exit_code == 0
    assert "Initialized CodeAlign in:" in result.stdout
    assert "mock_project" in result.stdout
    assert "Branch:" in result.stdout
    assert "main" in result.stdout
    assert "HEAD:" in result.stdout
    assert "0123456789abcdef" in result.stdout
    assert "Graphify:\n  available" in result.stdout
    assert "3 nodes" in result.stdout
    assert "2 relationships" in result.stdout

    # Verify .codealign directory was created
    config_file = mock_git_repo / ".codealign" / "config.toml"
    assert config_file.is_file()


def test_repeated_init_behavior(
    mock_git_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify repeated init without --force detects existing setup."""

    def mock_extract(repo_root: Path, output_dir: Path, executable: str | None = None) -> Path:
        target = output_dir / "graphify-out" / "graph.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps({"nodes": [{"id": "n1"}], "edges": []}),
            encoding="utf-8",
        )
        return target

    monkeypatch.setattr(
        "codealign.commands.init.find_graphify_executable", lambda: "dummy-graphify"
    )
    monkeypatch.setattr("codealign.commands.init.run_graphify_extraction", mock_extract)

    # First init
    res1 = runner.invoke(app, ["init", "--path", str(mock_git_repo)])
    assert res1.exit_code == 0
    assert "Initialized CodeAlign in:" in res1.stdout

    # Second init without --force
    res2 = runner.invoke(app, ["init", "--path", str(mock_git_repo)])
    assert res2.exit_code == 0
    assert "CodeAlign is already initialized in:" in res2.stdout
    assert "(use --force to re-initialize)" in res2.stdout
    assert "1 nodes" in res2.stdout

    # Third init with --force
    res3 = runner.invoke(app, ["init", "--path", str(mock_git_repo), "--force"])
    assert res3.exit_code == 0
    assert "Initialized CodeAlign in:" in res3.stdout


def test_init_skip_graphify(
    mock_git_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify --skip-graphify initializes config but bypasses extraction."""
    monkeypatch.setattr(
        "codealign.commands.init.find_graphify_executable", lambda: "dummy-graphify"
    )

    result = runner.invoke(app, ["init", "--path", str(mock_git_repo), "--skip-graphify"])
    assert result.exit_code == 0
    assert "skipped (--skip-graphify specified)" in result.stdout
    assert (mock_git_repo / ".codealign" / "config.toml").is_file()


def test_init_non_git_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify codealign init fails cleanly when run outside a Git repository."""

    def mock_raise(path=None):
        raise NotAGitRepositoryError("Not in a git repository")

    monkeypatch.setattr("codealign.commands.init.get_git_repo_info", mock_raise)

    result = runner.invoke(app, ["init", "--path", str(tmp_path)])
    assert result.exit_code == 1
    assert "Error:" in result.output or "not inside a Git repository" in result.output


def test_init_real_graphify_integration(tmp_path: Path) -> None:
    """End-to-end integration test verifying real Graphify extraction into .codealign."""
    import subprocess

    from codealign.graphify.client import find_graphify_executable

    exe = find_graphify_executable()
    if not exe:
        pytest.skip("Graphify executable not available on PATH")

    # Create a tiny Git repo with 1 python file
    repo_dir = tmp_path / "mini_repo"
    repo_dir.mkdir()
    subprocess.run(["git", "init"], cwd=repo_dir, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=repo_dir,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Tester"],
        cwd=repo_dir,
        check=True,
        capture_output=True,
    )
    (repo_dir / "service.py").write_text(
        "class UserService:\n    def get_profile(self):\n        pass\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "."], cwd=repo_dir, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=repo_dir,
        check=True,
        capture_output=True,
    )

    result = runner.invoke(app, ["init", "--path", str(repo_dir)])
    assert result.exit_code == 0
    assert "Graphify:\n  available" in result.stdout
    assert "Code intelligence:" in result.stdout
    assert "nodes" in result.stdout

    # Verify graph.json exists inside .codealign/graphify-out/
    graph_path = repo_dir / ".codealign" / "graphify-out" / "graph.json"
    assert graph_path.is_file()

    # Verify no root graphify-out pollution occurred in repo_dir
    assert not (repo_dir / "graphify-out").exists()
