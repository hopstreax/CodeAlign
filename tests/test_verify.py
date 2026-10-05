"""Unit and functional tests for codealign verify command and verification engine."""

import hashlib
from pathlib import Path

from typer.testing import CliRunner

from codealign.cli import app
from codealign.git.repository import GitRepoInfo
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
from codealign.models.finding import FindingCategory
from codealign.models.result import VerificationStatus
from codealign.verify.git_diff import GitChangeSet
from codealign.verify.verifier import verify_implementation

runner = CliRunner()


def _make_sample_baseline(
    commit: str = "abcdef1234567890",
    repo_name: str = "CodeAlign",
) -> ImplementationBaseline:
    """Create a realistic ImplementationBaseline fixture for verification tests."""
    return ImplementationBaseline(
        schema_version="0.1.0",
        generated_at="2026-10-05T12:00:00Z",
        repository=BaselineRepositoryInfo(
            name=repo_name,
            branch="main",
            commit=commit,
        ),
        intent=BaselineIntent(
            plan_file="plan.md",
            title="Add Redis cache to user profiles",
            goal="Add Redis cache for profile lookups.",
            steps=[
                "Update `UserService.getProfile()` to query Redis cache.",
                "Create `tests/test_cache.py`.",
                "Review `docs/missing_notes.md`.",
            ],
        ),
        evidence=BaselineEvidence(
            summary={"total_references": 3, "resolved_count": 1, "unresolved_count": 2},
            resolved=[
                BaselineEvidenceItem(
                    reference="UserService.getProfile()",
                    status="resolved",
                    kind="method",
                    symbol="UserService.getProfile",
                    file_path="src/services/UserService.ts",
                    line=42,
                ),
            ],
            unresolved=[
                BaselineEvidenceItem(
                    reference="docs/missing_notes.md",
                    status="unresolved",
                    kind="file",
                    reason="File 'docs/missing_notes.md' not found in codebase graph",
                ),
                BaselineEvidenceItem(
                    reference="MissingService.missingMethod()",
                    status="unresolved",
                    kind="method",
                    reason="Class 'MissingService' not found in codebase graph",
                ),
            ],
        ),
        expectations=BaselineExpectations(
            expected_files=[
                ExpectedFile(
                    path="docs/missing_notes.md",
                    action="unresolved",
                    status="unresolved",
                    reason="File referenced by plan does not currently exist in repository",
                ),
                ExpectedFile(
                    path="src/services/UserService.ts",
                    action="modify",
                    status="resolved",
                    reason="Defines target symbol 'UserService.getProfile'",
                ),
                ExpectedFile(
                    path="tests/test_cache.py",
                    action="create",
                    status="expected",
                    reason="Explicit creation intent in plan",
                ),
            ],
            expected_symbols=[
                ExpectedSymbol(
                    name="UserService.getProfile",
                    kind="method",
                    file_path="src/services/UserService.ts",
                    line=42,
                    status="existing",
                    reason="Target symbol",
                ),
                ExpectedSymbol(
                    name="MissingService.missingMethod()",
                    kind="method",
                    status="unresolved",
                    reason="Class 'MissingService' not found in codebase graph",
                ),
            ],
            expected_tests=[
                ExpectedTest(
                    path="tests/test_cache.py",
                    reason="Explicit creation intent in plan",
                )
            ],
            expected_relationships=[],
        ),
        constraints=["Do not add network calls in unit tests."],
    )


