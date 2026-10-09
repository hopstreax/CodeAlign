"""Unit and functional tests for codealign verify command and verification engine."""

import hashlib
from pathlib import Path

import pytest
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
from codealign.models.finding import FindingCategory, FindingSeverity
from codealign.models.result import VerificationStatus
from codealign.verify.git_diff import (
    GitChangeSet,
    WorkingTreeSnapshot,
    capture_working_tree_snapshot,
    compute_session_changes,
    extract_file_symbols,
    extract_file_symbols_and_fingerprints,
)
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


def test_verify_codealign_artifacts_excluded_from_scope_drift(
    tmp_path: Path, monkeypatch
) -> None:
    """Verify .codealign/** artifacts are excluded from scope drift warnings."""
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

    # Mock changeset containing expected changes plus .codealign/** workflow artifacts
    mock_changeset = GitChangeSet(
        base_commit="abcdef1234567890",
        modified={
            "src/services/UserService.ts",
            ".codealign/baseline.json",
            ".codealign/config.toml",
            ".codealign/context.md",
        },
        added={
            "tests/test_cache.py",
            ".codealign/graphify-out/graph.json",
            ".codealign/graphify-out/manifest.json",
            ".codealign/graphify-out/cache/ast/sample.json",
        },
    )
    monkeypatch.setattr(
        "codealign.verify.verifier.get_git_changes",
        lambda repo_root, base_commit: mock_changeset,
    )

    result = verify_implementation(baseline, tmp_path, repo_info=repo_info)
    drift_findings = [f for f in result.warnings if f.category == FindingCategory.SCOPE_DRIFT]
    assert len(drift_findings) == 0


def test_verify_plan_artifact_excluded_from_scope_drift(
    tmp_path: Path, monkeypatch
) -> None:
    """Verify plan input file is treated as workflow artifact and excluded from scope drift."""
    baseline = _make_sample_baseline(repo_name=tmp_path.name)
    baseline.intent.plan_file = "custom-plan.md"
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

    # Plan file was modified in working tree
    mock_changeset = GitChangeSet(
        base_commit="abcdef1234567890",
        modified={"src/services/UserService.ts", "custom-plan.md"},
        added={"tests/test_cache.py"},
    )
    monkeypatch.setattr(
        "codealign.verify.verifier.get_git_changes",
        lambda repo_root, base_commit: mock_changeset,
    )

    result = verify_implementation(baseline, tmp_path, repo_info=repo_info)
    drift_findings = [f for f in result.warnings if f.category == FindingCategory.SCOPE_DRIFT]
    assert len(drift_findings) == 0


def test_verify_plan_artifact_absolute_path_excluded(
    tmp_path: Path, monkeypatch
) -> None:
    """Verify plan file specified as absolute path is excluded from scope drift."""
    plan_file = tmp_path / "docs" / "plan.md"
    baseline = _make_sample_baseline(repo_name=tmp_path.name)
    baseline.intent.plan_file = str(plan_file)
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

    mock_changeset = GitChangeSet(
        base_commit="abcdef1234567890",
        modified={"src/services/UserService.ts", "docs/plan.md"},
        added={"tests/test_cache.py"},
    )
    monkeypatch.setattr(
        "codealign.verify.verifier.get_git_changes",
        lambda repo_root, base_commit: mock_changeset,
    )

    result = verify_implementation(baseline, tmp_path, repo_info=repo_info)
    drift_findings = [f for f in result.warnings if f.category == FindingCategory.SCOPE_DRIFT]
    assert len(drift_findings) == 0


def test_verify_python_runtime_artifacts_ignored(
    tmp_path: Path, monkeypatch
) -> None:
    """Verify Python runtime artifacts like __pycache__ and *.pyc/*.pyo are ignored."""
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

    # Working tree has pycache files and pyc/pyo files
    mock_changeset = GitChangeSet(
        base_commit="abcdef1234567890",
        modified={"src/services/UserService.ts"},
        added={
            "tests/test_cache.py",
            "__pycache__/runner.cpython-314.pyc",
            "src/__pycache__/service.pyc",
            "orphan.pyc",
            "orphan.pyo",
        },
    )
    monkeypatch.setattr(
        "codealign.verify.verifier.get_git_changes",
        lambda repo_root, base_commit: mock_changeset,
    )

    result = verify_implementation(baseline, tmp_path, repo_info=repo_info)
    drift_findings = [f for f in result.warnings if f.category == FindingCategory.SCOPE_DRIFT]
    assert len(drift_findings) == 0


def test_verify_unresolved_symbol_created_in_expected_file_reports_pass(
    tmp_path: Path, monkeypatch
) -> None:
    """Verify when an unresolved symbol now exists in expected file, PASS is reported."""
    baseline = ImplementationBaseline(
        schema_version="0.1.0",
        repository=BaselineRepositoryInfo(
            name=tmp_path.name, branch="main", commit="abcdef1234567890"
        ),
        intent=BaselineIntent(
            plan_file="calc-plan.md",
            title="Add subtract function",
            goal="Add subtract function to calculator.",
            steps=["Add subtract() to src/calculator.py."],
        ),
        evidence=BaselineEvidence(
            summary={"total_references": 1, "resolved_count": 0, "unresolved_count": 1},
            unresolved=[
                BaselineEvidenceItem(
                    reference="subtract()",
                    status="unresolved",
                    kind="function",
                    reason="Symbol 'subtract()' unconfirmed in codebase graph",
                )
            ],
        ),
        expectations=BaselineExpectations(
            expected_files=[
                ExpectedFile(path="src/calculator.py", action="modify", status="resolved"),
            ],
            expected_symbols=[
                ExpectedSymbol(
                    name="subtract()",
                    kind="function",
                    file_path="",
                    status="unresolved",
                    reason="Symbol was unconfirmed at baseline time",
                )
            ],
        ),
    )
    repo_info = GitRepoInfo(
        root=tmp_path, branch="main", head_sha="abcdef1234567890", is_dirty=True
    )

    calc_file = tmp_path / "src" / "calculator.py"
    calc_file.parent.mkdir(parents=True)
    calc_file.write_text(
        "def subtract(a: int, b: int) -> int:\n    return a - b\n", encoding="utf-8"
    )

    mock_changeset = GitChangeSet(
        base_commit="abcdef1234567890",
        modified={"src/calculator.py"},
    )
    monkeypatch.setattr(
        "codealign.verify.verifier.get_git_changes",
        lambda repo_root, base_commit: mock_changeset,
    )

    result = verify_implementation(baseline, tmp_path, repo_info=repo_info)

    # Must NOT have UNRESOLVED_REFERENCE warning
    unresolved_warnings = [
        f for f in result.warnings if f.category == FindingCategory.UNRESOLVED_REFERENCE
    ]
    assert len(unresolved_warnings) == 0

    # Must have PASS for created symbol matching the required format
    symbol_passes = [f for f in result.passes if f.symbol == "subtract"]
    assert len(symbol_passes) == 1
    sp = symbol_passes[0]
    assert sp.severity == FindingSeverity.PASS
    assert sp.message == "Expected symbol 'subtract' created in 'src/calculator.py'."
    assert sp.file_path == "src/calculator.py"
    assert sp.expected == "created"


