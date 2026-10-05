"""Unit and functional tests for the Agent Handoff Contract."""

import hashlib
from pathlib import Path

import pytest
from typer.testing import CliRunner

from codealign.cli import app
from codealign.git.repository import GitRepoInfo
from codealign.handoff import (
    AgentHandoffPayload,
    BaselineNotFoundError,
    prepare_agent_handoff,
)
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
    """Create a realistic ImplementationBaseline fixture for handoff tests."""
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


def test_handoff_valid_baseline(tmp_path: Path) -> None:
    """Verify preparing handoff from a valid baseline contract succeeds and produces payload."""
    codealign_dir = tmp_path / ".codealign"
    codealign_dir.mkdir(parents=True)
    baseline_path = codealign_dir / "baseline.json"
    baseline = _make_sample_baseline()
    baseline_path.write_text(baseline.to_json(), encoding="utf-8")

    handoff = prepare_agent_handoff(tmp_path)
    assert isinstance(handoff, AgentHandoffPayload)
    assert handoff.baseline.intent.title == "Add Redis caching to user profiles"
    assert handoff.intent.goal == "Add Redis caching for user profile lookups."
    assert len(handoff.intent.steps) == 4
    assert handoff.repository.name == "CodeAlign"
    assert handoff.repository.branch == "feature/cache"
    assert handoff.repository.commit == "abcdef1234567890"

    assert len(handoff.expectations.expected_files) == 4
    assert len(handoff.expectations.expected_symbols) == 2
    assert len(handoff.expectations.expected_tests) == 1
    assert handoff.constraints == ["Do not add network calls in unit tests."]

    # Verify context markdown is prepared
    assert "# CodeAlign Implementation Context: Add Redis caching to user profiles" in (
        handoff.context_markdown
    )
    assert "UserService.getProfile()" in handoff.context_markdown


def test_handoff_missing_baseline_fails_clearly(tmp_path: Path) -> None:
    """Verify missing baseline fails clearly with BaselineNotFoundError without regeneration."""
    codealign_dir = tmp_path / ".codealign"
    codealign_dir.mkdir(parents=True)
    baseline_path = codealign_dir / "baseline.json"

    with pytest.raises(BaselineNotFoundError) as exc_info:
        prepare_agent_handoff(tmp_path)

    err_msg = str(exc_info.value)
    assert "Baseline contract not found" in err_msg
    assert "codealign baseline <plan.md>" in err_msg

    # Verify baseline was not silently regenerated
    assert not baseline_path.exists()
    assert not (codealign_dir / "context.md").exists()


def test_handoff_determinism(tmp_path: Path) -> None:
    """Verify preparing handoff twice against same baseline produces identical payloads."""
    codealign_dir = tmp_path / ".codealign"
    codealign_dir.mkdir(parents=True)
    baseline_path = codealign_dir / "baseline.json"
    baseline = _make_sample_baseline()
    baseline_path.write_text(baseline.to_json(), encoding="utf-8")

    handoff1 = prepare_agent_handoff(tmp_path)
    handoff2 = prepare_agent_handoff(tmp_path)

    assert handoff1.context_markdown == handoff2.context_markdown
    assert handoff1.baseline.to_dict() == handoff2.baseline.to_dict()


def test_handoff_uncertainty_preserved(tmp_path: Path) -> None:
    """Verify unresolved references and unconfirmed items remain explicit in handoff."""
    codealign_dir = tmp_path / ".codealign"
    codealign_dir.mkdir(parents=True)
    baseline_path = codealign_dir / "baseline.json"
    baseline = _make_sample_baseline()
    baseline_path.write_text(baseline.to_json(), encoding="utf-8")

    handoff = prepare_agent_handoff(tmp_path)

    # Check model evidence items
    unresolved_refs = [u.reference for u in handoff.evidence.unresolved]
    assert "docs/missing_notes.md" in unresolved_refs
    assert "MissingService.missingMethod()" in unresolved_refs

    # Check markdown presentation
    assert "### Unresolved References" in handoff.context_markdown
    assert "MissingService.missingMethod()" in handoff.context_markdown
    assert "docs/missing_notes.md" in handoff.context_markdown


