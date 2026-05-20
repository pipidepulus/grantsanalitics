from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # Database
    DATABASE_URL: str = "postgresql://pipidepulus:pipidepulus@localhost:5432/pipidepulus_db"

    # OpenAI
    OPENAI_API_KEY: str = ""
    OPENAI_MODEL: str = "gpt-5-mini"
    OPENAI_VECTOR_STORE_ID: str = ""  # Knowledge base (Metodología Propulsa)
    OPENAI_PROJECTS_VECTOR_STORE_ID: str = ""  # Projects & call documents

    # App
    APP_NAME: str = "Pipidepulus AI"
    DEBUG: bool = False
    CORS_ORIGINS: list[str] = ["http://localhost:3000"]

    # Cyrano validation threshold
    CYRANO_THRESHOLD: float = 95.01

    # Storage
    STORAGE_BACKEND: str = "local"           # "local" | "s3"
    STORAGE_LOCAL_PATH: str = "/var/pipidepulus/storage"
    STORAGE_S3_BUCKET: str = ""
    STORAGE_S3_ENDPOINT_URL: str = ""        # Override for MinIO / R2 / etc.

    model_config = {"env_file": "../.env", "env_file_encoding": "utf-8"}


@lru_cache
def get_settings() -> Settings:
    return Settings()
