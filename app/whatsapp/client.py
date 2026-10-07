"""Outbound WhatsApp Cloud API client: timeouts, bounded retries, no secrets in logs."""
import asyncio
import logging

import httpx

from app.whatsapp.settings import WhatsAppSettings

logger = logging.getLogger(__name__)

# MAX_BODY_CHARS = 4096  # WhatsApp text limit
MAX_BODY_CHARS = 4096
MAX_ERROR_MESSAGE_CHARS = 200
RETRY_STATUSES = {429, 500, 502, 503, 504}


class WhatsAppClient:
    def __init__(
        self,
        settings: WhatsAppSettings,
        transport: httpx.AsyncBaseTransport | None = None,  # injected in tests
        max_attempts: int = 3,
        backoff_seconds: float = 0.5,
    ) -> None:
        self._settings = settings
        self._transport = transport
        self._max_attempts = max_attempts
        self._backoff = backoff_seconds

    async def send_text(self, to_phone: str, body: str) -> bool:
        """Send a text message. Returns True only if Meta accepted it. Never raises."""
        token = self._settings.whatsapp_access_token
        phone_number_id = self._settings.whatsapp_phone_number_id
        if token is None or not phone_number_id:
            logger.error("whatsapp send skipped: WHATSAPP_ACCESS_TOKEN / WHATSAPP_PHONE_NUMBER_ID not set")
            return False

        url = f"https://graph.facebook.com/{self._settings.whatsapp_api_version}/{phone_number_id}/messages"
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to_phone.lstrip("+"),
            "type": "text",
            "text": {"preview_url": False, "body": body[:MAX_BODY_CHARS]},
        }
        headers = {"Authorization": f"Bearer {token.get_secret_value()}"}

        async with httpx.AsyncClient(
            timeout=self._settings.whatsapp_timeout_seconds, transport=self._transport
        ) as http:
            for attempt in range(1, self._max_attempts + 1):
                try:
                    response = await http.post(url, json=payload, headers=headers)
                except httpx.TransportError as exc:  # includes timeouts
                    logger.warning("whatsapp send transport error attempt=%d type=%s", attempt, type(exc).__name__)
                else:
                    if response.is_success:
                        return self._accepted(response)
                    if response.status_code not in RETRY_STATUSES:
                        # Auth/validation errors: retrying cannot help (CLAUDE.md §57).
                        logger.error(
                            "whatsapp send rejected status=%d error=%s",
                            response.status_code, self._error_message(response),
                        )
                        return False
                    logger.warning("whatsapp send retryable status=%d attempt=%d", response.status_code, attempt)
                if attempt < self._max_attempts:
                    await asyncio.sleep(self._backoff * 2 ** (attempt - 1))

        logger.error("whatsapp send failed after %d attempts", self._max_attempts)
        return False

    @staticmethod
    def _accepted(response: httpx.Response) -> bool:
        try:
            message_id = response.json()["messages"][0]["id"]
        except (ValueError, KeyError, IndexError, TypeError):
            logger.error("whatsapp send: 2xx response without a message id")
            return False
        # logger.info("whatsapp message sent wamid=%s", message_id)
        logger.info("whatsapp message accepted wamid=%s", message_id)
        return True

    @staticmethod
    def _error_message(response: httpx.Response) -> str:
        try:
            return str(response.json().get("error", {}).get("message", ""))[:200]
        except (ValueError, AttributeError):
            return ""
