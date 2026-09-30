"""Construct the configured tutor adapter at the application boundary."""

from app.config import Settings, get_settings
from app.services.tutor_provider import MockTutorProvider, TutorProvider, TutorProviderError


def build_tutor_provider(settings: Settings) -> TutorProvider:
    """Select a replaceable adapter without exposing vendor types to callers."""

    if settings.tutor_provider == "mock":
        return MockTutorProvider()
    if settings.tutor_provider == "gemini":
        try:
            from app.services.gemini_tutor_provider import GeminiTutorProvider
        except ImportError as error:
            raise TutorProviderError("Gemini tutor adapter is unavailable") from error
        return GeminiTutorProvider(settings)
    raise TutorProviderError("Unsupported tutor provider")


def get_tutor_provider() -> TutorProvider:
    """FastAPI dependency; tests override it with an isolated mock."""

    return build_tutor_provider(get_settings())
