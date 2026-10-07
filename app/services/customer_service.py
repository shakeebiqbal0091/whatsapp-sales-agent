import logging

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database.models import Customer, Lead
from app.database.repositories.customer_repository import CustomerRepository

logger = logging.getLogger(__name__)


class CustomerService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.repo = CustomerRepository(session)

    def identify(self, phone: str) -> Customer:
        """Get-or-create by phone. Safe against two simultaneous first messages (unique constraint)."""
        customer = self.repo.get_by_phone(phone)
        if customer:
            return customer
        try:
            with self.session.begin_nested():
                customer = self.repo.add(phone)
            logger.info("customer created customer_id=%s", customer.id)
            return customer
        except IntegrityError:
            existing = self.repo.get_by_phone(phone)
            if existing is None:
                raise
            return existing

    def create_lead(self, customer_id: int, conversation_id: int | None, interest: str) -> Lead:
        interest = interest.strip()
        if not interest:
            raise ValueError("interest must not be empty")
        lead = self.repo.add_lead(customer_id, conversation_id, interest[:500])
        logger.info("lead created lead_id=%s customer_id=%s", lead.id, customer_id)
        return lead
