"""Verification result models."""

import json
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from codealign.models.finding import Finding, FindingSeverity


class VerificationStatus(str, Enum):
    """Overall outcome of a verification run."""

    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"


class VerificationResult(BaseModel):
    """The outcome of verifying actual changes against the implementation baseline."""

    status: VerificationStatus = Field(description="Overall verification status")
    summary: str = Field(default="", description="High-level summary of verification results")
    findings: list[Finding] = Field(
        default_factory=list,
        description="List of specific findings and discrepancies discovered",
    )

    @property
    def failures(self) -> list[Finding]:
        """Return all findings with ERROR severity (failures)."""
        return [f for f in self.findings if f.severity == FindingSeverity.ERROR]

    @property
    def warnings(self) -> list[Finding]:
        """Return all findings with WARN severity."""
        return [f for f in self.findings if f.severity == FindingSeverity.WARN]

    @property
    def passes(self) -> list[Finding]:
        """Return all confirmed pass findings."""
        return [f for f in self.findings if f.severity == FindingSeverity.PASS]

    def to_dict(self) -> dict[str, Any]:
        """Convert verification result to dictionary representation."""
        return {
            "status": self.status.value,
            "summary": self.summary,
            "counts": {
                "passes": len(self.passes),
                "warnings": len(self.warnings),
                "failures": len(self.failures),
                "total": len(self.findings),
            },
            "findings": [f.to_dict() for f in self.findings],
        }

    def to_json(self, indent: int = 2) -> str:
        """Convert verification result to deterministic JSON."""
        return json.dumps(self.to_dict(), indent=indent, sort_keys=False)
