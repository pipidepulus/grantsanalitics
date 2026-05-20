import uuid
from datetime import datetime
from pydantic import BaseModel, field_validator


class ChatRequest(BaseModel):
    conversation_id: uuid.UUID | None = None
    user_id: uuid.UUID
    message: str
    project_id: uuid.UUID | None = None

    @field_validator("message")
    @classmethod
    def message_not_empty(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError("El mensaje no puede estar vacío.")
        if len(stripped) > 8000:
            raise ValueError("El mensaje no puede superar los 8 000 caracteres.")
        # Reject messages that are only control/non-printable characters
        printable_chars = sum(1 for c in stripped if c.isprintable())
        if printable_chars < len(stripped) * 0.5:
            raise ValueError("El mensaje contiene demasiados caracteres no imprimibles.")
        return stripped


class MessageResponse(BaseModel):
    id: uuid.UUID
    role: str
    content: str
    tool_calls: list[dict] | dict | None
    created_at: datetime

    model_config = {"from_attributes": True}


class ChatResponse(BaseModel):
    conversation_id: uuid.UUID
    message: MessageResponse
    project_update: dict | None = None
    cyrano_score: float | None = None
