"""Developer intent and implementation plan models."""

from pydantic import BaseModel, Field


class Plan(BaseModel):
    """Developer-provided implementation plan.

    Represents the intent, objectives, and structured steps of a planned change.
    """

    title: str = Field(description="Short title of the implementation plan")
    description: str = Field(
        default="", description="Detailed narrative or description of the goal"
    )
    steps: list[str] = Field(
        default_factory=list,
        description="Sequential implementation steps or requirements",
    )
