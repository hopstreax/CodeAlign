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
from codealign.models.finding import FindingCategory, FindingSeverity
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
