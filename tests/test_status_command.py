"""Comprehensive unit tests for codealign status command."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from typer.testing import CliRunner

from codealign.cli import app
from codealign.git.repository import GitRepoInfo, NotAGitRepositoryError
from codealign.models.baseline import (
    BaselineEvidence,
    BaselineEvidenceItem,
    BaselineExpectations,
    BaselineIntent,
    BaselineRepositoryInfo,
    ExpectedFile,
    ExpectedSymbol,
    ExpectedTest,
    ImplementationBaseline,
)
from codealign.verify.git_diff import BaseCommitNotFoundError, GitChangeSet

runner = CliRunner()


def _make_sample_baseline(repo_root: Path, commit: str = "abc1234567890") -> ImplementationBaseline:
    """Helper to create a standard valid ImplementationBaseline."""
    return ImplementationBaseline(
        schema_version="0.1.0",
        generated_at="2026-10-10T12:00:00+00:00",
        repository=BaselineRepositoryInfo(
            name=repo_root.name,
            branch="main",
            commit=commit,
        ),
        intent=BaselineIntent(
            plan_file="plan.md",
            title="Add user service endpoint",
            goal="Implement user profile lookup",
            steps=["Update `src/service.py`", "Create `tests/test_service.py`"],
        ),
        evidence=BaselineEvidence(
            summary={"total": 2, "resolved": 1, "unresolved": 1},
            resolved=[
                BaselineEvidenceItem(
                    reference="src/service.py",
                    status="resolved",
                    kind="file",
                    symbol="UserService",
                    file_path="src/service.py",
                    line=10,
                )
            ],
            unresolved=[
                BaselineEvidenceItem(
                    reference="unknown_dep",
                    status="unresolved",
                    kind="symbol",
                    reason="Reference not found",
                )
            ],
        ),
        expectations=BaselineExpectations(
            expected_files=[
                ExpectedFile(
                    path="src/service.py",
                    action="modify",
                    status="resolved",
                    reason="Target service file",
                ),
                ExpectedFile(
                    path="tests/test_service.py",
                    action="create",
                    status="expected",
                    reason="New unit test file",
                ),
            ],
            expected_symbols=[
                ExpectedSymbol(
                    name="UserService.get_profile",
                    kind="method",
                    file_path="src/service.py",
                    status="existing",
                )
            ],
            expected_tests=[
                ExpectedTest(
                    path="tests/test_service.py",
                    reason="Unit test coverage",
                )
            ],
        ),
        constraints=["Maintain backwards compatibility with legacy API"],
    )


def test_status_not_in_git_repo(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify status fails with clear error and exit code 1 when not in a Git repository."""
    def fake_repo_info():
        raise NotAGitRepositoryError("Current directory is not inside a Git repository.")

    monkeypatch.setattr("codealign.commands.status.get_git_repo_info", fake_repo_info)
    result = runner.invoke(app, ["status"])

    assert result.exit_code == 1
    assert "Error: Current directory is not inside a Git repository." in result.output
    assert "CodeAlign requires a Git repository." in result.output


def test_status_uninitialized_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify status fails with actionable guidance when CodeAlign is not initialized."""
    repo_info = GitRepoInfo(
        root=tmp_path,
        branch="main",
        head_sha="abc1234567890",
        is_dirty=False,
    )
    monkeypatch.setattr("codealign.commands.status.get_git_repo_info", lambda: repo_info)

    result = runner.invoke(app, ["status"])

    assert result.exit_code == 1
    assert "Error: CodeAlign is not initialized in" in result.output
    assert "Run 'codealign init' first" in result.output


def test_status_missing_baseline(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify status fails when .codealign exists but baseline.json is missing."""
    codealign_dir = tmp_path / ".codealign"
    codealign_dir.mkdir()

    repo_info = GitRepoInfo(
        root=tmp_path,
        branch="main",
        head_sha="abc1234567890",
        is_dirty=False,
    )
    monkeypatch.setattr("codealign.commands.status.get_git_repo_info", lambda: repo_info)

    result = runner.invoke(app, ["status"])

    assert result.exit_code == 1
    assert "Error: Baseline contract not found at" in result.output
    assert "Run 'codealign baseline <plan.md>' first" in result.output


