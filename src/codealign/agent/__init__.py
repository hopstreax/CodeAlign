"""Agent adapters for CodeAlign."""

from codealign.agent.antigravity import (
    AntigravityAgent,
    AntigravityError,
    AntigravityExecutionError,
    AntigravityNotFoundError,
    AntigravityResult,
)
from codealign.agent.gemini import (
    GeminiAgent,
    GeminiError,
    GeminiExecutionError,
    GeminiNotFoundError,
    GeminiResult,
)

__all__ = [
    "AntigravityAgent",
    "AntigravityError",
    "AntigravityExecutionError",
    "AntigravityNotFoundError",
    "AntigravityResult",
    "GeminiAgent",
    "GeminiError",
    "GeminiExecutionError",
    "GeminiNotFoundError",
    "GeminiResult",
]
