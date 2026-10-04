"""Command: codealign analyze"""

from enum import Enum
from pathlib import Path

import typer

from codealign.analysis.graph_index import GraphIndex
from codealign.analysis.plan_parser import parse_plan_file
from codealign.analysis.resolver import resolve_plan
from codealign.config import get_codealign_dir, load_config
from codealign.git.repository import GitError, NotAGitRepositoryError, get_git_repo_info


class OutputFormat(str, Enum):
    """Output format for analysis results."""

    TERMINAL = "terminal"
    JSON = "json"


def analyze_command(
    plan: Path | None = typer.Argument(
        None,
        help="Path to the developer's implementation plan file (e.g. plan.md).",
    ),
    format: OutputFormat = typer.Option(
        OutputFormat.TERMINAL,
        "--format",
        "-f",
        help="Output format: 'terminal' (human-readable) or 'json' (machine/agent-readable).",
    ),
) -> None:
    """Analyze a developer implementation plan and resolve repository evidence against Graphify."""
    # 1. Determine plan path
    if plan is None:
        default_plan = Path("plan.md")
        if default_plan.is_file():
            plan = default_plan
        else:
            typer.secho(
                "Error: No implementation plan file specified and 'plan.md' was not found.\n"
                "Usage: codealign analyze <plan.md>",
                fg=typer.colors.RED,
                err=True,
            )
            raise typer.Exit(code=1)

    if not plan.is_file():
        typer.secho(
            f"Error: Implementation plan file not found: {plan}",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=1)

    # 2. Locate repository root and .codealign state
    try:
        repo_info = get_git_repo_info()
    except (NotAGitRepositoryError, GitError) as exc:
        typer.secho(f"Error: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)

    codealign_dir = get_codealign_dir(repo_info.root)
    if not codealign_dir.is_dir():
        typer.secho(
            f"Error: CodeAlign is not initialized in '{repo_info.root}'.\n"
            "Run 'codealign init' first to generate code intelligence.",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=1)

    # 3. Locate graph.json
    try:
        config = load_config(codealign_dir)
        graph_rel = config.get("graphify", {}).get("graph_file", "graphify-out/graph.json")
    except Exception:
        graph_rel = "graphify-out/graph.json"

    graph_path = codealign_dir / graph_rel
    if not graph_path.is_file():
        typer.secho(
            f"Error: Code intelligence graph not found at '{graph_path}'.\n"
            "Run 'codealign init' to extract code intelligence from the repository.",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=1)

    # 4. Parse plan markdown
    try:
        parsed_plan = parse_plan_file(plan)
    except Exception as exc:
        typer.secho(f"Error reading plan file: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)

    # 5. Load GraphIndex and resolve references
    try:
        index = GraphIndex.from_file(graph_path)
    except Exception as exc:
        typer.secho(
            f"Error loading code intelligence graph: {exc}",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=1)

    result = resolve_plan(parsed_plan, index)

    # 6. Output formatted result
    if format == OutputFormat.JSON:
        typer.echo(result.to_json())
    else:
        typer.echo(result.format_terminal())
