"""Tier 2 opt-in real-agent end-to-end acceptance test for CodeAlign.

This test exercises the actual installed `agy` (Antigravity) CLI executable
against a disposable Git repository running the full unmocked CodeAlign
implementation and verification pipeline.

It is strictly opt-in:
    CODEALIGN_RUN_REAL_AGENT=1 pytest tests/test_e2e_real_agent.py

When opt-in is absent or when 'agy' is not installed on PATH, the test is
skipped cleanly so ordinary CI runs remain deterministic and fast.
"""

import os
import signal
import subprocess
import sys
from pathlib import Path

import pytest

from codealign.agent.antigravity import AntigravityAgent
from codealign.context.exporter import export_agent_context
from codealign.git.repository import run_git_command
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

DEFAULT_TIMEOUT_SECONDS = 180.0


def _kill_process_tree(pid: int) -> None:
    """Safely terminate a process and its full subprocess tree on Windows and POSIX."""
    if sys.platform == "win32":
        try:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                capture_output=True,
                check=False,
            )
        except Exception:
            pass
    else:
        try:
            os.killpg(os.getpgid(pid), signal.SIGTERM)
        except Exception:
            try:
                os.kill(pid, signal.SIGTERM)
            except Exception:
                pass


def _detect_environmental_failure(output: str) -> str | None:
    """Detect whether output indicates an external environmental issue rather than a bug.

    External issues include quota exhaustion, API rate limits, authentication failures,
    network dropouts, and command timeouts.
    """
    lowered = output.lower()

    if any(
        k in lowered
        for k in (
            "quota",
            "resource_exhausted",
            "rate limit",
            "too many requests",
            "429",
            "exceeded your current quota",
        )
    ):
        return "Agent API quota or rate limit exceeded"

    if any(
        k in lowered
        for k in (
            "unauthenticated",
            "unauthorized",
            "not logged in",
            "auth error",
            "authentication failed",
            "invalid api key",
            "api key not found",
            "credentials",
            "401",
            "403",
        )
    ):
        return "Agent authentication or credential error"

    if any(
        k in lowered
        for k in (
            "econnrefused",
            "connection refused",
            "connection reset",
            "failed to connect",
            "network error",
            "socket hang up",
            "dns error",
            "name resolution",
            "temporary failure in name resolution",
        )
    ):
        return "Agent network connectivity error"

    if any(k in lowered for k in ("timed out", "timeout expired", "deadline exceeded")):
        return "Agent execution timeout"

    if any(
        k in lowered
        for k in (
            "permission check failed",
            "user denied permission",
            "permission denied",
            "operation not permitted",
        )
    ):
        return "Agent tool permission check failed or denied"

    return None