def test_verify_unresolved_symbol_with_escaped_name_reports_pass(
    tmp_path: Path, monkeypatch
) -> None:
    """Verify symbol with markdown-escaped name reports clean PASS when created."""
    baseline = ImplementationBaseline(
        schema_version="0.1.0",
        repository=BaselineRepositoryInfo(
            name=tmp_path.name, branch="main", commit="abcdef1234567890"
        ),
        intent=BaselineIntent(
            plan_file="plan.md",
            title="Add helper",
            goal="Add helper func.",
            steps=[r"Add `my\_helper()` to `src/helpers.py`."],
        ),
        expectations=BaselineExpectations(
            expected_files=[
                ExpectedFile(path="src/helpers.py", action="create", status="expected"),
            ],
            expected_symbols=[
                ExpectedSymbol(
                    name=r"my\_helper()",
                    kind="function",
                    file_path="",
                    status="unresolved",
                )
            ],
        ),
    )
    repo_info = GitRepoInfo(
        root=tmp_path, branch="main", head_sha="abcdef1234567890", is_dirty=True
    )

    helper_file = tmp_path / "src" / "helpers.py"
    helper_file.parent.mkdir(parents=True)
    helper_file.write_text("def my_helper():\n    return True\n", encoding="utf-8")

    mock_changeset = GitChangeSet(
        base_commit="abcdef1234567890",
        added={"src/helpers.py"},
    )
    monkeypatch.setattr(
        "codealign.verify.verifier.get_git_changes",
        lambda repo_root, base_commit: mock_changeset,
    )

    result = verify_implementation(baseline, tmp_path, repo_info=repo_info)
    assert result.status == VerificationStatus.PASS
    passes = [f for f in result.passes if f.symbol == "my_helper"]
    assert len(passes) == 1
    assert passes[0].message == "Expected symbol 'my_helper' created in 'src/helpers.py'."


def test_verify_class_method_symbol_created_reports_pass(
    tmp_path: Path, monkeypatch
) -> None:
    """Verify class-qualified symbol reports PASS when class and method exist."""
    baseline = ImplementationBaseline(
        schema_version="0.1.0",
        repository=BaselineRepositoryInfo(
            name=tmp_path.name, branch="main", commit="abcdef1234567890"
        ),
        intent=BaselineIntent(
            plan_file="plan.md",
            title="Add multiply",
            goal="Add multiply method.",
            steps=["Add Calculator.multiply() to src/calculator.py."],
        ),
        expectations=BaselineExpectations(
            expected_files=[
                ExpectedFile(path="src/calculator.py", action="modify", status="resolved"),
            ],
            expected_symbols=[
                ExpectedSymbol(
                    name="Calculator.multiply()",
                    kind="method",
                    file_path="",
                    status="unresolved",
                )
            ],
        ),
    )
    repo_info = GitRepoInfo(
        root=tmp_path, branch="main", head_sha="abcdef1234567890", is_dirty=True
    )

    calc_file = tmp_path / "src" / "calculator.py"
    calc_file.parent.mkdir(parents=True)
    calc_file.write_text(
        "class Calculator:\n    def multiply(self, a, b):\n        return a * b\n",
        encoding="utf-8",
    )

    mock_changeset = GitChangeSet(
        base_commit="abcdef1234567890",
        modified={"src/calculator.py"},
    )
    monkeypatch.setattr(
        "codealign.verify.verifier.get_git_changes",
        lambda repo_root, base_commit: mock_changeset,
    )

    result = verify_implementation(baseline, tmp_path, repo_info=repo_info)
    symbol_passes = [f for f in result.passes if f.symbol == "Calculator.multiply"]
    assert len(symbol_passes) == 1
    expected_msg = "Expected symbol 'Calculator.multiply' created in 'src/calculator.py'."
    assert symbol_passes[0].message == expected_msg


def test_verify_genuinely_unresolved_and_unexpected_changes_preserved(
    tmp_path: Path, monkeypatch
) -> None:
    """Verify genuinely unresolved symbols and unexpected changes still trigger warnings."""
    baseline = ImplementationBaseline(
        schema_version="0.1.0",
        repository=BaselineRepositoryInfo(
            name=tmp_path.name, branch="main", commit="abcdef1234567890"
        ),
        intent=BaselineIntent(
            plan_file="plan.md",
            title="Partial work",
            goal="Test partial work.",
            steps=["Do something."],
        ),
        expectations=BaselineExpectations(
            expected_files=[
                ExpectedFile(path="src/service.py", action="modify", status="resolved"),
            ],
            expected_symbols=[
                ExpectedSymbol(
                    name="still_missing_func()",
                    kind="function",
                    file_path="",
                    status="unresolved",
                    reason="Function not found",
                )
            ],
        ),
    )
    repo_info = GitRepoInfo(
        root=tmp_path, branch="main", head_sha="abcdef1234567890", is_dirty=True
    )

    service_file = tmp_path / "src" / "service.py"
    service_file.parent.mkdir(parents=True)
    service_file.write_text("# service implementation without the func\n", encoding="utf-8")

    # Working tree has expected file, genuinely unexpected source file, and package source change
    mock_changeset = GitChangeSet(
        base_commit="abcdef1234567890",
        modified={"src/service.py", "src/unexpected_module.py", "codealign/internal.py"},
    )
    monkeypatch.setattr(
        "codealign.verify.verifier.get_git_changes",
        lambda repo_root, base_commit: mock_changeset,
    )

    result = verify_implementation(baseline, tmp_path, repo_info=repo_info)

    # 1. Genuinely unresolved symbol must trigger UNRESOLVED_REFERENCE warning
    unresolved_warnings = [
        f for f in result.warnings if f.category == FindingCategory.UNRESOLVED_REFERENCE
    ]
    assert len(unresolved_warnings) == 1
    expected_sym_msg = (
        "Baseline contains unresolved symbol reference: 'still_missing_func()'."
    )
    assert unresolved_warnings[0].message == expected_sym_msg

    # 2. Genuinely unexpected files must trigger SCOPE_DRIFT warnings
    drift_warnings = [
        f for f in result.warnings if f.category == FindingCategory.SCOPE_DRIFT
    ]
    drift_files = {f.file_path for f in drift_warnings}
    assert "src/unexpected_module.py" in drift_files
    assert "codealign/internal.py" in drift_files


def test_verify_existing_symbol_continues_to_pass(
    tmp_path: Path, monkeypatch
) -> None:
    """Verify existing symbol in baseline continues to report PASS when confirmed in file."""
    baseline = ImplementationBaseline(
        schema_version="0.1.0",
        repository=BaselineRepositoryInfo(
            name=tmp_path.name, branch="main", commit="abcdef1234567890"
        ),
        intent=BaselineIntent(
            plan_file="plan.md",
            title="Update calculator",
            goal="Ensure existing add is preserved.",
            steps=["Check add()."],
        ),
        expectations=BaselineExpectations(
            expected_files=[
                ExpectedFile(path="src/calculator.py", action="modify", status="resolved"),
            ],
            expected_symbols=[
                ExpectedSymbol(
                    name="add",
                    kind="function",
                    file_path="src/calculator.py",
                    status="existing",
                )
            ],
        ),
    )
    repo_info = GitRepoInfo(
        root=tmp_path, branch="main", head_sha="abcdef1234567890", is_dirty=True
    )

    calc_file = tmp_path / "src" / "calculator.py"
    calc_file.parent.mkdir(parents=True)
    calc_file.write_text("def add(a: int, b: int) -> int:\n    return a + b\n", encoding="utf-8")

    mock_changeset = GitChangeSet(
        base_commit="abcdef1234567890",
        modified={"src/calculator.py"},
    )
    monkeypatch.setattr(
        "codealign.verify.verifier.get_git_changes",
        lambda repo_root, base_commit: mock_changeset,
    )

    result = verify_implementation(baseline, tmp_path, repo_info=repo_info)
    add_passes = [f for f in result.passes if f.symbol == "add"]
    assert len(add_passes) == 1
    assert add_passes[0].message == "Expected symbol 'add' confirmed in 'src/calculator.py'."


