import pytest
from sqlalchemy import select

from app.database.models import Conversation, Customer, Message
from app.services.conversation_service import ConversationService
from app.services.customer_service import CustomerService
from scripts import escalations as esc

pytestmark = pytest.mark.anyio
PHONE = "+923001234567"


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class FakeClient:
    def __init__(self, ok: bool = True) -> None:
        self.ok, self.sent = ok, []

    async def send_text(self, to_phone: str, body: str) -> bool:
        self.sent.append((to_phone, body))
        return self.ok


def make_escalated(session, phone: str = PHONE, text: str = "I want a refund") -> int:
    customer = CustomerService(session).identify(phone)
    service = ConversationService(session)
    conversation = service.get_or_open(customer.id)
    service.add_message(conversation.id, "user", text)
    service.escalate(conversation.id, "refund requested")
    session.commit()
    return conversation.id


def test_list_shows_only_escalated(session):
    cid = make_escalated(session)
    other = CustomerService(session).identify("+923009999999")
    ConversationService(session).get_or_open(other.id)
    session.commit()
    rows = esc.list_escalated(session)
    assert [(r.conversation_id, r.phone, r.reason, r.last_customer_message) for r in rows] == [
        (cid, PHONE, "refund requested", "I want a refund")
    ]


def test_resolve_closes_and_bot_gets_fresh_conversation(session):
    cid = make_escalated(session)
    assert esc.resolve(session, "+92 300 1234567") == 1
    assert session.get(Conversation, cid).status == "closed"
    customer = session.scalar(select(Customer).where(Customer.phone == PHONE))
    fresh = ConversationService(session).get_or_open(customer.id)
    assert fresh.id != cid and fresh.status == "open"
    assert esc.resolve(session, PHONE) == 0  # nothing left to resolve


async def test_reply_sends_and_records_only_for_escalated(session):
    client = FakeClient()
    cid = make_escalated(session)
    assert await esc.reply(session, client, PHONE, "  Refund approved.  ")
    assert client.sent == [(PHONE, "Refund approved.")]
    last = session.scalars(select(Message).where(Message.conversation_id == cid).order_by(Message.id.desc())).first()
    assert (last.role, last.content) == ("assistant", "Refund approved.")


async def test_reply_refuses_non_escalated_empty_or_failed_send(session):
    client = FakeClient()
    customer = CustomerService(session).identify(PHONE)
    ConversationService(session).get_or_open(customer.id)
    session.commit()
    assert not await esc.reply(session, client, PHONE, "hello")  # open conversation: bot's territory
    make_escalated(session)
    assert not await esc.reply(session, client, PHONE, "   ")
    failing = FakeClient(ok=False)
    assert not await esc.reply(session, failing, PHONE, "hi")
    assert session.scalar(select(Message.id).where(Message.content == "hi")) is None  # not recorded if not sent
