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
async def test_duplicate_escalated_webhook_sends_one_handoff_reply(
    session_factory, settings, monkeypatch
):
    from sqlalchemy import func, select

    from app.database.models import Conversation, Customer, Message
    from app.services.chat_service import HANDOFF_REPLY
    from app.services.conversation_service import ConversationService
    from app.services.customer_service import CustomerService
    from app.whatsapp.rate_limit import Decision

    phone = "+923001234567"
    with session_factory() as session:
        customer = CustomerService(session).identify(phone)
        conversations = ConversationService(session)
        conversation = conversations.get_or_open(customer.id)
        conversations.add_message(conversation.id, "user", "Pending human request")
        conversations.escalate(conversation.id, "human review")
        session.commit()
        escalated_id = conversation.id

    class AllowLimiter:
        @staticmethod
        def check(_key):
            return Decision.ALLOW

    class FakeWhatsAppClient:
        def __init__(self):
            self.sent = []

        async def send_text(self, _phone, body):
            self.sent.append(body)
            return True

    client = FakeWhatsAppClient()
    monkeypatch.setattr(webhook, "get_rate_limiter", lambda: AllowLimiter())
    message = IncomingMessage(
        message_id="wamid.ESCALATED_DUPLICATE_TEST",
        phone=phone,
        text="Is anyone there?",
    )

    await webhook.process_message(message, session_factory, None, settings, client)
    await webhook.process_message(message, session_factory, None, settings, client)

    assert client.sent == [HANDOFF_REPLY]
    with session_factory() as session:
        assert session.scalar(select(func.count(Conversation.id))) == 1
        conversation = session.get(Conversation, escalated_id)
        assert conversation.status == "escalated"
        messages = list(
            session.scalars(
                select(Message)
                .where(Message.conversation_id == escalated_id)
                .order_by(Message.id)
            )
        )
        assert len(messages) == 3
        assert messages[-1].content == HANDOFF_REPLY


@pytest.mark.anyio
async def test_new_question_uses_separate_conversation_and_preserves_escalation(
    session_factory, settings, monkeypatch
):
    from langchain_core.messages import AIMessage, HumanMessage
    from sqlalchemy import select

    from app.database.models import Conversation, Customer, Message
    from app.services import chat_service
    from app.services.chat_service import HANDOFF_REPLY
    from app.services.conversation_service import ConversationService
    from app.services.customer_service import CustomerService
    from app.whatsapp.rate_limit import Decision

    with session_factory() as session:
        customer = CustomerService(session).identify("+923001234567")
        conversations = ConversationService(session)
        escalated = conversations.get_or_open(customer.id)
        conversations.add_message(escalated.id, "user", "Pending human request")
        conversations.escalate(escalated.id, "human review")
        session.commit()
        customer_id = customer.id
        escalated_id = escalated.id

    with session_factory() as session:
        initial_escalation = session.get(Conversation, escalated_id)
        original_status = initial_escalation.status
        original_history = [
            (message.role, message.content)
            for message in session.scalars(
                select(Message)
                .where(Message.conversation_id == escalated_id)
                .order_by(Message.id)
            )
        ]

    graph_inputs = []
    graph_conversation_ids = []
    assistant_reply = "I can check Notebook A4 for you."

    class FakeGraph:
        def invoke(self, state, config):
            human_inputs = [
                message.content
                for message in state["messages"]
                if isinstance(message, HumanMessage)
            ]
            graph_inputs.extend(human_inputs)
            graph_conversation_ids.append(state["conversation_id"])
            return {
                "messages": [
                    *state["messages"],
                    AIMessage(content=assistant_reply),
                ]
            }

    monkeypatch.setattr(
        chat_service,
        "build_sales_graph",
        lambda *_args, **_kwargs: FakeGraph(),
    )

    class AllowLimiter:
        @staticmethod
        def check(_key):
            return Decision.ALLOW

    class FakeWhatsAppClient:
        def __init__(self):
            self.sent = []

        async def send_text(self, _phone, body):
            self.sent.append(body)
            return True

    monkeypatch.setattr(webhook, "get_rate_limiter", lambda: AllowLimiter())
    client = FakeWhatsAppClient()
    message = IncomingMessage(
        message_id="wamid.NEW_QUESTION_TEST",
        phone="+923001234567",
        text="New question: Do you have Notebook A4?",
    )

    await webhook.process_message(message, session_factory, None, settings, client)

    assert graph_inputs == ["Do you have Notebook A4?"]
    assert graph_conversation_ids[0] != escalated_id
    assert client.sent == [assistant_reply]

    with session_factory() as session:
        original = session.get(Conversation, escalated_id)
        assert original.status == original_status == "escalated"
        assert [
            (item.role, item.content)
            for item in session.scalars(
                select(Message)
                .where(Message.conversation_id == escalated_id)
                .order_by(Message.id)
            )
        ] == original_history

        new_conversation = session.get(Conversation, graph_conversation_ids[0])
        assert new_conversation.customer_id == customer_id
        assert new_conversation.status == "open"
        assert [
            (item.role, item.content)
            for item in session.scalars(
                select(Message)
                .where(Message.conversation_id == graph_conversation_ids[0])
                .order_by(Message.id)
            )
        ] == [
            ("user", "Do you have Notebook A4?"),
            ("assistant", assistant_reply),
        ]
        assert HANDOFF_REPLY not in [
            item.content
            for item in session.scalars(
                select(Message).where(Message.conversation_id == escalated_id)
            )
        ]


