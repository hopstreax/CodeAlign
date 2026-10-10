"""Command: codealign init"""

from pathlib import Path

import typer

from codealign.config import init_codealign_state
from codealign.git.repository import GitError, NotAGitRepositoryError, get_git_repo_info
from codealign.graphify.client import (
    GraphifyError,
    find_graphify_executable,
    run_graphify_extraction,
)
from codealign.graphify.loader import load_and_validate_graph


def init_command(
    path: Path = typer.Option(
        Path("."),
        "--path",
        "-p",
        help="Target directory or repository path to initialize.",
        file_okay=False,
        dir_okay=True,
    ),
    force: bool = typer.Option(
        False,
        "--force",
        "-f",
        help="Re-initialize .codealign configuration and re-run Graphify extraction.",
    ),
    skip_graphify: bool = typer.Option(
        False,
        "--skip-graphify",
        help="Skip Graphify code intelligence extraction during initialization.",
    ),
) -> None:
    """Initialize CodeAlign in a Git repository and generate initial code intelligence."""
    # 1. Discover Git repository
    try:
        repo_info = get_git_repo_info(path)
    except NotAGitRepositoryError:
        typer.secho(
            f"Error: '{path.resolve()}' is not inside a Git repository. "
            "CodeAlign requires a Git repository.",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=1)
    except GitError as exc:
        typer.secho(f"Git error: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)

    # 2. Initialize .codealign directory and config.toml
    codealign_dir, newly_created = init_codealign_state(repo_info, force=force)

    if newly_created:
        typer.echo(f"Initialized CodeAlign in:\n{repo_info.root}\n")
    else:
        typer.echo(
            f"CodeAlign is already initialized in:\n{repo_info.root}\n"
            "(use --force to re-initialize)\n"
        )

    typer.echo("Repository:")
    typer.echo(f"  {repo_info.root.name}")
    typer.echo("Branch:")
    typer.echo(f"  {repo_info.branch}")
    typer.echo("HEAD:")
    typer.echo(f"  {repo_info.head_sha}")
    if repo_info.is_dirty:
        typer.echo("Working tree:")
        typer.echo("  dirty (uncommitted changes present)")

    # 3. Graphify code intelligence
    graph_file = codealign_dir / "graphify-out" / "graph.json"
    graphify_bin = find_graphify_executable()

    typer.echo("\nGraphify:")
    if not graphify_bin:
        typer.echo("  not available (CLI 'graphify' not found in PATH)")
        typer.echo("\nCode intelligence:")
        typer.echo("  unavailable (graph has not been generated)")
        typer.secho(
            "\nPrerequisite notice: Graphify is required to extract repository code intelligence.\n"
            "Install Graphify (e.g. 'pip install graphifyy') and ensure 'graphify' is on PATH,\n"
            "then rerun 'codealign init --force' to extract code intelligence.",
            fg=typer.colors.YELLOW,
        )
        return

    typer.echo("  available")

    if skip_graphify:
        typer.echo("\nCode intelligence:")
        typer.echo("  skipped (--skip-graphify specified)")
        return

    # If already initialized and not forced, reuse existing graph if present
    if not newly_created and not force and graph_file.is_file():
        validation = load_and_validate_graph(graph_file)
        if validation.is_valid:
            typer.echo("\nCode intelligence:")
            typer.echo(f"  {validation.node_count} nodes")
            typer.echo(f"  {validation.edge_count} relationships")
            return

    # Run Graphify extraction
    typer.echo("  extracting code intelligence (AST, no-cluster)...")
    try:
        extracted_graph_path = run_graphify_extraction(
            repo_root=repo_info.root,
            output_dir=codealign_dir,
            executable=graphify_bin,
        )
    except GraphifyError as exc:
        typer.secho(
            f"Warning: Graphify extraction failed: {exc}",
            fg=typer.colors.YELLOW,
            err=True,
        )
        typer.echo("\nCode intelligence:")
        typer.echo("  extraction failed")
        return

    validation = load_and_validate_graph(extracted_graph_path)
    typer.echo("\nCode intelligence:")
    if validation.is_valid:
        typer.echo(f"  {validation.node_count} nodes")
        typer.echo(f"  {validation.edge_count} relationships")
    else:
        typer.secho(
            f"  validation error: {validation.error_message}",
            fg=typer.colors.YELLOW,
        )
