"""Minimal human hand-off for escalated conversations (v0.1, no UI yet).

    python -m scripts.escalations list
    python -m scripts.escalations reply +923001234567 "Hi, this is Ali from the shop. Refund approved." [--resolve]
    python -m scripts.escalations resolve +923001234567      # close it: the bot serves that customer again

Why: once a conversation is escalated the bot only sends the fixed handoff reply, and nothing else could
reset it. `reply` sends through the same WhatsApp client (only into escalated conversations); `resolve`
sets status=closed, so the customer's next message opens a fresh conversation."""
import argparse
import asyncio
import logging
import sys
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.models import Conversation, Customer, Message
from app.schemas.customer import normalize_phone

logger = logging.getLogger(__name__)
ESCALATED, CLOSED = "escalated", "closed"


@dataclass(frozen=True)
class EscalationRow:
    conversation_id: int
    phone: str
    reason: str | None
    since: datetime
    last_customer_message: str


def list_escalated(session: Session) -> list[EscalationRow]:
    rows = session.execute(
        select(Conversation, Customer.phone)
        .join(Customer, Customer.id == Conversation.customer_id)
        .where(Conversation.status == ESCALATED)
        .order_by(Conversation.updated_at)
    ).all()
    out: list[EscalationRow] = []
    for conversation, phone in rows:
        last = session.scalar(
            select(Message.content)
            .where(Message.conversation_id == conversation.id, Message.role == "user")
            .order_by(Message.id.desc()).limit(1)
        )
        out.append(EscalationRow(conversation.id, phone, conversation.escalation_reason, conversation.updated_at, (last or "")[:80]))
    return out


def _escalated_for(session: Session, phone: str) -> list[Conversation]:
    return list(session.scalars(
        select(Conversation).join(Customer, Customer.id == Conversation.customer_id)
        .where(Customer.phone == normalize_phone(phone), Conversation.status == ESCALATED)
    ))


def resolve(session: Session, phone: str) -> int:
    """Close the customer's escalated conversations. Returns how many were closed."""
    conversations = _escalated_for(session, phone)
    for conversation in conversations:
        conversation.status = CLOSED
    session.commit()
    logger.info("escalations resolved count=%d", len(conversations))
    return len(conversations)


async def reply(session: Session, client, phone: str, text: str) -> bool:
    """Send a human reply to a customer with an escalated conversation, and record it. False if not sent."""
    conversations = _escalated_for(session, phone)
    if not conversations or not text.strip():
        return False
    if not await client.send_text(normalize_phone(phone), text.strip()):
        return False
    session.add(Message(conversation_id=conversations[-1].id, role="assistant", content=text.strip()))
    session.commit()
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list")
    p_reply = sub.add_parser("reply")
    p_reply.add_argument("phone")
    p_reply.add_argument("text")
    p_reply.add_argument("--resolve", action="store_true", help="also close the conversation after replying")
    p_resolve = sub.add_parser("resolve")
    p_resolve.add_argument("phone")
    args = parser.parse_args(argv)

    from app.database.connection import get_session_factory

    with get_session_factory()() as session:
        if args.command == "list":
            rows = list_escalated(session)
            for r in rows:
                print(f"{r.since:%Y-%m-%d %H:%M} conv={r.conversation_id} {r.phone} reason={r.reason!r} last={r.last_customer_message!r}")
            print(f"{len(rows)} escalated conversation(s)")
            return 0
        if args.command == "resolve":
            closed = resolve(session, args.phone)
            print(f"closed {closed} conversation(s)")
            return 0 if closed else 1
        from app.whatsapp.client import WhatsAppClient
        from app.whatsapp.settings import get_whatsapp_settings

        sent = asyncio.run(reply(session, WhatsAppClient(get_whatsapp_settings()), args.phone, args.text))
        print("sent" if sent else "NOT sent (no escalated conversation for that number, empty text, or Meta rejected it; see log)")
        if sent and args.resolve:
            resolve(session, args.phone)
        return 0 if sent else 1


if __name__ == "__main__":
    sys.exit(main())
