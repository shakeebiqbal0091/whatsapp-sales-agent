# """Product/price/stock business logic. The database is the source of truth (CLAUDE.md §51)."""
# import re

# from sqlalchemy.orm import Session

# from app.database.models import Product
# from app.database.repositories.product_repository import ProductRepository
# from app.schemas.product import ProductOut, StockCheck

# _TOKEN = re.compile(r"[a-z0-9]+")
# _STOPWORDS = frozenset(
#     "a an and any are can do does for get got have i in is it me my need of on or please "
#     "product products sell show some something tell the there to want what with you your looking".split()
# )


# def _tokenize(query: str) -> list[str]:
#     terms: list[str] = []
#     for token in _TOKEN.findall(query.lower()):
#         if token in _STOPWORDS:
#             continue
#         if len(token) > 3 and token.endswith("s"):  # keyboards -> keyboard
#             token = token[:-1]
#         if token not in terms:
#             terms.append(token)
#     return terms


# class SalesService:
#     def __init__(self, session: Session, currency: str) -> None:
#         self.repo = ProductRepository(session)
#         self.currency = currency

#     def _to_out(self, product: Product) -> ProductOut:
#         return ProductOut(
#             id=product.id,
#             name=product.name,
#             description=product.description,
#             price=product.price,
#             currency=self.currency,
#             category=product.category,
#             stock_quantity=product.stock_quantity,
#             in_stock=product.stock_quantity > 0,
#         )

#     def search_products(
#         self, query: str, category: str | None = None, limit: int = 5
#     ) -> list[ProductOut]:
#         """Rank by term hits (name > category > description), then cheapest first.

#         A query made only of stopwords ("what products do you have?") lists the catalogue.
#         """
#         # Reject obvious SQL-injection-style input.
#         if re.search(
#             r"(--|;|/\*|\*/|\b(drop|alter|truncate|insert|delete|update|union|exec)\b)",
#             query,
#             flags=re.IGNORECASE,
#         ):
#             return []
#         terms = _tokenize(query)
#         candidates = self.repo.search(terms, category)

#         def score(p: Product) -> int:
#             name, cat, desc = p.name.lower(), p.category.lower(), p.description.lower()
#             return sum(3 * (t in name) + 2 * (t in cat) + (t in desc) for t in terms)

#         ranked = sorted(candidates, key=lambda p: (-score(p), p.price, p.id))
#         return [self._to_out(p) for p in ranked[:limit]]

#     def get_product(self, product_id: int) -> ProductOut | None:
#         product = self.repo.get(product_id)
#         return self._to_out(product) if product and product.active else None

#     def check_stock(self, product_id: int, quantity: int | None = None) -> StockCheck | None:
#         product = self.repo.get(product_id)
#         if product is None or not product.active:
#             return None
#         needed = quantity if quantity is not None else 1
#         return StockCheck(
#             product_id=product.id,
#             name=product.name,
#             stock=product.stock_quantity,
#             requested=quantity,
#             available=product.stock_quantity >= needed,
#         )



# ---------------------------------------Connected With Inventory Manageement System ------------------------------------------------------


"""Product, price and stock business logic.
When configured, the Inventory Management System API is the source of truth.
Otherwise, the local database is used for development and existing tests.
"""
import re
from decimal import Decimal
from typing import Any
from sqlalchemy.orm import Session
from app.config import get_settings
from app.database.models import Product
from app.database.repositories.product_repository import ProductRepository
from app.integrations.inventory_client import InventoryClient
from app.schemas.product import ProductOut, StockCheck

_TOKEN = re.compile(r"[a-z0-9]+")
_STOPWORDS = frozenset(
    "a an and any are can do does for get got have i in is it me my need of on or please "
    "product products sell show some something tell the there to want what with you your looking".split()
)

def _tokenize(query: str) -> list[str]:
    terms: list[str] = []
    for token in _TOKEN.findall(query.lower()):
        if token in _STOPWORDS:
            continue

        if len(token) > 3 and token.endswith("s"):
            token = token[:-1]

        if token not in terms:
            terms.append(token)

    return terms

