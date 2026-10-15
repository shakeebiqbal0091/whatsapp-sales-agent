
"""Product tools backed by the Inventory API when configured."""
import logging
import re
from typing import Any

from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.integrations.inventory_client import InventoryAPIError, InventoryClient
from app.services.sales_service import SalesService

logger = logging.getLogger(__name__)

_TOKEN = re.compile(r"[a-z0-9]+")
_STOPWORDS = frozenset(
    "a an and are can do does for get got have i in is it me my need of on or "
    "please product products sell show some something tell the there to want "
    "what with you your looking".split()
)


class SearchProductsArgs(BaseModel):
    query: str = Field(min_length=1, max_length=200)
    category: str | None = Field(default=None, max_length=80)


class ProductIdArgs(BaseModel):
    product_id: str | int = Field(
        description="Product ID returned by search_products."
    )


class CheckStockArgs(BaseModel):
    product_id: str | int = Field(
        description="Product ID returned by search_products."
    )
    quantity: int | None = Field(default=None, ge=1, le=100_000)


def _search_inventory(
    client: InventoryClient,
    query: str,
) -> list[dict[str, Any]]:
    terms = []
    for term in _TOKEN.findall(query.lower()):
        if term in _STOPWORDS:
            continue
        if len(term) > 3 and term.endswith("s"):
            term = term[:-1]
        if term not in terms:
            terms.append(term)

    products = client.list_products()
    results = []

    for product in products:
        name = product["name"]
        if terms and not any(term in name.lower() for term in terms):
            continue

        score = sum(term in name.lower() for term in terms)
        results.append((score, product))

    results.sort(key=lambda item: (-item[0], float(item[1]["price"])))
    return [product for _, product in results[:5]]


def build_product_tools(
    session: Session,
    currency: str,
    inventory_client: InventoryClient | None = None,
) -> list[BaseTool]:
    service = SalesService(session, currency)

    @tool("search_products", args_schema=SearchProductsArgs)
    def search_products(query: str, category: str | None = None) -> dict:
        """Search real products, prices and stock. Use for catalogue questions."""
        if inventory_client and category:
            return {
                "error": "Category filtering is not supported by the Inventory API."
            }

        try:
            if inventory_client:
                products = _search_inventory(inventory_client, query)
            else:
                products = [
                    p.model_dump(mode="json")
                    for p in service.search_products(query, category)
                ]

            logger.info("tool search_products results=%d", len(products))
            result = {"count": len(products), "products": products}
            if not products:
                result["note"] = "No matching products found."
            return result
        except InventoryAPIError:
            logger.warning("Inventory API product search failed")
            return {"error": "The product catalogue is temporarily unavailable."}

    @tool("get_product", args_schema=ProductIdArgs)
    def get_product(product_id: str | int) -> dict:
        """Get product details, price and stock by the returned product ID."""
        try:
            if inventory_client:
                product = inventory_client.get_product(str(product_id))
                if product is None:
                    return {"found": False, "product_id": str(product_id)}
                return {
                    "found": True,
                    "product": product,
                }

            product = service.get_product(int(product_id))
            if product is None:
                return {"found": False, "product_id": product_id}
            return {"found": True, "product": product.model_dump(mode="json")}
        except ValueError:
            return {"found": False, "product_id": str(product_id)}
        except InventoryAPIError:
            logger.warning("Inventory API product details request failed")
            return {"error": "Product details are temporarily unavailable."}

    @tool("check_stock", args_schema=CheckStockArgs)
    def check_stock(product_id: str | int, quantity: int | None = None) -> dict:
        """Check current inventory quantity for a product ID."""
        try:
            if inventory_client:
                product = inventory_client.get_product(str(product_id))
                if product is None:
                    return {"found": False, "product_id": str(product_id)}

                stock = product["quantity"]
                needed = quantity if quantity is not None else 1
                return {
                    "found": True,
                    "product_id": str(product["id"]),
                    "name": str(product.get("name", "Unknown product")),
                    "stock": stock,
                    "requested": quantity,
                    "available": stock >= needed,
                }

            check = service.check_stock(int(product_id), quantity)
            if check is None:
                return {"found": False, "product_id": product_id}
            return {"found": True, **check.model_dump(mode="json")}
        except ValueError:
            return {"found": False, "product_id": str(product_id)}
        except InventoryAPIError:
            logger.warning("Inventory API stock check failed")
            return {"error": "Stock information is temporarily unavailable."}

    tools = [search_products, get_product, check_stock]

    if inventory_client:

        @tool("list_products")
        def list_products() -> dict:
            """List all products from the Inventory Management System."""
            try:
                products = inventory_client.list_products()
                return {"count": len(products), "products": products}
            except InventoryAPIError:
                logger.warning("Inventory API product listing failed")
                return {"error": "The product catalogue is temporarily unavailable."}

        @tool("low_stock_products")
        def low_stock_products() -> dict:
            """List products currently reported as low stock."""
            try:
                products = inventory_client.list_low_stock_products()
                return {"count": len(products), "products": products}
            except InventoryAPIError:
                logger.warning("Inventory API low-stock lookup failed")
                return {"error": "Low-stock information is temporarily unavailable."}

        tools.extend([list_products, low_stock_products])

    return tools
