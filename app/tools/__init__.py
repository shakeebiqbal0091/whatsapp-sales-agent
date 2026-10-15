
from langchain_core.tools import BaseTool
from sqlalchemy.orm import Session

from app.config import get_settings
from app.integrations.inventory_client import InventoryClient
from app.tools.customer_tools import build_customer_tools
from app.tools.escalation_tools import build_escalation_tools
from app.tools.product_tools import build_product_tools


def build_tools(
    session: Session,
    customer_id: int,
    conversation_id: int,
    currency: str,
    *,
    use_inventory_api: bool | None = None,
) -> list[BaseTool]:
    """Build tools using the configured product source."""
    settings = get_settings()
    inventory_base_url = settings.inventory_api_base_url
    inventory_token = (
        settings.inventory_service_token.get_secret_value()
        if settings.inventory_service_token
        else None
    )

    if use_inventory_api is None:
        use_inventory_api = bool(inventory_base_url or inventory_token)

    inventory_client = None

    if use_inventory_api:
        if (
            not inventory_base_url
            or not inventory_base_url.strip()
            or not inventory_token
            or not inventory_token.strip()
        ):
            raise RuntimeError(
                "INVENTORY_API_BASE_URL and INVENTORY_SERVICE_TOKEN are required."
            )

        inventory_client = InventoryClient(
            base_url=inventory_base_url,
            token=inventory_token,
        )

    return [
        *build_product_tools(session, currency, inventory_client),
        *build_customer_tools(session, customer_id, conversation_id),
        *build_escalation_tools(session, conversation_id),
    ]
