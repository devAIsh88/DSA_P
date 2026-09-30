from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuration loaded from environment variables or a local .env file."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = Field(default="DEV Placement OS", validation_alias="APP_NAME")
    app_env: str = Field(default="development", validation_alias="APP_ENV")
    database_url: str = Field(
        default="postgresql+psycopg://dev_placement:dev_placement@localhost:5432/dev_placement",
        validation_alias="DATABASE_URL",
    )
    sql_echo: bool = Field(default=False, validation_alias="SQL_ECHO")
    judge0_base_url: str = Field(default="", validation_alias="JUDGE0_BASE_URL")
    tutor_provider: str = Field(default="gemini", validation_alias="TUTOR_PROVIDER")
    tutor_model: str = Field(default="gemini-3.8-flash", validation_alias="TUTOR_MODEL")
    google_api_key: str = Field(default="", validation_alias="GOOGLE_API_KEY", repr=False)
    tutor_timeout_seconds: float = Field(default=20.0, gt=0, le=120, validation_alias="TUTOR_TIMEOUT_SECONDS")
    tutor_max_retries: int = Field(default=2, ge=0, le=3, validation_alias="TUTOR_MAX_RETRIES")
    hint_level_6_requires_level_5: bool = Field(default=True, validation_alias="HINT_LEVEL_6_REQUIRES_LEVEL_5")


@lru_cache
def get_settings() -> Settings:
    return Settings()
