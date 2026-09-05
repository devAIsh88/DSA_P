from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.problem import ProblemDetailResponse, ProblemListItemResponse, SampleTestCaseResponse
from app.services.problem_service import ProblemNotFoundError, get_problem, list_problems

router = APIRouter(prefix="/problems", tags=["problems"])


@router.get("", response_model=list[ProblemListItemResponse])
def read_problems(db: Session = Depends(get_db)) -> list[ProblemListItemResponse]:
    """List the available programming problems."""

    return [ProblemListItemResponse.model_validate(problem) for problem in list_problems(db)]


@router.get("/{problem_id}", response_model=ProblemDetailResponse)
def read_problem(problem_id: int, db: Session = Depends(get_db)) -> ProblemDetailResponse:
    """Return a problem's details without exposing hidden test cases."""

    try:
        problem, sample_cases = get_problem(db, problem_id)
    except ProblemNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Problem not found") from error

    return ProblemDetailResponse(
        **ProblemListItemResponse.model_validate(problem).model_dump(),
        description=problem.description,
        constraints=problem.constraints,
        input_format=problem.input_format,
        output_format=problem.output_format,
        expected_complexity=problem.expected_complexity,
        created_at=problem.created_at,
        sample_test_cases=[SampleTestCaseResponse.model_validate(test_case) for test_case in sample_cases],
    )
