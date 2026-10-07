"""WhatsApp-specific settings, read from the same .env as app.config.Settings (which ignores extra keys)."""
from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class WhatsAppSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    whatsapp_access_token: SecretStr | None = None
    whatsapp_phone_number_id: str | None = None
    whatsapp_verify_token: SecretStr | None = None
    whatsapp_app_secret: SecretStr | None = None  # when set, X-Hub-Signature-256 is enforced on POST /webhook
    whatsapp_api_version: str = "v21.0"
    whatsapp_timeout_seconds: float = 10.0


@lru_cache
def get_whatsapp_settings() -> WhatsAppSettings:
    return WhatsAppSettings()
