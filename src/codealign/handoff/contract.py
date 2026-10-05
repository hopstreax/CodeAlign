"""Agent Handoff Contract.

Defines the boundary and payload for handing off CodeAlign's trusted
implementation context and baseline to external coding agents.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from codealign.config import get_codealign_dir
from codealign.context.exporter import export_agent_context
from codealign.models.baseline import (
    BaselineEvidence,
    BaselineExpectations,
    BaselineIntent,
    BaselineRepositoryInfo,
    ImplementationBaseline,
)


class BaselineNotFoundError(FileNotFoundError):
    """Raised when the baseline contract does not exist on disk."""


@dataclass(frozen=True)
class AgentHandoffPayload:
    """The canonical handoff payload delivered to an external implementation agent.

    This payload combines:
    1. The canonical ImplementationBaseline contract (machine-readable ground truth).
    2. The agent-consumable Markdown context (transport/presentation format).
    """

    baseline: ImplementationBaseline
    context_markdown: str

    @property
    def intent(self) -> BaselineIntent:
        """Original developer intent from implementation plan."""
        return self.baseline.intent

    @property
    def repository(self) -> BaselineRepositoryInfo:
        """Repository identity and commit snapshot at baseline creation."""
        return self.baseline.repository

    @property
    def expectations(self) -> BaselineExpectations:
        """Expected files, symbols, tests, and relationships."""
        return self.baseline.expectations

    @property
    def evidence(self) -> BaselineEvidence:
        """Resolved and unresolved codebase evidence."""
        return self.baseline.evidence

    @property
    def constraints(self) -> list[str]:
        """Architectural constraints specified by developer."""
        return self.baseline.constraints

    def to_dict(self) -> dict[str, Any]:
        """Return machine-readable representation of handoff payload."""
        return {
            "baseline": self.baseline.to_dict(),
            "context_markdown": self.context_markdown,
        }


def prepare_agent_handoff(
    repo_root: Path,
    baseline_path: Path | None = None,
) -> AgentHandoffPayload:
    """Prepare the agent handoff contract from the repository baseline.

    Guarantees:
    - Non-mutation: does not modify baseline.json, source files, or git state.
    - No re-analysis: strictly consumes existing baseline without rerunning Graphify.
    - Determinism: produces identical context across repeated invocations.
    - Preserves uncertainty: unresolved references remain explicit and unhidden.

    Args:
        repo_root: The root directory of the target repository.
        baseline_path: Optional explicit path to baseline.json. If None, defaults to
            .codealign/baseline.json within repo_root.

    Returns:
        AgentHandoffPayload containing the baseline and generated Markdown context.

    Raises:
        BaselineNotFoundError: If the baseline file does not exist.
    """
    codealign_dir = get_codealign_dir(repo_root)
    resolved_path = baseline_path or (codealign_dir / "baseline.json")

    if not resolved_path.is_file():
        raise BaselineNotFoundError(
            f"Baseline contract not found at '{resolved_path}'. "
            "Run 'codealign baseline <plan.md>' first to generate the implementation baseline."
        )

    baseline = ImplementationBaseline.from_file(resolved_path)
    context_md = export_agent_context(baseline)

    return AgentHandoffPayload(
        baseline=baseline,
        context_markdown=context_md,
    )