def test_verify_perfect_implementation(tmp_path: Path, monkeypatch) -> None:
    """Verify PASS status when all expected files, tests, and symbols are satisfied."""
    baseline = _make_sample_baseline(repo_name=tmp_path.name)
    repo_info = GitRepoInfo(
        root=tmp_path,
        branch="main",
        head_sha="abcdef1234567890",
        is_dirty=True,
    )

    # Mock filesystem
    user_service = tmp_path / "src" / "services" / "UserService.ts"
    user_service.parent.mkdir(parents=True)
    user_service.write_text(
        "class UserService { getProfile() { return cache; } }\n", encoding="utf-8"
    )

    test_cache = tmp_path / "tests" / "test_cache.py"
    test_cache.parent.mkdir(parents=True)
    test_cache.write_text("def test_cache(): pass\n", encoding="utf-8")

    # Mock git changes matching expected files
    mock_changeset = GitChangeSet(
        base_commit="abcdef1234567890",
        modified={"src/services/UserService.ts"},
        added={"tests/test_cache.py"},
    )
    monkeypatch.setattr(
        "codealign.verify.verifier.get_git_changes",
        lambda repo_root, base_commit: mock_changeset,
    )

    result = verify_implementation(baseline, tmp_path, repo_info=repo_info)
    # Only warnings should be unresolved reference and constraint
    assert len(result.failures) == 0
    assert result.status == VerificationStatus.WARN  # warnings present due to unresolved reference

    passed_files = [p.file_path for p in result.passes if p.file_path]
    passed_symbols = [p.symbol for p in result.passes if p.symbol]
    assert "src/services/UserService.ts" in passed_files
    assert "tests/test_cache.py" in passed_files
    assert "UserService.getProfile" in passed_symbols


def test_verify_missing_expected_modification(tmp_path: Path, monkeypatch) -> None:
    """Verify FAIL when an expected modified file is unchanged."""
    baseline = _make_sample_baseline(repo_name=tmp_path.name)
    repo_info = GitRepoInfo(
        root=tmp_path,
        branch="main",
        head_sha="abcdef1234567890",
        is_dirty=False,
    )

    user_service = tmp_path / "src" / "services" / "UserService.ts"
    user_service.parent.mkdir(parents=True)
    user_service.write_text("class UserService { getProfile() {} }\n", encoding="utf-8")

    test_cache = tmp_path / "tests" / "test_cache.py"
    test_cache.parent.mkdir(parents=True)
    test_cache.write_text("def test_cache(): pass\n", encoding="utf-8")

    # UserService.ts was NOT modified!
    mock_changeset = GitChangeSet(
        base_commit="abcdef1234567890",
        modified=set(),
        added={"tests/test_cache.py"},
    )
    monkeypatch.setattr(
        "codealign.verify.verifier.get_git_changes",
        lambda repo_root, base_commit: mock_changeset,
    )

    result = verify_implementation(baseline, tmp_path, repo_info=repo_info)
    assert result.status == VerificationStatus.FAIL
    fail_files = [f.file_path for f in result.failures]
    assert "src/services/UserService.ts" in fail_files


def test_verify_missing_expected_created_file(tmp_path: Path, monkeypatch) -> None:
    """Verify FAIL when an expected created file was not created."""
    baseline = _make_sample_baseline(repo_name=tmp_path.name)
    repo_info = GitRepoInfo(
        root=tmp_path,
        branch="main",
        head_sha="abcdef1234567890",
        is_dirty=True,
    )

    user_service = tmp_path / "src" / "services" / "UserService.ts"
    user_service.parent.mkdir(parents=True)
    user_service.write_text("class UserService { getProfile() {} }\n", encoding="utf-8")

    # tests/test_cache.py was NOT created!
    mock_changeset = GitChangeSet(
        base_commit="abcdef1234567890",
        modified={"src/services/UserService.ts"},
        added=set(),
    )
    monkeypatch.setattr(
        "codealign.verify.verifier.get_git_changes",
        lambda repo_root, base_commit: mock_changeset,
    )

    result = verify_implementation(baseline, tmp_path, repo_info=repo_info)
    assert result.status == VerificationStatus.FAIL
    fail_files = [f.file_path for f in result.failures]
    assert "tests/test_cache.py" in fail_files


