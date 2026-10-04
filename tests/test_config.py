"""Unit tests for CodeAlign state and configuration management."""

from pathlib import Path

from codealign.config import (
    get_config_path,
    init_codealign_state,
    is_initialized,
    load_config,
)
from codealign.git.repository import GitRepoInfo


def test_init_codealign_state(tmp_path: Path) -> None:
    """Verify initialization creates .codealign directory and config.toml."""
    repo_info = GitRepoInfo(
        root=tmp_path,
        branch="feature/test",
        head_sha="abcdef1234567890",
        is_dirty=False,
    )

    assert not is_initialized(tmp_path)

    codealign_dir, newly_created = init_codealign_state(repo_info)
    assert newly_created is True
    assert codealign_dir == tmp_path / ".codealign"
    assert is_initialized(tmp_path)

    config = load_config(codealign_dir)
    assert config["repository"]["name"] == tmp_path.name
    assert config["git"]["initial_branch"] == "feature/test"
    assert config["git"]["initial_commit"] == "abcdef1234567890"
    assert config["graphify"]["graph_file"] == "graphify-out/graph.json"


def test_repeated_init_preserves_existing(tmp_path: Path) -> None:
    """Verify repeated initialization without force does not overwrite existing config."""
    repo_info = GitRepoInfo(
        root=tmp_path,
        branch="main",
        head_sha="1111111111111111",
        is_dirty=False,
    )
    codealign_dir, newly_created = init_codealign_state(repo_info)
    assert newly_created is True

    # Mutate the file to verify it doesn't get overwritten
    config_path = get_config_path(tmp_path)
    config_path.write_text("# custom modification", encoding="utf-8")

    # Second init without force
    _, newly_created_2 = init_codealign_state(repo_info, force=False)
    assert newly_created_2 is False
    assert config_path.read_text(encoding="utf-8") == "# custom modification"

    # Third init with force
    _, newly_created_3 = init_codealign_state(repo_info, force=True)
    assert newly_created_3 is True
    assert "[repository]" in config_path.read_text(encoding="utf-8")
