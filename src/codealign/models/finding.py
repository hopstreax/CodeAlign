"""Verification finding models."""

from enum import Enum

from pydantic import BaseModel, Field


class FindingSeverity(str, Enum):
    """Severity of a verification finding."""

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


class Finding(BaseModel):
    """An individual discrepancy found during implementation verification."""

    category: FindingCategory = Field(description="Category of the finding")
    severity: FindingSeverity = Field(
        default=FindingSeverity.WARN, description="Severity level of the finding"
    )
    message: str = Field(description="Human-readable explanation of the discrepancy")
    file_path: str | None = Field(default=None, description="Affected file path if applicable")
    symbol: str | None = Field(default=None, description="Affected symbol name if applicable")
    evidence: str | None = Field(
        default=None,
        description=(
            "Deterministic evidence supporting the finding (e.g. diff snippet or graph reference)"
        ),
    )
