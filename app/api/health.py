from fastapi import APIRouter

from app.config import get_settings
from app.schemas.health import HealthResponse

router = APIRouter(tags=["system"])


@router.get("/health", response_model=HealthResponse)
def health_check() -> HealthResponse:
    """Return process health without depending on external services."""

    settings = get_settings()
    return HealthResponse(status="ok", service=settings.app_name, environment=settings.app_env)

