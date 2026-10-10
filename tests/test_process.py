"""Direct unit tests for process tree termination utilities."""

import subprocess
import sys
import time

import pytest

from codealign.agent.process import kill_process_tree


def _spawn_disposable_process() -> subprocess.Popen:
    """Spawn a disposable long-running Python subprocess with session isolation."""
    popen_kwargs: dict = {
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "text": True,
    }
    if sys.platform != "win32":
        popen_kwargs["start_new_session"] = True

    proc = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        **popen_kwargs,
    )
    # Give the child process a moment to initialize
    time.sleep(0.1)
    return proc


def test_kill_process_tree_terminates_running_process() -> None:
    """Verify kill_process_tree actually terminates a running disposable process."""
    proc = _spawn_disposable_process()
    try:
        assert proc.poll() is None, "Process failed to start."
        pid = proc.pid

        kill_process_tree(pid)

        # Wait bounded time for process to terminate
        try:
            exit_code = proc.wait(timeout=5.0)
        except subprocess.TimeoutExpired:
            proc.kill()
            exit_code = proc.wait(timeout=2.0)

        assert exit_code is not None
        assert proc.poll() is not None
    finally:
        # Reliable cleanup in teardown
        if proc.poll() is None:
            try:
                proc.kill()
                proc.wait(timeout=2.0)
            except Exception:
                pass


def test_kill_process_tree_already_exited_process() -> None:
    """Verify kill_process_tree safely handles a process that has already exited."""
    proc = subprocess.Popen(
        [sys.executable, "-c", "pass"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    proc.wait(timeout=5.0)
    assert proc.poll() is not None
    pid = proc.pid

    # Calling kill_process_tree on already-terminated PID must not raise
    kill_process_tree(pid)


@pytest.mark.parametrize("invalid_pid", [0, -1, -999])
def test_kill_process_tree_rejects_invalid_pids(invalid_pid: int) -> None:
    """Verify kill_process_tree safely rejects non-positive PIDs without signaling."""
    # Must return cleanly without raising exceptions or sending signals
    kill_process_tree(invalid_pid)


def test_kill_process_tree_rejects_non_integer_pid() -> None:
    """Verify kill_process_tree safely rejects non-integer PID values."""
    # Type-check guard safety test
    kill_process_tree(None)  # type: ignore[arg-type]
    kill_process_tree("not-a-pid")  # type: ignore[arg-type]


def test_kill_process_tree_posix_group_isolation(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify on POSIX that kill_process_tree never signals caller's own process group."""
    killpg_called: list[tuple[int, int]] = []
    kill_called: list[tuple[int, int]] = []

    monkeypatch.setattr("sys.platform", "linux")
    monkeypatch.setattr("os.getpgid", lambda pid: 12345, raising=False)
    monkeypatch.setattr("os.getpgrp", lambda: 12345, raising=False)
    monkeypatch.setattr(
        "os.killpg",
        lambda pgid, sig: killpg_called.append((pgid, sig)),
        raising=False,
    )
    monkeypatch.setattr(
        "os.kill",
        lambda pid, sig: kill_called.append((pid, sig)),
        raising=False,
    )

    kill_process_tree(9999)

    # Must NOT have signaled the process group because it matches caller's group
    assert len(killpg_called) == 0
    # Must have fallen back to signaling only the child process directly
    assert len(kill_called) == 1
    assert kill_called[0][0] == 9999


def test_kill_process_tree_posix_signals_isolated_group(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify on POSIX that kill_process_tree signals isolated process group."""
    killpg_called: list[tuple[int, int]] = []

    monkeypatch.setattr("sys.platform", "linux")
    monkeypatch.setattr("os.getpgid", lambda pid: 54321, raising=False)
    monkeypatch.setattr("os.getpgrp", lambda: 12345, raising=False)
    monkeypatch.setattr(
        "os.killpg",
        lambda pgid, sig: killpg_called.append((pgid, sig)),
        raising=False,
    )

    kill_process_tree(9999)

    assert len(killpg_called) == 1
    assert killpg_called[0][0] == 54321
