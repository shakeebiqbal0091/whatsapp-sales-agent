"""Parse Meta WhatsApp Cloud API webhook payloads into validated messages."""
import logging

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.schemas.customer import normalize_phone

logger = logging.getLogger(__name__)

MAX_TEXT_CHARS = 2000


class IncomingMessage(BaseModel):
    message_id: str
    phone: str  # normalised "+<digits>" for parsed webhook messages
    text: str | None = None
    message_type: str = "text"
    media_id: str | None = None
    mime_type: str | None = None


class _Text(BaseModel):
    body: str


class _Audio(BaseModel):
    id: str
    mime_type: str | None = None


class _Message(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    sender: str = Field(alias="from")
    type: str
    text: _Text | None = None
    audio: _Audio | None = None


class _Value(BaseModel):
    messages: list[_Message] = []


class _Change(BaseModel):
    value: _Value = _Value()


class _Entry(BaseModel):
    changes: list[_Change] = []


class _Payload(BaseModel):
    entry: list[_Entry] = []


def parse_incoming(payload: object) -> list[IncomingMessage]:
    """Return supported text/audio messages; ignore statuses and other types."""
    try:
        parsed = _Payload.model_validate(payload)
    except ValidationError:
        logger.warning("webhook payload failed validation; ignoring")
        return []

    messages: list[IncomingMessage] = []
    for entry in parsed.entry:
        for change in entry.changes:
            for raw in change.value.messages:
                try:
                    phone = normalize_phone(raw.sender)
                except ValueError:
                    logger.warning("ignoring message with invalid sender id=%s", raw.id)
                    continue

                if raw.type == "text" and raw.text is not None:
                    body = raw.text.body.strip()[:MAX_TEXT_CHARS]
                    if body:
                        messages.append(
                            IncomingMessage(
                                message_id=raw.id,
                                phone=phone,
                                text=body,
                                message_type="text",
                            )
                        )
                    continue

                if raw.type == "audio" and raw.audio is not None and raw.audio.id.strip():
                    messages.append(
                        IncomingMessage(
                            message_id=raw.id,
                            phone=phone,
                            message_type="audio",
                            media_id=raw.audio.id,
                            mime_type=raw.audio.mime_type,
                        )
                    )
                    continue

                logger.info("ignoring unsupported or incomplete message type=%s id=%s", raw.type, raw.id)
    return messages