def test_session_clean_repo_modifies_file() -> None:
    """A. Clean repo: agent modifies file -> session contains it."""
    pre = WorkingTreeSnapshot(changeset=GitChangeSet(base_commit="c1"))
    post = WorkingTreeSnapshot(
        changeset=GitChangeSet(base_commit="c1", modified={"src/calc.py"}),
        dirty_hashes={"src/calc.py": "hash_new"},
    )
    session = compute_session_changes(pre, post, Path("/repo"))
    assert session.modified == {"src/calc.py"}
    assert session.added == set()
    assert session.deleted == set()


def test_session_clean_repo_creates_file() -> None:
    """B. Clean repo: agent creates file -> session contains it."""
    pre = WorkingTreeSnapshot(changeset=GitChangeSet(base_commit="c1"))
    post = WorkingTreeSnapshot(
        changeset=GitChangeSet(base_commit="c1", added={"src/new.py"}),
        dirty_hashes={"src/new.py": "hash_new"},
    )
    session = compute_session_changes(pre, post, Path("/repo"))
    assert session.added == {"src/new.py"}
    assert session.modified == set()


def test_session_clean_repo_deletes_file() -> None:
    """C. Clean repo: agent deletes file -> session contains it."""
    pre = WorkingTreeSnapshot(changeset=GitChangeSet(base_commit="c1"))
    post = WorkingTreeSnapshot(
        changeset=GitChangeSet(base_commit="c1", deleted={"src/old.py"}),
    )
    session = compute_session_changes(pre, post, Path("/repo"))
    assert session.deleted == {"src/old.py"}


def test_session_clean_repo_renames_file() -> None:
    """Clean repo: agent renames file -> session contains rename and modified."""
    pre = WorkingTreeSnapshot(changeset=GitChangeSet(base_commit="c1"))
    post = WorkingTreeSnapshot(
        changeset=GitChangeSet(
            base_commit="c1",
            modified={"src/new_name.py"},
            renamed={"src/new_name.py": "src/old_name.py"},
        ),
    )
    session = compute_session_changes(pre, post, Path("/repo"))
    assert session.renamed == {"src/new_name.py": "src/old_name.py"}
    assert "src/new_name.py" in session.modified


def test_session_preexisting_modified_file_untouched() -> None:
    """D. Pre-existing modified file untouched -> excluded from session."""
    pre = WorkingTreeSnapshot(
        changeset=GitChangeSet(base_commit="c1", modified={"src/dirty.py"}),
        dirty_hashes={"src/dirty.py": "hash_dirty"},
    )
    post = WorkingTreeSnapshot(
        changeset=GitChangeSet(
            base_commit="c1",
            modified={"src/dirty.py", "src/agent.py"},
        ),
        dirty_hashes={"src/dirty.py": "hash_dirty", "src/agent.py": "hash_agent"},
    )
    session = compute_session_changes(pre, post, Path("/repo"))
    assert session.modified == {"src/agent.py"}
    assert "src/dirty.py" not in session.all_changed_files


def test_session_preexisting_untracked_file_untouched() -> None:
    """E. Pre-existing untracked file untouched -> excluded from session."""
    pre = WorkingTreeSnapshot(
        changeset=GitChangeSet(base_commit="c1", added={"temp.txt"}),
        dirty_hashes={"temp.txt": "hash_temp"},
    )
    post = WorkingTreeSnapshot(
        changeset=GitChangeSet(
            base_commit="c1",
            added={"temp.txt", "src/new.py"},
        ),
        dirty_hashes={"temp.txt": "hash_temp", "src/new.py": "hash_new"},
    )
    session = compute_session_changes(pre, post, Path("/repo"))
    assert session.added == {"src/new.py"}
    assert "temp.txt" not in session.all_changed_files


def test_session_preexisting_modified_file_changed() -> None:
    """F. Pre-existing modified file changed by agent -> included in session."""
    pre = WorkingTreeSnapshot(
        changeset=GitChangeSet(base_commit="c1", modified={"src/calc.py"}),
        dirty_hashes={"src/calc.py": "hash_v1"},
    )
    post = WorkingTreeSnapshot(
        changeset=GitChangeSet(base_commit="c1", modified={"src/calc.py"}),
        dirty_hashes={"src/calc.py": "hash_v2"},
    )
    session = compute_session_changes(pre, post, Path("/repo"))
    assert session.modified == {"src/calc.py"}


def test_session_preexisting_untracked_file_changed() -> None:
    """G. Pre-existing untracked file changed by agent -> included in session."""
    pre = WorkingTreeSnapshot(
        changeset=GitChangeSet(base_commit="c1", added={"scratch.py"}),
        dirty_hashes={"scratch.py": "hash_v1"},
    )
    post = WorkingTreeSnapshot(
        changeset=GitChangeSet(base_commit="c1", added={"scratch.py"}),
        dirty_hashes={"scratch.py": "hash_v2"},
    )
    session = compute_session_changes(pre, post, Path("/repo"))
    assert session.modified == {"scratch.py"}
    assert session.added == set()


def test_session_preexisting_dirty_file_restored() -> None:
    """H. Pre-existing dirty file restored to HEAD -> handled without crash."""
    pre = WorkingTreeSnapshot(
        changeset=GitChangeSet(base_commit="c1", modified={"src/reverted.py"}),
        dirty_hashes={"src/reverted.py": "hash_dirty"},
    )
    post = WorkingTreeSnapshot(
        changeset=GitChangeSet(base_commit="c1"),
        dirty_hashes={},
    )
    session = compute_session_changes(pre, post, Path("/repo"))
    assert session.modified == {"src/reverted.py"}


def test_session_agent_makes_no_changes() -> None:
    """I. Agent makes no changes -> empty session."""
    pre = WorkingTreeSnapshot(
        changeset=GitChangeSet(base_commit="c1", modified={"src/dirty.py"}),
        dirty_hashes={"src/dirty.py": "hash_dirty"},
    )
    post = WorkingTreeSnapshot(
        changeset=GitChangeSet(base_commit="c1", modified={"src/dirty.py"}),
        dirty_hashes={"src/dirty.py": "hash_dirty"},
    )
    session = compute_session_changes(pre, post, Path("/repo"))
    assert session.all_changed_files == set()


def test_verify_standalone_calculates_own_changeset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """J. Standalone verify_implementation calculates its own changeset when changeset=None."""
    baseline = _make_sample_baseline(commit="c1", repo_name="calc_repo")
    repo_info = GitRepoInfo(root=tmp_path, branch="main", head_sha="c1", is_dirty=False)

    called = False

    def fake_get_git_changes(repo_root, base_commit):
        nonlocal called
        called = True
        return GitChangeSet(base_commit="c1")

    monkeypatch.setattr("codealign.verify.verifier.get_git_changes", fake_get_git_changes)
    result = verify_implementation(baseline, tmp_path, repo_info=repo_info, changeset=None)
    assert called is True
    assert result.status is not None


