"""One customer turn end-to-end. Reused by /chat now and the WhatsApp webhook in Phase 9."""
import logging

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from sqlalchemy.orm import Session

from app.agents.sales_agent import FALLBACK_REPLY
from app.config import Settings
from app.graph.sales_graph import MAX_GRAPH_STEPS, build_sales_graph
from app.services.conversation_service import ESCALATED, ConversationService
from app.services.customer_service import CustomerService

logger = logging.getLogger(__name__)

HANDOFF_REPLY = "Our team has your request and will get back to you here shortly."


def _text(content: str | list) -> str:
    if isinstance(content, str):
        return content.strip()
    parts = [b.get("text", "") if isinstance(b, dict) else str(b) for b in content]
    return "".join(parts).strip()


class ChatService:
    def __init__(self, session: Session, llm: BaseChatModel, settings: Settings) -> None:
        self.session = session
        self.llm = llm
        self.settings = settings
        self.customers = CustomerService(session)
        self.conversations = ConversationService(session)

    def handle_message(self, phone: str, text: str) -> str:
        customer = self.customers.identify(phone)
        conversation = self.conversations.get_or_open(customer.id)
        logger.info(
            "message received customer_id=%s conversation_id=%s chars=%d",
            customer.id, conversation.id, len(text),
        )

        history = self.conversations.history(conversation.id, self.settings.history_message_limit)
        self.conversations.add_message(conversation.id, "user", text)
        self.session.commit()  # the customer's message is never lost, even if the agent fails

        # Already handed to a human: don't let the bot talk over the team.
        if conversation.status == ESCALATED:
            self.conversations.add_message(conversation.id, "assistant", HANDOFF_REPLY)
            self.session.commit()
            return HANDOFF_REPLY

        prior: list[BaseMessage] = [
            HumanMessage(content=c) if role == "user" else AIMessage(content=c) for role, c in history
        ]
        try:
            graph = build_sales_graph(
                self.llm, self.session, customer.id, conversation.id, self.settings.currency
            )
            result = graph.invoke(
                {
                    "messages": [*prior, HumanMessage(content=text)],
                    "customer_id": customer.id,
                    "phone_number": phone,
                    "conversation_id": conversation.id,
                },
                config={"recursion_limit": MAX_GRAPH_STEPS},
            )
            new_messages = result["messages"][len(prior) + 1 :]
            reply = _text(new_messages[-1].content) if new_messages else ""
            if not reply:
                raise ValueError("agent produced an empty reply")
        except Exception:
            # Never expose raw errors to customers (CLAUDE.md §25); log the real one.
            logger.exception("agent failure customer_id=%s conversation_id=%s", customer.id, conversation.id)
            self.session.rollback()
            return FALLBACK_REPLY

        for message in new_messages[:-1]:
            if isinstance(message, ToolMessage):
                self.conversations.add_message(conversation.id, "tool", _text(message.content))
        self.conversations.add_message(conversation.id, "assistant", reply)
        self.session.commit()
        return reply
