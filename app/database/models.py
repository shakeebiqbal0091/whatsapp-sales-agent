"""SQLAlchemy models. Entities follow CLAUDE.md §16 (+ a minimal Lead for create_lead)."""
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )


class Customer(TimestampMixin, Base):
    __tablename__ = "customers"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str | None] = mapped_column(String(120))
    phone: Mapped[str] = mapped_column(String(20), unique=True, index=True)  # E.164, "+<digits>"


class Product(TimestampMixin, Base):
    __tablename__ = "products"
    __table_args__ = (CheckConstraint("stock_quantity >= 0", name="ck_products_stock_nonneg"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True)
    description: Mapped[str] = mapped_column(Text, default="")
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    stock_quantity: Mapped[int] = mapped_column(Integer, default=0)
    category: Mapped[str] = mapped_column(String(80), index=True)
    active: Mapped[bool] = mapped_column(default=True)


class Conversation(TimestampMixin, Base):
    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), index=True)
    status: Mapped[str] = mapped_column(String(20), default="open")  # open | escalated | closed
    escalation_reason: Mapped[str | None] = mapped_column(String(500))

    messages: Mapped[list["Message"]] = relationship(
        back_populates="conversation", order_by="Message.id"
    )


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id"), index=True)
    role: Mapped[str] = mapped_column(String(20))  # user | assistant | system | tool
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    conversation: Mapped[Conversation] = relationship(back_populates="messages")


class Lead(TimestampMixin, Base):
    __tablename__ = "leads"

    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), index=True)
    conversation_id: Mapped[int | None] = mapped_column(ForeignKey("conversations.id"))
    interest: Mapped[str] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(20), default="new")
