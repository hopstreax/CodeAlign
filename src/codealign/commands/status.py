"""Command: codealign status"""

import typer


def status_command() -> None:
    """Show current status of the implementation baseline and verification findings."""
    typer.echo("CodeAlign status: no active baseline found in repository (placeholder).")
