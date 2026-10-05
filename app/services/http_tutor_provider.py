"""Bounded JSON transport shared by the Groq and local Ollama adapters."""

from __future__ import annotations

import asyncio
import json
import logging
from time import monotonic
from typing import Any

import httpx

from app.config import Settings
from app.schemas.tutor import GenerationProvenance
from app.services.tutor_generation_contract import StructuredTutorProvider, _Payload, _SYSTEM_BASE
from app.services.tutor_prompts import PROMPT_VERSIONS
from app.services.tutor_provider import TutorProviderError

logger = logging.getLogger(__name__)


class HttpTutorError(TutorProviderError):
    """Safe categories only; the enclosing request must not retry this chain."""

    def __init__(self, category: str) -> None:
        super().__init__("Tutor provider unavailable", retryable=False)
        self.category = category


class HttpTutorProvider(StructuredTutorProvider):
    """No persistence, SDK types, raw errors or credentials escape this boundary."""

    provider_name: str
    model_id: str
    timeout_seconds: float

    def __init__(self, settings: Settings, *, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.settings = settings
        self._transport = transport

    async def _json(self, client: httpx.AsyncClient, method: str, url: str,
                    **kwargs: Any) -> dict[str, Any]:
        async with client.stream(method, url, **kwargs) as response:
            if response.status_code != 200:
                category = "rate_limit" if response.status_code == 429 else "http_error"
                raise HttpTutorError(category)
            data = bytearray()
            async for chunk in response.aiter_bytes():
                data.extend(chunk)
                if len(data) > 131072:
                    raise HttpTutorError("output_limit")
            key = self.settings.groq_api_key.get_secret_value()
            if key and key.encode() in data:
                raise HttpTutorError("unsafe_output")
            body = json.loads(data)
            if not isinstance(body, dict):
                raise HttpTutorError("schema_error")
            return body

    async def _exchange(self, messages: list[dict[str, str]], schema: type[_Payload]
                        ) -> tuple[str, str | None, str | None]:
        raise NotImplementedError

    async def _generate(self, task: str, instruction: str, data: dict[str, object],
                        schema: type[_Payload]) -> tuple[_Payload, GenerationProvenance]:
        started = monotonic()
        category = "success"
        try:
            contents = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
            if len(contents) > self.settings.tutor_max_input_chars:
                raise HttpTutorError("input_limit")
            # Schema and task instructions are application-owned; learner strings
            # occur only in the JSON user message, never in system instructions.
            messages = [
                {"role": "system", "content": f"{_SYSTEM_BASE} {instruction} Output JSON matching: "
                 + json.dumps(schema.model_json_schema(), separators=(",", ":"))},
                {"role": "user", "content": contents},
            ]
            text, invocation_id, served_model = await asyncio.wait_for(
                self._exchange(messages, schema), timeout=self.timeout_seconds,
            )
            if not isinstance(text, str) or len(text) > 30000:
                raise HttpTutorError("output_limit")
            result = schema.model_validate_json(text)
            key = self.settings.groq_api_key.get_secret_value()
            if key and key in result.model_dump_json():
                raise HttpTutorError("unsafe_output")
            if any(value is not None and (not isinstance(value, str) or len(value) > 200)
                   for value in (invocation_id, served_model)):
                raise HttpTutorError("schema_error")
            provenance = GenerationProvenance(
                provider=self.provider_name, model_id=self.model_id,
                prompt_version=PROMPT_VERSIONS[task], invocation_id=invocation_id,
                served_model_id=served_model, max_output_tokens=self.settings.tutor_max_output_tokens,
            )
            if key and key in provenance.model_dump_json():
                raise HttpTutorError("unsafe_output")
            return result, provenance
        except HttpTutorError as error:
            category = error.category
            raise HttpTutorError(category) from None
        except (TimeoutError, httpx.TimeoutException):
            category = "timeout"
            raise HttpTutorError(category) from None
        except httpx.RequestError:
            category = "connection"
            raise HttpTutorError(category) from None
        except Exception:
            category = "schema_error"
            raise HttpTutorError(category) from None
        finally:
            # Fixed adapter identity/categories only; never log request bodies,
            # Authorization, exception text, or untrusted configured identifiers.
            logger.info("tutor provider=%s latency_ms=%d category=%s", self.provider_name,
                        int((monotonic() - started) * 1000), category)
