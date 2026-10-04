"""Command: codealign context"""

from enum import Enum
from pathlib import Path

import typer


class ContextFormat(str, Enum):
    """Output format for agent context."""

    JSON = "json"
    MARKDOWN = "markdown"


def context_command(
    baseline: Path = typer.Option(
        Path(".codealign/baseline.json"),
        "--baseline",
        "-b",
        help="Path to the baseline contract file.",
    ),
    format: ContextFormat = typer.Option(
        ContextFormat.JSON,
        "--format",
        "-f",
        help="Output format: 'json' (machine/agent-readable) or 'markdown' (prompt-ready).",
    ),
) -> None:
    """Export baseline and repository context formatted for coding agent consumption."""
    if format == ContextFormat.JSON:
        typer.echo('{"baseline": null, "message": "Context export placeholder"}')
    else:
        typer.echo("# CodeAlign Agent Handoff Context (placeholder)")
