"""Unit and functional tests for codealign context command and exporter."""

from pathlib import Path

from typer.testing import CliRunner

from codealign.cli import app
from codealign.context.exporter import export_agent_context
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

runner = CliRunner()


def _make_sample_baseline() -> ImplementationBaseline:
    """Create a realistic ImplementationBaseline fixture."""
    return ImplementationBaseline(
        schema_version="0.1.0",
        generated_at="2026-10-05T12:00:00Z",
        repository=BaselineRepositoryInfo(
            name="CodeAlign",
            branch="feature/cache",
            commit="abcdef1234567890",
        ),
        intent=BaselineIntent(
            plan_file="plan.md",
            title="Add Redis caching to user profiles",
            goal="Add Redis caching for user profile lookups.",
            steps=[
                "Update `UserService.getProfile()` to query Redis cache.",
                "Add Redis configuration in `src/config/redis.ts`.",
                "Create `tests/test_cache.py`.",
                "Update `docs/missing_notes.md`.",
            ],
        ),
        evidence=BaselineEvidence(
            summary={
                "total_references": 5,
                "resolved_count": 2,
                "unresolved_count": 3,
            },
            resolved=[
                BaselineEvidenceItem(
                    reference="UserService.getProfile()",
                    status="resolved",
                    kind="method",
                    symbol="UserService.getProfile",
                    file_path="src/services/UserService.ts",
                    line=42,
                    callers=[
                        {
                            "file_path": "src/controllers/UserController.ts",
                            "line": 18,
                            "symbol": "showUser",
                            "relation": "calls",
                        }
                    ],
                    callees=[
                        {
                            "file_path": "src/repositories/UserRepository.ts",
                            "line": 25,
                            "symbol": ".findById",
                            "relation": "calls",
                        }
                    ],
                    relationships=[
                        {
                            "direction": "outgoing",
                            "relation": "calls",
                            "source_file": "src/services/UserService.ts",
                            "source_line": 42,
                            "source_symbol": ".getProfile",
                            "target_file": "src/repositories/UserRepository.ts",
                            "target_line": 25,
                            "target_symbol": ".findById",
                        }
                    ],
                ),
                BaselineEvidenceItem(
                    reference="src/config/redis.ts",
                    status="resolved",
                    kind="file",
                    symbol="src/config/redis.ts",
                    file_path="src/config/redis.ts",
                    line=1,
                    symbols_in_file=[{"line": 5, "name": "RedisConfig", "kind": "class"}],
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
                    reference="tests/test_cache.py",
                    status="unresolved",
                    kind="file",
                    reason="File 'tests/test_cache.py' not found in codebase graph",
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
                    path="src/config/redis.ts",
                    action="modify",
                    status="resolved",
                    reason="Explicitly referenced in plan",
                ),
                ExpectedFile(
                    path="src/services/UserService.ts",
                    action="modify",
                    status="resolved",
                    reason="Defines target symbol 'UserService.getProfile' referenced in plan",
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
                    reason="Explicitly referenced in plan as 'UserService.getProfile()'",
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


def test_context_generation_from_valid_baseline() -> None:
    """Verify that export_agent_context faithfully transforms baseline contract into Markdown."""
    baseline = _make_sample_baseline()
    md = export_agent_context(baseline)

    # 1. Header & Intent
    assert "# CodeAlign Implementation Context: Add Redis caching to user profiles" in md
    assert "## Intent" in md
    assert "### Goal" in md
    assert "Add Redis caching for user profile lookups." in md
    assert "### Implementation Steps" in md
    assert "1. Update `UserService.getProfile()` to query Redis cache." in md
    assert "3. Create `tests/test_cache.py`." in md

    # 2. Repository Identity
    assert "## Repository" in md
    assert "- **Name:** CodeAlign" in md
    assert "- **Branch:** feature/cache" in md
    assert "- **Baseline Commit:** `abcdef1234567890`" in md

    # 3. Expected Changes
    assert "## Expected Changes" in md
    assert "| `src/services/UserService.ts` | modify | resolved |" in md
    assert "| `tests/test_cache.py` | create | expected |" in md
    assert "| `docs/missing_notes.md` | unresolved | unresolved |" in md

    # 4. Expected Symbols
    assert "## Expected Symbols" in md
    expected_sym = (
        "`UserService.getProfile` [method, status: existing] (`src/services/UserService.ts:42`)"
    )
    assert expected_sym in md
    assert "`MissingService.missingMethod()` [method, status: unresolved]" in md

    # 5. Expected Tests
    assert "## Expected Tests" in md
    assert "- `tests/test_cache.py`" in md

    # 6. Repository Evidence
    assert "## Repository Evidence" in md
    assert "### Resolved References" in md
    assert "#### `UserService.getProfile()`" in md
    assert "- **Target:** `src/services/UserService.ts:42` (method: `UserService.getProfile`)" in md
    assert "- `src/controllers/UserController.ts:18` (`showUser`)" in md
    assert "- `src/repositories/UserRepository.ts:25` (`.findById`)" in md

    # 7. Unresolved References
    assert "### Unresolved References" in md
    expected_unres_file = (
        "- **`docs/missing_notes.md`** (file): File 'docs/missing_notes.md' "
        "not found in codebase graph"
    )
    assert expected_unres_file in md
    expected_unres_sym = (
        "- **`MissingService.missingMethod()`** (method): Class 'MissingService' "
        "not found in codebase graph"
    )
    assert expected_unres_sym in md

    # 8. Constraints
    assert "## Constraints" in md
    assert "- Do not add network calls in unit tests." in md


def test_context_unresolved_references_visible() -> None:
    """Verify unresolved references and missing files remain clearly visible."""
    baseline = _make_sample_baseline()
    md = export_agent_context(baseline)

    assert "unresolved" in md
    assert "MissingService.missingMethod()" in md
    assert "docs/missing_notes.md" in md


def test_context_determinism() -> None:
    """Verify context generation is deterministic and free of machine paths or timestamps."""
    baseline = _make_sample_baseline()
    md1 = export_agent_context(baseline)
    md2 = export_agent_context(baseline)

    assert md1 == md2
    # Ensure no local absolute filesystem path leaks
    assert "C:" not in md1
    assert "/Users/" not in md1
    assert "/home/" not in md1
    # Ensure generated_at timestamp is not embedded in context
    assert "2026-10-05T12:00:00Z" not in md1


def test_context_command_default_file_output(tmp_path: Path, monkeypatch) -> None:
    """Verify codealign context command writes .codealign/context.md and echoes summary."""
    codealign_dir = tmp_path / ".codealign"
    codealign_dir.mkdir(parents=True)
    baseline_path = codealign_dir / "baseline.json"
    baseline = _make_sample_baseline()
    baseline_path.write_text(baseline.to_json(), encoding="utf-8")

    repo_info = GitRepoInfo(
        root=tmp_path,
        branch="main",
        head_sha="abcdef1234567890",
        is_dirty=False,
    )
    monkeypatch.setattr("codealign.commands.context.get_git_repo_info", lambda: repo_info)

    result = runner.invoke(app, ["context"])
    assert result.exit_code == 0
    assert "CONTEXT GENERATED" in result.stdout
    assert "Add Redis caching to user profiles" in result.stdout
    assert ".codealign/context.md" in result.stdout

    context_file = codealign_dir / "context.md"
    assert context_file.is_file()
    content = context_file.read_text(encoding="utf-8")
    assert "# CodeAlign Implementation Context:" in content
    assert "UserService.getProfile()" in content


def test_context_command_stdout_flag(tmp_path: Path, monkeypatch) -> None:
    """Verify codealign context --stdout prints raw Markdown directly to standard output."""
    codealign_dir = tmp_path / ".codealign"
    codealign_dir.mkdir(parents=True)
    baseline_path = codealign_dir / "baseline.json"
    baseline = _make_sample_baseline()
    baseline_path.write_text(baseline.to_json(), encoding="utf-8")

    repo_info = GitRepoInfo(
        root=tmp_path,
        branch="main",
        head_sha="abcdef1234567890",
        is_dirty=False,
    )
    monkeypatch.setattr("codealign.commands.context.get_git_repo_info", lambda: repo_info)

    result = runner.invoke(app, ["context", "--stdout"])
    assert result.exit_code == 0
    assert result.stdout.startswith("# CodeAlign Implementation Context:")
    assert "## Expected Changes" in result.stdout
    # Also verify file was written
    assert (codealign_dir / "context.md").is_file()


def test_context_command_custom_paths(tmp_path: Path, monkeypatch) -> None:
    """Verify codealign context with custom --baseline and --output paths."""
    codealign_dir = tmp_path / ".codealign"
    codealign_dir.mkdir(parents=True)

    custom_baseline = tmp_path / "custom_baseline.json"
    custom_output = tmp_path / "custom_context.md"

    baseline = _make_sample_baseline()
    custom_baseline.write_text(baseline.to_json(), encoding="utf-8")

    repo_info = GitRepoInfo(
        root=tmp_path,
        branch="main",
        head_sha="abcdef1234567890",
        is_dirty=False,
    )
    monkeypatch.setattr("codealign.commands.context.get_git_repo_info", lambda: repo_info)

    result = runner.invoke(
        app,
        ["context", "--baseline", str(custom_baseline), "--output", str(custom_output)],
    )
    assert result.exit_code == 0
    assert "CONTEXT GENERATED" in result.stdout
    assert custom_output.is_file()


def test_context_command_missing_baseline_fails(tmp_path: Path, monkeypatch) -> None:
    """Verify clear error when baseline contract does not exist without silent regeneration."""
    codealign_dir = tmp_path / ".codealign"
    codealign_dir.mkdir(parents=True)

    repo_info = GitRepoInfo(
        root=tmp_path,
        branch="main",
        head_sha="abcdef1234567890",
        is_dirty=False,
    )
    monkeypatch.setattr("codealign.commands.context.get_git_repo_info", lambda: repo_info)

    result = runner.invoke(app, ["context"])
    assert result.exit_code == 1
    assert "Error: Baseline contract not found" in result.output
    assert "codealign baseline" in result.output

    # Confirm baseline was not created silently
    assert not (codealign_dir / "baseline.json").exists()
    assert not (codealign_dir / "context.md").exists()


def test_context_command_uninitialized_repo_fails(tmp_path: Path, monkeypatch) -> None:
    """Verify error when repository has not been initialized with codealign init."""
    repo_info = GitRepoInfo(
        root=tmp_path,
        branch="main",
        head_sha="abcdef1234567890",
        is_dirty=False,
    )
    monkeypatch.setattr("codealign.commands.context.get_git_repo_info", lambda: repo_info)

    result = runner.invoke(app, ["context"])
    assert result.exit_code == 1
    assert "Error: CodeAlign is not initialized" in result.output
    assert "codealign init" in result.output
