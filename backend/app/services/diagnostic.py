"""
Cyrano diagnostic scoring helpers.

Responsible for extracting and persisting the structured Cyrano evaluation
score produced by the AI agent.  Keeping this logic here — rather than inline
in the orchestrator — makes it independently testable and easy to evolve
(e.g., replacing regex fallback with a validation schema).

Score resolution priority
-------------------------
1. ``save_diagnostic_result`` tool call  → structured, authoritative.
2. Regex scan of the assistant's free text  → fallback when the structured
   tool was not called but ``run_diagnostic`` was.
3. ``None``  → no diagnostic was run in this turn.
"""

import json
import logging
import re
import uuid

from sqlalchemy.orm import Session

from app.models.enums import ProjectStatus
from app.models.project import Project

logger = logging.getLogger(__name__)


def extract_cyrano_score(content: str) -> float | None:
    """Scan free text for a numeric Cyrano score between 0 and 100."""
    patterns = [
        r"puntaje\s+cyrano\s*[:=]\s*(\d+(?:\.\d+)?)",
        r"puntaje\s*(?:total|final|ponderado)?\s*[:=]\s*(\d+(?:\.\d+)?)",
        r"score\s*[:=]\s*(\d+(?:\.\d+)?)",
        r"(\d+(?:\.\d+)?)\s*/\s*100",
        r"(\d+(?:\.\d+)?)\s*puntos",
    ]
    for pattern in patterns:
        match = re.search(pattern, content, re.IGNORECASE)
        if match:
            score = float(match.group(1))
            if 0 <= score <= 100:
                return score
    return None


def resolve_cyrano_score(
    tool_calls_log: list[dict], assistant_content: str
) -> float | None:
    """Resolve the Cyrano score from a completed agent turn.

    Prefers the structured ``save_diagnostic_result`` result; falls back to
    regex scanning the assistant's free text only when ``run_diagnostic`` was
    called but the structured tool was not invoked.
    """
    diag_result = next(
        (tc for tc in tool_calls_log if tc.get("tool") == "save_diagnostic_result"),
        None,
    )
    if diag_result:
        try:
            return float(json.loads(diag_result["result"])["score"])
        except (KeyError, ValueError, json.JSONDecodeError):
            logger.warning(
                "cyrano_score_parse_failed",
                extra={"raw_result": diag_result.get("result", "")[:200]},
            )
            return extract_cyrano_score(assistant_content)

    if any(tc.get("tool") == "run_diagnostic" for tc in tool_calls_log):
        return extract_cyrano_score(assistant_content)

    return None


def persist_cyrano_score(
    db: Session, project_id: uuid.UUID, cyrano_score: float
) -> dict | None:
    """Write ``cyrano_score`` to the project row and return an update dict.

    Also transitions ``project.status`` automatically:
    - score >= 95.01 → ``validated`` (unless already exported)
    - score < 95.01 and status is ``draft`` → ``in_progress``

    Returns ``None`` if the project is not found or the score is ``None``.
    """
    if cyrano_score is None:
        return None
    project = db.query(Project).filter(Project.id == project_id).first()
    if project is None:
        return None
    project.cyrano_score = cyrano_score

    if cyrano_score >= 95.01 and project.status not in (
        ProjectStatus.validated, ProjectStatus.exported
    ):
        project.status = ProjectStatus.validated
    elif cyrano_score < 95.01 and project.status == ProjectStatus.draft:
        project.status = ProjectStatus.in_progress

    db.commit()
    return {"cyrano_score": cyrano_score, "status": project.status}
