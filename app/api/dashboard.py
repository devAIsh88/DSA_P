"""Read-only learner dashboard for the local MVP."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.dashboard import DashboardSummaryResponse
from app.services.attempt_service import LearnerIdentityError, LearnerNotFoundError
from app.services.dashboard_service import get_dashboard_summary


router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/summary", response_model=DashboardSummaryResponse)
def read_dashboard_summary(db: Session = Depends(get_db)) -> DashboardSummaryResponse:
    try:
        return get_dashboard_summary(db)
    except LearnerNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Learner not found") from error
    except LearnerIdentityError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
