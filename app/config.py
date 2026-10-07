"""Central configuration. All secrets come from the environment / .env — never hardcode."""
from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "WhatsApp Sales Agent"
    app_env: str = "development"
    log_level: str = "INFO"

    groq_api_key: SecretStr | None = None
    groq_model: str = "openai/gpt-oss-120b"
    llm_timeout_seconds: float = 30.0

    # Used from Phase 9 (WhatsApp). Declared now so .env.example and Settings stay in sync.
    whatsapp_access_token: SecretStr | None = None
    whatsapp_phone_number_id: str | None = None
    whatsapp_verify_token: SecretStr | None = None

    database_url: str = "postgresql://postgres:password@localhost:5432/whatsapp_sales_agent"

    currency: str = "USD"
    history_message_limit: int = 20  # user/assistant messages replayed to the LLM per turn


@lru_cache
def get_settings() -> Settings:
    return Settings()
