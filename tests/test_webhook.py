import hashlib
import hmac
import json

from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.config import get_settings
from app.main import app
from app.whatsapp.client import WhatsAppClient
from app.whatsapp.settings import get_whatsapp_settings


VERIFY_TOKEN = "test-verify-token"
APP_SECRET = "test-app-secret"


def webhook_settings():
    from app.whatsapp.settings import WhatsAppSettings

    return WhatsAppSettings(
        _env_file=None,
        whatsapp_verify_token=SecretStr(VERIFY_TOKEN),
        whatsapp_app_secret=SecretStr(APP_SECRET),
        whatsapp_access_token=SecretStr("test-access-token"),
        whatsapp_phone_number_id="123456789",
        whatsapp_api_version="v26.0",
    )


def sign(body: bytes) -> str:
    digest = hmac.new(
        APP_SECRET.encode(),
        body,
        hashlib.sha256,
    ).hexdigest()

    return f"sha256={digest}"


def payload(
    message_id: str = "wamid.TEST001",
    text: str = "Hello",
    phone: str = "923001234567",
):
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {
                                    "from": phone,
                                    "id": message_id,
                                    "type": "text",
                                    "text": {
                                        "body": text,
                                    },
                                }
                            ]
                        }
                    }
                ]
            }
        ],
    }


def setup_overrides(
    session_factory,
    llm,
    fake_client,
):
    from app.database.connection import get_session_factory
    from app.dependencies import get_llm

    app.dependency_overrides[get_whatsapp_settings] = webhook_settings
    app.dependency_overrides[get_settings] = lambda: get_settings()
    app.dependency_overrides[get_session_factory] = lambda: session_factory
    app.dependency_overrides[get_llm] = lambda: llm

    from app.whatsapp.webhook import get_whatsapp_client

    app.dependency_overrides[get_whatsapp_client] = lambda: fake_client


def clear_overrides():
    app.dependency_overrides.clear()


def test_webhook_verification_success():
    app.dependency_overrides[get_whatsapp_settings] = webhook_settings

    try:
        response = TestClient(app).get(
            "/webhook",
            params={
                "hub.mode": "subscribe",
                "hub.verify_token": VERIFY_TOKEN,
                "hub.challenge": "123456789",
            },
        )

        assert response.status_code == 200
        assert response.text == "123456789"
    finally:
        clear_overrides()


def test_webhook_verification_wrong_token():
    app.dependency_overrides[get_whatsapp_settings] = webhook_settings

    try:
        response = TestClient(app).get(
            "/webhook",
            params={
                "hub.mode": "subscribe",
                "hub.verify_token": "wrong-token",
                "hub.challenge": "123456789",
            },
        )

        assert response.status_code == 403
    finally:
        clear_overrides()


def test_webhook_verification_wrong_mode():
    app.dependency_overrides[get_whatsapp_settings] = webhook_settings

    try:
        response = TestClient(app).get(
            "/webhook",
            params={
                "hub.mode": "not-subscribe",
                "hub.verify_token": VERIFY_TOKEN,
                "hub.challenge": "123456789",
            },
        )

        assert response.status_code == 403
    finally:
        clear_overrides()


def test_webhook_invalid_json():
    app.dependency_overrides[get_whatsapp_settings] = webhook_settings

    try:
        response = TestClient(app).post(
            "/webhook",
            content=b"{invalid json",
            headers={
                "Content-Type": "application/json",
                "X-Hub-Signature-256": sign(b"{invalid json"),
            },
        )

        assert response.status_code == 400
    finally:
        clear_overrides()


def test_webhook_rejects_invalid_signature():
    app.dependency_overrides[get_whatsapp_settings] = webhook_settings

    body = json.dumps(payload()).encode()

    try:
        response = TestClient(app).post(
            "/webhook",
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-Hub-Signature-256": "sha256=invalid",
            },
        )

        assert response.status_code == 403
    finally:
        clear_overrides()


def test_webhook_rejects_missing_signature():
    app.dependency_overrides[get_whatsapp_settings] = webhook_settings

    body = json.dumps(payload()).encode()

    try:
        response = TestClient(app).post(
            "/webhook",
            content=body,
            headers={
                "Content-Type": "application/json",
            },
        )

        assert response.status_code == 403
    finally:
        clear_overrides()


def test_webhook_accepts_valid_signature():
    app.dependency_overrides[get_whatsapp_settings] = webhook_settings

    body = json.dumps(payload()).encode()

    try:
        response = TestClient(app).post(
            "/webhook",
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-Hub-Signature-256": sign(body),
            },
        )

        assert response.status_code == 200
        assert response.json() == {"status": "ok"}
    finally:
        clear_overrides()


def test_webhook_empty_message_payload_is_acknowledged():
    app.dependency_overrides[get_whatsapp_settings] = webhook_settings

    body = json.dumps(
        {
            "object": "whatsapp_business_account",
            "entry": [],
        }
    ).encode()

    try:
        response = TestClient(app).post(
            "/webhook",
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-Hub-Signature-256": sign(body),
            },
        )

        assert response.status_code == 200
        assert response.json() == {"status": "ok"}
    finally:
        clear_overrides()



import pytest

from app.agents.sales_agent import FALLBACK_REPLY
from app.whatsapp.parser import IncomingMessage
from app.whatsapp import webhook


def test_duplicate_event_is_processed_only_once(
    session_factory,
    settings,
    monkeypatch,
):
    """The same WhatsApp event must only be processed once."""

    message = IncomingMessage(
        message_id="wamid.DUPLICATE_TEST",
        phone="923001234567",
        text="Do you have laptops?",
    )

    calls = []

    class FakeChatService:
        def __init__(self, session, llm, settings):
            pass

        def handle_message(self, phone, text):
            calls.append((phone, text))
            return "Yes, we have laptops."

    monkeypatch.setattr(
        webhook,
        "ChatService",
        FakeChatService,
    )

    fake_llm = object()

    first_result = webhook._handle_sync(
        message,
        session_factory,
        fake_llm,
        settings,
    )

    second_result = webhook._handle_sync(
        message,
        session_factory,
        fake_llm,
        settings,
    )

    assert first_result == "Yes, we have laptops."
    assert second_result is None

    # ChatService must only run once.
    assert len(calls) == 1

    assert calls[0] == (
        "923001234567",
        "Do you have laptops?",
    )


@pytest.mark.anyio
async def test_process_message_sends_fallback_on_failure(monkeypatch):
    """Processing failure should send the fallback reply."""

    message = IncomingMessage(
        message_id="wamid.BACKGROUND_FAILURE_TEST",
        phone="923001234567",
        text="Hello",
    )

    async def fake_run_in_threadpool(func, *args, **kwargs):
        raise RuntimeError("Simulated processing failure")

    monkeypatch.setattr(
        webhook,
        "run_in_threadpool",
        fake_run_in_threadpool,
    )

    sent_messages = []

    class FakeWhatsAppClient:
        async def send_text(self, phone, text):
            sent_messages.append((phone, text))
            return True

    await webhook.process_message(
        message=message,
        session_factory=None,
        llm=None,
        settings=None,
        client=FakeWhatsAppClient(),
    )

    assert sent_messages == [
        (
            "923001234567",
            FALLBACK_REPLY,
        )
    ]