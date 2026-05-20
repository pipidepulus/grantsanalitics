import uuid
from datetime import datetime
from pydantic import BaseModel, EmailStr


class UserCreate(BaseModel):
    name: str
    email: str
    organization: str | None = None
    sector: str | None = None
    territory: str | None = None


class UserUpdate(BaseModel):
    name: str | None = None
    organization: str | None = None
    sector: str | None = None
    territory: str | None = None
    preferences: dict | None = None


class UserResponse(BaseModel):
    id: uuid.UUID
    name: str
    email: str
    organization: str | None
    sector: str | None
    territory: str | None
    preferences: dict | None
    created_at: datetime

    model_config = {"from_attributes": True}
