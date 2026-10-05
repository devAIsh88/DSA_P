"""The sole automatic tutor chain: confirmed free Groq, then local Ollama."""

import logging

import httpx

from app.config import Settings
from app.services.groq_tutor_provider import GroqTutorProvider
from app.services.ollama_tutor_provider import OllamaTutorProvider
from app.services.tutor_generation_contract import StructuredTutorProvider, _Payload
from app.schemas.tutor import GenerationProvenance
from app.services.tutor_provider import TutorProviderError

logger = logging.getLogger(__name__)


class ZeroCostFallbackTutorProvider(StructuredTutorProvider):
    """All five tasks share the same safe chain, with no repeated network retries."""

    def __init__(self, settings: Settings, *, groq_transport: httpx.AsyncBaseTransport | None = None,
                 ollama_transport: httpx.AsyncBaseTransport | None = None) -> None:
        # Concrete construction prevents injection/configuration of a paid fallback.
        self._groq = GroqTutorProvider(settings, transport=groq_transport)
        self._ollama = OllamaTutorProvider(settings, transport=ollama_transport)

    async def _generate(self, task: str, instruction: str, data: dict[str, object],
                        schema: type[_Payload]) -> tuple[_Payload, GenerationProvenance]:
        try:
            return await self._groq._generate(task, instruction, data, schema)
        except TutorProviderError:
            logger.info("tutor fallback occurred provider=ollama")
        try:
            return await self._ollama._generate(task, instruction, data, schema)
        except TutorProviderError:
            # Stop the outer service retry loop too: a quota error must not
            # cause another Groq call just because local inference also failed.
            raise TutorProviderError("Tutor provider unavailable", retryable=False) from None
