"""Focused tests for voice-note parsing and WhatsApp media API helpers."""
import json

import httpx
import pytest
from pydantic import SecretStr

from app.whatsapp.client import WhatsAppClient
from app.whatsapp.parser import parse_incoming
from app.whatsapp.settings import WhatsAppSettings

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


def settings() -> WhatsAppSettings:
    return WhatsAppSettings(
        _env_file=None,
        whatsapp_access_token=SecretStr("test-token"),
        whatsapp_phone_number_id="123456789",
        whatsapp_api_version="v26.0",
        whatsapp_timeout_seconds=5,
    )


def test_parser_accepts_audio_with_media_id():
    payload = {
        "entry": [{"changes": [{"value": {"messages": [{
            "from": "923001234567",
            "id": "wamid.AUDIO001",
            "type": "audio",
            "audio": {"id": "media-123", "mime_type": "audio/ogg; codecs=opus", "voice": True},
        }]}}]}]
    }
    messages = parse_incoming(payload)
    assert len(messages) == 1
    assert messages[0].message_type == "audio"
    assert messages[0].media_id == "media-123"
    assert messages[0].mime_type == "audio/ogg; codecs=opus"
    assert messages[0].phone == "+923001234567"
    assert messages[0].text is None


@pytest.mark.anyio
async def test_download_media_metadata_then_audio():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/media-123"):
            return httpx.Response(200, json={
                "url": "https://lookaside.fbsbx.com/whatsapp_business/attachments/?mid=media-123",
                "mime_type": "audio/ogg; codecs=opus",
                "file_size": 4,
            })
        if request.url.host == "lookaside.fbsbx.com":
            assert request.headers["Authorization"] == "Bearer test-token"
            return httpx.Response(200, content=b"opus")
        raise AssertionError(f"Unexpected request: {request.url}")

    client = WhatsAppClient(settings(), transport=httpx.MockTransport(handler), max_attempts=1)
    result = await client.download_media("media-123")
    assert result == (b"opus", "audio/ogg; codecs=opus")


@pytest.mark.anyio
async def test_download_media_rejects_unexpected_host():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"url": "https://example.com/unsafe", "mime_type": "audio/ogg"})

    client = WhatsAppClient(settings(), transport=httpx.MockTransport(handler), max_attempts=1)
    assert await client.download_media("media-123") is None


@pytest.mark.anyio
async def test_send_audio_uploads_then_sends_message():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path.endswith("/media"):
            assert request.headers["Authorization"] == "Bearer test-token"
            assert b"messaging_product" in request.content
            assert b"audio/ogg" in request.content
            return httpx.Response(200, json={"id": "uploaded-media-id"})
        if request.url.path.endswith("/messages"):
            body = json.loads(request.content)
            assert body["type"] == "audio"
            assert body["audio"]["id"] == "uploaded-media-id"
            assert body["to"] == "923001234567"
            return httpx.Response(200, json={"messages": [{"id": "wamid.OUTAUDIO"}]})
        raise AssertionError(f"Unexpected request: {request.url}")

    client = WhatsAppClient(settings(), transport=httpx.MockTransport(handler), max_attempts=1)
    assert await client.send_audio("+923001234567", b"fake-ogg") is True
    assert len(seen) == 2

@pytest.mark.anyio
async def test_audio_message_transcribes_uses_agent_and_sends_voice_reply(monkeypatch):
    from app.whatsapp import webhook
    from app.whatsapp.parser import IncomingMessage
    from app.whatsapp.rate_limit import Decision

    captured = []

    class FakeLimiter:
        def check(self, phone):
            return Decision.ALLOW

    class FakeClient:
        async def download_media(self, media_id):
            assert media_id == "media-voice"
            return b"fake-audio", "audio/ogg; codecs=opus"

        async def send_audio(self, phone, audio):
            captured.append(("audio", phone, audio))
            return True

        async def send_text(self, phone, text):
            captured.append(("text", phone, text))
            return True

    async def fake_transcribe(audio, filename, mime_type, app_settings):
        return "Do you have the keyboard in stock?"

    async def fake_synthesize(text, app_settings):
        assert text == "Yes, it is in stock."
        return b"reply-ogg"
    async def fake_threadpool(func, *args, **kwargs):
        if func is webhook._claim_event:
            return True

        message = args[0]
        captured.append(("transcript", message.text))
        return "Yes, it is in stock."

    monkeypatch.setattr(webhook, "get_rate_limiter", lambda: FakeLimiter())
    monkeypatch.setattr(webhook, "transcribe_audio", fake_transcribe)
    monkeypatch.setattr(webhook, "synthesize_speech", fake_synthesize)
    monkeypatch.setattr(webhook, "run_in_threadpool", fake_threadpool)
    monkeypatch.setattr(webhook, "_claim_event", lambda *args: True)

    message = IncomingMessage(
        message_id="wamid.VOICE001",
        phone="+923001234567",
        message_type="audio",
        media_id="media-voice",
        mime_type="audio/ogg; codecs=opus",
    )
    await webhook.process_message(message, None, None, object(), FakeClient())

    assert ("transcript", "Do you have the keyboard in stock?") in captured
    assert ("audio", "+923001234567", b"reply-ogg") in captured
    assert not any(item[0] == "text" for item in captured)


@pytest.mark.anyio
async def test_audio_message_falls_back_to_text_if_voice_reply_fails(monkeypatch):
    from app.whatsapp import webhook
    from app.whatsapp.parser import IncomingMessage
    from app.whatsapp.rate_limit import Decision

    sent = []

    class FakeLimiter:
        def check(self, phone):
            return Decision.ALLOW

    class FakeClient:
        async def download_media(self, media_id):
            return b"fake-audio", "audio/ogg"

        async def send_audio(self, phone, audio):
            return False

        async def send_text(self, phone, text):
            sent.append((phone, text))
            return True

    async def fake_transcribe(*args):
        return "Hello"

    async def fake_synthesize(*args):
        return b"reply-ogg"
    
    async def fake_threadpool(func, *args, **kwargs):
        if func is webhook._claim_event:
            return True

        return "Hello! How can I help?"
    
    monkeypatch.setattr(webhook, "get_rate_limiter", lambda: FakeLimiter())
    monkeypatch.setattr(webhook, "transcribe_audio", fake_transcribe)
    monkeypatch.setattr(webhook, "synthesize_speech", fake_synthesize)
    monkeypatch.setattr(webhook, "run_in_threadpool", fake_threadpool)
    monkeypatch.setattr(webhook, "_claim_event", lambda *args: True)
    

    message = IncomingMessage(
        message_id="wamid.VOICE002",
        phone="+923001234567",
        message_type="audio",
        media_id="media-voice",
        mime_type="audio/ogg",
    )
    await webhook.process_message(message, None, None, object(), FakeClient())
    assert sent == [("+923001234567", "Hello! How can I help?")]
