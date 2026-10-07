"""Idempotency table for webhook events. Kept in its own module so models.py stays untouched.

Importing this module registers the table on the shared Base.metadata."""
from datetime import datetime

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database.models import Base, _utcnow


class ProcessedEvent(Base):
    """WhatsApp message ids already claimed for processing (Meta may deliver a webhook more than once)."""

    __tablename__ = "processed_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[str] = mapped_column(String(128), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