def test_verify_with_supplied_changeset_skips_get_git_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """verify_implementation uses supplied changeset and skips get_git_changes."""
    baseline = _make_sample_baseline(commit="c1", repo_name="calc_repo")
    repo_info = GitRepoInfo(root=tmp_path, branch="main", head_sha="c1", is_dirty=False)

    called = False

    def fake_get_git_changes(repo_root, base_commit):
        nonlocal called
        called = True
        return GitChangeSet(base_commit="c1")

    monkeypatch.setattr("codealign.verify.verifier.get_git_changes", fake_get_git_changes)
    custom_cs = GitChangeSet(base_commit="c1", modified={"src/services/UserService.ts"})
    result = verify_implementation(baseline, tmp_path, repo_info=repo_info, changeset=custom_cs)
    assert called is False
    assert result.status is not None


def test_capture_working_tree_snapshot_hashes_dirty_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """capture_working_tree_snapshot hashes dirty files reported by get_git_changes."""
    f = tmp_path / "foo.py"
    f.write_text("print('hello')", encoding="utf-8")

    def fake_get_git_changes(repo_root, base_commit):
        return GitChangeSet(base_commit="c1", modified={"foo.py"})

    monkeypatch.setattr("codealign.verify.git_diff.get_git_changes", fake_get_git_changes)
    snapshot = capture_working_tree_snapshot(tmp_path, "c1")
    expected_hash = hashlib.sha256("print('hello')".encode("utf-8")).hexdigest()
    assert snapshot.dirty_hashes.get("foo.py") == expected_hash


def test_extract_file_symbols_python(tmp_path: Path) -> None:
    """extract_file_symbols extracts top-level and class functions/classes."""
    code = """
import os
MY_CONST = 100

def top_func(x):
    def inner_closure():
        return x
    return inner_closure()

async def async_top():
    pass

class Calculator:
    def add(self):
        pass

    async def async_compute(self):
        pass

    def _private_method(self):
        pass

class _PrivateClass:
    def run(self):
        pass
"""
    f = tmp_path / "calc.py"
    f.write_text(code, encoding="utf-8")
    symbols = extract_file_symbols(f)
    assert "top_func" in symbols
    assert "async_top" in symbols
    assert "Calculator" in symbols
    assert "Calculator.add" in symbols
    assert "Calculator.async_compute" in symbols
    assert "Calculator._private_method" in symbols
    assert "_PrivateClass" in symbols
    assert "_PrivateClass.run" in symbols
    # Inner closures and constants/imports must not be present
    assert "inner_closure" not in symbols
    assert "MY_CONST" not in symbols
    assert "os" not in symbols


def test_extract_file_symbols_generic(tmp_path: Path) -> None:
    """extract_file_symbols extracts functions and classes from non-Python files using regex."""
    code = """
export function runTask() {}
export class TaskManager {}
const value = 42;
"""
    f = tmp_path / "tasks.ts"
    f.write_text(code, encoding="utf-8")
    symbols = extract_file_symbols(f)
    assert "runTask" in symbols
    assert "TaskManager" in symbols
    assert "value" not in symbols


def _make_symbol_drift_baseline(tmp_path: Path) -> tuple[ImplementationBaseline, GitRepoInfo]:
    calc_path = tmp_path / "src" / "calculator.py"
    calc_path.parent.mkdir(parents=True, exist_ok=True)
    calc_path.write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")

    baseline = ImplementationBaseline(
        schema_version="0.1.0",
        repository=BaselineRepositoryInfo(name=tmp_path.name, commit="c1"),
        intent=BaselineIntent(title="Add multiply", goal="Multiply feature"),
        expectations=BaselineExpectations(
            expected_files=[
                ExpectedFile(path="src/calculator.py", action="modify", status="resolved")
            ],
            expected_symbols=[
                ExpectedSymbol(name="multiply", kind="function", status="unresolved")
            ],
        ),
    )
    repo_info = GitRepoInfo(root=tmp_path, branch="main", head_sha="c1", is_dirty=False)
    return baseline, repo_info


def test_symbol_drift_t1_expected_multiply_passes(tmp_path: Path) -> None:
    """T1: Clean file + expected multiply() introduced by agent -> PASS, 0 drift warnings."""
    baseline, repo_info = _make_symbol_drift_baseline(tmp_path)
    calc = tmp_path / "src" / "calculator.py"
    calc.write_text(
        "def add(a, b):\n    return a + b\ndef multiply(a, b):\n    return a * b\n",
        encoding="utf-8",
    )

    pre = WorkingTreeSnapshot(
        changeset=GitChangeSet(base_commit="c1"),
        file_symbols={"src/calculator.py": {"add"}},
    )
    post = WorkingTreeSnapshot(
        changeset=GitChangeSet(base_commit="c1", modified={"src/calculator.py"}),
        file_symbols={"src/calculator.py": {"add", "multiply"}},
    )
    cs = GitChangeSet(base_commit="c1", modified={"src/calculator.py"})

    result = verify_implementation(
        baseline=baseline,
        repo_root=tmp_path,
        repo_info=repo_info,
        changeset=cs,
        pre_snapshot=pre,
        post_snapshot=post,
    )
    assert result.status == VerificationStatus.PASS
    drift_findings = [f for f in result.findings if f.category == FindingCategory.ABSTRACTION_DRIFT]
    assert len(drift_findings) == 0


def test_symbol_drift_t2_expected_multiply_plus_unexpected_divide(tmp_path: Path) -> None:
    """T2: Expected multiply() + agent adds divide() -> PASS for multiply + WARN for divide."""
    baseline, repo_info = _make_symbol_drift_baseline(tmp_path)
    calc = tmp_path / "src" / "calculator.py"
    calc.write_text(
        "def add(a, b):\n    return a + b\n"
        "def multiply(a, b):\n    return a * b\n"
        "def divide(a, b):\n    return a / b\n",
        encoding="utf-8",
    )

    pre = WorkingTreeSnapshot(
        changeset=GitChangeSet(base_commit="c1"),
        file_symbols={"src/calculator.py": {"add"}},
    )
    post = WorkingTreeSnapshot(
        changeset=GitChangeSet(base_commit="c1", modified={"src/calculator.py"}),
        file_symbols={"src/calculator.py": {"add", "multiply", "divide"}},
    )
    cs = GitChangeSet(base_commit="c1", modified={"src/calculator.py"})

    result = verify_implementation(
        baseline=baseline,
        repo_root=tmp_path,
        repo_info=repo_info,
        changeset=cs,
        pre_snapshot=pre,
        post_snapshot=post,
    )
    assert result.status == VerificationStatus.WARN
    drift = [f for f in result.findings if f.category == FindingCategory.ABSTRACTION_DRIFT]
    assert len(drift) == 1
    assert drift[0].symbol == "divide"
    assert drift[0].severity == FindingSeverity.WARN
    assert "Unexpected symbol 'divide' introduced in 'src/calculator.py'" in drift[0].message
    assert "Symbol 'divide' was not present in pre-session file" in drift[0].evidence


