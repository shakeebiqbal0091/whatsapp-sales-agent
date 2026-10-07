from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.models import Customer, Lead


class CustomerRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_by_phone(self, phone: str) -> Customer | None:
        return self.session.scalar(select(Customer).where(Customer.phone == phone))

    def add(self, phone: str, name: str | None = None) -> Customer:
        customer = Customer(phone=phone, name=name)
        self.session.add(customer)
        self.session.flush()
        return customer

    def add_lead(self, customer_id: int, conversation_id: int | None, interest: str) -> Lead:
        lead = Lead(customer_id=customer_id, conversation_id=conversation_id, interest=interest)
        self.session.add(lead)
        self.session.flush()
        return lead
