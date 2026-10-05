"""Gemini SDK adapter; vendor types and transport remain confined here."""

from __future__ import annotations

import asyncio
import json
from typing import Callable

from google import genai
from google.genai import types
from pydantic import ValidationError

from app.config import Settings
from app.schemas.tutor import GenerationProvenance
from app.services.tutor_generation_contract import StructuredTutorProvider, _Payload, _SYSTEM_BASE
from app.services.tutor_prompts import PROMPT_VERSIONS
from app.services.tutor_provider import TutorProviderError


class GeminiTutorProvider(StructuredTutorProvider):
    """Structured Gemini responses with local validation and bounded requests."""

    def __init__(self, settings: Settings, client_factory: Callable[..., object] | None = None,
                 *, sdk_retry_attempts: int | None = None, temperature: float | None = None) -> None:
        if sdk_retry_attempts is not None and (type(sdk_retry_attempts) is not int or not 1 <= sdk_retry_attempts <= 10):
            raise ValueError("SDK retry attempts must be bounded positive integers")
        if temperature is not None and not 0 <= temperature <= 2:
            raise ValueError("Temperature must be between zero and two")
        if settings.zero_cost_mode:
            raise TutorProviderError("ZERO_COST_MODE prohibits Gemini")
        self._settings = settings
        self._client_factory = client_factory or genai.Client
        # Evaluation may explicitly control SDK retries/temperature. Leaving
        # these unset preserves the normal Phase 6 adapter configuration.
        self._sdk_retry_attempts = sdk_retry_attempts
        self._temperature = temperature

    async def _generate(
        self, task: str, instruction: str, data: dict[str, object],
        schema: type[_Payload],
    ) -> tuple[_Payload, GenerationProvenance]:
        if self._settings.zero_cost_mode:
            raise TutorProviderError("ZERO_COST_MODE prohibits Gemini")
        if not self._settings.google_api_key:
            raise TutorProviderError("Tutor provider is not configured")
        contents = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
        if len(contents) > self._settings.tutor_max_input_chars:
            raise TutorProviderError("Tutor input exceeds configured bound")
        client = None
        try:
            http_options = {"timeout": int(self._settings.tutor_timeout_seconds * 1000)}
            if self._sdk_retry_attempts is not None:
                http_options["retry_options"] = types.HttpRetryOptions(attempts=self._sdk_retry_attempts)
            generation_options = {}
            if self._temperature is not None:
                generation_options["temperature"] = self._temperature
            client = self._client_factory(
                api_key=self._settings.google_api_key,
                http_options=types.HttpOptions(**http_options),
            )
            response = await asyncio.wait_for(
                client.aio.models.generate_content(
                    model=self._settings.tutor_model,
                    contents=contents,
                    config=types.GenerateContentConfig(
                        system_instruction=f"{_SYSTEM_BASE} {instruction}",
                        response_mime_type="application/json", response_schema=schema,
                        max_output_tokens=self._settings.tutor_max_output_tokens,
                        **generation_options,
                    ),
                ),
                timeout=self._settings.tutor_timeout_seconds + 1,
            )
            parsed = getattr(response, "parsed", None)
            if parsed is not None:
                result = schema.model_validate(parsed)
            else:
                body = getattr(response, "text", None)
                if not isinstance(body, str) or len(body) > 30000:
                    raise TutorProviderError("Tutor output is missing or too large")
                result = schema.model_validate_json(body)
            provenance = GenerationProvenance(
                provider="gemini", model_id=self._settings.tutor_model,
                prompt_version=PROMPT_VERSIONS[task],
                invocation_id=getattr(response, "response_id", None),
                served_model_id=getattr(response, "model_version", None),
                max_output_tokens=self._settings.tutor_max_output_tokens,
            )
            return result, provenance
        except (TutorProviderError, ValidationError):
            raise TutorProviderError("Gemini returned no valid tutor result") from None
        except Exception:
            # SDK and transport errors must not disclose credentials or provider diagnostics.
            raise TutorProviderError("Gemini tutor unavailable") from None
        finally:
            if client is not None:
                try:
                    await client.aio.aclose()
                except Exception:
                    pass