def test_status_malformed_baseline(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify status fails cleanly with actionable message when baseline.json has invalid JSON."""
    codealign_dir = tmp_path / ".codealign"
    codealign_dir.mkdir()
    baseline_file = codealign_dir / "baseline.json"
    baseline_file.write_text("{ this is malformed json", encoding="utf-8")

    repo_info = GitRepoInfo(
        root=tmp_path,
        branch="main",
        head_sha="abc1234567890",
        is_dirty=False,
    )
    monkeypatch.setattr("codealign.commands.status.get_git_repo_info", lambda: repo_info)

    result = runner.invoke(app, ["status"])

    assert result.exit_code == 1
    assert "Error loading baseline file at" in result.output
    assert "Verify that the file contains valid JSON" in result.output


def test_status_baseline_commit_absent_from_git_history(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify status reports BaseCommitNotFoundError and exits with 1 when commit is missing."""
    codealign_dir = tmp_path / ".codealign"
    codealign_dir.mkdir()
    baseline = _make_sample_baseline(tmp_path, commit="deadbeef99999")
    (codealign_dir / "baseline.json").write_text(baseline.to_json(), encoding="utf-8")

    repo_info = GitRepoInfo(
        root=tmp_path,
        branch="main",
        head_sha="abc1234567890",
        is_dirty=False,
    )
    monkeypatch.setattr("codealign.commands.status.get_git_repo_info", lambda: repo_info)

    def fake_get_git_changes(root, commit):
        raise BaseCommitNotFoundError(
            f"Baseline commit '{commit}' does not exist in current Git history."
        )

    monkeypatch.setattr("codealign.commands.status.get_git_changes", fake_get_git_changes)

    result = runner.invoke(app, ["status"])

    assert result.exit_code == 1
    assert (
        "Error: Baseline commit 'deadbeef99999' does not exist in current Git history."
        in result.output
    )
    assert "rebased or squashed" in result.output
    assert "codealign baseline <plan.md>" in result.output


def test_status_valid_baseline_clean_repo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify status exits with 0 and shows status report even with pending implementation."""
    codealign_dir = tmp_path / ".codealign"
    codealign_dir.mkdir()
    baseline = _make_sample_baseline(tmp_path, commit="abc1234567890")
    (codealign_dir / "baseline.json").write_text(baseline.to_json(), encoding="utf-8")

    repo_info = GitRepoInfo(
        root=tmp_path,
        branch="main",
        head_sha="abc1234567890",
        is_dirty=False,
    )
    monkeypatch.setattr("codealign.commands.status.get_git_repo_info", lambda: repo_info)

    empty_changeset = GitChangeSet(
        base_commit="abc1234567890",
        modified=set(),
        added=set(),
        deleted=set(),
        renamed={},
    )
    monkeypatch.setattr(
        "codealign.commands.status.get_git_changes",
        lambda root, commit: empty_changeset,
    )

    result = runner.invoke(app, ["status"])

    assert result.exit_code == 0
    assert "CODEALIGN STATUS" in result.output
    assert "Repository:" in result.output
    assert f"Name:          {tmp_path.name}" in result.output
    assert "Branch:        main" in result.output
    assert "Working tree:  clean" in result.output
    assert "Active Baseline:" in result.output
    assert "Plan:          Add user service endpoint (plan.md)" in result.output
    assert "Evidence:      1 resolved, 1 unresolved" in result.output
    assert "Expectations:  2 files, 1 tests, 1 symbols, 1 constraints" in result.output
    assert "Changes Since Baseline:" in result.output
    assert "Files:         0 modified, 0 added, 0 deleted, 0 renamed" in result.output
    assert "Scope drift:   clean (0 unexpected files)" in result.output
    assert "Fresh Verification (Current Working Tree):" in result.output
    assert "Status:        FAIL" in result.output  # Pending files correctly reported as missing
    assert "Failures:" in result.output
    assert "Note: Standalone status reflects fresh verification" in result.output


def test_status_expected_changes_and_scope_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify status accurately classifies expected modifications and unexpected scope drift."""
    codealign_dir = tmp_path / ".codealign"
    codealign_dir.mkdir()
    baseline = _make_sample_baseline(tmp_path, commit="abc1234567890")
    (codealign_dir / "baseline.json").write_text(baseline.to_json(), encoding="utf-8")

    # Set up actual file on disk
    src_file = tmp_path / "src" / "service.py"
    src_file.parent.mkdir(parents=True)
    src_file.write_text("class UserService:\n    def get_profile(self):\n        pass\n")

    repo_info = GitRepoInfo(
        root=tmp_path,
        branch="main",
        head_sha="abc1234567890",
        is_dirty=True,
    )
    monkeypatch.setattr("codealign.commands.status.get_git_repo_info", lambda: repo_info)

    changeset = GitChangeSet(
        base_commit="abc1234567890",
        modified={"src/service.py"},
        added={"unexpected_file.txt"},
        deleted=set(),
        renamed={},
    )
    monkeypatch.setattr("codealign.commands.status.get_git_changes", lambda root, commit: changeset)

    result = runner.invoke(app, ["status"])

    assert result.exit_code == 0
    assert "Changes Since Baseline:" in result.output
    assert "Files:         1 modified, 1 added, 0 deleted, 0 renamed" in result.output
    assert "Scope drift:   1 unexpected file(s)" in result.output
    assert "[!] unexpected_file.txt" in result.output


def test_status_read_only_behavior_preserves_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify that status is strictly read-only and does not mutate or create repository files."""
    codealign_dir = tmp_path / ".codealign"
    codealign_dir.mkdir()
    baseline = _make_sample_baseline(tmp_path, commit="abc1234567890")
    baseline_json = baseline.to_json()
    baseline_path = codealign_dir / "baseline.json"
    baseline_path.write_text(baseline_json, encoding="utf-8")

    src_file = tmp_path / "src" / "service.py"
    src_file.parent.mkdir(parents=True)
    src_file.write_text("# service code\n")

    untracked_file = tmp_path / "notes.txt"
    untracked_file.write_text("local developer notes\n")

    repo_info = GitRepoInfo(
        root=tmp_path,
        branch="main",
        head_sha="abc1234567890",
        is_dirty=True,
    )
    monkeypatch.setattr("codealign.commands.status.get_git_repo_info", lambda: repo_info)

    changeset = GitChangeSet(
        base_commit="abc1234567890",
        modified={"src/service.py"},
        added={"notes.txt"},
        deleted=set(),
        renamed={},
    )
    monkeypatch.setattr("codealign.commands.status.get_git_changes", lambda root, commit: changeset)

    # Capture snapshot of files and contents before running status
    before_files = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}

    result = runner.invoke(app, ["status"])

    assert result.exit_code == 0
    after_files = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}

    assert before_files == after_files, "Filesystem was mutated by status command"


def test_status_no_graphify_or_agent_invocation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify status executes without invoking Graphify or coding agents."""
    codealign_dir = tmp_path / ".codealign"
    codealign_dir.mkdir()
    baseline = _make_sample_baseline(tmp_path, commit="abc1234567890")
    (codealign_dir / "baseline.json").write_text(baseline.to_json(), encoding="utf-8")

    repo_info = GitRepoInfo(
        root=tmp_path,
        branch="main",
        head_sha="abc1234567890",
        is_dirty=False,
    )
    monkeypatch.setattr("codealign.commands.status.get_git_repo_info", lambda: repo_info)
    empty_changeset = GitChangeSet(base_commit="abc1234567890")
    monkeypatch.setattr(
        "codealign.commands.status.get_git_changes",
        lambda root, commit: empty_changeset,
    )

    # Mock Graphify and Agent functions to ensure they are never called
    graphify_mock = MagicMock()
    gemini_mock = MagicMock()
    antigravity_mock = MagicMock()
    monkeypatch.setattr("codealign.graphify.client.run_graphify_extraction", graphify_mock)
    monkeypatch.setattr("codealign.agent.gemini.GeminiAgent.run", gemini_mock)
    monkeypatch.setattr("codealign.agent.antigravity.AntigravityAgent.run", antigravity_mock)

    result = runner.invoke(app, ["status"])

    assert result.exit_code == 0
    assert graphify_mock.call_count == 0
    assert gemini_mock.call_count == 0
    assert antigravity_mock.call_count == 0


def test_status_custom_baseline_option(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify status accepts a custom baseline path with --baseline / -b option."""
    custom_baseline_file = tmp_path / "custom_baseline.json"
    baseline = _make_sample_baseline(tmp_path, commit="abc1234567890")
    custom_baseline_file.write_text(baseline.to_json(), encoding="utf-8")

    # .codealign directory exists
    (tmp_path / ".codealign").mkdir()

    repo_info = GitRepoInfo(
        root=tmp_path,
        branch="main",
        head_sha="abc1234567890",
        is_dirty=False,
    )
    monkeypatch.setattr("codealign.commands.status.get_git_repo_info", lambda: repo_info)
    empty_changeset = GitChangeSet(base_commit="abc1234567890")
    monkeypatch.setattr(
        "codealign.commands.status.get_git_changes",
        lambda root, commit: empty_changeset,
    )

    result = runner.invoke(app, ["status", "-b", str(custom_baseline_file)])

    assert result.exit_code == 0
    assert "Active Baseline:" in result.output
    assert "Add user service endpoint" in result.output
