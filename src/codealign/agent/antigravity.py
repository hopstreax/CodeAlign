"""Antigravity CLI agent adapter for CodeAlign."""

import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path


class AntigravityError(Exception):
    """Base exception for Antigravity CLI agent operations."""


class AntigravityNotFoundError(AntigravityError):
    """Raised when the Antigravity CLI executable is not found on PATH."""


class AntigravityExecutionError(AntigravityError):
    """Raised when invocation of the Antigravity CLI fails unexpectedly."""

    def __init__(self, message: str, command: list[str] | None = None) -> None:
        super().__init__(message)
        self.command = command or []


@dataclass(frozen=True)
class AntigravityResult:
    """Outcome of invoking the Antigravity CLI."""

    success: bool
    exit_code: int
    stdout: str = ""
    stderr: str = ""
    command: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Convert result to dictionary for serialization."""
        return {
            "success": self.success,
            "exit_code": self.exit_code,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "command": self.command,
        }


class AntigravityAgent:
    """Agent interface to invoke the user's local Antigravity CLI."""

    def __init__(self, executable: str | None = None) -> None:
        self._executable = executable

    @property
    def executable(self) -> str:
        """Resolve the Antigravity CLI executable path on PATH."""
        exe = self._executable or self.find_executable()
        if not exe:
            raise AntigravityNotFoundError(
                "Antigravity CLI ('agy' or 'antigravity') not found on PATH. "
                "Please install and configure Antigravity CLI before running 'codealign implement'."
            )
        return exe

    @classmethod
    def find_executable(cls) -> str | None:
        """Locate the Antigravity CLI executable on PATH.

        Prefers 'agy' and falls back to 'antigravity'.
        """
        return shutil.which("agy") or shutil.which("antigravity")

    @classmethod
    def is_available(cls) -> bool:
        """Check whether the Antigravity CLI is available on PATH."""
        return cls.find_executable() is not None

    def build_prompt(self, context_markdown: str) -> str:
        """Construct the prompt delivering CodeAlign implementation context to Antigravity."""
        return (
            "You are implementing planned repository changes guided by CodeAlign.\n\n"
            "Follow the implementation context below carefully. Modify and create only "
            "the expected files, symbols, and tests as described.\n"
            "Do not commit or push your changes.\n\n"
            "----------------------------------------\n"
            f"{context_markdown.strip()}\n"
            "----------------------------------------\n"
        )

    def build_command(
        self,
        prompt: str,
        mode: str = "accept-edits",
        dangerously_skip_permissions: bool = False,
        model: str | None = None,
    ) -> list[str]:
        """Construct the Antigravity CLI argument list."""
        cmd = [self.executable, "-p", prompt]
        if mode:
            cmd.extend(["--mode", mode])
        if dangerously_skip_permissions:
            cmd.append("--dangerously-skip-permissions")
        if model:
            cmd.extend(["--model", model])
        return cmd

    def run(
        self,
        context_markdown: str,
        cwd: Path,
        mode: str = "accept-edits",
        dangerously_skip_permissions: bool = False,
        model: str | None = None,
        timeout: float | None = None,
    ) -> AntigravityResult:
        """Invoke Antigravity CLI with implementation context in the repository working tree."""
        prompt = self.build_prompt(context_markdown)
        cmd = self.build_command(
            prompt,
            mode=mode,
            dangerously_skip_permissions=dangerously_skip_permissions,
            model=model,
        )
        try:
            process = subprocess.run(
                cmd,
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            return AntigravityResult(
                success=(process.returncode == 0),
                exit_code=process.returncode,
                stdout=process.stdout,
                stderr=process.stderr,
                command=cmd,
            )
        except subprocess.TimeoutExpired as exc:
            raise AntigravityExecutionError(
                f"Antigravity CLI timed out after {timeout} seconds.",
                command=cmd,
            ) from exc
        except Exception as exc:
            raise AntigravityExecutionError(
                f"Failed to execute Antigravity CLI: {exc}",
                command=cmd,
            ) from exc
