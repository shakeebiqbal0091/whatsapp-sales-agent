"""Product tools. The LLM only ever sees structured results from the service layer."""
import logging

from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.services.sales_service import SalesService

logger = logging.getLogger(__name__)


class SearchProductsArgs(BaseModel):
    query: str = Field(min_length=1, max_length=200, description="Product name, keywords or type, e.g. 'wireless keyboard'.")
    category: str | None = Field(default=None, max_length=80, description="Optional category filter.")


class ProductIdArgs(BaseModel):
    product_id: int = Field(ge=1, description="Product id returned by search_products.")


class CheckStockArgs(BaseModel):
    product_id: int = Field(ge=1, description="Product id returned by search_products.")
    quantity: int | None = Field(default=None, ge=1, le=100_000, description="Units the customer wants, if stated.")


def build_product_tools(session: Session, currency: str) -> list[BaseTool]:
    service = SalesService(session, currency)

    @tool("search_products", args_schema=SearchProductsArgs)
    def search_products(query: str, category: str | None = None) -> dict:
        """Search the product catalogue by name, keywords or category.
        Returns up to 5 real active products with price and stock.
        For broad catalogue requests such as "What products do you have?",
        "What do you sell?", or "Show me your products", call this tool and
        present multiple products from the returned results when available.
        Never invent products or product details.
        """
        products = service.search_products(query, category)
        logger.info("tool search_products results=%d", len(products))
        result: dict = {"count": len(products), "products": [p.model_dump(mode="json") for p in products]}
        if not products:
            result["note"] = "No matching products found."
        return result

    @tool("get_product", args_schema=ProductIdArgs)
    def get_product(product_id: int) -> dict:
        """Get full details (description, price, category, availability) for one product id."""
        product = service.get_product(product_id)
        logger.info("tool get_product found=%s", product is not None)
        if product is None:
            return {"found": False, "product_id": product_id}
        return {"found": True, "product": product.model_dump(mode="json")}

    @tool("check_stock", args_schema=CheckStockArgs)
    def check_stock(product_id: int, quantity: int | None = None) -> dict:
        """Check real stock for a product id, optionally against a requested quantity."""
        check = service.check_stock(product_id, quantity)
        logger.info("tool check_stock found=%s", check is not None)
        if check is None:
            return {"found": False, "product_id": product_id}
        return {"found": True, **check.model_dump(mode="json")}

    return [search_products, get_product, check_stock]
