"""Explicit evaluation adapter registry; offline construction never reads credentials."""

from __future__ import annotations

import re
from hashlib import sha256

from app.schemas.benchmark import BenchmarkCase, EvaluationCandidate, ExecutionPolicy
from app.services.tutor_provider import TutorProvider


def parse_candidate(specification: str) -> EvaluationCandidate:
    """Resolve explicit identities, without inspecting application model defaults."""

    if specification in {"synthetic-good", "synthetic-bad"}:
        return EvaluationCandidate(candidate_id=specification, provider="synthetic",
                                   model_id=f"{specification}-v1", synthetic=True)
    provider, separator, model = specification.partition(":")
    if separator and provider == "gemini" and model:
        label = re.sub(r"[^A-Za-z0-9_.-]", "-", model)[:80]
        digest = sha256(specification.encode()).hexdigest()[:12]
        return EvaluationCandidate(candidate_id=f"gemini-{label}-{digest}",
                                   provider=provider, model_id=model, synthetic=False)
    raise ValueError("Unsupported candidate; use synthetic-good/synthetic-bad or an explicit registered provider:model")


def build_provider(candidate: EvaluationCandidate, case: BenchmarkCase, policy: ExecutionPolicy,
                   *, live_authorized: bool = False) -> TutorProvider:
    """Keep credentials and concrete adapters out of the generic evaluator."""

    if candidate.synthetic:
        from app.services.evaluation_candidates import build_synthetic_provider

        return build_synthetic_provider(candidate, case)
    if not live_authorized or candidate.provider != "gemini":
        raise ValueError("External evaluation provider construction is not authorized")
    if not (policy.timeout_seconds <= 120 and 1000 <= policy.max_input_chars <= 60000
            and 128 <= policy.max_output_tokens <= 4096):
        raise ValueError("Execution controls exceed the registered adapter's bounds")
    # Only the explicitly authorized live path resolves a provider credential.
    from pydantic import Field, SecretStr
    from pydantic_settings import BaseSettings, SettingsConfigDict
    from app.config import Settings
    from app.services.gemini_tutor_provider import GeminiTutorProvider

    class Credentials(BaseSettings):
        model_config = SettingsConfigDict(env_file=".env", extra="ignore")
        api_key: SecretStr = Field(default=SecretStr(""), validation_alias="GOOGLE_API_KEY")

    credential = Credentials().api_key.get_secret_value()
    if not credential:
        raise ValueError("The explicitly selected provider credential is unavailable")
    settings = Settings(_env_file=None, GOOGLE_API_KEY=credential, TUTOR_PROVIDER="gemini",
                        TUTOR_MODEL=candidate.model_id, TUTOR_TIMEOUT_SECONDS=policy.timeout_seconds,
                        TUTOR_MAX_RETRIES=0, TUTOR_MAX_INPUT_CHARS=policy.max_input_chars,
                        TUTOR_MAX_OUTPUT_TOKENS=policy.max_output_tokens)
    return GeminiTutorProvider(settings, sdk_retry_attempts=1, temperature=policy.temperature)
