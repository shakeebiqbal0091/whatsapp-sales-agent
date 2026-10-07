from decimal import Decimal

from pydantic import BaseModel


class ProductOut(BaseModel):
    id: int
    name: str
    description: str
    price: Decimal
    currency: str
    category: str
    stock_quantity: int
    in_stock: bool


class StockCheck(BaseModel):
    product_id: int
    name: str
    stock: int
    requested: int | None
    available: bool  # True if stock covers `requested` (or stock > 0 when no quantity given)