def test_symbol_drift_t3_private_helper_ignored(tmp_path: Path) -> None:
    """T3: Expected multiply() + agent adds private _validate_args() -> no drift warning."""
    baseline, repo_info = _make_symbol_drift_baseline(tmp_path)
    calc = tmp_path / "src" / "calculator.py"
    calc.write_text(
        "def add(a, b):\n    return a + b\n"
        "def _validate_args(a, b):\n    pass\n"
        "def multiply(a, b):\n    _validate_args(a, b)\n    return a * b\n",
        encoding="utf-8",
    )

    pre = WorkingTreeSnapshot(
        changeset=GitChangeSet(base_commit="c1"),
        file_symbols={"src/calculator.py": {"add"}},
    )
    post = WorkingTreeSnapshot(
        changeset=GitChangeSet(base_commit="c1", modified={"src/calculator.py"}),
        file_symbols={"src/calculator.py": {"add", "multiply", "_validate_args"}},
    )
    cs = GitChangeSet(base_commit="c1", modified={"src/calculator.py"})

    result = verify_implementation(
        baseline=baseline,
        repo_root=tmp_path,
        repo_info=repo_info,
        changeset=cs,
        pre_snapshot=pre,
        post_snapshot=post,
    )
    assert result.status == VerificationStatus.PASS
    drift = [f for f in result.findings if f.category == FindingCategory.ABSTRACTION_DRIFT]
    assert len(drift) == 0


def test_symbol_drift_t4_unexpected_class_utils(tmp_path: Path) -> None:
    """T4: Expected multiply() + agent adds Utils class -> WARN for Utils."""
    baseline, repo_info = _make_symbol_drift_baseline(tmp_path)
    calc = tmp_path / "src" / "calculator.py"
    calc.write_text(
        "def add(a, b):\n    return a + b\n"
        "def multiply(a, b):\n    return a * b\n"
        "class Utils:\n    pass\n",
        encoding="utf-8",
    )

    pre = WorkingTreeSnapshot(
        changeset=GitChangeSet(base_commit="c1"),
        file_symbols={"src/calculator.py": {"add"}},
    )
    post = WorkingTreeSnapshot(
        changeset=GitChangeSet(base_commit="c1", modified={"src/calculator.py"}),
        file_symbols={"src/calculator.py": {"add", "multiply", "Utils"}},
    )
    cs = GitChangeSet(base_commit="c1", modified={"src/calculator.py"})

    result = verify_implementation(
        baseline=baseline,
        repo_root=tmp_path,
        repo_info=repo_info,
        changeset=cs,
        pre_snapshot=pre,
        post_snapshot=post,
    )
    assert result.status == VerificationStatus.WARN
    drift = [f for f in result.findings if f.category == FindingCategory.ABSTRACTION_DRIFT]
    assert len(drift) == 1
    assert drift[0].symbol == "Utils"


def test_symbol_drift_t5_preexisting_dirty_symbol_not_flagged(tmp_path: Path) -> None:
    """T5: Pre-session dirty file already contains draft() -> draft() produces NO drift warning."""
    baseline, repo_info = _make_symbol_drift_baseline(tmp_path)
    calc = tmp_path / "src" / "calculator.py"
    calc.write_text(
        "def add(a, b):\n    return a + b\n"
        "def draft(a):\n    pass\n"
        "def multiply(a, b):\n    return a * b\n",
        encoding="utf-8",
    )

    pre = WorkingTreeSnapshot(
        changeset=GitChangeSet(base_commit="c1", modified={"src/calculator.py"}),
        file_symbols={"src/calculator.py": {"add", "draft"}},
    )
    post = WorkingTreeSnapshot(
        changeset=GitChangeSet(base_commit="c1", modified={"src/calculator.py"}),
        file_symbols={"src/calculator.py": {"add", "draft", "multiply"}},
    )
    cs = GitChangeSet(base_commit="c1", modified={"src/calculator.py"})

    result = verify_implementation(
        baseline=baseline,
        repo_root=tmp_path,
        repo_info=repo_info,
        changeset=cs,
        pre_snapshot=pre,
        post_snapshot=post,
    )
    assert result.status == VerificationStatus.PASS
    drift = [f for f in result.findings if f.category == FindingCategory.ABSTRACTION_DRIFT]
    assert len(drift) == 0


def test_symbol_drift_t6_preexisting_dirty_symbol_removed(tmp_path: Path) -> None:
    """T6: Pre-session dirty symbol removed during session -> no false warning, no crash."""
    baseline, repo_info = _make_symbol_drift_baseline(tmp_path)
    calc = tmp_path / "src" / "calculator.py"
    calc.write_text(
        "def add(a, b):\n    return a + b\n"
        "def multiply(a, b):\n    return a * b\n",
        encoding="utf-8",
    )

    pre = WorkingTreeSnapshot(
        changeset=GitChangeSet(base_commit="c1", modified={"src/calculator.py"}),
        file_symbols={"src/calculator.py": {"add", "old_draft"}},
    )
    post = WorkingTreeSnapshot(
        changeset=GitChangeSet(base_commit="c1", modified={"src/calculator.py"}),
        file_symbols={"src/calculator.py": {"add", "multiply"}},
    )
    cs = GitChangeSet(base_commit="c1", modified={"src/calculator.py"})

    result = verify_implementation(
        baseline=baseline,
        repo_root=tmp_path,
        repo_info=repo_info,
        changeset=cs,
        pre_snapshot=pre,
        post_snapshot=post,
    )
    assert result.status == VerificationStatus.PASS
    drift = [f for f in result.findings if f.category == FindingCategory.ABSTRACTION_DRIFT]
    assert len(drift) == 0


def test_symbol_drift_t7_test_file_excluded(tmp_path: Path) -> None:
    """T7: Helper added to test file -> no symbol drift warning because test files excluded."""
    baseline, repo_info = _make_symbol_drift_baseline(tmp_path)
    test_f = tmp_path / "tests" / "test_calculator.py"
    test_f.parent.mkdir(parents=True, exist_ok=True)
    test_f.write_text(
        "def test_multiply():\n    pass\ndef test_helper():\n    pass\n",
        encoding="utf-8",
    )

    pre = WorkingTreeSnapshot(
        changeset=GitChangeSet(base_commit="c1"),
        file_symbols={"tests/test_calculator.py": {"test_existing"}},
    )
    post = WorkingTreeSnapshot(
        changeset=GitChangeSet(base_commit="c1", modified={"tests/test_calculator.py"}),
        file_symbols={
            "tests/test_calculator.py": {"test_existing", "test_multiply", "test_helper"}
        },
    )
    cs = GitChangeSet(base_commit="c1", modified={"tests/test_calculator.py"})

    result = verify_implementation(
        baseline=baseline,
        repo_root=tmp_path,
        repo_info=repo_info,
        changeset=cs,
        pre_snapshot=pre,
        post_snapshot=post,
    )
    drift = [f for f in result.findings if f.category == FindingCategory.ABSTRACTION_DRIFT]
    assert len(drift) == 0


def test_symbol_drift_t8_standalone_verify_without_snapshots(tmp_path: Path) -> None:
    """T8: Standalone verify with no session changeset -> existing behavior works without crash."""
    baseline, repo_info = _make_symbol_drift_baseline(tmp_path)
    calc = tmp_path / "src" / "calculator.py"
    calc.write_text(
        "def add(a, b):\n    return a + b\ndef multiply(a, b):\n    return a * b\n",
        encoding="utf-8",
    )

    result = verify_implementation(
        baseline=baseline,
        repo_root=tmp_path,
        repo_info=repo_info,
        changeset=None,
        pre_snapshot=None,
        post_snapshot=None,
    )
    assert result.status is not None
    drift = [f for f in result.findings if f.category == FindingCategory.ABSTRACTION_DRIFT]
    assert len(drift) == 0


