"""Command: codealign baseline"""

from pathlib import Path

import typer


def baseline_command(
    plan: Path | None = typer.Option(
        None,
        "--plan",
        "-p",
        help="Path to the developer's implementation plan file.",
        exists=True,
        dir_okay=False,
    ),
    output: Path = typer.Option(
        Path(".codealign/baseline.json"),
        "--output",
        "-o",
        help="Target file path for the generated baseline artifact.",
    ),
) -> None:
    """Generate an Implementation Baseline contract from the plan and codebase graph."""
    typer.echo(
        f"CodeAlign baseline: generating baseline at '{output}' (placeholder)."
    )
