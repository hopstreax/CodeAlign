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
    """Discover Git repository details for the given path.

    Resolves:
    - Repository root path
    - Current branch name (or detached head indicator)
    - HEAD commit SHA (or 'uncommitted' for empty repositories)
    - Working tree cleanliness (dirty/clean)
    """
    target = path.resolve() if path else Path.cwd().resolve()

    # 1. Discover repository root
    root_str = _run_git(["rev-parse", "--show-toplevel"], cwd=target)
    root = Path(root_str).resolve()

    # 2. Discover current branch
    branch = _run_git(["branch", "--show-current"], cwd=root)
    if not branch:
        try:
            short_head = _run_git(["rev-parse", "--short", "HEAD"], cwd=root)
            branch = f"detached:{short_head}"
        except GitError:
            branch = "main"

    # 3. Discover HEAD commit SHA
    try:
        head_sha = _run_git(["rev-parse", "HEAD"], cwd=root)
    except GitError:
        head_sha = "uncommitted"

    # 4. Check whether working tree has changes
    status_output = _run_git(["status", "--porcelain"], cwd=root)
    is_dirty = bool(status_output.strip())

    return GitRepoInfo(
        root=root,
        branch=branch,
        head_sha=head_sha,
        is_dirty=is_dirty,
    )
