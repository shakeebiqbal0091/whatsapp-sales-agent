from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database.event_models import ProcessedEvent


class EventRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def claim(self, event_id: str) -> bool:
        """Atomically record an event id. True = first time seen (caller should process it)."""
        self.session.add(ProcessedEvent(event_id=event_id))
        try:
            self.session.commit()
        except IntegrityError:
            self.session.rollback()
            return False
        return True
