"""Command: codealign verify"""

from enum import Enum
from pathlib import Path

import typer


class OutputFormat(str, Enum):
    """Output format for verification results."""

    TERMINAL = "terminal"
    JSON = "json"


def verify_command(
    baseline: Path = typer.Option(
        Path(".codealign/baseline.json"),
        "--baseline",
        "-b",
        help="Path to the baseline contract file.",
    ),
    format: OutputFormat = typer.Option(
        OutputFormat.TERMINAL,
        "--format",
        "-f",
        help="Output format: 'terminal' (human-readable) or 'json' (machine/agent-readable).",
    ),
    strict: bool = typer.Option(
        False,
        "--strict",
        help="Treat warnings as verification failures.",
    ),
) -> None:
    """Verify actual code changes against the implementation baseline and code graph."""
    if format == OutputFormat.JSON:
        typer.echo(
            '{"status": "placeholder", "findings": [], '
            '"message": "Verification not implemented yet"}'
        )
    else:
        typer.echo(
            "CodeAlign verify: verifying implementation changes against baseline (placeholder)."
        )
