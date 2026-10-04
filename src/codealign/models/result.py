"""Verification result models."""

from enum import Enum

from pydantic import BaseModel, Field

from codealign.models.finding import Finding


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
