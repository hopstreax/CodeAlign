"""Command: codealign init"""

from pathlib import Path

import typer


def init_command(
    path: Path = typer.Option(
        Path("."),
        "--path",
        "-p",
        help="Target repository path to initialize.",
        exists=True,
        file_okay=False,
        dir_okay=True,
    ),
    force: bool = typer.Option(
        False,
        "--force",
        "-f",
        help="Overwrite existing .codealign directory if it exists.",
    ),
) -> None:
    """Initialize CodeAlign configuration and state directory (.codealign/) in the repository."""
    typer.echo(f"CodeAlign init: preparing runtime environment at '{path}' (placeholder).")
