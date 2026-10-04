"""CodeAlign local state directory and configuration management."""

import tomllib
from datetime import datetime, timezone
from pathlib import Path

from codealign.git.repository import GitRepoInfo

CODEALIGN_DIR_NAME = ".codealign"
CONFIG_FILE_NAME = "config.toml"


def get_codealign_dir(repo_root: Path) -> Path:
    """Return the absolute path to .codealign within the repository root."""
    return repo_root / CODEALIGN_DIR_NAME


def get_config_path(repo_root: Path) -> Path:
    """Return the path to config.toml within .codealign."""
    return get_codealign_dir(repo_root) / CONFIG_FILE_NAME


def is_initialized(repo_root: Path) -> bool:
    """Check if .codealign directory and config.toml exist."""
    return get_config_path(repo_root).is_file()


def init_codealign_state(
    repo_info: GitRepoInfo,
    force: bool = False,
) -> tuple[Path, bool]:
    """Initialize .codealign directory and config.toml.

    Returns:
        tuple of (codealign_dir_path, is_newly_created)
    """
    codealign_dir = get_codealign_dir(repo_info.root)
    config_file = codealign_dir / CONFIG_FILE_NAME

    if config_file.exists() and not force:
        return codealign_dir, False

    codealign_dir.mkdir(parents=True, exist_ok=True)

    repo_name = repo_info.root.name
    now_iso = datetime.now(timezone.utc).isoformat()
    # Normalize path to forward slashes for cross-platform TOML portability
    root_str = repo_info.root.as_posix()

    config_content = f"""# CodeAlign project configuration

[repository]
name = "{repo_name}"
root = "{root_str}"
initialized_at = "{now_iso}"

[git]
initial_branch = "{repo_info.branch}"
initial_commit = "{repo_info.head_sha}"

[graphify]
output_dir = "graphify-out"
graph_file = "graphify-out/graph.json"
"""

    config_file.write_text(config_content, encoding="utf-8")
    return codealign_dir, True


def load_config(codealign_dir: Path) -> dict:
    """Read and parse .codealign/config.toml."""
    config_file = codealign_dir / CONFIG_FILE_NAME
    if not config_file.exists():
        raise FileNotFoundError(f"Configuration file not found at {config_file}")
    with open(config_file, "rb") as f:
        return tomllib.load(f)