def test_symbol_drift_async_and_class_methods(tmp_path: Path) -> None:
    """Symbol drift detects unexpected async functions and class methods."""
    baseline, repo_info = _make_symbol_drift_baseline(tmp_path)
    calc = tmp_path / "src" / "calculator.py"
    calc.write_text("class Calculator:\n    pass\n", encoding="utf-8")

    pre = WorkingTreeSnapshot(
        changeset=GitChangeSet(base_commit="c1"),
        file_symbols={"src/calculator.py": set()},
    )
    post = WorkingTreeSnapshot(
        changeset=GitChangeSet(base_commit="c1", modified={"src/calculator.py"}),
        file_symbols={
            "src/calculator.py": {
                "multiply",
                "async_fetch",
                "Calculator.compute",
                "Calculator._private_helper",
            }
        },
    )
    cs = GitChangeSet(base_commit="c1", modified={"src/calculator.py"})

    result = verify_implementation(
        baseline=baseline,
        repo_root=tmp_path,
        repo_info=repo_info,
        changeset=cs,
        pre_snapshot=pre,
        post_snapshot=post,
    )
    assert result.status == VerificationStatus.WARN
    drift = [f for f in result.findings if f.category == FindingCategory.ABSTRACTION_DRIFT]
    drift_symbols = {d.symbol for d in drift}
    assert "async_fetch" in drift_symbols
    assert "Calculator.compute" in drift_symbols
    assert "Calculator._private_helper" not in drift_symbols
    assert "multiply" not in drift_symbols


def test_symbol_drift_expected_class_qualified_symbol(tmp_path: Path) -> None:
    """Expected class-qualified symbol Calculator.multiply produces no drift warning."""
    calc_path = tmp_path / "src" / "calculator.py"
    calc_path.parent.mkdir(parents=True, exist_ok=True)
    calc_path.write_text(
        "class Calculator:\n    def multiply(self):\n        pass\n",
        encoding="utf-8",
    )

    baseline = ImplementationBaseline(
        schema_version="0.1.0",
        repository=BaselineRepositoryInfo(name=tmp_path.name, commit="c1"),
        intent=BaselineIntent(title="Add Calculator.multiply", goal="Method addition"),
        expectations=BaselineExpectations(
            expected_files=[
                ExpectedFile(path="src/calculator.py", action="modify", status="resolved")
            ],
            expected_symbols=[
                ExpectedSymbol(name="Calculator.multiply", kind="method", status="unresolved")
            ],
        ),
    )
    repo_info = GitRepoInfo(root=tmp_path, branch="main", head_sha="c1", is_dirty=False)

    pre = WorkingTreeSnapshot(
        changeset=GitChangeSet(base_commit="c1"),
        file_symbols={"src/calculator.py": {"Calculator"}},
    )
    post = WorkingTreeSnapshot(
        changeset=GitChangeSet(base_commit="c1", modified={"src/calculator.py"}),
        file_symbols={"src/calculator.py": {"Calculator", "Calculator.multiply"}},
    )
    cs = GitChangeSet(base_commit="c1", modified={"src/calculator.py"})

    result = verify_implementation(
        baseline=baseline,
        repo_root=tmp_path,
        repo_info=repo_info,
        changeset=cs,
        pre_snapshot=pre,
        post_snapshot=post,
    )
    assert result.status == VerificationStatus.PASS
    drift = [f for f in result.findings if f.category == FindingCategory.ABSTRACTION_DRIFT]
    assert len(drift) == 0


def test_behavioral_drift_body_change_warns(tmp_path: Path) -> None:
    """Body change (a + b -> a - b) triggers BEHAVIORAL_DRIFT WARN, FAIL in strict mode."""
    baseline, repo_info = _make_symbol_drift_baseline(tmp_path)
    calc = tmp_path / "src" / "calculator.py"
    calc.write_text("def add(a: int, b: int) -> int:\n    return a + b\n", encoding="utf-8")

    syms_pre, fps_pre, _ = extract_file_symbols_and_fingerprints(calc)
    pre = WorkingTreeSnapshot(
        changeset=GitChangeSet(base_commit="c1"),
        file_symbols={"src/calculator.py": syms_pre},
        symbol_fingerprints={"src/calculator.py": fps_pre},
    )

    calc.write_text(
        "def add(a: int, b: int) -> int:\n    return a - b\n"
        "def multiply(a: int, b: int) -> int:\n    return a * b\n",
        encoding="utf-8",
    )
    syms_post, fps_post, _ = extract_file_symbols_and_fingerprints(calc)
    post = WorkingTreeSnapshot(
        changeset=GitChangeSet(base_commit="c1", modified={"src/calculator.py"}),
        file_symbols={"src/calculator.py": syms_post},
        symbol_fingerprints={"src/calculator.py": fps_post},
    )
    cs = GitChangeSet(base_commit="c1", modified={"src/calculator.py"})

    result = verify_implementation(
        baseline=baseline,
        repo_root=tmp_path,
        repo_info=repo_info,
        changeset=cs,
        pre_snapshot=pre,
        post_snapshot=post,
    )
    assert result.status == VerificationStatus.WARN
    drift = [f for f in result.findings if f.category == FindingCategory.BEHAVIORAL_DRIFT]
    assert len(drift) == 1
    assert drift[0].symbol == "add"
    assert drift[0].severity == FindingSeverity.WARN
    assert "Implementation body of function 'add' was modified" in drift[0].message
    assert "(signature preserved)" in drift[0].message
    assert drift[0].expected == "unmodified function body"
    assert drift[0].actual == "modified body implementation"

    result_strict = verify_implementation(
        baseline=baseline,
        repo_root=tmp_path,
        repo_info=repo_info,
        changeset=cs,
        pre_snapshot=pre,
        post_snapshot=post,
        strict=True,
    )
    assert result_strict.status == VerificationStatus.FAIL


def test_behavioral_drift_signature_change_warns(tmp_path: Path) -> None:
    """Signature change (adding parameter) triggers BEHAVIORAL_DRIFT WARN."""
    baseline, repo_info = _make_symbol_drift_baseline(tmp_path)
    calc = tmp_path / "src" / "calculator.py"
    calc.write_text("def add(a: int, b: int) -> int:\n    return a + b\n", encoding="utf-8")

    syms_pre, fps_pre, _ = extract_file_symbols_and_fingerprints(calc)
    pre = WorkingTreeSnapshot(
        changeset=GitChangeSet(base_commit="c1"),
        file_symbols={"src/calculator.py": syms_pre},
        symbol_fingerprints={"src/calculator.py": fps_pre},
    )

    calc.write_text(
        "def add(a: int, b: int, c: int = 0) -> int:\n    return a + b\n"
        "def multiply(a: int, b: int) -> int:\n    return a * b\n",
        encoding="utf-8",
    )
    syms_post, fps_post, _ = extract_file_symbols_and_fingerprints(calc)
    post = WorkingTreeSnapshot(
        changeset=GitChangeSet(base_commit="c1", modified={"src/calculator.py"}),
        file_symbols={"src/calculator.py": syms_post},
        symbol_fingerprints={"src/calculator.py": fps_post},
    )
    cs = GitChangeSet(base_commit="c1", modified={"src/calculator.py"})

    result = verify_implementation(
        baseline=baseline,
        repo_root=tmp_path,
        repo_info=repo_info,
        changeset=cs,
        pre_snapshot=pre,
        post_snapshot=post,
    )
    assert result.status == VerificationStatus.WARN
    drift = [f for f in result.findings if f.category == FindingCategory.BEHAVIORAL_DRIFT]
    assert len(drift) == 1
    assert drift[0].symbol == "add"
    assert drift[0].severity == FindingSeverity.WARN
    assert "Signature of function 'add' was modified" in drift[0].message
    assert drift[0].expected == "unmodified function signature"
    assert drift[0].actual == "modified signature"


