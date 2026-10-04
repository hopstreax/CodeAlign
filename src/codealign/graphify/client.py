"""Graphify CLI client and process execution."""

import os
import shutil
import subprocess
from pathlib import Path


class GraphifyError(Exception):
    """Base exception for Graphify integration operations."""


class GraphifyNotFoundError(GraphifyError):
    """Raised when the graphify executable cannot be located."""


class GraphifyExecutionError(GraphifyError):
    """Raised when graphify fails during extraction execution."""


def find_graphify_executable() -> str | None:
    """Locate the graphify executable in PATH or via environment overrides."""
    env_bin = os.environ.get("GRAPHIFY_BIN")
    if env_bin and shutil.which(env_bin):
        return env_bin

    which_bin = shutil.which("graphify") or shutil.which("graphify.exe")
    if which_bin:
        return which_bin

    return None


def run_graphify_extraction(
    repo_root: Path,
    output_dir: Path,
    executable: str | None = None,
) -> Path:
    """Execute Graphify AST extraction on the target repository.

    Executes:
        graphify extract <repo_root> --code-only --no-cluster --out <output_dir>

    Configures GRAPHIFY_OUT environment variable pointing inside output_dir to
    prevent root-level graphify-out repository pollution.

    Returns:
        Path to the generated graph.json artifact.
    """
    exe = executable or find_graphify_executable()
    if not exe:
        raise GraphifyNotFoundError(
            "Graphify CLI was not found on PATH. "
            "Install Graphify or set GRAPHIFY_BIN environment variable."
        )

    target_graphify_out = output_dir / "graphify-out"
    target_graphify_out.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env["GRAPHIFY_OUT"] = str(target_graphify_out)

    cmd = [
        exe,
        "extract",
        str(repo_root),
        "--code-only",
        "--no-cluster",
        "--out",
        str(output_dir),
    ]

    try:
        result = subprocess.run(
            cmd,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
    except Exception as exc:
        raise GraphifyExecutionError(f"Failed to launch Graphify subprocess: {exc}") from exc

    if result.returncode != 0:
        error_details = (result.stderr or result.stdout or "").strip()
        raise GraphifyExecutionError(
            f"Graphify extraction failed with exit code {result.returncode}:\n{error_details}"
        )

    # Output should exist at <output_dir>/graphify-out/graph.json
    expected_graph = target_graphify_out / "graph.json"
    if not expected_graph.is_file():
        # Fallback check directly in output_dir
        direct_graph = output_dir / "graph.json"
        if direct_graph.is_file():
            return direct_graph
        raise GraphifyExecutionError(
            f"Graphify succeeded but did not produce graph.json at {expected_graph}"
        )

    return expected_graph
