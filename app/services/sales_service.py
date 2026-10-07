"""Product/price/stock business logic. The database is the source of truth (CLAUDE.md §51)."""
import re

from sqlalchemy.orm import Session

from app.database.models import Product
from app.database.repositories.product_repository import ProductRepository
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
        if len(token) > 3 and token.endswith("s"):  # keyboards -> keyboard
            token = token[:-1]
        if token not in terms:
            terms.append(token)
    return terms


class SalesService:
    def __init__(self, session: Session, currency: str) -> None:
        self.repo = ProductRepository(session)
        self.currency = currency

    def _to_out(self, product: Product) -> ProductOut:
        return ProductOut(
            id=product.id,
            name=product.name,
            description=product.description,
            price=product.price,
            currency=self.currency,
            category=product.category,
            stock_quantity=product.stock_quantity,
            in_stock=product.stock_quantity > 0,
        )

    def search_products(
        self, query: str, category: str | None = None, limit: int = 5
    ) -> list[ProductOut]:
        """Rank by term hits (name > category > description), then cheapest first.

        A query made only of stopwords ("what products do you have?") lists the catalogue.
        """
        terms = _tokenize(query)
        candidates = self.repo.search(terms, category)

        def score(p: Product) -> int:
            name, cat, desc = p.name.lower(), p.category.lower(), p.description.lower()
            return sum(3 * (t in name) + 2 * (t in cat) + (t in desc) for t in terms)

        ranked = sorted(candidates, key=lambda p: (-score(p), p.price, p.id))
        return [self._to_out(p) for p in ranked[:limit]]

    def get_product(self, product_id: int) -> ProductOut | None:
        product = self.repo.get(product_id)
        return self._to_out(product) if product and product.active else None

    def check_stock(self, product_id: int, quantity: int | None = None) -> StockCheck | None:
        product = self.repo.get(product_id)
        if product is None or not product.active:
            return None
        needed = quantity if quantity is not None else 1
        return StockCheck(
            product_id=product.id,
            name=product.name,
            stock=product.stock_quantity,
            requested=quantity,
            available=product.stock_quantity >= needed,
        )