def test_behavioral_drift_decorator_change_warns(tmp_path: Path) -> None:
    """Decorator change triggers BEHAVIORAL_DRIFT WARN."""
    baseline, repo_info = _make_symbol_drift_baseline(tmp_path)
    calc = tmp_path / "src" / "calculator.py"
    calc.write_text("def add(a: int, b: int) -> int:\n    return a + b\n", encoding="utf-8")

    syms_pre, fps_pre, _ = extract_file_symbols_and_fingerprints(calc)
    pre = WorkingTreeSnapshot(
        changeset=GitChangeSet(base_commit="c1"),
        file_symbols={"src/calculator.py": syms_pre},
        symbol_fingerprints={"src/calculator.py": fps_pre},
    )

    calc.write_text(
        "@validate\ndef add(a: int, b: int) -> int:\n    return a + b\n"
        "def multiply(a: int, b: int) -> int:\n    return a * b\n",
        encoding="utf-8",
    )
    syms_post, fps_post, _ = extract_file_symbols_and_fingerprints(calc)
    post = WorkingTreeSnapshot(
        changeset=GitChangeSet(base_commit="c1", modified={"src/calculator.py"}),
        file_symbols={"src/calculator.py": syms_post},
        symbol_fingerprints={"src/calculator.py": fps_post},
    )
    cs = GitChangeSet(base_commit="c1", modified={"src/calculator.py"})

    result = verify_implementation(
        baseline=baseline,
        repo_root=tmp_path,
        repo_info=repo_info,
        changeset=cs,
        pre_snapshot=pre,
        post_snapshot=post,
    )
    assert result.status == VerificationStatus.WARN
    drift = [f for f in result.findings if f.category == FindingCategory.BEHAVIORAL_DRIFT]
    assert len(drift) == 1
    assert drift[0].symbol == "add"
    assert "Signature of function 'add' was modified" in drift[0].message


def test_behavioral_drift_docstring_only_no_warning(tmp_path: Path) -> None:
    """Modifying only the docstring produces zero behavioral drift findings."""
    baseline, repo_info = _make_symbol_drift_baseline(tmp_path)
    calc = tmp_path / "src" / "calculator.py"
    calc.write_text(
        'def add(a: int, b: int) -> int:\n    """Original docstring."""\n    return a + b\n',
        encoding="utf-8",
    )

    syms_pre, fps_pre, _ = extract_file_symbols_and_fingerprints(calc)
    pre = WorkingTreeSnapshot(
        changeset=GitChangeSet(base_commit="c1"),
        file_symbols={"src/calculator.py": syms_pre},
        symbol_fingerprints={"src/calculator.py": fps_pre},
    )

    calc.write_text(
        'def add(a: int, b: int) -> int:\n    """Updated detailed docstring."""\n    return a + b\n'
        "def multiply(a: int, b: int) -> int:\n    return a * b\n",
        encoding="utf-8",
    )
    syms_post, fps_post, _ = extract_file_symbols_and_fingerprints(calc)
    post = WorkingTreeSnapshot(
        changeset=GitChangeSet(base_commit="c1", modified={"src/calculator.py"}),
        file_symbols={"src/calculator.py": syms_post},
        symbol_fingerprints={"src/calculator.py": fps_post},
    )
    cs = GitChangeSet(base_commit="c1", modified={"src/calculator.py"})

    result = verify_implementation(
        baseline=baseline,
        repo_root=tmp_path,
        repo_info=repo_info,
        changeset=cs,
        pre_snapshot=pre,
        post_snapshot=post,
    )
    drift = [f for f in result.findings if f.category == FindingCategory.BEHAVIORAL_DRIFT]
    assert len(drift) == 0
    assert result.status == VerificationStatus.PASS


def test_behavioral_drift_formatting_only_no_warning(tmp_path: Path) -> None:
    """Formatting and comment changes produce zero behavioral drift findings."""
    baseline, repo_info = _make_symbol_drift_baseline(tmp_path)
    calc = tmp_path / "src" / "calculator.py"
    calc.write_text(
        "def add(a: int, b: int) -> int:\n    # Comment 1\n    return a + b\n",
        encoding="utf-8",
    )

    syms_pre, fps_pre, _ = extract_file_symbols_and_fingerprints(calc)
    pre = WorkingTreeSnapshot(
        changeset=GitChangeSet(base_commit="c1"),
        file_symbols={"src/calculator.py": syms_pre},
        symbol_fingerprints={"src/calculator.py": fps_pre},
    )

    calc.write_text(
        "def add(  a: int,   b: int  ) -> int:\n"
        "    # Completely different comment\n\n"
        "    return a   +   b\n"
        "def multiply(a: int, b: int) -> int:\n    return a * b\n",
        encoding="utf-8",
    )
    syms_post, fps_post, _ = extract_file_symbols_and_fingerprints(calc)
    post = WorkingTreeSnapshot(
        changeset=GitChangeSet(base_commit="c1", modified={"src/calculator.py"}),
        file_symbols={"src/calculator.py": syms_post},
        symbol_fingerprints={"src/calculator.py": fps_post},
    )
    cs = GitChangeSet(base_commit="c1", modified={"src/calculator.py"})

    result = verify_implementation(
        baseline=baseline,
        repo_root=tmp_path,
        repo_info=repo_info,
        changeset=cs,
        pre_snapshot=pre,
        post_snapshot=post,
    )
    drift = [f for f in result.findings if f.category == FindingCategory.BEHAVIORAL_DRIFT]
    assert len(drift) == 0
    assert result.status == VerificationStatus.PASS


def test_behavioral_drift_untouched_preexisting_dirty_no_warning(tmp_path: Path) -> None:
    """Pre-existing dirty function untouched in session produces zero drift findings."""
    baseline, repo_info = _make_symbol_drift_baseline(tmp_path)
    calc = tmp_path / "src" / "calculator.py"
    calc.write_text(
        "def add(a, b):\n    return a + b\n"
        "def untouched(x):\n    return x * 2\n",
        encoding="utf-8",
    )

    syms_pre, fps_pre, _ = extract_file_symbols_and_fingerprints(calc)
    pre = WorkingTreeSnapshot(
        changeset=GitChangeSet(base_commit="c1", modified={"src/calculator.py"}),
        file_symbols={"src/calculator.py": syms_pre},
        symbol_fingerprints={"src/calculator.py": fps_pre},
    )

    calc.write_text(
        "def add(a, b):\n    return a + b\n"
        "def untouched(x):\n    return x * 2\n"
        "def multiply(a, b):\n    return a * b\n",
        encoding="utf-8",
    )
    syms_post, fps_post, _ = extract_file_symbols_and_fingerprints(calc)
    post = WorkingTreeSnapshot(
        changeset=GitChangeSet(base_commit="c1", modified={"src/calculator.py"}),
        file_symbols={"src/calculator.py": syms_post},
        symbol_fingerprints={"src/calculator.py": fps_post},
    )
    cs = GitChangeSet(base_commit="c1", modified={"src/calculator.py"})

    result = verify_implementation(
        baseline=baseline,
        repo_root=tmp_path,
        repo_info=repo_info,
        changeset=cs,
        pre_snapshot=pre,
        post_snapshot=post,
    )
    drift = [f for f in result.findings if f.category == FindingCategory.BEHAVIORAL_DRIFT]
    assert len(drift) == 0
    assert result.status == VerificationStatus.PASS


