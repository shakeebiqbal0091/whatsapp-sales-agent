"""Create ALL tables, including processed_events: `python -m scripts.create_tables`.

Why this exists: scripts/seed_database.py never imports app.database.event_models, so on a fresh database it
creates 5 tables and the webhook's duplicate check then fails on every message. Run this before seeding.
Safe to re-run: create_all only creates missing tables and never alters existing ones."""
from sqlalchemy import Engine, inspect

from app.database import event_models  # noqa: F401  (registers processed_events on Base.metadata)
from app.database.models import Base


def create_all_tables(engine: Engine) -> list[str]:
    Base.metadata.create_all(engine)
    return sorted(inspect(engine).get_table_names())


def main() -> None:
    from app.database.connection import get_engine

    print("Tables ready:", ", ".join(create_all_tables(get_engine())))


if __name__ == "__main__":
    main()
