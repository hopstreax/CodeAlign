"""Verify that CodeAlign package and core models import successfully."""

import codealign
from codealign.models import (
    ExpectedFile,
    Finding,
    FindingCategory,
    FindingSeverity,
    ImplementationBaseline,
    Plan,
    VerificationResult,
    VerificationStatus,
)


def test_package_metadata() -> None:
    """Verify package version is exposed."""
    assert hasattr(codealign, "__version__")
    assert codealign.__version__ == "0.1.0"


def test_models_instantiation() -> None:
    """Verify basic domain models can be instantiated."""
    plan = Plan(title="Add Redis cache", steps=["Step 1", "Step 2"])
    assert plan.title == "Add Redis cache"
    assert len(plan.steps) == 2

    baseline = ImplementationBaseline(
        plan_title=plan.title,
        expected_files=[ExpectedFile(path="src/service.py", action="modify")],
        expected_symbols=["get_profile"],
        constraints=["Do not add external network calls in unit tests"],
    )
    assert baseline.version == "0.1.0"
    assert len(baseline.expected_files) == 1
    assert baseline.expected_files[0].path == "src/service.py"

    finding = Finding(
        category=FindingCategory.SCOPE_DRIFT,
        severity=FindingSeverity.WARN,
        message="Unexpected file modified",
        file_path="src/other.py",
    )
    assert finding.category == FindingCategory.SCOPE_DRIFT

    result = VerificationResult(
        status=VerificationStatus.PASS,
        summary="Implementation matches baseline",
        findings=[finding],
    )
    assert result.status == VerificationStatus.PASS
    assert len(result.findings) == 1
