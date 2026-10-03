"""Public sample execution, separate from persisted grading submissions."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.submissions import get_execution_provider
from app.db.session import get_db
from app.schemas.run import RunCreate, RunResponse
from app.services.execution_service import ExecutionProvider
from app.services.problem_service import ProblemNotFoundError
from app.services.run_service import NoPublicSamplesError, run_code

router = APIRouter(prefix="/runs", tags=["runs"])


@router.post("", response_model=RunResponse)
async def run_samples(
    payload: RunCreate,
    db: Session = Depends(get_db),
    provider: ExecutionProvider = Depends(get_execution_provider),
) -> RunResponse:
    try:
        return await run_code(db, payload, provider)
    except ProblemNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Problem not found") from error
    except NoPublicSamplesError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail={"code": "NO_PUBLIC_SAMPLE_TESTS"}) from error
