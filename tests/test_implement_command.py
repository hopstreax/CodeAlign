"""Functional and CLI integration tests for codealign implement command."""

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from typer.testing import CliRunner

from codealign.agent.antigravity import AntigravityResult
from codealign.agent.gemini import GeminiResult
from codealign.cli import app
from codealign.git.repository import GitRepoInfo, NotAGitRepositoryError, run_git_command
from codealign.models.baseline import (
    BaselineEvidence,
    BaselineExpectations,
    BaselineIntent,
    BaselineRepositoryInfo,
    ExpectedFile,
    ExpectedSymbol,
    ExpectedTest,
    ImplementationBaseline,
)
from codealign.models.finding import Finding, FindingCategory, FindingSeverity
from codealign.models.result import VerificationResult, VerificationStatus
from codealign.verify.git_diff import GitChangeSet

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


def test_implement_missing_antigravity_cli(
    initialized_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify implement fails clearly when Antigravity CLI is not available on PATH."""
    monkeypatch.setattr("codealign.agent.AntigravityAgent.is_available", lambda: False)

    result = runner.invoke(app, ["implement", "--agent", "antigravity"])
    assert result.exit_code == 1
    assert "Error: Antigravity CLI ('agy' or 'antigravity') not found on PATH" in result.output
    assert "Please install and configure Antigravity CLI" in result.output


def test_implement_antigravity_success_proceeds_to_verification_pass(
    initialized_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify successful Antigravity execution proceeds to verification and passes cleanly."""
    monkeypatch.setattr("codealign.agent.AntigravityAgent.is_available", lambda: True)

    mock_run = MagicMock(
        return_value=AntigravityResult(
            success=True,
            exit_code=0,
            stdout="Created subtract() in src/calculator.py",
            stderr="",
        )
    )
    monkeypatch.setattr("codealign.agent.AntigravityAgent.run", mock_run)

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

    result = runner.invoke(app, ["implement", "--agent", "antigravity"])
    assert result.exit_code == 0

    # Both Antigravity result and verification result reported
    assert "ANTIGRAVITY IMPLEMENTATION" in result.stdout
    assert "Agent: antigravity" in result.stdout
    assert "Status: SUCCESS (exit code 0)" in result.stdout
    assert "Created subtract() in src/calculator.py" in result.stdout

    assert "CODEALIGN VERIFICATION" in result.stdout
    assert "Result:\n  PASS" in result.stdout
    assert "[OK] Expected file 'src/calculator.py' was modified." in result.stdout


def test_implement_agy_alias(
    initialized_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify --agent agy alias normalizes to antigravity and executes AntigravityAgent."""
    monkeypatch.setattr("codealign.agent.AntigravityAgent.is_available", lambda: True)

    mock_run = MagicMock(
        return_value=AntigravityResult(
            success=True,
            exit_code=0,
            stdout="Created subtract() in src/calculator.py",
            stderr="",
        )
    )
    monkeypatch.setattr("codealign.agent.AntigravityAgent.run", mock_run)
    monkeypatch.setattr(
        "codealign.commands.implement.verify_implementation",
        lambda **kwargs: VerificationResult(status=VerificationStatus.PASS, summary="ok"),
    )

    result = runner.invoke(app, ["implement", "--agent", "agy"])
    assert result.exit_code == 0
    assert "ANTIGRAVITY IMPLEMENTATION" in result.stdout
    assert "Agent: antigravity" in result.stdout
    mock_run.assert_called_once()


def test_implement_antigravity_subprocess_failure(
    initialized_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify Antigravity failure surfaces error and stops before running verification."""
    monkeypatch.setattr("codealign.agent.AntigravityAgent.is_available", lambda: True)

    mock_run = MagicMock(
        return_value=AntigravityResult(
            success=False,
            exit_code=1,
            stdout="",
            stderr="Permission error encountered.",
        )
    )
    monkeypatch.setattr("codealign.agent.AntigravityAgent.run", mock_run)

    mock_verify = MagicMock()
    monkeypatch.setattr("codealign.commands.implement.verify_implementation", mock_verify)

    result = runner.invoke(app, ["implement", "--agent", "antigravity"])
    assert result.exit_code == 1
    assert "ANTIGRAVITY IMPLEMENTATION" in result.stdout
    assert "Agent: antigravity" in result.stdout
    assert "Status: FAILED (exit code 1)" in result.stdout
    assert "Permission error encountered." in result.stdout

    # Verification must NOT run if Antigravity fails
    mock_verify.assert_not_called()


def test_implement_antigravity_json_format(
    initialized_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify --format json outputs structured JSON with antigravity agent key."""
    monkeypatch.setattr("codealign.agent.AntigravityAgent.is_available", lambda: True)

    mock_run = MagicMock(
        return_value=AntigravityResult(
            success=True,
            exit_code=0,
            stdout="Modified files.",
            stderr="",
        )
    )
    monkeypatch.setattr("codealign.agent.AntigravityAgent.run", mock_run)
    monkeypatch.setattr(
        "codealign.commands.implement.verify_implementation",
        lambda **kwargs: VerificationResult(status=VerificationStatus.PASS, summary="ok"),
    )

    result = runner.invoke(app, ["implement", "--agent", "antigravity", "--format", "json"])
    assert result.exit_code == 0

    data = json.loads(result.stdout)
    assert data["agent"] == "antigravity"
    assert data["implementation"]["success"] is True
    assert data["implementation"]["exit_code"] == 0
    assert data["implementation"]["stdout"] == "Modified files."
    assert data["verification"]["status"] == "pass"


def test_implement_options_forwarded_to_antigravity(
    initialized_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify options --dangerously-skip-permissions, --model are passed to Antigravity."""
    monkeypatch.setattr("codealign.agent.AntigravityAgent.is_available", lambda: True)

    mock_run = MagicMock(
        return_value=AntigravityResult(
            success=True,
            exit_code=0,
        )
    )
    monkeypatch.setattr("codealign.agent.AntigravityAgent.run", mock_run)
    monkeypatch.setattr(
        "codealign.commands.implement.verify_implementation",
        lambda **kwargs: VerificationResult(status=VerificationStatus.PASS, summary="ok"),
    )

    result = runner.invoke(
        app,
        [
            "implement",
            "--agent",
            "antigravity",
            "--dangerously-skip-permissions",
            "--model",
            "custom-model",
        ],
    )
    assert result.exit_code == 0

    mock_run.assert_called_once()
    _, kwargs = mock_run.call_args
    assert kwargs["dangerously_skip_permissions"] is True
    assert kwargs["model"] == "custom-model"
    assert kwargs["mode"] == "accept-edits"


def test_implement_passes_session_changeset_to_verification(
    initialized_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """K. Verify implement passes computed session changeset into verify_implementation."""
    monkeypatch.setattr("codealign.agent.GeminiAgent.is_available", lambda: True)
    mock_run = MagicMock(return_value=GeminiResult(success=True, exit_code=0, stdout="Done"))
    monkeypatch.setattr("codealign.agent.GeminiAgent.run", mock_run)

    captured_changeset = None

    def fake_verify(**kwargs):
        nonlocal captured_changeset
        captured_changeset = kwargs.get("changeset")
        return VerificationResult(status=VerificationStatus.PASS, summary="ok")

    monkeypatch.setattr("codealign.commands.implement.verify_implementation", fake_verify)

    result = runner.invoke(app, ["implement"])
    assert result.exit_code == 0
    assert captured_changeset is not None
    assert isinstance(captured_changeset, GitChangeSet)


def test_implement_session_terminal_output_renders_changes(
    initialized_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify SESSION CHANGES section is rendered in terminal output."""
    monkeypatch.setattr("codealign.agent.GeminiAgent.is_available", lambda: True)
    mock_run = MagicMock(
        return_value=GeminiResult(success=True, exit_code=0, stdout="Created file")
    )
    monkeypatch.setattr("codealign.agent.GeminiAgent.run", mock_run)

    mock_session_cs = GitChangeSet(
        base_commit="1234567890abcdef",
        modified={"src/calculator.py"},
        added={"tests/test_calculator.py"},
    )
    monkeypatch.setattr(
        "codealign.commands.implement.compute_session_changes",
        lambda *args: mock_session_cs,
    )
    monkeypatch.setattr(
        "codealign.commands.implement.verify_implementation",
        lambda **kwargs: VerificationResult(status=VerificationStatus.PASS, summary="ok"),
    )

    result = runner.invoke(app, ["implement"])
    assert result.exit_code == 0
    assert "SESSION CHANGES" in result.stdout
    assert "Modified:\n    src/calculator.py" in result.stdout
    assert "Added:\n    tests/test_calculator.py" in result.stdout


def test_implement_session_json_output_contains_session(
    initialized_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify session section is included in JSON output with sorted lists."""
    monkeypatch.setattr("codealign.agent.GeminiAgent.is_available", lambda: True)
    mock_run = MagicMock(return_value=GeminiResult(success=True, exit_code=0, stdout="Modified"))
    monkeypatch.setattr("codealign.agent.GeminiAgent.run", mock_run)

    mock_session_cs = GitChangeSet(
        base_commit="1234567890abcdef",
        modified={"src/calculator.py"},
        added={"new_file.py"},
        deleted={"old_file.py"},
        renamed={"b.py": "a.py"},
    )
    monkeypatch.setattr(
        "codealign.commands.implement.compute_session_changes",
        lambda *args: mock_session_cs,
    )
    monkeypatch.setattr(
        "codealign.commands.implement.verify_implementation",
        lambda **kwargs: VerificationResult(status=VerificationStatus.PASS, summary="ok"),
    )

    result = runner.invoke(app, ["implement", "--format", "json"])
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert "session" in data
    assert data["session"]["modified"] == ["src/calculator.py"]
    assert data["session"]["added"] == ["new_file.py"]
    assert data["session"]["deleted"] == ["old_file.py"]
    assert data["session"]["renamed"] == {"b.py": "a.py"}


def test_implement_session_captured_on_agent_failure(
    initialized_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify session changes are captured and included in JSON even when agent fails."""
    monkeypatch.setattr("codealign.agent.GeminiAgent.is_available", lambda: True)
    mock_run = MagicMock(
        return_value=GeminiResult(success=False, exit_code=1, stderr="Syntax error")
    )
    monkeypatch.setattr("codealign.agent.GeminiAgent.run", mock_run)

    mock_session_cs = GitChangeSet(
        base_commit="1234567890abcdef",
        modified={"src/partial.py"},
    )
    monkeypatch.setattr(
        "codealign.commands.implement.compute_session_changes",
        lambda *args: mock_session_cs,
    )

    result = runner.invoke(app, ["implement", "--format", "json"])
    assert result.exit_code == 1
    data = json.loads(result.stdout)
    assert data["implementation"]["success"] is False
    assert data["session"]["modified"] == ["src/partial.py"]


def test_implement_session_excludes_preexisting_changes_from_scope_drift(
    initialized_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify pre-existing dirty files excluded from session do not produce scope drift."""
    monkeypatch.setattr("codealign.agent.GeminiAgent.is_available", lambda: True)
    mock_run = MagicMock(return_value=GeminiResult(success=True, exit_code=0, stdout="Done"))
    monkeypatch.setattr("codealign.agent.GeminiAgent.run", mock_run)

    # Session only modified the expected calculator file; pre-existing notes.md was excluded
    session_cs = GitChangeSet(
        base_commit="1234567890abcdef",
        modified={"src/calculator.py"},
    )
    monkeypatch.setattr(
        "codealign.commands.implement.compute_session_changes",
        lambda *args: session_cs,
    )

    result = runner.invoke(app, ["implement"])
    assert result.exit_code == 0
    assert "Unexpected file changed" not in result.stdout
    assert "notes.md" not in result.stdout


def test_implement_session_filters_artifacts_from_scope_drift(
    initialized_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """L. Verify workflow artifacts generated during session do not produce scope drift."""
    monkeypatch.setattr("codealign.agent.GeminiAgent.is_available", lambda: True)
    mock_run = MagicMock(return_value=GeminiResult(success=True, exit_code=0, stdout="Done"))
    monkeypatch.setattr("codealign.agent.GeminiAgent.run", mock_run)

    # Session touched expected file PLUS workflow/runtime artifacts
    session_cs = GitChangeSet(
        base_commit="1234567890abcdef",
        modified={"src/calculator.py", "plan.md", ".codealign/config.toml"},
        added={"__pycache__/calc.cpython-312.pyc", "other.pyc"},
    )
    monkeypatch.setattr(
        "codealign.commands.implement.compute_session_changes",
        lambda *args: session_cs,
    )

    result = runner.invoke(app, ["implement"])
    assert result.exit_code == 0
    assert "Unexpected file changed: 'plan.md'" not in result.stdout
    assert "Unexpected file changed: '__pycache__/calc.cpython-312.pyc'" not in result.stdout
    assert "Unexpected file changed: 'other.pyc'" not in result.stdout


def test_implement_detects_symbol_drift_in_expected_file(
    initialized_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End-to-end implement detects symbol-level drift inside expected files."""
    monkeypatch.setattr("codealign.agent.GeminiAgent.is_available", lambda: True)

    calc = initialized_repo / "src" / "calculator.py"
    calc.parent.mkdir(parents=True, exist_ok=True)
    calc.write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")

    # Update baseline with expected symbol 'multiply'
    bl_path = initialized_repo / ".codealign" / "baseline.json"
    bl = ImplementationBaseline.from_file(bl_path)
    bl.expectations.expected_symbols = [
        ExpectedSymbol(name="multiply", kind="function", status="unresolved")
    ]
    bl_path.write_text(bl.to_json(), encoding="utf-8")

    def mock_agent_run(*args, **kwargs):
        # Agent adds expected 'multiply' PLUS unexpected 'divide'
        calc.write_text(
            "def add(a, b):\n    return a + b\n"
            "def multiply(a, b):\n    return a * b\n"
            "def divide(a, b):\n    return a / b\n",
            encoding="utf-8",
        )
        return GeminiResult(success=True, exit_code=0, stdout="Done")

    monkeypatch.setattr("codealign.agent.GeminiAgent.run", mock_agent_run)
    session_cs = GitChangeSet(base_commit="1234567890abcdef", modified={"src/calculator.py"})
    monkeypatch.setattr(
        "codealign.commands.implement.compute_session_changes",
        lambda *args: session_cs,
    )

    # Normal mode: exit code 0, warning rendered
    result = runner.invoke(app, ["implement"])
    assert result.exit_code == 0
    assert "Unexpected symbol 'divide' introduced in 'src/calculator.py'" in result.stdout

    # Reset file before second run to simulate a fresh agent session introducing divide
    calc.write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")

    # Strict mode: exit code 1
    result_strict = runner.invoke(app, ["implement", "--strict"])
    assert result_strict.exit_code == 1


def test_implement_symbol_drift_detected_with_expected_multiply_and_unexpected_divide(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """E2E implement detects unexpected symbol drift during session alongside expected changes."""
    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    # 1. Initialize a clean real Git repo so snapshot capture and session diff execute naturally
    run_git_command(["init", "-b", "main"], cwd=repo_root)
    run_git_command(["config", "user.name", "Test User"], cwd=repo_root)
    run_git_command(["config", "user.email", "test@example.com"], cwd=repo_root)

    calc = repo_root / "src" / "calculator.py"
    calc.parent.mkdir(parents=True, exist_ok=True)
    calc.write_text(
        "def add(a: int, b: int) -> int:\n"
        "    return a + b\n",
        encoding="utf-8",
    )

    test_calc = repo_root / "tests" / "test_calculator.py"
    test_calc.parent.mkdir(parents=True, exist_ok=True)
    test_calc.write_text(
        "from src.calculator import add\n\n\n"
        "def test_add() -> None:\n"
        "    assert add(2, 3) == 5\n",
        encoding="utf-8",
    )

    run_git_command(["add", "."], cwd=repo_root)
    run_git_command(["commit", "-m", "Initial commit"], cwd=repo_root)
    base_commit = run_git_command(["rev-parse", "HEAD"], cwd=repo_root)

    repo_info = GitRepoInfo(
        root=repo_root,
        branch="main",
        head_sha=base_commit,
        is_dirty=False,
    )
    monkeypatch.setattr("codealign.commands.implement.get_git_repo_info", lambda: repo_info)

    # 2. Setup .codealign baseline and context
    codealign_dir = repo_root / ".codealign"
    codealign_dir.mkdir(parents=True, exist_ok=True)

    baseline = ImplementationBaseline(
        schema_version="0.1.0",
        generated_at="2026-10-09T00:00:00Z",
        repository=BaselineRepositoryInfo(
            name=repo_root.name,
            branch="main",
            commit=base_commit,
        ),
        intent=BaselineIntent(
            plan_file="plan.md",
            title="Add Multiply Operation",
            goal="Add multiply operation without changing add.",
            steps=[
                "Add `multiply()` to `src/calculator.py`.",
                "Add a test for `multiply()` to `tests/test_calculator.py`.",
                "Preserve the existing `add()` behavior.",
            ],
        ),
        evidence=BaselineEvidence(),
        expectations=BaselineExpectations(
            expected_files=[
                ExpectedFile(path="src/calculator.py", action="modify", status="resolved"),
                ExpectedFile(path="tests/test_calculator.py", action="modify", status="resolved"),
            ],
            expected_symbols=[
                ExpectedSymbol(
                    name="add",
                    kind="function",
                    file_path="src/calculator.py",
                    status="existing",
                ),
                ExpectedSymbol(name="multiply", kind="function", status="unresolved"),
            ],
            expected_tests=[
                ExpectedTest(path="tests/test_calculator.py", reason="Test multiply"),
            ],
        ),
    )
    (codealign_dir / "baseline.json").write_text(baseline.to_json(), encoding="utf-8")
    (codealign_dir / "context.md").write_text(
        "# Context\nAdd multiply operation\n", encoding="utf-8"
    )

    # 3. Deterministic fake agent run
    monkeypatch.setattr("codealign.agent.GeminiAgent.is_available", lambda: True)

    def fake_agent_run(*args, **kwargs) -> GeminiResult:
        # Preserve add, add expected multiply, add unexpected divide
        calc.write_text(
            "def add(a: int, b: int) -> int:\n"
            "    return a + b\n\n\n"
            "def multiply(a: int, b: int) -> int:\n"
            "    return a * b\n\n\n"
            "def divide(a: int, b: int) -> float:\n"
            "    return a / b\n",
            encoding="utf-8",
        )
        # Add test for multiply
        test_calc.write_text(
            "from src.calculator import add, multiply\n\n\n"
            "def test_add() -> None:\n"
            "    assert add(2, 3) == 5\n\n\n"
            "def test_multiply() -> None:\n"
            "    assert multiply(2, 3) == 6\n",
            encoding="utf-8",
        )
        return GeminiResult(success=True, exit_code=0, stdout="Implemented changes")

    monkeypatch.setattr("codealign.agent.GeminiAgent.run", fake_agent_run)

    # 4. Verify normal mode: exit code 0, expected passes and ABSTRACTION_DRIFT warning rendered
    result_normal = runner.invoke(app, ["implement"])
    assert result_normal.exit_code == 0
    assert "Expected symbol 'multiply' created in 'src/calculator.py'" in result_normal.output
    assert "Expected file 'src/calculator.py' was modified" in result_normal.output
    assert "Expected file 'tests/test_calculator.py' was modified" in result_normal.output
    assert "Expected test file 'tests/test_calculator.py' verified" in result_normal.output
    assert "Unexpected symbol 'divide' introduced in 'src/calculator.py'" in result_normal.output

    # 5. Verify JSON mode to assert finding category is ABSTRACTION_DRIFT explicitly
    calc.write_text("def add(a: int, b: int) -> int:\n    return a + b\n", encoding="utf-8")
    test_calc.write_text(
        "from src.calculator import add\n\ndef test_add() -> None:\n    assert add(2, 3) == 5\n",
        encoding="utf-8",
    )

    result_json = runner.invoke(app, ["implement", "--format", "json"])
    assert result_json.exit_code == 0
    data = json.loads(result_json.output)
    assert data["session"]["modified"] == ["src/calculator.py", "tests/test_calculator.py"]
    assert data["verification"]["status"] == "warn"

    findings = data["verification"]["findings"]
    drift_findings = [f for f in findings if f["category"] == "abstraction_drift"]
    assert len(drift_findings) == 1
    assert drift_findings[0]["symbol"] == "divide"
    assert drift_findings[0]["severity"] == "warn"
    assert (
        "Unexpected symbol 'divide' introduced in 'src/calculator.py'"
        in drift_findings[0]["message"]
    )

    # 6. Verify strict mode: exit code 1 because warnings are treated as failures
    calc.write_text("def add(a: int, b: int) -> int:\n    return a + b\n", encoding="utf-8")
    test_calc.write_text(
        "from src.calculator import add\n\ndef test_add() -> None:\n    assert add(2, 3) == 5\n",
        encoding="utf-8",
    )

    result_strict = runner.invoke(app, ["implement", "--strict"])
    assert result_strict.exit_code == 1
    assert "Unexpected symbol 'divide' introduced in 'src/calculator.py'" in result_strict.output


def test_implement_full_pipeline_session_tracking_abstraction_and_behavioral_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """E2E test for session tracking, abstraction/behavioral drift, and exit codes."""
    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    # 1. Initialize real Git repo with committed add() and test_add()
    run_git_command(["init", "-b", "main"], cwd=repo_root)
    run_git_command(["config", "user.name", "Test User"], cwd=repo_root)
    run_git_command(["config", "user.email", "test@example.com"], cwd=repo_root)

    calc = repo_root / "src" / "calculator.py"
    calc.parent.mkdir(parents=True, exist_ok=True)
    calc.write_text(
        "def add(a: int, b: int) -> int:\n"
        "    return a + b\n",
        encoding="utf-8",
    )

    test_calc = repo_root / "tests" / "test_calculator.py"
    test_calc.parent.mkdir(parents=True, exist_ok=True)
    test_calc.write_text(
        "from src.calculator import add\n\n\n"
        "def test_add() -> None:\n"
        "    assert add(2, 3) == 5\n",
        encoding="utf-8",
    )

    run_git_command(["add", "."], cwd=repo_root)
    run_git_command(["commit", "-m", "Initial commit"], cwd=repo_root)
    base_commit = run_git_command(["rev-parse", "HEAD"], cwd=repo_root)

    repo_info = GitRepoInfo(
        root=repo_root,
        branch="main",
        head_sha=base_commit,
        is_dirty=False,
    )
    monkeypatch.setattr("codealign.commands.implement.get_git_repo_info", lambda: repo_info)

    # 2. Setup pre-existing untracked file before session
    notes_file = repo_root / "local-notes.txt"
    notes_file.write_text("TODO: check performance\n", encoding="utf-8")

    # 3. Setup .codealign baseline expecting multiply() and test_multiply()
    codealign_dir = repo_root / ".codealign"
    codealign_dir.mkdir(parents=True, exist_ok=True)

    baseline = ImplementationBaseline(
        schema_version="0.1.0",
        generated_at="2026-10-09T00:00:00Z",
        repository=BaselineRepositoryInfo(
            name=repo_root.name,
            branch="main",
            commit=base_commit,
        ),
        intent=BaselineIntent(
            plan_file="plan.md",
            title="Add Multiply Operation",
            goal="Add multiply operation without changing add.",
            steps=[
                "Add `multiply()` to `src/calculator.py`.",
                "Add a test for `multiply()` to `tests/test_calculator.py`.",
                "Preserve the existing `add()` behavior.",
            ],
        ),
        evidence=BaselineEvidence(),
        expectations=BaselineExpectations(
            expected_files=[
                ExpectedFile(path="src/calculator.py", action="modify", status="resolved"),
                ExpectedFile(path="tests/test_calculator.py", action="modify", status="resolved"),
            ],
            expected_symbols=[
                ExpectedSymbol(
                    name="add",
                    kind="function",
                    file_path="src/calculator.py",
                    status="existing",
                ),
                ExpectedSymbol(name="multiply", kind="function", status="unresolved"),
            ],
            expected_tests=[
                ExpectedTest(path="tests/test_calculator.py", reason="Test multiply"),
            ],
        ),
    )
    (codealign_dir / "baseline.json").write_text(baseline.to_json(), encoding="utf-8")
    (codealign_dir / "context.md").write_text(
        "# Context\nAdd multiply operation\n", encoding="utf-8"
    )

    # 4. Deterministic fake agent simulation
    monkeypatch.setattr("codealign.agent.AntigravityAgent.is_available", lambda: True)

    def fake_agent_run(*args, **kwargs) -> AntigravityResult:
        # 1. Adds expected multiply()
        # 2. Adds unexpected public divide()
        # 3. Changes existing add() from (a + b) to (a - b)
        calc.write_text(
            "def add(a: int, b: int) -> int:\n"
            "    return a - b\n\n\n"
            "def multiply(a: int, b: int) -> int:\n"
            "    return a * b\n\n\n"
            "def divide(a: int, b: int) -> float:\n"
            "    return a / b\n",
            encoding="utf-8",
        )
        # Adds test_multiply() alongside test_add()
        test_calc.write_text(
            "from src.calculator import add, multiply\n\n\n"
            "def test_add() -> None:\n"
            "    assert add(2, 3) == 5\n\n\n"
            "def test_multiply() -> None:\n"
            "    assert multiply(2, 3) == 6\n",
            encoding="utf-8",
        )
        # 5. Leaves local-notes.txt untouched
        return AntigravityResult(
            success=True,
            exit_code=0,
            stdout="Implemented multiply, modified add, added divide",
        )

    monkeypatch.setattr("codealign.agent.AntigravityAgent.run", fake_agent_run)

    def reset_pre_session_state() -> None:
        calc.write_text(
            "def add(a: int, b: int) -> int:\n"
            "    return a + b\n",
            encoding="utf-8",
        )
        test_calc.write_text(
            "from src.calculator import add\n\n\n"
            "def test_add() -> None:\n"
            "    assert add(2, 3) == 5\n",
            encoding="utf-8",
        )
        notes_file.write_text("TODO: check performance\n", encoding="utf-8")

    # 5. Run normal mode: exit code 0, warnings rendered, expected passed
    result_normal = runner.invoke(app, ["implement", "--agent", "antigravity"])
    assert result_normal.exit_code == 0
    assert "Expected symbol 'multiply' created in 'src/calculator.py'" in result_normal.output
    assert "Expected file 'src/calculator.py' was modified" in result_normal.output
    assert "Expected file 'tests/test_calculator.py' was modified" in result_normal.output
    assert "Expected test file 'tests/test_calculator.py' verified" in result_normal.output
    assert "Unexpected symbol 'divide' introduced in 'src/calculator.py'" in result_normal.output
    assert "Implementation body of function 'add' was modified" in result_normal.output
    assert "local-notes.txt" not in result_normal.output

    # 6. Run JSON mode: verify structured session changes and findings
    reset_pre_session_state()
    result_json = runner.invoke(app, ["implement", "--agent", "antigravity", "--format", "json"])
    assert result_json.exit_code == 0
    data = json.loads(result_json.output)
    assert data["agent"] == "antigravity"
    assert data["session"]["modified"] == ["src/calculator.py", "tests/test_calculator.py"]
    assert "local-notes.txt" not in data["session"]["added"]
    assert "local-notes.txt" not in data["session"]["modified"]
    assert data["verification"]["status"] == "warn"

    findings = data["verification"]["findings"]
    # Scope drift must not include local-notes.txt
    assert not any(f.get("file_path") == "local-notes.txt" for f in findings)
    assert not any(f.get("category") == "scope_drift" for f in findings)

    # Abstraction drift for divide
    abs_drift = [f for f in findings if f["category"] == "abstraction_drift"]
    assert len(abs_drift) == 1
    assert abs_drift[0]["symbol"] == "divide"
    assert abs_drift[0]["severity"] == "warn"
    assert (
        "Unexpected symbol 'divide' introduced in 'src/calculator.py'"
        in abs_drift[0]["message"]
    )

    # Behavioral drift for add
    beh_drift = [f for f in findings if f["category"] == "behavioral_drift"]
    assert len(beh_drift) == 1
    assert beh_drift[0]["symbol"] == "add"
    assert beh_drift[0]["severity"] == "warn"
    assert beh_drift[0]["expected"] == "unmodified function body"
    assert beh_drift[0]["actual"] == "modified body implementation"
    assert (
        "Implementation body of function 'add' was modified in 'src/calculator.py'"
        in beh_drift[0]["message"]
    )

    # Expected symbol passes
    passes = [f for f in findings if f["severity"] == "pass"]
    pass_symbols = {f.get("symbol") for f in passes}
    assert "multiply" in pass_symbols

    # 7. Run strict mode: exit code 1 because warnings escalate to failures
    reset_pre_session_state()
    result_strict = runner.invoke(app, ["implement", "--agent", "antigravity", "--strict"])
    assert result_strict.exit_code == 1
    assert "Unexpected symbol 'divide' introduced in 'src/calculator.py'" in result_strict.output
    assert "Implementation body of function 'add' was modified" in result_strict.output
    assert "local-notes.txt" not in result_strict.output
