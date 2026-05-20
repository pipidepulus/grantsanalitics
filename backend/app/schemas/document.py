import uuid
from datetime import datetime
from pydantic import BaseModel


class GeneratedDocResponse(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    filename: str
    version_number: int
    created_at: datetime

    model_config = {"from_attributes": True}


class UploadedDocumentResponse(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    user_id: uuid.UUID
    filename: str
    original_filename: str
    file_size: int
    content_type: str
    vector_store_file_id: str | None
    indexing_status: str
    created_at: datetime

    model_config = {"from_attributes": True}
