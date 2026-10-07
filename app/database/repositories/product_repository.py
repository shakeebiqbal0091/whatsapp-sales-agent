from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.database.models import Product

_CANDIDATE_CAP = 200


class ProductRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, product_id: int) -> Product | None:
        return self.session.get(Product, product_id)

    def search(self, terms: list[str], category: str | None = None) -> list[Product]:
        """Active products matching ANY term in name/description/category.

        `terms` must already be sanitised alphanumeric tokens (see SalesService), so LIKE
        wildcards cannot appear. Ranking happens in the service.
        """
        stmt = select(Product).where(Product.active.is_(True))
        if category:
            stmt = stmt.where(Product.category.ilike(f"%{category.strip()}%"))
        if terms:
            conditions = []
            for term in terms:
                like = f"%{term}%"
                conditions += [
                    Product.name.ilike(like),
                    Product.description.ilike(like),
                    Product.category.ilike(like),
                ]
            stmt = stmt.where(or_(*conditions))
        return list(self.session.scalars(stmt.order_by(Product.id).limit(_CANDIDATE_CAP)))