def test_verify_unexpected_scope_drift(tmp_path: Path, monkeypatch) -> None:
    """Verify WARN when an unexpected file is modified."""
    baseline = _make_sample_baseline(repo_name=tmp_path.name)
    repo_info = GitRepoInfo(
        root=tmp_path,
        branch="main",
        head_sha="abcdef1234567890",
        is_dirty=True,
    )

    user_service = tmp_path / "src" / "services" / "UserService.ts"
    user_service.parent.mkdir(parents=True)
    user_service.write_text("class UserService { getProfile() {} }\n", encoding="utf-8")

    test_cache = tmp_path / "tests" / "test_cache.py"
    test_cache.parent.mkdir(parents=True)
    test_cache.write_text("def test_cache(): pass\n", encoding="utf-8")

    # Unexpected file modified: src/random.py
    mock_changeset = GitChangeSet(
        base_commit="abcdef1234567890",
        modified={"src/services/UserService.ts", "src/random.py"},
        added={"tests/test_cache.py"},
    )
    monkeypatch.setattr(
        "codealign.verify.verifier.get_git_changes",
        lambda repo_root, base_commit: mock_changeset,
    )

    result = verify_implementation(baseline, tmp_path, repo_info=repo_info)
    drift_findings = [f for f in result.warnings if f.category == FindingCategory.SCOPE_DRIFT]
    assert len(drift_findings) == 1
    assert drift_findings[0].file_path == "src/random.py"


def test_verify_repository_mismatch(tmp_path: Path, monkeypatch) -> None:
    """Verify FAIL when baseline was generated for a different repository name."""
    baseline = _make_sample_baseline(repo_name="DifferentRepo")
    repo_info = GitRepoInfo(
        root=tmp_path,
        branch="main",
        head_sha="abcdef1234567890",
        is_dirty=False,
    )

    mock_changeset = GitChangeSet(base_commit="abcdef1234567890")
    monkeypatch.setattr(
        "codealign.verify.verifier.get_git_changes",
        lambda repo_root, base_commit: mock_changeset,
    )

    result = verify_implementation(baseline, tmp_path, repo_info=repo_info)
    assert result.status == VerificationStatus.FAIL
    repo_findings = [f for f in result.failures if f.category == FindingCategory.REPOSITORY_BINDING]
    assert len(repo_findings) == 1
    assert "DifferentRepo" in repo_findings[0].message


def test_verify_unresolved_references_preserved_as_warnings(tmp_path: Path, monkeypatch) -> None:
    """Verify unresolved references remain WARN without becoming false failures."""
    baseline = _make_sample_baseline(repo_name=tmp_path.name)
    repo_info = GitRepoInfo(
        root=tmp_path,
        branch="main",
        head_sha="abcdef1234567890",
        is_dirty=False,
    )

    user_service = tmp_path / "src" / "services" / "UserService.ts"
    user_service.parent.mkdir(parents=True)
    user_service.write_text("class UserService { getProfile() {} }\n", encoding="utf-8")

    test_cache = tmp_path / "tests" / "test_cache.py"
    test_cache.parent.mkdir(parents=True)
    test_cache.write_text("def test_cache(): pass\n", encoding="utf-8")

    mock_changeset = GitChangeSet(
        base_commit="abcdef1234567890",
        modified={"src/services/UserService.ts"},
        added={"tests/test_cache.py"},
    )
    monkeypatch.setattr(
        "codealign.verify.verifier.get_git_changes",
        lambda repo_root, base_commit: mock_changeset,
    )

    result = verify_implementation(baseline, tmp_path, repo_info=repo_info)
    unresolved_findings = [
        f for f in result.warnings if f.category == FindingCategory.UNRESOLVED_REFERENCE
    ]
    assert len(unresolved_findings) == 2
    unresolved_messages = " ".join(f.message for f in unresolved_findings)
    assert "docs/missing_notes.md" in unresolved_messages
    assert "MissingService.missingMethod()" in unresolved_messages