@pytest.mark.anyio
async def test_unprefixed_webhook_message_on_escalation_uses_handoff(
    session_factory, settings, monkeypatch
):
    from sqlalchemy import select

    from app.database.models import Conversation, Message
    from app.services import chat_service
    from app.services.chat_service import HANDOFF_REPLY
    from app.services.conversation_service import ConversationService
    from app.services.customer_service import CustomerService
    from app.whatsapp.rate_limit import Decision

    phone = "+923001234567"
    with session_factory() as session:
        customer = CustomerService(session).identify(phone)
        conversations = ConversationService(session)
        conversation = conversations.get_or_open(customer.id)
        conversations.add_message(conversation.id, "user", "Pending human request")
        conversations.escalate(conversation.id, "human review")
        session.commit()
        escalated_id = conversation.id

    graph_calls = []

    def unexpected_graph(*_args, **_kwargs):
        graph_calls.append(True)
        raise AssertionError("unprefixed escalated messages must not invoke the graph")

    monkeypatch.setattr(chat_service, "build_sales_graph", unexpected_graph)

    class AllowLimiter:
        @staticmethod
        def check(_key):
            return Decision.ALLOW

    class FakeWhatsAppClient:
        def __init__(self):
            self.sent = []

        async def send_text(self, _phone, body):
            self.sent.append(body)
            return True

    monkeypatch.setattr(webhook, "get_rate_limiter", lambda: AllowLimiter())
    client = FakeWhatsAppClient()
    message = IncomingMessage(
        message_id="wamid.UNPREFIXED_ESCALATED_TEST",
        phone=phone,
        text="Can someone help me?",
    )

    await webhook.process_message(message, session_factory, None, settings, client)

    assert client.sent == [HANDOFF_REPLY]
    assert graph_calls == []
    with session_factory() as session:
        conversation = session.get(Conversation, escalated_id)
        assert conversation.status == "escalated"
        assert [
            item.content
            for item in session.scalars(
                select(Message).where(Message.conversation_id == escalated_id)
            )
        ][-1] == HANDOFF_REPLY


@pytest.mark.anyio
async def test_duplicate_rate_limited_event_sends_only_one_notification(
    session_factory, settings, monkeypatch
):
    from app.whatsapp.rate_limit import Decision, RATE_LIMIT_REPLY

    class NotifyLimiter:
        def __init__(self):
            self.checks = 0

        def check(self, _key):
            self.checks += 1
            return Decision.NOTIFY

    class FakeWhatsAppClient:
        def __init__(self):
            self.sent = []

        async def send_text(self, _phone, body):
            self.sent.append(body)
            return True

    limiter = NotifyLimiter()
    client = FakeWhatsAppClient()
    monkeypatch.setattr(webhook, "get_rate_limiter", lambda: limiter)
    message = IncomingMessage(
        message_id="wamid.RATE_LIMIT_DUPLICATE_TEST",
        phone="923001234567",
        text="Rate-limited unique event",
    )

    await webhook.process_message(message, session_factory, None, settings, client)
    await webhook.process_message(message, session_factory, None, settings, client)

    assert client.sent == [RATE_LIMIT_REPLY]
    assert limiter.checks == 1


@pytest.mark.anyio
async def test_first_rate_limited_event_sends_notification_without_chat(
    session_factory, settings, monkeypatch
):
    from app.whatsapp.rate_limit import Decision, RATE_LIMIT_REPLY

    class NotifyLimiter:
        @staticmethod
        def check(_key):
            return Decision.NOTIFY

    class FakeWhatsAppClient:
        def __init__(self):
            self.sent = []

        async def send_text(self, _phone, body):
            self.sent.append(body)
            return True

    def unexpected_chat(*_args, **_kwargs):
        raise AssertionError("rate-limited event must not invoke ChatService")

    monkeypatch.setattr(webhook, "get_rate_limiter", lambda: NotifyLimiter())
    monkeypatch.setattr(webhook, "_handle_claimed_sync", unexpected_chat)
    client = FakeWhatsAppClient()
    message = IncomingMessage(
        message_id="wamid.RATE_LIMIT_UNIQUE_TEST",
        phone="923001234567",
        text="Rate-limited unique event",
    )

    await webhook.process_message(message, session_factory, None, settings, client)

    assert client.sent == [RATE_LIMIT_REPLY]


@pytest.mark.anyio
async def test_process_message_sends_fallback_on_failure(monkeypatch):
    """Processing failure should send the fallback reply."""

    message = IncomingMessage(
        message_id="wamid.BACKGROUND_FAILURE_TEST",
        phone="923001234567",
        text="Hello",
    )

    async def fake_run_in_threadpool(func, *args, **kwargs):
        if func is webhook._claim_event_sync:
            return True
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