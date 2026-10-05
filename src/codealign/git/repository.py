"""Git repository discovery and inspection utilities."""

import subprocess
from dataclasses import dataclass
from pathlib import Path


class GitError(Exception):
    """Base exception for Git operations."""


class NotAGitRepositoryError(GitError):
    """Raised when a target directory is not within a Git repository."""


@dataclass(frozen=True)
class GitRepoInfo:
    """Summary of Git repository state."""

    root: Path
    branch: str
    head_sha: str
    is_dirty: bool


def run_git_command(args: list[str], cwd: Path | None = None) -> str:
    """Execute a git command and return stripped stdout."""
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.strip()
        if "not a git repository" in stderr.lower():
            target = cwd or Path.cwd()
            raise NotAGitRepositoryError(f"'{target}' is not inside a Git repository.") from exc
        raise GitError(f"Git command failed (git {' '.join(args)}): {stderr}") from exc
    except FileNotFoundError as exc:
        raise GitError("Git executable ('git') was not found in PATH.") from exc


# Backwards compatibility alias
_run_git = run_git_command


def get_git_repo_info(path: Path | None = None) -> GitRepoInfo:
    """Discover Git repository details for the given path."""
    target = Path(path or ".").resolve()

    try:
        repo_root = Path(
            _run_git(
                ["rev-parse", "--show-toplevel"],
                cwd=target,
            )
        ).resolve()
    except GitError as exc:
        raise NotAGitRepositoryError(
            f"Not a Git repository: {target}"
        ) from exc

    branch = _run_git(
        ["branch", "--show-current"],
        cwd=repo_root,
    ) or "HEAD (detached)"

    head_sha = _run_git(
        ["rev-parse", "HEAD"],
        cwd=repo_root,
    )

    status = _run_git(
        ["status", "--porcelain"],
        cwd=repo_root,
    )

    return GitRepoInfo(
        root=repo_root,
        branch=branch,
        head_sha=head_sha,
        is_dirty=bool(status),
    )