class SalesService:
    def __init__(self, session: Session, currency: str) -> None:
        self.repo = ProductRepository(session)
        self.currency = currency
        settings = get_settings()
        self.inventory_client: InventoryClient | None = None

        if settings.inventory_api_url and settings.inventory_api_token:
            token = settings.inventory_api_token.get_secret_value()
            
            self.inventory_client = InventoryClient(
                base_url=settings.inventory_api_url,
                token=token,
                timeout=settings.inventory_api_timeout_seconds,
            )

    def _to_out(self, product: Product) -> ProductOut:
        """Convert a local database product into the shared output schema."""
        return ProductOut(
            id=str(product.id),
            name=product.name,
            description=product.description or "",
            price=product.price,
            currency=self.currency,
            category=product.category,
            stock_quantity=product.stock_quantity,
            in_stock=product.stock_quantity > 0,
        )

    def _inventory_to_out(self, product: dict[str, Any]) -> ProductOut:
        """Convert an Inventory API product into the shared output schema."""
        try:
            product_id = str(product["id"])
            name = str(product["name"])
            price = Decimal(str(product["price"]))
            quantity = int(product.get("quantity", 0))
        except (KeyError, TypeError, ValueError, ArithmeticError) as exc:
            raise ValueError(
                "Inventory API returned a product with missing or invalid fields."
            ) from exc

        if not product_id or not name or quantity < 0 or not price.is_finite():
            raise ValueError("Inventory API returned invalid product data.")

        return ProductOut(
            id=product_id,
            name=name,
            description=str(product.get("description") or ""),
            price=price,
            currency=self.currency,
            category=str(product.get("category") or "Uncategorized"),
            stock_quantity=quantity,
            in_stock=quantity > 0,
        )

    def _get_local_product(self, product_id: str | int) -> Product | None:
        """Look up a local product whose primary key is an integer."""
        try:
            numeric_id = int(product_id)
        except (TypeError, ValueError):
            return None

        if numeric_id < 1:
            return None

        return self.repo.get(numeric_id)

    def search_products(
        self, query: str, category: str | None = None, limit: int = 5
    ) -> list[ProductOut]:
        """Search real products, ranking name matches before category and description.

        Broad catalogue questions can return products even when the query contains
        only stopwords. If the Inventory API is configured, its data is used instead
        of the local product table.
        """
        if re.search(
            r"(--|;|/\*|\*/|\b(drop|alter|truncate|insert|delete|update|union|exec)\b)",
            query,
            flags=re.IGNORECASE,
        ):
            return []

        terms = _tokenize(query)

        if self.inventory_client is not None:
            inventory_products = self.inventory_client.list_products()
            candidates = [
                self._inventory_to_out(product)
                for product in inventory_products
            ]

            if category:
                category_term = category.strip().lower()
                candidates = [
                    product
                    for product in candidates
                    if category_term in product.category.lower()
                ]

            if terms:
                candidates = [
                    product
                    for product in candidates
                    if any(
                        term in product.name.lower()
                        or term in product.category.lower()
                        or term in product.description.lower()
                        for term in terms
                    )
                ]

            def inventory_score(product: ProductOut) -> int:
                name = product.name.lower()
                cat = product.category.lower()
                desc = product.description.lower()

                return sum(
                    3 * (term in name)
                    + 2 * (term in cat)
                    + (term in desc)
                    for term in terms
                )

            ranked = sorted(
                candidates,
                key=lambda product: (
                    -inventory_score(product),
                    product.price,
                    product.id,
                ),
            )
            return ranked[: max(0, limit)]

        # Existing local-database search path.
        candidates = self.repo.search(terms, category)

        def score(product: Product) -> int:
            name = product.name.lower()
            cat = product.category.lower()
            desc = product.description.lower()

            return sum(
                3 * (term in name)
                + 2 * (term in cat)
                + (term in desc)
                for term in terms
            )

        ranked = sorted(
            candidates,
            key=lambda product: (-score(product), product.price, product.id),
        )
        return [self._to_out(product) for product in ranked[: max(0, limit)]]

    def get_product(self, product_id: str | int) -> ProductOut | None:
        """Get a product by its Inventory API ID or local database ID."""
        if self.inventory_client is not None:
            product = self.inventory_client.get_product(str(product_id))
            return self._inventory_to_out(product) if product else None

        product = self._get_local_product(product_id)

        if product is None or not product.active:
            return None

        return self._to_out(product)

    def check_stock(
        self, product_id: str | int, quantity: int | None = None
    ) -> StockCheck | None:
        """Check current stock against an optional requested quantity."""
        product = self.get_product(product_id)

        if product is None:
            return None

        needed = quantity if quantity is not None else 1

        return StockCheck(
            product_id=product.id,
            name=product.name,
            stock=product.stock_quantity,
            requested=quantity,
            available=product.stock_quantity >= needed,
        )