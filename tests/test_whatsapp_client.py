import json

import httpx
import pytest
from pydantic import SecretStr

from app.whatsapp.client import WhatsAppClient
from app.whatsapp.settings import WhatsAppSettings


pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    """Run async tests with asyncio only.

    WhatsAppClient uses asyncio.sleep() for retry backoff, so running these
    tests under Trio is not appropriate.
    """
    return "asyncio"


def make_settings() -> WhatsAppSettings:
    return WhatsAppSettings(
        _env_file=None,
        whatsapp_access_token=SecretStr("test-token"),
        whatsapp_phone_number_id="123456789",
        whatsapp_api_version="v21.0",
        whatsapp_timeout_seconds=5,
    )


@pytest.mark.anyio
async def test_send_text_success():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/123456789/messages")
        assert request.headers["Authorization"] == "Bearer test-token"

        body = json.loads(request.content)

        assert body["messaging_product"] == "whatsapp"
        assert body["to"] == "923001234567"
        assert body["type"] == "text"
        assert body["text"]["body"] == "Hello"

        return httpx.Response(
            200,
            json={
                "messages": [
                    {
                        "id": "wamid.OUT001",
                    }
                ]
            },
        )

    transport = httpx.MockTransport(handler)

    client = WhatsAppClient(
        make_settings(),
        transport=transport,
        max_attempts=3,
        backoff_seconds=0,
    )

    assert await client.send_text(
        "+923001234567",
        "Hello",
    ) is True


@pytest.mark.anyio
async def test_send_text_retries_500():
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1

        if attempts < 3:
            return httpx.Response(
                500,
                json={"error": {"message": "temporary"}},
            )

        return httpx.Response(
            200,
            json={
                "messages": [
                    {
                        "id": "wamid.RETRY",
                    }
                ]
            },
        )

    transport = httpx.MockTransport(handler)

    client = WhatsAppClient(
        make_settings(),
        transport=transport,
        max_attempts=3,
        backoff_seconds=0,
    )

    assert await client.send_text(
        "+923001234567",
        "Hello",
    ) is True

    assert attempts == 3


@pytest.mark.anyio
async def test_send_text_retries_429():
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1

        if attempts == 1:
            return httpx.Response(429)

        return httpx.Response(
            200,
            json={
                "messages": [
                    {
                        "id": "wamid.RATE",
                    }
                ]
            },
        )

    transport = httpx.MockTransport(handler)

    client = WhatsAppClient(
        make_settings(),
        transport=transport,
        max_attempts=3,
        backoff_seconds=0,
    )

    assert await client.send_text(
        "+923001234567",
        "Hello",
    ) is True

    assert attempts == 2


@pytest.mark.anyio
async def test_send_text_does_not_retry_401():
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1

        return httpx.Response(
            401,
            json={
                "error": {
                    "message": "invalid token",
                }
            },
        )

    transport = httpx.MockTransport(handler)

    client = WhatsAppClient(
        make_settings(),
        transport=transport,
        max_attempts=3,
        backoff_seconds=0,
    )

    assert await client.send_text(
        "+923001234567",
        "Hello",
    ) is False

    assert attempts == 1


@pytest.mark.anyio
async def test_send_text_handles_transport_error():
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1

        raise httpx.ConnectError(
            "connection failed",
            request=request,
        )

    transport = httpx.MockTransport(handler)

    client = WhatsAppClient(
        make_settings(),
        transport=transport,
        max_attempts=3,
        backoff_seconds=0,
    )

    assert await client.send_text(
        "+923001234567",
        "Hello",
    ) is False

    assert attempts == 3


@pytest.mark.anyio
async def test_send_text_rejects_malformed_success_response():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "success": True,
            },
        )

    transport = httpx.MockTransport(handler)

    client = WhatsAppClient(
        make_settings(),
        transport=transport,
        max_attempts=1,
        backoff_seconds=0,
    )

    assert await client.send_text(
        "+923001234567",
        "Hello",
    ) is False


@pytest.mark.anyio
async def test_send_text_returns_false_when_credentials_missing():
    settings = WhatsAppSettings(
        _env_file=None,
        whatsapp_access_token=None,
        whatsapp_phone_number_id=None,
    )

    client = WhatsAppClient(
        settings,
        max_attempts=1,
    )

    assert await client.send_text(
        "+923001234567",
        "Hello",
    ) is False