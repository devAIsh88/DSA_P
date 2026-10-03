"""Non-secret local UI configuration, separate from backend configuration."""

from urllib.parse import urlsplit

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class UISettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    api_base_url: str = Field(default="http://127.0.0.1:8000", validation_alias="UI_API_BASE_URL")
    learner_id: int | None = Field(default=None, gt=0, validation_alias="UI_LEARNER_ID")
    request_timeout_seconds: float = Field(default=90, gt=0, le=300, validation_alias="UI_REQUEST_TIMEOUT_SECONDS")

    @field_validator("learner_id", mode="before")
    @classmethod
    def blank_learner(cls, value: object) -> object:
        return None if value == "" else value

    @field_validator("api_base_url")
    @classmethod
    def safe_base_url(cls, value: str) -> str:
        parsed = urlsplit(value)
        # Accessing port validates malformed values before creating an HTTP client.
        parsed.port
        if (parsed.scheme not in {"http", "https"} or not parsed.hostname
                or parsed.username or parsed.password or parsed.query or parsed.fragment):
            raise ValueError("UI_API_BASE_URL must be an HTTP URL without credentials, query or fragment")
        return value.rstrip("/")
