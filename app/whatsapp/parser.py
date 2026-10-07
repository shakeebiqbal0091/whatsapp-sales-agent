"""Parse Meta WhatsApp Cloud API webhook payloads into plain messages. Never trusts raw input."""
import logging

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.schemas.customer import normalize_phone

logger = logging.getLogger(__name__)

MAX_TEXT_CHARS = 2000  # same cap as /chat


class IncomingMessage(BaseModel):
    message_id: str
    phone: str  # normalised "+<digits>"
    text: str


class _Text(BaseModel):
    body: str


class _Message(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    sender: str = Field(alias="from")
    type: str
    text: _Text | None = None


class _Value(BaseModel):
    messages: list[_Message] = []  # delivery/read "statuses" are not modelled, so they are ignored


class _Change(BaseModel):
    value: _Value = _Value()


class _Entry(BaseModel):
    changes: list[_Change] = []


class _Payload(BaseModel):
    entry: list[_Entry] = []


def parse_incoming(payload: object) -> list[IncomingMessage]:
    """Return the customer text messages in a webhook payload; everything else is dropped."""
    try:
        parsed = _Payload.model_validate(payload)
    except ValidationError:
        logger.warning("webhook payload failed validation; ignoring")
        return []

    messages: list[IncomingMessage] = []
    for entry in parsed.entry:
        for change in entry.changes:
            for raw in change.value.messages:
                if raw.type != "text" or raw.text is None:
                    logger.info("ignoring unsupported message type=%s id=%s", raw.type, raw.id)
                    continue
                body = raw.text.body.strip()[:MAX_TEXT_CHARS]
                if not body:
                    continue
                try:
                    phone = normalize_phone(raw.sender)
                except ValueError:
                    logger.warning("ignoring message with invalid sender id=%s", raw.id)
                    continue
                messages.append(IncomingMessage(message_id=raw.id, phone=phone, text=body))
    return messages
