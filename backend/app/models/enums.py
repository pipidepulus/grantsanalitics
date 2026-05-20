"""Domain-level enums shared across models, schemas, and services.

Using plain string-backed enums keeps PostgreSQL columns as VARCHAR (no
migration cost when adding a new value) while enforcing a closed contract
at the Python layer.
"""

from enum import Enum


class ProjectStatus(str, Enum):
    draft = "draft"
    in_progress = "in_progress"
    validated = "validated"
    exported = "exported"


class ProjectLanguage(str, Enum):
    es = "es"
    en = "en"
