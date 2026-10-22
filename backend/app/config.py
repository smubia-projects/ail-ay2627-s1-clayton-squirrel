"""
Settings for the Squirrel demo API, read from environment variables.

A `.env` file in backend/ is loaded for local development (it is gitignored and
excluded from the Docker image); on Cloud Run every value comes from the
service's env vars. See backend/.env.example for the full list.
"""

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # OpenRouter (all AI calls go through its OpenAI-compatible chat/completions API).
    openrouter_api_key: str = Field("", validation_alias=AliasChoices("API_KEY", "OPENROUTER_API_KEY"))
    openrouter_model: str = Field("google/gemini-2.5-flash", validation_alias=AliasChoices("MODEL_NAME", "OPENROUTER_MODEL"))
    openrouter_base_url: str = Field("https://openrouter.ai/api/v1", validation_alias=AliasChoices("API_BASE_URL", "OPENROUTER_BASE_URL"))

    # Comma-separated frontend origins allowed by CORS, e.g. https://squirrel.vercel.app
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    # Shared rate-limit engine (Upstash Redis). Unset = rate limiting disabled (local dev).
    upstash_redis_rest_url: str = ""
    upstash_redis_rest_token: str = ""
    upstash_redis_url: str = ""
    upstash_redis_token: str = ""

    # Per-IP limits per bucket within the rolling window. Fallbacks only: the
    # central rate-limit sheet overrides them at runtime.
    rate_limit_extract_max: int = 5
    rate_limit_digest_max: int = 5
    rate_limit_ask_max: int = 5
    rate_limit_window_seconds: int = 432000  # 5 days

    @property
    def redis_url(self) -> str:
        """Accept both the Upstash-default (REST_) and the short env var names."""
        return self.upstash_redis_rest_url or self.upstash_redis_url

    @property
    def redis_token(self) -> str:
        return self.upstash_redis_rest_token or self.upstash_redis_token

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
