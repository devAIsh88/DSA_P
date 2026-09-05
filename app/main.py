from fastapi import FastAPI

from app.api.health import router as health_router
from app.api.problems import router as problems_router
from app.api.submissions import router as submissions_router
from app.config import get_settings

settings = get_settings()
app = FastAPI(title=settings.app_name, version="0.1.0")
app.include_router(health_router)
app.include_router(problems_router)
app.include_router(submissions_router)
