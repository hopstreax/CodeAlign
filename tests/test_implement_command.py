"""Functional and CLI integration tests for codealign implement command."""

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from typer.testing import CliRunner

from codealign.agent.gemini import GeminiResult
from codealign.cli import app
from codealign.git.repository import GitRepoInfo, NotAGitRepositoryError
from codealign.models.baseline import (
    BaselineEvidence,
    BaselineExpectations,
    BaselineIntent,
    BaselineRepositoryInfo,
    ExpectedFile,
    ImplementationBaseline,
)
from codealign.models.finding import Finding, FindingCategory, FindingSeverity
from codealign.models.result import VerificationResult, VerificationStatus

runner = CliRunner()


def _make_sample_baseline(repo_root: Path) -> ImplementationBaseline:
    """Create a minimal ImplementationBaseline for tests."""
    return ImplementationBaseline(
        schema_version="0.1.0",
        generated_at="2026-10-06T00:00:00Z",
        repository=BaselineRepositoryInfo(
            name=repo_root.name,
            branch="main",
            commit="1234567890abcdef",
        ),
        intent=BaselineIntent(
            plan_file="plan.md",
            title="Implement Calculator Feature",
            goal="Add calculator subtract function.",
            steps=["Implement `subtract()` in `src/calculator.py`."],
        ),
        evidence=BaselineEvidence(),
        expectations=BaselineExpectations(
            expected_files=[
                ExpectedFile(
                    path="src/calculator.py",
                    action="modify",
                    status="resolved",
                    reason="Target implementation file",
                )
            ],
            expected_symbols=[],
            expected_tests=[],
        ),
    )


@pytest.fixture
def initialized_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Fixture providing initialized repo with baseline.json and context.md."""
    repo_root = tmp_path / "calc_repo"
    repo_root.mkdir()

    repo_info = GitRepoInfo(
        root=repo_root,
        branch="main",
        head_sha="1234567890abcdef",
        is_dirty=False,
    )
    monkeypatch.setattr("codealign.commands.implement.get_git_repo_info", lambda: repo_info)

    codealign_dir = repo_root / ".codealign"
    codealign_dir.mkdir(parents=True)

    baseline = _make_sample_baseline(repo_root)
    (codealign_dir / "baseline.json").write_text(baseline.to_json(), encoding="utf-8")

    context_md = (
        f"# CodeAlign Implementation Context: {baseline.intent.title}\n\n"
        "## Intent\nAdd subtract function.\n\n"
        "## Expected Changes\n- `src/calculator.py`\n"
    )
    (codealign_dir / "context.md").write_text(context_md, encoding="utf-8")

    return repo_root


def test_implement_not_in_git_repo(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify implement fails when not inside a git repository."""
    def fake_git_info():
        raise NotAGitRepositoryError("Not a Git repository")

    monkeypatch.setattr("codealign.commands.implement.get_git_repo_info", fake_git_info)
    result = runner.invoke(app, ["implement"])
    assert result.exit_code == 1
    assert "Error: Not a Git repository" in result.output


def test_implement_uninitialized_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify implement fails when CodeAlign is not initialized."""
    repo_info = GitRepoInfo(
        root=tmp_path,
        branch="main",
        head_sha="123456",
        is_dirty=False,
    )
    monkeypatch.setattr("codealign.commands.implement.get_git_repo_info", lambda: repo_info)

    result = runner.invoke(app, ["implement"])
    assert result.exit_code == 1
    assert "CodeAlign is not initialized" in result.output
    assert "codealign init" in result.output


def test_implement_missing_baseline(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify implement fails clearly when baseline contract is missing."""
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / ".codealign").mkdir()

    repo_info = GitRepoInfo(
        root=repo_root,
        branch="main",
        head_sha="123456",
        is_dirty=False,
    )
    monkeypatch.setattr("codealign.commands.implement.get_git_repo_info", lambda: repo_info)

    result = runner.invoke(app, ["implement"])
    assert result.exit_code == 1
    assert "Error: Baseline contract not found" in result.output
    assert "codealign baseline" in result.output


