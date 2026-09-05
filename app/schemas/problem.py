from datetime import datetime

from pydantic import BaseModel, ConfigDict


class SampleTestCaseResponse(BaseModel):
    """A test case that is intentionally visible to learners."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    input: str
    expected_output: str


class ProblemListItemResponse(BaseModel):
    """Problem metadata used in catalogue results."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    difficulty: str
    source: str | None
    topic: str
    subtopic: str | None
    target_track: str | None


class ProblemDetailResponse(ProblemListItemResponse):
    """Learner-safe problem detail, including sample cases only."""

    description: str
    constraints: str | None
    input_format: str | None
    output_format: str | None
    expected_complexity: str | None
    created_at: datetime
    sample_test_cases: list[SampleTestCaseResponse]
