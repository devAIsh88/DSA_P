"""Local Ollama only: verify resident weights before sending learner context."""

import httpx

from app.config import Settings
from app.services.http_tutor_provider import HttpTutorError, HttpTutorProvider
from app.services.tutor_generation_contract import _Payload


class OllamaTutorProvider(HttpTutorProvider):
    """No remote endpoints, cloud model shims, proxy use, redirects or model pulls."""

    provider_name = "ollama"

    def __init__(self, settings: Settings, *, transport: httpx.AsyncBaseTransport | None = None) -> None:
        # Revalidate even if a caller bypassed Pydantic using model_copy.
        settings.validate_tutor_safety()
        super().__init__(settings, transport=transport)
        self.model_id = settings.ollama_model
        self.timeout_seconds = settings.ollama_timeout_seconds
        self._base_url = settings.ollama_base_url.rstrip("/")

    async def _exchange(self, messages: list[dict[str, str]], schema: type[_Payload]
                        ) -> tuple[str, str | None, str | None]:
        async with httpx.AsyncClient(transport=self._transport, trust_env=False, follow_redirects=False,
                                     timeout=self.timeout_seconds) as client:
            shown = await self._json(client, "POST", self._base_url + "/api/show",
                                     json={"model": self.model_id})
            # A local daemon can forward cloud aliases. Require a local GGUF
            # model with architecture metadata; unknown/remote formats fail closed.
            if (shown.get("remote_host") or shown.get("remote_model")
                    or shown.get("details", {}).get("format") != "gguf"
                    or not shown.get("model_info", {}).get("general.architecture")):
                raise HttpTutorError("nonlocal_model")
            body = await self._json(
                client, "POST", self._base_url + "/api/chat",
                json={"model": self.model_id, "messages": messages, "stream": False,
                      "format": schema.model_json_schema(),
                      "options": {"temperature": 0, "num_predict": self.settings.tutor_max_output_tokens}},
            )
        if not body.get("done") or body.get("done_reason") != "stop" or body.get("remote_host"):
            raise HttpTutorError("incomplete_or_remote_output")
        return body["message"]["content"], None, body.get("model")
