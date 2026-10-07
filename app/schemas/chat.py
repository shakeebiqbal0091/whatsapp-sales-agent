from pydantic import BaseModel, Field, field_validator

from app.schemas.customer import normalize_phone


class ChatRequest(BaseModel):
    phone: str
    message: str = Field(min_length=1, max_length=2000)

    @field_validator("phone")
    @classmethod
    def _normalize_phone(cls, value: str) -> str:
        return normalize_phone(value)

    @field_validator("message")
    @classmethod
    def _strip_message(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("message must not be blank")
        return value


class ChatResponse(BaseModel):
    response: str
