# """WhatsApp-specific settings, read from the same .env as app.config.Settings (which ignores extra keys)."""
# from functools import lru_cache

# from pydantic import SecretStr
# from pydantic_settings import BaseSettings, SettingsConfigDict


# class WhatsAppSettings(BaseSettings):
#     model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

#     whatsapp_access_token: SecretStr | None = None
#     whatsapp_phone_number_id: str | None = None
#     whatsapp_verify_token: SecretStr | None = None
#     whatsapp_app_secret: SecretStr | None = None  # when set, X-Hub-Signature-256 is enforced on POST /webhook
#     whatsapp_api_version: str = "v21.0"
#     whatsapp_timeout_seconds: float = 10.0


# @lru_cache
# def get_whatsapp_settings() -> WhatsAppSettings:
#     return WhatsAppSettings()



"""WhatsApp Cloud API configuration."""

from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class WhatsAppSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Meta WhatsApp Cloud API
    whatsapp_access_token: SecretStr | None = None
    whatsapp_phone_number_id: str | None = None

    # GET /webhook verification
    whatsapp_verify_token: SecretStr | None = None

    # X-Hub-Signature-256 validation
    whatsapp_app_secret: SecretStr | None = None

    # Keep this configurable because Meta API versions change.
    whatsapp_api_version: str = "v26.0"

    # HTTP timeout for outbound Meta API calls.
    whatsapp_timeout_seconds: float = 10.0

    def validate_production_config(self) -> None:
        """Validate configuration required for a real WhatsApp deployment."""

        missing: list[str] = []

        if self.whatsapp_access_token is None:
            missing.append("WHATSAPP_ACCESS_TOKEN")

        if not self.whatsapp_phone_number_id:
            missing.append("WHATSAPP_PHONE_NUMBER_ID")

        if self.whatsapp_verify_token is None:
            missing.append("WHATSAPP_VERIFY_TOKEN")

        if self.whatsapp_app_secret is None:
            missing.append("WHATSAPP_APP_SECRET")

        if missing:
            raise RuntimeError(
                "Missing WhatsApp production configuration: "
                + ", ".join(missing)
            )


@lru_cache
def get_whatsapp_settings() -> WhatsAppSettings:
    return WhatsAppSettings()