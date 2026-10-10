"""Outbound WhatsApp Cloud API client: bounded requests and no secrets in logs."""
import asyncio
import logging
from urllib.parse import urlparse

import httpx

from app.whatsapp.settings import WhatsAppSettings

logger = logging.getLogger(__name__)
MAX_BODY_CHARS = 4096
MAX_ERROR_MESSAGE_CHARS = 200
MAX_AUDIO_BYTES = 16 * 1024 * 1024
RETRY_STATUSES = {429, 500, 502, 503, 504}


def _allowed_media_url(url: str) -> bool:
    """Restrict Meta-returned media URLs to expected HTTPS Facebook media hosts."""
    try:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        allowed = host == "lookaside.fbsbx.com" or host.endswith(".fbcdn.net") or host == "fbcdn.net"
        return parsed.scheme == "https" and allowed and not parsed.username and not parsed.password
    except ValueError:
        return False


class WhatsAppClient:
    def __init__(
        self,
        settings: WhatsAppSettings,
        transport: httpx.AsyncBaseTransport | None = None,
        max_attempts: int = 3,
        backoff_seconds: float = 0.5,
    ) -> None:
        self._settings = settings
        self._transport = transport
        self._max_attempts = max_attempts
        self._backoff = backoff_seconds

    def _credentials(self) -> tuple[str, str] | None:
        token = self._settings.whatsapp_access_token
        phone_number_id = self._settings.whatsapp_phone_number_id
        if token is None or not phone_number_id:
            logger.error("whatsapp operation skipped: required credentials are not configured")
            return None
        return token.get_secret_value(), phone_number_id

    async def send_text(self, to_phone: str, body: str) -> bool:
        """Send a text message. Returns True only if Meta accepted it. Never raises."""
        credentials = self._credentials()
        if credentials is None:
            return False
        token, phone_number_id = credentials
        url = f"https://graph.facebook.com/{self._settings.whatsapp_api_version}/{phone_number_id}/messages"
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to_phone.lstrip("+"),
            "type": "text",
            "text": {"preview_url": False, "body": body[:MAX_BODY_CHARS]},
        }
        headers = {"Authorization": f"Bearer {token}"}

        async with httpx.AsyncClient(timeout=self._settings.whatsapp_timeout_seconds, transport=self._transport) as http:
            for attempt in range(1, self._max_attempts + 1):
                try:
                    response = await http.post(url, json=payload, headers=headers)
                except httpx.TransportError as exc:
                    logger.warning("whatsapp send transport error attempt=%d type=%s", attempt, type(exc).__name__)
                else:
                    if response.is_success:
                        return self._accepted(response)
                    if response.status_code not in RETRY_STATUSES:
                        logger.error("whatsapp send rejected status=%d error=%s", response.status_code, self._error_message(response))
                        return False
                    logger.warning("whatsapp send retryable status=%d attempt=%d", response.status_code, attempt)
                if attempt < self._max_attempts:
                    await asyncio.sleep(self._backoff * 2 ** (attempt - 1))
        logger.error("whatsapp send failed after %d attempts", self._max_attempts)
        return False

    async def download_media(self, media_id: str) -> tuple[bytes, str] | None:
        """Download incoming media via Meta's media metadata URL, enforcing a size cap."""
        credentials = self._credentials()
        if credentials is None or not media_id.strip():
            return None
        token, phone_number_id = credentials
        headers = {"Authorization": f"Bearer {token}"}
        metadata_url = f"https://graph.facebook.com/{self._settings.whatsapp_api_version}/{media_id}"

        try:
            async with httpx.AsyncClient(timeout=self._settings.whatsapp_timeout_seconds, transport=self._transport) as http:
                metadata_response = await http.get(
                    metadata_url,
                    headers=headers,
                    params={"phone_number_id": phone_number_id},
                )
                metadata_response.raise_for_status()
                metadata = metadata_response.json()
                media_url = metadata.get("url")
                mime_type = str(metadata.get("mime_type") or "audio/ogg")
                file_size = metadata.get("file_size")
                if isinstance(file_size, int) and file_size > MAX_AUDIO_BYTES:
                    logger.warning("incoming WhatsApp media exceeds size limit")
                    return None
                if not isinstance(media_url, str) or not _allowed_media_url(media_url):
                    logger.warning("Meta returned an unexpected media URL host")
                    return None

                media_response = await http.get(media_url, headers=headers)
                media_response.raise_for_status()
                audio_bytes = media_response.content
                if not audio_bytes or len(audio_bytes) > MAX_AUDIO_BYTES:
                    logger.warning("downloaded WhatsApp media is empty or too large")
                    return None
                return audio_bytes, mime_type
        except (httpx.HTTPError, ValueError, TypeError, KeyError) as exc:
            logger.warning("WhatsApp media download failed type=%s", type(exc).__name__)
            return None

    async def send_audio(self, to_phone: str, audio_bytes: bytes) -> bool:
        """Upload OGG/Opus audio and send it as a WhatsApp audio message."""
        credentials = self._credentials()
        if credentials is None or not audio_bytes or len(audio_bytes) > MAX_AUDIO_BYTES:
            return False
        token, phone_number_id = credentials
        headers = {"Authorization": f"Bearer {token}"}
        base_url = f"https://graph.facebook.com/{self._settings.whatsapp_api_version}"

        try:
            async with httpx.AsyncClient(timeout=self._settings.whatsapp_timeout_seconds, transport=self._transport) as http:
                upload_response = await http.post(
                    f"{base_url}/{phone_number_id}/media",
                    headers=headers,
                    data={
                        "messaging_product": "whatsapp",
                        "type": "audio/ogg; codecs=opus",
                    },
                    files={
                        "file": (
                            "reply.ogg",
                            audio_bytes,
                            "audio/ogg; codecs=opus",
                        )
                    },
                )
                if not upload_response.is_success:
                    logger.warning("WhatsApp audio upload rejected status=%d", upload_response.status_code)
                    return False
                media_id = upload_response.json().get("id")
                if not isinstance(media_id, str) or not media_id:
                    logger.warning("WhatsApp audio upload response did not contain a media id")
                    return False

                response = await http.post(
                    f"{base_url}/{phone_number_id}/messages",
                    headers=headers,
                    json={
                        "messaging_product": "whatsapp",
                        "recipient_type": "individual",
                        "to": to_phone.lstrip("+"),
                        "type": "audio",
                        "audio": {"id": media_id},
                    },
                )
                if not response.is_success:
                    logger.warning("WhatsApp audio message rejected status=%d", response.status_code)
                    return False
                return self._accepted(response)
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            logger.warning("WhatsApp audio send failed type=%s", type(exc).__name__)
            return False

    @staticmethod
    def _accepted(response: httpx.Response) -> bool:
        try:
            message_id = response.json()["messages"][0]["id"]
        except (ValueError, KeyError, IndexError, TypeError):
            logger.error("whatsapp send: 2xx response without a message id")
            return False
        logger.info("whatsapp message accepted wamid=%s", message_id)
        return True

    @staticmethod
    def _error_message(response: httpx.Response) -> str:
        try:
            return str(response.json().get("error", {}).get("message", ""))[:MAX_ERROR_MESSAGE_CHARS]
        except (ValueError, AttributeError):
            return ""