def test_handoff_repository_binding(tmp_path: Path) -> None:
    """Verify the handoff payload retains the baseline's repository identity and commit."""
    codealign_dir = tmp_path / ".codealign"
    codealign_dir.mkdir(parents=True)
    baseline_path = codealign_dir / "baseline.json"
    baseline = _make_sample_baseline()
    baseline_path.write_text(baseline.to_json(), encoding="utf-8")

    handoff = prepare_agent_handoff(tmp_path)
    assert handoff.repository.name == "CodeAlign"
    assert handoff.repository.branch == "feature/cache"
    assert handoff.repository.commit == "abcdef1234567890"

    assert "- **Name:** CodeAlign" in handoff.context_markdown
    assert "- **Branch:** feature/cache" in handoff.context_markdown
    assert "- **Baseline Commit:** `abcdef1234567890`" in handoff.context_markdown


def test_handoff_no_mutation(tmp_path: Path) -> None:
    """Verify creating handoff does not modify baseline.json or repository files."""
    codealign_dir = tmp_path / ".codealign"
    codealign_dir.mkdir(parents=True)
    baseline_path = codealign_dir / "baseline.json"
    baseline = _make_sample_baseline()
    baseline_raw = baseline.to_json()
    baseline_path.write_text(baseline_raw, encoding="utf-8")

    # Compute baseline file hash before handoff
    initial_baseline_hash = hashlib.sha256(baseline_path.read_bytes()).hexdigest()

    # Create dummy source file to verify non-mutation
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    sample_file = src_dir / "sample.py"
    sample_content = "def sample(): return True\n"
    sample_file.write_text(sample_content, encoding="utf-8")
    initial_src_hash = hashlib.sha256(sample_file.read_bytes()).hexdigest()

    # Run handoff preparation
    _ = prepare_agent_handoff(tmp_path)

    # Verify baseline.json is byte-for-byte unchanged
    final_baseline_hash = hashlib.sha256(baseline_path.read_bytes()).hexdigest()
    assert initial_baseline_hash == final_baseline_hash

    # Verify source file is byte-for-byte unchanged
    final_src_hash = hashlib.sha256(sample_file.read_bytes()).hexdigest()
    assert initial_src_hash == final_src_hash


def test_handoff_to_dict_serializable(tmp_path: Path) -> None:
    """Verify AgentHandoffPayload.to_dict() returns valid serialized payload."""
    codealign_dir = tmp_path / ".codealign"
    codealign_dir.mkdir(parents=True)
    baseline_path = codealign_dir / "baseline.json"
    baseline = _make_sample_baseline()
    baseline_path.write_text(baseline.to_json(), encoding="utf-8")

    handoff = prepare_agent_handoff(tmp_path)
    data = handoff.to_dict()

    assert "baseline" in data
    assert "context_markdown" in data
    assert data["baseline"]["schema_version"] == "0.1.0"
    assert data["baseline"]["intent"]["title"] == "Add Redis caching to user profiles"
    assert isinstance(data["context_markdown"], str)


def test_handoff_cli_context_integration(tmp_path: Path, monkeypatch) -> None:
    """Verify codealign context CLI invokes handoff contract cleanly."""
    codealign_dir = tmp_path / ".codealign"
    codealign_dir.mkdir(parents=True)
    baseline_path = codealign_dir / "baseline.json"
    baseline = _make_sample_baseline()
    baseline_path.write_text(baseline.to_json(), encoding="utf-8")

    repo_info = GitRepoInfo(
        root=tmp_path,
        branch="feature/cache",
        head_sha="abcdef1234567890",
        is_dirty=False,
    )
    monkeypatch.setattr("codealign.commands.context.get_git_repo_info", lambda: repo_info)

    result = runner.invoke(app, ["context", "--stdout"])
    assert result.exit_code == 0
    assert result.stdout.startswith("# CodeAlign Implementation Context:")
    assert "Add Redis caching to user profiles" in result.stdout
