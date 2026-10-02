"""Allowlisted next-activity selection for the single-learner MVP."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.recommendation import NextRecommendationResponse
from app.services.attempt_service import LearnerIdentityError, LearnerNotFoundError
from app.services.recommendation_context import LearnerStateNotReadyError
from app.services.recommendation_service import (
    ActiveAttemptError, RecommendationUnavailableError, get_next_recommendation,
)


router = APIRouter(prefix="/recommendations", tags=["recommendations"])


@router.get("/next", response_model=NextRecommendationResponse)
def read_next_recommendation(db: Session = Depends(get_db)) -> NextRecommendationResponse:
    try:
        return get_next_recommendation(db)
    except LearnerNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Learner not found") from error
    except LearnerIdentityError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    except ActiveAttemptError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail={"code": "ACTIVE_ATTEMPT_EXISTS", "attempt_ids": error.attempt_ids}) from error
    except LearnerStateNotReadyError as error:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail={"code": "LEARNER_STATE_NOT_READY"}) from error
    except RecommendationUnavailableError as error:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail={"code": "RECOMMENDATION_UNAVAILABLE"}) from error
