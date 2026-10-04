"""Command: codealign explain"""

import typer


def explain_command(
    finding_id: str | None = typer.Option(
        None,
        "--finding-id",
        "-i",
        help="Optional specific finding ID or category to explain.",
    ),
) -> None:
    """Explain verification findings and provide evidence-backed guidance for resolution."""
    typer.echo("CodeAlign explain: explaining verification findings and remedies (placeholder).")
