"""Create tables and seed products: `python -m scripts.seed_database` (run from the project root)."""
from app.database.connection import get_engine, get_session_factory
from app.database.models import Base
from scripts.seed_products import seed_products


def main() -> None:
    Base.metadata.create_all(get_engine())  # v0.1: no migrations yet (Alembic is a v0.9 item)
    with get_session_factory()() as session:
        created = seed_products(session)
    print(f"Tables ready. Products created: {created}")


if __name__ == "__main__":
    main()
