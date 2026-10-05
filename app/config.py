from functools import lru_cache

from ipaddress import ip_address
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuration loaded from environment variables or a local .env file."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore",
                                      hide_input_in_errors=True)

    app_name: str = Field(default="DEV Placement OS", validation_alias="APP_NAME")
    app_env: str = Field(default="development", validation_alias="APP_ENV")
    database_url: str = Field(
        default="postgresql+psycopg://dev_placement:dev_placement@localhost:5432/dev_placement",
        validation_alias="DATABASE_URL",
    )
    sql_echo: bool = Field(default=False, validation_alias="SQL_ECHO")
    judge0_base_url: str = Field(default="", validation_alias="JUDGE0_BASE_URL")
    zero_cost_mode: bool = Field(default=True, validation_alias="ZERO_COST_MODE")
    tutor_provider: str = Field(default="zero_cost", validation_alias="TUTOR_PROVIDER")
    groq_api_key: SecretStr = Field(default=SecretStr(""), validation_alias="GROQ_API_KEY", repr=False)
    groq_model: str = Field(default="", max_length=200, validation_alias="GROQ_MODEL")
    groq_free_tier_confirmed: bool = Field(default=False, validation_alias="GROQ_FREE_TIER_CONFIRMED")
    groq_timeout_seconds: float = Field(default=8, gt=0, le=10, validation_alias="GROQ_TIMEOUT_SECONDS")
    ollama_base_url: str = Field(default="http://127.0.0.1:11434", validation_alias="OLLAMA_BASE_URL")
    ollama_model: str = Field(default="qwen2.5-coder:3b", max_length=200, validation_alias="OLLAMA_MODEL")
    ollama_timeout_seconds: float = Field(default=60, gt=0, le=70, validation_alias="OLLAMA_TIMEOUT_SECONDS")
    tutor_model: str = Field(default="gemini-3.8-flash", validation_alias="TUTOR_MODEL")
    google_api_key: str = Field(default="", validation_alias="GOOGLE_API_KEY", repr=False)
    tutor_timeout_seconds: float = Field(default=20.0, gt=0, le=120, validation_alias="TUTOR_TIMEOUT_SECONDS")
    tutor_max_retries: int = Field(default=2, ge=0, le=3, validation_alias="TUTOR_MAX_RETRIES")
    tutor_max_input_chars: int = Field(default=30000, ge=1000, le=60000, validation_alias="TUTOR_MAX_INPUT_CHARS")
    tutor_max_output_tokens: int = Field(default=2048, ge=128, le=4096, validation_alias="TUTOR_MAX_OUTPUT_TOKENS")
    hint_level_6_requires_level_5: bool = Field(default=True, validation_alias="HINT_LEVEL_6_REQUIRES_LEVEL_5")

    @model_validator(mode="after")
    def validate_tutor_safety(self) -> "Settings":
        if self.zero_cost_mode and self.tutor_provider not in {"zero_cost", "groq", "ollama", "mock"}:
            raise ValueError("ZERO_COST_MODE rejects this tutor provider; select zero_cost, ollama or mock")
        url = urlsplit(self.ollama_base_url)
        try:
            local = ip_address(url.hostname or "").is_loopback
            port = url.port
        except ValueError:
            local, port = False, None
        if (url.scheme != "http" or not local or not port or url.username is not None
                or url.password is not None or url.path not in {"", "/"} or url.query or url.fragment):
            raise ValueError("Ollama requires an HTTP loopback IP URL with an explicit port")
        if (not self.ollama_model or any(word in self.ollama_model.lower() for word in ("cloud", "://"))
                or any(char.isspace() for char in self.ollama_model)):
            raise ValueError("Ollama requires a local model identifier, not a cloud model")
        if self.groq_model and (any(char.isspace() for char in self.groq_model)
                                or "compound" in self.groq_model.lower()):
            raise ValueError("Groq requires an explicitly approved text model, without external tools")
        key = self.groq_api_key.get_secret_value()
        if key and any(key in value for value in (self.groq_model, self.ollama_model, self.ollama_base_url)):
            raise ValueError("Provider identifiers must not contain credentials")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
