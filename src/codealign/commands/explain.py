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
    """Explain verification findings and provide evidence-backed guidance (preview placeholder)."""
    typer.echo(
        "CodeAlign explain: [Preview] This command is currently an experimental placeholder. "
        "Detailed finding explanations and remedies are planned for a future release."
    )
