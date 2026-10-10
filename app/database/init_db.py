"""Initialize the V0.1 database tables."""
from app.database.connection import get_engine
from app.database.models import Base
from app.database import event_models  # noqa: F401


def main() -> None:
    Base.metadata.create_all(bind=get_engine())
    print("Database tables are ready.")


if __name__ == "__main__":
    main()
