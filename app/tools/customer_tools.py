"""Customer tools. customer_id / conversation_id are bound server-side — the LLM cannot supply them."""
import logging

from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.services.customer_service import CustomerService

logger = logging.getLogger(__name__)


class CreateLeadArgs(BaseModel):
    interest: str = Field(
        min_length=1,
        max_length=500,
        description="What the customer wants, e.g. '2x Logitech K380 Wireless Keyboard'.",
    )


def build_customer_tools(session: Session, customer_id: int, conversation_id: int) -> list[BaseTool]:
    service = CustomerService(session)

    @tool("create_lead", args_schema=CreateLeadArgs)
    def create_lead(interest: str) -> dict:
        """Record a sales lead for the current customer when they show clear buying interest (e.g. want to order). Does NOT place an order."""
        lead = service.create_lead(customer_id, conversation_id, interest)
        logger.info("tool create_lead lead_id=%s", lead.id)
        return {"created": True, "lead_id": lead.id}

    return [create_lead]
