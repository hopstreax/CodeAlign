"""Command: codealign baseline"""

from enum import Enum
from pathlib import Path

import typer

from codealign.analysis.graph_index import GraphIndex
from codealign.analysis.plan_parser import parse_plan_file
from codealign.analysis.resolver import resolve_plan
from codealign.baseline.generator import generate_baseline
from codealign.config import get_codealign_dir, load_config
from codealign.git.repository import GitError, NotAGitRepositoryError, get_git_repo_info


class OutputFormat(str, Enum):
    """Output format for baseline command."""

    TERMINAL = "terminal"
    JSON = "json"


def baseline_command(
    plan: Path | None = typer.Argument(
        None,
        help="Path to the developer's implementation plan file (e.g. plan.md).",
    ),
    format: OutputFormat = typer.Option(
        OutputFormat.TERMINAL,
        "--format",
        "-f",
        help="Output format: 'terminal' (summary) or 'json' (machine/agent-readable).",
    ),
    output: Path | None = typer.Option(
        None,
        "--output",
        "-o",
        help="Target file path for baseline artifact (defaults to .codealign/baseline.json).",
    ),
) -> None:
    """Generate an Implementation Baseline contract from the plan and repository evidence."""
    # 1. Determine plan path
    if plan is None:
        default_plan = Path("plan.md")
        if default_plan.is_file():
            plan = default_plan
        else:
            typer.secho(
                "Error: No implementation plan file specified and 'plan.md' was not found.\n"
                "Usage: codealign baseline <plan.md>",
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
        direct_graph = codealign_dir / "graph.json"
        alt_graph = codealign_dir / "graphify-out" / "graph.json"
        if direct_graph.is_file():
            graph_path = direct_graph
        elif alt_graph.is_file():
            graph_path = alt_graph
        else:
            typer.secho(
                f"Error: Code intelligence graph not found at '{graph_path}'.\n"
                "Code intelligence requires Graphify extraction. Ensure 'graphify' is installed\n"
                "and on PATH, then run 'codealign init --force' to generate the repository graph.",
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

    analysis_result = resolve_plan(parsed_plan, index)

    # 6. Generate Implementation Baseline
    baseline = generate_baseline(parsed_plan, analysis_result, repo_info=repo_info)

    # 7. Determine output path and write file
    target_output = output if output is not None else (codealign_dir / "baseline.json")
    try:
        baseline.write_to_file(target_output)
    except Exception as exc:
        typer.secho(f"Error writing baseline artifact: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)

    # Relative path display
    try:
        rel_output = target_output.relative_to(repo_info.root).as_posix()
    except ValueError:
        rel_output = str(target_output)

    # 8. Output to stdout
    if format == OutputFormat.JSON:
        typer.echo(baseline.to_json())
    else:
        typer.echo(baseline.format_terminal(output_path=rel_output))
