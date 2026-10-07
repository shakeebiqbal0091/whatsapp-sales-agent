from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.models import Conversation, Message


class ConversationRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, conversation_id: int) -> Conversation | None:
        return self.session.get(Conversation, conversation_id)

    def get_latest_active(self, customer_id: int) -> Conversation | None:
        return self.session.scalar(
            select(Conversation)
            .where(Conversation.customer_id == customer_id, Conversation.status != "closed")
            .order_by(Conversation.id.desc())
            .limit(1)
        )

    def add(self, customer_id: int) -> Conversation:
        conversation = Conversation(customer_id=customer_id, status="open")
        self.session.add(conversation)
        self.session.flush()
        return conversation

    def add_message(self, conversation_id: int, role: str, content: str) -> Message:
        message = Message(conversation_id=conversation_id, role=role, content=content)
        self.session.add(message)
        self.session.flush()
        return message

    def recent_messages(
        self, conversation_id: int, roles: tuple[str, ...], limit: int
    ) -> list[Message]:
        rows = self.session.scalars(
            select(Message)
            .where(Message.conversation_id == conversation_id, Message.role.in_(roles))
            .order_by(Message.id.desc())
            .limit(limit)
        )
        return list(reversed(list(rows)))