def test_verify_cli_terminal_and_json(tmp_path: Path, monkeypatch) -> None:
    """Verify codealign verify CLI runs in terminal and JSON formats with proper exit codes."""
    codealign_dir = tmp_path / ".codealign"
    codealign_dir.mkdir(parents=True)
    baseline_path = codealign_dir / "baseline.json"
    baseline = _make_sample_baseline(repo_name=tmp_path.name)
    baseline_path.write_text(baseline.to_json(), encoding="utf-8")

    user_service = tmp_path / "src" / "services" / "UserService.ts"
    user_service.parent.mkdir(parents=True)
    user_service.write_text("class UserService { getProfile() {} }\n", encoding="utf-8")

    test_cache = tmp_path / "tests" / "test_cache.py"
    test_cache.parent.mkdir(parents=True)
    test_cache.write_text("def test_cache(): pass\n", encoding="utf-8")

    repo_info = GitRepoInfo(
        root=tmp_path,
        branch="main",
        head_sha="abcdef1234567890",
        is_dirty=True,
    )
    monkeypatch.setattr("codealign.commands.verify.get_git_repo_info", lambda: repo_info)

    mock_changeset = GitChangeSet(
        base_commit="abcdef1234567890",
        modified={"src/services/UserService.ts"},
        added={"tests/test_cache.py"},
    )
    monkeypatch.setattr(
        "codealign.verify.verifier.get_git_changes",
        lambda repo_root, base_commit: mock_changeset,
    )

    # 1. Terminal format (non-strict passes with code 0)
    result_term = runner.invoke(app, ["verify"])
    assert result_term.exit_code == 0
    assert "CODEALIGN VERIFICATION" in result_term.stdout
    assert "PASS:" in result_term.stdout
    assert "Summary:" in result_term.stdout

    # 2. JSON format
    result_json = runner.invoke(app, ["verify", "--format", "json"])
    assert result_json.exit_code == 0
    assert '"status": "warn"' in result_json.stdout
    assert '"findings": [' in result_json.stdout

    # 3. Strict mode treats warnings as failures (exit code 1)
    result_strict = runner.invoke(app, ["verify", "--strict"])
    assert result_strict.exit_code == 1
    assert "FAIL" in result_strict.stdout


def test_verify_cli_missing_baseline_fails(tmp_path: Path, monkeypatch) -> None:
    """Verify codealign verify fails cleanly with exit code 1 if baseline is missing."""
    codealign_dir = tmp_path / ".codealign"
    codealign_dir.mkdir(parents=True)

    repo_info = GitRepoInfo(
        root=tmp_path,
        branch="main",
        head_sha="abcdef1234567890",
        is_dirty=False,
    )
    monkeypatch.setattr("codealign.commands.verify.get_git_repo_info", lambda: repo_info)

    result = runner.invoke(app, ["verify"])
    assert result.exit_code == 1
    assert "Error: Baseline contract not found" in result.output
    assert "codealign baseline" in result.output


def test_verify_no_mutation(tmp_path: Path, monkeypatch) -> None:
    """Verify running verification does not mutate baseline or repository files."""
    codealign_dir = tmp_path / ".codealign"
    codealign_dir.mkdir(parents=True)
    baseline_path = codealign_dir / "baseline.json"
    baseline = _make_sample_baseline(repo_name=tmp_path.name)
    baseline_path.write_text(baseline.to_json(), encoding="utf-8")
    initial_hash = hashlib.sha256(baseline_path.read_bytes()).hexdigest()

    user_service = tmp_path / "src" / "services" / "UserService.ts"
    user_service.parent.mkdir(parents=True)
    user_service.write_text("class UserService { getProfile() {} }\n", encoding="utf-8")
    initial_code_hash = hashlib.sha256(user_service.read_bytes()).hexdigest()

    repo_info = GitRepoInfo(
        root=tmp_path,
        branch="main",
        head_sha="abcdef1234567890",
        is_dirty=False,
    )
    monkeypatch.setattr("codealign.commands.verify.get_git_repo_info", lambda: repo_info)
    mock_changeset = GitChangeSet(base_commit="abcdef1234567890")
    monkeypatch.setattr(
        "codealign.verify.verifier.get_git_changes",
        lambda repo_root, base_commit: mock_changeset,
    )

    runner.invoke(app, ["verify"])

    final_hash = hashlib.sha256(baseline_path.read_bytes()).hexdigest()
    assert initial_hash == final_hash

    final_code_hash = hashlib.sha256(user_service.read_bytes()).hexdigest()
    assert initial_code_hash == final_code_hash
