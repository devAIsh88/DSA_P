"""Read-only learner-state endpoints for the single-learner MVP."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.dashboard import LearnerStateResponse
from app.schemas.skill_state import SkillStateResponse
from app.services.attempt_service import LearnerIdentityError, LearnerNotFoundError, single_learner_id
from app.services.dashboard_service import get_learner_state
from app.services.learner_state_service import get_skill_state, list_skill_states


router = APIRouter(prefix="/learner", tags=["learner"])


def _learner_id(db: Session) -> int:
    try:
        return single_learner_id(db)
    except LearnerNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Learner not found") from error
    except LearnerIdentityError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error


@router.get("/state", response_model=LearnerStateResponse)
def read_learner_state(db: Session = Depends(get_db)) -> LearnerStateResponse:
    try:
        return get_learner_state(db)
    except LearnerNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Learner not found") from error
    except LearnerIdentityError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error


@router.get("/skills", response_model=list[SkillStateResponse])
def read_skills(db: Session = Depends(get_db)) -> list[SkillStateResponse]:
    user_id = _learner_id(db)
    return [SkillStateResponse.model_validate(state) for state in list_skill_states(db, user_id)]


@router.get("/skills/{skill_id}", response_model=SkillStateResponse)
def read_skill(skill_id: int, db: Session = Depends(get_db)) -> SkillStateResponse:
    user_id = _learner_id(db)
    state = get_skill_state(db, user_id, skill_id)
    if state is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Skill state not found")
    return SkillStateResponse.model_validate(state)
