"""Thin Attempt-scoped Phase 6 tutor routes."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.session import get_db
from app.schemas.tutor import (
    DiagnoseRequest, DiagnoseResponse, ReasoningAnalysisRequest, ReasoningAnalysisResponse,
)
from app.services.attempt_service import AttemptNotFoundError, LearnerIdentityError, LearnerNotFoundError
from app.services.tutor_provider import TutorProvider, TutorProviderError
from app.services.tutor_provider_factory import get_tutor_provider
from app.services.tutor_service import TutorConflictError, TutorNotFoundError, analyze_reasoning, diagnose_attempt


router = APIRouter(prefix="/attempts", tags=["tutor"])


def _tutor_error(error: Exception) -> HTTPException:
    if isinstance(error, (AttemptNotFoundError, LearnerNotFoundError, TutorNotFoundError)):
        return HTTPException(status_code=404, detail="Attempt or reference not found")
    if isinstance(error, (TutorConflictError, LearnerIdentityError)):
        return HTTPException(status_code=409, detail=str(error))
    return HTTPException(status_code=503, detail="Tutor unavailable")


@router.post("/{attempt_id}/diagnose", response_model=DiagnoseResponse)
async def diagnose(
    attempt_id: int, payload: DiagnoseRequest, db: Session = Depends(get_db),
    provider: TutorProvider = Depends(get_tutor_provider),
) -> DiagnoseResponse:
    try:
        return await diagnose_attempt(db, attempt_id, payload, provider, get_settings())
    except (AttemptNotFoundError, LearnerNotFoundError, TutorNotFoundError,
            TutorConflictError, LearnerIdentityError, TutorProviderError) as error:
        raise _tutor_error(error) from error


@router.post("/{attempt_id}/reasoning-analysis", response_model=ReasoningAnalysisResponse)
async def reasoning_analysis(
    attempt_id: int, payload: ReasoningAnalysisRequest, db: Session = Depends(get_db),
    provider: TutorProvider = Depends(get_tutor_provider),
) -> ReasoningAnalysisResponse:
    try:
        return await analyze_reasoning(db, attempt_id, payload, provider, get_settings())
    except (AttemptNotFoundError, LearnerNotFoundError, TutorNotFoundError,
            TutorConflictError, LearnerIdentityError, TutorProviderError) as error:
        raise _tutor_error(error) from error
