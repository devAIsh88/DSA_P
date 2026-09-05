from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.session import get_db
from app.schemas.submission import SubmissionCreate, SubmissionResultResponse
from app.services.execution_service import ExecutionProvider, Judge0ExecutionService
from app.services.problem_service import ProblemNotFoundError
from app.services.submission_service import create_submission

router = APIRouter(prefix="/submissions", tags=["submissions"])


def get_execution_provider() -> ExecutionProvider:
    """Construct the configured isolated execution adapter."""

    return Judge0ExecutionService(get_settings().judge0_base_url)


@router.post("", response_model=SubmissionResultResponse, status_code=status.HTTP_201_CREATED)
async def submit_code(
    payload: SubmissionCreate,
    db: Session = Depends(get_db),
    provider: ExecutionProvider = Depends(get_execution_provider),
) -> SubmissionResultResponse:
    try:
        return await create_submission(db, payload, provider)
    except ProblemNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Problem not found") from error
