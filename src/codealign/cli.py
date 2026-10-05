"""CodeAlign CLI entry point."""

import typer

from codealign import __version__
from codealign.commands import (
    analyze_command,
    baseline_command,
    context_command,
    explain_command,
    implement_command,
    init_command,
    status_command,
    verify_command,
)


app = typer.Typer(
    name="codealign",
    help="CodeAlign: Keep implementations aligned with developer intent.",
    no_args_is_help=True,
    add_completion=False,
)


def version_callback(value: bool) -> None:
    if value:
        typer.echo(f"CodeAlign version {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(
        None,
        "--version",
        "-v",
        help="Show CodeAlign version and exit.",
        callback=version_callback,
        is_eager=True,
    ),
) -> None:
    """CodeAlign: Keep implementations aligned with developer intent."""


app.command(
    name="init",
    help="Initialize CodeAlign configuration and state directory (.codealign/) in the repository.",
)(init_command)

app.command(
    name="analyze",
    help="Analyze codebase and plan to discover code structure, symbols, and impact.",
)(analyze_command)

app.command(
    name="baseline",
    help="Generate an Implementation Baseline contract from the plan and code graph.",
)(baseline_command)

app.command(
    name="verify",
    help="Verify actual code changes against the implementation baseline and code graph.",
)(verify_command)

app.command(
    name="status",
    help="Show current status of the implementation baseline and verification findings.",
)(status_command)

app.command(
    name="context",
    help="Export baseline and repository context formatted for coding agent consumption.",
)(context_command)

app.command(
    name="explain",
    help="Explain verification findings and provide evidence-backed guidance for resolution.",
)(explain_command)

app.command(
    name="implement",
    help="Hand off implementation baseline to Gemini CLI and verify resulting changes.",
)(implement_command)


if __name__ == "__main__":
    app()
