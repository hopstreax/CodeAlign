"""Unit tests for the AntigravityAgent adapter."""

import subprocess
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from codealign.agent.antigravity import (
    AntigravityAgent,
    AntigravityExecutionError,
    AntigravityNotFoundError,
    AntigravityResult,
)


def test_antigravity_is_available_agy(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify is_available returns True when agy is on PATH."""
    monkeypatch.setattr("shutil.which", lambda cmd: "/usr/bin/agy" if cmd == "agy" else None)
    assert AntigravityAgent.is_available() is True


def test_antigravity_is_available_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify is_available returns True when antigravity is on PATH as fallback."""
    monkeypatch.setattr(
        "shutil.which",
        lambda cmd: "/usr/bin/antigravity" if cmd == "antigravity" else None,
    )
    assert AntigravityAgent.is_available() is True


def test_antigravity_is_available_false(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify is_available returns False when neither agy nor antigravity is on PATH."""
    monkeypatch.setattr("shutil.which", lambda cmd: None)
    assert AntigravityAgent.is_available() is False


def test_antigravity_prefers_agy(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify find_executable prefers 'agy' over 'antigravity'."""
    monkeypatch.setattr(
        "shutil.which",
        lambda cmd: f"/usr/bin/{cmd}" if cmd in ("agy", "antigravity") else None,
    )
    assert AntigravityAgent.find_executable() == "/usr/bin/agy"


def test_antigravity_missing_executable_raises_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify accessing executable raises AntigravityNotFoundError when not on PATH."""
    monkeypatch.setattr("shutil.which", lambda cmd: None)
    agent = AntigravityAgent()
    with pytest.raises(AntigravityNotFoundError) as exc_info:
        _ = agent.executable
    assert "Antigravity CLI ('agy' or 'antigravity') not found on PATH" in str(exc_info.value)


def test_antigravity_explicit_executable() -> None:
    """Verify providing an explicit executable overrides PATH lookup."""
    agent = AntigravityAgent(executable="/custom/path/to/agy")
    assert agent.executable == "/custom/path/to/agy"


def test_antigravity_build_prompt() -> None:
    """Verify prompt formatting contains CodeAlign instructions and context markdown."""
    agent = AntigravityAgent(executable="/bin/agy")
    context_md = "# CodeAlign Implementation Context: Feature Y\n\n- modify src/calc.py"
    prompt = agent.build_prompt(context_md)

    assert "You are implementing planned repository changes guided by CodeAlign." in prompt
    assert "# CodeAlign Implementation Context: Feature Y" in prompt
    assert "- modify src/calc.py" in prompt
    assert "Do not commit or push your changes." in prompt


def test_antigravity_build_command_default() -> None:
    """Verify default command uses accept-edits mode and does NOT bypass permissions."""
    agent = AntigravityAgent(executable="/bin/agy")
    cmd = agent.build_command("test prompt")

    assert cmd == [
        "/bin/agy",
        "-p",
        "test prompt",
        "--mode",
        "accept-edits",
    ]
    assert "--dangerously-skip-permissions" not in cmd
    assert "--model" not in cmd


def test_antigravity_build_command_permission_bypass_explicit() -> None:
    """Verify dangerously-skip-permissions flag is added only when explicitly requested."""
    agent = AntigravityAgent(executable="/bin/agy")
    cmd = agent.build_command("test prompt", dangerously_skip_permissions=True)

    assert cmd == [
        "/bin/agy",
        "-p",
        "test prompt",
        "--mode",
        "accept-edits",
        "--dangerously-skip-permissions",
    ]


def test_antigravity_build_command_custom_mode() -> None:
    """Verify custom mode can be passed."""
    agent = AntigravityAgent(executable="/bin/agy")
    cmd = agent.build_command("test prompt", mode="plan")

    assert cmd == [
        "/bin/agy",
        "-p",
        "test prompt",
        "--mode",
        "plan",
    ]


def test_antigravity_build_command_with_model() -> None:
    """Verify model flag is passed only when explicitly specified."""
    agent = AntigravityAgent(executable="/bin/agy")
    cmd = agent.build_command("test prompt", model="gemini-2.5-pro")

    assert "--model" in cmd
    assert "gemini-2.5-pro" in cmd


def test_antigravity_run_success(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify successful subprocess execution returns AntigravityResult with success=True."""
    mock_run = MagicMock(
        return_value=subprocess.CompletedProcess(
            args=["/bin/agy"],
            returncode=0,
            stdout="Implemented files successfully.",
            stderr="",
        )
    )
    monkeypatch.setattr("subprocess.run", mock_run)

    agent = AntigravityAgent(executable="/bin/agy")
    result = agent.run(
        context_markdown="context",
        cwd=tmp_path,
        dangerously_skip_permissions=True,
    )

    assert isinstance(result, AntigravityResult)
    assert result.success is True
    assert result.exit_code == 0
    assert result.stdout == "Implemented files successfully."
    assert result.stderr == ""

    # Verify subprocess call arguments
    mock_run.assert_called_once()
    call_args, call_kwargs = mock_run.call_args
    assert call_kwargs["cwd"] == tmp_path
    assert call_kwargs["capture_output"] is True
    assert call_kwargs["text"] is True


def test_antigravity_run_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify subprocess non-zero exit code returns AntigravityResult with success=False."""
    mock_run = MagicMock(
        return_value=subprocess.CompletedProcess(
            args=["/bin/agy"],
            returncode=1,
            stdout="",
            stderr="Execution failed.",
        )
    )
    monkeypatch.setattr("subprocess.run", mock_run)

    agent = AntigravityAgent(executable="/bin/agy")
    result = agent.run(
        context_markdown="context",
        cwd=tmp_path,
    )

    assert result.success is False
    assert result.exit_code == 1
    assert "Execution failed." in result.stderr


def test_antigravity_run_timeout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify TimeoutExpired raises AntigravityExecutionError."""
    def fake_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=args[0], timeout=10.0)

    monkeypatch.setattr("subprocess.run", fake_run)

    agent = AntigravityAgent(executable="/bin/agy")
    with pytest.raises(AntigravityExecutionError) as exc_info:
        agent.run("context", cwd=tmp_path, timeout=10.0)

    assert "timed out after 10.0 seconds" in str(exc_info.value)


def test_antigravity_run_unexpected_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify unexpected OSError raises AntigravityExecutionError."""
    def fake_run(*args, **kwargs):
        raise OSError("Permission denied")

    monkeypatch.setattr("subprocess.run", fake_run)

    agent = AntigravityAgent(executable="/bin/agy")
    with pytest.raises(AntigravityExecutionError) as exc_info:
        agent.run("context", cwd=tmp_path)

    assert "Failed to execute Antigravity CLI: Permission denied" in str(exc_info.value)


def test_antigravity_run_timeout_kills_process_tree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify AntigravityAgent invokes kill_process_tree when process times out."""
    killed_pids: list[int] = []
    monkeypatch.setattr(
        "codealign.agent.antigravity.kill_process_tree",
        lambda pid: killed_pids.append(pid),
    )

    class FakePopen:
        pid = 88888
        returncode = None

        def __init__(self, *args, **kwargs):
            pass

        def communicate(self, timeout=None):
            raise subprocess.TimeoutExpired(cmd=["agy"], timeout=5.0)

        def poll(self):
            return None

    monkeypatch.setattr("subprocess.Popen", FakePopen)

    agent = AntigravityAgent(executable="/bin/agy")
    with pytest.raises(AntigravityExecutionError) as exc_info:
        agent.run("context", cwd=tmp_path, timeout=5.0)

    assert "timed out after 5.0 seconds" in str(exc_info.value)
    assert 88888 in killed_pids
