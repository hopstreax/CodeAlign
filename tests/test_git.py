"""Unit tests for Git repository discovery."""

from pathlib import Path

import pytest

from codealign.git.repository import (
    GitRepoInfo,
    NotAGitRepositoryError,
    get_git_repo_info,
)


def test_get_git_repo_info_current_repo() -> None:
    """Verify Git repository inspection succeeds on the active CodeAlign repository."""
    info = get_git_repo_info()
    assert isinstance(info, GitRepoInfo)
    assert info.root.is_dir()
    assert info.root.name.lower() == "codealign"
    assert info.branch != ""
    assert len(info.head_sha) == 40 or info.head_sha == "uncommitted"


def test_get_git_repo_info_non_git_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify NotAGitRepositoryError is raised for a directory outside any Git repo."""
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))
    with pytest.raises(NotAGitRepositoryError):
        get_git_repo_info(tmp_path)