@pytest.mark.e2e
def test_real_agent_implement_antigravity(tmp_path: Path) -> None:
    """Opt-in E2E acceptance test invoking real 'agy' on a disposable repository."""
    # 1. Verify opt-in behavior and executable availability
    if os.environ.get("CODEALIGN_RUN_REAL_AGENT") != "1":
        pytest.skip("Skipping real agent E2E test: set CODEALIGN_RUN_REAL_AGENT=1 to enable.")

    if not AntigravityAgent.is_available():
        pytest.skip("Skipping real agent E2E test: 'agy' executable not found on PATH.")

    # 2. Build disposable Git repository
    repo_root = tmp_path / "disposable_calc_repo"
    repo_root.mkdir(parents=True, exist_ok=True)

    run_git_command(["init", "-b", "main"], cwd=repo_root)
    run_git_command(["config", "user.name", "CodeAlign Acceptance Test"], cwd=repo_root)
    run_git_command(["config", "user.email", "test@codealign.local"], cwd=repo_root)

    src_dir = repo_root / "src"
    src_dir.mkdir(parents=True, exist_ok=True)
    calc_file = src_dir / "calculator.py"
    calc_file.write_text("def add(a: int, b: int) -> int:\n    return a + b\n", encoding="utf-8")
    (src_dir / "__init__.py").write_text("", encoding="utf-8")

    tests_dir = repo_root / "tests"
    tests_dir.mkdir(parents=True, exist_ok=True)
    test_calc_file = tests_dir / "test_calculator.py"
    test_calc_file.write_text(
        "from src.calculator import add\n\n\ndef test_add():\n    assert add(2, 3) == 5\n",
        encoding="utf-8",
    )
    (tests_dir / "__init__.py").write_text("", encoding="utf-8")

    pytest_ini = repo_root / "pytest.ini"
    pytest_ini.write_text("[pytest]\npythonpath = .\n", encoding="utf-8")

    gitignore = repo_root / ".gitignore"
    gitignore.write_text(
        "__pycache__/\n*.py[cod]\n.pytest_cache/\n.codealign/\n", encoding="utf-8"
    )

    plan_file = repo_root / "plan.md"
    plan_file.write_text(
        "# Add Multiply Operation\n\n"
        "## Goal\n"
        "Add a multiply operation without changing the existing add behavior.\n\n"
        "## Implementation Steps\n"
        "1. Add `multiply()` to `src/calculator.py`.\n"
        "2. Add a test for `multiply()` to `tests/test_calculator.py`.\n"
        "3. Preserve the existing `add()` behavior.\n\n"
        "## Constraints\n"
        "- Perform file edits directly using file edit tools "
        "without executing terminal commands.\n",
        encoding="utf-8",
    )

    # Initial commit establishes baseline commit
    run_git_command(["add", "."], cwd=repo_root)
    run_git_command(["commit", "-m", "Initial calculator baseline commit"], cwd=repo_root)
    base_commit = run_git_command(["rev-parse", "HEAD"], cwd=repo_root)
    branch = run_git_command(["branch", "--show-current"], cwd=repo_root) or "main"

    # Pre-existing untracked file (must remain untouched and excluded from session changes)
    notes_file = repo_root / "local-notes.txt"
    notes_content = "Developer private notes: verify edge cases later.\n"
    notes_file.write_text(notes_content, encoding="utf-8")

    # 3. Create CodeAlign baseline and context artifacts
    baseline = ImplementationBaseline(
        schema_version="0.1.0",
        generated_at="2026-10-10T00:00:00Z",
        repository=BaselineRepositoryInfo(
            name=repo_root.name,
            branch=branch,
            commit=base_commit,
        ),
        intent=BaselineIntent(
            plan_file="plan.md",
            title="Add Multiply Operation",
            goal="Add a multiply operation without changing the existing add behavior.",
            steps=[
                "Add `multiply()` to `src/calculator.py`.",
                "Add a test for `multiply()` to `tests/test_calculator.py`.",
                "Preserve the existing `add()` behavior.",
            ],
        ),
        constraints=[
            "Perform file edits directly using file edit tools without executing terminal commands."
        ],
        evidence=BaselineEvidence(
            summary={"total_references": 4, "resolved_count": 3, "unresolved_count": 1},
            resolved=[
                BaselineEvidenceItem(
                    reference="add()",
                    status="resolved",
                    kind="function",
                    symbol="add",
                    file_path="src/calculator.py",
                    line=1,
                ),
                BaselineEvidenceItem(
                    reference="src/calculator.py",
                    status="resolved",
                    kind="file",
                    symbol="src/calculator.py",
                    file_path="src/calculator.py",
                    line=1,
                ),
                BaselineEvidenceItem(
                    reference="tests/test_calculator.py",
                    status="resolved",
                    kind="file",
                    symbol="tests/test_calculator.py",
                    file_path="tests/test_calculator.py",
                    line=1,
                ),
            ],
            unresolved=[
                BaselineEvidenceItem(
                    reference="multiply()",
                    status="unresolved",
                    kind="symbol",
                    reason="Symbol 'multiply()' not found in codebase graph",
                ),
            ],
        ),
        expectations=BaselineExpectations(
            expected_files=[
                ExpectedFile(
                    path="src/calculator.py",
                    action="modify",
                    status="resolved",
                    reason="Explicitly referenced in plan",
                ),
                ExpectedFile(
                    path="tests/test_calculator.py",
                    action="modify",
                    status="resolved",
                    reason="Explicitly referenced in plan",
                ),
            ],
            expected_symbols=[
                ExpectedSymbol(
                    name="add",
                    kind="function",
                    file_path="src/calculator.py",
                    line=1,
                    status="existing",
                    reason="Explicitly referenced in plan as 'add()'",
                ),
                ExpectedSymbol(
                    name="multiply",
                    kind="function",
                    file_path="",
                    status="unresolved",
                    reason="Symbol 'multiply()' not found in codebase graph",
                ),
            ],
            expected_tests=[
                ExpectedTest(
                    path="tests/test_calculator.py",
                    reason="Explicit test file referenced in plan",
                ),
            ],
        ),
    )

    codealign_dir = repo_root / ".codealign"
    codealign_dir.mkdir(parents=True, exist_ok=True)
    (codealign_dir / "baseline.json").write_text(baseline.to_json(indent=2), encoding="utf-8")
    (codealign_dir / "context.md").write_text(export_agent_context(baseline), encoding="utf-8")

    config_content = (
        f"# CodeAlign project configuration\n\n"
        f"[repository]\n"
        f'name = "{repo_root.name}"\n'
        f'root = "{repo_root.as_posix()}"\n'
        f'initialized_at = "2026-10-10T00:00:00Z"\n\n'
        f"[git]\n"
        f'initial_branch = "{branch}"\n'
        f'initial_commit = "{base_commit}"\n\n'
        f"[graphify]\n"
        f'output_dir = "graphify-out"\n'
        f'graph_file = "graphify-out/graph.json"\n'
    )
    (codealign_dir / "config.toml").write_text(config_content, encoding="utf-8")

    # 4. Invoke real codealign implement --agent antigravity workflow
    timeout_env = os.environ.get("CODEALIGN_REAL_AGENT_TIMEOUT")
    timeout_seconds = float(timeout_env) if timeout_env else DEFAULT_TIMEOUT_SECONDS

    cmd = [sys.executable, "-m", "codealign.cli", "implement", "--agent", "antigravity"]
    if os.environ.get("CODEALIGN_DANGEROUSLY_SKIP_PERMISSIONS") == "1":
        cmd.append("--dangerously-skip-permissions")

    proc = subprocess.Popen(
        cmd,
        cwd=repo_root,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    stdout = ""
    stderr = ""
    timed_out = False
    try:
        stdout, stderr = proc.communicate(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        timed_out = True
        _kill_process_tree(proc.pid)
        stdout, stderr = proc.communicate()
    finally:
        if proc.poll() is None:
            _kill_process_tree(proc.pid)

    # 5. Handle timeouts and environmental failures gracefully
    if timed_out:
        pytest.skip(
            f"Environmental failure: Real agent invocation timed out after {timeout_seconds}s."
        )

    if proc.returncode != 0:
        combined_output = f"{stdout}\n{stderr}"
        env_reason = _detect_environmental_failure(combined_output)
        if env_reason:
            pytest.skip(
                f"Environmental failure during real agent execution ({env_reason}):\n"
                f"{combined_output.strip()}"
            )
        pytest.fail(
            f"Real agent implement command failed (exit code {proc.returncode}).\n"
            f"STDOUT:\n{stdout}\nSTDERR:\n{stderr}"
        )

    # 6. Verify command exit status and terminal output
    assert proc.returncode == 0
    assert "PASS" in stdout
    assert "Expected symbol 'multiply' created" in stdout
    assert "Expected file 'src/calculator.py' was modified" in stdout
    assert "Expected file 'tests/test_calculator.py' was modified" in stdout
    assert "Expected test file 'tests/test_calculator.py' verified" in stdout

    # 7. Verify source files and function definitions on disk
    calc_text = calc_file.read_text(encoding="utf-8")
    assert "def add(" in calc_text, "Existing function 'add' was removed or corrupted."
    assert "def multiply(" in calc_text, "'multiply' function was not created in src/calculator.py."

    test_calc_text = test_calc_file.read_text(encoding="utf-8")
    assert "test_add" in test_calc_text, "Existing 'test_add' test was removed."
    assert "multiply" in test_calc_text, (
        "Test for 'multiply' was not added to tests/test_calculator.py."
    )

    # 8. Run target repository's tests to confirm they pass
    target_test_result = subprocess.run(
        [sys.executable, "-m", "pytest"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert target_test_result.returncode == 0, (
        f"Target repository test suite failed after agent modification:\n"
        f"{target_test_result.stdout}\n{target_test_result.stderr}"
    )

    # 9. Verify pre-existing untracked file is unchanged and excluded from session
    assert notes_file.read_text(encoding="utf-8") == notes_content, (
        "Untracked local-notes.txt was unexpectedly modified."
    )
    assert "local-notes.txt" not in stdout, (
        "local-notes.txt was unexpectedly included in CodeAlign session changes."
    )
    assert "local-notes.txt" not in stderr
