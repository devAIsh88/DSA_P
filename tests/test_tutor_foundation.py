"""Provider-neutral contracts and deterministic provider tests."""

import asyncio

import pytest
from pydantic import ValidationError

from app.config import Settings
from app.schemas.tutor import HintRequest, HintTask, TutorContext
from app.services.tutor_provider import FallbackHintProvider, MockTutorProvider
from app.services.tutor_provider_factory import build_tutor_provider


def test_tutor_configuration_and_contract_bounds() -> None:
    settings = Settings(_env_file=None, GOOGLE_API_KEY="", TUTOR_PROVIDER="gemini")
    assert settings.tutor_model == "gemini-3.8-flash"
    assert settings.hint_level_6_requires_level_5 is True
    assert isinstance(build_tutor_provider(Settings(_env_file=None, TUTOR_PROVIDER="mock")), MockTutorProvider)
    for level in (0, 7):
        with pytest.raises(ValidationError):
            HintRequest(attempt_id=1, requested_level=level, idempotency_key="k")
    with pytest.raises(ValidationError):
        HintRequest(attempt_id=1, requested_level=1, idempotency_key="")


def test_mock_and_hint_only_fallback_are_deterministic() -> None:
    request = HintTask(context=TutorContext(problem_title="Arrays", problem_description="Find a pair",
                                            attempt_status="ACTIVE"), level=1)
    mock = MockTutorProvider()
    first = asyncio.run(mock.generate_hint(request))
    second = asyncio.run(mock.generate_hint(request))
    assert first == second
    fallback = FallbackHintProvider()
    assert asyncio.run(fallback.generate_hint(request)).hint_text
    assert asyncio.run(fallback.generate_hint(request.model_copy(update={"level": 6}))) is None
