from langchain_core.tools import BaseTool
from sqlalchemy.orm import Session

from app.tools.customer_tools import build_customer_tools
from app.tools.escalation_tools import build_escalation_tools
from app.tools.product_tools import build_product_tools


def build_tools(
    session: Session, customer_id: int, conversation_id: int, currency: str
) -> list[BaseTool]:
    """All tools for one request, bound to this session/customer/conversation."""
    return [
        *build_product_tools(session, currency),
        *build_customer_tools(session, customer_id, conversation_id),
        *build_escalation_tools(session, conversation_id),
    ]
