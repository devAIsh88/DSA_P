"""Groq text generation, gated by explicit operator free-tier confirmation."""

import httpx

from app.config import Settings
from app.services.http_tutor_provider import HttpTutorError, HttpTutorProvider
from app.services.tutor_generation_contract import _Payload


class GroqTutorProvider(HttpTutorProvider):
    """One request, no SDK retries, tools, redirects or billing operations."""

    provider_name = "groq"

    def __init__(self, settings: Settings, *, transport: httpx.AsyncBaseTransport | None = None) -> None:
        super().__init__(settings, transport=transport)
        self.model_id = settings.groq_model
        self.timeout_seconds = settings.groq_timeout_seconds

    async def _exchange(self, messages: list[dict[str, str]], schema: type[_Payload]
                        ) -> tuple[str, str | None, str | None]:
        if (not self.settings.groq_free_tier_confirmed or not self.model_id
                or not self.settings.groq_api_key.get_secret_value()):
            raise HttpTutorError("free_tier_unconfirmed_or_unconfigured")
        # The OpenAI-compatible protocol is sent only to Groq, never OpenAI.
        async with httpx.AsyncClient(transport=self._transport, trust_env=False, follow_redirects=False,
                                     timeout=self.timeout_seconds) as client:
            body = await self._json(
                client, "POST", "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": "Bearer " + self.settings.groq_api_key.get_secret_value()},
                json={"model": self.model_id, "messages": messages, "temperature": 0,
                      "max_completion_tokens": self.settings.tutor_max_output_tokens,
                      "response_format": {"type": "json_object"}},
            )
        choice = body["choices"][0]
        if choice.get("finish_reason") != "stop":
            raise HttpTutorError("incomplete_output")
        return choice["message"]["content"], body.get("id"), body.get("model")