def test_implement_missing_context(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify implement fails clearly when context.md is missing."""
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    codealign_dir = repo_root / ".codealign"
    codealign_dir.mkdir()

    baseline = _make_sample_baseline(repo_root)
    (codealign_dir / "baseline.json").write_text(baseline.to_json(), encoding="utf-8")

    repo_info = GitRepoInfo(
        root=repo_root,
        branch="main",
        head_sha="123456",
        is_dirty=False,
    )
    monkeypatch.setattr("codealign.commands.implement.get_git_repo_info", lambda: repo_info)

    result = runner.invoke(app, ["implement"])
    assert result.exit_code == 1
    assert "Error: Implementation context artifact not found" in result.output
    assert "codealign context" in result.output


def test_implement_unsupported_agent(initialized_repo: Path) -> None:
    """Verify implement fails when an unsupported agent is specified."""
    result = runner.invoke(app, ["implement", "--agent", "claude"])
    assert result.exit_code == 1
    assert "Error: Unsupported agent 'claude'" in result.output
    assert "Currently supported: 'gemini'" in result.output


def test_implement_missing_gemini_cli(
    initialized_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify implement fails clearly when Gemini CLI is not available on PATH."""
    monkeypatch.setattr("codealign.agent.GeminiAgent.is_available", lambda: False)

    result = runner.invoke(app, ["implement", "--agent", "gemini"])
    assert result.exit_code == 1
    assert "Error: Gemini CLI ('gemini') not found on PATH" in result.output
    assert "Please install and authenticate Gemini CLI" in result.output


def test_implement_gemini_subprocess_failure(
    initialized_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify Gemini failure surfaces error and stops before running verification."""
    monkeypatch.setattr("codealign.agent.GeminiAgent.is_available", lambda: True)

    mock_run = MagicMock(
        return_value=GeminiResult(
            success=False,
            exit_code=1,
            stdout="",
            stderr="Authentication expired. Please re-authenticate.",
        )
    )
    monkeypatch.setattr("codealign.agent.GeminiAgent.run", mock_run)

    mock_verify = MagicMock()
    monkeypatch.setattr("codealign.commands.implement.verify_implementation", mock_verify)

    result = runner.invoke(app, ["implement"])
    assert result.exit_code == 1
    assert "GEMINI IMPLEMENTATION" in result.stdout
    assert "Status: FAILED (exit code 1)" in result.stdout
    assert "Authentication expired" in result.stdout

    # Verification must NOT be run if Gemini fails
    mock_verify.assert_not_called()


def test_implement_success_proceeds_to_verification_pass(
    initialized_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify successful Gemini execution proceeds to verification and passes cleanly."""
    monkeypatch.setattr("codealign.agent.GeminiAgent.is_available", lambda: True)

    mock_run = MagicMock(
        return_value=GeminiResult(
            success=True,
            exit_code=0,
            stdout="Created subtract() in src/calculator.py",
            stderr="",
        )
    )
    monkeypatch.setattr("codealign.agent.GeminiAgent.run", mock_run)

    mock_verify_result = VerificationResult(
        status=VerificationStatus.PASS,
        summary="1 pass, 0 warnings, 0 failures",
        findings=[
            Finding(
                category=FindingCategory.MISSING_IMPLEMENTATION,
                severity=FindingSeverity.PASS,
                message="Expected file 'src/calculator.py' was modified.",
                file_path="src/calculator.py",
                expected="modify",
                actual="modified",
                evidence="File modified in working tree",
            )
        ],
    )
    monkeypatch.setattr(
        "codealign.commands.implement.verify_implementation",
        lambda **kwargs: mock_verify_result,
    )

    result = runner.invoke(app, ["implement"])
    assert result.exit_code == 0

    # Both Gemini result and verification result reported
    assert "GEMINI IMPLEMENTATION" in result.stdout
    assert "Status: SUCCESS (exit code 0)" in result.stdout
    assert "Created subtract() in src/calculator.py" in result.stdout

    assert "CODEALIGN VERIFICATION" in result.stdout
    assert "Result:\n  PASS" in result.stdout
    assert "[OK] Expected file 'src/calculator.py' was modified." in result.stdout
    assert "Summary:\n  1 pass, 0 warnings, 0 failures" in result.stdout


def test_implement_success_proceeds_to_verification_fail(
    initialized_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify successful Gemini execution proceeds to verification and fails if changes missing."""
    monkeypatch.setattr("codealign.agent.GeminiAgent.is_available", lambda: True)

    mock_run = MagicMock(
        return_value=GeminiResult(
            success=True,
            exit_code=0,
            stdout="Execution completed.",
        )
    )
    monkeypatch.setattr("codealign.agent.GeminiAgent.run", mock_run)

    mock_verify_result = VerificationResult(
        status=VerificationStatus.FAIL,
        summary="0 passes, 0 warnings, 1 failure",
        findings=[
            Finding(
                category=FindingCategory.MISSING_IMPLEMENTATION,
                severity=FindingSeverity.ERROR,
                message="Expected file 'src/calculator.py' was not modified.",
                file_path="src/calculator.py",
                expected="modify",
                actual="unchanged",
                evidence="File has no modifications",
            )
        ],
    )
    monkeypatch.setattr(
        "codealign.commands.implement.verify_implementation",
        lambda **kwargs: mock_verify_result,
    )

    result = runner.invoke(app, ["implement"])
    assert result.exit_code == 1

    # Both reported
    assert "GEMINI IMPLEMENTATION" in result.stdout
    assert "Status: SUCCESS (exit code 0)" in result.stdout

    assert "CODEALIGN VERIFICATION" in result.stdout
    assert "Result:\n  FAIL" in result.stdout
    assert "[X] Expected file 'src/calculator.py' was not modified." in result.stdout


def test_implement_json_format(
    initialized_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify --format json outputs structured JSON with both implementation and verification."""
    monkeypatch.setattr("codealign.agent.GeminiAgent.is_available", lambda: True)

    mock_run = MagicMock(
        return_value=GeminiResult(
            success=True,
            exit_code=0,
            stdout="Modified files.",
            stderr="",
        )
    )
    monkeypatch.setattr("codealign.agent.GeminiAgent.run", mock_run)

    mock_verify_result = VerificationResult(
        status=VerificationStatus.PASS,
        summary="1 pass, 0 warnings, 0 failures",
        findings=[],
    )
    monkeypatch.setattr(
        "codealign.commands.implement.verify_implementation",
        lambda **kwargs: mock_verify_result,
    )

    result = runner.invoke(app, ["implement", "--format", "json"])
    assert result.exit_code == 0

    data = json.loads(result.stdout)
    assert data["agent"] == "gemini"
    assert data["implementation"]["success"] is True
    assert data["implementation"]["exit_code"] == 0
    assert data["implementation"]["stdout"] == "Modified files."
    assert data["verification"]["status"] == "pass"


def test_implement_options_forwarded_to_gemini(
    initialized_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify CLI options --approval-mode, --yolo, --model are forwarded to GeminiAgent.run."""
    monkeypatch.setattr("codealign.agent.GeminiAgent.is_available", lambda: True)

    mock_run = MagicMock(
        return_value=GeminiResult(
            success=True,
            exit_code=0,
        )
    )
    monkeypatch.setattr("codealign.agent.GeminiAgent.run", mock_run)
    monkeypatch.setattr(
        "codealign.commands.implement.verify_implementation",
        lambda **kwargs: VerificationResult(status=VerificationStatus.PASS, summary="ok"),
    )

    result = runner.invoke(
        app,
        [
            "implement",
            "--approval-mode",
            "plan",
            "--yolo",
            "--model",
            "gemini-2.5-pro",
        ],
    )
    assert result.exit_code == 0

    mock_run.assert_called_once()
    _, kwargs = mock_run.call_args
    assert kwargs["approval_mode"] == "plan"
    assert kwargs["yolo"] is True
    assert kwargs["model"] == "gemini-2.5-pro"
