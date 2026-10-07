import logging

from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.services.conversation_service import ConversationService

logger = logging.getLogger(__name__)


class EscalateArgs(BaseModel):
    reason: str = Field(min_length=1, max_length=500, description="Short internal reason for the handoff.")


def build_escalation_tools(session: Session, conversation_id: int) -> list[BaseTool]:
    service = ConversationService(session)

    @tool("escalate_to_human", args_schema=EscalateArgs)
    def escalate_to_human(reason: str) -> dict:
        """Hand the conversation to a human team member. Use when the customer asks for a human, is angry or abusive, wants a refund, wants to place an order, or the request cannot be handled safely."""
        ok = service.escalate(conversation_id, reason)
        logger.info("tool escalate_to_human ok=%s", ok)
        return {"escalated": ok}

    return [escalate_to_human]
