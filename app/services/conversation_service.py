import logging

from sqlalchemy.orm import Session

from app.database.models import Conversation
from app.database.repositories.conversation_repository import ConversationRepository

logger = logging.getLogger(__name__)

OPEN = "open"
ESCALATED = "escalated"
_HISTORY_ROLES = ("user", "assistant")  # tool rows are stored for audit but never replayed


class ConversationService:
    def __init__(self, session: Session) -> None:
        self.repo = ConversationRepository(session)

    def get_or_open(self, customer_id: int) -> Conversation:
        conversation = self.repo.get_latest_active(customer_id)
        if conversation is None:
            conversation = self.repo.add(customer_id)
            logger.info(
                "conversation opened conversation_id=%s customer_id=%s", conversation.id, customer_id
            )
        return conversation

    def history(self, conversation_id: int, limit: int) -> list[tuple[str, str]]:
        rows = self.repo.recent_messages(conversation_id, _HISTORY_ROLES, limit)
        return [(m.role, m.content) for m in rows]

    def add_message(self, conversation_id: int, role: str, content: str) -> None:
        self.repo.add_message(conversation_id, role, content)

    def escalate(self, conversation_id: int, reason: str) -> bool:
        """Mark the conversation for human takeover. Returns False if it doesn't exist."""
        conversation = self.repo.get(conversation_id)
        if conversation is None:
            return False
        conversation.status = ESCALATED
        conversation.escalation_reason = reason.strip()[:500]
        self.repo.session.flush()
        logger.warning(
            "conversation escalated conversation_id=%s reason=%r", conversation_id, reason[:120]
        )
        return True