def test_behavioral_drift_preexisting_dirty_modified_in_session_warns(tmp_path: Path) -> None:
    """Pre-existing dirty function modified in session triggers drift warning."""
    baseline, repo_info = _make_symbol_drift_baseline(tmp_path)
    calc = tmp_path / "src" / "calculator.py"
    calc.write_text(
        "def add(a, b):\n    return a + b\n"
        "def draft(x):\n    return x\n",
        encoding="utf-8",
    )

    syms_pre, fps_pre, _ = extract_file_symbols_and_fingerprints(calc)
    pre = WorkingTreeSnapshot(
        changeset=GitChangeSet(base_commit="c1", modified={"src/calculator.py"}),
        file_symbols={"src/calculator.py": syms_pre},
        symbol_fingerprints={"src/calculator.py": fps_pre},
    )

    calc.write_text(
        "def add(a, b):\n    return a + b\n"
        "def draft(x):\n    return x * 10\n"
        "def multiply(a, b):\n    return a * b\n",
        encoding="utf-8",
    )
    syms_post, fps_post, _ = extract_file_symbols_and_fingerprints(calc)
    post = WorkingTreeSnapshot(
        changeset=GitChangeSet(base_commit="c1", modified={"src/calculator.py"}),
        file_symbols={"src/calculator.py": syms_post},
        symbol_fingerprints={"src/calculator.py": fps_post},
    )
    cs = GitChangeSet(base_commit="c1", modified={"src/calculator.py"})

    result = verify_implementation(
        baseline=baseline,
        repo_root=tmp_path,
        repo_info=repo_info,
        changeset=cs,
        pre_snapshot=pre,
        post_snapshot=post,
    )
    assert result.status == VerificationStatus.WARN
    drift = [f for f in result.findings if f.category == FindingCategory.BEHAVIORAL_DRIFT]
    assert len(drift) == 1
    assert drift[0].symbol == "draft"
    assert "Implementation body of function 'draft' was modified" in drift[0].message


def test_behavioral_drift_new_function_ignored_by_phase8(tmp_path: Path) -> None:
    """New unexpected function is reported by Phase 7 as ABSTRACTION_DRIFT, not Phase 8."""
    baseline, repo_info = _make_symbol_drift_baseline(tmp_path)
    calc = tmp_path / "src" / "calculator.py"
    calc.write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")

    syms_pre, fps_pre, _ = extract_file_symbols_and_fingerprints(calc)
    pre = WorkingTreeSnapshot(
        changeset=GitChangeSet(base_commit="c1"),
        file_symbols={"src/calculator.py": syms_pre},
        symbol_fingerprints={"src/calculator.py": fps_pre},
    )

    calc.write_text(
        "def add(a, b):\n    return a + b\n"
        "def multiply(a, b):\n    return a * b\n"
        "def divide(a, b):\n    return a / b\n",
        encoding="utf-8",
    )
    syms_post, fps_post, _ = extract_file_symbols_and_fingerprints(calc)
    post = WorkingTreeSnapshot(
        changeset=GitChangeSet(base_commit="c1", modified={"src/calculator.py"}),
        file_symbols={"src/calculator.py": syms_post},
        symbol_fingerprints={"src/calculator.py": fps_post},
    )
    cs = GitChangeSet(base_commit="c1", modified={"src/calculator.py"})

    result = verify_implementation(
        baseline=baseline,
        repo_root=tmp_path,
        repo_info=repo_info,
        changeset=cs,
        pre_snapshot=pre,
        post_snapshot=post,
    )
    behavioral_drift = [
        f for f in result.findings if f.category == FindingCategory.BEHAVIORAL_DRIFT
    ]
    assert len(behavioral_drift) == 0

    abstraction_drift = [
        f for f in result.findings if f.category == FindingCategory.ABSTRACTION_DRIFT
    ]
    assert len(abstraction_drift) == 1
    assert abstraction_drift[0].symbol == "divide"


def test_behavioral_drift_syntax_error_reported_as_error(tmp_path: Path) -> None:
    """Invalid syntax in post-snapshot file reports MISSING_IMPLEMENTATION error."""
    baseline, repo_info = _make_symbol_drift_baseline(tmp_path)
    calc = tmp_path / "src" / "calculator.py"
    calc.write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")

    syms_pre, fps_pre, _ = extract_file_symbols_and_fingerprints(calc)
    pre = WorkingTreeSnapshot(
        changeset=GitChangeSet(base_commit="c1"),
        file_symbols={"src/calculator.py": syms_pre},
        symbol_fingerprints={"src/calculator.py": fps_pre},
    )

    calc.write_text("def broken(:\n    return\n", encoding="utf-8")
    syms_post, fps_post, err_post = extract_file_symbols_and_fingerprints(calc)
    assert err_post is not None
    post = WorkingTreeSnapshot(
        changeset=GitChangeSet(base_commit="c1", modified={"src/calculator.py"}),
        file_symbols={"src/calculator.py": syms_post},
        symbol_fingerprints={"src/calculator.py": fps_post},
        parse_errors={"src/calculator.py": err_post},
    )
    cs = GitChangeSet(base_commit="c1", modified={"src/calculator.py"})

    result = verify_implementation(
        baseline=baseline,
        repo_root=tmp_path,
        repo_info=repo_info,
        changeset=cs,
        pre_snapshot=pre,
        post_snapshot=post,
    )
    assert result.status == VerificationStatus.FAIL
    errors = [f for f in result.findings if f.severity == FindingSeverity.ERROR]
    assert len(errors) == 1
    assert errors[0].category == FindingCategory.MISSING_IMPLEMENTATION
    assert "Syntax error in 'src/calculator.py'" in errors[0].message
    assert "SyntaxError" in errors[0].evidence


def test_behavioral_drift_standalone_verify_without_snapshots_passes(tmp_path: Path) -> None:
    """Standalone verification without snapshots passes without behavioral drift checks."""
    baseline, repo_info = _make_symbol_drift_baseline(tmp_path)
    calc = tmp_path / "src" / "calculator.py"
    calc.write_text(
        "def add(a, b):\n    return a - b\n"
        "def multiply(a, b):\n    return a * b\n",
        encoding="utf-8",
    )

    result = verify_implementation(
        baseline=baseline,
        repo_root=tmp_path,
        repo_info=repo_info,
        changeset=None,
        pre_snapshot=None,
        post_snapshot=None,
    )
    assert result.status is not None
    drift = [f for f in result.findings if f.category == FindingCategory.BEHAVIORAL_DRIFT]
    assert len(drift) == 0
