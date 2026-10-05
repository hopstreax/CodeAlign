"""Verification finding models."""

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class FindingSeverity(str, Enum):
    """Severity of a verification finding."""

    PASS = "pass"
    INFO = "info"
    WARN = "warn"
    ERROR = "error"


class FindingCategory(str, Enum):
    """Category of implementation drift or discrepancy."""

    SCOPE_DRIFT = "scope_drift"
    MISSING_IMPLEMENTATION = "missing_implementation"
    ARCHITECTURE_DRIFT = "architecture_drift"
    DEPENDENCY_DRIFT = "dependency_drift"
    TEST_DRIFT = "test_drift"
    ABSTRACTION_DRIFT = "abstraction_drift"
    BEHAVIORAL_DRIFT = "behavioral_drift"
    REPOSITORY_BINDING = "repository_binding"
    UNRESOLVED_REFERENCE = "unresolved_reference"
    CONSTRAINT_VIOLATION = "constraint_violation"


class Finding(BaseModel):
    """An individual discrepancy or confirmation found during verification."""

    category: FindingCategory = Field(description="Category of the finding")
    severity: FindingSeverity = Field(
        default=FindingSeverity.WARN, description="Severity level of the finding"
    )
    message: str = Field(description="Human-readable explanation of the discrepancy")
    file_path: str | None = Field(default=None, description="Affected file path if applicable")
    symbol: str | None = Field(default=None, description="Affected symbol name if applicable")
    expected: str | None = Field(
        default=None, description="What was expected according to baseline"
    )
    actual: str | None = Field(default=None, description="What was actually observed in repository")
    evidence: str | None = Field(
        default=None,
        description=(
            "Deterministic evidence supporting the finding (e.g. diff snippet or graph reference)"
        ),
    )

    def to_dict(self) -> dict[str, Any]:
        """Convert finding to dictionary representation."""
        return {
            "category": self.category.value,
            "severity": self.severity.value,
            "message": self.message,
            "file_path": self.file_path,
            "symbol": self.symbol,
            "expected": self.expected,
            "actual": self.actual,
            "evidence": self.evidence,
        }
