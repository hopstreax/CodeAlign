"""Unit tests for the GeminiAgent adapter."""

import subprocess
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from codealign.agent.gemini import (
    GeminiAgent,
    GeminiExecutionError,
    GeminiNotFoundError,
    GeminiResult,
)


def test_gemini_is_available_true(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify is_available returns True when gemini is on PATH."""
    monkeypatch.setattr("shutil.which", lambda cmd: "/usr/bin/gemini" if cmd == "gemini" else None)
    assert GeminiAgent.is_available() is True


def test_gemini_is_available_false(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify is_available returns False when gemini is not on PATH."""
    monkeypatch.setattr("shutil.which", lambda cmd: None)
    assert GeminiAgent.is_available() is False


def test_gemini_missing_executable_raises_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify accessing executable raises GeminiNotFoundError when not on PATH."""
    monkeypatch.setattr("shutil.which", lambda cmd: None)
    agent = GeminiAgent()
    with pytest.raises(GeminiNotFoundError) as exc_info:
        _ = agent.executable
    assert "Gemini CLI ('gemini') not found on PATH" in str(exc_info.value)


def test_gemini_explicit_executable() -> None:
    """Verify providing an explicit executable overrides PATH lookup."""
    agent = GeminiAgent(executable="/custom/path/to/gemini")
    assert agent.executable == "/custom/path/to/gemini"


def test_gemini_build_prompt() -> None:
    """Verify prompt formatting contains CodeAlign instructions and context markdown."""
    agent = GeminiAgent(executable="/bin/gemini")
    context_md = "# CodeAlign Implementation Context: Feature X\n\n- modify src/app.py"
    prompt = agent.build_prompt(context_md)

    assert "You are implementing planned repository changes guided by CodeAlign." in prompt
    assert "# CodeAlign Implementation Context: Feature X" in prompt
    assert "- modify src/app.py" in prompt
    assert "Do not commit or push your changes." in prompt


def test_gemini_build_command_default() -> None:
    """Verify default command uses auto_edit approval mode and --skip-trust."""
    agent = GeminiAgent(executable="/bin/gemini")
    cmd = agent.build_command("test prompt")

    assert cmd == [
        "/bin/gemini",
        "-p",
        "test prompt",
        "--approval-mode",
        "auto_edit",
        "--skip-trust",
    ]


def test_gemini_build_command_yolo() -> None:
    """Verify yolo flag is added when yolo=True."""
    agent = GeminiAgent(executable="/bin/gemini")
    cmd = agent.build_command("test prompt", yolo=True)

    assert cmd == [
        "/bin/gemini",
        "-p",
        "test prompt",
        "--yolo",
        "--skip-trust",
    ]


def test_gemini_build_command_custom_approval_mode() -> None:
    """Verify custom approval mode is passed."""
    agent = GeminiAgent(executable="/bin/gemini")
    cmd = agent.build_command("test prompt", approval_mode="plan")

    assert cmd == [
        "/bin/gemini",
        "-p",
        "test prompt",
        "--approval-mode",
        "plan",
        "--skip-trust",
    ]


def test_gemini_build_command_with_model() -> None:
    """Verify model flag is passed when specified."""
    agent = GeminiAgent(executable="/bin/gemini")
    cmd = agent.build_command("test prompt", model="gemini-2.5-pro")

    assert "--model" in cmd
    assert "gemini-2.5-pro" in cmd


def test_gemini_run_success(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify successful subprocess execution returns GeminiResult with success=True."""
    mock_run = MagicMock(
        return_value=subprocess.CompletedProcess(
            args=["/bin/gemini"],
            returncode=0,
            stdout="Implemented files successfully.",
            stderr="",
        )
    )
    monkeypatch.setattr("subprocess.run", mock_run)

    agent = GeminiAgent(executable="/bin/gemini")
    result = agent.run(
        context_markdown="context",
        cwd=tmp_path,
        approval_mode="auto_edit",
    )

    assert isinstance(result, GeminiResult)
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


def test_gemini_run_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify subprocess non-zero exit code returns GeminiResult with success=False."""
    mock_run = MagicMock(
        return_value=subprocess.CompletedProcess(
            args=["/bin/gemini"],
            returncode=1,
            stdout="",
            stderr="Authentication required.",
        )
    )
    monkeypatch.setattr("subprocess.run", mock_run)

    agent = GeminiAgent(executable="/bin/gemini")
    result = agent.run(
        context_markdown="context",
        cwd=tmp_path,
    )

    assert result.success is False
    assert result.exit_code == 1
    assert "Authentication required." in result.stderr


def test_gemini_run_timeout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify TimeoutExpired raises GeminiExecutionError."""
    def fake_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=args[0], timeout=10.0)

    monkeypatch.setattr("subprocess.run", fake_run)

    agent = GeminiAgent(executable="/bin/gemini")
    with pytest.raises(GeminiExecutionError) as exc_info:
        agent.run("context", cwd=tmp_path, timeout=10.0)

    assert "timed out after 10.0 seconds" in str(exc_info.value)


def test_gemini_run_unexpected_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify unexpected OSError raises GeminiExecutionError."""
    def fake_run(*args, **kwargs):
        raise OSError("Permission denied")

    monkeypatch.setattr("subprocess.run", fake_run)

    agent = GeminiAgent(executable="/bin/gemini")
    with pytest.raises(GeminiExecutionError) as exc_info:
        agent.run("context", cwd=tmp_path)

    assert "Failed to execute Gemini CLI: Permission denied" in str(exc_info.value)


def test_gemini_run_timeout_kills_process_tree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify GeminiAgent invokes kill_process_tree when process times out."""
    killed_pids: list[int] = []
    monkeypatch.setattr(
        "codealign.agent.gemini.kill_process_tree",
        lambda pid: killed_pids.append(pid),
    )

    class FakePopen:
        pid = 99999
        returncode = None

        def __init__(self, *args, **kwargs):
            pass

        def communicate(self, timeout=None):
            raise subprocess.TimeoutExpired(cmd=["gemini"], timeout=5.0)

        def poll(self):
            return None

    monkeypatch.setattr("subprocess.Popen", FakePopen)

    agent = GeminiAgent(executable="/bin/gemini")
    with pytest.raises(GeminiExecutionError) as exc_info:
        agent.run("context", cwd=tmp_path, timeout=5.0)

    assert "timed out after 5.0 seconds" in str(exc_info.value)
    assert 99999 in killed_pids
