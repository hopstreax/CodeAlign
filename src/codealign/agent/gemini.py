"""Gemini CLI agent adapter for CodeAlign."""

import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path


class GeminiError(Exception):
    """Base exception for Gemini CLI agent operations."""


class GeminiNotFoundError(GeminiError):
    """Raised when the Gemini CLI executable is not found on PATH."""


class GeminiExecutionError(GeminiError):
    """Raised when invocation of the Gemini CLI fails unexpectedly."""

    def __init__(self, message: str, command: list[str] | None = None) -> None:
        super().__init__(message)
        self.command = command or []


@dataclass(frozen=True)
class GeminiResult:
    """Outcome of invoking the Gemini CLI."""

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


class GeminiAgent:
    """Agent interface to invoke the user's local Gemini CLI."""

    def __init__(self, executable: str | None = None) -> None:
        self._executable = executable

    @property
    def executable(self) -> str:
        """Resolve the Gemini CLI executable path on PATH."""
        exe = self._executable or self.find_executable()
        if not exe:
            raise GeminiNotFoundError(
                "Gemini CLI ('gemini') not found on PATH. "
                "Please install and authenticate Gemini CLI before running 'codealign implement'."
            )
        return exe

    @classmethod
    def find_executable(cls) -> str | None:
        """Locate the Gemini CLI executable on PATH."""
        return shutil.which("gemini")

    @classmethod
    def is_available(cls) -> bool:
        """Check whether the Gemini CLI is available on PATH."""
        return cls.find_executable() is not None

    def build_prompt(self, context_markdown: str) -> str:
        """Construct the prompt delivering CodeAlign implementation context to Gemini."""
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
        approval_mode: str = "auto_edit",
        yolo: bool = False,
        model: str | None = None,
    ) -> list[str]:
        """Construct the Gemini CLI argument list."""
        cmd = [self.executable, "-p", prompt]
        if yolo:
            cmd.append("--yolo")
        else:
            cmd.extend(["--approval-mode", approval_mode])
        cmd.append("--skip-trust")
        if model:
            cmd.extend(["--model", model])
        return cmd

    def run(
        self,
        context_markdown: str,
        cwd: Path,
        approval_mode: str = "auto_edit",
        yolo: bool = False,
        model: str | None = None,
        timeout: float | None = None,
    ) -> GeminiResult:
        """Invoke Gemini CLI with implementation context in the specified repository working tree."""
        prompt = self.build_prompt(context_markdown)
        cmd = self.build_command(
            prompt,
            approval_mode=approval_mode,
            yolo=yolo,
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
            return GeminiResult(
                success=(process.returncode == 0),
                exit_code=process.returncode,
                stdout=process.stdout,
                stderr=process.stderr,
                command=cmd,
            )
        except subprocess.TimeoutExpired as exc:
            raise GeminiExecutionError(
                f"Gemini CLI timed out after {timeout} seconds.",
                command=cmd,
            ) from exc
        except Exception as exc:
            raise GeminiExecutionError(
                f"Failed to execute Gemini CLI: {exc}",
                command=cmd,
            ) from exc
