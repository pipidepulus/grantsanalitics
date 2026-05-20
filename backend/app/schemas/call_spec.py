import uuid
from datetime import datetime
from pydantic import BaseModel


class CallSpecCreate(BaseModel):
    title: str
    source_url: str | None = None
    eligibility_criteria: str | None = None
    max_amount: str | None = None
    counterpart_required: str | None = None
    deadline: str | None = None
    raw_text: str | None = None


class CallSpecResponse(BaseModel):
    id: uuid.UUID
    title: str
    source_url: str | None
    extracted_requirements: dict | None
    eligibility_criteria: str | None
    max_amount: str | None
    counterpart_required: str | None
    deadline: str | None
    mandatory_sections: dict | None
    created_at: datetime

    model_config = {"from_attributes": True}
