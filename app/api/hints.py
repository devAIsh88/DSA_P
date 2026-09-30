"""Thin public hint route over the tutor service."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.session import get_db
from app.schemas.tutor import HintRequest, HintResponse
from app.services.attempt_service import AttemptNotFoundError, LearnerIdentityError, LearnerNotFoundError
from app.services.tutor_provider import FallbackHintProvider, TutorProvider, TutorProviderError
from app.services.tutor_provider_factory import get_tutor_provider
from app.services.tutor_service import TutorConflictError, request_hint


router = APIRouter(prefix="/hints", tags=["hints"])


@router.post("/request", response_model=HintResponse)
async def create_hint(
    payload: HintRequest, db: Session = Depends(get_db),
    provider: TutorProvider = Depends(get_tutor_provider),
) -> HintResponse:
    try:
        return await request_hint(db, payload, provider, FallbackHintProvider(), get_settings())
    except (AttemptNotFoundError, LearnerNotFoundError) as error:
        raise HTTPException(status_code=404, detail="Attempt or learner not found") from error
    except (TutorConflictError, LearnerIdentityError) as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except TutorProviderError as error:
        raise HTTPException(status_code=503, detail="Hint unavailable") from error
