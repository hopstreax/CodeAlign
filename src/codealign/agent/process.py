"""Process execution and termination utilities for agent subprocesses."""

import os
import signal
import subprocess
import sys


def kill_process_tree(pid: int) -> None:
    """Safely terminate a process and its full subprocess tree on Windows and POSIX."""
    if not isinstance(pid, int) or pid <= 0:
        return

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
            target_pgid = os.getpgid(pid)
            caller_pgrp = os.getpgrp() if hasattr(os, "getpgrp") else os.getpid()
            if target_pgid != caller_pgrp and target_pgid > 0:
                os.killpg(target_pgid, signal.SIGTERM)
            else:
                # Target shares caller's process group: do not signal group
                os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            # Process has already exited
            pass
        except Exception:
            try:
                os.kill(pid, signal.SIGTERM)
            except Exception:
                pass
