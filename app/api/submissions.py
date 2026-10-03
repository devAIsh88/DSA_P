from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.session import get_db
from app.schemas.submission import SubmissionCreate, SubmissionReadResponse, SubmissionResultResponse
from app.services.execution_service import ExecutionProvider, Judge0ExecutionService
from app.services.attempt_service import LearnerIdentityError, LearnerNotFoundError
from app.services.problem_service import ProblemNotFoundError
from app.services.submission_service import (
    SubmissionAttemptNotFoundError, SubmissionConflictError, SubmissionNotFoundError, create_submission,
    get_submission,
)

router = APIRouter(prefix="/submissions", tags=["submissions"])


def get_execution_provider() -> ExecutionProvider:
    """Construct the configured isolated execution adapter."""

    return Judge0ExecutionService(get_settings().judge0_base_url)


@router.get("/{submission_id}", response_model=SubmissionReadResponse)
def read_submission(submission_id: int, db: Session = Depends(get_db)) -> SubmissionReadResponse:
    try:
        return get_submission(db, submission_id)
    except (SubmissionNotFoundError, LearnerNotFoundError) as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Submission or learner not found") from error
    except (SubmissionConflictError, LearnerIdentityError) as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error


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
    except SubmissionAttemptNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Attempt not found") from error
    except SubmissionConflictError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    except (LearnerIdentityError, LearnerNotFoundError) as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
