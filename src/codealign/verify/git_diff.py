"""Git diff and working tree change inspection for verification."""

from dataclasses import dataclass, field
from pathlib import Path

from codealign.git.repository import GitError, run_git_command


class BaseCommitNotFoundError(GitError):
    """Raised when the baseline commit does not exist in repository Git history."""


@dataclass
class GitChangeSet:
    """Deterministic snapshot of changes between baseline commit and current working tree."""

    base_commit: str
    modified: set[str] = field(default_factory=set)
    added: set[str] = field(default_factory=set)
    deleted: set[str] = field(default_factory=set)
    renamed: dict[str, str] = field(default_factory=dict)  # new_path -> old_path

    @property
    def all_changed_files(self) -> set[str]:
        """Return unified set of all changed (modified, added, deleted, renamed) file paths."""
        return self.modified | self.added | self.deleted | set(self.renamed.keys())


def _normalize_path(p: str) -> str:
    """Normalize file path to forward slashes."""
    return p.strip().replace("\\", "/").lstrip("./")


def get_git_changes(repo_root: Path, base_commit: str) -> GitChangeSet:
    """Inspect the repository and compute all changes relative to the baseline commit.

    Includes:
    - Tracked file modifications, additions, and deletions (committed, staged, or unstaged)
    - Untracked, non-ignored working tree files

    Args:
        repo_root: Path to repository root.
        base_commit: Baseline commit SHA to compare against.

    Returns:
        GitChangeSet with normalized paths.

    Raises:
        BaseCommitNotFoundError: If base_commit cannot be resolved in Git history.
        GitError: If underlying Git operations fail.
    """
    modified: set[str] = set()
    added: set[str] = set()
    deleted: set[str] = set()
    renamed: dict[str, str] = {}

    # 1. Validate that the baseline commit exists in Git history if specified
    if base_commit and base_commit != "uncommitted":
        try:
            run_git_command(["cat-file", "-e", f"{base_commit}^{{commit}}"], cwd=repo_root)
        except GitError as exc:
            raise BaseCommitNotFoundError(
                f"Baseline commit '{base_commit}' does not exist in current Git history."
            ) from exc

    # 2. Query diff of tracked files relative to base_commit
    # 'git diff --name-status <commit>' compares the commit tree directly to the working tree
    diff_args = (
        ["diff", "--name-status", base_commit]
        if (base_commit and base_commit != "uncommitted")
        else ["diff", "--name-status", "HEAD"]
    )
    try:
        diff_output = run_git_command(diff_args, cwd=repo_root)
    except GitError:
        # Fallback if HEAD does not exist (empty repo)
        diff_output = ""

    if diff_output:
        for line in diff_output.splitlines():
            parts = line.split("\t")
            if not parts or not parts[0]:
                continue
            status_code = parts[0][0].upper()
            if status_code in ("M", "T"):
                if len(parts) >= 2:
                    modified.add(_normalize_path(parts[1]))
            elif status_code == "A":
                if len(parts) >= 2:
                    added.add(_normalize_path(parts[1]))
            elif status_code == "D":
                if len(parts) >= 2:
                    deleted.add(_normalize_path(parts[1]))
            elif status_code == "R":
                if len(parts) >= 3:
                    old_path = _normalize_path(parts[1])
                    new_path = _normalize_path(parts[2])
                    renamed[new_path] = old_path
                    modified.add(new_path)

    # 3. Query untracked, non-ignored files in working tree
    try:
        untracked_output = run_git_command(
            ["ls-files", "--others", "--exclude-standard"],
            cwd=repo_root,
        )
    except GitError:
        untracked_output = ""

    if untracked_output:
        for line in untracked_output.splitlines():
            path_str = _normalize_path(line)
            if path_str:
                added.add(path_str)

    return GitChangeSet(
        base_commit=base_commit,
        modified=modified,
        added=added,
        deleted=deleted,
        renamed=renamed,
    )
